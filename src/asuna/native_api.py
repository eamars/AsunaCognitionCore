"""Bounded, read-only projections for native DSH's Asuna memory tab.

The native session is the authority boundary, never a scene supplied by a UI.
Lists carry excerpts; full bodies and authorized sources are read on demand.
"""
from .config import character_id
from .state import Denied
from . import scene_links


class NativeMemory:
    PAGE = 24

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
            ('persona', 'VOICE / 人格基线'), ('character_core', 'Character Core'), ('current_self', 'Current Self'))}
        relation = scene_links.relationship_target(self.store.config, self.store.db, self.scene, self.binding['person_id'])
        self.heads[relation['entity'] + '|' + relation['scope']] = ('relation', '关系与偏好')
        self.unit_query = {'status': 'active', 'character_id': character_id(self.store.config),
                           '$or': self.scopes + [{'scope_key': 'global-safe', 'policy_epoch': 1}]}
        self.message_query = {'$and': [{'$or': self.sources}, {'$or': [
            {'direction': 'inbound'}, {'direction': 'outbound', 'delivery_state': 'DELIVERED'}]}]}

    def head_rows(self, kind):
        keys = [key for key, (category, _) in self.heads.items() if kind in ('all', category)]
        heads = list(self.store.db.state_heads.find({'_id': {'$in': keys}}))
        revisions = {row['_id']: row for row in self.store.db.state_revisions.aggregate([
            {'$match': {'_id': {'$in': [head['revision_id'] for head in heads]}}},
            {'$project': {'excerpt': {'$substrCP': [{'$ifNull': ['$content.body', '']}, 0, 200]},
                          'updated_at': 1, 'generated_at': 1}}])}
        return [{'id': 'head:' + head['_id'], 'kind': self.heads[head['_id']][0],
                 'title': self.heads[head['_id']][1], 'scope_key': head['scope_key'],
                 'excerpt': revisions.get(head['revision_id'], {}).get('excerpt', ''),
                 'revision': head['revision_id'], 'updated_at': head.get('updated_at')}
                for head in heads]

    def page(self, kind='all', offset=0):
        if kind not in ('all', 'self', 'relation', 'summary', 'source'):
            raise ValueError('INVALID_MEMORY_CATEGORY')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('INVALID_MEMORY_PAGE')
        heads = self.head_rows(kind) if kind in ('all', 'self', 'relation') else []
        rows = heads[offset:offset + self.PAGE + 1]
        if kind in ('all', 'summary', 'source'):
            messages = kind == 'source'
            query = self.message_query if messages else dict(self.unit_query)
            if kind == 'summary':
                query['epistemic_type'] = 'derived_summary'
            projection = {'scope_key': 1, 'scene_id': 1, 'author': 1, 'speaker': 1, 'kind': 1,
                'epistemic_type': 1, 'generated_at': 1, 'occurred_at': 1,
                'excerpt': {'$substrCP': [{'$ifNull': ['$text' if messages else '$body_markdown', '']}, 0, 200]}}
            collection = self.store.db.messages if messages else self.store.db.memory_units
            result = collection.aggregate([{'$match': query}, {'$sort': {'_id': -1}},
                {'$skip': max(0, offset - len(heads))}, {'$limit': self.PAGE + 1 - len(rows)}, {'$project': projection}])
            for row in result:
                source = row.get('scene_id') or row.get('scope_key', '').removeprefix('scene:')
                rows.append({'id': ('source:' if messages else 'unit:') + row['_id'],
                    'kind': 'source' if messages else row.get('epistemic_type', row.get('kind')),
                    'title': ('原话 · ' + str(row.get('author', ''))) if messages else row.get('kind', '记忆'),
                    'excerpt': row['excerpt'], 'scene_id': source,
                    'updated_at': row.get('generated_at') or row.get('occurred_at')})
        return {'scene_id': self.scene['_id'], 'persona': self.binding['persona'],
                'linked_scenes': self.read['linked_scenes'], 'rows': rows[:self.PAGE],
                'offset': offset, 'next_offset': offset + self.PAGE if len(rows) > self.PAGE else None}

    def detail(self, identifier):
        if not isinstance(identifier, str) or len(identifier) > 512 or ':' not in identifier:
            raise ValueError('INVALID_MEMORY_ID')
        kind, key = identifier.split(':', 1)
        if kind == 'head' and key in self.heads:
            entity, scope = key.rsplit('|', 1)
            pair = self.store.head(entity, scope)
            row = pair[1] if pair else None
            if row:
                body = row['content'].get('body', '')
                result = {'id': identifier, 'body': body, 'interpretation': True,
                          'revision': row['_id'], 'scope_key': scope,
                          'levels': {k: v for k, v in row['content'].items() if k != 'body'},
                          'source_ids': row.get('source_ids', [])}
        elif kind == 'unit':
            row = self.store.db.memory_units.find_one({**self.unit_query, '_id': key}, {'embedding': 0})
            if row:
                result = {'id': identifier, 'body': row.get('body_markdown', ''),
                          'interpretation': row.get('epistemic_type') not in ('public_statement', 'reported_speech'),
                          'source_ids': row.get('source_event_ids', row.get('source_ids', [])),
                          **{k: row[k] for k in ('epistemic_type', 'scope_key', 'speaker', 'generated_at',
                              'source_window', 'participants', 'corrected_by', 'revision') if k in row}}
        elif kind == 'source':
            row = self.store.db.messages.find_one({**self.message_query, '_id': key},
                {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1, 'direction': 1})
            if row:
                result = {'id': identifier, 'body': row.pop('text', ''), 'interpretation': False, **row}
        else:
            row = None
        if not row:
            raise Denied('MEMORY_NOT_VISIBLE')
        result['body'] = result['body'][:65536]
        ids = result.pop('source_ids', [])[:12]
        result['sources'] = list(self.store.db.messages.find({**self.message_query, '_id': {'$in': ids}},
            {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1}).limit(12))
        for source in result['sources']:
            source['text'] = source.get('text', '')[:8192]
        return result
