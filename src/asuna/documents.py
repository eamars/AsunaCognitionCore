"""Document layer ``doc:<persona>:<slug>`` (ADR-009 ARCHITECTURE §5).

Persona, voice, dossier, ledger and working documents are whole revisable texts
stored by section on the existing state_heads/state_revisions ledger (scope
``global-safe``; visibility lives on each section). Package markdown only
seeds a missing head. There is no delete: only operator erasure writes a
tombstone section.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata

from .evidence import canonical, sha
from .state import Conflict, Denied, now

SCOPE = 'global-safe'
VISIBILITIES = ('public', 'owner_private')
INJECTS = ('always', 'on_demand', 'never')
ALWAYS_KINDS = ('persona', 'voice', 'ledger')
PREAMBLE = '_preamble'
MAX_REVISION_BYTES = 1024 * 1024
FRONT_MATTER = re.compile(r'\A\s*<!--\s*asuna-seed\s+(\{.*?\})\s*-->\s*\n?', re.S)
OPS = ('replace_section', 'append_section', 'correction', 'set_tags', 'adopt_seed')
WRITE_STAGE_OPS = ('replace_section', 'append_section', 'correction')


class DocumentError(ValueError):
    """A refused document operation; ``code`` is the stable reason."""
    def __init__(self, code, detail=''):
        super().__init__(code + (': ' + detail if detail else ''))
        self.code, self.detail = code, detail


def slugify(heading: str) -> str:
    """GitHub-style: lowercase, drop punctuation, spaces to hyphens (CJK kept)."""
    text = unicodedata.normalize('NFKC', heading).strip().lower()
    text = ''.join(ch for ch in text if ch.isalnum() or ch in ' -_' or unicodedata.category(ch).startswith('M'))
    return re.sub(r'\s', '-', text) or 'section'


def unique_sid(base: str, taken) -> str:
    sid, n = base, 1
    while sid in taken:
        n += 1
        sid = f'{base}-{n}'
    return sid


def _section(sid, heading, body, *, visibility, inject, tags=(), entry_date=None):
    value = {'sid': sid, 'heading': heading, 'body': body, 'visibility': visibility, 'inject': inject,
             'tags': list(tags), 'body_sha256': sha(body.encode())}
    if entry_date:
        value['entry_date'] = entry_date
    return value


def parse_markdown(text: str, kind: str):
    """(front_matter, sections) from seed markdown split on '##'; deterministic sids."""
    front = {}
    match = FRONT_MATTER.match(text)
    if match:
        front = json.loads(match.group(1))
        text = text[match.end():]
    # Package seeds are public by default; a person's dossier defaults to owner-private (§2.2).
    default_visibility = front.get('visibility', 'owner_private' if kind == 'dossier' else 'public')
    default_inject = front.get('inject', 'always' if kind in ALWAYS_KINDS else 'on_demand')
    default_tags = front.get('tags', [])
    parts = re.split(r'(?m)^## +(.*)$', text)
    raw = [(None, parts[0])] + [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts), 2)]
    sections, taken = [], set()
    for heading, body in raw:
        body = body.strip('\n')
        if heading is None:
            if not body.strip():
                continue
            sid = PREAMBLE
        else:
            sid = unique_sid(slugify(heading), taken)
        taken.add(sid)
        override = (front.get('sections') or {}).get(sid, {})
        sections.append(_section(sid, heading or '', body,
                                 visibility=override.get('visibility', default_visibility),
                                 inject=override.get('inject', default_inject),
                                 tags=override.get('tags', default_tags),
                                 entry_date=override.get('entry_date')))
    unknown = sorted(set(front.get('sections') or {}) - taken)
    return front, sections, unknown


def render_markdown(sections) -> str:
    out = []
    for section in sections:
        out.append(section['body'] if section['sid'] == PREAMBLE else '## ' + section['heading'] + '\n' + section['body'])
    return '\n'.join(out)


class DocumentStore:
    def __init__(self, store, persona: str):
        self.store, self.persona = store, persona

    def entity(self, slug):
        return f'doc:{self.persona}:{slug}'

    def key(self, slug):
        return self.entity(slug) + '|' + SCOPE

    def head(self, slug):
        return self.store.head(self.entity(slug), SCOPE)

    def read(self, slug):
        """(revision id, content) or (None, None)."""
        pair = self.head(slug)
        return (pair[0]['revision_id'], pair[1]['content']) if pair else (None, None)

    def revision(self, revision_id):
        return self.store.db.state_revisions.find_one({'_id': revision_id})

    def slugs(self, prefix=''):
        rows = self.store.db.state_heads.find({'_id': {'$regex': '^' + re.escape(f'doc:{self.persona}:' + prefix)}}, {'_id': 1})
        return sorted(row['_id'][len(f'doc:{self.persona}:'):-len('|' + SCOPE)] for row in rows)

    # ── writes ─────────────────────────────────────────────────────
    def _commit(self, slug, content, *, base_revision_id, reason, author, mutation_id, sources=(), extra=None):
        size = len(json.dumps(content, ensure_ascii=False).encode())
        if size > MAX_REVISION_BYTES:
            raise DocumentError('DOC_REVISION_TOO_LARGE', str(size))
        existing = self.store.db.state_revisions.find_one({'mutation_id': mutation_id})
        if existing:
            if existing.get('entity_key') != self.key(slug) or existing['content'] != content:
                raise Conflict('MUTATION_ID_CONTENT_CHANGED')
            return existing
        head = self.store.db.state_heads.find_one({'_id': self.key(slug)})
        current = head['revision_id'] if head else None
        if current != base_revision_id:
            self.store.audit('doc:' + mutation_id, 'state.conflict', {'entity': self.entity(slug),
                             'base_revision_id': base_revision_id, 'reason': 'BASE_REVISION_STALE'}, SCOPE)
            raise Conflict('BASE_REVISION_STALE')
        revision_id = sha(canonical({'mutation_id': mutation_id, 'entity': self.entity(slug)}))
        revision = self.store.put('state_revisions', {
            '_id': revision_id, 'mutation_id': mutation_id, 'entity_key': self.key(slug), 'scope_key': SCOPE,
            'content': content, 'source_ids': list(sources), 'parent_revision_id': current, 'reason': reason,
            'author': author, 'created_at': now(), **(extra or {})}, stream='doc:' + mutation_id)
        try:
            if head:
                self.store.put('state_heads', {**head, 'revision_id': revision_id}, expected=head['revision'],
                               stream='doc:' + mutation_id)
            else:
                self.store.put('state_heads', {'_id': self.key(slug), 'scope_key': SCOPE, 'revision_id': revision_id},
                               stream='doc:' + mutation_id)
        except Conflict:
            self.store.audit('doc:' + mutation_id, 'state.conflict', {'entity': self.entity(slug),
                             'base_revision_id': base_revision_id, 'reason': 'BASE_REVISION_STALE'}, SCOPE)
            raise Conflict('BASE_REVISION_STALE') from None
        return revision

    def seed(self, slug, kind, text, *, path=None, title=None, subject=None):
        """Import a package seed only when the head is missing (package upgrades never overwrite)."""
        if self.head(slug):
            return None
        front, sections, unknown = parse_markdown(text, kind)
        content = {'kind': kind, 'title': title or front.get('title') or slug, 'sections': sections,
                   'source': {'origin': 'seed', 'path': path, 'sha256': sha(text.encode())}}
        if subject:
            content['subject'] = subject
        revision = self._commit(slug, content, base_revision_id=None, reason='package seed', author='seed',
                                mutation_id=f'seed:{self.persona}:{slug}', extra={'seed_unknown_sids': unknown} if unknown else None)
        return revision

    def apply(self, slug, intent, body=None, *, base_revision_id, author, mutation_id, budget=None):
        """One write intent. ``budget(slug, new_content)`` may refuse growth (PERSONA_RENDER_OVER_BUDGET)."""
        op = intent.get('op')
        if op not in OPS or op == 'adopt_seed':
            raise DocumentError('DOC_OP_UNKNOWN', str(op))
        reason = intent.get('reason')
        if not isinstance(reason, str) or not 1 <= len(reason) <= 2000:
            raise DocumentError('DOC_REASON_REQUIRED')
        replay = self.store.db.state_revisions.find_one({'mutation_id': mutation_id})
        if replay and replay.get('entity_key') == self.key(slug):
            return replay                      # the same intent already committed (crash recovery)
        revision_id, content = self.read(slug)
        if revision_id != base_revision_id:
            raise Conflict('BASE_REVISION_STALE')
        if content is None:
            if op != 'append_section':
                raise DocumentError('DOC_NOT_FOUND', slug)
            kind = 'dossier' if slug.startswith('dossier:') else 'working'
            content = {'kind': kind, 'title': slug, 'sections': [], 'source': {'origin': 'asuna'}}
            if kind == 'dossier':
                content['subject'] = slug.split(':', 1)[1]
        content = copy.deepcopy(content)
        kind, sections = content['kind'], content['sections']
        if kind == 'contract':
            raise DocumentError('DOC_OP_NOT_ALLOWED', 'contract documents are read-only')
        by_sid = {s['sid']: s for s in sections}
        if op in WRITE_STAGE_OPS and (not isinstance(body, str) or not body.strip()):
            raise DocumentError('DOC_BODY_REQUIRED')
        if op == 'replace_section':
            target = by_sid.get(intent.get('sid'))
            if not target:
                raise DocumentError('DOC_SECTION_NOT_FOUND', str(intent.get('sid')))
            if kind == 'dossier' and 'preamble' not in target['tags'] and target['sid'] != PREAMBLE:
                raise DocumentError('DOC_OP_NOT_ALLOWED', 'dossier entries are append-only; use correction')
            if intent.get('body_sha256') and intent['body_sha256'] != target['body_sha256']:
                raise Conflict('BASE_REVISION_STALE')
            target.update(body=body, body_sha256=sha(body.encode()))
        elif op in ('append_section', 'correction'):
            heading = intent.get('heading') or ''
            if op == 'correction':
                if kind not in ('dossier', 'ledger'):
                    raise DocumentError('DOC_OP_NOT_ALLOWED', 'correction applies to dossier entries and ledgers')
                original = by_sid.get(intent.get('sid'))
                if not original:
                    raise DocumentError('DOC_SECTION_NOT_FOUND', str(intent.get('sid')))
                heading = heading or '更正：' + (original['heading'] or original['sid'])
            if not heading.strip():
                raise DocumentError('DOC_HEADING_REQUIRED')
            tags = list(intent.get('tags') or [])
            if kind == 'dossier' and op == 'append_section' and 'preamble' not in tags:
                if not intent.get('entry_date'):
                    raise DocumentError('DOC_ENTRY_DATE_REQUIRED')
                if 'entry' not in tags:
                    tags.append('entry')
            if op == 'correction':
                tags = [*dict.fromkeys([*tags, 'correction'])]
            visibility = intent.get('visibility') or 'owner_private'
            inject = intent.get('inject') or ('always' if kind in ALWAYS_KINDS else 'on_demand')
            if visibility not in VISIBILITIES or inject not in INJECTS:
                raise DocumentError('DOC_TAGS_INVALID')
            section = _section(unique_sid(slugify(heading), by_sid), heading, body, visibility=visibility,
                               inject=inject, tags=tags, entry_date=intent.get('entry_date'))
            if op == 'correction':
                section['corrects'] = intent['sid']
            sections.append(section)
        elif op == 'set_tags':
            target = by_sid.get(intent.get('sid'))
            if not target:
                raise DocumentError('DOC_SECTION_NOT_FOUND', str(intent.get('sid')))
            for field, allowed in (('visibility', VISIBILITIES), ('inject', INJECTS)):
                if field in intent:
                    if intent[field] not in allowed:
                        raise DocumentError('DOC_TAGS_INVALID', field)
                    target[field] = intent[field]
            if 'tags' in intent:
                target['tags'] = list(intent['tags'])
        if budget:
            budget(slug, content)
        return self._commit(slug, content, base_revision_id=base_revision_id, reason=reason, author=author,
                            mutation_id=mutation_id)

    def adopt_seed(self, slug, kind, text, *, base_revision_id, author, mutation_id, reason='adopt package seed'):
        """Merge a newer package seed by sid; sections both sides changed are listed, never overwritten."""
        revision_id, content = self.read(slug)
        if content is None:
            return {'state': 'seeded', 'revision': self.seed(slug, kind, text)}
        if revision_id != base_revision_id:
            raise Conflict('BASE_REVISION_STALE')
        seed_rev = self.store.db.state_revisions.find_one({'mutation_id': f'seed:{self.persona}:{slug}'})
        seeded = {s['sid']: s for s in (seed_rev['content']['sections'] if seed_rev else [])}
        _, incoming, _ = parse_markdown(text, kind)
        content = copy.deepcopy(content)
        current = {s['sid']: s for s in content['sections']}
        conflicts, changed = [], []
        for section in incoming:
            mine = current.get(section['sid'])
            if mine is None:
                content['sections'].append(section); changed.append(section['sid'])
            elif mine['body_sha256'] == section['body_sha256']:
                continue
            elif seeded.get(section['sid'], {}).get('body_sha256') == mine['body_sha256']:
                mine.update(body=section['body'], body_sha256=section['body_sha256']); changed.append(section['sid'])
            else:
                conflicts.append(section['sid'])
        if not changed:
            return {'state': 'unchanged', 'conflicts': conflicts}
        revision = self._commit(slug, content, base_revision_id=base_revision_id, reason=reason, author=author,
                                mutation_id=mutation_id)
        return {'state': 'updated', 'changed': changed, 'conflicts': conflicts, 'revision_id': revision['_id']}
