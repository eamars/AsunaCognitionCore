"""Role-owned self descriptions, stored in the existing revision ledger."""
from __future__ import annotations

from .records import heads as head_records


class SelfState:
    def __init__(self, store):
        self.store = store

    def read(self, persona, scope):
        result = {}
        for name, key, target_scope in (
            ('character_core', 'character_core:' + persona, 'global-safe'),
            ('current_self', 'current_self:' + persona, 'global-safe'),
        ):
            head = head_records.current(self.store, key, target_scope)
            result[name] = {'body': head[1]['content']['body'], 'revision_id': head[0]['revision_id']} if head else None
        return result
