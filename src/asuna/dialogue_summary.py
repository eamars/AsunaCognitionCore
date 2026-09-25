"""Low-priority, source-bound summaries for new dialogue batches (DM and authorized groups).

什么时候动手在 summary_trigger（触发点从场景自己真实出现过的节奏里算），
「这段盖了谁、谁更正了谁」在 summary_attribution（全部由程序从真实行算出来）；
本模块只负责这一段链路：选批 → 判断 → 整理 → 落库 → 标来源 → 回标更正。
不新增集合、不新增状态服务、不多调一次模型、不碰 QQ 平台。

崩溃恢复仍按原口径：摘要已存但来源没标时，先补标记再选新批，同一条原文不会被讲两遍。
"""
from __future__ import annotations

import json
import threading
import time

from . import summary_attribution, summary_trigger
from .evidence import canonical, sha
from .state import Conflict, now


class DialogueSummarizer:
    WINDOW_ROWS = 8              # 一次送进模型的真实行数上限：批不可能比窗口更大（结构性）
    ROW_CHAR_CAP = 4000          # 单行送进模型的字符上限，超了显式标 excerpt_truncated
    SCENE_KINDS = ('dm', 'group')
    RETRY_BASE_SECONDS = 30.0    # 失败退避：错误处理，不是触发条件
    RETRY_CAP_SECONDS = 900.0
    SYSTEM = ('你是小满对话记录的后台整理步骤，只整理提供的当前场景原文（私聊或已授权群）。'
              '区分每个人说的话、小满已经实际送达的话和各自的看法；每条转述都用给定的 author '
              '标明是谁说的，不要把一个人的偏好或决定写成另一个人的，也不要把群里的旁听当成谁'
              '对谁说的。这一批里有人更正自己或更正别人时，写清谁更正了什么、更正成什么，被推翻'
              '的旧说法只当历史保留。遇到来源节选不全或主体不明时明确保留不确定性。只输出简短'
              '自然语言摘要，不调用工具，也不编造来源编号。')

    def __init__(self, store, evidence, lane, scenes, can_run=lambda: True, clock=None):
        self.store, self.evidence, self.lane = store, evidence, lane
        self.scene_ids = [scenes] if isinstance(scenes, str) else [s for s in scenes if s]
        self.scene_id = self.scene_ids[0] if self.scene_ids else None   # 兼容旧接线
        self.can_run = can_run
        # 判断“现在安静了多久”用的钟：默认墙上时钟，检查里可注入固定时刻。
        self.clock = clock or (lambda: time.time())
        self.paused = threading.Event()
        self.next_attempt = {}      # 每场景的失败退避截止点（monotonic）
        self.failures = {}          # 每场景连续失败次数
        self.profiles = {}          # 每场景最近一次实测到的节奏画像
        self.held = {}              # 已经报过的等待理由（避免每 2 秒刷同一条证据）

    def initialize(self):
        """Do not bulk-summarize pre-feature history on host startup."""
        for scene_id in self.scene_ids:
            scene = self.store.db.scenes.find_one({'_id': scene_id})
            if not scene or scene.get('kind') not in self.SCENE_KINDS:
                continue
            if 'summary_start_seq' not in scene:
                self.store.put('scenes', {**scene, 'summary_start_seq': scene.get('sequence', 0)},
                               expected=scene['revision'], stream='summary:init:' + scene_id)

    def _pending(self, scene):
        query = {'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
                 'scene_seq': {'$gt': scene['summary_start_seq']},
                 'summary_batch_id': {'$exists': False},
                 '$or': [{'direction': 'inbound'},
                         {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]}
        rows = list(self.store.db.messages.find(query).sort('scene_seq', 1).limit(self.WINDOW_ROWS))
        # A saved summary may precede a crash during source marking. Complete
        # those markings before selecting a new batch, so no source is retold.
        for row in rows:
            prior = self.store.db.memory_units.find_one({
                'kind': 'dialogue_summary', 'scope_key': scene['scope_key'],
                'policy_epoch': scene['policy_epoch'], 'status': 'active',
                'source_event_ids': row['_id']}, {'_id': 1})
            if prior:
                self.store.put('messages', {**row, 'summary_batch_id': prior['_id']},
                               expected=row['revision'], stream='summary:recover:' + scene['_id'])
        if any(self.store.db.memory_units.find_one({
                'kind': 'dialogue_summary', 'scope_key': scene['scope_key'],
                'policy_epoch': scene['policy_epoch'], 'status': 'active',
                'source_event_ids': row['_id']}, {'_id': 1}) for row in rows):
            rows = list(self.store.db.messages.find(query).sort('scene_seq', 1).limit(self.WINDOW_ROWS))
        return rows

    def _labels(self, rows):
        """给多说话人的批次带上显示名：模型按名字顺句子，程序仍按 person_id 认归属。"""
        if len({row.get('author') for row in rows}) < 2:
            return {}
        names = {}
        for row in rows:
            author = row.get('author')
            if not author or author in names:
                continue
            identity = self.store.db.identities.find_one({'_id': author}, {'display_name': 1}) or {}
            names[author] = identity.get('display_name') or author
        # 同名不合并人物：显示名撞车时把 person_id 一起给模型，否则两个人在转述里会长成一个。
        shared = {name for name in names.values() if list(names.values()).count(name) > 1}
        return {author: (name + '（' + author + '）' if name in shared else name)
                for author, name in names.items()}

    def _hold(self, scene_id, decision):
        note = (decision['pending_rows'], decision.get('hold'), decision.get('pending_age') is None)
        if self.held.get(scene_id) == note:
            return
        self.held[scene_id] = note
        self.evidence.record('summary.hold', {'scene_id': scene_id, 'decision': decision})

    def tick(self, scene_id=None):
        """索引线程轮转到哪个场景，就只判断那个场景。"""
        scene_id = scene_id or self.scene_id
        if scene_id is None or scene_id not in self.scene_ids:
            return None
        if self.paused.is_set() or time.monotonic() < self.next_attempt.get(scene_id, 0.0) \
                or not self.can_run():
            return None
        scene = self.store.db.scenes.find_one({'_id': scene_id})
        if not scene or scene.get('kind') not in self.SCENE_KINDS or 'summary_start_seq' not in scene:
            return None
        rows = self._pending(scene)
        if not rows:
            return None
        moment = self.clock()
        profile = summary_trigger.observe(self.store, scene, now_ts=moment)
        self.profiles[scene_id] = profile
        decision = summary_trigger.decide(profile, rows,
                                          pooled_prior=summary_trigger.pooled(self.profiles, exclude=scene_id),
                                          now_ts=moment, window_rows=self.WINDOW_ROWS,
                                          row_char_cap=self.ROW_CHAR_CAP)
        if not decision['fire']:
            self._hold(scene_id, decision)
            return None
        self.held.pop(scene_id, None)
        if not self.lane.lock.acquire(blocking=False):
            return None
        try:
            if self.paused.is_set() or not self.can_run():
                return None
            return self._summarize(scene, rows, decision)
        except Exception:
            # 失败留在本场景自己的退避里（指数、有上限），不拖慢别的场景，也不改触发口径。
            attempts = self.failures[scene_id] = self.failures.get(scene_id, 0) + 1
            self.next_attempt[scene_id] = time.monotonic() + min(
                self.RETRY_BASE_SECONDS * (2 ** (attempts - 1)), self.RETRY_CAP_SECONDS)
            raise
        finally:
            self.lane.lock.release()

    def _summarize(self, scene, rows, decision):
        scene_id = scene['_id']
        labels = self._labels(rows)
        window = [{'index': index + 1, 'author': row['author'],
                   'speaker_label': labels.get(row['author'], row['author']),
                   'direction': row['direction'], 'text': row['text'][:self.ROW_CHAR_CAP],
                   'excerpt_truncated': len(row['text']) > self.ROW_CHAR_CAP}
                  for index, row in enumerate(rows)]
        source_ids = [row['_id'] for row in rows]
        key = 'summary-' + sha(canonical([scene_id, scene['policy_epoch'], source_ids]))
        saved = self.store.db.memory_units.find_one({'_id': key})
        attribution = summary_attribution.attribute(self.store, scene, rows)
        if not saved:
            prompt = ('请总结这一小段已确认交流；窗口与来源由程序保存，不需复制 ID。'
                      'attribution 是程序从这些行算出来的归属事实，与它冲突就以它为准。\n'
                      + json.dumps({'window': window, 'attribution': attribution}, ensure_ascii=False))
            operation = key
            receipt = self.store.db.lane_receipts.find_one({'_id': operation})
            attempt = 0
            # A durably completed but interrupted/incomplete native turn is
            # known not to contain a usable summary. DSH replays DONE operations,
            # so use a fresh operation only for that explicit terminal result.
            # Unknown delivery still reuses the original idempotency key.
            while receipt and not (
                    receipt.get('result', {}).get('finish_reason') == 'stop'
                    and str(receipt.get('result', {}).get('content') or '').strip()):
                attempt += 1
                operation = key + ':retry-' + str(attempt)
                receipt = self.store.db.lane_receipts.find_one({'_id': operation})
            result = self.lane.generate('dialogue-summary:' + scene_id + ':' + str(scene['policy_epoch']),
                                        operation, 'dialogue-summary', prompt, self.SYSTEM,
                                        scope_key=scene['scope_key'], policy_epoch=scene['policy_epoch'])
            if result.finish_reason != 'stop' or not result.content.strip():
                raise RuntimeError('DIALOGUE_SUMMARY_INCOMPLETE: ' + result.finish_reason)
            saved = self.store.put('memory_units', {
                '_id': key, 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'],
                'character_id': 'xiaoman', 'kind': 'dialogue_summary',
                'epistemic_type': 'derived_summary', 'body_markdown': result.content.strip(),
                'source_event_ids': source_ids, 'depends_on': source_ids,
                'scene_id': scene_id, 'source_window': [rows[0]['scene_seq'], rows[-1]['scene_seq']],
                'participants': attribution['participants'],
                'source_by_speaker': attribution['source_by_speaker'],
                'attribution': {'multi_speaker': attribution['multi_speaker'],
                                'speakers': attribution['speakers'],
                                'corrections': attribution['corrections']},
                'trigger': {field: decision[field] for field in
                            ('signals', 'quiet_after', 'quiet_source', 'burst_rows', 'silence',
                             'pending_age', 'pending_rows', 'samples')},
                'creator_model': self.lane.model['model'], 'generated_at': now(),
                'status': 'active', 'embedding_status': 'PENDING'}, stream=key)
            self.evidence.record('summary.saved', {'scene_id': scene_id, 'summary_id': key,
                'source_ids': source_ids, 'trigger': decision, 'participants': attribution['participants'],
                'corrections': len(attribution['corrections']), 'request_refs': result.request_refs})
        for row in rows:
            current = self.store.db.messages.find_one({'_id': row['_id']})
            if current.get('summary_batch_id') == key:
                continue
            if current.get('summary_batch_id'):
                raise Conflict('SUMMARY_SOURCE_ALREADY_PROCESSED')
            self.store.put('messages', {**current, 'summary_batch_id': key},
                           expected=current['revision'], stream=key)
        corrected = summary_attribution.annotate_corrected(self.store, scene,
                                                           attribution['corrections'], key)
        if corrected:
            self.evidence.record('summary.corrected', {'scene_id': scene_id, 'summary_id': key,
                                                       'applied': corrected})
        self.failures[scene_id] = 0
        return saved
