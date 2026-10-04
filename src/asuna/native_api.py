"""Bounded, read-only projections for native DSH's Asuna memory tab.

The native session is the authority boundary, never a scene supplied by a UI.
Lists carry excerpts; full bodies and authorized sources are read on demand.
"""
from datetime import datetime
import re

from .config import ago, character_id
from .state import Denied
from . import channel_kinds, scene_links
from .ingress import NOT_CORE_NOTICE
from .native_cognition import CognitionView
from .peer_context import speaker_name

VISIBILITY_LABELS = {'public': '公开', 'owner_private': '仅主人可见'}
INJECT_LABELS = {'always': '每轮都用', 'on_demand': '相关时才用', 'never': '不放进对话'}
DOCUMENT_KINDS = {'persona': '人格设定', 'voice': '说话方式', 'ledger': '承诺与挂账', 'dossier': '人物档案', 'working': '工作笔记'}


# When an empty entry gets written, so an empty row explains itself.
EMPTY_HEAD = {'self': '她只在每天一次的内部自省时间里决定要不要写下或改写。',
              'relation': '她在对话中觉得对这个人的理解有了变化时才会写下。'}


# Emotion in words. val is how good or bad she feels (−100…100), arl how stirred up (0…100).
AMENDMENT_WORDS = {'close': '已了结', 'void': '作废（前提不成立）', 'fix_ts': '更正时间', 'fix_kind': '更正种类'}


def kind_label(model, kind):
    return (model.get('kinds', {}).get(kind) or {}).get('label') or kind or '未分类'


def mood_line(view):
    line = f"{view['label'] or '平静'} · 心情 {view['val']:+.0f} · 激动 {view['arl']:.0f}"
    return line + (f" · {view['open_count']} 件事还挂着" if view.get('open_count') else '')


def event_line(event, settled):
    held = ' · 还挂着' if event.get('open') and not settled else ''
    return f"心情 {float(event.get('val', 0)):+.0f} · 激动 {float(event.get('arl', 0)):.0f}{held} · {event.get('why', '')[:120]}"


def mood_body(model, view):
    lines = [f"**{view['label'] or '平静'}**（心情 {view['val']:+.0f}，范围 −100～100；激动 {view['arl']:.0f}，范围 0～100）"]
    if view.get('policy'):
        lines.append('此刻的倾向：' + '；'.join(f"{slot['slot']}：{slot['text']}" for slot in view['policy']))
    if view.get('tendencies'):
        lines.append('主要的情绪带来：' + '、'.join(view['tendencies']))
    if view.get('contributions'):
        lines.append('来自：')
        lines += [f"- {kind_label(model, row['kind'])} · 心情 {row['val']:+.0f} · 激动 {row['arl']:.0f} · "
                  f"{ago(row['age_h'])}{'（还挂着，不会淡去）' if row.get('held') else ''}：{row.get('why', '')}"
                  for row in view['contributions']]
    lines.append('每件触动会随时间淡去（各种情绪淡得快慢不同）；还挂着的事要等了结后才开始淡。')
    return '\n\n'.join(lines)


def event_body(model, event, amendments):
    lines = [event.get('why', ''),
             f"种类：{kind_label(model, event.get('kind'))} · 心情 {float(event.get('val', 0)):+.0f} · 激动 {float(event.get('arl', 0)):.0f}"]
    if event.get('cost'):
        lines.append('代价：' + event['cost'])
    if event.get('open'):
        lines.append('这是一件还挂着的事：了结之前不会淡去。')
    lines += [f"{AMENDMENT_WORDS.get(item['op'], item['op'])}：{item.get('why') or '（未写原因）'}" for item in amendments]
    return '\n\n'.join(line for line in lines if line)


def document_title(content, slug):
    kind = DOCUMENT_KINDS.get(content['kind'], '文档')
    title = content.get('title') or slug
    return kind if title in (slug, content['kind']) else kind + ' · ' + title


def plain(text):
    """One line of readable text: markdown markers and emphasis removed."""
    text = re.sub(r'^\s*(?:[-*#>]\s*)+', '', ' '.join(text.split()))
    return re.sub(r'\*\*|__|`', '', text)


class NativeMemory:
    PAGE = 24
    LABELS = {'self': '自我', 'relation': '对人的认识', 'derived_summary': '交流摘要',
              'character_interpretation': '当时的理解', 'public_statement': '角色的发言',
              'reported_speech': '他人的原话', 'observed_fact': '事实记录', 'source': '原始消息',
              'document': '文档', 'affect': '情感', 'affect_event': '情感', 'persona_job_report': '作业报告'}

    def __init__(self, worker, session_id):
        self.store = worker.app.store
        self.binding = worker.session(session_id)
        self.scene = self.store.authorize(self.binding['scene_id'], self.binding['person_id'])
        self.read = scene_links.read_scope(self.store.config, self.scene)
        scenes = list(self.store.db.scenes.find({'_id': {'$in': self.read['scene_ids']}}))
        # Current epochs are resolved independently for each explicit A2 source.
        self.scopes = [{'scope_key': row['scope_key'], 'policy_epoch': row['policy_epoch']} for row in scenes]
        self.sources = [{'scene_id': row['_id'], 'policy_epoch': row['policy_epoch']} for row in scenes]
        persona = self.binding['persona']
        self.persona = persona
        # The persona itself is a document now; legacy persona heads are not listed.
        self.heads = {f'{kind}:{persona}|global-safe': ('self', title) for kind, title in (
            ('character_core', '核心自我'), ('current_self', '当前自我'))}
        relation = scene_links.relationship_target(self.store.config, self.store.db, self.scene, self.binding['person_id'])
        self.heads[relation['entity'] + '|' + relation['scope']] = ('relation', '关系与偏好')
        self.subject = relation.get('canonical') or self.binding['person_id']
        # Operator view: owner-private imported entries are listed too, each with its scope label.
        self.unit_query = {'status': 'active', 'character_id': character_id(self.store.config),
                           '$or': self.scopes + [{'scope_key': 'global-safe', 'policy_epoch': 1},
                                                 {'scope_key': 'owner-private:' + persona, 'policy_epoch': 1}]}
        self.message_query = {'$and': [{'$or': self.sources}, NOT_CORE_NOTICE, {'$or': [
            {'direction': 'inbound'}, {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]}]}
        self.cognition = CognitionView(self)

    def scene_title(self, scene_id):
        if not scene_id or scene_id == 'global-safe':
            return '所有对话共用'
        if scene_id == self.scene['_id'] and self.binding.get('native_title'):
            return self.binding['native_title']
        # The same title the conversation list shows for that scene.
        main = self.store.db.sessions.find_one({'scene_id': scene_id, 'main_conversation': True,
                                                'native_title': {'$exists': True}}, {'native_title': 1})
        if main:
            return main['native_title']
        platform = channel_kinds.of(scene_id)
        parts = platform.scene_parts(scene_id) if platform else None
        return ('群聊 · ' if parts[1] == 'group' else '私聊 · ') + parts[2] if parts else '本地聊天'

    @staticmethod
    def timestamp(row):
        try:
            return datetime.fromisoformat(row.get('updated_at') or '').timestamp()
        except (TypeError, ValueError):
            return float('-inf')

    def head_rows(self, kind, search=''):
        keys = [key for key, (category, _) in self.heads.items() if kind in ('all', category)]
        heads = list(self.store.db.state_heads.find({'_id': {'$in': keys}}))
        revisions = {row['_id']: row for row in self.store.db.state_revisions.find(
            {'_id': {'$in': [head['revision_id'] for head in heads]}},
            {'content': 1, 'updated_at': 1, 'generated_at': 1, 'created_at': 1})}
        by_key = {head['_id']: head for head in heads}
        rows = []
        for key in keys:
            head = by_key.get(key)
            revision = revisions.get(head['revision_id']) if head else None
            if head and not revision:
                raise Denied('MEMORY_REVISION_UNAVAILABLE')
            category, title = self.heads[key]
            body = revision.get('content', {}).get('body', '') if revision else ''
            row = {'id': 'head:' + key, 'kind': category, 'title': title,
                   'scope_key': key.rsplit('|', 1)[1], 'excerpt': body[:200],
                   'updated_at': (head or {}).get('updated_at') or (revision or {}).get('generated_at')
                       or (revision or {}).get('updated_at') or (revision or {}).get('created_at')}
            if revision and not row['updated_at']:
                # Older revisions carry no time of their own; the audited commit has it.
                commit = self.store.db.audit_events.find_one({'type': 'state.commit', 'payload.collection': 'state_revisions',
                                                              'payload.document._id': revision['_id']}, {'occurred_at': 1})
                row['updated_at'] = (commit or {}).get('occurred_at')
            if not revision:
                row.update(status_label='还没有写过', excerpt=EMPTY_HEAD[category])
            else:
                row['usage'] = self.cognition.usage(row['id'], revision['content'], revision['_id'])
            if not search or search.casefold() in (title + '\n' + (body or row['excerpt'])).casefold():
                rows.append(row)
        return rows

    def document_rows(self):
        """Operator view of the persona's documents: every section, each with its visibility label."""
        from .documents import DocumentStore
        from .render import render_status
        docs = DocumentStore(self.store, self.persona)
        if any(pair and pair[1] is None for pair in map(docs.head, docs.slugs())):
            raise Denied('MEMORY_REVISION_UNAVAILABLE')      # a broken head is never shown as an empty document
        status = render_status(self.store, self.persona) if docs.head('persona') else None
        rows = []
        for slug in docs.slugs():
            head, stored = docs.head(slug)
            revision, content = head['revision_id'], stored['content']
            counts = {}
            for section in content['sections']:
                label = VISIBILITY_LABELS[section['visibility']]
                counts[label] = counts.get(label, 0) + 1
            labels = '，'.join(f'{k} {v} 节' for k, v in counts.items())
            red = status and status['over_budget'] and slug in ('persona', 'voice')
            rows.append({'id': 'doc:' + slug, 'kind': 'document', 'title': document_title(content, slug),
                         'excerpt': labels + ('，超出渲染预算' if red else ''),
                         'scope_key': 'doc:' + slug, 'revision': revision,
                         'updated_at': stored.get('created_at')})
        return rows

    def affect_ledger(self):
        from .affect import AffectLedger
        from .render import model_and_policy
        return AffectLedger(self.store, self.persona, *model_and_policy(self.store, self.persona))

    def affect_rows(self):
        """Owner view: her mood now, then the most recent things that moved her, each from its conversation."""
        ledger = self.affect_ledger()
        if not ledger.enabled:
            return []
        view = ledger.description('owner_private')
        # "Now" sorts first: the mood is computed for this moment.
        rows = [{'id': 'affect:state', 'kind': 'affect', 'title': '此刻的心情', 'excerpt': mood_line(view),
                 'updated_at': datetime.now().astimezone().isoformat()}]
        events = list(self.store.db.affect_events.find({'persona': self.persona}).sort('ts', -1).limit(20))
        closed = {row['target'] for row in self.store.db.affect_amendments.find(
            {'target': {'$in': [event['_id'] for event in events]}, 'op': {'$in': ['close', 'void']}}, {'target': 1})}
        scenes = {row['_id']: row['scene_id'] for row in self.store.db.episodes.find(
            {'_id': {'$in': [event.get('episode_id') for event in events]}}, {'scene_id': 1})}
        for event in events:
            rows.append({'id': 'affect:' + event['_id'], 'kind': 'affect_event',
                         'title': '触动 · ' + kind_label(ledger.model, event.get('kind')),
                         'excerpt': event_line(event, event['_id'] in closed),
                         'scene_id': scenes.get(event.get('episode_id')), 'updated_at': event.get('ts')})
        return rows

    def job_rows(self):
        rows = []
        for item in self.store.db.artifacts.find({'kind': 'persona_job_report', 'scope_key': 'owner-private:' + self.persona},
                                                 {'_id': 1, 'size': 1}).sort('_id', -1).limit(20):
            rows.append({'id': 'report:' + item['_id'], 'kind': 'persona_job_report', 'title': '作业报告',
                         'excerpt': item['_id'], 'scope_key': 'owner-private:' + self.persona})
        return rows

    def page(self, kind='summary', offset=0, search=''):
        if kind not in ('all', 'documents', 'affect', 'jobs', 'self', 'relation', 'interpretation', 'summary', 'source'):
            raise ValueError('INVALID_MEMORY_CATEGORY')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('INVALID_MEMORY_PAGE')
        if not isinstance(search, str) or len(search) > 160:
            raise ValueError('INVALID_MEMORY_SEARCH')
        search = search.strip()
        # ADR-009 operator rows (documents, affect, job reports) come first; search applies to their titles.
        extra = (self.document_rows() if kind in ('all', 'documents') else
                 [row for row in self.document_rows() if row['id'] == 'doc:dossier:' + self.subject] if kind == 'relation' else []) + (
            self.affect_rows() if kind in ('all', 'affect') else []) + (
            self.job_rows() if kind in ('all', 'jobs') else [])
        heads = [row for row in extra if not search or search.casefold() in (row['title'] + '\n' + row['excerpt']).casefold()]
        heads += self.head_rows(kind, search) if kind in ('all', 'self', 'relation') else []
        heads += [row for row in self.cognition.supplements(kind) if not search or
                  search.casefold() in (row['title'] + '\n' + row['body']).casefold()]
        rows = list(heads)
        skipped = 0
        if kind in ('all', 'summary', 'source', 'interpretation'):
            messages = kind == 'source'
            query = self.message_query if messages else dict(self.unit_query)
            if kind == 'summary':
                query['epistemic_type'] = 'derived_summary'
            elif kind == 'interpretation':
                query['epistemic_type'] = 'character_interpretation'
            if search:
                query = {'$and': [query, {'text' if messages else 'body_markdown': {
                    '$regex': re.escape(search), '$options': 'i'}}]}
            projection = {'scope_key': 1, 'scene_id': 1, 'author': 1, 'speaker': 1, 'kind': 1, 'event.raw.asuna_peer': 1,
                'epistemic_type': 1, 'generated_at': 1, 'occurred_at': 1, '_memory_time': 1,
                'excerpt': {'$substrCP': [{'$ifNull': ['$text' if messages else '$body_markdown', '']}, 0, 200]}}
            collection = self.store.db.messages if messages else self.store.db.memory_units
            # State and coverage rows are bounded. Merge into a time-ordered
            # window instead of loading every preceding page or pinning them first.
            skipped = max(0, offset - len(heads))
            timing = [] if messages else [
                {'$lookup': {'from': 'audit_events', 'localField': 'episode_id', 'foreignField': 'stream_id',
                    'let': {'unit_id': '$_id'}, 'pipeline': [
                        {'$match': {'type': 'state.commit', 'payload.collection': 'memory_units',
                                    '$expr': {'$eq': ['$payload.document._id', '$$unit_id']}}},
                        {'$sort': {'seq': -1}}, {'$limit': 1}, {'$project': {'occurred_at': 1}}],
                    'as': '_memory_commit'}},
                {'$addFields': {'_memory_time': {'$ifNull': ['$generated_at', '$occurred_at',
                    {'$arrayElemAt': ['$_memory_commit.occurred_at', 0]}]}}}]
            result = collection.aggregate([{'$match': query}, *timing, {'$sort': {
                'occurred_at' if messages else '_memory_time': -1, '_id': -1}},
                {'$skip': skipped}, {'$limit': self.PAGE + 1 + len(heads)}, {'$project': projection}])
            for row in result:
                source = row.get('scene_id') or row.get('scope_key', '').removeprefix('scene:')
                rows.append({'id': ('source:' if messages else 'unit:') + row['_id'],
                    'kind': 'source' if messages else row.get('epistemic_type', row.get('kind')),
                    'title': ('原话 · ' + speaker_name(self.store.config, row.get('author'), row, self.store.db)) if messages else
                        plain(row['excerpt'])[:48] or '无正文的记忆',
                    # A memory's title is already the start of its text; only original messages show both.
                    'excerpt': row['excerpt'] if messages else '', 'scene_id': source,
                    'updated_at': row.get('_memory_time') or row.get('generated_at') or row.get('occurred_at')})
        rows.sort(key=lambda row: (self.timestamp(row), row['id']), reverse=True)
        rows = rows[offset - skipped:]
        for row in rows:
            row.pop('body', None)
            row.pop('source_ids', None)
            row['category_label'] = self.LABELS.get(row['kind'], '记忆')
            # Documents and job reports belong to the persona, not to any one conversation.
            row['scene_title'] = None if row['kind'] in ('document', 'persona_job_report', 'affect') else self.scene_title(
                row.get('scene_id') or row.get('scope_key', '').removeprefix('scene:'))
        return {'scene_id': self.scene['_id'], 'scene_title': self.scene_title(self.scene['_id']),
                'persona': self.binding['persona'], 'subject_name': self.cognition.subject_name(),
                'persona_name': self.store.config.get('chat', {}).get('display_name', '当前角色'),
                'linked_scenes': self.read['linked_scenes'], 'rows': rows[:self.PAGE],
                'linked_scene_titles': [self.scene_title(scene) for scene in self.read['linked_scenes']],
                'offset': offset, 'next_offset': offset + self.PAGE if len(rows) > self.PAGE else None}

    def detail(self, identifier):
        if not isinstance(identifier, str) or len(identifier) > 512 or ':' not in identifier:
            raise ValueError('INVALID_MEMORY_ID')
        kind, key = identifier.split(':', 1)
        if kind == 'report':
            from .blobs import BlobStore
            import json as _json
            row = self.store.db.artifacts.find_one({'_id': key, 'kind': 'persona_job_report'})
            if row:
                report = _json.loads(BlobStore(self.store).get(key, row['scope_key'], operator=True))
                lines = [f"状态：{report['status']} · 作业 {report['job']} · {report['run_id']}", report.get('summary', '')]
                lines += ['- ' + _json.dumps(item, ensure_ascii=False) for item in report.get('items', [])]
                result = {'id': identifier, 'body': '\n'.join(lines), 'interpretation': False, 'source_ids': [],
                          'scope_key': row['scope_key']}
        elif kind == 'affect':
            from .affect import AffectLedger
            from .render import model_and_policy
            import json as _json
            ledger = AffectLedger(self.store, self.persona, *model_and_policy(self.store, self.persona))
            if key == 'state':
                row = ledger.description('owner_private') if ledger.enabled else None
                result = row and {'id': identifier, 'body': mood_body(ledger.model, row), 'interpretation': True,
                                  'source_ids': []}
            else:
                row = self.store.db.affect_events.find_one({'_id': key, 'persona': self.persona})
                amendments = list(self.store.db.affect_amendments.find({'target': key}).sort('at', 1))
                result = row and {'id': identifier, 'body': event_body(ledger.model, row, amendments),
                                  'interpretation': True, 'source_ids': [], 'scope_key': row.get('source_scope')}
        elif kind == 'doc':
            from .documents import DocumentStore
            pair = DocumentStore(self.store, self.persona).head(key)
            if pair and pair[1] is None:
                raise Denied('MEMORY_REVISION_UNAVAILABLE')
            revision_id, content = (pair[0]['revision_id'], pair[1]['content']) if pair else (None, None)
            row = content
            if row:
                lines = []
                for section in content['sections']:
                    # Who may see it and when it is used, in words; the section body follows unchanged.
                    label = '，'.join([VISIBILITY_LABELS[section['visibility']], INJECT_LABELS[section['inject']],
                                      *([section['entry_date']] if section.get('entry_date') else [])])
                    lines.append(('### ' + section['heading'] + '\n' if section['heading'] else '') + f'*{label}*\n\n' + section['body'])
                result = {'id': identifier, 'body': '\n\n'.join(lines), 'interpretation': True,
                          'scope_key': 'global-safe', 'source_ids': [],
                          'usage': self.cognition.usage(identifier, revision=revision_id)}
        elif kind == 'head' and key in self.heads:
            entity, scope = key.rsplit('|', 1)
            pair = self.store.head(entity, scope)
            row = pair[1] if pair else None
            if pair and not row:
                raise Denied('MEMORY_REVISION_UNAVAILABLE')
            if row:
                body = row['content'].get('body', '')
                result = {'id': identifier, 'body': body, 'interpretation': True,
                          'category_label': self.heads[key][1],
                          'revision': pair[0]['revision'], 'scope_key': scope,
                          'usage': self.cognition.usage(identifier, row['content'], row['_id']),
                          'source_ids': row.get('source_ids', [])}
            else:
                row = {'missing': True}
                title = self.heads[key][1]
                result = {'id': identifier, 'body': EMPTY_HEAD[self.heads[key][0]],
                          'category_label': title, 'status_label': '还没有写过', 'source_ids': []}
        elif kind == 'cognition':
            row = next((item for item in self.cognition.supplements('all') if item['id'] == identifier), None)
            if row:
                result = dict(row)
        elif kind == 'unit':
            row = self.store.db.memory_units.find_one({**self.unit_query, '_id': key}, {'embedding': 0})
            if row:
                result = {'id': identifier, 'body': row.get('body_markdown', ''),
                          'category_label': self.LABELS.get(row.get('epistemic_type'), '记忆'),
                          'interpretation': row.get('epistemic_type') not in ('public_statement', 'reported_speech'),
                          'source_ids': row.get('source_event_ids', row.get('source_ids', [])),
                          **{k: row[k] for k in ('epistemic_type', 'scope_key', 'speaker', 'generated_at',
                              'source_window', 'participants', 'corrected_by', 'revision') if k in row}}
                window = row.get('source_window') if isinstance(row.get('source_window'), dict) else None
                if window and window.get('file_sha256'):
                    # Read back the exact lines from the snapshot taken at import (MEMORY §6.3).
                    snapshot = self.store.db.artifacts.find_one({'sha256': window['file_sha256'], 'kind': 'source_snapshot',
                                                                 'scope_key': row['scope_key']})
                    if snapshot:
                        from .blobs import BlobStore
                        lines = BlobStore(self.store).get(snapshot['_id'], row['scope_key'], operator=True).decode('utf-8').splitlines()
                        excerpt = '\n'.join(lines[max(0, window.get('line_from', 1) - 1):window.get('line_to', 1)])
                        result['body'] += ('\n\n——回读（' + str(window.get('path')) + ' 第 ' + str(window.get('line_from'))
                                           + '–' + str(window.get('line_to')) + ' 行，导入时快照）——\n' + excerpt)
                result['usage'] = self.cognition.usage(identifier)
        elif kind == 'source':
            row = self.store.db.messages.find_one({**self.message_query, '_id': key},
                {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1, 'direction': 1, 'event.raw.asuna_peer': 1})
            if row:
                result = {'id': identifier, 'body': row.pop('text', ''), 'interpretation': False,
                          'category_label': '原始消息', 'usage': self.cognition.usage(identifier), **row}
        else:
            row = None
        if not row:
            raise Denied('MEMORY_NOT_VISIBLE')
        result['body'] = result['body'][:65536]
        if kind == 'unit' and not result.get('generated_at') and row.get('episode_id'):
            commit = self.store.db.audit_events.find_one({'stream_id': row['episode_id'],
                'type': 'state.commit', 'payload.collection': 'memory_units',
                'payload.document._id': row['_id']}, {'occurred_at': 1}, sort=[('seq', -1)])
            if commit:
                result['generated_at'] = commit['occurred_at']
        if result.get('usage') and self.cognition.snapshot:
            result['context_at'] = self.cognition.snapshot['at']
        if result.get('corrected_by'):
            result['correction_note'] = '这条记录之后出现了更正；请结合后续原话查看。'
        ids = result.pop('source_ids', [])
        result['sources_truncated'] = len(ids) > 12
        ids = ids[:12]
        result['sources'] = list(self.store.db.messages.find({**self.message_query, '_id': {'$in': ids}},
            {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1, 'event.raw.asuna_peer': 1}).sort([('occurred_at', 1), ('_id', 1)]).limit(12))
        # Self/relationship revisions can cite interpretation or summary units,
        # not only original messages. Keep the source type and the same scope.
        for source in self.store.db.memory_units.find({**self.unit_query, '_id': {'$in': ids}},
                {'body_markdown': 1, 'speaker': 1, 'scope_key': 1, 'generated_at': 1,
                 'occurred_at': 1, 'epistemic_type': 1}).limit(12):
            result['sources'].append({'_id': source['_id'], 'text': source.get('body_markdown', ''),
                'author': source.get('speaker'), 'scene_id': source.get('scope_key', '').removeprefix('scene:'),
                'occurred_at': source.get('generated_at') or source.get('occurred_at'),
                'category_label': self.LABELS.get(source.get('epistemic_type'), '记忆来源')})
        result['sources'].sort(key=lambda source: (source.get('occurred_at') or '', source['_id']))
        result['sources_truncated'] |= len(result['sources']) > 12
        result['sources'] = result['sources'][:12]
        for source in result['sources']:
            source['text'] = source.get('text', '')[:8192]
            source['scene_title'] = self.scene_title(source.get('scene_id'))
            source['author'] = speaker_name(self.store.config, source.get('author'), source, self.store.db) if source.get('author') else None
            source.pop('event', None)
        for field in ('author', 'speaker'):
            if result.get(field):
                result[field] = speaker_name(self.store.config, result[field], row, self.store.db)
        result.pop('event', None)
        return result
