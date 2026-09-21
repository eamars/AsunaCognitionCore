from __future__ import annotations
import uuid
from .state import Store, Denied, Conflict, now
from .evidence import sha
from .queue import database_effects_lock


class PublishService:
    def __init__(self, store: Store, *, idempotent=True, crash=lambda point: None):
        self.store,self.idempotent,self.crash = store,idempotent,crash

    def publish(self, message_id: str):
        with database_effects_lock(self.store.name):return self._publish(message_id)

    def _publish(self, message_id: str):
        db=self.store.db
        msg=db.messages.find_one({'_id':message_id})
        if not msg or msg.get('author')!='xiaoman' or msg.get('phase')!='SPEAK':
            raise Denied('ONLY_CHARACTER_SPEAK_CAN_PUBLISH')
        if msg['delivery_state'] in ('DELIVERED','UNKNOWN','FAILED'):
            return msg
        ep=db.episodes.find_one({'_id':msg['episode_id']})
        scene=db.scenes.find_one({'_id':msg['scene_id']})
        if not ep or ep['state'] not in ('SPEAK_ACCEPTED','COMMITTED') or ep['policy_epoch']!=scene['policy_epoch'] or msg['scope_key']!=scene['scope_key']:
            raise Denied('PUBLICATION_CONTEXT_STALE')
        if ep.get('task_id'):
            task=db.tasks.find_one({'_id':ep['task_id']})
            if not task or task['intent_revision']!=ep['intent_revision'] or task['state'] in ('CANCELLED','STALE','UNKNOWN'):
                raise Denied('PUBLICATION_INTENT_STALE')
        if scene.get('channel_id'):
            if msg['delivery_state'] in ('QUEUED_EXTERNAL', 'SENDING'):
                return msg
            from .channels import route_for_scene
            route = route_for_scene(self.store.config, scene['channel_id'], scene['_id'])
            source_ep = ep
            # Feedback inherits the original transport target, including continued tasks.
            seen = set()
            while source_ep.get('episode_kind') == 'task_feedback':
                if source_ep['_id'] in seen:
                    raise Denied('PUBLICATION_SOURCE_CYCLE')
                seen.add(source_ep['_id'])
                task = db.tasks.find_one({'_id': source_ep['task_id']})
                source_ep = db.episodes.find_one({'_id': task['episode_id']})
            source = db.messages.find_one({'_id': 'in-' + source_ep['_id']})
            channel = (source or {}).get('event', {}).get('channel', {})
            if (channel.get('id') != scene['channel_id'] or channel.get('target') != route['target']
                    or channel.get('account_id') != self.store.config['channels'][scene['channel_id']]['account_id']):
                raise Denied('PUBLICATION_SOURCE_TARGET_MISMATCH')
            return self.store.put('messages', {**msg, 'delivery_state': 'QUEUED_EXTERNAL',
                                  'channel_id': scene['channel_id'], 'target': route['target'],
                                  'channel_account_id': channel['account_id'],
                                  'platform_reply_to': channel['platform_event_id']},
                                  expected=msg['revision'], stream=ep['_id'])
        if msg['delivery_state']=='SENDING' and not self.idempotent:
            return self.store.put('messages',{**msg,'delivery_state':'UNKNOWN'},expected=msg['revision'],stream=ep['_id'])
        receipt=db.sink_receipts.find_one({'_id':msg['publication_key']}) if self.idempotent else None
        if receipt is None:
            self.store.audit(ep['_id'],'publication.attempt',{'message_id':message_id,'key':msg['publication_key']},msg['scope_key'])
            msg=self.store.put('messages',{**msg,'delivery_state':'SENDING'},expected=msg['revision'],stream=ep['_id'])
            self.crash('before_send')
            receipt={'_id':msg['publication_key'] if self.idempotent else str(uuid.uuid4()),'publication_key':msg['publication_key'],'scope_key':msg['scope_key'],'text':msg['text'],'content_hash':sha(msg['text'].encode()),'received_at':now()}
            try:
                receipt=self.store.put('sink_receipts',receipt,stream=ep['_id'])
            except Conflict:
                receipt=db.sink_receipts.find_one({'_id':receipt['_id']})
                if receipt['content_hash'] != sha(msg['text'].encode()):
                    raise Denied('IDEMPOTENCY_CONTENT_MISMATCH')
            self.crash('after_send_before_receipt')
        self.store.audit(ep['_id'],'publication.receipt',{'message_id':message_id,'receipt_id':receipt['_id']},msg['scope_key'])
        return self.store.put('messages',{**msg,'delivery_state':'DELIVERED','delivery_basis':'local_sink','receipt':receipt['_id']},expected=msg['revision'],stream=ep['_id'])
