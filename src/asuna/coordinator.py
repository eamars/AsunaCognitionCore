from __future__ import annotations
import json
import copy
from pathlib import Path
import threading
import uuid
import jsonschema
from .config import BUNDLE, prompt_path
from .context import ContextBuilder
from .evidence import canonical, sha
from .lanes import Lane
from .publish import PublishService
from .state import Store, Conflict, Denied, now

DECISION_SCHEMA=json.loads((BUNDLE/'schemas/decision.schema.json').read_text(encoding='utf-8'))
WORKSPACE_DECISION_SCHEMA=copy.deepcopy(DECISION_SCHEMA)
WORKSPACE_DECISION_SCHEMA['properties']['cancel_task_id']={'type':'string','minLength':1,'maxLength':200}
WORKSPACE_DECISION_SCHEMA['properties']['reflect_understanding']={'type':'boolean'}
WORKSPACE_DECISION_SCHEMA['allOf'].append({'if':{'required':['cancel_task_id']},'then':{'properties':{'next':{'const':'speak'}}}})


class ProtocolFailure(RuntimeError):
    pass


class Coordinator:
    def __init__(self, store: Store, character: Lane, *, context=None, publisher=None, crash=lambda point:None,monologue_enabled=True):
        self.store,self.character = store,character
        self.context=context or ContextBuilder(store)
        self.publisher=publisher or PublishService(store,crash=crash)
        self.crash=crash
        self.lock=threading.RLock()
        self.monologue_enabled=monologue_enabled

    def ingest(self, event: dict, *, persona='P1'):
        with self.lock:
            scene=self.store.authorize(event['scene_id'],event['person_id'])
            ep_id='ep-'+sha(canonical([event['scene_id'],event['event_id'],event.get('episode_kind','external')]))[:32]
            existing=self.store.db.episodes.find_one({'_id':ep_id})
            if existing:
                self.store.audit(ep_id,'ingress.deduped',{'event_id':event['event_id']},scene['scope_key'])
                return existing
            from .ingress import persist_input
            persist_input(self.store,event)
            system,context,manifest=self.context.prepare(event,persona)
            self.store.audit(ep_id,'context.prepared',{'manifest':manifest,'context':context},scene['scope_key'])
            ep=self.store.put('episodes',{'_id':ep_id,'scene_id':scene['_id'],'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],'source_event_id':event['event_id'],'episode_kind':event.get('episode_kind','external'),'state':'PREPARED','persona':persona,'manifest':manifest,'context':context,'system':system,'person_id':event['person_id'],'monologue_refs':[],**{k:event[k] for k in ('task_id','intent_revision','delegation_depth','supersedes_task_id') if k in event}},stream=ep_id)
            if scene.get('character_context'):
                ep=self._update(ep,character_context=scene['character_context'])
            return self.advance(ep_id)

    def _update(self, ep, **changes):
        return self.store.put('episodes',{**ep,**changes},expected=ep['revision'],stream=ep['_id'])

    def _stage(self, ep, phase, round_id=0, extra=''):
        operation=f"{ep['_id']}:{phase}:{round_id}"
        instruction=prompt_path(self.store.config,f'stage_{phase.lower()}.md').read_text(encoding='utf-8')
        if phase=='MONOLOGUE' or (not self.monologue_enabled and phase=='DECIDE'):
            instruction=json.dumps(ep['context'],ensure_ascii=False,default=str)+'\n'+instruction
        instruction += '\n'+extra
        self.store.audit(ep['_id'],'phase.started',{'operation':operation,'phase':phase},ep['scope_key'])
        binding=f"xiaoman:{ep['scene_id']}:{ep['policy_epoch']}:{ep['persona']}"
        if ep.get('character_context'):binding+=':'+ep['character_context']
        value=self.character.generate(binding,operation,phase,instruction,ep['system'])
        self.crash('after_lane_delivery')
        self.store.audit(ep['_id'],'phase.output',{'operation':operation,'phase':phase,'content':value.content,'reasoning':value.reasoning,'finish_reason':value.finish_reason,'request_refs':value.request_refs,'receipt':value.receipt},ep['scope_key'])
        if value.finish_reason!='stop' or not value.content.strip() or value.tool_calls:
            raise ProtocolFailure('INVALID_STAGE_OUTPUT')
        return value.content

    def advance(self, ep_id: str):
        with self.lock:
            ep=self.store.db.episodes.find_one({'_id':ep_id})
            if not ep:
                raise ValueError('EPISODE_NOT_FOUND')
            try:
                if ep['state']=='PREPARED':
                    if not self.monologue_enabled:
                        ep=self._update(ep,state='MONOLOGUE_ACCEPTED',monologue_refs=[],experiment_control='monologue_off')
                if ep['state']=='PREPARED':
                    text=self._stage(ep,'MONOLOGUE',ep.get('recall_rounds',0))
                    memory_id='mono-'+ep_id+':'+str(ep.get('recall_rounds',0))
                    if not self.store.db.memory_units.find_one({'_id':memory_id}):
                        self.store.put('memory_units',{'_id':memory_id,'character_id':'xiaoman','kind':'monologue','scope_key':ep['scope_key'],'policy_epoch':ep['policy_epoch'],'body_markdown':text,'epistemic_type':'character_interpretation','source_event_ids':[ep['source_event_id']],'depends_on':[ep['source_event_id']],'episode_id':ep_id,'status':'active','embedding_status':'PENDING'},stream=ep_id)
                    ep=self._update(ep,state='MONOLOGUE_ACCEPTED',monologue_refs=[memory_id])
                if ep['state']=='MONOLOGUE_ACCEPTED':
                    for attempt in range(2):
                        text=self._stage(ep,'DECIDE',ep.get('recall_rounds',0)*2+attempt,extra='修复上一条JSON，只修复格式，不改变意图。' if attempt else '')
                        try:
                            decision=json.loads(text)
                            jsonschema.validate(decision,WORKSPACE_DECISION_SCHEMA if self.store.config.get('task_mode')=='workspace' else DECISION_SCHEMA)
                            break
                        except (ValueError,jsonschema.ValidationError):
                            if attempt==1:
                                raise ProtocolFailure('BAD_DECISION_JSON')
                    ep=self._update(ep,state='DECISION_ACCEPTED',decision=decision)
                if ep['state']=='DECISION_ACCEPTED':
                    if ep['decision'].get('reflect_understanding') and not ep.get('understanding_update'):
                        from .memory import MemoryService
                        if not ep['context'].get('understanding_update_from_program',{}).get('available'):
                            raise Denied('UNDERSTANDING_UPDATE_NOT_AVAILABLE')
                        text=self._stage(ep,'REFLECT')
                        update=MemoryService(self.store).commit_understanding(ep,text)
                        ep=self._update(ep,understanding_update=update)
                    if ep['decision'].get('cancel_task_id') and not ep.get('control_result'):
                        from .tasks import TaskService
                        target=self.store.db.tasks.find_one({'_id':ep['decision']['cancel_task_id'],
                            'scene_id':ep['scene_id'],'requester_id':ep['person_id'],'policy_epoch':ep['policy_epoch']})
                        if not target or target['_id'] not in {t['_id'] for t in ep['context']['task_state_from_program']}:
                            raise Denied('CANCEL_TASK_NOT_IN_CURRENT_CONTEXT')
                        if target['state'] in ('READY','RUNNING'):
                            target=TaskService(self.store).cancel(target['_id'],reason='character_confirmed_user_cancellation',person_id=ep['person_id'])
                        ep=self._update(ep,control_result={'action':'cancel','task_id':target['_id'],'actual_state':target['state']})
                    next_step=ep['decision']['next']
                    if next_step=='silent':
                        return self._update(ep,state='COMMITTED',silent_reason=ep['decision']['goal'])
                    if next_step=='recall':
                        rounds=ep.get('recall_rounds',0)
                        if rounds>=2:
                            return self._update(ep,state='NEEDS_INFORMATION',reason='recall budget exhausted')
                        event={'event_id':ep['source_event_id'],'scene_id':ep['scene_id'],'person_id':ep['person_id'],'text':ep['decision']['recall_query']}
                        _, recalled,manifest=self.context.prepare(event,ep['persona'])
                        context={**ep['context'],'recall':{'query':ep['decision']['recall_query'],'memories':recalled['memories']}}
                        for old_id in ep['monologue_refs']:
                            old=self.store.db.memory_units.find_one({'_id':old_id})
                            self.store.put('memory_units',{**old,'status':'superseded'},expected=old['revision'],stream=ep_id)
                        ep=self._update(ep,state='PREPARED',recall_rounds=rounds+1,context=context)
                        return self.advance(ep_id)
                    if next_step=='delegate':
                        if self.store.config.get('task_mode')=='workspace':
                            from .resources import workspace_grant
                            workspace_grant(self.store.config, ep['scene_id'], ep['person_id'])
                        if ep.get('delegation_depth',0)>=3:
                            return self._update(ep,state='BLOCKED',reason='delegation depth exhausted')
                        task_id=ep.get('supersedes_task_id') or 'task-'+ep_id
                        intent_revision=1
                        if ep.get('supersedes_task_id'):
                            from .tasks import TaskService
                            revised=TaskService(self.store).activate_revision(ep)
                            intent_revision=revised['intent_revision']
                        if not self.store.db.tasks.find_one({'_id':task_id}):
                            from .tasks import WORKSPACE_TOOLS,TOOLS
                            capabilities=WORKSPACE_TOOLS if self.store.config.get('task_mode')=='workspace' else TOOLS
                            self.store.put('tasks',{'_id':task_id,'request_key':task_id,'episode_id':ep_id,'scene_id':ep['scene_id'],'scope_key':ep['scope_key'],'requester_id':ep['person_id'],'policy_epoch':ep['policy_epoch'],'persona_revision':ep['manifest']['persona_revision'],'intent_revision':1,'goal':ep['decision']['goal'],'constraints':ep['decision']['constraints'],'raw_input_refs':['in-'+ep_id],'state':'READY','fencing_token':0,'tool_steps':0,'allowed_capabilities':[t['name'] for t in capabilities]},stream=ep_id)
                        self.crash('after_task_persist')
                        if not ep['decision']['speak_before_action']:
                            return self._update(ep,state='WAITING_TASK',task_id=task_id,intent_revision=intent_revision)
                        ep=self._update(ep,task_id=task_id,intent_revision=intent_revision)
                    results={k:ep[k] for k in ('control_result','understanding_update') if k in ep}
                    text=self._stage(ep,'SPEAK',extra='程序已提交的结果：'+json.dumps(results,ensure_ascii=False) if results else '')
                    ep=self._update(ep,state='SPEAK_ACCEPTED',speech=text)
                if ep['state']=='SPEAK_ACCEPTED':
                    key=ep_id+':speak:0'
                    if not self.store.db.messages.find_one({'_id':key}):
                        sequence=self.store.db.scenes.find_one_and_update({'_id':ep['scene_id']},{'$inc':{'sequence':1}},return_document=True)['sequence']
                        self.store.put('messages',{'_id':key,'publication_key':key,'episode_id':ep_id,'scene_id':ep['scene_id'],'scene_seq':sequence,'scope_key':ep['scope_key'],'policy_epoch':ep['policy_epoch'],'text':ep['speech'],'direction':'outbound','author':'xiaoman','phase':'SPEAK','reply_to':'in-'+ep_id,'monologue_refs':ep['monologue_refs'],'delivery_state':'READY'},stream=ep_id)
                    self.publisher.publish(key)
                    self.crash('before_episode_commit')
                    ep=self._update(ep,state='WAITING_TASK' if ep['decision']['next']=='delegate' else 'COMMITTED')
                return ep
            except ProtocolFailure as exc:
                self.store.audit(ep_id,'phase.failed',{'reason':str(exc)},ep['scope_key'])
                return self._update(ep,state='FAILED_PROTOCOL',failure=str(exc))

    def recover(self):
        self.store.recover_commits()
        return [self.advance(ep['_id']) for ep in self.store.db.episodes.find({'state':{'$in':['PREPARED','MONOLOGUE_ACCEPTED','DECISION_ACCEPTED','SPEAK_ACCEPTED']}})]
