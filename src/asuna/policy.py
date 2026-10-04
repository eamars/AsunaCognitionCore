"""Policy store ``policy:<persona>`` (ADR-009 PERSONA_CONTRACT §3).

Each key is ``{value, what, class: "param"}``; numbers live in one place. Every
change is a revision on the existing state_heads/state_revisions ledger with a
reason, sources and author. Credentials and run counters are not policy.
"""
from __future__ import annotations

from .evidence import canonical, sha
from .persona_model import check_value, key_spec
from .state import Conflict, Denied, now

SCOPE = 'global-safe'
REFUSED_CLASSES = ('secret', 'counter')


class PolicyStore:
    def __init__(self, store, persona: str, model: dict):
        self.store, self.persona, self.model = store, persona, model
        self.entity = 'policy:' + persona

    @property
    def key(self):
        return self.entity + '|' + SCOPE

    def read(self):
        """(head revision id or None, {key: {value, what, class}})."""
        pair = self.store.head(self.entity, SCOPE)
        if not pair:
            return None, {}
        return pair[0]['revision_id'], dict(pair[1]['content'].get('params', {}))

    def params(self) -> dict:
        return self.read()[1]

    def validate(self, items):
        """Reject the whole request on the first invalid item; returns normalized params."""
        out = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get('key'), str):
                raise ValueError(f'POLICY_ITEM_INVALID: {index}')
            if item.get('class', 'param') in REFUSED_CLASSES:
                raise Denied(f"POLICY_CLASS_REFUSED: {item['key']}")
            if item.get('class', 'param') != 'param':
                raise ValueError(f"POLICY_CLASS_UNKNOWN: {item['key']}")
            what = item.get('what')
            if not isinstance(what, str) or not 1 <= len(what) <= 300:
                raise ValueError(f"POLICY_WHAT_REQUIRED: {item['key']}")
            spec = key_spec(self.model, item['key'])
            if spec is None:
                raise Denied(f"POLICY_KEY_UNDECLARED: {item['key']}")
            try:
                check_value(spec, item.get('value'))
            except ValueError as exc:
                raise ValueError(f"{exc}: {item['key']}") from None
            out[item['key']] = {'value': item['value'], 'what': what, 'class': 'param'}
        return out

    def set(self, items, *, base_revision_id, reason, author, mutation_id, sources=()):
        """CAS write: the caller's base revision must still be the head (BASE_REVISION_STALE)."""
        if not isinstance(reason, str) or not 1 <= len(reason) <= 2000:
            raise ValueError('POLICY_REASON_REQUIRED')
        changes = self.validate(items)
        existing = self.store.db.state_revisions.find_one({'mutation_id': mutation_id})
        if existing:
            if existing.get('entity_key') != self.key or existing['content'].get('changes') != changes:
                raise Conflict('MUTATION_ID_CONTENT_CHANGED')
            return existing
        head = self.store.db.state_heads.find_one({'_id': self.key})
        current = head['revision_id'] if head else None
        if current != base_revision_id:
            self.store.audit('policy:' + mutation_id, 'state.conflict', {'entity': self.entity,
                             'base_revision_id': base_revision_id, 'reason': 'BASE_REVISION_STALE'}, SCOPE)
            raise Conflict('BASE_REVISION_STALE')
        params = self.read()[1] if head else {}
        params.update(changes)
        revision_id = sha(canonical({'mutation_id': mutation_id, 'entity': self.entity}))
        revision = self.store.put('state_revisions', {
            '_id': revision_id, 'mutation_id': mutation_id, 'entity_key': self.key, 'scope_key': SCOPE,
            'content': {'params': params, 'changes': changes}, 'source_ids': list(sources),
            'parent_revision_id': current, 'reason': reason, 'author': author, 'created_at': now()},
            stream='policy:' + mutation_id)
        try:
            if head:
                self.store.put('state_heads', {**head, 'revision_id': revision_id}, expected=head['revision'],
                               stream='policy:' + mutation_id)
            else:
                self.store.put('state_heads', {'_id': self.key, 'scope_key': SCOPE, 'revision_id': revision_id},
                               stream='policy:' + mutation_id)
        except Conflict:
            # A concurrent writer moved the head first; this revision stays unreferenced.
            self.store.audit('policy:' + mutation_id, 'state.conflict', {'entity': self.entity,
                             'base_revision_id': base_revision_id, 'reason': 'BASE_REVISION_STALE'}, SCOPE)
            raise Conflict('BASE_REVISION_STALE') from None
        return revision
