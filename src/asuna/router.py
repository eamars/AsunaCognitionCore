"""Trusted host envelopes and debug fixtures share the persisted application route."""
from collections import defaultdict,deque
from .evidence import canonical,sha
from .state import Store,Denied,now
from .peer_context import snapshot_event


class FairQueue:
    """At most two completed episodes from one scene before a waiting peer."""
    def __init__(self):self.queues=defaultdict(deque);self.scenes=deque();self.last=None;self.streak=0
    def put(self,scene,item):
        if not self.queues[scene]:self.scenes.append(scene)
        self.queues[scene].append(item)
    def pop(self):
        if not self.scenes:return None
        if self.scenes[0]==self.last and self.streak>=2 and len(self.scenes)>1:self.scenes.rotate(-1)
        scene=self.scenes[0];item=self.queues[scene].popleft()
        self.streak=self.streak+1 if self.last==scene else 1;self.last=scene
        if not self.queues[scene]:self.scenes.popleft()
        return item


class Router:
    def __init__(self,store,coordinator,executor=None,task_service=None):
        self.store,self.coordinator,self.executor,self.tasks=store,coordinator,executor,task_service

    def receive(self,event,*,persona='P1',workspace=None):
        # Identity and integration grants come from the host envelope, never
        # from quoted JSON in event text. Channel adapters cannot submit grants.
        scene=self.store.authorize(event['scene_id'],event['person_id'])
        allowed=('event_id','scene_id','person_id','text','occurred_at','trusted_context_events','episode_kind','scheduled_plan_id','task_id','intent_revision','delegation_depth','supersedes_task_id')
        trusted={k:event[k] for k in allowed if k in event}
        if isinstance(event.get('channel'),dict):
            # Channels.receive built this envelope after route/member checks.
            # Persist only the bounded peer snapshot, not arbitrary OneBot raw.
            trusted['channel']=event['channel']
            peer=snapshot_event(event)
            if peer: trusted['raw']={'asuna_peer':peer}
        if event.get('channel') and 'group_context' in event:
            trusted['group_context'] = event['group_context']
        if event.get('integration_profile'):
            from .integration import event_granted
            if event_granted(self.store.config, event): trusted['integration_profile'] = 'owner'
        self.store.audit('router','event.received',{'event_id':event['event_id'],'scene':scene['_id'],'adapter':'cli-fixture'},scene['scope_key'])
        if event.get('supersedes_task_id'):
            if not self.tasks:raise Denied('TASK_SERVICE_UNAVAILABLE')
            self.tasks.revise(event['supersedes_task_id'],trusted)
        wake = event.get('group_context', {}).get('wake_reason') if event.get('channel') else (event.get('mentioned') or event.get('scene_tick'))
        if scene['kind']=='group' and not wake and event.get('episode_kind') != 'task_feedback':
            if event.get('channel'):
                from .ingress import persist_input
                row, _ = persist_input(self.store, event, managed=True)
                self.store.put('messages', {**row, 'processing_outcome': 'RECORDED_NO_WAKE'}, expected=row['revision'], stream=row['episode_id'])
                return {'state': 'RECEIVED_NO_WAKE', 'message_id': row['_id']}
            key='quiet-'+sha(canonical([scene['_id'],event['event_id']]))
            previous=self.store.db.messages.find_one({'_id':key})
            if previous:return {'state':'RECEIVED_NO_WAKE','message_id':key}
            sequence=self.store.db.scenes.find_one_and_update({'_id':scene['_id']},{'$inc':{'sequence':1}},return_document=True)['sequence']
            self.store.put('messages',{'_id':key,'scope_key':scene['scope_key'],'scene_id':scene['_id'],'scene_seq':sequence,'adapter_id':'fixture','platform_event_id':event['event_id'],'text':event['text'],'author':event['person_id'],'direction':'inbound','delivery_state':'RECEIVED','occurred_at':event.get('occurred_at',now()),'received_at':now()},stream='router')
            return {'state':'RECEIVED_NO_WAKE','message_id':key}
        ep=self.coordinator.ingest(trusted,persona=persona)
        while ep['state']=='WAITING_TASK' and workspace is not None and self.executor:
            task=self.executor.run(ep['task_id'],workspace)
            feedback=self.tasks.feedback(task,self.coordinator)
            if feedback is None:break
            ep=feedback
        return ep

    def batch(self,events,**kwargs):
        queue=FairQueue()
        for event in events:queue.put(event['scene_id'],event)
        results=[]
        while (event:=queue.pop()) is not None:results.append(self.receive(event,**kwargs))
        return results
