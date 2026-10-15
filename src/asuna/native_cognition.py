"""Read-only cognitive state coverage for the existing native Memory view."""
import json


class CognitionView:
    def __init__(self, memory):
        self.memory = memory
        self.store = memory.store
        self.binding = memory.binding
        self.snapshot = self._snapshot()

    def _snapshot(self):
        # Episodes have no wall-clock field. Use the real context-prepared audit,
        # then reauthorize its episode; never sort opaque episode IDs as time.
        scope = self.memory.scene['scope_key']
        query = {'type': 'context.prepared', 'scope_key': scope,
                 'payload.context.person_id': self.binding['person_id'],
                 'payload.context.policy_epoch': self.binding['policy_epoch']}
        role = self.binding.get('role_session_id') or self.binding['_id']
        episode_query = {'native_session_id': role, 'scope_key': scope,
                         'scene_id': self.binding['scene_id'],
                         'person_id': self.binding['person_id'],
                         'policy_epoch': self.binding['policy_epoch'],
                         'persona': self.binding['persona']}
        if self.binding.get('task_id'):
            task = self.store.db.tasks.find_one({'_id': self.binding['task_id'],
                'scene_id': self.binding['scene_id'], 'requester_id': self.binding['person_id'],
                'policy_epoch': self.binding['policy_epoch']})
            if not task:
                return None
            episode_query['_id'] = task['episode_id']
            query['stream_id'] = task['episode_id']
        for audit in self.store.db.audit_events.find(query, {
                'stream_id': 1, 'occurred_at': 1}).sort([('occurred_at', -1), ('_id', -1)]).limit(24):
            episode = self.store.db.episodes.find_one({**episode_query, '_id': audit['stream_id']},
                {'context': 1, 'manifest': 1, 'monologue_refs': 1})
            if episode:
                return {**episode, 'at': audit['occurred_at']}
        return None

    def usage(self, identifier, content=None, revision=None):
        """A key of the client's memory.usage words: whether the latest turn used this record."""
        if not self.snapshot:
            return 'none'
        context = self.snapshot['context']
        manifest = self.snapshot['manifest']
        kind, key = identifier.split(':', 1)
        if kind == 'head':
            entity = key.split('|', 1)[0]
            if entity.startswith('persona:'):
                selected = manifest.get('persona_revision')
            elif entity.startswith('relationship:'):
                selected = (manifest.get('relationship_revision') if key == manifest.get('relationship_entity_key')
                            else manifest.get('person_revision') if key == manifest.get('person_entity_key') else None)
            elif entity.startswith(('character_core:', 'current_self:')):
                selected = (context.get('self_state_from_program', {}).get(entity.split(':')[0]) or {}).get('revision_id')
            else:
                selected = None
            if selected:
                return 'used' if selected == revision else 'older'
        elif kind == 'doc':
            # The persona is a document (ADR-009); the manifest names the revision this turn rendered.
            selected = manifest.get('persona_revision') if key == 'persona' else manifest.get('documents', {}).get(key)
            if selected:
                return 'used' if selected == revision else 'older'
        elif kind == 'item':
            # An item of her self is cited by its doc ref wherever the turn showed it (carried, or brought up).
            slug, _, sid = key.partition('#')
            if f'doc:{slug}#{sid}' in json.dumps(context, ensure_ascii=False):
                return 'used'
        elif kind == 'unit':
            if key in manifest.get('selected', []):
                return 'used'
            if key in self.snapshot.get('monologue_refs', []):
                return 'formed'
        elif kind == 'source':
            rows = list(context.get('delivered_history', []))
            group = context.get('group_continuity_from_program', {})
            rows += group.get('related_messages', []) + group.get('current_speaker_tail', [])
            if any(row.get('_id') == key for row in rows):
                return 'used'
            if key == 'in-' + self.snapshot['_id']:
                return 'input'
        return 'unused'
