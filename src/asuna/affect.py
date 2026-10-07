"""Affect ledger and projection (ADR-009 ARCHITECTURE §6).

Events and amendments are append-only (insert only, never replaced, updated or
deleted). The projection is a pure function of the persona model parameters,
the folded events and a moment. Only the character commits events; the optional
appraiser route only proposes; persona jobs only import under their origin.
The projection yields bands and behaviour slots, never a line of dialogue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from .evidence import canonical, sha
from .state import Denied, now
from . import visibility
from .context_budget import AFFECT_REASONS, rough_ago

SHORT_ID = 12                 # event ids as she reads and quotes them; a unique prefix resolves to the event

SECONDS_PER_HOUR = 3600.0
COLLECTIONS = ('affect_events', 'affect_amendments', 'affect_proposals')
EVENT_FIELDS = ('kind', 'val', 'arl', 'who', 'ref', 'why', 'cost', 'open', 'half', 'half_arl')
CORE = {'close_mode': 'from_close', 'require_cost': False, 'allow_untyped': True,
        'max_delta': {'val': 100, 'arl': 100}, 'proposal_ttl_h': 24, 'kind_floor': 0,
        'kinds': {}, 'bands': [], 'policy': [],
        # Words a model writes, and the numbers they stand for (a model never writes or reads the numbers).
        'scale': {'val': {'轻微': 8, '明显': 20, '强烈': 40}, 'arl': {'平稳': 0, '有些波动': 15, '激动': 35}}}
PUBLIC_MOOD_NOTE = '这份心情可能来自别的对话：不必在这里解释原因，也不要编一个理由。'


# ── pure projection ─────────────────────────────────────────────────
def parse_ts(value):
    """ISO-8601 → aware UTC; a timestamp without an offset is refused."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError(f'TIMESTAMP_REQUIRES_OFFSET: {value}')
    return moment.astimezone(timezone.utc)


def fold(events, amendments):
    """Copies of the events with void / close / fix_ts / fix_kind applied in amendment time order."""
    folded = {}
    for event in events:
        if event['id'] in folded:
            raise ValueError(f"DUPLICATE_EVENT_ID: {event['id']}")
        folded[event['id']] = {**event, '_void': False, '_closed_at': None}
    for amendment in sorted(amendments, key=lambda item: parse_ts(item['at'])):
        target = folded.get(amendment['target'])
        if target is None:
            raise KeyError(f"AMENDMENT_TARGET_UNKNOWN: {amendment['target']}")
        op = amendment['op']
        if op == 'void':
            if not str(amendment.get('why', '')).strip():
                raise ValueError(f"VOID_REQUIRES_WHY: {amendment['target']}")
            target['_void'] = True
        elif op == 'close':
            if not target.get('open'):
                raise ValueError(f"CLOSE_REQUIRES_OPEN: {amendment['target']}")
            if target['_closed_at'] is None:
                target['_closed_at'] = parse_ts(amendment['at'])
        elif op == 'fix_ts':
            target['ts'] = amendment['value']
        elif op == 'fix_kind':
            target['kind'] = amendment['value']
        else:
            raise ValueError(f'UNKNOWN_AMENDMENT_OP: {op}')
    return list(folded.values())


def half_life(event, model):
    own = event.get('half')
    if own is not None and float(own) != 0:          # None/0 mean "unset"
        if float(own) < 0:
            raise ValueError(f"HALF_LIFE_MUST_BE_POSITIVE: {event.get('id')}")
        return float(own)
    kind = model.get('kinds', {}).get(event.get('kind') or '')
    return float(kind['half_h']) if kind else float(model['default_half_h'])


def _clamp(value, bounds):
    return max(float(bounds[0]), min(float(bounds[1]), value))


def project(model, events, amendments, at):
    """Projection at a moment: sum then clamp; future events excluded; void counts as never counted."""
    moment = parse_ts(at)
    mode = model.get('close_mode', 'from_close')
    if mode not in ('from_close', 'retroactive'):
        raise ValueError(f'UNKNOWN_CLOSE_MODE: {mode}')
    total_val = total_arl = 0.0
    held_count, rows = 0, []
    for event in fold(events, amendments):
        start = parse_ts(event['ts'])
        if start > moment or event['_void']:
            continue
        half_v = half_life(event, model)
        if event.get('half_arl') is not None and float(event['half_arl']) < 0:
            raise ValueError(f"HALF_LIFE_MUST_BE_POSITIVE: {event.get('id')}")
        half_a = float(event.get('half_arl') or model['arl_half_h'])
        age_h = (moment - start).total_seconds() / SECONDS_PER_HOUR
        closed_at, held = event['_closed_at'], False
        if event.get('open') and closed_at is None:
            decay_v, held = 1.0, True
        elif event.get('open') and mode == 'from_close':
            if moment < closed_at:
                decay_v, held = 1.0, True
            else:
                decay_v = 0.5 ** (((moment - closed_at).total_seconds() / SECONDS_PER_HOUR) / half_v)
        else:
            decay_v = 0.5 ** (age_h / half_v)
        held_count += held
        decay_a = 0.5 ** (age_h / half_a)
        value_v = float(event.get('val', 0.0)) * decay_v
        value_a = float(event.get('arl', 0.0)) * decay_a
        total_val += value_v
        total_arl += value_a
        if abs(value_v) >= 0.5 or abs(value_a) >= 0.5:
            rows.append({'event_id': event['id'], 'kind': event.get('kind') or '', 'val': value_v, 'arl': value_a,
                         'age_h': age_h, 'held': held, 'why': event.get('why', '')})
    state = {'val': _clamp(total_val, model['clamp']['val']), 'arl': _clamp(total_arl, model['clamp']['arl'])}
    state['contributions'] = sorted(rows, key=lambda row: -(abs(row['val']) + abs(row['arl'])))
    state['open_count'] = held_count
    return state


_COMPARE = {
    'val_gte': lambda s, c: s['val'] >= c, 'val_gt': lambda s, c: s['val'] > c,
    'val_lte': lambda s, c: s['val'] <= c, 'val_lt': lambda s, c: s['val'] < c,
    'arl_gte': lambda s, c: s['arl'] >= c, 'arl_gt': lambda s, c: s['arl'] > c,
    'arl_lte': lambda s, c: s['arl'] <= c, 'arl_lt': lambda s, c: s['arl'] < c,
}


def first_rule(rules, state):
    """Ordered rule table: the first rule whose every comparison holds wins."""
    for rule in rules:
        if all(_COMPARE[key](state, float(value)) for key, value in rule.get('if', {}).items()):
            return rule
    return None


def describe(model, state, cls):
    """Projection → injected description. Public: band, public tendencies and slots only."""
    band = first_rule(model.get('bands', []), state)
    weights = {}
    for row in state['contributions']:
        weights[row['kind']] = weights.get(row['kind'], 0.0) + abs(row['val'])
    total = sum(weights.values()) or 1.0
    kinds, floor, top = model.get('kinds', {}), float(model.get('kind_floor') or 0.0), []
    for kind, weight in sorted(weights.items(), key=lambda item: -item[1])[:3]:
        if weight < floor:
            continue
        spec = kinds.get(kind, {})
        shown = spec.get('tendency_visibility', 'owner_private') == 'public' or cls == visibility.OWNER_PRIVATE
        top.append({'kind': kind, 'share': weight / total, 'tendency': spec.get('tendency') if shown else None})
    policy = []
    for slot in model.get('policy', []):
        if slot.get('visibility', 'owner_private') != 'public' and cls != visibility.OWNER_PRIVATE:
            continue
        rule = first_rule(slot.get('rules', []), state)
        policy.append({'slot': slot['slot'], 'text': rule['text'] if rule else slot.get('default', '')})
    description = {'label': band['label'] if band else '', 'policy': policy,
                   'tendencies': [item['tendency'] for item in top if item['tendency']]}
    if cls == visibility.OWNER_PRIVATE:
        description.update(val=state['val'], arl=state['arl'], top_kinds=top, open_count=state['open_count'],
                           contributions=state['contributions'])
    return description


def _word(scale, magnitude):
    """The scale word a magnitude now reads as: nearest word, by midpoints between the defined values."""
    words = sorted(scale.items(), key=lambda item: item[1])
    chosen = words[0][0] if words[0][1] > 0 and magnitude >= words[0][1] / 2 else None
    for (_, low), (word, high) in zip(words, words[1:]):
        if magnitude >= (low + high) / 2:
            chosen = word
    return chosen or (words[0][0] if words[0][1] == 0 else '淡了')


def kind_key(model, kind):
    """A kind given by key or by its display label."""
    kinds = model.get('kinds', {})
    if not kind or kind in kinds:
        return kind or ''
    return next((key for key, spec in kinds.items() if spec.get('label') == kind), kind)


def kind_label(model, kind):
    return (model.get('kinds', {}).get(kind) or {}).get('label') or kind or '未分类'


def from_words(model, item):
    """A feeling recorded in words → the numeric event the ledger stores."""
    scale = model.get('scale') or CORE['scale']
    kind = kind_key(model, item.get('kind'))
    if item['intensity'] not in scale['val']:
        raise AffectError('AFFECT_INTENSITY_UNKNOWN', item['intensity'])
    arousal = item.get('arousal') or min(scale['arl'], key=scale['arl'].get)
    if arousal not in scale['arl']:
        raise AffectError('AFFECT_AROUSAL_UNKNOWN', arousal)
    valence = (model.get('kinds', {}).get(kind) or {}).get('valence')
    direction = item.get('direction') or {'positive': '好', 'negative': '坏'}.get(valence)
    if direction not in ('好', '坏'):
        raise AffectError('AFFECT_DIRECTION_REQUIRED', kind or '未分类')
    value = {k: item[k] for k in ('ref', 'why', 'cost', 'open', 'who') if k in item}
    if kind:
        value['kind'] = kind
    return {**value, 'val': scale['val'][item['intensity']] * (1 if direction == '好' else -1), 'arl': scale['arl'][arousal]}


def interpret(model, state, cls, where=None):
    """Projection → the words she reads (no numbers). Public: mood, public tendencies and hints, and a note."""
    view = describe(model, state, cls)
    scale = model.get('scale') or CORE['scale']
    band = first_rule(model.get('bands', []), state) or {}
    out = {'label': view['label'] or '平静', **({'face': band['face']} if band.get('face') else {}),
           'policy': view['policy'], 'tendencies': view['tendencies']}
    if cls != visibility.OWNER_PRIVATE:
        return {**out, 'note': PUBLIC_MOOD_NOTE}
    out['main_feelings'] = [kind_label(model, item['kind']) for item in view['top_kinds']]
    if view['open_count']:
        out['unsettled'] = f"{view['open_count']} 件事还挂着"
    # Bounded and stable (context_budget.py): every unsettled feeling, then the strongest others up to the limit;
    # times in coarse words and short ids, so an unchanged mood reads the same from one turn to the next.
    rows = view['contributions']
    held = [row for row in rows if row.get('held')]
    shown = held + [row for row in rows if not row.get('held')][:max(AFFECT_REASONS - len(held), 0)]
    out['reasons'] = [{'feeling': kind_label(model, row['kind']),
                       'strength': _word(scale['val'], abs(row['val'])), 'stirred': _word(scale['arl'], row['arl']),
                       'when': rough_ago(row['age_h']),
                       **({'unsettled': True} if row.get('held') else {}), 'why': row.get('why', ''),
                       # ADR-018 §6: a reason written outside says where (where: event id -> words, home only).
                       **({'where': where[row['event_id']]} if where and row['event_id'] in where else {}),
                       'event_id': row['event_id'][:SHORT_ID]}
                      for row in rows if row in shown]
    if len(rows) > len(shown):
        out['fainter'] = f'还有 {len(rows) - len(shown)} 笔较淡的心情没列出'
    return out


def recording_guide(model):
    """How she records a feeling, in words."""
    scale = model.get('scale') or CORE['scale']
    kinds = model.get('kinds', {})
    return {'kinds': [spec.get('label') or key for key, spec in kinds.items()],
            'intensity': list(scale['val']), 'arousal': list(scale['arl']),
            'direction': '种类本身带好坏的不用写；不在种类表里的感受写 direction（好/坏）',
            'cost_required': bool(model.get('require_cost'))}


def affect_model(model, policy=None):
    """Persona model ``affect`` merged over core defaults, with policy overrides for affect.* keys."""
    import copy
    value = {**copy.deepcopy(CORE), **copy.deepcopy((model or {}).get('affect') or {})}
    for key, item in (policy or {}).items():
        if not key.startswith('affect.'):
            continue
        node, parts = value, key.split('.')[1:]
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = item['value']
    return value


# ── ledger ──────────────────────────────────────────────────────────
class AffectError(ValueError):
    def __init__(self, code, detail=''):
        super().__init__(code + (': ' + str(detail) if detail else ''))
        self.code = code


class AffectLedger:
    def __init__(self, store, persona, model, policy=None):
        self.store, self.persona = store, persona
        self.model = affect_model(model, policy)

    @property
    def enabled(self):
        return bool(self.model.get('enabled'))

    def _insert(self, collection, doc, stream):
        """Insert-only write path for affect_*; an identical replay returns the stored row."""
        if collection not in COLLECTIONS:
            raise Denied('AFFECT_COLLECTION_ONLY')
        doc = {**doc, 'schema_version': 1}
        try:
            self.store.db[collection].insert_one(doc)
        except DuplicateKeyError:
            existing = self.store.db[collection].find_one({'_id': doc['_id']}) or self.store.db[collection].find_one(
                {'persona': doc.get('persona'), 'origin': doc.get('origin'), 'source_identity': doc.get('source_identity')})
            core = lambda row: {k: v for k, v in row.items() if k not in ('created_at', 'schema_version', 'ts')}
            if existing and core(existing) == core(doc):
                return existing, False
            raise AffectError('EVENT_IMMUTABLE', doc.get('source_identity') or doc['_id']) from None
        self.store.audit(stream, 'affect.insert', {'collection': collection, 'id': doc['_id'],
                         'content_sha256': sha(canonical({k: v for k, v in doc.items() if k != 'schema_version'}))},
                         doc.get('source_scope') or 'global-safe')
        return doc, True

    def events(self):
        return [{**row, 'id': row['_id']} for row in self.store.db.affect_events.find({'persona': self.persona})]

    def amendments(self):
        return list(self.store.db.affect_amendments.find({'persona': self.persona}))

    def projection(self, at=None):
        return project(self.model, self.events(), self.amendments(), at or datetime.now(timezone.utc))

    def description(self, cls, at=None):
        """§6.5 injection, filtered by readable source scopes for the contribution reasons."""
        if not self.enabled:
            return None
        state = self.projection(at)
        if cls == visibility.OWNER_PRIVATE:
            scopes = {row['_id']: row.get('source_scope') for row in self.store.db.affect_events.find(
                {'persona': self.persona}, {'source_scope': 1})}
            for row in state['contributions']:
                row['source_scope'] = scopes.get(row['event_id'])
        return describe(self.model, state, cls)

    def readable(self, source_scope, ep_scope, cls):
        if visibility.is_owner_private_scope(source_scope):
            return cls == visibility.OWNER_PRIVATE and source_scope == visibility.owner_private_scope(self.persona)
        if cls == visibility.OWNER_PRIVATE:
            return True          # home is shown every reason, so it may settle one written outside (ADR-018 §3.3)
        return source_scope in ('global-safe', ep_scope)

    def check(self, item, refs):
        """Program gates for a committed event (§6.4): any failure refuses only this item."""
        if not self.enabled:
            raise AffectError('AFFECT_DISABLED')
        if item.get('ref') not in refs:
            raise AffectError('AFFECT_REF_NOT_IN_INDEX', item.get('ref'))
        if self.model.get('require_cost') and not str(item.get('cost') or '').strip():
            raise AffectError('AFFECT_COST_REQUIRED')
        limit = self.model.get('max_delta') or {}
        for axis in ('val', 'arl'):
            if abs(float(item.get(axis, 0))) > float(limit.get(axis, 100)):
                raise AffectError('AFFECT_DELTA_TOO_LARGE', axis)
        kind = item.get('kind') or ''
        if kind and kind not in self.model.get('kinds', {}):
            raise AffectError('AFFECT_KIND_UNKNOWN', kind)
        if not kind and not self.model.get('allow_untyped', True):
            raise AffectError('AFFECT_KIND_REQUIRED')
        for field in ('half', 'half_arl'):
            if item.get(field) is not None and float(item[field]) < 0:
                raise AffectError('HALF_LIFE_MUST_BE_POSITIVE', field)

    def commit(self, ep, index, item, cls, *, refs=None, proposal_id=None, key=None):
        """A character-committed event: host timestamp, origin asuna, source scope from the session class.

        ``key`` names which effect this event is (DECIDE dedups optional items by it). The row id
        derives from the key when given: a later DECIDE round that records a new feeling at the same
        position no longer collides with the earlier one, and replaying the same item hits the same
        row instead of raising EVENT_IMMUTABLE.
        """
        self.check(item, refs if refs is not None else ep['context'].get('ref_index', []))
        source_scope = visibility.owner_private_scope(self.persona) if cls == visibility.OWNER_PRIVATE else ep['scope_key']
        doc = {'_id': sha(canonical([ep['_id'], 'affect', key if key is not None else index, proposal_id])),
               'persona': self.persona,
               'origin': 'asuna', 'ts': now(), 'ref_kind': 'episode', 'source_scope': source_scope,
               'episode_id': ep['_id'], 'created_at': now(),
               **{k: item[k] for k in EVENT_FIELDS if k in item}}
        doc.setdefault('open', False)
        if proposal_id:
            doc['proposal_id'] = proposal_id
        return self._insert('affect_events', doc, 'affect:' + ep['_id'])[0]

    def record(self, ep, index, item, cls, *, key=None):
        """A feeling she recorded in words (DECIDE): mapped to numbers here, then the usual gates."""
        if not self.enabled:
            raise AffectError('AFFECT_DISABLED')
        return self.commit(ep, index, from_words(self.model, item), cls, key=key)

    def amend(self, ep, index, item, cls, *, key=None):
        """One amendment of an existing event; ``key`` names which effect it is (DECIDE dedups by it).

        The row id derives from the key when given, so a later DECIDE round that amends another
        event at the same position does not collide with this one, and replaying the same item
        returns the amendment already made instead of reporting it as a second, impossible change.
        """
        target = self.store.db.affect_events.find_one({'_id': item['event_id'], 'persona': self.persona})
        if not target and len(str(item['event_id'])) >= 8:
            # She reads short ids (interpret): a prefix that names exactly one of her events is that event.
            import re
            found = list(self.store.db.affect_events.find({'_id': {'$regex': '^' + re.escape(str(item['event_id']))},
                                                           'persona': self.persona}).limit(2))
            target = found[0] if len(found) == 1 else None
        if not target:
            raise AffectError('AFFECT_EVENT_UNKNOWN', item['event_id'])
        if not self.readable(target.get('source_scope'), ep['scope_key'], cls):
            raise AffectError('AFFECT_EVENT_NOT_READABLE', item['event_id'])
        if item['op'] == 'void' and not str(item.get('why') or '').strip():
            raise AffectError('VOID_REQUIRES_WHY')
        key = [ep['_id'], 'affect_ops', key if key is not None else index]
        made = self.store.db.affect_amendments.find_one({'_id': sha(canonical(['amendment', self.persona, *key]))})
        if made:
            return made          # 这一处修订已经记过了：同一轮重复、回想那一轮之前记过、崩溃重放
        if item['op'] == 'close':
            if not target.get('open'):
                raise AffectError('CLOSE_REQUIRES_OPEN')
            if self.store.db.affect_amendments.find_one({'target': target['_id'], 'op': 'close'}):
                raise AffectError('ALREADY_CLOSED')
        return self.amendment(target['_id'], item['op'], why=item.get('why', ''), by='character',
                              key=key, scope=target.get('source_scope'))

    def amendment(self, target, op, *, why, by, key, value=None, origin='asuna', source_identity=None, at=None, scope=None):
        if op in ('fix_ts', 'fix_kind') and value is None:
            raise AffectError('AMENDMENT_VALUE_REQUIRED', op)
        if op == 'void' and not str(why or '').strip():
            raise AffectError('VOID_REQUIRES_WHY')
        doc = {'_id': sha(canonical(['amendment', self.persona, *key])), 'persona': self.persona, 'target': target,
               'op': op, 'at': at or now(), 'why': why, 'by': by, 'origin': origin, 'created_at': now(),
               **({'value': value} if value is not None else {}),
               **({'source_identity': source_identity} if source_identity else {})}
        return self._insert('affect_amendments', doc, 'affect-amend:' + target)[0]

    # ── proposals (appraiser route) ─────────────────────────────────
    def propose(self, ep, index, item, cls):
        source_scope = visibility.owner_private_scope(self.persona) if cls == visibility.OWNER_PRIVATE else ep['scope_key']
        doc = {'_id': sha(canonical(['proposal', ep['_id'], index])), 'persona': self.persona, 'kind_row': 'proposal',
               'status': 'pending', 'source_scope': source_scope, 'episode_id': ep['_id'],
               'ref_index': list(ep['context'].get('ref_index', [])), 'created_at': now(),
               **{k: item[k] for k in EVENT_FIELDS if k in item}}
        return self._insert('affect_proposals', doc, 'affect-propose:' + ep['_id'])[0]

    def proposal_state(self, proposal, at=None):
        decided = self.store.db.affect_proposals.find_one({'_id': 'decision:' + proposal['_id']})
        if decided:
            return decided['decision']
        ttl = float(self.model.get('proposal_ttl_h') or 24)
        if parse_ts(at or now()) - parse_ts(proposal['created_at']) > timedelta(hours=ttl):
            return 'expired'
        return 'pending'

    def proposals(self, ep_scope, cls, at=None):
        """Pending and newly expired proposals readable here; expiry is recorded, never silent."""
        out = []
        for row in self.store.db.affect_proposals.find({'persona': self.persona, 'kind_row': 'proposal'}).sort('created_at', 1):
            if not self.readable(row['source_scope'], ep_scope, cls):
                continue
            state = self.proposal_state(row, at)
            if state == 'expired':
                # Said once, on the turn it lapses; after that it is decided (expired) and leaves the view.
                if self.store.db.affect_proposals.find_one({'_id': 'decision:' + row['_id']}):
                    continue
                self._insert('affect_proposals', {'_id': 'decision:' + row['_id'], 'persona': self.persona,
                             'kind_row': 'decision', 'proposal_id': row['_id'], 'decision': 'expired',
                             'why': 'proposal_ttl_h elapsed', 'created_at': now(), 'source_scope': row['source_scope']},
                             'affect-propose:' + row['_id'])
            if state in ('pending', 'expired'):
                # In words, like everything else she reads about her feelings.
                scale = self.model.get('scale') or CORE['scale']
                out.append({'proposal_id': row['_id'], 'status': '待定' if state == 'pending' else '已过期',
                            'feeling': kind_label(self.model, row.get('kind')),
                            'direction': '好' if row.get('val', 0) >= 0 else '坏',
                            'intensity': _word(scale['val'], abs(row.get('val', 0))),
                            'arousal': _word(scale['arl'], row.get('arl', 0)),
                            **{k: row[k] for k in ('ref', 'why', 'cost', 'open') if k in row}})
        return out

    def adopt(self, ep, index, item, cls, *, key=None):
        proposal = self.store.db.affect_proposals.find_one({'_id': item['proposal_id'], 'persona': self.persona,
                                                            'kind_row': 'proposal'})
        if not proposal or not self.readable(proposal['source_scope'], ep['scope_key'], cls):
            raise AffectError('AFFECT_PROPOSAL_UNKNOWN', item['proposal_id'])
        word = 'accepted_edited' if item['decision'] == 'edit' else item['decision']
        decided = self.store.db.affect_proposals.find_one({'_id': 'decision:' + proposal['_id']})
        if decided and decided.get('episode_id') == ep['_id'] and decided.get('decision') == word:
            # 这一轮已经这样决定过这条提案（同一轮重复、回想那一轮之前决定过、崩溃重放）：
            # 不再插一条决定，也不把它当成「已经不是待定」而退回。
            return self.store.db.affect_events.find_one({'_id': decided['event_id']}) if decided.get('event_id') else None
        if self.proposal_state(proposal) != 'pending':
            raise AffectError('AFFECT_PROPOSAL_NOT_PENDING', self.proposal_state(proposal))
        event = None
        if item['decision'] in ('accept', 'edit'):
            fields = (from_words(self.model, item['edit']) if item['decision'] == 'edit'
                      else {k: proposal[k] for k in EVENT_FIELDS if k in proposal})
            event = self.commit(ep, index, fields, cls, refs=proposal['ref_index'], proposal_id=proposal['_id'],
                                key=key)
        self._insert('affect_proposals', {'_id': 'decision:' + proposal['_id'], 'persona': self.persona,
                     'kind_row': 'decision', 'proposal_id': proposal['_id'], 'decision': item['decision'] if item['decision'] != 'edit' else 'accepted_edited',
                     'why': item['why'], 'event_id': event['_id'] if event else None, 'episode_id': ep['_id'],
                     'created_at': now(), 'source_scope': proposal['source_scope']}, 'affect-propose:' + proposal['_id'])
        return event

    # ── import (persona jobs, via the data API) ─────────────────────
    def import_batch(self, origin, events=(), amendments=(), *, dry_run=False):
        """Idempotent by (origin, source_identity); changed content → EVENT_IMMUTABLE (use an amendment)."""
        report = {'created': 0, 'existing': 0, 'rejected': [], 'amendments_created': 0, 'amendments_existing': 0}
        for item in events:
            try:
                doc = self._import_doc(origin, item)
                existing = self.store.db.affect_events.find_one({'_id': doc['_id']})
                if existing:
                    same = {k: existing.get(k) for k in doc if k not in ('created_at',)} == \
                           {k: v for k, v in doc.items() if k not in ('created_at',)}
                    if not same:
                        raise AffectError('EVENT_IMMUTABLE', item.get('source_identity'))
                    report['existing'] += 1
                elif not dry_run:
                    self._insert('affect_events', doc, 'affect-import:' + origin)
                    report['created'] += 1
                else:
                    report['created'] += 1
            except (AffectError, ValueError, KeyError) as exc:
                report['rejected'].append({'source_identity': item.get('source_identity'), 'code': str(exc).split(':')[0]})
        for item in amendments:
            try:
                target = sha(canonical([self.persona, origin, item['target_source_identity']]))
                if not self.store.db.affect_events.find_one({'_id': target}) and not dry_run:
                    raise AffectError('AMENDMENT_TARGET_UNKNOWN', item['target_source_identity'])
                key = ['import', origin, item['source_identity']]
                if self.store.db.affect_amendments.find_one({'_id': sha(canonical(['amendment', self.persona, *key]))}):
                    report['amendments_existing'] += 1
                    continue
                if item['op'] not in ('close', 'void', 'fix_ts', 'fix_kind'):
                    raise AffectError('UNKNOWN_AMENDMENT_OP', item['op'])
                if item['op'] in ('fix_ts', 'fix_kind') and item.get('value') is None:
                    raise AffectError('AMENDMENT_VALUE_REQUIRED', item['op'])
                if item['op'] == 'void' and not str(item.get('why') or '').strip():
                    raise AffectError('VOID_REQUIRES_WHY')
                if not dry_run:
                    self.amendment(target, item['op'], why=item.get('why', ''), by='persona_job:' + origin, key=key,
                                   value=item.get('value'), origin=origin, source_identity=item['source_identity'],
                                   at=parse_ts(item['at']).isoformat())
                report['amendments_created'] += 1
            except (AffectError, ValueError, KeyError) as exc:
                report['rejected'].append({'source_identity': item.get('source_identity'), 'code': str(exc).split(':')[0]})
        return report

    def _import_doc(self, origin, item):
        if not item.get('source_identity'):
            raise AffectError('SOURCE_IDENTITY_REQUIRED')
        if not str(item.get('ref') or '').strip() or not str(item.get('why') or '').strip():
            raise AffectError('AFFECT_REF_AND_WHY_REQUIRED', item['source_identity'])
        moment = parse_ts(item['ts'])
        kind = item.get('kind') or ''
        if kind and kind not in self.model.get('kinds', {}):
            raise AffectError('AFFECT_KIND_UNKNOWN', kind)
        for field in ('half', 'half_arl'):
            if item.get(field) is not None and float(item[field]) < 0:
                raise AffectError('HALF_LIFE_MUST_BE_POSITIVE', field)
        scope = 'global-safe' if item.get('visibility') == 'public' else visibility.owner_private_scope(self.persona)
        return {'_id': sha(canonical([self.persona, origin, item['source_identity']])), 'persona': self.persona,
                'origin': origin, 'source_identity': item['source_identity'], 'ts': moment.isoformat(),
                'ts_original': str(item['ts']), 'ref_kind': 'external', 'source_scope': scope, 'episode_id': None,
                'open': bool(item.get('open', False)), 'created_at': now(),
                **{k: item[k] for k in EVENT_FIELDS if k in item and k != 'open'}}


# ── appraiser route (optional, proposals only) ─────────────────────
PROPOSAL_FIELDS = {'kind', 'direction', 'intensity', 'arousal', 'ref', 'why', 'cost', 'open', 'who'}


class Appraiser:
    """Runs after an episode is committed, never inside it; failures and timeouts are audited only.

    The proposal schema has no field that could carry a line of dialogue.
    """
    def __init__(self, store, lane):
        self.store, self.lane = store, lane

    def run(self, episode_id):
        import json
        from .config import prompt_path
        from .render import model_and_policy
        ep = self.store.db.episodes.find_one({'_id': episode_id})
        if not ep or ep.get('state') not in ('COMMITTED', 'WAITING_TASK'):
            return []
        model, policy = model_and_policy(self.store, ep['persona'])
        ledger = AffectLedger(self.store, ep['persona'], model, policy)
        if not ledger.enabled or self.store.db.affect_proposals.find_one({'episode_id': episode_id}):
            return []
        monologues = [row.get('body_markdown', '') for row in self.store.db.memory_units.find(
            {'_id': {'$in': ep.get('monologue_refs', [])}}, {'body_markdown': 1})]
        payload = {'input': ep['context'].get('event', {}).get('text'), 'monologue': monologues,
                   'speech': ep.get('speech'), 'ref_index': ep['context'].get('ref_index', []),
                   'how_to_record': recording_guide(ledger.model)}
        from . import answers
        question = (prompt_path(self.store.config, 'stage_appraise.md').read_text(encoding='utf-8')
                    + '\n' + json.dumps(payload, ensure_ascii=False))
        system = prompt_path(self.store.config, 'common.md').read_text(encoding='utf-8')
        operation = episode_id + ':APPRAISE:0'

        def generate(attempt, note):
            return self.lane.generate('appraiser:' + ep['persona'],
                                      operation if not attempt else operation + ':fix-' + str(attempt),
                                      'APPRAISE', note or question, system)

        def rejected(attempt, issue, value):
            self.store.audit(episode_id, 'phase.rejected', {'operation': operation, 'phase': 'APPRAISE',
                             'attempt': attempt, 'problem': issue}, ep['scope_key'])
        try:
            result, items = answers.ask(generate, '一个 JSON 数组（格式见上面的说明，没有值得提的就写 []）',
                                        answers.json_list, rejected=rejected)
            if items is None:
                raise ValueError('APPRAISAL_NOT_FINISHED: ' + result.finish_reason)
        except answers.Rejected as exc:
            self.store.audit(episode_id, 'affect.appraisal_failed', {'error': 'Rejected: ' + exc.problem}, ep['scope_key'])
            return []
        except Exception as exc:
            self.store.audit(episode_id, 'affect.appraisal_failed', {'error': type(exc).__name__ + ': ' + str(exc)[:300]},
                             ep['scope_key'])
            return []
        cls = ep['manifest'].get('session_class', visibility.PUBLIC)
        stored = []
        for index, item in enumerate(items[:3]):
            if not isinstance(item, dict) or set(item) - PROPOSAL_FIELDS or not isinstance(item.get('why'), str) \
                    or len(item['why']) > 200 or not item.get('ref') or not isinstance(item.get('intensity'), str):
                self.store.audit(episode_id, 'affect.proposal_refused', {'index': index}, ep['scope_key'])
                continue
            try:
                stored.append(ledger.propose(ep, index, from_words(ledger.model, item), cls))
            except AffectError as exc:
                self.store.audit(episode_id, 'affect.proposal_refused', {'index': index, 'code': exc.code}, ep['scope_key'])
        return stored
