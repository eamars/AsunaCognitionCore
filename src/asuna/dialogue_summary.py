"""Low-priority, source-bound summaries for new personal dialogue batches."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time

from .evidence import canonical, sha
from .state import Conflict, now


class DialogueSummarizer:
    def __init__(self, store, evidence, lane, scene_id, can_run=lambda: True):
        self.store, self.evidence, self.lane = store, evidence, lane
        self.scene_id, self.can_run = scene_id, can_run
        self.next_attempt = 0.0
        self.paused = threading.Event()

    def initialize(self):
        """Do not bulk-summarize pre-feature history on host startup."""
        scene = self.store.db.scenes.find_one({'_id': self.scene_id})
        if not scene or scene['kind'] != 'dm':
            return
        if 'summary_start_seq' not in scene:
            self.store.put('scenes', {**scene, 'summary_start_seq': scene.get('sequence', 0)},
                           expected=scene['revision'], stream='summary:init:' + self.scene_id)

    def _pending(self, scene):
        query = {'scene_id': self.scene_id, 'policy_epoch': scene['policy_epoch'],
                 'scene_seq': {'$gt': scene['summary_start_seq']},
                 'summary_batch_id': {'$exists': False},
                 '$or': [{'direction': 'inbound'},
                         {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]}
        rows = list(self.store.db.messages.find(query).sort('scene_seq', 1).limit(8))
        # A saved summary may precede a crash during source marking. Complete
        # those markings before selecting a new batch, so no source is retold.
        for row in rows:
            prior = self.store.db.memory_units.find_one({
                'kind': 'dialogue_summary', 'scope_key': scene['scope_key'],
                'policy_epoch': scene['policy_epoch'], 'status': 'active',
                'source_event_ids': row['_id']}, {'_id': 1})
            if prior:
                self.store.put('messages', {**row, 'summary_batch_id': prior['_id']},
                               expected=row['revision'], stream='summary:recover:' + self.scene_id)
        if any(self.store.db.memory_units.find_one({
                'kind': 'dialogue_summary', 'scope_key': scene['scope_key'],
                'policy_epoch': scene['policy_epoch'], 'status': 'active',
                'source_event_ids': row['_id']}, {'_id': 1}) for row in rows):
            rows = list(self.store.db.messages.find(query).sort('scene_seq', 1).limit(8))
        return rows

    @staticmethod
    def _quiet(rows):
        timestamps = [row.get('received_at') or row.get('receipt_at') for row in rows]
        if not timestamps or not timestamps[0]:
            return False
        try:
            return (datetime.now(timezone.utc) -
                    datetime.fromisoformat(timestamps[0])).total_seconds() >= 120
        except ValueError:
            return False

    def tick(self):
        if self.paused.is_set() or time.monotonic() < self.next_attempt or not self.can_run():
            return None
        scene = self.store.db.scenes.find_one({'_id': self.scene_id})
        if not scene or scene['kind'] != 'dm' or 'summary_start_seq' not in scene:
            return None
        rows = self._pending(scene)
        if len(rows) < 4 and not (len(rows) >= 2 and self._quiet(rows)):
            return None
        if not self.lane.lock.acquire(blocking=False):
            return None
        try:
            if self.paused.is_set() or not self.can_run():
                return None
            # Bounded input: original messages stay intact in Mongo; the model
            # is told explicitly when a displayed source excerpt is shortened.
            window = [{'index': i + 1, 'author': row['author'],
                       'direction': row['direction'], 'text': row['text'][:4000],
                       'excerpt_truncated': len(row['text']) > 4000}
                      for i, row in enumerate(rows)]
            source_ids = [row['_id'] for row in rows]
            key = 'summary-' + sha(canonical([self.scene_id, scene['policy_epoch'], source_ids]))
            saved = self.store.db.memory_units.find_one({'_id': key})
            if not saved:
                system = ('你是小满对话记录的后台整理步骤，只整理提供的当前私聊原文。'
                          '区分用户说的话、小满已经实际送达的话和各自的看法；不要把草稿、工具目标、推测或一人的偏好写成另一人的事实。'
                          '遇到来源节选不全或主体不明时明确保留不确定性。只输出简短自然语言摘要，不调用工具，也不编造来源编号。')
                prompt = '请总结这一小段已确认交流；窗口与来源由程序保存，不需复制 ID。\n' + json.dumps(window, ensure_ascii=False)
                result = self.lane.generate('dialogue-summary:' + self.scene_id + ':' + str(scene['policy_epoch']),
                                            key, 'dialogue-summary', prompt, system,
                                            scope_key=scene['scope_key'], policy_epoch=scene['policy_epoch'])
                if result.finish_reason != 'stop' or not result.content.strip():
                    raise RuntimeError('DIALOGUE_SUMMARY_INCOMPLETE: ' + result.finish_reason)
                saved = self.store.put('memory_units', {
                    '_id': key, 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                    'character_id': 'xiaoman', 'kind': 'dialogue_summary',
                    'epistemic_type': 'derived_summary', 'body_markdown': result.content.strip(),
                    'source_event_ids': source_ids, 'depends_on': source_ids,
                    'scene_id': self.scene_id, 'source_window': [rows[0]['scene_seq'], rows[-1]['scene_seq']],
                    'creator_model': self.lane.model['model'], 'generated_at': now(),
                    'status': 'active', 'embedding_status': 'PENDING'}, stream=key)
                self.evidence.record('summary.saved', {'scene_id': self.scene_id,
                    'summary_id': key, 'source_ids': source_ids, 'request_refs': result.request_refs})
            for row in rows:
                current = self.store.db.messages.find_one({'_id': row['_id']})
                if current.get('summary_batch_id') == key:
                    continue
                if current.get('summary_batch_id'):
                    raise Conflict('SUMMARY_SOURCE_ALREADY_PROCESSED')
                self.store.put('messages', {**current, 'summary_batch_id': key},
                               expected=current['revision'], stream=key)
            self.next_attempt = time.monotonic() + 60
            return saved
        finally:
            self.lane.lock.release()
