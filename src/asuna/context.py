from __future__ import annotations
import json
import traceback
from .config import prompt_path, redact_text
from .evidence import canonical, sha
from .state import Store, Denied
from .peer_context import apply_peer_context


class ContextBuilder:
    def __init__(self, store: Store, retrieval=None, skill_catalog=None):
        self.store,self.retrieval,self.skill_catalog=store,retrieval,skill_catalog

    def _reply_context(self, rows, scene):
        """Keep transport reply attribution when projecting scoped history."""
        for row in rows:
            event = row.pop('event', {})
            group = event.get('group_context', {})
            if group:
                row['mentioned_account_ids'] = group.get('mentioned_account_ids', [])
            reply = row.pop('platform_reply_to', None) or group.get('reply_to')
            if not reply:
                continue
            row['reply_to'] = reply
            parent = self.store.db.messages.find_one({
                'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
                '$or': [{'direction': 'inbound', 'event.channel.platform_event_id': reply},
                        {'direction': 'outbound', 'platform_message_id': reply,
                         'delivery_state': 'DELIVERED'}]},
                {'text': 1, 'author': 1, 'direction': 1})
            if parent:
                row['reply_to_message'] = parent
        return rows

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
        from .ingress import episode_id
        source = self.store.db.messages.find_one({'_id': 'in-' + episode_id(event)})
        history_query = {'scene_id':scene['_id'],'policy_epoch':scene['policy_epoch'],
                         '$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]}
        if source:
            # Newly accepted/future queued inputs must not enter an earlier turn.
            history_query['$or'][0]['scene_seq'] = {'$lt': source['scene_seq']}
        history=list(self.store.db.messages.find(history_query,{'text':1,'author':1,'direction':1,'delivery_state':1,'platform_event_id':1,
            'platform_reply_to':1,'event.group_context':1}).sort('scene_seq',-1).limit(12))
        self._reply_context(history, scene)
        undelivered=list(self.store.db.messages.find({'scene_id':scene['_id'],'direction':'outbound','delivery_state':{'$in':['READY','QUEUED_EXTERNAL','SENDING','FAILED','UNKNOWN']}},{'text':1,'delivery_state':1,'author':1}).sort('scene_seq',-1).limit(4))
        tail_sources={x for m in history for x in (m['_id'],m.get('platform_event_id')) if x}
        if source:
            for queued in self.store.db.messages.find({'scene_id':scene['_id'], 'direction':'inbound',
                                                       'scene_seq':{'$gte':source['scene_seq']}},
                                                      {'platform_event_id':1}):
                tail_sources.update((queued['_id'], queued.get('platform_event_id')))
        if self.retrieval:
            try:
                memories, retrieval_manifest=self.retrieval.search(scope,scene['policy_epoch'],event['text'],exclude_sources=tail_sources)
            except (Denied, PermissionError):
                raise
            except Exception:
                # Authorization, persona and direct scoped history already
                # succeeded. Optional RAG must not prevent diagnosis/chat.
                memories=[]
                retrieval_manifest={'path':'scoped_history_without_rag','vector_verified':False,
                                    'error':redact_text(traceback.format_exc(),self.store.config)}
        else:
            memories=list(self.store.db.memory_units.find({'$or':[{'scope_key':'global-safe','policy_epoch':1},{'scope_key':scope,'policy_epoch':scene['policy_epoch']}],'status':'active'},{'embedding':0}).sort('_id',1).limit(6))
            retrieval_manifest={'path':'scoped_recent_development_fallback','vector_verified':False}
        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','source_event_ids','status','historical_sources','speaker','scene_seq','occurred_at','segment_index','segment_count') if k in m} for m in memories]
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
        task_states=list(self.store.db.tasks.find({'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch']},
            {'_id':1,'intent_revision':1,'state':1,'goal':1,'feedback_state':1,'finished_at':1,'cancel_reason':1,'revision_requested_at':1}).sort('revision',-1).limit(8))
        plans=list(self.store.db.plans.find({'scene_id':scene['_id'],'scope_key':scope,
            'person_id':event['person_id'],'policy_epoch':scene['policy_epoch'],
            'status':{'$in':['CREATING','ACTIVE']}},
            {'_id':1,'intent':1,'rule':1,'scheduled_at':1,'status':1}).sort('created_at',-1).limit(8))
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 'relationship':relation[1]['content'] if relation else None,'overlay':overlay[1]['content'] if overlay else None,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'memory_source_rules':'reported_speech 是来源人物说过的话，并非已核实的外部事实；同一人物的原话按 scene_seq 从旧到新排列。对于他自己的物品、偏好和更正，以他较新的明确陈述为准。public_statement 只证明角色说过这句话，承诺不等于完成；character_interpretation 只是角色当时的理解或猜测。角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。',
                 'task_state_from_program':task_states,
                 'plans_from_program':plans,
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        if source:
            apply_peer_context(context,source)
        if event.get('episode_kind')=='scheduled':
            plan=self.store.db.plans.find_one({'_id':event.get('scheduled_plan_id'),
                'scene_id':scene['_id'],'scope_key':scope,'person_id':event['person_id'],
                'policy_epoch':scene['policy_epoch']},
                {'_id':1,'intent':1,'rule':1,'last_occurrence_id':1,'last_outcome':1})
            if not plan:raise Denied('SCHEDULE_PLAN_CONTEXT_MISSING')
            context['scheduled_plan_from_program']=plan
        if retrieval_manifest.get('error'):
            context['retrieval_diagnostic_from_host']=retrieval_manifest
        if source and source.get('failure'):
            context['prior_input_failure_from_host']=source['failure']
        if event.get('group_context'):
            group = event['group_context']
            refs = [group.get('reply_message_id')]
            if group.get('topic_id'):
                anchor = self.store.db.messages.find_one({'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
                                                         'event.event_id': group['topic_id']}, {'_id':1})
                if anchor: refs.append(anchor['_id'])
            related = list(self.store.db.messages.find({'_id': {'$in': [r for r in refs if r]},
                'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch']},
                {'text':1, 'author':1, 'direction':1, 'scene_seq':1, 'delivery_state':1,
                 'platform_reply_to':1, 'event.group_context':1}))
            self._reply_context(related, scene)
            speaker_tail = list(self.store.db.messages.find({'scene_id':scene['_id'], 'policy_epoch':scene['policy_epoch'],
                'author':event['person_id'], 'direction':'inbound', 'scene_seq':{'$lt':source['scene_seq']}},
                {'text':1,'author':1,'scene_seq':1,'event.group_context':1}).sort('scene_seq',-1).limit(3)) if source else []
            self._reply_context(speaker_tail, scene)
            context['group_continuity_from_program'] = {**group, 'related_messages': related,
                                                       'current_speaker_tail': list(reversed(speaker_tail))}
        manifest={'persona_revision':head['revision_id'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        if self.store.config.get('task_mode')=='workspace':
            if relation:
                context['understanding_update_from_program']={
                    'available':True,'target':'只更新当前场景下对当前说话人的关系理解；不修改全局人格或权限。',
                    'route':'有值得留下的理解变化时，在 DECIDE 中选择 reflect_understanding=true；程序随后让你独立反思一次并提交。无需每轮更新。'}
            from .tasks import WORKSPACE_TOOLS
            from .resources import workspace_grant
            grant = workspace_grant(self.store.config, scene['_id'], event['person_id'], required=False)
            context['action_capabilities_from_program']={
                'available':bool(grant),'route':'通过 DECIDE 的 delegate 委托行动脑；角色本身不直接调用工具。',
                'authorized_workspace':grant.get('workspace'),
                'tools':[tool['name'] for tool in WORKSPACE_TOOLS] if grant else [],
                'read_only_paths':grant.get('read_only_paths',[]),
                'cancellation_available':True,
                'network':'isolated','delivery':'程序自动执行委托，结果作为独立事件返回当前场景；等待时仍可聊天。'}
            context['action_capabilities_from_program']['history_query']=(
                '可委托行动脑查询当前授权场景保存的完整原话：字面检索覆盖全部消息并按 cursor 续页，返回原文、作者、时间及其来源；'
                '语义候选不等于全部原话，送达回执时间会标明是回执。需要引用原话时以查询结果为准，不凭印象复述。')
            from .integration import event_granted, INTEGRATION_TOOLS
            if event_granted(self.store.config, event):
                context['action_capabilities_from_program']['integration'] = {
                    'tools': [tool['name'] for tool in INTEGRATION_TOOLS],
                    'grant': 'owner 在 Web 为本条消息明确选择了集成开发。开发目录独立持久保存；试运行和启用使用冻结副本。仅配置端点可达；进程启动不证明平台发送。'}
            from .skills import skills_directory
            if skills_directory(self.store.config,scene['_id'],event['person_id']):
                context['action_capabilities_from_program']['skill_development']='行动脑可在独立持久目录创建、试用和复用技能。你决定适用方式，再委托行动脑；下列目录说明不是已完成任务或公开承诺。'
                if self.skill_catalog:
                    try:context['available_skills_from_native_dsh']=self.skill_catalog()
                    except Exception:context['skill_catalog_diagnostic_from_host']=redact_text(traceback.format_exc(),self.store.config)
            manifest['context_sha256']=sha(canonical(context))
        system=prompt_path(self.store.config,'common.md').read_text(encoding='utf-8')+'\n'+body
        return system,context,manifest
