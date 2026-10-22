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

DOCUMENT_KINDS = ('persona', 'voice', 'ledger', 'working')
# The two scopes of the tab: what is the same in every conversation, and what this conversation reads.
EVERYWHERE = ('self', 'affect', 'ideas', 'people', 'documents')
THIS_CONVERSATION = ('here_people', 'group_notes', 'summary', 'interpretation', 'source')
# Her documents a reader knows by name (the rest are shown by the name she gave them).
NAMED_DOCUMENTS = {'persona': 'persona', 'voice': 'voice', 'self': 'self', 'core': 'core', 'ledger': 'ledger',
                   'work_log': 'journal'}


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

    def self_documents(self):
        """Her self as her turns read it (ADR-062): {old head name: (document, its sections placed)} for each of
        `self` and `core` she has written; an empty one leaves its old head in the list."""
        from . import memory_tiers
        from .documents import DocumentStore
        if not memory_tiers.ENABLED:
            return {}
        if hasattr(self, '_self_documents'):
            return self._self_documents
        docs, found = DocumentStore(self.store, self.persona), {}
        for name, slug in (('current_self', memory_tiers.SELF_DOC), ('character_core', memory_tiers.CORE_DOC)):
            content = memory_tiers.placed(self.store, self.persona, slug, docs.read(slug)[1])
            if content and content.get('sections'):
                found[name] = (slug, content)
        self._self_documents = found
        return found

    def item_rows(self, slug, content, kind, tag, search=''):
        """One row per section of a document, with the place it is in (carried every turn, at hand, put away)."""
        times = {row['sid']: row.get('memorable_at') or row.get('added') for row in self.store.db.memory_tiers.find(
            {'row': 'item', 'persona': self.persona, 'doc': slug}, {'sid': 1, 'memorable_at': 1, 'added': 1})}
        return [{'id': f"item:{slug}#{section['sid']}", 'kind': kind,
                 'title': section['heading'] or plain(section['body'])[:48] or label('title.blank'),
                 'excerpt': [*([tag, ' · '] if tag else []), label('inject.' + section['inject'])],
                 'scope_key': 'doc:' + slug, 'updated_at': times.get(section['sid'])}
                for section in content['sections']
                if not search or search.casefold() in (section['heading'] + section['body']).casefold()]

    def self_item_rows(self, search=''):
        """Her self, item by item: the `self` and `core` documents."""
        return [row for name, (slug, content) in self.self_documents().items()
                for row in self.item_rows(slug, content, 'self', label('title.' + name), search)]

    def group_note_rows(self, search=''):
        """This group's notes, item by item (only in a group's own conversation)."""
        from . import memory_tiers
        from .documents import DocumentStore
        from .group_admin import notes_slug
        if self.scene.get('kind') != 'group':
            return []
        slug = notes_slug(self.scene['_id'])
        content = memory_tiers.placed(self.store, self.persona, slug, DocumentStore(self.store, self.persona).read(slug)[1])
        return self.item_rows(slug, content, 'group_notes', None, search) if content and content.get('sections') else []

    # -- people: her written understanding of each person (understanding.py) --
    def person_name(self, person):
        """A person as the owner reads them: the name this machine keeps, else the card or nickname they last had."""
        from .people import safe_name
        row = self.store.db.identities.find_one({'_id': person}, {'display_name': 1})
        kept = safe_name((row or {}).get('display_name'))
        if kept:
            return kept
        seen = self.store.db.scene_people.find_one({'person': person}, {'card': 1, 'nickname': 1}, sort=[('seen_at', -1)])
        return (safe_name((seen or {}).get('card')) or safe_name((seen or {}).get('nickname'))
                or speaker_name(self.store.config, person, None, self.store.db))

    def relation_records(self, person=None):
        """{person: [(scope, short and body, time)]}: what holds of them anywhere (scope `person`) and how they are in each
        conversation (scope `scene:...`)."""
        pattern = '^relationship:' + (re.escape(person) + '[|]' if person else '')
        heads = list(self.store.db.state_heads.find({'_id': {'$regex': pattern}}))
        revisions = {row['_id']: row for row in self.store.db.state_revisions.find(
            {'_id': {'$in': [head['revision_id'] for head in heads]}}, {'content': 1, 'created_at': 1, 'generated_at': 1})}
        found = {}
        for head in heads:
            entity, scope = head['_id'].rsplit('|', 1)
            revision = revisions.get(head['revision_id']) or {}
            content = revision.get('content') or {}
            # Her one line for herself first, then the body (ADR-082); read only.
            text = (content['short'] + '\n\n' if content.get('short') else '') + content.get('body', '')
            found.setdefault(entity.removeprefix('relationship:'), []).append(
                (scope, text,
                 head.get('updated_at') or revision.get('generated_at') or revision.get('created_at')))
        return found

    def people_rows(self, search=''):
        """Everyone she has written about, newest first; search matches a name or what she wrote."""
        rows = []
        for person, records in self.relation_records().items():
            name = self.person_name(person)
            records.sort(key=lambda record: (record[0] != 'person', str(record[2] or '')))
            if search and not any(search.casefold() in text.casefold() for text in [name] + [r[1] for r in records]):
                continue
            rows.append({'id': 'person:' + person, 'kind': 'relation', 'title': name,
                         'excerpt': plain(records[0][1])[:200],
                         'updated_at': max(str(record[2] or '') for record in records) or None})
        return rows

    def here_people_rows(self, search=''):
        """The last ten people who spoke in this conversation, each with how she sees them here (or nothing yet)."""
        from . import understanding
        latest = {}
        for message in self.store.db.messages.find({'scene_id': self.scene['_id'], 'direction': 'inbound', **NOT_CORE_NOTICE},
                                                   {'author': 1, 'occurred_at': 1}).sort('occurred_at', -1).limit(2000):
            if message.get('author') and message['author'] not in latest:
                latest[message['author']] = message.get('occurred_at')
            if len(latest) == 10:
                break
        rows = []
        for author, at in latest.items():
            target = scene_links.relationship_target(self.store.config, self.store.db, self.scene, author)
            person = target['entity'].removeprefix('relationship:')
            records = {scope: body for scope, body, _ in self.relation_records(person).get(person, [])}
            name = self.person_name(author)
            text = records.get(target['scope']) or records.get(understanding.PERSON_SCOPE)
            if search and search.casefold() not in (name + (text or '')).casefold():
                continue
            rows.append({'id': 'person:' + person, 'kind': 'relation', 'title': name,
                         'excerpt': plain(text)[:200] if text else label('status.empty'), 'updated_at': at})
        return rows

    def person_detail(self, person):
        """What she wrote about one person: what holds anywhere first, then how they are in each conversation."""
        records = sorted(self.relation_records(person).get(person, []),
                         key=lambda record: (record[0] != 'person', str(record[2] or '')))
        parts = []
        for scope, body, _ in records:
            where = label('title.person') if scope == 'person' else self.scene_title(scope.removeprefix('scene:'))
            parts += [where, body]
        return {'id': 'person:' + person, 'category': 'relation', 'interpretation': True, 'source_ids': [],
                'body': paragraphs(*[part for pair in zip(parts[0::2], parts[1::2])
                                     for part in ([{'key': 'memory.heading', 'params': {'text': pair[0]}}, pair[1]])])
                if parts else label('hint.relation')}

    def head_rows(self, kind, search=''):
        replaced = {f'{name}:{self.persona}|global-safe' for name in self.self_documents()}
        keys = [key for key, (category, _) in self.heads.items() if kind == category and key not in replaced]
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
        """Operator view of the persona's documents, each by its name, with how many of its sections are in each
        place (every turn, when relevant, put away)."""
        from . import memory_tiers
        from .documents import DocumentStore
        from .group_admin import notes_slug
        from .render import render_status
        docs = DocumentStore(self.store, self.persona)
        if any(pair and pair[1] is None for pair in map(docs.head, docs.slugs())):
            raise Denied('MEMORY_REVISION_UNAVAILABLE')      # a broken head is never shown as an empty document
        status = render_status(self.store, self.persona) if docs.head('persona') else None
        groups = {notes_slug(row['_id']): row['_id'] for row in self.store.db.scenes.find({'kind': 'group'}, {'_id': 1})}
        rows = []
        for slug in docs.slugs():
            if slug in groups:
                continue                      # a group's notes are listed in that group's own conversation
            head, stored = docs.head(slug)
            revision = head['revision_id']
            content = memory_tiers.placed(self.store, self.persona, slug, stored['content'])
            counts = {}
            for inject in ('always', 'on_demand', 'never'):
                n = sum(1 for section in content['sections'] if section.get('inject') == inject)
                if n:
                    counts[inject] = n
            red = status and status['over_budget'] and slug in ('persona', 'voice')
            rows.append({'id': 'doc:' + slug, 'kind': 'document', 'title': self.document_name(slug, groups),
                         'excerpt': [part for index, (inject, count) in enumerate(counts.items())
                                     for part in ([' · '] if index else []) + [label('doc.sections', label=label('inject.' + inject), n=count)]]
                                    + ([' · ', label('doc.overBudget')] if red else []),
                         'scope_key': 'doc:' + slug, 'revision': revision,
                         'updated_at': stored.get('created_at')})
        return rows + self.job_rows()

    def document_name(self, slug, groups):
        """A document as a reader knows it: her persona, voice, self, core, ledger, work log, a group's notes by the
        group's name, or her own name for it."""
        if slug in NAMED_DOCUMENTS:
            return label('doc.' + NAMED_DOCUMENTS[slug])
        if slug in groups:
            return label('doc.groupNotes', name=self.scene_title(groups[slug]))
        return label('title.documentNamed', kind=label('doc.other'), name=slug)

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
        if kind not in EVERYWHERE + THIS_CONVERSATION:
            raise ValueError('INVALID_MEMORY_CATEGORY')
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('INVALID_MEMORY_PAGE')
        if not isinstance(search, str) or len(search) > 160:
            raise ValueError('INVALID_MEMORY_SEARCH')
        search = search.strip()
        # ADR-009 operator rows (documents and job reports, feelings, ideas) come first; search applies to their titles.
        extra = (self.document_rows() if kind == 'documents' else []) + (
            self.affect_rows() if kind == 'affect' else []) + (
            self.idea_rows() if kind == 'ideas' else [])
        heads = [row for row in extra if not search or search.casefold() in searchable(row).casefold()]
        heads += (self.head_rows(kind, search) + self.self_item_rows(search)) if kind == 'self' else []
        heads += self.people_rows(search) if kind == 'people' else []
        heads += self.here_people_rows(search) if kind == 'here_people' else []
        heads += self.group_note_rows(search) if kind == 'group_notes' else []
        rows = list(heads)
        skipped = 0
        if kind in ('summary', 'source', 'interpretation'):
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
            # Every memory carries its own time: a summary when it was made, a line when it was said, a thought
            # when she formed it.
            timing = [] if messages else [
                {'$addFields': {'_memory_time': {'$ifNull': ['$generated_at', '$occurred_at', '$formed_at']}}}]
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
            # Documents and their items, job reports, and what holds of a person anywhere belong to no one
            # conversation.
            row['scene_title'] = None if kind in EVERYWHERE or row['kind'] in ('relation', 'group_notes') else self.scene_title(
                row.get('scene_id') or row.get('scope_key', '').removeprefix('scene:'))
        return {'scene_id': self.scene['_id'], 'scene_kind': self.scene.get('kind'),
                'scene_title': self.scene_title(self.scene['_id']),
                'persona': self.binding['persona'],
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
            from . import memory_tiers
            # Each section as her turns read it: the place it is in now, not the label it was written with.
            content = row = memory_tiers.placed(self.store, self.persona, key, content)
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
        elif kind == 'item':
            from . import memory_tiers
            from .documents import DocumentStore
            from .group_admin import notes_slug
            slug, _, sid = key.partition('#')
            content = memory_tiers.placed(self.store, self.persona, slug, DocumentStore(self.store, self.persona).read(slug)[1])
            row = next((section for section in (content or {}).get('sections', ()) if section['sid'] == sid), None)
            if row:
                result = {'id': identifier, 'interpretation': True, 'scope_key': 'doc:' + slug, 'source_ids': [],
                          'category': 'self' if slug in ('self', 'core') else 'group_notes'
                              if slug == notes_slug(self.scene['_id']) else 'document',
                          'usage': self.cognition.usage(identifier),
                          'body': paragraphs(row['heading'] and '### ' + row['heading'],
                                             label('doc.meta', visibility=label('visibility.' + row['visibility']),
                                                   inject=label('inject.' + row['inject']), date=''), row['body'])}
        elif kind == 'person':
            row = self.relation_records(key).get(key)
            if row:
                result = self.person_detail(key)
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
                if row.get('kind') == 'monologue':
                    from . import reasons
                    result['then'] = reasons.then(self.store, row)       # what she did after this thought
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
        if kind == 'unit' and not result.get('generated_at'):
            result['generated_at'] = row.get('occurred_at') or row.get('formed_at')
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
