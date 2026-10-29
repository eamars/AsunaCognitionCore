"""Role-owned self descriptions, stored in the existing revision ledger."""
from __future__ import annotations

import uuid

from .state import Conflict, Denied
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

    def commit(self, episode, target, body, mutation=None):
        """Her own update_self call (ADR-011 §6.1): in an owner-private turn, like her documents."""
        from . import visibility
        if target not in ('character_core', 'current_self'):
            raise ValueError('INVALID_SELF_STATE_UPDATE: target「%s」不对，只能是 character_core 或 current_self' % target)
        if not isinstance(body, str) or not body.strip():
            raise ValueError('INVALID_SELF_STATE_UPDATE: content 是空的；写完整的新正文')
        if (episode.get('manifest') or {}).get('session_class') != visibility.OWNER_PRIVATE:
            raise Denied('SELF_STATE_REQUIRES_OWNER_PRIVATE: 自我描述只能在家里改；重试也一样')
        from .context_budget import SINGLE_BODY_CHARS
        if len(body) > SINGLE_BODY_CHARS:
            raise ValueError('SELF_STATE_TOO_LARGE: content %d 字，上限 %d 字；精简到 %d 字以内'
                             % (len(body), SINGLE_BODY_CHARS, SINGLE_BODY_CHARS))
        scope = 'global-safe'
        entity = target + ':' + episode['persona']
        key = entity + '|' + scope
        mutation = mutation or 'self-state:' + episode['_id']
        old = head_records.by_mutation(self.store, mutation)
        if old:
            if old['entity_key'] != key or old['content'] != {'body': body}:
                raise Conflict('SELF_STATE_MUTATION_CHANGED')
            current = head_records.head(self.store, key)
            if not current or current['revision_id'] != old['_id']:
                if (current or {}).get('revision_id') != old.get('parent_revision_id'):
                    raise Conflict('SELF_STATE_MUTATION_NOT_HEAD')
                head_records.save_head(self.store, {'_id':key,'scope_key':scope,'revision_id':old['_id']},
                                       expected=current['revision'] if current else None,stream=episode['_id'])
            return {'target': target, 'revision_id': old['_id'], 'committed': True}
        head = head_records.head(self.store, key)
        revision_id = str(uuid.uuid4())
        revision = head_records.save_revision(self.store, {
            '_id': revision_id, 'entity_key': key, 'scope_key': scope,
            'mutation_id': mutation, 'content': {'body': body},
            'source_ids': episode.get('monologue_refs', []),
            'parent_revision_id': head['revision_id'] if head else None,
        }, stream=episode['_id'])
        document = {'_id': key, 'scope_key': scope, 'revision_id': revision_id}
        try:
            head_records.save_head(self.store, document, expected=head['revision'] if head else None,
                                   stream=episode['_id'])
        except Conflict:
            raise Conflict('SELF_STATE_BASE_REVISION_STALE: %s 刚被别处改过（不是你的错）；再调用一次 update_self' % target)
        return {'target': target, 'revision_id': revision['_id'], 'committed': True}
