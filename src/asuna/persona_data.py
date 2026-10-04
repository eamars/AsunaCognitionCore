"""Persona data API and probes (ADR-009 PERSONA_CONTRACT §5–§6).

Only persona jobs call this, through the job's stdio pipe (the pipe is the
token; one persona per run). Writes need ``persona_data.write`` and an
authorized source root in ``cohabiting``; reads need ``probe``. Every write is
idempotent by origin + source_identity + content sha, supports ``dry_run`` and
is audited in ``persona-data:<origin>`` with the run id. Probes take exactly the
path a real turn takes, so "can she recall it / see it" is answered honestly.
"""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

from .documents import (DocumentError, DocumentStore, PREAMBLE, _section, slugify, unique_sid, SCOPE as DOC_SCOPE)
from .evidence import canonical, sha
from .state import Conflict, Denied, now
from . import visibility

WRITE_METHODS = ('documents.upsert', 'documents.append', 'affect.import', 'memory.upsert', 'policy.set',
                 'artifacts.snapshot', 'report.put')
READ_METHODS = ('documents.get', 'probe.retrieve', 'probe.context', 'sources.list')
MAX_ITEMS, MAX_BYTES, MAX_SNAPSHOT = 200, 2 * 1024 * 1024, 8 * 1024 * 1024
INVENTED_MARK = '（自述编写，非共同经历）'
SOURCE_STATES = ('cohabiting', 'cutover')


class DataError(ValueError):
    def __init__(self, code, detail=''):
        super().__init__(code + (': ' + str(detail) if detail else ''))
        self.code, self.detail = code, str(detail)


def persona_sources(config, persona):
    """{root id: {path, state, exclude}} from the owner's local config; malformed roots are refused."""
    out = {}
    for root_id, spec in ((config.get('persona_sources') or {}).get(persona) or {}).items():
        if not isinstance(spec, dict) or spec.get('state') not in SOURCE_STATES or not spec.get('path'):
            raise ValueError(f'PERSONA_SOURCE_INVALID: {root_id}')
        out[root_id] = {'path': spec['path'], 'state': spec['state'], 'exclude': list(spec.get('exclude') or [])}
    return out


def persona_runtime(config, persona):
    return (config.get('persona_runtime') or {}).get(persona) or {}


class PersonaDataAPI:
    def __init__(self, store, persona, *, run_id, job_id, grants, sources, retrieval=None):
        self.store, self.persona, self.run_id, self.job_id = store, persona, run_id, job_id
        self.grants, self.sources, self.retrieval = set(grants), dict(sources), retrieval
        self.docs = DocumentStore(store, persona)
        self.reports = []

    # ── dispatch ────────────────────────────────────────────────────
    def dispatch(self, method, args):
        if not isinstance(args, dict):
            raise DataError('REQUEST_INVALID')
        if args.get('persona', self.persona) != self.persona:
            raise DataError('PERSONA_SCOPE_DENIED', args.get('persona'))
        limit = MAX_SNAPSHOT * 4 // 3 + 4096 if method == 'artifacts.snapshot' else MAX_BYTES
        if len(json.dumps(args, ensure_ascii=False).encode()) > limit:
            raise DataError('REQUEST_TOO_LARGE')
        for key in ('sections', 'events', 'amendments', 'units', 'params', 'items'):
            if isinstance(args.get(key), list) and len(args[key]) > MAX_ITEMS:
                raise DataError('TOO_MANY_ITEMS', key)
        if method in WRITE_METHODS:
            if 'persona_data.write' not in self.grants:
                raise DataError('GRANT_REQUIRED', 'persona_data.write')
            if method != 'report.put':
                self._origin(args.get('origin'))
        elif method in READ_METHODS:
            if 'probe' not in self.grants:
                raise DataError('GRANT_REQUIRED', 'probe')
        else:
            raise DataError('METHOD_UNKNOWN', method)
        handler = getattr(self, method.replace('.', '_'))
        result = handler(args)
        if method in WRITE_METHODS and not args.get('dry_run'):
            self.store.audit('persona-data:' + (args.get('origin') or 'report'), 'persona_data.write',
                             {'run_id': self.run_id, 'job': self.job_id, 'method': method,
                              'summary': {k: v for k, v in result.items() if isinstance(v, (int, str))}},
                             visibility.owner_private_scope(self.persona))
        return result

    def _origin(self, origin):
        if origin not in self.sources:
            raise DataError('SOURCE_NOT_AUTHORIZED', origin)
        if self.sources[origin] != 'cohabiting':
            raise DataError('SOURCE_CUTOVER', origin)

    def _visibility(self, value, defaulted, label):
        if value is None:
            defaulted.append(label)
            return 'owner_private'
        if value not in visibility.VISIBILITIES:
            raise DataError('VISIBILITY_INVALID', label)
        return value

    # ── documents ───────────────────────────────────────────────────
    def documents_upsert(self, args):
        """Whole-document import by sections; cohabiting conflict rules (MEMORY §6.2)."""
        slug, kind, origin = args['slug'], args['kind'], args['origin']
        defaulted, taken, sections = [], set(), []
        for index, item in enumerate(args.get('sections') or []):
            heading = item.get('heading') or ''
            sid = item.get('sid') or (PREAMBLE if not heading else unique_sid(slugify(heading), taken))
            taken.add(sid)
            sections.append(_section(sid, heading, item['body'],
                                     visibility=self._visibility(item.get('visibility'), defaulted, sid),
                                     inject=item.get('inject') or ('always' if kind in ('persona', 'voice', 'ledger') else 'on_demand'),
                                     tags=item.get('tags') or [], entry_date=item.get('entry_date')))
        source = dict(args.get('source') or {})
        content_sha = sha(canonical([kind, args.get('title'), args.get('subject'), sections]))
        mutation_id = f"import:{self.persona}:{origin}:{args['source_identity']}:{content_sha}"
        revision_id, current = self.docs.read(slug)
        next_id = sha(canonical({'mutation_id': mutation_id, 'entity': self.docs.entity(slug)}))
        content = {'kind': kind, 'title': args.get('title') or slug, 'sections': sections,
                   'source': {'origin': origin, 'source_identity': args['source_identity'], 'path': source.get('path'),
                              'sha256': source.get('sha256'), 'content_sha256': content_sha, 'import_base': next_id}}
        if args.get('subject'):
            content['subject'] = args['subject']
        result = {'slug': slug, 'visibility_defaulted': defaulted}
        if current is None:
            action = 'created'
        elif (current.get('source') or {}).get('content_sha256') == content_sha:
            return {**result, 'action': 'unchanged', 'revision_id': revision_id}
        elif (current.get('source') or {}).get('origin') != origin or revision_id != (current.get('source') or {}).get('import_base'):
            # The character (or another origin) changed it since import: never overwrite; report RED.
            changed = sorted({s['sid'] for s in current['sections']} ^ {s['sid'] for s in sections}
                             | {s['sid'] for s in sections for c in current['sections'] if c['sid'] == s['sid'] and c['body_sha256'] != s['body_sha256']})
            return {**result, 'action': 'conflict', 'revision_id': revision_id, 'differs': changed}
        else:
            action = 'updated'
        if args.get('dry_run'):
            return {**result, 'action': action, 'dry_run': True, 'sections': len(sections)}
        from .render import budget_gate
        if slug in ('persona', 'voice'):
            budget_gate(self.store, self.persona)(slug, content)
        revision = self.docs._commit(slug, content, base_revision_id=revision_id, reason=f'import from {origin}',
                                     author='persona_job:' + self.job_id, mutation_id=mutation_id)
        return {**result, 'action': action, 'revision_id': revision['_id'], 'sections': len(sections)}

    def documents_append(self, args):
        """Append-only union by origin + source_identity (dossier entries, logs)."""
        slug, origin, item = args['slug'], args['origin'], args['section']
        revision_id, current = self.docs.read(slug)
        defaulted = []
        if current and any(s.get('source_identity') == args['source_identity'] and s.get('origin') == origin
                           for s in current['sections']):
            same = [s for s in current['sections'] if s.get('source_identity') == args['source_identity']][0]
            if same['body_sha256'] == sha(item['body'].encode()):
                return {'action': 'unchanged', 'slug': slug, 'revision_id': revision_id}
            return {'action': 'conflict', 'slug': slug, 'revision_id': revision_id, 'differs': [same['sid']]}
        content = copy.deepcopy(current) if current else {
            'kind': 'dossier' if slug.startswith('dossier:') else 'working', 'title': slug, 'sections': [],
            'source': {'origin': origin}, **({'subject': slug.split(':', 1)[1]} if slug.startswith('dossier:') else {})}
        if content['kind'] == 'dossier' and not item.get('entry_date') and 'preamble' not in (item.get('tags') or []):
            raise DataError('DOC_ENTRY_DATE_REQUIRED')
        tags = list(item.get('tags') or [])
        if content['kind'] == 'dossier' and 'preamble' not in tags and 'entry' not in tags:
            tags.append('entry')
        section = _section(unique_sid(slugify(item.get('heading') or args['source_identity']), {s['sid'] for s in content['sections']}),
                           item.get('heading') or '', item['body'],
                           visibility=self._visibility(item.get('visibility'), defaulted, args['source_identity']),
                           inject=item.get('inject') or 'on_demand', tags=tags, entry_date=item.get('entry_date'))
        section.update(origin=origin, source_identity=args['source_identity'])
        content['sections'].append(section)
        if args.get('dry_run'):
            return {'action': 'appended', 'slug': slug, 'dry_run': True, 'visibility_defaulted': defaulted}
        revision = self.docs._commit(slug, content, base_revision_id=revision_id, reason=f'append from {origin}',
                                     author='persona_job:' + self.job_id,
                                     mutation_id=f"append:{self.persona}:{origin}:{args['source_identity']}")
        return {'action': 'appended', 'slug': slug, 'revision_id': revision['_id'], 'visibility_defaulted': defaulted}

    def documents_get(self, args):
        revision_id, content = self.docs.read(args['slug'])
        if content is None:
            raise DataError('DOC_NOT_FOUND', args['slug'])
        return {'slug': args['slug'], 'revision_id': revision_id, 'content': content}

    # ── affect, memory, policy, artifacts, reports ─────────────────
    def affect_import(self, args):
        from .affect import AffectLedger
        from .render import model_and_policy
        ledger = AffectLedger(self.store, self.persona, *model_and_policy(self.store, self.persona))
        return ledger.import_batch(args['origin'], args.get('events') or [], args.get('amendments') or [],
                                   dry_run=bool(args.get('dry_run')))

    def memory_upsert(self, args):
        from .config import character_id
        origin, report = args['origin'], {'created': 0, 'updated': 0, 'unchanged': 0, 'pending_embedding': 0,
                                          'visibility_defaulted': []}
        for unit in args.get('units') or []:
            vis = self._visibility(unit.get('visibility'), report['visibility_defaulted'], unit.get('source_identity'))
            scope = 'global-safe' if vis == 'public' else visibility.owner_private_scope(self.persona)
            body = unit['body_markdown']
            doc = {'_id': 'imp-' + sha(canonical([scope, origin, unit['source_identity']])), 'scope_key': scope,
                   'policy_epoch': 1, 'character_id': character_id(self.store.config), 'persona': self.persona,
                   'kind': 'imported_entry', 'entry_type': unit.get('entry_type'), 'body_markdown': body,
                   'epistemic_type': unit.get('epistemic_type') or 'reported_speech', 'occurred_at': unit.get('occurred_at'),
                   'source_window': unit.get('source_window'), 'invented': bool(unit.get('invented')), 'origin': origin,
                   'source_identity': unit['source_identity'], 'source_event_ids': [], 'depends_on': [],
                   'status': 'active', 'embedding_status': 'PENDING', 'content_sha256': sha(canonical([body, unit.get('source_window'),
                                                                                                     bool(unit.get('invented')), vis]))}
            existing = self.store.db.memory_units.find_one({'_id': doc['_id']})
            if existing and existing.get('content_sha256') == doc['content_sha256']:
                report['unchanged'] += 1
                continue
            report['updated' if existing else 'created'] += 1
            report['pending_embedding'] += 1
            if args.get('dry_run'):
                continue
            if existing:
                self.store.put('memory_units', {**existing, **doc}, expected=existing['revision'], stream='persona-data:' + origin)
            else:
                self.store.put('memory_units', doc, stream='persona-data:' + origin)
        return report

    def policy_set(self, args):
        from .policy import PolicyStore
        from .render import model_and_policy
        model, _ = model_and_policy(self.store, self.persona)
        policy = PolicyStore(self.store, self.persona, model)
        report = {'set': 0, 'rejected': []}
        for index, item in enumerate(args.get('params') or []):
            try:
                policy.validate([item])
                if not args.get('dry_run'):
                    policy.set([item], base_revision_id=policy.read()[0], reason=f"import from {args['origin']}",
                               author='persona_job:' + self.job_id,
                               mutation_id=f"policy:{self.persona}:{args['origin']}:{item['key']}:{sha(canonical(item))}")
                report['set'] += 1
            except (ValueError, Denied, Conflict) as exc:
                report['rejected'].append({'index': index, 'key': item.get('key'), 'code': str(exc).split(':')[0]})
        return report

    def artifacts_snapshot(self, args):
        from .blobs import BlobStore
        data = base64.b64decode(args['content'], validate=True)
        if len(data) > MAX_SNAPSHOT:
            raise DataError('SNAPSHOT_TOO_LARGE')
        if sha(data) != args['sha256']:
            raise DataError('SNAPSHOT_SHA_MISMATCH')
        if args.get('dry_run'):
            return {'action': 'snapshot', 'dry_run': True, 'sha256': args['sha256']}
        stored = BlobStore(self.store).put_once(data, visibility.owner_private_scope(self.persona), 'source_snapshot',
                                                source_ids=[f"{args['origin']}:{args.get('path')}"])
        return {'artifact_id': stored['artifact_id'], 'sha256': stored['sha256'], 'deduplicated': bool(stored.get('deduplicated'))}

    def report_put(self, args):
        from .blobs import BlobStore
        if args.get('status') not in ('ok', 'red', 'error'):
            raise DataError('REPORT_STATUS_INVALID')
        body = json.dumps({'run_id': self.run_id, 'job': self.job_id, 'status': args['status'],
                           'summary': args.get('summary', ''), 'items': args.get('items') or [], 'at': now()},
                          ensure_ascii=False).encode()
        stored = BlobStore(self.store).put(body, visibility.owner_private_scope(self.persona), 'persona_job_report',
                                           source_ids=[self.run_id])
        self.reports.append({'artifact_id': stored['artifact_id'], 'status': args['status']})
        return {'artifact_id': stored['artifact_id']}

    # ── probes ──────────────────────────────────────────────────────
    def _probe_scope(self, as_class):
        if as_class == visibility.OWNER_PRIVATE:
            local = self.store.config['chat']
            scene = self.store.db.scenes.find_one({'_id': local['scene_id']})
            return scene['scope_key'], scene['policy_epoch'], visibility.owner_private_scope(self.persona)
        if as_class == visibility.PUBLIC:
            return 'scene:__probe_public__', 1, None      # a public view sees global-safe only
        raise DataError('PROBE_CLASS_INVALID', as_class)

    def probe_retrieve(self, args):
        from .persona_model import effective
        from .render import model_and_policy
        if self.retrieval is None:
            raise DataError('PROBE_RETRIEVAL_UNAVAILABLE')
        k = int(args.get('k') or 6)
        if not 1 <= k <= 12:
            raise DataError('PROBE_K_INVALID')
        scope, epoch, private = self._probe_scope(args.get('as'))
        model, policy = model_and_policy(self.store, self.persona)
        selected, manifest = self.retrieval.search(scope, epoch, args['query'], private_scope=private,
                                                   coverage_floor=effective(model, 'memory.coverage_floor', policy) or 0)
        ranks = manifest.get('ranks', {})
        items = [{'id': m['_id'], 'kind': m.get('kind'), 'score': (ranks.get(m['_id']) or {}).get('score', 0.0),
                  'source_window': m.get('source_window'),
                  'excerpt': (INVENTED_MARK if m.get('invented') else '') + m.get('body_markdown', '')[:400]}
                 for m in selected[:k]]
        return {'items': items, **{key: manifest.get(key) for key in ('coverage', 'coverage_score', 'coverage_basis')}}

    def probe_context(self, args):
        from .render import render_system, readable_sections
        cls = args.get('as')
        if cls not in visibility.VISIBILITIES:
            raise DataError('PROBE_CLASS_INVALID', cls)
        text, ref = render_system(self.store, self.persona, cls)
        blocks = {}
        for slug in self.docs.slugs():
            _, content = self.docs.read(slug)
            shown = readable_sections(content, cls)
            if shown and (not args.get('blocks') or slug in args['blocks']):
                blocks[slug] = [{'sid': s['sid'], 'heading': s['heading']} for s in shown]
        return {'render_sha256': ref['render_sha256'], 'system_ref': ref, 'blocks': blocks}

    def sources_list(self, args):
        return {'sources': dict(self.sources)}


def check_export_path(target, root):
    """Export only outside the repository worktree, or into a git-ignored path (R-7)."""
    import subprocess
    target, root = Path(target).resolve(), Path(root).resolve()
    if not target.is_relative_to(root):
        return target
    relative = target.relative_to(root).as_posix() + '/probe.md'
    ignored = subprocess.run(['git', 'check-ignore', '-q', relative], cwd=root).returncode == 0
    if not ignored:
        raise DataError('EXPORT_PATH_TRACKED', 'export_dir must be outside the worktree or git-ignored')
    return target


def export_documents(store, persona, target, root):
    """Render the document layer to markdown; every section carries its revision id and visibility."""
    target = check_export_path(target, root)
    docs = DocumentStore(store, persona)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for slug in docs.slugs():
        revision_id, content = docs.read(slug)
        lines = [f"<!-- asuna-export {json.dumps({'persona': persona, 'slug': slug, 'kind': content['kind'], 'revision_id': revision_id}, ensure_ascii=False)} -->",
                 f"# {content.get('title') or slug}"]
        for section in content['sections']:
            label = f"<!-- section {json.dumps({'sid': section['sid'], 'visibility': section['visibility'], 'inject': section['inject'], 'tags': section.get('tags', []), 'revision_id': revision_id}, ensure_ascii=False)} -->"
            lines += [label, section['body'] if section['sid'] == PREAMBLE else f"## {section['heading']}\n{section['body']}"]
        path = target / (slug.replace(':', '__') + '.md')
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        written.append(path.name)
    return {'exported': written, 'directory': str(target)}
