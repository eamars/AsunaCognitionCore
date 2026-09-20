from __future__ import annotations
import json
from .config import prompt_path
from .evidence import canonical, sha
from .state import Store, Denied


class ContextBuilder:
    def __init__(self, store: Store, retrieval=None, skill_catalog=None):
        self.store,self.retrieval,self.skill_catalog=store,retrieval,skill_catalog

    def prepare(self, event: dict, persona='P1'):
        scene=self.store.authorize(event['scene_id'],event['person_id'])
        scope=scene['scope_key']
        head,revision=self.store.head('persona:'+persona,'global-safe') or (None,None)
        if not revision:
            raise ValueError('REQUIRED_PERSONA_MISSING')
        body=revision['content']['body']
        content_lines=[line for line in body.splitlines() if line.strip() and not line.startswith('#')]
        if len(''.join(content_lines))<80:
            raise ValueError('REQUIRED_PERSONA_BODY_MISSING')
        relation=self.store.head('relationship:'+event['person_id'],scope)
        overlay=self.store.head('overlay:'+persona,scope)
        history=list(self.store.db.messages.find({'scene_id':scene['_id'],'$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]},{'text':1,'author':1,'direction':1,'delivery_state':1,'platform_event_id':1}).sort('scene_seq',-1).limit(12))
        undelivered=list(self.store.db.messages.find({'scene_id':scene['_id'],'direction':'outbound','delivery_state':{'$in':['READY','FAILED','UNKNOWN']}},{'text':1,'delivery_state':1,'author':1}).sort('scene_seq',-1).limit(4))
        tail_sources={x for m in history for x in (m['_id'],m.get('platform_event_id')) if x}
        if self.retrieval:
            memories, retrieval_manifest=self.retrieval.search(scope,scene['policy_epoch'],event['text'],exclude_sources=tail_sources)
        else:
            memories=list(self.store.db.memory_units.find({'$or':[{'scope_key':'global-safe','policy_epoch':1},{'scope_key':scope,'policy_epoch':scene['policy_epoch']}],'status':'active'},{'embedding':0}).sort('_id',1).limit(6))
            retrieval_manifest={'path':'scoped_recent_development_fallback','vector_verified':False}
        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','source_event_ids','status','historical_sources','speaker','scene_seq','occurred_at','segment_index','segment_count') if k in m} for m in memories]
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
        task_states=list(self.store.db.tasks.find({'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch']},
            {'_id':1,'intent_revision':1,'state':1,'goal':1,'feedback_state':1,'finished_at':1,'cancel_reason':1,'revision_requested_at':1}).sort('revision',-1).limit(8))
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 'relationship':relation[1]['content'] if relation else None,'overlay':overlay[1]['content'] if overlay else None,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'memory_source_rules':'reported_speech 是来源人物说过的话，并非已核实的外部事实；同一人物的原话按 scene_seq 从旧到新排列。对于他自己的物品、偏好和更正，以他较新的明确陈述为准。public_statement 只证明角色说过这句话，承诺不等于完成；character_interpretation 只是角色当时的理解或猜测。角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。',
                 'task_state_from_program':task_states,
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        manifest={'persona_revision':head['revision_id'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        if self.store.config.get('task_mode')=='workspace':
            if relation:
                context['understanding_update_from_program']={
                    'available':True,'target':'只更新当前场景下对当前说话人的关系理解；不修改全局人格或权限。',
                    'route':'有值得留下的理解变化时，在 DECIDE 中选择 reflect_understanding=true；程序随后让你独立反思一次并提交。无需每轮更新。'}
            from .tasks import WORKSPACE_TOOLS
            context['action_capabilities_from_program']={
                'available':True,'route':'通过 DECIDE 的 delegate 委托行动脑；角色本身不直接调用工具。',
                'authorized_workspace':self.store.config['chat']['workspace'],
                'tools':[tool['name'] for tool in WORKSPACE_TOOLS],
                'read_only_paths':self.store.config['chat'].get('read_only_paths',[]),
                'cancellation_available':True,
                'network':'isolated','delivery':'程序自动执行委托，结果作为独立事件返回当前场景；等待时仍可聊天。'}
            from .skills import skills_directory
            if skills_directory(self.store.config,scene['_id'],event['person_id']):
                context['action_capabilities_from_program']['skill_development']='行动脑可在独立持久目录创建、试用和复用技能。你决定适用方式，再委托行动脑；下列目录说明不是已完成任务或公开承诺。'
                if self.skill_catalog:
                    context['available_skills_from_native_dsh']=self.skill_catalog()
            manifest['context_sha256']=sha(canonical(context))
        system=prompt_path(self.store.config,'common.md').read_text(encoding='utf-8')+'\n'+body
        return system,context,manifest
