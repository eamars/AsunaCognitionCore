"""Role-owned self descriptions, stored in the existing revision ledger."""
from __future__ import annotations

import uuid

from .state import Conflict, Denied


class SelfState:
    def __init__(self, store):
        self.store = store

    def read(self, persona, scope):
        result = {}
        for name, key, target_scope in (
            ('character_core', 'character_core:' + persona, 'global-safe'),
            ('current_self', 'current_self:' + persona, 'global-safe'),
        ):
            head = self.store.head(key, target_scope)
            result[name] = {'body': head[1]['content']['body'], 'revision_id': head[0]['revision_id']} if head else None
        return result

    def commit(self, episode, target, body):
        if target not in ('character_core', 'current_self') or not isinstance(body, str) or not body.strip():
            raise ValueError('INVALID_SELF_STATE_UPDATE')
        if episode['state'] != 'DECISION_ACCEPTED' or not episode.get('decision', {}).get('reflect_self'):
            raise Denied('SELF_STATE_REQUIRES_ROLE_DECISION')
        if (episode.get('episode_kind') != 'self_development' or
                (episode['scene_id'],episode['person_id']) !=
                (self.store.config['chat']['scene_id'],self.store.config['chat']['person_id'])):
            raise Denied('SELF_STATE_REQUIRES_OWNER_INTERNAL_CONTEXT')
        if len(body) > 12000:
            raise ValueError('SELF_STATE_TOO_LARGE')
        scope = 'global-safe'
        entity = target + ':' + episode['persona']
        key = entity + '|' + scope
        mutation = 'self-state:' + episode['_id']
        old = self.store.db.state_revisions.find_one({'mutation_id': mutation})
        if old:
            if old['entity_key'] != key or old['content'] != {'body': body}:
                raise Conflict('SELF_STATE_MUTATION_CHANGED')
            current = self.store.db.state_heads.find_one({'_id': key})
            if not current or current['revision_id'] != old['_id']:
                if (current or {}).get('revision_id') != old.get('parent_revision_id'):
                    raise Conflict('SELF_STATE_MUTATION_NOT_HEAD')
                self.store.put('state_heads', {'_id':key,'scope_key':scope,'revision_id':old['_id']},
                               expected=current['revision'] if current else None,stream=episode['_id'])
            return {'target': target, 'revision_id': old['_id'], 'committed': True}
        head = self.store.db.state_heads.find_one({'_id': key})
        revision_id = str(uuid.uuid4())
        revision = self.store.put('state_revisions', {
            '_id': revision_id, 'entity_key': key, 'scope_key': scope,
            'mutation_id': mutation, 'content': {'body': body},
            'source_ids': episode.get('monologue_refs', []),
            'parent_revision_id': head['revision_id'] if head else None,
        }, stream=episode['_id'])
        document = {'_id': key, 'scope_key': scope, 'revision_id': revision_id}
        try:
            self.store.put('state_heads', document, expected=head['revision'] if head else None,
                           stream=episode['_id'])
        except Conflict:
            raise Conflict('SELF_STATE_BASE_REVISION_STALE')
        return {'target': target, 'revision_id': revision['_id'], 'committed': True}
