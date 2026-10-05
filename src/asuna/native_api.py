"""Bounded, read-only projections for native DSH's Asuna memory tab.

The native session is the authority boundary, never a scene supplied by a UI.
Lists carry excerpts; full bodies and authorized sources are read on demand.

Words of the page are the client's (ADR-011 §2.8): a label is `{'key', 'params'}` from the client's
`asuna` locale namespace, and a list of parts is joined as paragraphs. Content (her documents, her
memories, people's messages, names, her persona's own words for feelings) is sent as it is.
"""
from datetime import datetime
import re

from .config import ago, character_id
from .state import Denied
from . import channel_kinds, scene_links
from .ingress import NOT_CORE_NOTICE
from .native_cognition import CognitionView
from .peer_context import speaker_name

DOCUMENT_KINDS = ('persona', 'voice', 'ledger', 'dossier', 'working')


def label(key, **params):
    return {'key': 'memory.' + key, 'params': params}


def signed(value):
    return f'{float(value or 0):+.0f}'


def ago_label(hours):
    """How long ago, in the viewer's words (config.ago is the model-facing twin)."""
    return (label('ago.now') if hours * 60 < 5 else label('ago.minutes', n=round(hours * 60)) if hours < 1
            else label('ago.hours', n=round(hours)) if hours < 48 else label('ago.days', n=round(hours / 24)))


def kind_label(model, kind):
    """Her persona's own word for a feeling (content), or the kind's id when it has none."""
    return (model.get('kinds', {}).get(kind) or {}).get('label') or kind or '?'


def paragraphs(*items):
    """Parts the client concatenates: these items, a blank line between each (empty ones left out)."""
    out = []
    for item in items:
        if item in (None, '', []):
            continue
        if out:
            out.append('\n\n')
        out.append(item)
    return out


def mood_word(view):
    return view['label'] or label('mood.calm')


def mood_line(view):
    return label('mood.line', label=mood_word(view), val=signed(view['val']), arl=f"{view['arl']:.0f}",
                 open=label('mood.open', n=view['open_count']) if view.get('open_count') else '')


def event_line(event, settled):
    return label('event.line', val=signed(event.get('val')), arl=f"{float(event.get('arl', 0)):.0f}",
                 held=label('event.held') if event.get('open') and not settled else '', why=event.get('why', '')[:120])


def mood_body(model, view):
    contributions = []
    for row in view.get('contributions') or []:
        if contributions:
            contributions.append('\n')
        contributions.append(label('mood.contribution', feeling=kind_label(model, row['kind']), val=signed(row['val']),
                                   arl=f"{row['arl']:.0f}", ago=ago_label(row['age_h']),
                                   held=label('mood.held') if row.get('held') else '', why=row.get('why', '')))
    return paragraphs(
        label('mood.head', label=mood_word(view), val=signed(view['val']), arl=f"{view['arl']:.0f}"),
        view.get('policy') and label('mood.policy', text=' · '.join(f"{slot['slot']}：{slot['text']}" for slot in view['policy'])),
        view.get('tendencies') and label('mood.tendencies', text=' · '.join(view['tendencies'])),
        contributions and label('mood.from'), contributions, label('mood.fade'))


def event_body(model, event, amendments):
    return paragraphs(
        event.get('why', ''),
        label('event.kind', feeling=kind_label(model, event.get('kind')), val=signed(event.get('val')),
              arl=f"{float(event.get('arl', 0)):.0f}"),
        event.get('cost') and label('event.cost', text=event['cost']),
        event.get('open') and label('event.open'),
        *[label('amendment.' + item['op'], why=item.get('why') or label('event.noReason'))
          if item['op'] in ('close', 'void', 'fix_ts', 'fix_kind') else item['op'] + ' ' + (item.get('why') or '')
          for item in amendments])


def document_title(content, slug):
    kind = label('doc.' + (content['kind'] if content['kind'] in DOCUMENT_KINDS else 'other'))
    title = content.get('title') or slug
    return label('title.document', kind=kind) if title in (slug, content['kind']) else label('title.documentNamed', kind=kind, name=title)


def searchable(row):
    """The content text of a row (titles and excerpts may be labels: their content parameters count)."""
    def parts(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [part for item in (value.get('params') or {}).values() for part in parts(item)]
        if isinstance(value, list):
            return [part for item in value for part in parts(item)]
        return []
    return '\n'.join(parts(row.get('title')) + parts(row.get('excerpt')))


def plain(text):
    """One line of readable text: markdown markers and emphasis removed."""
    text = re.sub(r'^\s*(?:[-*#>]\s*)+', '', ' '.join(text.split()))
    return re.sub(r'\*\*|__|`', '', text)


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
        self.heads = {f'{kind}:{persona}|global-safe': ('self', label('title.' + kind)) for kind in (
            'character_core', 'current_self')}
        relation = scene_links.relationship_target(self.store.config, self.store.db, self.scene, self.binding['person_id'])
        self.heads[relation['entity'] + '|' + relation['scope']] = ('relation', label('title.relation'))
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
            return label('scene.shared')
        if scene_id == self.scene['_id'] and self.binding.get('native_title'):
            return self.binding['native_title']
        # The same title the conversation list shows for that scene.
        main = self.store.db.sessions.find_one({'scene_id': scene_id, 'main_conversation': True,
                                                'native_title': {'$exists': True}}, {'native_title': 1})
        if main:
            return main['native_title']
        platform = channel_kinds.of(scene_id)
        parts = platform.scene_parts(scene_id) if platform else None
        return label('scene.group' if parts[1] == 'group' else 'scene.dm', name=parts[2]) if parts else label('scene.local')

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
                row.update(status='empty', excerpt=label('hint.' + category))
            else:
                row['usage'] = self.cognition.usage(row['id'], revision['content'], revision['_id'])
            if not search or search.casefold() in (body or '').casefold():
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
                counts[section['visibility']] = counts.get(section['visibility'], 0) + 1
            red = status and status['over_budget'] and slug in ('persona', 'voice')
            rows.append({'id': 'doc:' + slug, 'kind': 'document', 'title': document_title(content, slug),
                         'excerpt': [part for index, (visibility, count) in enumerate(counts.items())
                                     for part in ([' · '] if index else []) + [label('doc.sections', label=label('visibility.' + visibility), n=count)]]
                                    + ([' · ', label('doc.overBudget')] if red else []),
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
        rows = [{'id': 'affect:state', 'kind': 'affect', 'title': label('title.mood'), 'excerpt': mood_line(view),
                 'updated_at': datetime.now().astimezone().isoformat()}]
        events = list(self.store.db.affect_events.find({'persona': self.persona}).sort('ts', -1).limit(20))
        closed = {row['target'] for row in self.store.db.affect_amendments.find(
            {'target': {'$in': [event['_id'] for event in events]}, 'op': {'$in': ['close', 'void']}}, {'target': 1})}
        scenes = {row['_id']: row['scene_id'] for row in self.store.db.episodes.find(
            {'_id': {'$in': [event.get('episode_id') for event in events]}}, {'scene_id': 1})}
        for event in events:
            rows.append({'id': 'affect:' + event['_id'], 'kind': 'affect_event',
                         'title': label('title.moved', feeling=kind_label(ledger.model, event.get('kind'))),
                         'excerpt': event_line(event, event['_id'] in closed),
                         'scene_id': scenes.get(event.get('episode_id')), 'updated_at': event.get('ts')})
        return rows

    def owner_view(self):
        from . import visibility
        return visibility.session_class(self.store.config, self.store.db, self.scene,
                                        self.binding['person_id']) == visibility.OWNER_PRIVATE

    def idea_rows(self):
        """Her improvement-idea notebook and what she decided (ADR-011 §6.2), for the owner's view only."""
        if not self.owner_view():
            return []
        rows = []
        for row in self.store.db.ideas.find({'persona': self.persona}).sort('created_at', -1).limit(50):
            decided = (row.get('decisions') or [{}])[-1]
            rows.append({'id': 'idea:' + row['_id'], 'kind': 'idea', 'title': row['idea'],
                         'excerpt': [label('idea.state.' + row.get('state', 'open')), ' · ', decided.get('why') or row['why']],
                         'updated_at': decided.get('at') or row.get('created_at')})
        return rows

    def job_rows(self):
        rows = []
        for item in self.store.db.artifacts.find({'kind': 'persona_job_report', 'scope_key': 'owner-private:' + self.persona},
                                                 {'_id': 1, 'size': 1}).sort('_id', -1).limit(20):
            rows.append({'id': 'report:' + item['_id'], 'kind': 'persona_job_report', 'title': label('title.job'),
                         'excerpt': item['_id'], 'scope_key': 'owner-private:' + self.persona})
        return rows

    def page(self, kind='summary', offset=0, search=''):
        if kind not in ('all', 'documents', 'affect', 'jobs', 'ideas', 'self', 'relation', 'interpretation', 'summary', 'source'):
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
            self.job_rows() if kind in ('all', 'jobs') else []) + (
            self.idea_rows() if kind in ('all', 'ideas') else [])
        heads = [row for row in extra if not search or search.casefold() in searchable(row).casefold()]
        heads += self.head_rows(kind, search) if kind in ('all', 'self', 'relation') else []
        heads += [row for row in self.cognition.supplements(kind) if not search or
                  search.casefold() in row['body'].casefold()]
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
                    'title': label('title.said', speaker=speaker_name(self.store.config, row.get('author'), row, self.store.db)) if messages else
                        plain(row['excerpt'])[:48] or label('title.blank'),
                    # A memory's title is already the start of its text; only original messages show both.
                    'excerpt': row['excerpt'] if messages else '', 'scene_id': source,
                    'updated_at': row.get('_memory_time') or row.get('generated_at') or row.get('occurred_at')})
        rows.sort(key=lambda row: (self.timestamp(row), row['id']), reverse=True)
        rows = rows[offset - skipped:]
        for row in rows:
            row.pop('body', None)
            row.pop('source_ids', None)
            # Documents and job reports belong to the persona, not to any one conversation.
            row['scene_title'] = None if row['kind'] in ('document', 'persona_job_report', 'affect') else self.scene_title(
                row.get('scene_id') or row.get('scope_key', '').removeprefix('scene:'))
        return {'scene_id': self.scene['_id'], 'scene_title': self.scene_title(self.scene['_id']),
                'persona': self.binding['persona'], 'subject_name': self.cognition.subject_name(),
                'persona_name': self.store.config.get('chat', {}).get('display_name'),
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
                lines = paragraphs(label('report.status', status=report['status'], job=report['job'], run=report['run_id']),
                                   report.get('summary', ''),
                                   '\n'.join('- ' + _json.dumps(item, ensure_ascii=False) for item in report.get('items', [])))
                result = {'id': identifier, 'body': lines, 'interpretation': False, 'source_ids': [],
                          'category': 'persona_job_report', 'scope_key': row['scope_key']}
        elif kind == 'idea':
            row = self.store.db.ideas.find_one({'_id': key, 'persona': self.persona}) if self.owner_view() else None
            source = (row or {}).get('source') or {}
            result = row and {'id': identifier, 'category': 'idea', 'interpretation': True, 'source_ids': [],
                              'status': 'idea.' + row.get('state', 'open'),
                              'body': paragraphs(row['idea'], label('idea.why', text=row['why']),
                                                 label('idea.from.' + ('action' if source.get('by') == 'action' else 'character'),
                                                       where=self.scene_title(source.get('scene_id'))),
                                                 *[label('idea.decision.' + item['decision'], why=item.get('why', ''))
                                                   for item in row.get('decisions') or []])}
        elif kind == 'affect':
            from .affect import AffectLedger
            from .render import model_and_policy
            import json as _json
            ledger = AffectLedger(self.store, self.persona, *model_and_policy(self.store, self.persona))
            if key == 'state':
                row = ledger.description('owner_private') if ledger.enabled else None
                result = row and {'id': identifier, 'body': mood_body(ledger.model, row), 'interpretation': True,
                                  'category': 'affect', 'source_ids': []}
            else:
                row = self.store.db.affect_events.find_one({'_id': key, 'persona': self.persona})
                amendments = list(self.store.db.affect_amendments.find({'target': key}).sort('at', 1))
                result = row and {'id': identifier, 'body': event_body(ledger.model, row, amendments), 'category': 'affect_event',
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
                    lines += [section['heading'] and '### ' + section['heading'],
                              label('doc.meta', visibility=label('visibility.' + section['visibility']),
                                    inject=label('inject.' + section['inject']),
                                    date=' · ' + section['entry_date'] if section.get('entry_date') else ''),
                              section['body']]
                result = {'id': identifier, 'body': paragraphs(*lines), 'interpretation': True, 'category': 'document',
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
                          'category': self.heads[key][0],
                          'revision': pair[0]['revision'], 'scope_key': scope,
                          'usage': self.cognition.usage(identifier, row['content'], row['_id']),
                          'source_ids': row.get('source_ids', [])}
            else:
                row = {'missing': True}
                title = self.heads[key][1]
                result = {'id': identifier, 'body': label('hint.' + self.heads[key][0]),
                          'category': self.heads[key][0], 'status': 'empty', 'source_ids': []}
        elif kind == 'cognition':
            row = next((item for item in self.cognition.supplements('all') if item['id'] == identifier), None)
            if row:
                result = dict(row)
        elif kind == 'unit':
            row = self.store.db.memory_units.find_one({**self.unit_query, '_id': key}, {'embedding': 0})
            if row:
                result = {'id': identifier, 'body': row.get('body_markdown', ''),
                          'category': row.get('epistemic_type') or 'other',
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
                        result['body'] = paragraphs(result['body'], label('readback', path=str(window.get('path')),
                                          **{'from': window.get('line_from'), 'to': window.get('line_to')}), excerpt)
                result['usage'] = self.cognition.usage(identifier)
        elif kind == 'source':
            row = self.store.db.messages.find_one({**self.message_query, '_id': key},
                {'text': 1, 'author': 1, 'scene_id': 1, 'occurred_at': 1, 'direction': 1, 'event.raw.asuna_peer': 1})
            if row:
                result = {'id': identifier, 'body': row.pop('text', ''), 'interpretation': False,
                          'category': 'source', 'usage': self.cognition.usage(identifier), **row}
        else:
            row = None
        if not row:
            raise Denied('MEMORY_NOT_VISIBLE')
        if isinstance(result['body'], str):
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
            result['corrected'] = True
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
                'category': source.get('epistemic_type') or 'other'})
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
