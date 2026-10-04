"""Optional DECIDE fields (ADR-009 §9.1, examples/decision-delta.schema.json).

Each item is validated and committed on its own. A rejected item is recorded in
``episode.rejections`` as ``{field, index, code, detail}`` and never fails the
turn; only an unparseable decision or a missing base field is BAD_DECISION_JSON.
Order: affect_ops → affect_adopt → affect → policy_set → pin → write_docs
(set_tags/adopt_seed directly, the rest through one WRITE stage each).

``next=recall`` runs a second DECIDE in the same episode, and models usually
rewrite the whole decision there: the second round often repeats the first
round's pin/affect/write_docs verbatim and adds one new item. So idempotency is
keyed per item on what that item *does* (``semantic_key``), never on a hash of
the whole delta and never on the item's position in the round:

- a verbatim repeat from the earlier round is applied once (skipped here);
- a genuinely new item in the later round is applied once, even at the same
  index as an old one (effect ids derive from the key, not from the index);
- replaying the same delta after a crash, or re-entering ``advance``, is a no-op;
- ``attach`` is not deduplicated at all: the picture follows the *last* DECIDE
  of the episode -- that round names one, it sends that one (a refused picture
  is refused out loud, never silently); that round names none, it sends none,
  and the earlier picture is dropped rather than riding along.
- ``write_docs`` keeps ``reason`` in its key: the WRITE stage receives the whole
  item as the intent, so two ``append_section`` items for the same document with
  different reasons are two effects, in one round or across two.

``read`` is validated exactly once per round: by the recall branch when that
branch will handle it, otherwise here (it used to be validated by both, which
duplicated every read rejection).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .config import prompt_path, schema
from .documents import DocumentError, DocumentStore, WRITE_STAGE_OPS
from .evidence import canonical, sha
from . import visibility, outbound_media

DELTA = schema('decision-delta.schema.json')
DELTA_KEYS = tuple(DELTA['properties'])
ORDER = ('affect_ops', 'affect_adopt', 'affect', 'policy_set', 'pin', 'write_docs', 'promote', 'group_action',
         'attach')
# Fields whose engines arrive in later phases are refused explicitly, not silently dropped.
NOT_YET = {}
# ``read`` is the recall branch's own field: whoever handles it that round validates it, once.
READ_FIELD = 'read'
# What makes one item the same effect as another. ``None`` means the whole item is the effect;
# a tuple names the fields that carry the effect. Rationale wording is not part of an identity
# where the engine ignores it (``policy_set`` stores key+value), but it IS part of it where the
# engine consumes the whole item -- ``write_docs`` hands the item (reason included) to the WRITE
# stage as the intent, so two appends with different reasons are two things to write.
KEY_FIELDS = {
    'affect': None,                       # the item *is* this feeling, wording included
    'affect_ops': ('op', 'event_id'),     # one amendment per (op, target event)
    'affect_adopt': ('proposal_id',),     # a proposal is decided once
    'policy_set': ('key', 'value'),       # same key+value = same change; a new value is a new change
    'pin': ('memory_id', 'pinned'),       # pin/unpin the same memory with the same value = one change
    # reason 在这一条里不是措辞：WRITE 阶段拿整条 item 当 intent，理由不同就是要写两件不同的事。
    'write_docs': ('doc', 'op', 'sid', 'heading', 'entry_date', 'tags', 'visibility', 'inject', 'reason'),
    'promote': ('fact', 'appraisal', 'signal', 'source_ids', 'visibility'),
    'group_action': ('kind', 'who', 'duration', 'which'),
}
# Later DECIDE wins over the earlier one instead of being deduplicated (schema maxItems=1).
LAST_ROUND_WINS = ('attach',)


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


def semantic_key(field, item):
    """这一条要造成的那个效果本身，与它在这一轮排第几、理由怎么措辞都无关。

    去重只用这个键：整份 delta 的指纹会把「原样重写第一轮 + 加一条新的」判成一整份新决策
    （旧条目就再生效一次），按条目位置（index）去重又会把第二轮的新条目误认成第一轮那条已生效的。
    """
    if field in KEY_FIELDS:
        fields = KEY_FIELDS[field]
    else:                                   # 没在表里的可选字段：整条内容就是它的身份
        fields = tuple(sorted(item or {}))
    picked = item if fields is None else {k: item[k] for k in fields if isinstance(item, dict) and k in item}
    return f'{field}:{sha(canonical(picked))[:24]}'


def validate_items(delta: dict, skip=()):
    """({field: [(index, item)]}, rejections) — item-level schema checks only.

    ``skip`` names fields another branch validates this round (``read`` with ``next=recall``),
    so one round never produces the same rejection twice.
    """
    skip = tuple(skip or ())
    valid, rejected = {}, []
    for field, items in delta.items():
        if field in skip:
            continue
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


def _recall_will_read(ep, delta):
    """这一轮的 ``read`` 是不是交给 recall 分支去验（那边验，这边就不重复验）。"""
    return (READ_FIELD in delta and (ep.get('decision') or {}).get('next') == 'recall'
            and int(ep.get('recall_rounds') or 0) < 2)


def apply(coordinator, ep):
    """Apply every optional field once; results and rejections land on the episode.

    Idempotency is per item (``semantic_key``) and is durable on the episode row
    (``delta_effects``), so a second DECIDE after ``next=recall`` may restate the
    earlier round verbatim, and a crash replay of the same delta changes nothing.
    """
    delta = ep.get('decision_delta') or {}
    results = dict(ep.get('delta_results') or {})
    # 图只跟最后一次 DECIDE 走：这一轮给了就换成这一张（被退回就没有图），这一轮没给就把上一轮
    # 那张摘掉。发出去的必须正好是最后那份决策里写的，主人在界面上看到的决策才对得上。
    carried = any(field in results for field in LAST_ROUND_WINS)
    for field in LAST_ROUND_WINS:
        results.pop(field, None)
    if not delta:
        # 这一轮的决策一个可选字段都没有：也没有图。
        return coordinator._update(ep, delta_results=results) if carried else ep
    store = coordinator.store
    # 已经生效的条目按语义键记在行上；行上没有这个键就是空账（开发期不写旧数据兼容）。
    applied = [key for key in (ep.get('delta_effects') or []) if isinstance(key, str)]
    seen = set(applied)
    valid, rejected = validate_items(delta, skip=(READ_FIELD,) if _recall_will_read(ep, delta) else ())
    cls = ep['manifest'].get('session_class', visibility.PUBLIC)
    round_no = int(ep.get('recall_rounds') or 0)
    ledger = None
    for field in ORDER:
        pending = valid.get(field, [])
        if not pending:
            continue
        before = len(applied)
        for index, item in pending:
            key = semantic_key(field, item)
            if field not in LAST_ROUND_WINS and key in seen:
                continue          # 这一条已经生效过：同一轮里重复、或回想那一轮之前就已生效
            refusals = len(rejected)
            if field in NOT_YET:
                rejected.append(rejection(field, index, 'FIELD_NOT_AVAILABLE', 'arrives in ' + NOT_YET[field]))
            elif field in ('affect_ops', 'affect_adopt', 'affect'):
                if ledger is None:
                    from .affect import AffectLedger
                    from .render import model_and_policy
                    ledger = AffectLedger(store, ep['persona'], *model_and_policy(store, ep['persona']))
                try:
                    if field == 'affect':
                        from .affect import kind_label
                        row = ledger.record(ep, index, item, cls, key=key)
                        results.setdefault('affect', []).append({'index': index, 'event_id': row['_id'],
                                                                 'feeling': kind_label(ledger.model, row.get('kind'))})
                    elif field == 'affect_ops':
                        row = ledger.amend(ep, index, item, cls, key=key)
                        results.setdefault('affect_ops', []).append({'index': index, 'op': item['op'], 'event_id': item['event_id']})
                    else:
                        row = ledger.adopt(ep, index, item, cls, key=key)
                        results.setdefault('affect_adopt', []).append({'index': index, 'proposal_id': item['proposal_id'],
                                                                       'decision': item['decision'],
                                                                       'event_id': row['_id'] if row else None})
                except Exception as exc:  # each item is independent
                    rejected.append(rejection(field, index, code_of(exc), exc))
            elif field == 'policy_set':
                _policy_set(store, ep, cls, index, item, results, rejected, key,
                            getattr(coordinator, 'scheduler', None))
            elif field == 'pin':
                _pin(store, ep, cls, index, item, results, rejected)
            elif field == 'write_docs':
                ep = _write(coordinator, ep, cls, index, item, results, rejected, key, round_no)
            elif field == 'promote':
                _promote(store, ep, cls, index, item, results, rejected, key)
            elif field == 'group_action':
                from . import group_admin
                try:
                    results.setdefault('group_action', []).append(group_admin.queue(store, ep, index, item, key=key))
                except Exception as exc:  # each item is independent; a refusal is said, never acted on
                    rejected.append(rejection(field, index, code_of(exc), exc))
            elif field == 'attach':
                _attach(coordinator, ep, cls, index, item, results, rejected, round_no)
            if field not in LAST_ROUND_WINS and key not in seen and len(rejected) == refusals:
                # 只有真办成的条目进账；被退回的条目下一轮还能再试（那时它是一次新的尝试）。
                seen.add(key)
                applied.append(key)
        if len(applied) != before:
            # 每个字段组落一次账：崩溃重放最多重来这一组，而组内每条副作用的 id 都由语义键导出。
            ep = coordinator._update(ep, delta_effects=list(applied))
    return coordinator._update(ep, rejections=[*(ep.get('rejections') or []), *rejected],
                               delta_results=results, delta_effects=list(applied))


def _attach(coordinator, ep, cls, index, item, results, rejected, round_no=0):
    """随这条消息发出去的一张图：只接受程序本轮列出的 image artifact，逐条判定。

    方向（owner_private + 该场景路由 target.type=dm）、可引用清单、字节格式与大小都在这里判；
    任何一条不成立只进 rejections，不影响这一轮。字节留在 BlobStore，行上只写元数据（claim 时给领取方）。
    能引用哪些场景里登记的图由 ``outbound_media.image_scopes`` 现算（本场景 + 同一主人的另一个
    owner_private 场景），不接受模型或参数指定 scope。
    后一次 DECIDE 覆盖前一次：``results['attach']`` 整份换成本轮接受的那张（schema 一轮至多 1 条）。
    """
    store = coordinator.store
    scene = store.db.scenes.find_one({'_id': ep['scene_id']},
                                     {'_id': 1, 'channel_id': 1, 'kind': 1, 'scope_key': 1, 'members': 1})
    allowed, reason = outbound_media.target_allowed(store.config, scene, cls)
    if not allowed:
        rejected.append(rejection('attach', index, 'ATTACH_TARGET_NOT_ALLOWED', reason))
        return
    if (ep.get('decision') or {}).get('next') == 'silent':
        rejected.append(rejection('attach', index, 'ATTACH_NOT_WHEN_SILENT', '这一轮不出声，图也没有跟着走'))
        return
    offered = (ep.get('context') or {}).get('image_artifacts_from_program') or {}
    listed = {row.get('artifact_id') for row in offered.get('items') or [] if isinstance(row, dict)}
    if item['artifact_id'] not in listed:
        rejected.append(rejection('attach', index, 'ATTACH_ARTIFACT_NOT_IN_CONTEXT',
                                  '%s：只能引用 image_artifacts_from_program 里列出的 artifact_id'
                                  % item['artifact_id']))
        return
    try:
        from .blobs import BlobStore
        meta = outbound_media.accept_artifact(
            store, BlobStore(store), item['artifact_id'],
            outbound_media.image_scopes(store, store.config, scene, cls, ep.get('person_id')))
    except Exception as exc:
        rejected.append(rejection('attach', index, code_of(exc), exc))
        return
    results['attach'] = [dict(meta, index=index, round=round_no)]


def _policy_set(store, ep, cls, index, item, results, rejected, key, scheduler=None):
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
        # mutation_id 跟着「这个键改成这个值」走，不跟着轮次里的位置走：原样重写命中已经提交的
        # 那一份修订，第二轮换个新值是新修订；新条目即使也排在 index 0 也不撞上第一轮 index 0 那条。
        revision = policy.set([{'key': item['key'], 'value': item['value'], 'what': what}],
                              base_revision_id=policy.read()[0], reason=item['reason'], author='character',
                              mutation_id=f"{ep['_id']}:policy_set:{key}", sources=[ep['source_event_id']])
        results.setdefault('policy_set', []).append({'index': index, 'key': item['key'], 'value': item['value'],
                                                     'revision_id': revision['_id']})
        if scheduler and hasattr(scheduler, 'ensure_presence') and item['key'].startswith(('heartbeat.', 'rhythm.')):
            # A new rhythm takes effect through schedule_update, never delete + create.
            scheduler.ensure_presence()
            scheduler.ensure_settlement()
    except Exception as exc:  # each item is independent
        rejected.append(rejection('policy_set', index, code_of(exc), exc))


def _pin(store, ep, cls, index, item, results, rejected):
    if cls != visibility.OWNER_PRIVATE:
        rejected.append(rejection('pin', index, 'PIN_REQUIRES_OWNER_PRIVATE', item['memory_id']))
        return
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


def _promote(store, ep, cls, index, item, results, rejected, key):
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
    # 记忆 id 由这一条 promote 的内容导出：第二轮换个位置也不会把新条目写成旧 id 而悄悄丢掉。
    doc = {'_id': 'mu-' + sha(canonical([ep['_id'], 'promote', key])), 'kind': 'memory_unit', 'scope_key': scope,
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


def _write_base(ep, results, docs, slug):
    """这一份文档要接着哪一份修订写。

    上下文里钉住的那一份（manifest.documents）是本轮开始时的样子：同一轮里连写同一份文档两次、
    或回想那一轮写过一次之后再决定，第二份都还拿旧 base 去 CAS，会被 BASE_REVISION_STALE 退回。
    本集已经写过的最新一份优先（write_docs 的结果里带着 revision_id，跨轮也一路带着），
    没有才回落到上下文那一份 —— 别人在这轮之后改过仍然照旧撞 CAS，不静默覆盖。
    """
    for row in reversed((results or {}).get('write_docs') or []):
        if isinstance(row, dict) and row.get('doc') == slug and row.get('revision_id'):
            return row['revision_id']
    return (ep.get('manifest') or {}).get('documents', {}).get(slug, docs.read(slug)[0])


def _write(coordinator, ep, cls, index, item, results, rejected, key, round_no=0):
    store = coordinator.store
    if item['doc'] == 'group_notes':
        # Her notes about the group she is in: written from that group's own turns, public to it.
        from .group_admin import notes_slug
        scene = store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1})
        if (scene or {}).get('kind') != 'group' or item['op'] not in ('append_section', 'replace_section'):
            rejected.append(rejection('write_docs', index, 'GROUP_NOTES_ONLY_IN_ITS_GROUP'))
            return ep
        item = {**item, 'doc': notes_slug(ep['scene_id']), 'visibility': 'public', 'inject': 'always'}
    elif cls != visibility.OWNER_PRIVATE:
        rejected.append(rejection('write_docs', index, 'DOC_WRITE_REQUIRES_OWNER_PRIVATE'))
        return ep
    from .render import budget_gate
    docs = DocumentStore(store, ep['persona'])
    slug = item['doc']
    base = _write_base(ep, results, docs, slug)
    # mutation_id 与 WRITE 那一次生成的 operation 都跟着语义键/轮次走：旧条目原样重写时
    # mutation_id 命中已经提交的那份修订（不再写第二遍），而第二轮的新条目即使也排在 index 0
    # 也不会撞上第一轮 index 0 那一条。
    mutation_id = f"{ep['_id']}:write:{key}"
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
                body = coordinator._stage(ep, 'WRITE', index, operation=f"{ep['_id']}:WRITE:{round_no}:{index}",
                                          instruction=_write_instruction(store, docs, slug, item))
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
