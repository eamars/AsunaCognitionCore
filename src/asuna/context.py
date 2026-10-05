from __future__ import annotations
import json
import traceback
from .config import excerpt, redact_text
from . import visibility
from .render import render_system, readable_sections, model_and_policy
from .documents import DocumentStore, render_markdown
from .persona_model import effective
from .evidence import canonical, sha
from .state import Store, Denied
from .people import People
from .familiarity import NO_UNDERSTANDING, words as familiarity_words
from . import attend

try:                                  # 宿主按包加载
    from . import schedule_rules
except Exception:                     # 同目录平铺加载（离线自检）也认
    import schedule_rules

try:                                  # 跨场景只读联动（A2）：联动范围现算自配置
    from . import scene_links
except Exception:
    scene_links = None                # 拿不到就整体不联动，与改动前逐字一致

try:                                  # 出站图片附件：本轮可引用清单 + 历史里的附件位
    from . import outbound_media
except Exception:                     # 拿不到就整体不带附件位，行形状与改动前逐字一致
    outbound_media = None

# 主动机会给角色看的说明：只说清这是什么、她能选什么，不暗示她该说。
PROACTIVE_NOTE = ('这是一段没有@你的群讨论。程序按这个场景的闸门（安静时段、群里现在的语速、'
                  '同一话题没被接话之前只试一次、不催问）判断现在可以问你一句；值不值得说、'
                  '说多少、还是继续旁听，都由你定。沉默不需要理由，也不因为"有机会"就该开口。'
                  'related_messages 里带 topic_id 的是这条话题线到目前为止的原话（含没@你的旁听行），'
                  '谁说的以行上的 speaker 为准。')


# Per-turn budget (ADR-009 revision): long text is cut with a marker; the full record stays readable.
HISTORY_ROW_CHARS = 1500
MEMORY_CHARS = 1200
EXPERIENCE_MESSAGE_CHARS = 160      # recent experience is headlines; recall reads the rest
EXPERIENCE_TASK_CHARS = 200
EXPERIENCE_MESSAGES = 20
EXPERIENCE_TASKS = 8
EXPERIENCE_PUBLICATIONS = 5
FINISHED_TASKS_SHOWN = 3              # task state: every open task, and only the last few finished
RECENT_THOUGHTS = 3          # ADR-011 §3.2: her last few thoughts in this scene carry into the next turn

# ADR-009 §8.2: context blocks in the persona's recall order; keys never sorted.
BLOCKS = {
    'self_state': ('self_state_from_program', 'recent_thoughts_from_program'),
    'affect': ('affect_from_program',),
    'affect_proposals': ('affect_proposals_from_program',),
    'relationship': ('relationship', 'relationship_shared_from_program'),
    'ledgers': ('ledgers_from_program',),
    'rhythm': ('rhythm_from_program',),
    'memories': ('memories', 'memory_source_rules', 'coverage_from_program'),
    'history': ('delivered_history', 'undelivered_outbound_not_public', 'linked_scenes_from_program'),
    'tasks_plans': ('task_state_from_program', 'plans_from_program', 'schedule_control_from_program',
                    'scheduled_plan_from_program'),
    'recent_phrasing': ('recent_phrasing_from_program', 'speak_from_program'),
    'media': ('media_from_program', 'image_artifacts_from_program'),
    'group_continuity': ('group_continuity_from_program',),
    'sender_identity': ('sender_identity',),
}
CONTEXT_HEAD = ('scene', 'speaker', 'session_class')
CONTEXT_TAIL = ('understanding_update_from_program', 'action_capabilities_from_program', 'proactive_from_program',
                'recent_experience_from_program')


def catch_up(store, scene, rows, now_ts=None):
    """A group's history for her turn (newest first): the last 12 lines, plus every line since she last spoke
    there, reaching back at least 10 and at most 60 minutes (attend.py's window), at most 40 lines."""
    from datetime import datetime, timezone
    from .config import character_id
    now_ts = now_ts or datetime.now(timezone.utc).timestamp()
    mine = next(iter(store.db.messages.find({'scene_id': scene['_id'], 'direction': 'outbound', 'author': character_id(store.config),
                                             'delivery_state': 'DELIVERED'}, {'scene_seq': 1}).sort('scene_seq', -1).limit(1)), None)
    since = (mine or {}).get('scene_seq') or 0
    floor, always = now_ts - attend.WINDOW_MAX_MINUTES * 60, now_ts - attend.WINDOW_MIN_MINUTES * 60
    kept = []
    for index, row in enumerate(rows):
        at = attend._seconds(row.get('received_at') or row.get('receipt_at'))
        recent = at is not None and at >= floor and (row.get('scene_seq', 0) > since or at >= always)
        if index >= 12 and not recent:
            break
        kept.append(row)
    return kept


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

    def recent_thoughts(self, scope, moment):
        from datetime import datetime
        from .config import ago
        rows=list(self.store.db.memory_units.find({'kind':'monologue','scope_key':scope,'status':'active'},
            {'body_markdown':1,'formed_at':1}).sort('formed_at',-1).limit(RECENT_THOUGHTS))
        out=[]
        for row in reversed(rows):
            try:
                hours=(moment-datetime.fromisoformat(row['formed_at'])).total_seconds()/3600
            except (KeyError,TypeError,ValueError):
                hours=None
            out.append({'thought':excerpt(row.get('body_markdown'),MEMORY_CHARS),**({'when':ago(hours)} if hours is not None else {})})
        return out

    def prepare(self, event: dict, persona='P1', recall=False):
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
            'platform_reply_to':1,'event.group_context':1,'scene_seq':1,'episode_id':1,'received_at':1,'receipt_at':1,
            'attachment':1,'attachment_skipped':1}   # 附件位：只多带这两个小字段，字节仍在 BlobStore
        if read['linked_scenes']:
            # 只在真联动时多带这几个字段：归并要有可比的时间，行上也要能看出是哪个入口说的。
            history_projection=dict(history_projection,scene_id=1,occurred_at=1,receipt_at=1,
                                    receipt=1,received_at=1)
        history=list(self.store.db.messages.find(history_query,history_projection).sort('scene_seq',-1)
                     .limit(attend.MAX_LINES if scene['kind']=='group' else 12))
        if scene['kind']=='group':
            history=catch_up(self.store,scene,history)
        if read['linked_scenes']:
            history=self._merge_linked_history(history,scene,read,history_projection)
        else:
            for row in history:                  # read only to size the catch-up window; not shown as raw times
                row.pop('received_at',None); row.pop('receipt_at',None)
        self._reply_context(history, scene)
        undelivered=list(self.store.db.messages.find({'scene_id':scene['_id'],'direction':'outbound','delivery_state':{'$in':['READY','QUEUED_EXTERNAL','SENDING','FAILED','UNKNOWN']}},{'text':1,'delivery_state':1,'author':1}).sort('scene_seq',-1).limit(4))
        tail_sources={x for m in history for x in (m['_id'],m.get('platform_event_id')) if x}
        if source:
            for queued in self.store.db.messages.find({'scene_id':scene['_id'], 'direction':'inbound',
                                                       'scene_seq':{'$gte':source['scene_seq']}},
                                                      {'platform_event_id':1}):
                tail_sources.update((queued['_id'], queued.get('platform_event_id')))
        for row in history:
            # A native role session leaves out rows (and its own replies) it still shows; it needs the ids.
            row.pop('scene_seq',None)
            row['text']=excerpt(row.get('text'),HISTORY_ROW_CHARS)
            if row.get('direction')!='outbound':
                row.pop('episode_id',None)
            if outbound_media is not None:
                # 已送达的图在她历史里显示成「我发过这张图」；没跟着出去的、回执对不上的都另说，不含混。
                slot=outbound_media.history_slot(row,self.store)
                if slot:row['attachment']=slot
                else:row.pop('attachment',None)
        if self.retrieval:
            try:
                from .persona_model import effective as _effective
                from .render import model_and_policy as _model_and_policy
                _m,_p=_model_and_policy(self.store,persona)
                memories, retrieval_manifest=self.retrieval.search(scope,scene['policy_epoch'],event['text'],exclude_sources=tail_sources,
                                                                   coverage_floor=_effective(_m,'memory.coverage_floor',_p) or 0,
                                                                   forgetting={k:_effective(_m,'memory.forgetting.'+k,_p) for k in ('half_life_days','half_life_messages','step_back_below')},
                                                                   record_use=True,automatic=not recall,
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
            # The whole unit stays readable through recall/read; the turn carries a bounded excerpt.
            fact['body_markdown']=excerpt(fact.get('body_markdown'),MEMORY_CHARS)
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
            {'$sort':{'_active':-1,'_input_time':-1,'_id':1}}, {'$limit':16},
            {'$project':{'_id':1,'state':1,'goal':1,'title':1,'feedback_state':1,'finished_at':1,
                'cancel_reason':1,'pause_reason':1,'paused_at':1,'_active':1}},
        ]))
        # Every open task, and only the last few finished ones (their results came back as their own turns).
        open_tasks=[task for task in task_states if task['_active'] or task['state']=='PAUSED']
        task_states=open_tasks+[task for task in task_states if task not in open_tasks][:FINISHED_TASKS_SHOWN]
        for task in task_states:
            task.pop('_active',None)
            # A task's title is what she called it; the old goal text only when there is no title.
            if task.get('title'):
                task.pop('goal',None)
            elif task.get('goal'):
                task['goal']=excerpt(task['goal'],EXPERIENCE_TASK_CHARS)
            if task['state'] not in ('READY','RUNNING'):
                continue
            # What the action brain reported on its own while working (report_progress), newest last.
            notes=list(self.store.db.task_messages.find({'task_id':task['_id'],'from':'action'},
                {'text':1}).sort('created_at',-1).limit(2))
            if notes:
                task['progress_from_action']=[excerpt(row['text'],HISTORY_ROW_CHARS) for row in reversed(notes)]
        plan_rows=list(self.store.db.plans.find({'scene_id':scene['_id'],'scope_key':scope,
            'person_id':event['person_id'],'policy_epoch':scene['policy_epoch'],
            # Her rhythms belong to the program (ADR-012 §4.3); she tunes them with set_policy, never cancels them.
            'kind':{'$nin':['self_development','presence','settlement']},
            'status':{'$in':['CREATING','ACTIVE','SUSPENDED']}},
            {'_id':1,'intent':1,'rule':1,'scheduled_at':1,'status':1,'plan_version':1,
             'timezone':1,'tz_source':1,'next_fire_at':1,'created_at':1,'updated_at':1,
             'last_outcome':1}).sort('created_at',-1).limit(8))
        # P3：计划行按这个场景的时区翻成人话再给她看——不让她自己拿 UTC 心算「明天九点」。
        # 已暂停（SUSPENDED）也列出来：不列就等于她不知道自己有一条挂着的安排没生效。
        schedule_zone=schedule_rules.scene_timezone(self.store.config,scene)
        plans=[schedule_rules.project(row,schedule_rules.scene_timezone(self.store.config,scene,row),
                                      moment) for row in plan_rows]
        # Recall is said in words only when it falls short (AGENTS.md: interpreted state); the score stays in the manifest.
        coverage_block=None
        if retrieval_manifest.get('coverage')=='insufficient':
            coverage_block=('关于眼前这件事，你想不起相关的记忆；不要编，记不清就直说。' if not memories
                            else '想起来的这些和眼前的事关系不大：只能当灵感，不能当事实说。')
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 # How well she knows them (familiarity.py) and what she has written about them, in words.
                 'relationship':{**familiarity_words(self.store,event['person_id'],persona),
                                 'understanding':((relation[1]['content'] or {}).get('body') if relation else None)
                                                 or NO_UNDERSTANDING},
                 'self_state_from_program':self_state,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'memory_source_rules':'reported_speech 是来源人物说过的话，并非已核实的外部事实；同一人物的原话按 scene_seq 从旧到新排列。对于他自己的物品、偏好和更正，以他较新的明确陈述为准。public_statement 只证明角色说过这句话，承诺不等于完成；character_interpretation 只是角色当时的理解或猜测。角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。derived_summary 是程序后台从一段原文整理出来的有界摘要：source_window 是它覆盖的 scene_seq 区间，source_event_ids 可回读原文；它只证明那段交流里说过什么，不是新的经历，也不等于任何人确认过的事实，与同一人物较新的明确陈述冲突时以陈述为准，需要细节就回读来源。摘要的 who 是这段里说话的人，about_current_speaker 说明它算不算当前说话人的证据：只有别人的话的那段是背景，不能当成当前说话人说过什么；corrections 与 corrected_by 是程序按真实 reply 链算出的更正，非空就说明这段转述之后有人更正过，以更正后的原话为准。人按标签区分（如 [名字 #4]）：名字会重复、会改，标签不会。',
                 'task_state_from_program':task_states,
                 'plans_from_program':plans,
                 'schedule_control_from_program':schedule_rules.control_note(schedule_zone,moment),
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        if coverage_block:
            context['coverage_from_program']=coverage_block
        thoughts=self.recent_thoughts(scope,moment)
        if thoughts:
            context['recent_thoughts_from_program']={'items':thoughts,
                'note':'这是你此前在这里的心里话（最近的在最后），是当时的看法，不是说出口的话。'}
        if any(task['state'] == 'PAUSED' for task in task_states):
            context['task_continuation_from_program'] = (
                'PAUSED 是重启后等待操作者决定的旧行动，历史与回执仍保留。'
                '只有本地用户明确要求继续时才可以用 message_action 接着做；'
                '普通聊天、内部机会及旧任务反馈不构成继续旧工作的授权。'
                '继续时先核实已有结果，未确认回执的操作不能盲目重做。')
        if read['linked_scenes']:
            context['linked_scenes_from_program']={
                'readable':read['linked_scenes'],'canonical_person':target['canonical'],
                'note':'delivered_history 与 memories 里带 scene 的行来自这些联动场景'
                       '（配置认定是同一个人的另一个入口，只读）：它们不是这个场景里的新输入，不用当成'
                       '刚说的话再回应一次；要引用就说清那是在哪个入口说的。'}
        if target['shared']:
            context['relationship_shared_from_program']={
                'scope':target['scope'],
                'note':'这个人在配置里与另一个入口是同一个人，关系与偏好只维护那一份；这一轮的理解更新'
                       '会写进 scope 那个场景的那一份，来源仍只取本轮场景里真实给过你的证据。'}
        if event.get('episode_kind') == 'self_development':
            # ADR-011 §6.2: ideas from anywhere are read and decided only here.
            from .role_tools import ideas_block
            ideas=ideas_block(self.store,persona,moment)
            if ideas:
                context['ideas_from_program']={'items':ideas,
                    'note':'这是你的「改进想法」本里还没处理完的想法（来自你自己或行动脑做事时）。逐条用 review_idea 写下处理结果'
                           '（采纳、暂缓或放弃，附理由）；采纳的用 delegate 交代行动脑去做，它会带开发工具，'
                           '改动只经 development_publish 生效。灵感可以来自别人，写进代码、技能和文档的东西不能带别人的个人信息。'}
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
                 'delivery_state':1}).sort('received_at',-1).limit(EXPERIENCE_MESSAGES))
            for row in recent:
                row['text']=excerpt(row.get('text'),EXPERIENCE_MESSAGE_CHARS)
            # Headlines (owner, 2026-10-05): titles, states and the start of each report; recall reads more.
            tasks = list(self.store.db.tasks.find({'scene_id': {'$in': list(allowed)}},
                {'scene_id':1,'state':1,'title':1,'goal':1,'failure_type':1,'result':1,
                 'feedback_state':1,'finished_at':1}).sort('finished_at',-1).limit(EXPERIENCE_TASKS))
            for item in tasks:
                if item.get('title'):
                    item.pop('goal',None)
                elif item.get('goal'):
                    item['goal']=excerpt(item['goal'],EXPERIENCE_TASK_CHARS)
                result=item.pop('result',None)
                if isinstance(result,dict) and result.get('text'):
                    item['report_start']=excerpt(result['text'],EXPERIENCE_TASK_CHARS)
            lineage=list(self.store.db.sink_receipts.find({'kind':'self_development_publish'},
                {'project':1,'state':1,'changed_files':1,'deleted_files':1,'published_at':1,
                 'activated_at':1,'task_id':1}).sort('published_at',-1).limit(EXPERIENCE_PUBLICATIONS))
            for row in lineage:
                # How much each publication changed, not every path (the receipt keeps the list).
                row['changed_files']=len(row.get('changed_files') or [])
                row['deleted_files']=len(row.get('deleted_files') or [])
            context['recent_experience_from_program'] = {
                'messages': list(reversed(recent)), 'tasks': tasks, 'publish_lineage':lineage,
                'note': '真实历史片段与行动结果；每条保留来源场景。未列出的历史仍可按原有授权查询。'}
        if event.get('episode_kind') == 'presence':
            # ADR-012 §4.4: her groups in words, and what her recent visits came to.
            from . import places
            from .render import model_and_policy as _places_model
            plan=self.store.db.plans.find_one({'_id':'plan-asuna-presence'}) or {}
            _pm,_pp=_places_model(self.store,persona)
            date=places.local_date(self.store.config,_pm,_pp,moment)
            places_view=places.places_block(self.store,persona,_pm,_pp,plan,moment,date)
            if places_view:
                context['places_from_program']=places_view
            visits=places.last_visits_block(self.store,persona,plan,moment)
            if visits:
                context['last_visits_from_program']=visits
        people=People(self.store,persona)
        if source and (source.get('event') or {}).get('channel'):
            # Who is speaking, by account (people.py): label, notes, names in quotes; never a QQ number.
            line=people.identity_line(scene,source)
            if line:context['sender_identity']=line
        if source:
            # 这条消息里出现过什么非文本段：只给有界事实与「能不能按需拉」，不替她决定要不要看图。
            from .vision import media_note
            media=media_note(source,self.store.config)
            if media:context['media_from_program']=media
        if outbound_media is not None:
            # 本轮可随这条消息发出去的图片：程序给出的 artifact，不是文件路径；方向不对或没图就不出现。
            offer=outbound_media.offer(self.store,self.store.config,scene,session_class,event['person_id'])
            if offer:context['image_artifacts_from_program']=offer
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
                {'text':1,'author':1,'scene_seq':1,'event.group_context':1}).sort('scene_seq',-1).limit(3)) \
                if source and event.get('episode_kind')!='visit' else []
            self._reply_context(speaker_tail, scene)
            for row in [*related, *speaker_tail]:
                row['text']=excerpt(row.get('text'),HISTORY_ROW_CHARS)
            continuity = {**group, 'related_messages': related,
                          'current_speaker_tail': list(reversed(speaker_tail))}
            if str(group.get('wake_reason') or '').startswith('proactive'):
                continuity['proactive_from_program'] = PROACTIVE_NOTE
            context['group_continuity_from_program'] = continuity
        model,policy=model_and_policy(self.store,persona)
        documents={'persona':system_ref['persona_doc_revision'],'voice':system_ref['voice_doc_revision']}
        ledgers=ledger_block(docs,session_class)
        if ledgers:
            context['ledgers_from_program']=ledgers
            documents.update({item['doc']:item['revision'] for item in ledgers})
        from . import group_admin
        place=group_admin.place(people,scene)
        if place:
            # Her own role in this group, what she may do there as an admin, and her notes about it (group_admin.py).
            context['your_place_from_program']=place
            notes_revision,context['group_notes_from_program']=group_admin.notes_block(docs,scene)
            if notes_revision:
                documents[group_admin.notes_slug(scene['_id'])]=notes_revision
        from .ingress import episode_id as _episode_id
        context['ref_index']=list(dict.fromkeys([event['event_id'],'in-'+_episode_id(event),*[m['_id'] for m in memories],
            *[t['_id'] for t in task_states],
            *['doc:%s#%s'%(item['doc'],section['sid']) for item in ledgers for section in item['sections']],
            *['doc:persona#'+section['sid'] for section in readable_sections(persona_doc,session_class)]]))
        manifest={'session_class':session_class,'documents':documents,'persona_revision':system_ref['persona_doc_revision'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'relationship_entity_key':relation[0]['_id'] if relation else target['entity']+'|'+target['scope'],'linked_scenes':read['linked_scenes'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        # Available with or without a record: her first understanding of someone creates it.
        context['understanding_update_from_program']={
            'available':True,'target':target_note,
            'route':'有值得留下的理解变化时，用 understand_person 写下完整的新理解；无需每轮更新。本轮上下文里的 derived_summary 也会被程序一并登记成这次理解的来源（按本轮实际展示与当前场景/纪元复核，不用你填 ID）；同一批原文已经进过这条关系时，程序记为未提交并给出原因，那不算你改过自己。群场景里只有 about_current_speaker 说有当前说话人自己的话的摘要，才会被登记成这条关系的来源，盖不到人的摘要会带着原因记为未登记（照样给你看，只是不算这个人的证据）。'}
        from .grants import workspace_grant
        grant = workspace_grant(self.store.config, scene['_id'], event['person_id'], required=False)
        context['action_capabilities_from_program']={
            'available':bool(grant),'route':'用 delegate 把事交给行动脑；补话或接着做用 message_action，叫停用 stop_action。文件、网页、沙箱、原话检索和看图都是行动脑的事。',
            'cancellation_available':True,
            'network':'行动脑可以按需搜索公共网页并读取页面。',
            'delivery':'程序自动执行委托，结果作为独立事件返回当前场景；等待时仍可聊天。'}
        from .grants import development_granted
        if development_granted(self.store, scene, event, session_class):
            context['action_capabilities_from_program']['development'] = {
                'candidate':'持久的有效项目候选（代码、技能、提示、种子）；可委托行动脑检查、修改和自行发布。',
                'guide':'先读核心技能 asuna-self-improvement：改什么走哪层、怎么自检、怎么发布、什么会触发重启。'}
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
                'grant': '本机 owner 工作域允许适配器试运行和启停。试运行用开发候选的冻结副本，启用只用已发布的版本；改适配器代码要有开发授权。仅配置端点可达；进程启动不证明平台发送。'}
        if event.get('episode_kind')=='visit':
            # ADR-012 §4.2: nobody called her; the room as it is now, and what she came for. The person on the
            # event only authorizes the turn, so no block speaks of a current speaker.
            from . import places
            context['visit_from_program']=places.visit_block(self.store,scene,event.get('visit') or {},moment)
            for key in ('relationship','sender_identity','understanding_update_from_program'):
                context.pop(key,None)
        manifest['context_sha256']=sha(canonical(context))
        from .affect import AffectLedger
        ledger=AffectLedger(self.store,persona,model,policy)
        if ledger.enabled:
            # One heart per persona: the state is global; reasons, who and numbers stay owner-private (§6.5).
            m=ledger.model
            # Words only (AGENTS.md: interpreted state): her mood, its hints and reasons, and how to record one.
            from .affect import interpret, recording_guide
            context['affect_from_program']={**interpret(m,ledger.projection(),session_class),'how_to_record':recording_guide(m)}
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
        if scene.get('channel_id'):
            # How her words leave on a platform, and which lines are hers to answer now (coordinator._absorb).
            speak={'sent':'你这回合写出来的每段话都会发出去，写在工具调用旁边的也算；不想说出口的放进 think。',
                   'new_lines':'这段对话里新来的话——包括你这回合中途才到的——你看见了就算你接住了：'
                               '要回就在这回合一起回，它们不会再单独叫你一次。'}
            messages=int(effective(model,'speak.max_messages',policy) or 1)
            if messages>1:
                # Her words may leave as a few messages, broken where she marks them (ADR-009 §11.1).
                from .rhythm import SPLIT_MARKER
                marker=effective(model,'speak.split_marker',policy) or SPLIT_MARKER
                speak['messages']=(f'默认是一条消息。想像聊天那样分几条发，就在要断开的地方写 {marker}，最多 {messages} 条，'
                    f'多出来的并进最后一条；分开写的几段话也各是一条。代码块里的 {marker} 不算，代码块总是整块发出。不用为了分条而分条。')
            context['speak_from_program']=speak
        if event.get('episode_kind')=='settlement':
            from .rhythm import promotion_candidates
            from .affect import kind_label
            open_events=[{'event_id':e['_id'],'feeling':kind_label(ledger.model,e.get('kind')),'why':e.get('why'),'ts':e.get('ts')}
                         for e in ledger.events() if e.get('open')
                         and not self.store.db.affect_amendments.find_one({'target':e['_id'],'op':{'$in':['close','void']}})] if ledger.enabled else []
            context['settlement_from_program']={'open_affect_events':open_events,
                'promotion_candidates':promotion_candidates(self.store,model,policy),
                'promotion_quota':effective(model,'memory.promotion.daily_quota',policy) or 0,
                'note':'夜间沉淀：挂着的事可以 close / void（写理由）或保留；值得长期记住的可以 promote（fact/appraisal/signal + source_ids），配额与来源要求由程序检查。'}
        # Which writes and reads this turn allows (owner_private or public) is a program fact, stated plainly.
        context['session_class']=session_class
        people.relabel(context,scene,event['person_id'])
        context=order_context(context,effective(model,'recall_protocol.order',policy))
        manifest['context_sha256']=sha(canonical(context))
        manifest['system_ref']=system_ref
        return system,context,manifest
