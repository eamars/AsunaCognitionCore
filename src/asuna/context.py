from __future__ import annotations
import json
import traceback
from .config import redact_text
from . import visibility
from .render import render_system, readable_sections, model_and_policy
from .documents import DocumentStore, render_markdown
from .persona_model import effective
from .evidence import canonical, sha
from .state import Store, Denied
from .peer_context import apply_peer_context

try:                                  # 宿主按包加载
    from . import schedule_rules
except Exception:                     # 同目录平铺加载（离线自检）也认
    import schedule_rules

try:                                  # 跨场景只读联动（A2）：联动范围现算自配置
    from . import scene_links
except Exception:
    scene_links = None                # 拿不到就整体不联动，与改动前逐字一致

# 主动机会给角色看的说明：只说清这是什么、她能选什么，不暗示她该说。
PROACTIVE_NOTE = ('这是一段没有@你的群讨论。程序按这个场景的闸门（安静时段、群里现在的语速、'
                  '同一话题没被接话之前只试一次、不催问）判断现在可以问你一句；值不值得说、'
                  '说多少、还是继续旁听，都由你定。沉默不需要理由，也不因为"有机会"就该开口。'
                  'related_messages 里带 topic_id 的是这条话题线到目前为止的原话（含没@你的旁听行），'
                  '谁说的以行上的 author 为准。')


# ADR-009 §8.2: context blocks in the persona's recall order; keys never sorted.
BLOCKS = {
    'self_state': ('self_state_from_program',),
    'dossier': ('dossier_from_program',),
    'affect': ('affect_from_program',),
    'affect_proposals': ('affect_proposals_from_program',),
    'relationship': ('relationship', 'relationship_shared_from_program'),
    'ledgers': ('ledgers_from_program',),
    'rhythm': ('rhythm_from_program',),
    'memories': ('memories', 'memory_source_rules', 'coverage_from_program'),
    'history': ('delivered_history', 'undelivered_outbound_not_public', 'linked_scenes_from_program'),
    'tasks_plans': ('task_state_from_program', 'plans_from_program', 'schedule_control_from_program',
                    'scheduled_plan_from_program'),
    'recent_phrasing': ('recent_phrasing_from_program',),
    'media': ('media_from_program',),
    'group_continuity': ('group_continuity_from_program',),
    'sender_identity': ('sender_identity',),
}
CONTEXT_HEAD = ('scene_id', 'scope_key', 'policy_epoch', 'person_id', 'session_class')
CONTEXT_TAIL = ('understanding_update_from_program', 'action_capabilities_from_program', 'proactive_from_program',
                'recent_experience_from_program')


def order_context(context, order=None):
    """Fixed head, ordered blocks (persona order, then the core default for the rest), fixed tail."""
    blocks = [b for b in (order or []) if b in BLOCKS] + [b for b in BLOCKS if b not in (order or [])]
    keys = [*CONTEXT_HEAD, *[k for b in blocks for k in BLOCKS[b]]]
    rest = [k for k in context if k not in keys and k not in CONTEXT_TAIL and k not in ('ref_index', 'event')
            and not k.endswith('_from_host')]
    tail = [*CONTEXT_TAIL, *[k for k in context if k.endswith('_from_host')], 'ref_index', 'event']
    return {k: context[k] for k in [*keys, *rest, *tail] if k in context}


def _section_view(section):
    return {k: section[k] for k in ('sid', 'heading', 'body', 'visibility', 'entry_date', 'tags') if k in section}


def dossier_block(docs, model, policy, person, cls):
    """§7: preamble always-sections + last N injectable entries + a title index (owner-private);
    public sessions see only public always-sections; the action brain sees none."""
    slug = 'dossier:' + person
    revision, content = docs.read(slug)
    if not content:
        return None
    sections = content['sections']
    if cls == visibility.OWNER_PRIVATE:
        preamble = [s for s in sections if (s['sid'] == '_preamble' or 'preamble' in s['tags']) and s['inject'] == 'always']
        entries = [s for s in sections if 'entry' in s['tags'] and 'injectable' in s['tags']]
        last = effective(model, 'dossier.inject_last', policy) or 0
        index_size = effective(model, 'dossier.index_size', policy) or 0
        chosen = preamble + (entries[-last:] if last else [])
        index = [{'sid': s['sid'], 'heading': s['heading'], 'entry_date': s.get('entry_date')} for s in entries[-index_size:]] if index_size else []
    else:
        chosen = [s for s in sections if s['visibility'] == 'public' and s['inject'] == 'always']
        index = []
    if not chosen and not index:
        return None
    return {'doc': slug, 'revision': revision, 'subject': content.get('subject'),
            'sections': [_section_view(s) for s in chosen], 'index': index,
            'note': '人物档案：只追加的积累式正文；需要别的条目原文时用 next=recall 加 read。'}


def ledger_block(docs, cls):
    out = []
    for slug in docs.slugs():
        revision, content = docs.read(slug)
        if not content or content.get('kind') != 'ledger':
            continue
        sections = readable_sections(content, cls)
        if sections:
            out.append({'doc': slug, 'revision': revision, 'title': content.get('title'),
                        'sections': [_section_view(s) for s in sections]})
    return out


INVENTED_MARK = '（自述编写，非共同经历）'


class ContextBuilder:
    def __init__(self, store: Store, retrieval=None):
        self.store,self.retrieval=store,retrieval

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
                **(scene_links.scene_id_filter(scene_links.read_scope(self.store.config, scene))
                   if scene_links else {'scene_id': scene['_id']}),
                'policy_epoch': scene['policy_epoch'],
                '$or': [{'direction': 'inbound', 'event.channel.platform_event_id': reply},
                        {'direction': 'outbound', 'platform_message_id': reply,
                         'delivery_state': 'DELIVERED'}]},
                {'text': 1, 'author': 1, 'direction': 1})
            if parent:
                row['reply_to_message'] = parent
        return rows

    def _merge_linked_history(self, own, scene, read, projection):
        """把联动场景的最近几条按「有效时间」归并进这一轮的上下文窗口。

        排序不能再拿 scene_seq 比：那是每个场景自己的序号，跨场景不可比。时间口径与查询侧一致
        （平台回执 ＞ 本机送达回执 ＞ 入站发生时刻 ＞ 落库时刻），每条行上带 scene_id，
        她能看出这句话是在哪个入口说的。联动场景的行只是给她看的历史，不是这个场景的新输入。
        """
        rows = []
        for scene_id in read['linked_scenes']:
            rows.extend(self.store.db.messages.find(
                {'scene_id': scene_id, 'policy_epoch': scene['policy_epoch'],
                 '$or': [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]},
                projection).sort('scene_seq', -1).limit(12))
        if not rows:
            return own
        merged = list(own) + rows
        for row in merged:
            row['scene_id'] = row.get('scene_id') or scene['_id']
        times = scene_links.message_times(self.store, merged)
        merged.sort(key=lambda row: (times.get(row['_id'], ('', ''))[0],
                                     row.get('scene_id', ''), row.get('scene_seq') or 0),
                    reverse=True)
        return merged[:12]

    def prepare(self, event: dict, persona='P1', history_session=None):
        scene=self.store.authorize(event['scene_id'],event['person_id'])
        scope=scene['scope_key']
        moment=schedule_rules.now_utc()          # 本轮只用一个时刻：算下一次钟点与给她看的钟面同源
        session_class=visibility.session_class(self.store.config,self.store.db,scene,event['person_id'])
        system,system_ref=render_system(self.store,persona,session_class)
        docs=DocumentStore(self.store,persona)
        persona_doc=docs.read('persona')[1]
        body=render_markdown(readable_sections(persona_doc,visibility.OWNER_PRIVATE))
        content_lines=[line for line in body.splitlines() if line.strip() and not line.startswith('#')]
        if len(''.join(content_lines))<80:
            raise ValueError('REQUIRED_PERSONA_BODY_MISSING')
        read=(scene_links.read_scope(self.store.config,scene) if scene_links else
              {'scene_id':scene['_id'],'scene_ids':[scene['_id']],'linked_scenes':[],
               'scope_keys':[scope],'linked_scope_keys':[]})
        target=(scene_links.relationship_target(self.store.config,self.store.db,scene,event['person_id'])
                if scene_links else {'entity':'relationship:'+event['person_id'],'scope':scope,
                                     'canonical':event['person_id'],'shared':False,'linked_scopes':[]})
        # 没配 canonical 映射时 target 就是原来那一份（relationship:<本人>｜本场景 scope）。
        relation=self.store.head(target['entity'],target['scope'])
        from .self_state import SelfState
        self_state=SelfState(self.store).read(persona,scope)
        from .ingress import episode_id
        source = self.store.db.messages.find_one({'_id': 'in-' + episode_id(event)})
        history_query = {'scene_id':scene['_id'],'policy_epoch':scene['policy_epoch'],
                         '$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]}
        if source:
            # Newly accepted/future queued inputs must not enter an earlier turn.
            history_query['$or'][0]['scene_seq'] = {'$lt': source['scene_seq']}
        history_projection={'text':1,'author':1,'direction':1,'delivery_state':1,'platform_event_id':1,
            'platform_reply_to':1,'event.group_context':1,'scene_seq':1,'episode_id':1}
        if read['linked_scenes']:
            # 只在真联动时多带这几个字段：归并要有可比的时间，行上也要能看出是哪个入口说的。
            history_projection=dict(history_projection,scene_id=1,occurred_at=1,receipt_at=1,
                                    receipt=1,received_at=1)
        history=list(self.store.db.messages.find(history_query,history_projection).sort('scene_seq',-1).limit(12))
        if read['linked_scenes']:
            history=self._merge_linked_history(history,scene,read,history_projection)
        self._reply_context(history, scene)
        undelivered=list(self.store.db.messages.find({'scene_id':scene['_id'],'direction':'outbound','delivery_state':{'$in':['READY','QUEUED_EXTERNAL','SENDING','FAILED','UNKNOWN']}},{'text':1,'delivery_state':1,'author':1}).sort('scene_seq',-1).limit(4))
        tail_sources={x for m in history for x in (m['_id'],m.get('platform_event_id')) if x}
        if source:
            for queued in self.store.db.messages.find({'scene_id':scene['_id'], 'direction':'inbound',
                                                       'scene_seq':{'$gte':source['scene_seq']}},
                                                      {'platform_event_id':1}):
                tail_sources.update((queued['_id'], queued.get('platform_event_id')))
        history_delta=None
        if history_session:
            # D-3: rows this role session already holds are not given again (full window after compaction).
            from .history_delta import select
            history,history_delta=select(self.store,history_session,history,scene['_id'],
                                         source['scene_seq'] if source else None)
        for row in history:
            row.pop('episode_id',None);row.pop('scene_seq',None)
        if self.retrieval:
            try:
                from .persona_model import effective as _effective
                from .render import model_and_policy as _model_and_policy
                _m,_p=_model_and_policy(self.store,persona)
                memories, retrieval_manifest=self.retrieval.search(scope,scene['policy_epoch'],event['text'],exclude_sources=tail_sources,
                                                                   coverage_floor=_effective(_m,'memory.coverage_floor',_p) or 0,
                                                                   salience={k:_effective(_m,'memory.salience.'+k,_p) for k in ('w_pin','w_heat','w_age','half_life_days')},
                                                                   linked_scopes=read['linked_scope_keys'],
                                                                   private_scope=visibility.owner_private_scope(persona)
                                                                       if session_class==visibility.OWNER_PRIVATE else None)
            except (Denied, PermissionError):
                raise
            except Exception:
                # Authorization, persona and direct scoped history already
                # succeeded. Optional RAG must not prevent diagnosis/chat.
                memories=[]
                retrieval_manifest={'path':'scoped_history_without_rag','vector_verified':False,
                                    'error':redact_text(traceback.format_exc(),self.store.config)}
        else:
            readable=[{'scope_key':'global-safe','policy_epoch':1},{'scope_key':scope,'policy_epoch':scene['policy_epoch']}]
            if session_class==visibility.OWNER_PRIVATE:
                readable.append({'scope_key':visibility.owner_private_scope(persona),'policy_epoch':1})
            memories=list(self.store.db.memory_units.find({'$or':readable,'status':'active'},{'embedding':0}).sort('_id',1).limit(6))
            retrieval_manifest={'path':'scoped_recent_development_fallback','vector_verified':False}
        # scope_key 一起给出：联动场景召回的记忆要说得清是从哪个场景来的，不然「他说过」会没头没尾。
        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','kind','source_event_ids','source_window','generated_at','status','historical_sources','speaker','scene_seq','occurred_at','scope_key','segment_index','segment_count','participants','source_by_speaker','attribution','corrected_by','entry_type','invented') if k in m} for m in memories]
        for fact in facts:
            if fact.get('invented'):
                # Fixed mark on every injection of persona-authored, not shared, history (MEMORY §5).
                fact['body_markdown']=INVENTED_MARK+fact['body_markdown']
        # derived_summary 显式与 public_statement 同层：它是程序按原文整理的转述，既不是
        # 角色的看法也不是人物亲口陈述。摘要没有 scene_seq/segment_index，同层内不抢位。
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'derived_summary':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
        # A storage revision counts writes/tool calls, not conversational time.
        # Use each task's durable input timestamp, including legacy tasks, so
        # recently returned work is not hidden behind old high-write tasks.
        task_states=list(self.store.db.tasks.aggregate([
            {'$match':{'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch']}},
            {'$lookup':{'from':'messages','localField':'raw_input_refs','foreignField':'_id',
                'pipeline':[{'$project':{'received_at':1,'_id':0}}],'as':'_inputs'}},
            {'$addFields':{'_active':{'$cond':[{'$in':['$state',['READY','RUNNING']]},1,0]},
                '_input_time':{'$max':'$_inputs.received_at'}}},
            {'$sort':{'_active':-1,'_input_time':-1,'_id':1}}, {'$limit':8},
            {'$project':{'_id':1,'intent_revision':1,'state':1,'goal':1,'feedback_state':1,'finished_at':1,
                'cancel_reason':1,'revision_requested_at':1,'pause_reason':1,'paused_at':1,'paused_state':1}},
        ]))
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
        if 'coverage' in retrieval_manifest:
            coverage_block={k:retrieval_manifest[k] for k in ('coverage','coverage_score','coverage_basis')}
            if retrieval_manifest['coverage']=='insufficient':
                coverage_block['note']='证据不足，只能当灵感，不能当事实说。'
        else:
            coverage_block=None
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 'relationship':relation[1]['content'] if relation else None,
                 'self_state_from_program':self_state,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'memory_source_rules':'reported_speech 是来源人物说过的话，并非已核实的外部事实；同一人物的原话按 scene_seq 从旧到新排列。对于他自己的物品、偏好和更正，以他较新的明确陈述为准。public_statement 只证明角色说过这句话，承诺不等于完成；character_interpretation 只是角色当时的理解或猜测。角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。derived_summary 是程序后台从一段原文整理出来的有界摘要：source_window 是它覆盖的 scene_seq 区间，source_event_ids 可回读原文；它只证明那段交流里说过什么，不是新的经历，也不等于任何人确认过的事实，与同一人物较新的明确陈述冲突时以陈述为准，需要细节就回读来源。摘要只在 participants 覆盖当前说话人时才算这个人的证据：participants 里只有别人的那段是背景，不能当成当前说话人说过什么；attribution.corrections 与 corrected_by 是程序按真实 reply 链算出的更正标注，非空就说明这段转述之后有人更正过，以更正后的原话为准。',
                 'task_state_from_program':task_states,
                 'plans_from_program':plans,
                 'schedule_control_from_program':schedule_rules.control_note(schedule_zone,moment),
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        if coverage_block:
            context['coverage_from_program']=coverage_block
        if history_delta and history_delta['omitted']:
            context['history_from_program']={'given':history_delta['given'],'omitted':history_delta['omitted'],
                'note':'这个会话里已经给过的行和你自己在本会话说过的话不再重复列出；delivered_history 只含新行。'}
        if any(task['state'] == 'PAUSED' for task in task_states):
            context['task_continuation_from_program'] = (
                'PAUSED 是重启后等待操作者决定的旧行动，历史与回执仍保留。'
                '只有本地用户明确要求继续时才可通过 continue_task_id 续接；'
                '普通聊天、内部机会及旧任务反馈不构成继续旧工作的授权。'
                '继续时先核实已有结果，未确认回执的操作不能盲目重做。')
        if read['linked_scenes']:
            context['linked_scenes_from_program']={
                'readable':read['linked_scenes'],'canonical_person':target['canonical'],
                'note':'delivered_history 与 memories 里带 scene_id／scope_key 的行可能来自这些联动场景'
                       '（配置认定是同一个人的另一个入口，只读）：它们不是这个场景里的新输入，不用当成'
                       '刚说的话再回应一次；要引用就说清那是在哪个入口说的。'}
        if target['shared']:
            context['relationship_shared_from_program']={
                'entity':target['entity'],'scope':target['scope'],
                'note':'这个人在配置里与另一个入口是同一个人，关系与偏好只维护那一份；这一轮的理解更新'
                       '会写进 %s，来源仍只取本轮场景里真实给过你的证据。' % target['scope']}
        if event.get('episode_kind') in ('self_development', 'presence'):
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
            # 这条消息里出现过什么非文本段：只给有界事实与「能不能按需拉」，不替她决定要不要看图。
            from .vision import media_note
            media=media_note(source,self.store.config)
            if media:context['media_from_program']=media
        if event.get('episode_kind')=='scheduled':
            plan=self.store.db.plans.find_one({'_id':event.get('scheduled_plan_id'),
                'scene_id':scene['_id'],'scope_key':scope,'person_id':event['person_id'],
                'policy_epoch':scene['policy_epoch']},
                {'_id':1,'intent':1,'rule':1,'last_occurrence_id':1,'last_outcome':1})
            if not plan:raise Denied('SCHEDULE_PLAN_CONTEXT_MISSING')
            context['scheduled_plan_from_program']=plan
        target_note=('只更新当前场景下对当前说话人的关系理解；不修改全局人格或权限。'
                     if not target['shared'] else
                     '只更新对当前说话人的关系理解。配置认定他与另一个入口是同一个人，这份关系记录共用'
                     '（写在 %s 那一份上，来源仍只取本轮场景里真实给过你的证据）；不修改全局人格或权限。'
                     % target['scope'])
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
        model,policy=model_and_policy(self.store,persona)
        documents={'persona':system_ref['persona_doc_revision'],'voice':system_ref['voice_doc_revision']}
        dossier=dossier_block(docs,model,policy,target.get('canonical') or event['person_id'],session_class)
        if dossier:
            context['dossier_from_program']=dossier
            documents[dossier['doc']]=dossier['revision']
        ledgers=ledger_block(docs,session_class)
        if ledgers:
            context['ledgers_from_program']=ledgers
            documents.update({item['doc']:item['revision'] for item in ledgers})
        from .ingress import episode_id as _episode_id
        context['ref_index']=list(dict.fromkeys([event['event_id'],'in-'+_episode_id(event),*[m['_id'] for m in memories],
            *[t['_id'] for t in task_states],
            *['doc:%s#%s'%(item['doc'],section['sid']) for item in [*([dossier] if dossier else []),*ledgers] for section in item['sections']],
            *['doc:persona#'+section['sid'] for section in readable_sections(persona_doc,session_class)]]))
        manifest={'session_class':session_class,'documents':documents,'persona_revision':system_ref['persona_doc_revision'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'relationship_entity_key':relation[0]['_id'] if relation else None,'linked_scenes':read['linked_scenes'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        if history_delta:
            manifest['history_delta']=history_delta
        if relation:
            context['understanding_update_from_program']={
                'available':True,'target':target_note,
                'route':'有值得留下的理解变化时，在 DECIDE 中选择 reflect_understanding=true；程序随后让你独立反思一次并提交。无需每轮更新。本轮上下文里的 derived_summary 也会被程序一并登记成这次理解的来源（按本轮实际展示与当前场景/纪元复核，不用你填 ID）；同一批原文已经进过这条关系时，程序记为未提交并给出原因，那不算你改过自己。群场景里只有 participants 覆盖当前说话人的摘要会被登记成这条关系的来源，盖不到人的摘要会带着原因记为未登记（照样给你看，只是不算这个人的证据）。'}
        from .grants import workspace_grant
        grant = workspace_grant(self.store.config, scene['_id'], event['person_id'], required=False)
        context['action_capabilities_from_program']={
            'available':bool(grant),'route':'通过 DECIDE 的 delegate 委托行动脑；角色本身不直接调用工具。',
            'cancellation_available':True,
            'network':'行动脑可以按需搜索公共网页并读取页面。',
            'delivery':'程序自动执行委托，结果作为独立事件返回当前场景；等待时仍可聊天。'}
        development = (event.get('episode_kind') == 'self_development' or
            event.get('development_profile') == 'owner' or
            event.get('episode_kind') == 'task_feedback' and bool(
                (self.store.db.tasks.find_one({'_id':event.get('task_id')}) or {}).get('development_grant')))
        if development and (scene['_id'],event['person_id']) == (
                self.store.config['chat']['scene_id'],self.store.config['chat']['person_id']):
            context['action_capabilities_from_program']['development'] = {
                'candidate':'持久的有效项目候选；可委托行动脑检查、修改和自行发布。'}
        context['action_capabilities_from_program']['history_query']=(
            '可委托行动脑查询当前授权场景保存的完整原话：字面检索覆盖全部消息并按 cursor 续页，返回原文、作者、时间及其来源；'
            '语义候选不等于全部原话，送达回执时间会标明是回执。需要引用原话时以查询结果为准，不凭印象复述。')
        from .vision import vision_capability
        if vision_capability(self.store.config)['supported']:
            context['action_capabilities_from_program']['read_image']=(
                '图片按 Pull 模式接：入站只带元数据与占位符，委托行动脑时用 read_image(ref) 才把字节拉成'
                '这一轮真实的视觉输入。没调用就是没看过，占位符只证明那里有过一张图。')
        context['action_capabilities_from_program']['group_discussion']=(
            '可按需整理当前授权群指定时间／主题的讨论：参与者、后续更正、个人意见、未决事项与实际覆盖范围分开返回，'
            '每条带 message_id 供原文回读；分类是按字面线索的机械标注不是结论，more=true 表示只覆盖了部分'
            '（还有未读原文，或同一 reply 链的讨论流没走完），续页之后才能说整理完整；按 person '
            '整理时链上带进来的上下文发言可能不是那个人说的（标 thread_context）。措辞与取舍仍由你'
            '判断，不自动总结、不自动发言。')
        from .integration import event_granted
        if event_granted(self.store.config, event):
            context['action_capabilities_from_program']['integration'] = {
                'grant': '本机 owner 工作域允许集成开发。开发目录独立持久保存；试运行和启用使用冻结副本。仅配置端点可达；进程启动不证明平台发送。'}
        from .skills import skills_directory
        if skills_directory(self.store.config,scene['_id'],event['person_id']):
            context['action_capabilities_from_program']['skill_development']='行动脑可在独立持久目录创建、试用和复用技能。你决定适用方式，再委托行动脑；下列目录说明不是已完成任务或公开承诺。'
        manifest['context_sha256']=sha(canonical(context))
        from .affect import AffectLedger
        ledger=AffectLedger(self.store,persona,model,policy)
        if ledger.enabled:
            # One heart per persona: the state is global; reasons, who and numbers stay owner-private (§6.5).
            m=ledger.model
            context['affect_from_program']={**ledger.description(session_class),
                'commit_rules':{'require_cost':bool(m.get('require_cost')),'max_delta':m.get('max_delta'),
                                'kinds':sorted(m.get('kinds',{})),'allow_untyped':bool(m.get('allow_untyped',True))}}
            proposals=ledger.proposals(scope,session_class)
            if proposals:
                context['affect_proposals_from_program']={'items':proposals,
                    'note':'情感评估路由给出的提案，只是建议：用 affect_adopt 逐条 accept/decline/edit；过期的已明示，不再能采纳。'}
        from .rhythm import rhythm_block, recent_phrasing
        owner=(self.store.config.get('chat') or {}).get('person_id')
        last=next(iter(self.store.db.messages.find({'direction':'inbound','author':owner},{'received_at':1}).sort('received_at',-1).limit(1)),None) if owner else None
        rhythm=rhythm_block(self.store,model,policy,session_class,moment=moment,owner_last_at=(last or {}).get('received_at'))
        if rhythm:
            context['rhythm_from_program']=rhythm
        own=[row.get('text','') for row in self.store.db.messages.find({'scene_id':scene['_id'],'direction':'outbound',
             'delivery_state':'DELIVERED'},{'text':1}).sort('scene_seq',-1).limit(int(effective(model,'phrasing.window',policy) or 20))]
        phrasing=recent_phrasing(own)
        if phrasing:
            context['recent_phrasing_from_program']={'repeated_4grams':phrasing,
                'note':'你最近常用这些说法；只是提示，不禁止，换不换由你。'}
        if event.get('episode_kind')=='settlement':
            from .rhythm import promotion_candidates
            open_events=[{'event_id':e['_id'],'kind':e.get('kind'),'why':e.get('why'),'ts':e.get('ts')}
                         for e in ledger.events() if e.get('open')
                         and not self.store.db.affect_amendments.find_one({'target':e['_id'],'op':{'$in':['close','void']}})] if ledger.enabled else []
            context['settlement_from_program']={'open_affect_events':open_events,
                'promotion_candidates':promotion_candidates(self.store,model,policy),
                'promotion_quota':effective(model,'memory.promotion.daily_quota',policy) or 0,
                'note':'夜间沉淀：挂着的事可以 close / void（写理由）或保留；值得长期记住的可以 promote（fact/appraisal/signal + source_ids），配额与来源要求由程序检查。'}
        # Which writes and reads this turn allows (owner_private or public) is a program fact, stated plainly.
        context['session_class']=session_class
        context=order_context(context,effective(model,'recall_protocol.order',policy))
        manifest['context_sha256']=sha(canonical(context))
        manifest['system_ref']=system_ref
        return system,context,manifest
