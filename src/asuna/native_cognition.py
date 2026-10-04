"""Read-only cognitive state coverage for the existing native Memory view."""
from . import channel_kinds
from .peer_context import peer_from_message
from .people import People, safe_name


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
        if not self.snapshot:
            return '这个对话还没有可核对的一轮'
        context = self.snapshot['context']
        manifest = self.snapshot['manifest']
        kind, key = identifier.split(':', 1)
        if kind == 'head':
            entity = key.split('|', 1)[0]
            if entity.startswith('persona:'):
                selected = manifest.get('persona_revision')
            elif entity.startswith('relationship:'):
                selected = manifest.get('relationship_revision') if key == manifest.get('relationship_entity_key') else None
            elif entity.startswith(('character_core:', 'current_self:')):
                selected = (context.get('self_state_from_program', {}).get(entity.split(':')[0]) or {}).get('revision_id')
            else:
                selected = None
            if selected:
                return '最近一轮（{time}）用到了这一版' if selected == revision else '最近一轮（{time}）用的还是旧版本'
        elif kind == 'doc':
            # The persona is a document (ADR-009); the manifest names the revision this turn rendered.
            selected = manifest.get('persona_revision') if key == 'persona' else manifest.get('documents', {}).get(key)
            if selected:
                return '最近一轮（{time}）用到了这一版' if selected == revision else '最近一轮（{time}）用的还是旧版本'
        elif kind == 'unit':
            if key in manifest.get('selected', []):
                return '最近一轮（{time}）用到了这一版'
            if key in self.snapshot.get('monologue_refs', []):
                return '最近一轮形成的理解，保存在该轮原生会话中'
        elif kind == 'source':
            rows = list(context.get('delivered_history', []))
            group = context.get('group_continuity_from_program', {})
            rows += group.get('related_messages', []) + group.get('current_speaker_tail', [])
            if any(row.get('_id') == key for row in rows):
                return '最近一轮（{time}）用到了这一版'
            if key == 'in-' + self.snapshot['_id']:
                return '是最近一轮（{time}）的输入'
        return '最近一轮（{time}）没有用到'

    def peer(self):
        query = {'$and': [self.memory.message_query, {
            'direction': 'inbound', 'scene_id': self.binding['scene_id'],
            'author': self.binding['person_id'], 'event.raw.asuna_peer': {'$exists': True}}]}
        # A rejected newest block must not make an older identity look current.
        message = self.store.db.messages.find_one(query, sort=[('scene_seq', -1)])
        scene = self.store.db.scenes.find_one({'_id': self.binding['scene_id']}) if message else None
        # The same line her turn reads (people.py), so "用到了这一版" compares like with like.
        text = People(self.store).identity_line(scene, message) if scene else None
        if not text:
            return None
        peer = peer_from_message(message)
        profile_at = peer.get('profile_at')
        body = text
        display = safe_name(peer.get('card')) or safe_name(peer.get('nickname'))
        return {'id': 'cognition:peer', 'kind': 'relation', 'title': '对方身份资料',
                'body': body, 'excerpt': body, 'category_label': '对人的认识', 'subject_name': display,
                'scene_id': self.binding['scene_id'], 'updated_at': profile_at or message.get('occurred_at'),
                'occurred_at': profile_at or message.get('occurred_at'),
                'status_label': '已记录', 'source_ids': [message['_id']],
                'usage': ('最近一轮（{time}）用到了这一版' if self.snapshot and
                          self.snapshot['context'].get('sender_identity') == text else
                          '最近一轮（{time}）没有用到' if self.snapshot else
                          '这个对话还没有可核对的一轮')}

    def supplements(self, kind):
        """The platform identity saved with this person's latest message, when there is one."""
        peer = self.peer() if kind in ('all', 'relation') else None
        if peer:
            peer['scene_id'] = self.binding['scene_id']
        return [peer] if peer else []

    def subject_name(self):
        peer = self.peer()
        if peer and peer.get('subject_name'):
            return peer['subject_name'] + '（' + self.account_title() + '）'
        row = self.store.db.identities.find_one({'person_id': self.binding['person_id']},
                                               {'display_name': 1})
        return (row or {}).get('display_name') or self.account_title()

    def account_title(self):
        """qq:<account> reads as `QQ · <account>` on the owner's page; a local id reads as itself."""
        person = self.binding['person_id']
        platform = channel_kinds.of(person)
        return platform.TITLE + ' · ' + person.partition(':')[2] if platform else person
