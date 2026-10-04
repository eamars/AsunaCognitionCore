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
        self.persona = persona
        # The persona itself is a document now; legacy persona heads are not listed.
        self.heads = {f'{kind}:{persona}|global-safe': ('self', title) for kind, title in (
            ('character_core', 'Character Core'), ('current_self', 'Current Self'))}
        relation = scene_links.relationship_target(self.store.config, self.store.db, self.scene, self.binding['person_id'])
        self.heads[relation['entity'] + '|' + relation['scope']] = ('relation', '关系与偏好')
        # Operator view: owner-private imported entries are listed too, each with its scope label.
        self.unit_query = {'status': 'active', 'character_id': character_id(self.store.config),
                           '$or': self.scopes + [{'scope_key': 'global-safe', 'policy_epoch': 1},
                                                 {'scope_key': 'owner-private:' + persona, 'policy_epoch': 1}]}
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

    def document_rows(self):
        """Operator view of the persona's documents: every section, each with its visibility label."""
        from .documents import DocumentStore
        from .render import render_status
        docs = DocumentStore(self.store, self.persona)
        status = render_status(self.store, self.persona) if docs.head('persona') else None
        rows = []
        for slug in docs.slugs():
            revision, content = docs.read(slug)
            counts = {}
            for section in content['sections']:
                counts[section['visibility']] = counts.get(section['visibility'], 0) + 1
            labels = ' / '.join(f'{k} {v}' for k, v in sorted(counts.items()))
            red = status and status['over_budget'] and slug in ('persona', 'voice')
            rows.append({'id': 'doc:' + slug, 'kind': 'document', 'title': f"{content['kind']} · {content.get('title') or slug}",
                         'excerpt': f"{len(content['sections'])} 节 · {labels}" + (' · 超出渲染预算' if red else ''),
                         'scope_key': 'doc:' + slug, 'revision': revision})
        return rows

    def affect_rows(self):
        """Operator view: the current projection and the most recent events, each with its source scope."""
        from .affect import AffectLedger
        from .render import model_and_policy
        ledger = AffectLedger(self.store, self.persona, *model_and_policy(self.store, self.persona))
        if not ledger.enabled:
            return []
        view = ledger.description('owner_private')
        rows = [{'id': 'affect:state', 'kind': 'affect', 'title': '情感 · 当前投影',
                 'excerpt': f"{view['label']} · val {view['val']:.1f} · arl {view['arl']:.1f} · 挂账 {view['open_count']}",
                 'scope_key': 'affect'}]
        for event in self.store.db.affect_events.find({'persona': self.persona}).sort('ts', -1).limit(20):
            rows.append({'id': 'affect:' + event['_id'], 'kind': 'affect_event',
                         'title': '情感事件 · ' + (event.get('kind') or '未分类'),
                         'excerpt': f"val {event.get('val')} · arl {event.get('arl')} · {event.get('why', '')[:120]}",
                         'scope_key': event.get('source_scope'), 'updated_at': event.get('ts')})
        return rows

    def job_rows(self):
        rows = []
        for item in self.store.db.artifacts.find({'kind': 'persona_job_report', 'scope_key': 'owner-private:' + self.persona},
                                                 {'_id': 1, 'size': 1}).sort('_id', -1).limit(20):
            rows.append({'id': 'report:' + item['_id'], 'kind': 'persona_job_report', 'title': '作业报告',
                         'excerpt': item['_id'], 'scope_key': 'owner-private:' + self.persona})
        return rows

    def page(self, kind='all', offset=0):
        if kind not in ('all', 'documents', 'affect', 'jobs', 'self', 'relation', 'summary', 'source'):
            raise ValueError('INVALID_MEMORY_CATEGORY')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('INVALID_MEMORY_PAGE')
        heads = (self.document_rows() if kind in ('all', 'documents') else []) + (
            self.affect_rows() if kind in ('all', 'affect') else []) + (
            self.job_rows() if kind in ('all', 'jobs') else []) + (
            self.head_rows(kind) if kind in ('all', 'self', 'relation') else [])
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
                result = row and {'id': identifier, 'body': _json.dumps(row, ensure_ascii=False, indent=2, default=str),
                                  'interpretation': True, 'source_ids': []}
            else:
                row = self.store.db.affect_events.find_one({'_id': key, 'persona': self.persona})
                amendments = list(self.store.db.affect_amendments.find({'target': key}, {'_id': 0, 'op': 1, 'at': 1, 'why': 1, 'by': 1}))
                result = row and {'id': identifier, 'body': row.get('why', ''), 'interpretation': True, 'source_ids': [],
                                  'scope_key': row.get('source_scope'),
                                  'levels': {k: row.get(k) for k in ('kind', 'val', 'arl', 'ts', 'ref', 'who', 'cost', 'open', 'origin')}
                                            | {'amendments': amendments}}
        elif kind == 'doc':
            from .documents import DocumentStore
            from .render import render_status
            revision_id, content = DocumentStore(self.store, self.persona).read(key)
            row = content
            if row:
                lines = []
                for section in content['sections']:
                    label = ' · '.join([section['visibility'], section['inject'], *section.get('tags', []),
                                        *([section['entry_date']] if section.get('entry_date') else [])])
                    lines.append(('## ' + section['heading'] if section['heading'] else '（前言）') + f'\n〔{label}〕\n' + section['body'])
                status = render_status(self.store, self.persona) if key in ('persona', 'voice') else None
                result = {'id': identifier, 'body': '\n\n'.join(lines), 'interpretation': True, 'revision': revision_id,
                          'scope_key': 'global-safe', 'source_ids': [],
                          'levels': {'kind': content['kind'], 'sections': len(content['sections']),
                                     **({'render': status} if status else {})}}
        elif kind == 'head' and key in self.heads:
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
                window = row.get('source_window') if isinstance(row.get('source_window'), dict) else None
                if window and window.get('file_sha256'):
                    # Read back the exact lines from the snapshot taken at import (MEMORY §6.3).
                    result['levels'] = {'source_window': window, 'origin': row.get('origin'), 'invented': row.get('invented')}
                    snapshot = self.store.db.artifacts.find_one({'sha256': window['file_sha256'], 'kind': 'source_snapshot',
                                                                 'scope_key': row['scope_key']})
                    if snapshot:
                        from .blobs import BlobStore
                        lines = BlobStore(self.store).get(snapshot['_id'], row['scope_key'], operator=True).decode('utf-8').splitlines()
                        excerpt = '\n'.join(lines[max(0, window.get('line_from', 1) - 1):window.get('line_to', 1)])
                        result['body'] += ('\n\n——回读（' + str(window.get('path')) + ' 第 ' + str(window.get('line_from'))
                                           + '–' + str(window.get('line_to')) + ' 行，导入时快照）——\n' + excerpt)
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
