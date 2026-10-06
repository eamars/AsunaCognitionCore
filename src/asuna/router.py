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
        allowed=('event_id','scene_id','person_id','text','occurred_at','trusted_context_events','episode_kind','scheduled_plan_id','task_id','intent_revision','delegation_depth','adapter_id','visit')
        trusted={k:event[k] for k in allowed if k in event}
        # Only the private native Host adapter supplies this execution identity;
        # channel payloads cannot choose a local native session or its authority.
        if not event.get('channel') and event.get('native_session_id'):
            trusted['native_session_id']=event['native_session_id']
            trusted['native_message_ids']=event.get('native_message_ids',[])
        if isinstance(event.get('channel'),dict):
            # Channels.receive built this envelope after route/member checks and already kept only
            # the verified profile, media block and group name (channels.kept_raw).
            trusted['channel']=event['channel']
            peer=snapshot_event(event)
            if peer: trusted['raw']={'asuna_peer':peer}
        if event.get('channel') and 'group_context' in event:
            trusted['group_context'] = event['group_context']
        if event.get('integration_profile'):
            from .integration import event_granted
            if event_granted(self.store.config, event): trusted['integration_profile'] = 'owner'
        elif isinstance(event.get('channel'),dict):
            # The owner's own platform DM carries the owner's workspace grant too (owner 2026-10-06); the route and
            # the canonical person decide it here, never anything the adapter sent.
            from .integration import event_granted, owner_dm
            if owner_dm(getattr(self.store,'config',None) or {},event['scene_id'],event['person_id']):
                try:
                    if event_granted(self.store.config,{**event,'integration_profile':'owner'}): trusted['integration_profile']='owner'
                except Denied:
                    pass
        if (event.get('development_profile')=='owner' and not event.get('channel')
                and (event['scene_id'],event['person_id']) == (
                    self.store.config['chat']['scene_id'],self.store.config['chat']['person_id'])
                and self.store.config.get('self_development',{}).get('enabled')):
            trusted['development_profile']='owner'
        self.store.audit('router','event.received',{'event_id':event['event_id'],'scene':scene['_id'],'adapter':event.get('adapter_id') or ('channel' if event.get('channel') else 'local')},scene['scope_key'])
        wake = event.get('group_context', {}).get('wake_reason') if event.get('channel') else (event.get('mentioned') or event.get('scene_tick'))
        if scene['kind']=='group' and not wake and event.get('episode_kind') != 'task_feedback':
            from .ingress import persist_input
            row, _ = persist_input(self.store, event, managed=True)
            self.store.put('messages', {**row, 'processing_outcome': 'RECORDED_NO_WAKE'}, expected=row['revision'], stream=row['episode_id'])
            return {'state': 'RECEIVED_NO_WAKE', 'message_id': row['_id']}
        ep=self.coordinator.ingest(trusted,persona=persona)
        # Without the queued native Host (tests, diagnostics): run what she delegated, then her feedback turns.
        while workspace is not None and self.executor:
            ready=[task_id for task_id in ep.get('task_ids') or ()
                   if (self.store.db.tasks.find_one({'_id':task_id},{'state':1}) or {}).get('state')=='READY']
            if not ready:break
            for task_id in ready:
                task=self.executor.run(task_id,workspace)
                feedback=self.tasks.feedback(task,self.coordinator)
                if feedback is not None:ep=feedback
        return ep
