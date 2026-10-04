"""Optional DECIDE fields (ADR-009 §9.1, examples/decision-delta.schema.json).

Each item is validated and committed on its own. A rejected item is recorded in
``episode.rejections`` as ``{field, index, code, detail}`` and never fails the
turn; only an unparseable decision or a missing base field is BAD_DECISION_JSON.
Order: affect_ops → affect_adopt → affect → policy_set → pin → write_docs
(set_tags/adopt_seed directly, the rest through one WRITE stage each).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .config import prompt_path, schema
from .documents import DocumentError, DocumentStore, WRITE_STAGE_OPS
from . import visibility

DELTA = schema('decision-delta.schema.json')
DELTA_KEYS = tuple(DELTA['properties'])
ORDER = ('affect_ops', 'affect_adopt', 'affect', 'policy_set', 'pin', 'write_docs', 'promote')
# Fields whose engines arrive in later phases are refused explicitly, not silently dropped.
NOT_YET = {}


def split(decision: dict):
    """(base decision for the existing schema, optional ADR-009 fields)."""
    base = {k: v for k, v in decision.items() if k not in DELTA_KEYS}
    return base, {k: decision[k] for k in DELTA_KEYS if k in decision}


def rejection(field, index, code, detail=''):
    return {'field': field, 'index': index, 'code': code, 'detail': str(detail)[:500]}


def code_of(exc) -> str:
    if isinstance(exc, DocumentError) or hasattr(exc, 'code'):
        return exc.code
    return str(exc).split(':', 1)[0].strip() or type(exc).__name__


def validate_items(delta: dict):
    """({field: [(index, item)]}, rejections) — item-level schema checks only."""
    valid, rejected = {}, []
    for field, items in delta.items():
        spec = DELTA['properties'][field]
        if not isinstance(items, list):
            rejected.append(rejection(field, None, 'FIELD_NOT_A_LIST'))
            continue
        item_schema = {'definitions': DELTA['definitions'], **spec['items']}
        for index, item in enumerate(items):
            if index >= spec.get('maxItems', len(items)):
                rejected.append(rejection(field, index, 'TOO_MANY_ITEMS', spec.get('maxItems')))
                continue
            try:
                jsonschema.validate(item, item_schema)
            except jsonschema.ValidationError as exc:
                rejected.append(rejection(field, index, 'ITEM_INVALID', f'{list(exc.absolute_path)}: {exc.message}'))
                continue
            valid.setdefault(field, []).append((index, item))
    return valid, rejected


def apply(coordinator, ep):
    """Apply every optional field once; results and rejections land on the episode."""
    if ep.get('delta_applied') or not ep.get('decision_delta'):
        return ep
    store = coordinator.store
    valid, rejected = validate_items(ep['decision_delta'])
    cls = ep['manifest'].get('session_class', visibility.PUBLIC)
    results = dict(ep.get('delta_results') or {})
    ledger = None
    for field in ORDER:
        for index, item in valid.get(field, []):
            if field in NOT_YET:
                rejected.append(rejection(field, index, 'FIELD_NOT_AVAILABLE', 'arrives in ' + NOT_YET[field]))
            elif field in ('affect_ops', 'affect_adopt', 'affect'):
                if ledger is None:
                    from .affect import AffectLedger
                    from .render import model_and_policy
                    ledger = AffectLedger(store, ep['persona'], *model_and_policy(store, ep['persona']))
                try:
                    if field == 'affect':
                        row = ledger.commit(ep, index, item, cls)
                        results.setdefault('affect', []).append({'index': index, 'event_id': row['_id'], 'kind': row.get('kind'),
                                                                 'val': row.get('val'), 'arl': row.get('arl')})
                    elif field == 'affect_ops':
                        row = ledger.amend(ep, index, item, cls)
                        results.setdefault('affect_ops', []).append({'index': index, 'op': item['op'], 'event_id': item['event_id']})
                    else:
                        row = ledger.adopt(ep, index, item, cls)
                        results.setdefault('affect_adopt', []).append({'index': index, 'proposal_id': item['proposal_id'],
                                                                       'decision': item['decision'],
                                                                       'event_id': row['_id'] if row else None})
                except Exception as exc:  # each item is independent
                    rejected.append(rejection(field, index, code_of(exc), exc))
            elif field == 'policy_set':
                _policy_set(store, ep, cls, index, item, results, rejected, getattr(coordinator, 'scheduler', None))
            elif field == 'pin':
                _pin(store, ep, cls, index, item, results, rejected)
            elif field == 'write_docs':
                ep = _write(coordinator, ep, cls, index, item, results, rejected)
            elif field == 'promote':
                _promote(store, ep, cls, index, item, results, rejected)
    return coordinator._update(ep, rejections=[*(ep.get('rejections') or []), *rejected],
                               delta_results=results, delta_applied=True)


def _policy_set(store, ep, cls, index, item, results, rejected, scheduler=None):
    if cls != visibility.OWNER_PRIVATE:
        rejected.append(rejection('policy_set', index, 'POLICY_SET_REQUIRES_OWNER_PRIVATE'))
        return
    from .policy import PolicyStore
    from .render import model_and_policy
    model, _ = model_and_policy(store, ep['persona'])
    policy = PolicyStore(store, ep['persona'], model)
    try:
        spec_what = policy.validate([{'key': item['key'], 'value': item['value'], 'what': item['reason'][:300]}])
        what = ((model.get('policy_keys') or {}).get(item['key']) or {}).get('what') or spec_what[item['key']]['what']
        revision = policy.set([{'key': item['key'], 'value': item['value'], 'what': what}],
                              base_revision_id=policy.read()[0], reason=item['reason'], author='character',
                              mutation_id=f"{ep['_id']}:policy_set:{index}", sources=[ep['source_event_id']])
        results.setdefault('policy_set', []).append({'index': index, 'key': item['key'], 'value': item['value'],
                                                     'revision_id': revision['_id']})
        if scheduler and hasattr(scheduler, 'ensure_presence') and item['key'].startswith(('heartbeat.', 'rhythm.')):
            # A new rhythm takes effect through schedule_update, never delete + create.
            scheduler.ensure_presence()
            scheduler.ensure_settlement()
    except Exception as exc:  # each item is independent
        rejected.append(rejection('policy_set', index, code_of(exc), exc))


def _pin(store, ep, cls, index, item, results, rejected):
    memory = store.db.memory_units.find_one({'_id': item['memory_id']})
    readable = {ep['scope_key'], 'global-safe', *([visibility.owner_private_scope(ep['persona'])]
                                                 if cls == visibility.OWNER_PRIVATE else [])}
    if not memory or memory.get('status') != 'active' or memory.get('scope_key') not in readable:
        rejected.append(rejection('pin', index, 'PIN_MEMORY_NOT_READABLE', item['memory_id']))
        return
    if item['memory_id'] not in ep['context'].get('ref_index', []):
        rejected.append(rejection('pin', index, 'PIN_MEMORY_NOT_IN_CONTEXT', item['memory_id']))
        return
    store.put('memory_units', {**memory, 'pinned': item['pinned']}, expected=memory['revision'], stream=ep['_id'])
    results.setdefault('pin', []).append({'index': index, 'memory_id': item['memory_id'], 'pinned': item['pinned']})


def _promote(store, ep, cls, index, item, results, rejected):
    """Settlement only: quota, ≥ min_roots different turns and ≥ min_dates local dates behind the sources."""
    from .config import character_id
    from .evidence import canonical, sha
    from .persona_model import effective, timezone as persona_timezone
    from .render import model_and_policy
    from .rhythm import episode_dates, selections
    if ep.get('episode_kind') != 'settlement':
        rejected.append(rejection('promote', index, 'PROMOTE_ONLY_IN_SETTLEMENT'))
        return
    model, policy = model_and_policy(store, ep['persona'])
    quota = int(effective(model, 'memory.promotion.daily_quota', policy) or 0)
    if len(results.get('promote', [])) >= quota:
        rejected.append(rejection('promote', index, 'PROMOTION_QUOTA', quota))
        return
    picked = selections(store, effective(model, 'memory.promotion.window_days', policy) or 7)
    episodes = set()
    for source in item['source_ids']:
        unit = store.db.memory_units.find_one({'_id': source}, {'episode_id': 1})
        if store.db.episodes.find_one({'_id': source}, {'_id': 1}):
            episodes.add(source)
        elif source.startswith('in-') and store.db.episodes.find_one({'_id': source[3:]}, {'_id': 1}):
            episodes.add(source[3:])
        elif unit:
            episodes.update([unit['episode_id']] if unit.get('episode_id') else picked.get(source, []))
    zone, _ = persona_timezone(model, policy, store.config)
    dates = set(episode_dates(store, episodes, zone).values())
    need_roots = int(effective(model, 'memory.promotion.min_roots', policy) or 2)
    need_dates = int(effective(model, 'memory.promotion.min_dates', policy) or 2)
    if len(episodes) < need_roots or len(dates) < need_dates:
        rejected.append(rejection('promote', index, 'PROMOTION_SOURCES_INSUFFICIENT',
                                  f'{len(episodes)} turns / {len(dates)} dates; need {need_roots} / {need_dates}'))
        return
    scope = 'global-safe' if item.get('visibility') == 'public' else visibility.owner_private_scope(ep['persona'])
    body = f"事实：{item['fact']}\n评价：{item['appraisal']}\n信号：{item['signal']}"
    doc = {'_id': 'mu-' + sha(canonical([ep['_id'], 'promote', index])), 'kind': 'memory_unit', 'scope_key': scope,
           'policy_epoch': 1, 'persona': ep['persona'], 'character_id': character_id(store.config),
           'fact': item['fact'], 'appraisal': item['appraisal'], 'signal': item['signal'], 'body_markdown': body,
           'epistemic_type': 'character_interpretation', 'source_ids': item['source_ids'],
           'source_event_ids': item['source_ids'], 'depends_on': item['source_ids'], 'episode_id': ep['_id'],
           'status': 'active', 'embedding_status': 'PENDING', 'origin': 'asuna'}
    if not store.db.memory_units.find_one({'_id': doc['_id']}):
        store.put('memory_units', doc, stream=ep['_id'])
    results.setdefault('promote', []).append({'index': index, 'memory_id': doc['_id'], 'scope_key': scope})


def _seed_text(store, slug):
    for seed in (store.config.get('persona_contribution') or {}).get('seeds', []):
        if seed.get('slug') == slug:
            return seed['kind'], Path(seed['path']).read_text(encoding='utf-8')
    return None, None


def _write(coordinator, ep, cls, index, item, results, rejected):
    store = coordinator.store
    done = {r['index'] for r in (ep.get('write_results') or [])}
    if index in done:
        return ep
    if cls != visibility.OWNER_PRIVATE:
        rejected.append(rejection('write_docs', index, 'DOC_WRITE_REQUIRES_OWNER_PRIVATE'))
        return ep
    from .render import budget_gate
    docs = DocumentStore(store, ep['persona'])
    slug = item['doc']
    base = (ep['manifest'].get('documents') or {}).get(slug, docs.read(slug)[0])
    mutation_id = f"{ep['_id']}:write:{index}"
    try:
        if item['op'] == 'adopt_seed':
            kind, text = _seed_text(store, slug)
            if text is None:
                raise DocumentError('DOC_SEED_NOT_FOUND', slug)
            outcome = docs.adopt_seed(slug, kind, text, base_revision_id=base, author='character',
                                      mutation_id=mutation_id, reason=item['reason'])
            result = {'index': index, 'doc': slug, 'op': 'adopt_seed', **{k: v for k, v in outcome.items() if k != 'revision'}}
        else:
            body = None
            if item['op'] in WRITE_STAGE_OPS:
                body = coordinator._stage(ep, 'WRITE', index, instruction=_write_instruction(store, docs, slug, item))
            revision = docs.apply(slug, item, body, base_revision_id=base, author='character', mutation_id=mutation_id,
                                  budget=budget_gate(store, ep['persona']))
            result = {'index': index, 'doc': slug, 'op': item['op'], 'revision_id': revision['_id'],
                      'sid': item.get('sid'), 'heading': item.get('heading')}
        results.setdefault('write_docs', []).append(result)
        return coordinator._update(ep, write_results=[*(ep.get('write_results') or []), result])
    except Exception as exc:
        rejected.append(rejection('write_docs', index, code_of(exc), exc))
        return coordinator._update(ep, write_results=[*(ep.get('write_results') or []),
                                                      {'index': index, 'rejected': code_of(exc)}])


def _write_instruction(store, docs, slug, item):
    from .render import budget_limit, estimate_tokens, render_status
    _, content = docs.read(slug)
    target = next((s for s in (content or {}).get('sections', []) if s['sid'] == item.get('sid')), None)
    status = render_status(store, docs.persona) if slug in ('persona', 'voice') else None
    payload = {'intent': item, 'doc_kind': (content or {}).get('kind') or ('dossier' if slug.startswith('dossier:') else 'working'),
               'current_section': target and {'sid': target['sid'], 'heading': target['heading'], 'body': target['body']},
               'constraints': {'dossier': '条目只追加；更正用 correction，原条目不改',
                               'contract': '只读'}.get((content or {}).get('kind'), '整节替换或追加；必须写理由'),
               'budget_remaining_tokens': (status['limit_tokens'] - status['estimate_tokens'])
               if status and status['limit_tokens'] else None}
    return prompt_path(store.config, 'stage_write.md').read_text(encoding='utf-8') + '\n' + json.dumps(payload, ensure_ascii=False)


def read_sections(store, ep, items, cls):
    """``next=recall`` with ``read``: readable section text joins the recall context."""
    docs, out, rejected = DocumentStore(store, ep['persona']), [], []
    for index, item in items:
        _, content = docs.read(item['doc'])
        section = next((s for s in (content or {}).get('sections', []) if s['sid'] == item['sid']), None)
        if not section:
            rejected.append(rejection('read', index, 'DOC_SECTION_NOT_FOUND', f"{item['doc']}#{item['sid']}"))
        elif not visibility.readable(section['visibility'], cls):
            rejected.append(rejection('read', index, 'DOC_READ_DENIED', f"{item['doc']}#{item['sid']}"))
        else:
            out.append({'doc': item['doc'], 'sid': section['sid'], 'heading': section['heading'], 'body': section['body'],
                        'visibility': section['visibility']})
    return out, rejected
