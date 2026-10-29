"""Read-only cognitive state coverage for the existing native Memory view."""
import json

from . import audit as audit_trail
from .records import episodes as episode_records
from .records import tasks as task_records
from .records.view import ANY


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
        stream = ANY
        role = self.binding.get('role_session_id') or self.binding['_id']
        fence = {'session': role, 'scope': scope, 'scene': self.binding['scene_id'],
                 'person': self.binding['person_id'], 'epoch': self.binding['policy_epoch'],
                 'persona': self.binding['persona']}
        if self.binding.get('task_id'):
            task = task_records.get(self.store, self.binding['task_id'], scene=self.binding['scene_id'],
                                    requester=self.binding['person_id'], epoch=self.binding['policy_epoch'])
            if not task:
                return None
            # The turn the task works for: on an errand, the home turn that sent it (errands.home_turn).
            from .errands import home_turn
            begun = home_turn(self.store, episode_records.get(self.store, task['episode_id'], fields=['errand'])
                              or {'_id': task['episode_id']})
            stream = begun['_id']
        for audit in audit_trail.prepared_for(self.store, scope, self.binding['person_id'], self.binding['policy_epoch'],
                                              stream=stream):
            episode = episode_records.get(self.store, audit['stream_id'],
                                          ['context', 'manifest', 'monologue_refs', 'understanding_seen'], **fence)
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
                # ADR-082: in a group, what an entry or a recall of hers showed of each person.
                shown = {rev for pins in [*(manifest.get('people_shown') or {}).values(),
                                          *(self.snapshot.get('understanding_seen') or {}).values()]
                         for rev in (pins or {}).values() if rev}
                if revision in shown:
                    return 'used'
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
