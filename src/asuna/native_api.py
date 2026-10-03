"""Bounded, read-only projections for native DSH's Asuna memory tab.

The native session is the authority boundary, never a scene supplied by a UI.
Lists carry excerpts; full bodies and authorized sources are read on demand.
"""
from datetime import datetime
import re

from .config import character_id
from .state import Denied
from . import scene_links
from .native_cognition import CognitionView


class NativeMemory:
    PAGE = 24
    LABELS = {'self': '自我', 'relation': '对人的认识', 'world': '对世界的认识', 'derived_summary': '交流摘要',
              'character_interpretation': '当时的理解', 'public_statement': '角色的发言',
              'reported_speech': '他人的原话', 'observed_fact': '事实记录', 'source': '原始消息'}

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
        self.heads = {f'{kind}:{persona}|global-safe': ('self', title) for kind, title in (
            ('persona', '人格基线'), ('character_core', '核心自我'), ('current_self', '当前自我'))}
        self.heads[f"overlay:{persona}|{self.scene['scope_key']}"] = ('self', '当前场景的自我补充')
        relation = scene_links.relationship_target(self.store.config, self.store.db, self.scene, self.binding['person_id'])
        self.heads[relation['entity'] + '|' + relation['scope']] = ('relation', '关系与偏好')
        self.unit_query = {'status': 'active', 'character_id': character_id(self.store.config),
                           '$or': self.scopes + [{'scope_key': 'global-safe', 'policy_epoch': 1}]}
        self.message_query = {'$and': [{'$or': self.sources}, {'$or': [
            {'direction': 'inbound'}, {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]}]}
        self.cognition = CognitionView(self)

    def scene_title(self, scene_id):
        if not scene_id or scene_id == 'global-safe':
            return '角色共用'
        if scene_id == self.scene['_id'] and self.binding.get('native_title'):
            return self.binding['native_title']
        match = re.fullmatch(r'qq:[^:]+:(group|dm):(.+)', scene_id)
        return ('群聊 · ' if match[1] == 'group' else '私聊 · ') + match[2] if match else '本地聊天'

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
            {'content': 1, 'updated_at': 1, 'generated_at': 1})}
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
                   'updated_at': (head or {}).get('updated_at') or
                       (revision or {}).get('generated_at') or (revision or {}).get('updated_at')}
            if not revision:
                row.update(status_label='暂无记录', excerpt='暂无记录 · 尚未保存' + title + '。')
            else:
                row['usage'] = self.cognition.usage(row['id'], revision['content'], revision['_id'])
            if not search or search.casefold() in (title + '\n' + (body or row['excerpt'])).casefold():
                rows.append(row)
        return rows

    def page(self, kind='summary', offset=0, search=''):
        if kind not in ('all', 'self', 'relation', 'world', 'interpretation', 'summary', 'source'):
            raise ValueError('INVALID_MEMORY_CATEGORY')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('INVALID_MEMORY_PAGE')
        if not isinstance(search, str) or len(search) > 160:
            raise ValueError('INVALID_MEMORY_SEARCH')
        search = search.strip()
        heads = self.head_rows(kind, search) if kind in ('all', 'self', 'relation') else []
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
            projection = {'scope_key': 1, 'scene_id': 1, 'author': 1, 'speaker': 1, 'kind': 1,
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
                    'title': ('原话 · ' + str(row.get('author', '')).replace('qq:', 'QQ · ', 1)) if messages else
                        re.sub(r'^\s*(?:[-*#>]\s*)+', '', ' '.join(row['excerpt'].split()))[:48] or '无正文的记忆',
                    'excerpt': row['excerpt'], 'scene_id': source,
                    'updated_at': row.get('_memory_time') or row.get('generated_at') or row.get('occurred_at')})
        rows.sort(key=lambda row: (self.timestamp(row), row['id']), reverse=True)
        rows = rows[offset - skipped:]
        for row in rows:
            row.pop('body', None)
            row.pop('source_ids', None)
            row['category_label'] = self.LABELS.get(row['kind'], '记忆')
            row['scene_title'] = self.scene_title(row.get('scene_id') or
                row.get('scope_key', '').removeprefix('scene:'))
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
        if kind == 'head' and key in self.heads:
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
                          'levels': {label: row['content'][field] for field, label in (
                              ('familiarity', '熟悉程度'), ('trust', '信任'),
                              ('closeness', '亲近程度'), ('tension', '紧张程度')) if field in row['content']},
                          'source_ids': row.get('source_ids', [])}
            else:
                row = {'missing': True}
                title = self.heads[key][1]
                result = {'id': identifier, 'body': '暂无记录 · 尚未保存' + title + '。',
                          'category_label': title, 'status_label': '暂无记录', 'source_ids': []}
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
                result['usage'] = self.cognition.usage(identifier)
        elif kind == 'source':
            row = self.store.db.messages.find_one({**self.message_query, '_id': key},
                {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1, 'direction': 1})
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
            {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1}).sort([('occurred_at', 1), ('_id', 1)]).limit(12))
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
        return result
