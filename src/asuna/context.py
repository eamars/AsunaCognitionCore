from __future__ import annotations
import json
import traceback
from .config import prompt_path, redact_text
from .evidence import canonical, sha
from .state import Store, Denied
from .peer_context import apply_peer_context

try:                                  # 宿主按包加载
    from . import schedule_rules
except Exception:                     # 同目录平铺加载（离线自检）也认
    import schedule_rules

# 主动机会给角色看的说明：只说清这是什么、她能选什么，不暗示她该说。
PROACTIVE_NOTE = ('这是一段没有@你的群讨论。程序按这个场景的闸门（安静时段、群里现在的语速、'
                  '同一话题没被接话之前只试一次、不催问）判断现在可以问你一句；值不值得说、'
                  '说多少、还是继续旁听，都由你定。沉默不需要理由，也不因为"有机会"就该开口。'
                  'related_messages 里带 topic_id 的是这条话题线到目前为止的原话（含没@你的旁听行），'
                  '谁说的以行上的 author 为准。')


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
        moment=schedule_rules.now_utc()          # 本轮只用一个时刻：算下一次钟点与给她看的钟面同源
        head,revision=self.store.head('persona:'+persona,'global-safe') or (None,None)
        if not revision:
            raise ValueError('REQUIRED_PERSONA_MISSING')
        body=revision['content']['body']
        content_lines=[line for line in body.splitlines() if line.strip() and not line.startswith('#')]
        if len(''.join(content_lines))<80:
            raise ValueError('REQUIRED_PERSONA_BODY_MISSING')
        relation=self.store.head('relationship:'+event['person_id'],scope)
        overlay=self.store.head('overlay:'+persona,scope)
        from .self_state import SelfState
        self_state=SelfState(self.store).read(persona,scope)
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
        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','kind','source_event_ids','source_window','generated_at','status','historical_sources','speaker','scene_seq','occurred_at','segment_index','segment_count','participants','source_by_speaker','attribution','corrected_by') if k in m} for m in memories]
        # derived_summary 显式与 public_statement 同层：它是程序按原文整理的转述，既不是
        # 角色的看法也不是人物亲口陈述。摘要没有 scene_seq/segment_index，同层内不抢位。
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'derived_summary':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
        task_states=list(self.store.db.tasks.find({'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch']},
            {'_id':1,'intent_revision':1,'state':1,'goal':1,'feedback_state':1,'finished_at':1,'cancel_reason':1,'revision_requested_at':1}).sort('revision',-1).limit(8))
        plan_rows=list(self.store.db.plans.find({'scene_id':scene['_id'],'scope_key':scope,
            'person_id':event['person_id'],'policy_epoch':scene['policy_epoch'],
            'kind':{'$ne':'self_development'},
            'status':{'$in':['CREATING','ACTIVE','SUSPENDED']}},
            {'_id':1,'intent':1,'rule':1,'scheduled_at':1,'status':1,'plan_version':1,
             'timezone':1,'tz_source':1,'next_fire_at':1,'created_at':1,'updated_at':1,
             'last_outcome':1}).sort('created_at',-1).limit(8))
        # P3：计划行按这个场景的时区翻成人话再给她看——不让她自己拿 UTC 心算「明天九点」。
        # 已暂停（SUSPENDED）也列出来：不列就等于她不知道自己有一条挂着的安排没生效。
        schedule_zone=schedule_rules.scene_timezone(self.store.config,scene)
        plans=[schedule_rules.project(row,schedule_rules.scene_timezone(self.store.config,scene,row),
                                      moment) for row in plan_rows]
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 'relationship':relation[1]['content'] if relation else None,'overlay':overlay[1]['content'] if overlay else None,
                 'self_state_from_program':self_state,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'memory_source_rules':'reported_speech 是来源人物说过的话，并非已核实的外部事实；同一人物的原话按 scene_seq 从旧到新排列。对于他自己的物品、偏好和更正，以他较新的明确陈述为准。public_statement 只证明角色说过这句话，承诺不等于完成；character_interpretation 只是角色当时的理解或猜测。角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。derived_summary 是程序后台从一段原文整理出来的有界摘要：source_window 是它覆盖的 scene_seq 区间，source_event_ids 可回读原文；它只证明那段交流里说过什么，不是新的经历，也不等于任何人确认过的事实，与同一人物较新的明确陈述冲突时以陈述为准，需要细节就回读来源。摘要只在 participants 覆盖当前说话人时才算这个人的证据：participants 里只有别人的那段是背景，不能当成当前说话人说过什么；attribution.corrections 与 corrected_by 是程序按真实 reply 链算出的更正标注，非空就说明这段转述之后有人更正过，以更正后的原话为准。',
                 'task_state_from_program':task_states,
                 'plans_from_program':plans,
                 'schedule_control_from_program':schedule_rules.control_note(schedule_zone,moment),
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        if event.get('episode_kind') == 'self_development':
            if event.get('task_id'):
                context['ongoing_development_task_id_from_program']=event['task_id']
            # Local owner opportunity may read the real scenes already bound to
            # this host. Keep source scene/author on each excerpt.
            allowed = {scene['_id']}
            for channel in self.store.config.get('channels', {}).values():
                allowed.update(route['scene_id'] for route in channel.get('routes', {}).values())
            recent = list(self.store.db.messages.find({
                'scene_id': {'$in': list(allowed)},
                '$or': [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]},
                {'scene_id':1,'author':1,'direction':1,'text':1,'received_at':1,
                 'delivery_state':1}).sort('received_at',-1).limit(30))
            tasks = list(self.store.db.tasks.find({'scene_id': {'$in': list(allowed)}},
                {'scene_id':1,'state':1,'goal':1,'failure_type':1,'result':1,
                 'feedback_state':1,'finished_at':1}).sort('finished_at',-1).limit(12))
            for item in tasks:
                if item.get('result'):
                    item['result_excerpt']=json.dumps(item.pop('result'),ensure_ascii=False,default=str)[:2400]
            lineage=list(self.store.db.sink_receipts.find({'kind':'self_development_publish'},
                {'candidate':1,'state':1,'changed_files':1,'deleted_files':1,'published_at':1,
                 'activated_at':1,'task_id':1,'reason':1}).sort('published_at',-1).limit(8))
            context['recent_experience_from_program'] = {
                'messages': list(reversed(recent)), 'tasks': tasks, 'publish_lineage':lineage,
                'note': '真实历史片段与行动结果；每条保留来源场景。未列出的历史仍可按原有授权查询。'}
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
            # P5：整条话题线（含没@她的旁听行）一并给出——接不上话题就谈不上要不要接话。
            seen = {row['_id'] for row in related}
            if group.get('topic_id'):
                for row in self.store.db.messages.find({'scene_id': scene['_id'],
                        'policy_epoch': scene['policy_epoch'],
                        'event.group_context.topic_id': group['topic_id'],
                        '$or': [{'direction':'inbound'}, {'delivery_state':'DELIVERED'}]},
                        {'text':1, 'author':1, 'direction':1, 'scene_seq':1, 'delivery_state':1,
                         'platform_reply_to':1, 'event.group_context':1}
                        ).sort('scene_seq', -1).limit(12):
                    if row['_id'] not in seen:
                        seen.add(row['_id'])
                        related.append(row)
                related.sort(key=lambda row: row.get('scene_seq') or 0)
            self._reply_context(related, scene)
            speaker_tail = list(self.store.db.messages.find({'scene_id':scene['_id'], 'policy_epoch':scene['policy_epoch'],
                'author':event['person_id'], 'direction':'inbound', 'scene_seq':{'$lt':source['scene_seq']}},
                {'text':1,'author':1,'scene_seq':1,'event.group_context':1}).sort('scene_seq',-1).limit(3)) if source else []
            self._reply_context(speaker_tail, scene)
            continuity = {**group, 'related_messages': related,
                          'current_speaker_tail': list(reversed(speaker_tail))}
            if str(group.get('wake_reason') or '').startswith('proactive'):
                continuity['proactive_from_program'] = PROACTIVE_NOTE
            context['group_continuity_from_program'] = continuity
        manifest={'persona_revision':head['revision_id'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        if self.store.config.get('task_mode')=='workspace':
            if relation:
                context['understanding_update_from_program']={
                    'available':True,'target':'只更新当前场景下对当前说话人的关系理解；不修改全局人格或权限。',
                    'route':'有值得留下的理解变化时，在 DECIDE 中选择 reflect_understanding=true；程序随后让你独立反思一次并提交。无需每轮更新。本轮上下文里的 derived_summary 也会被程序一并登记成这次理解的来源（按本轮实际展示与当前场景/纪元复核，不用你填 ID）；同一批原文已经进过这条关系时，程序记为未提交并给出原因，那不算你改过自己。群场景里只有 participants 覆盖当前说话人的摘要会被登记成这条关系的来源，盖不到人的摘要会带着原因记为未登记（照样给你看，只是不算这个人的证据）。'}
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
            development = (event.get('episode_kind') == 'self_development' or
                event.get('development_profile') == 'owner' or
                event.get('episode_kind') == 'task_feedback' and bool(
                    (self.store.db.tasks.find_one({'_id':event.get('task_id')}) or {}).get('development_grant')))
            if development and (scene['_id'],event['person_id']) == (
                    self.store.config['chat']['scene_id'],self.store.config['chat']['person_id']):
                from .development import DEVELOPMENT_TOOLS
                context['action_capabilities_from_program']['development'] = {
                    'candidate':'持久的有效项目候选；通过行动脑 development_* 工具编辑、检查、自选发布。',
                    'tools':[tool['name'] for tool in DEVELOPMENT_TOOLS]}
            context['action_capabilities_from_program']['history_query']=(
                '可委托行动脑查询当前授权场景保存的完整原话：字面检索覆盖全部消息并按 cursor 续页，返回原文、作者、时间及其来源；'
                '语义候选不等于全部原话，送达回执时间会标明是回执。需要引用原话时以查询结果为准，不凭印象复述。')
            context['action_capabilities_from_program']['group_discussion']=(
                '可按需整理当前授权群指定时间／主题的讨论：参与者、后续更正、个人意见、未决事项与实际覆盖范围分开返回，'
                '每条带 message_id 供原文回读；分类是按字面线索的机械标注不是结论，more=true 表示只覆盖了部分'
                '（还有未读原文，或同一 reply 链的讨论流没走完），续页之后才能说整理完整；按 person '
                '整理时链上带进来的上下文发言可能不是那个人说的（标 thread_context）。措辞与取舍仍由你'
                '判断，不自动总结、不自动发言。')
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
