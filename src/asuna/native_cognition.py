"""Read-only cognitive state coverage for the existing native Memory view."""
from .peer_context import peer_from_message, project_message


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
            return '已保存；当前会话暂无上下文可核对'
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
                overlay = context.get('overlay')
                if overlay is not None:
                    return '最近一次上下文已选用' if overlay == content else '已保存；最近一次上下文使用的是旧内容'
                selected = None
            if selected:
                return '最近一次上下文已选用' if selected == revision else '已保存；最近一次上下文使用的是旧版本'
        elif kind == 'doc':
            # The persona is a document (ADR-009); the manifest names the revision this turn rendered.
            selected = manifest.get('persona_revision') if key == 'persona' else manifest.get('documents', {}).get(key)
            if selected:
                return '最近一次上下文已选用' if selected == revision else '已保存；最近一次上下文使用的是旧版本'
        elif kind == 'unit':
            if key in manifest.get('selected', []):
                return '最近一次上下文已选用'
            if key in self.snapshot.get('monologue_refs', []):
                return '最近一轮形成的理解，保存在该轮原生会话中'
        elif kind == 'source':
            rows = list(context.get('delivered_history', []))
            group = context.get('group_continuity_from_program', {})
            rows += group.get('related_messages', []) + group.get('current_speaker_tail', [])
            if any(row.get('_id') == key for row in rows):
                return '最近一次上下文已选用'
            if key == 'in-' + self.snapshot['_id']:
                return '最近一次上下文的输入'
        return '已保存；最近一次上下文未选用'

    def peer(self):
        query = {'$and': [self.memory.message_query, {
            'direction': 'inbound', 'scene_id': self.binding['scene_id'],
            'author': self.binding['person_id'], 'event.raw.asuna_peer': {'$exists': True}}]}
        # A rejected newest block must not make an older identity look current.
        message = self.store.db.messages.find_one(query, sort=[('scene_seq', -1)])
        text = project_message(message) if message else None
        if not text:
            return None
        peer = peer_from_message(message)
        profile_at = peer.get('profile_at')
        # The cognition projection contains a UTC wall-clock fragment. The Web
        # view displays its timestamp separately in the browser's timezone.
        body = text.replace('，时间 ' + str(profile_at)[:19], '') if profile_at else text
        display = peer.get('display') or peer.get('card') or peer.get('nickname')
        display = ' '.join(display.replace('\x00', '').split())[:60] if isinstance(display, str) else ''
        return {'id': 'cognition:peer', 'kind': 'relation', 'title': '对方身份资料',
                'body': body, 'excerpt': body, 'category_label': '对人的认识', 'subject_name': display,
                'scene_id': self.binding['scene_id'], 'updated_at': profile_at or message.get('occurred_at'),
                'occurred_at': profile_at or message.get('occurred_at'),
                'status_label': '已记录', 'source_ids': [message['_id']],
                'usage': ('最近一次上下文已选用' if self.snapshot and
                          self.snapshot['context'].get('sender_identity') == text else
                          '已保存；最近一次上下文未选用' if self.snapshot else
                          '已保存；当前会话暂无上下文可核对')}

    def supplements(self, kind):
        rows = []
        if kind in ('all', 'self'):
            rows.append(self.placeholder('mood', 'self', '心情与情绪',
                '未实现独立、持续更新的心情与情绪状态。当前自我描述和当时的理解仍可查看；它们不等同于当前心情。'))
        if kind in ('all', 'relation'):
            peer = self.peer()
            rows.append(peer or self.placeholder('peer', 'relation', '对方身份资料',
                '当前场景暂无可核对的身份资料。昵称、群名片等只显示随真实消息保存并通过身份绑定校验的内容。',
                status='暂无记录'))
            rows.append(self.placeholder('portrait', 'relation', '用户画像整理',
                '未实现独立的事实、偏好和性格画像整理。已有内容保留在本人的关系理解、交流摘要与原始来源中；角色的主观判断不等于对方确认的事实。'))
        if kind in ('all', 'world'):
            rows.append(self.placeholder('world', 'world', '世界知识整理',
                '未实现独立的世界知识整理。现有经验保存在交流摘要、当时的理解与原始来源中，仍可被检索使用；召回某个说法不等于角色已将其确认为知识。'))
        for row in rows:
            if row['kind'] == 'relation':
                row['scene_id'] = self.binding['scene_id']
        return rows

    @staticmethod
    def placeholder(key, kind, title, body, status='未实现'):
        return {'id': 'cognition:' + key, 'kind': kind, 'title': title,
                'body': body, 'excerpt': body if body.startswith(status) else status + ' · ' + body, 'status_label': status,
                'category_label': {'self': '自我', 'relation': '对人的认识', 'world': '对世界的认识'}[kind],
                'sources': [], 'interpretation': False}

    def subject_name(self):
        peer = self.peer()
        if peer and peer.get('subject_name'):
            return peer['subject_name'] + '（' + self.binding['person_id'].replace('qq:', 'QQ · ', 1) + '）'
        row = self.store.db.identities.find_one({'person_id': self.binding['person_id']},
                                               {'display_name': 1})
        return (row or {}).get('display_name') or self.binding['person_id'].replace('qq:', 'QQ · ', 1)
