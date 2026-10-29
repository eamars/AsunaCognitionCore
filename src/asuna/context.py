"""Builds what her turn shows her: `ContextBuilder.prepare` reads one event's scene, persona, relationship,
memories, history, tasks and other state, and returns the system text, the context blocks and a manifest of them.

The coordinator calls it for every turn. `order_context` puts the blocks in the persona's recall order (`BLOCKS`),
and long text is cut to the per-turn budget with a marker.
"""
from __future__ import annotations
import json
import traceback
from . import clock
from .config import character_id, excerpt, redact_text
from . import errands as _errands, visibility
from . import handover as _handover
from .render import render_system, readable_sections, model_and_policy
from .documents import DocumentStore, render_markdown
from .persona_model import effective
from .evidence import canonical, sha
from .state import Store, Denied
from .people import People
from .familiarity import words as familiarity_words
from . import attend, caught_up, notices, own_mute
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import receipts as receipt_records
from .records import plans as plan_records
from .records import tasks as task_records
from .records import memories as memory_records
from .records import heads as head_records

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
CHAIN_NOTE = ('群里在跟队形：好几个人接连发了同一样东西，没人叫你。要跟就发同样的东西：一句话就照抄；'
              '是表情包就先用 sticker 的 keep 收下那条的表情包 ref，再用 speak 发一个 kind=sticker 的 part（name 写你给它起的名字）。'
              '这一串程序只叫你这一次；跟不跟、怎么跟由你定，不跟就不发。')
PROACTIVE_NOTE = ('这是一段没有@你的群讨论。程序按这个场景的闸门（安静时段、群里现在的语速、'
                  '同一话题没被接话之前只试一次、不催问）判断现在可以问你一句；值不值得说、'
                  '说多少、还是继续旁听，都由你定。沉默不需要理由，也不因为"有机会"就该开口。'
                  'related_messages 里带 topic_id 的是这条话题线到目前为止的原话（含没@你的旁听行），'
                  '谁说的以行上的 speaker 为准。')

# ADR-018 §5.7 (owner 2026-10-07): one sentence in public turns. No content from her other conversations.
# ADR-064 phase 2: where she speaks only through reply.
REPLY_SENT=('一回合 speak 的 text 加起来平时 %d 行以内，硬线 %d 行：每一行都算，不管分成几条消息；'
            '空行不算，一个代码块算一行；表情包、图、戳、点表情不算。')
ONE_SELF = '你是一个人，同时在好几个对话里；在这里说的话，就是你说的。'
# ADR-079 §9.5: the one line of a turn where others spoke after the line that called her.
AMBIGUOUS = '叫你那条之后有 %d 条新话：%s。要引哪条就在 quote 写它的编号（只写数字），不写就不引用；一句话回好几条就不用引。'
AMBIGUOUS_MAX = 8


# Per-turn budget (ADR-009 revision): long text is cut with a marker; the full record stays readable.
HISTORY_ROW_CHARS = 1500
MEMORY_CHARS = 1200
EXPERIENCE_MESSAGE_CHARS = 160      # recent experience is headlines; recall reads the rest
EXPERIENCE_TASK_CHARS = 200
EXPERIENCE_MESSAGES = 20
EXPERIENCE_TASKS = 8
EXPERIENCE_PUBLICATIONS = 5
# What of a line her group continuity shows (the line it answers, its topic thread).
RELATED_FIELDS = ['text', 'author', 'direction', 'scene_seq', 'delivery_state', 'platform_reply_to', 'event.group_context',
                  'episode_id', 'occurred_at', 'receipt_at', 'received_at']
FINISHED_TASKS_SHOWN = 3              # task state: every open task, and only the last few finished
RECENT_THOUGHTS = 3          # ADR-011 §3.2: her last few thoughts in this scene carry into the next turn

# ADR-009 §8.2: context blocks in the persona's recall order; keys never sorted.
BLOCKS = {
    'self_state': ('self_state_from_program', 'things_from_program', 'recent_thoughts_from_program',
                   'night_from_program'),
    'affect': ('affect_from_program', 'how_to_record_from_program'),
    'affect_proposals': ('affect_proposals_from_program',),
    'relationship': ('relationship', 'relationship_shared_from_program', 'people_from_program'),
    'ledgers': ('ledgers_from_program',),
    'rhythm': ('rhythm_from_program',),
    'memories': ('memories', 'memory_source_rules', 'coverage_from_program'),
    'history': ('delivered_history', 'undelivered_outbound_not_public', 'linked_scenes_from_program'),
    'tasks_plans': ('task_state_from_program', 'plans_from_program', 'clock_from_program',
                    'scheduled_plan_from_program', 'watching_from_program',
                    'credentials_from_program'),
    'recent_phrasing': ('recent_phrasing_from_program', 'speak_from_program'),
    'media': ('media_from_program', 'image_artifacts_from_program', 'file_artifacts_from_program',
              'your_pictures_from_program', 'sticker_candidates_from_program',
              'stickers_from_program', 'faces_from_program'),
    'group_continuity': ('group_continuity_from_program', 'watched_from_program', 'waiting_from_program',
                         'peer_asides_from_program'),
    'notes': ('note_from_program', 'notes_from_program', 'notes_sent_from_program', 'note_places_from_program'),
    'sender_identity': ('sender_identity',),
}
CONTEXT_HEAD = ('scene', 'speaker', 'session_class')
SEGMENT_WORDS = {'face': '小黄脸', 'reply': '引用', 'at': '@', 'image': '图', 'record': '语音', 'mface': '表情包'}


def landing_lost(verification):
    """The parts of her delivered line the platform did not store, in words; None when it stored what was sent."""
    if not isinstance(verification, dict) or verification.get('result') != 'segment_mismatch':
        return None
    stored = list(verification.get('stored_segments') or [])
    lost = []
    for kind in verification.get('sent_segments') or []:
        if kind in stored:
            stored.remove(kind)
        elif kind != 'text':
            lost.append(SEGMENT_WORDS.get(kind, kind))
    return ('平台收下了这句，但%s没落成：对方看到的没有它' % '、'.join(dict.fromkeys(lost))) if lost else None


# A queued line has not left: recall takes it out (SPEAK_RECALL), so it reads as not sent, not as one on its way.
UNDELIVERED_WORDS = {'READY': '还没发', 'QUEUED_EXTERNAL': '排着队，还没发出去', 'SENDING': '在发', 'FAILED': '没发出去',
                     'UNKNOWN': '平台没给准话：多半已经发出去了，先看看那边有没有再决定，别直接重发'}
# What these blocks are for, said once in her system prompt (block_guide.py, ADR-056).
IDEAS_NOTE = ('这是你的「改进想法」本里还没处理完的想法（来自你自己或行动脑做事时）。逐条用 ideas 的 review 写下处理结果'
              '（采纳、暂缓或放弃，附理由）；采纳的用 delegate 交代行动脑去做，它会带开发工具，'
              '改动只经 development_publish 生效。灵感可以来自别人，写进代码、技能和文档的东西不能带别人的个人信息。')
EXPERIENCE_NOTE = ('真实历史片段与行动结果；每条保留来源场景。别人的原话只列你私人的对话；群和别人的私聊里只列你自己'
                   '说过的话，那边的情况心跳时看 places_from_program。想把那边的东西带回来，用想法本或夜间沉淀，写成你自己的话。')
DOC_REFS_NOTE = ('你能引用的文档小节：写文档、记想法或记感受要指向某一节时，照抄这里的 doc:… 引用。')
THOUGHTS_NOTE = '这是你此前在这里的心里话（最近的在最后），是当时的看法，不是说出口的话。'
# Said once in her system prompt (block_guide), not in every turn (measured 2026-10-16: in 92% of turns).
PEOPLE_NOTE = ('叫你的人：开启这一回合的人，和排在后面 @ 你、回你的人；熟悉程度、那一档的态度，和你写过的一句话（short 是人那层的，'
               'here 是这里那层的；那层还没写 short 时给的是全文 short_body、here_body）。本会话里给过、还在眼前的不再给；同一个人两份都在眼前时，以后给的为准。short 是给你自己的提示，'
               '不是要说出口的话。完整的理解用 recall 的 person 读；没写过的人只有熟悉程度。')
UNDERSTANDING_NOTE = ('有值得留下的理解变化时，用 understand_person 写下那一层完整的新理解（两层各自一回合最多写一次）；无需每轮更新。'
                      '本轮上下文里的 derived_summary 也会被程序一并登记成这次理解的来源（按本轮实际展示与当前场景/纪元复核，不用你填 ID）；'
                      '同一批原文已经进过这条关系时，程序记为未提交并给出原因，那不算你改过自己。群场景里只有 about_current_speaker '
                      '说有当前说话人自己的话的摘要，才会被登记成这条关系的来源，盖不到人的摘要会带着原因记为未登记（照样给你看，只是不算这个人的证据）。')
MEMORY_SOURCE_RULES = ('reported_speech 是那个人说过的话，不是核实过的事实；同一人的原话按 scene_seq 从旧到新排，'
                       '他自己的东西、喜好和更正以他较新的明确说法为准。public_statement 只证明说过，答应不等于做到；'
                       'character_interpretation 是你当时的理解或猜测。旧说法再出现不推翻已有的更正；旧记录是历史，再想起它不是新经历。'
                       'derived_summary 是程序从一段原文整理的摘要：source_window 是它覆盖的 scene_seq 范围，'
                       'source_event_ids 能回读原文；它只证明那段里说过什么，和同一人较新的明确说法冲突时以说法为准，'
                       '要细节就回读。摘要的 who 是那段里说话的人，about_current_speaker 说明它算不算眼前这个人的话；'
                       'corrections 和 corrected_by 是程序按真实回复算出的更正，有就以更正后的为准。人按标签分，名字会重复、会改，标签不会。')

def refs(context):
    """Every id she may cite in this turn: the turn's own event, ref_index, the document sections, and the memories and
    tasks shown in their own blocks."""
    event_id=context['event'].get('event_id') if isinstance(context.get('event'),dict) else None
    return list(dict.fromkeys([*([event_id] if event_id else []),*(context.get('ref_index') or []),
                               *(context.get('doc_refs_from_program') or []),
                               *[m.get('_id') for m in context.get('memories') or [] if isinstance(m, dict) and m.get('_id')],
                               *[t.get('_id') for t in context.get('task_state_from_program') or []
                                 if isinstance(t, dict) and t.get('_id')]]))


CONTEXT_TAIL = ('understanding_update_from_program', 'action_capabilities_from_program', 'proactive_from_program',
                'recent_experience_from_program')
# Read right before the turn's trigger: where her words cannot go out (own_mute.py).
BESIDE_EVENT = ('muted_here_from_program',)


def catch_up(store, scene, rows, now_ts=None):
    """A group's history for her turn (newest first): the last 12 lines, plus every line since she last spoke
    there, reaching back at least 10 and at most 60 minutes (attend.py's window), at most 40 lines. A group she
    lets rest gives its lines of the last day instead."""
    from .config import character_id
    from . import focus
    now_ts = now_ts or clock.now().timestamp()
    if not focus.active(store, scene):
        # ADR-039: she has not been following a resting group; what was said there in the last day (at most the
        # MAX_LINES the query read) tells her what an @ is about.
        day = now_ts - focus.DAY.total_seconds()
        return [row for row in rows if (attend._seconds(caught_up.said_at(row)) or day) >= day]
    mine = message_records.spoken(store, scene['_id'], author=character_id(store.config)).first(
        newest_first=True, fields=['scene_seq'])
    since = (mine or {}).get('scene_seq') or 0
    floor, always = now_ts - attend.WINDOW_MAX_MINUTES * 60, now_ts - attend.WINDOW_MIN_MINUTES * 60
    kept = []
    for index, row in enumerate(rows):
        at = attend._seconds(caught_up.said_at(row))
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
            and k not in BESIDE_EVENT and not k.endswith('_from_host')]
    tail = [*CONTEXT_TAIL, *[k for k in context if k.endswith('_from_host')], 'ref_index', *BESIDE_EVENT, 'event']
    return {k: context[k] for k in [*keys, *rest, *tail] if k in context}


def _section_view(section):
    # The id she copies is shown as `section`, the name write_document and recall take it by (ADR-060).
    return {('section' if k == 'sid' else k): section[k]
            for k in ('sid', 'heading', 'body', 'visibility', 'entry_date', 'tags') if k in section}


def ledger_block(docs, cls):
    """Every ledger she can read here, each within its per-turn limit (context_budget.note_view)."""
    from .carried import placed, sections as carried_sections
    from .context_budget import NOTE_CHARS, note_view
    out = []
    for slug in docs.slugs():
        revision, content = docs.read(slug)
        if not content or content.get('kind') != 'ledger':
            continue
        sections = carried_sections(placed(docs.store, docs.persona, slug, content), cls)
        if sections:
            kept, about = note_view(sections, NOTE_CHARS['ledger'])
            out.append({'doc': slug, 'revision': revision, 'title': content.get('title'),
                        'sections': [_section_view(s) for s in kept], **about})
    return out


INVENTED_MARK = '（自述编写，非共同经历）'




# Where a recalled record comes from, in the words her own items use (memory_tiers.FROM_NATURE).
MEMORY_FROM = {'reported_speech': '别人说的', 'public_statement': '我说出口的', 'derived_summary': '整理出来的摘要',
               'character_interpretation': '我自己的判断'}

def _errand_from_here(store, event):
    """Whether this home turn may send her on an errand (ADR-066; role_tools.ERRAND_FROM): someone speaking, her plan
    due, a note of hers from home, or a note from outside that carries the owner's own line."""
    kind = event.get('episode_kind') or 'external'
    if kind in ('external', 'scheduled'):
        return True
    if kind != 'note':
        return False
    from . import notes
    first = notes.opening_for(store, event) or {}
    return first.get('trust') == notes.TRUSTED or bool(first.get('owner_line'))


class ContextBuilder:
    def __init__(self, store: Store, retrieval=None):
        self.store,self.retrieval=store,retrieval
        self.pilot=None    # ADR-062 phase 1: the shadow pilot the Host attaches (memory_pilot.py); measures, delivers nothing

    def _reply_context(self, rows, scene, *, keep_event=False):
        """Keep transport reply attribution when projecting scoped history."""
        for row in rows:
            event = row.get('event', {}) if keep_event else row.pop('event', {})
            group = event.get('group_context', {})
            if group:
                row['mentioned_account_ids'] = group.get('mentioned_account_ids', [])
            reply = row.pop('platform_reply_to', None) or group.get('reply_to') or (event.get('reply') or {}).get('reply_to')
            if not reply:
                continue
            row['reply_to'] = reply
            from .channels import reply_parent
            from .people import People
            source = scene_records.get(self.store, row.get('scene_id', scene['_id']))
            parent = reply_parent(self.store, source or scene, reply,
                                  row.get('occurred_at') or row.get('receipt_at') or row.get('received_at'))
            # The quoted line in the one form every pointer has (ADR-079 §9.3); unknown to the program, said so.
            row['quotes'] = People(self.store).pointed(source or scene, parent) if parent else '一条更早的消息'
        return rows

    def _merge_linked_history(self, own, scene, read, projection):
        """把联动场景的最近几条按「有效时间」归并进这一轮的上下文窗口。

        排序不能再拿 scene_seq 比：那是每个场景自己的序号，跨场景不可比。时间口径与查询侧一致
        （平台回执 ＞ 本机送达回执 ＞ 入站发生时刻 ＞ 落库时刻），每条行上带 scene_id，
        她能看出这句话是在哪个入口说的。联动场景的行只是给她看的历史，不是这个场景的新输入。
        """
        rows = []
        for scene_id in read['linked_scenes']:
            rows.extend(message_records.said(self.store, scene_id, scene['policy_epoch']).rows(
                newest_first=True, limit=12, fields=list(projection)))
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

    def recent_thoughts(self, scope, zone):
        """Her last thoughts here, each with when she had it on her clock face: a stamp, not "how long ago", which would
        change the block every turn with nothing new in it."""
        from . import reasons
        rows=memory_records.of_kind(self.store,'monologue',scope=scope,status='active',by='formed_at').rows(
            newest_first=True,limit=RECENT_THOUGHTS,fields=['body_markdown','formed_at','episode_id','source'])
        out=[]
        for row in reversed(rows):
            when=schedule_rules.line_stamp(zone,row.get('formed_at'))
            # _id lets the Host leave out a thought her session still shows where she wrote it (context-delivery.js).
            then=reasons.then(self.store,row)
            out.append({'_id':row['_id'],'thought':reasons.shown(row,MEMORY_CHARS),      # ADR-099: a summary short
                        **({'when':when} if when else {}),**({'then':then} if then else {})})
        return out

    def own_thoughts_elsewhere(self, scene, query):
        """At home, what she herself thought in her groups about this (her monologue there, never their talk):
        each with the group's name and the time she thought it."""
        if not self.retrieval:
            return []
        from . import reasons
        groups={s['scope_key']:s for s in scene_records.of_kind(self.store, 'group', fields=['scope_key','policy_epoch','kind','channel_id'])}
        units=self.retrieval.own_thoughts([(key,s.get('policy_epoch',1)) for key,s in groups.items()],query)
        people=People(self.store)
        zone=schedule_rules.scene_timezone(self.store.config,scene)
        moment=clock.now()
        out=[]
        for unit in units:
            item={'_id':unit['_id'],'where':people.scene_title(groups.get(unit['scope_key'])),
                  'thought':reasons.shown(unit,MEMORY_CHARS)}
            when=self.when(unit,zone,moment)
            if when:item['when']=when
            then=reasons.then(self.store,unit)
            if then:item['then']=then
            out.append(item)
        return out

    def said_at(self, unit):
        """When a memory's source was said: a thought when she had it; a chunk its line, a summary its last line."""
        if unit.get('kind')=='monologue':
            return unit.get('formed_at')
        seq=unit.get('scene_seq')
        if seq is None:
            seq=(unit.get('source_window') or [None])[-1]
        scope=unit.get('scope_key') or ''
        if seq is not None and scope.startswith('scene:'):
            row=message_records.at(self.store,scope[len('scene:'):],seq,
                                   fields=['received_at','receipt_at','occurred_at','event.raw','event.occurred_at'])
            said=row and caught_up.said_at(row)
            if said:
                return said
        return unit.get('occurred_at') or unit.get('formed_at') or unit.get('generated_at')

    def when(self, unit, zone, moment):
        """A recalled record's time as her history lines show it: '10/11 19:16'. A stamp, not "how long ago",
        which would change with every turn and read on the speaker's terms (ADR-056 rule 2, her ask 2026-10-14)."""
        return schedule_rules.line_stamp(zone,self.said_at(unit)) or None

    def prepare(self, event: dict, persona='P1', recall=False, turn_kind=None):
        """`turn_kind`: a recall's own turn kind, for the shadow pilot's row only."""
        try:
            return self._prepare(event, persona, recall, turn_kind)
        finally:
            from .people import anchors_shown
            anchors_shown(event['scene_id'])        # her thought under a line of hers: once a turn

    def _prepare(self, event, persona, recall, turn_kind):
        scene=scene_records.authorize(self.store, event['scene_id'], event['person_id'])
        shown_stops=[]                  # the outages this turn shows (host_from_program, home turns only)
        from . import memory_tiers
        if memory_tiers.ENABLED and not recall:
            # ADR-062: rows for new items, then the lapses and cooling due, before anything is read for the turn.
            from .persona_model import effective as _tier_effective
            from .render import model_and_policy as _tier_model
            _tm,_tp=_tier_model(self.store,persona)
            _tiers=memory_tiers.Tiers(self.store,persona)
            _tiers.sync()
            _tiers.tick(half_life_days=float(_tier_effective(_tm,'memory.forgetting.half_life_days',_tp) or 30),
                        step_back_below=float(_tier_effective(_tm,'memory.forgetting.step_back_below',_tp) or 0.1))
        scope=scene['scope_key']
        moment=schedule_rules.now_utc()          # 本轮只用一个时刻：算下一次钟点与给她看的钟面同源
        session_class=visibility.session_class(self.store.config,self.store,scene,event['person_id'])
        place=visibility.place(self.store.config,self.store,scene,event['person_id'])
        from . import channel_kinds as _kinds
        system,system_ref=render_system(self.store,persona,session_class,place,
                                        bool(scene.get('channel_id')) and bool(_kinds.reply_parts(scene['_id'])))
        docs=DocumentStore(self.store,persona)
        persona_doc=docs.read('persona')[1]
        body=render_markdown(readable_sections(persona_doc,visibility.OWNER_PRIVATE))
        content_lines=[line for line in body.splitlines() if line.strip() and not line.startswith('#')]
        if len(''.join(content_lines))<80:
            raise ValueError('REQUIRED_PERSONA_BODY_MISSING')
        read=(scene_links.read_scope(self.store.config,scene) if scene_links else
              {'scene_id':scene['_id'],'scene_ids':[scene['_id']],'linked_scenes':[],
               'scope_keys':[scope],'linked_scope_keys':[]})
        target=(scene_links.relationship_target(self.store.config,self.store,scene,event['person_id'])
                if scene_links else {'entity':'relationship:'+event['person_id'],'scope':scope,
                                     'canonical':event['person_id'],'shared':False,'linked_scopes':[]})
        # 没配 canonical 映射时 target 就是原来那一份（relationship:<本人>｜本场景 scope）。
        relation=head_records.current(self.store,target['entity'],target['scope'])
        # The person layer (understanding.py): one record for this person, read wherever she meets them.
        from . import understanding as _understanding
        person_entity=_understanding.person_entity(self.store.config,self.store,event['person_id'])
        person_head=head_records.current(self.store,person_entity,_understanding.PERSON_SCOPE)
        from .self_state import SelfState
        self_state=SelfState(self.store).read(persona,scope)
        # ADR-096: what this turn carries of her identity, for its (place, class) pair: one function for every reader.
        from . import carried as _carried
        identity=_carried.contents(self.store,persona)
        carried_here=_carried.carried(self.store,persona,session_class,place,docs=identity)
        carried_here.update({slug:[s for sid in system_ref['carried'][slug]
                                   for s in (identity.get(slug) or {}).get('sections') or [] if s['sid']==sid]
                             for slug in system_ref['carried']})     # persona and voice exactly as the system rendered
        if memory_tiers.ENABLED:
            # ADR-062: once she has written herself as items, the carried ones are what she reads of herself.
            for name,slug in _carried.SELF_BLOCKS:
                if (identity.get(slug) or {}).get('sections'):
                    self_state[name]=_carried.self_block(slug,carried_here[slug])
        from .ingress import episode_id
        source = message_records.get(self.store, 'in-' + episode_id(event))
        # Newly accepted/future queued inputs must not enter an earlier turn.
        history_said = message_records.said(self.store, scene['_id'], scene['policy_epoch'],
                                             **({'heard_before': source['scene_seq']} if source else {}))
        history_projection={'text':1,'author':1,'direction':1,'delivery_state':1,'platform_event_id':1,
            'platform_reply_to':1,'event.group_context':1,'scene_seq':1,'episode_id':1,'received_at':1,'receipt_at':1,
            'attachment':1,'attachment_skipped':1,   # 附件位：只多带这两个小字段，字节仍在 BlobStore
            'occurred_at':1,'event.raw.'+caught_up.CATCHUP_KEY:1,   # a caught-up line shows when it was said
            'platform_receipt.response.verification':1,   # what of her line the platform really stored
            'event.raw.asuna_notice':1,                   # a platform notice is the program's line (notices.py)
            'recalled_at':1}                              # a line of hers she took back (role_tools._recall_part)
        if read['linked_scenes']:
            # 只在真联动时多带这几个字段：归并要有可比的时间，行上也要能看出是哪个入口说的。
            history_projection=dict(history_projection,scene_id=1,occurred_at=1,receipt_at=1,
                                    receipt=1,received_at=1)
        history=history_said.rows(newest_first=True,limit=attend.MAX_LINES if scene['kind']=='group' else 12,
                                   fields=list(history_projection))
        if scene['kind']=='group':
            history=catch_up(self.store,scene,history)
        if read['linked_scenes']:
            history=self._merge_linked_history(history,scene,read,history_projection)
        self._reply_context(history, scene, keep_event=True)
        zone=schedule_rules.scene_timezone(self.store.config,scene)
        for row in history:                      # no raw times: when it was said, on her clock face
            said=caught_up.said_at(row); late=caught_up.is_caught_up(row)
            got=row.get('receipt_at') or row.get('received_at')
            for key in ('received_at','receipt_at','occurred_at'):row.pop(key,None)
            stamp=schedule_rules.line_stamp(zone,said)
            if stamp:row['at']=stamp+('（%s）'%caught_up.CAUGHT_UP_WORD if late else '')
            # When it reached the other side, only when that is another minute: the gap is the delay (her ask).
            arrived=schedule_rules.line_stamp(zone,got)
            if stamp and arrived and arrived!=stamp:row['arrived']=arrived
        for row in history:
            if ((row.pop('event', None) or {}).get('raw') or {}).get('asuna_notice'):
                row['notice']=notices.HISTORY_WORD
            if row.pop('recalled_at',None):
                row['recalled']='你撤回了这句'
            # The platform took the line but stored less of it (a face, a quote): she reads which part did not land.
            lost=landing_lost((row.pop('platform_receipt',None) or {}).get('response',{}).get('verification'))
            if lost:row['not_landed']=lost
        undelivered=message_records.outgoing(self.store,scene['_id'],['READY','QUEUED_EXTERNAL','SENDING','FAILED','UNKNOWN']).rows(
            newest_first=True,limit=4,fields=['text','delivery_state','author','platform_receipt.response.reason',
            'platform_receipt.response.retcode','action.kind','file.name','failure','failure_detail',
            'platform_receipt.response.platform'])
        for row in undelivered:
            row['text']=excerpt(row.get('text'),HISTORY_ROW_CHARS)
            response=((row.get('platform_receipt') or {}).get('response') or {})
            if row.pop('file',None) is not None and row.get('delivery_state')=='FAILED':
                # A file that did not go says why, the program's reason or the platform's (ADR-092 D7).
                from . import outbound_files
                row['delivery_state']=outbound_files.failure_words(row)
                for key in ('platform_receipt','failure','failure_detail'):row.pop(key,None)
                continue
            row.pop('failure',None);row.pop('failure_detail',None)
            if (row.pop('action',None) or {}).get('kind')=='recall' and row.get('delivery_state') in ('FAILED','UNKNOWN'):
                # Her taking back a line of hers that did not go through, said as such (her ask): never left as "handed over".
                row.pop('platform_receipt',None)
                row['delivery_state']=('撤回没成：平台没执行' if row['delivery_state']=='FAILED' else '撤回不知道成没成：平台没回话') \
                    +('（%s）'%(response.get('reason') or 'retcode %s'%response.get('retcode')) if response.get('reason') or response.get('retcode') is not None else '')
                continue
            reason=((row.pop('platform_receipt',None) or {}).get('response') or {}).get('reason')
            # In words (AGENTS.md): an unknown send has most likely arrived, so she does not send it twice.
            row['delivery_state']=(own_mute.FAILED_WORDS if row.get('delivery_state')=='FAILED' and reason==own_mute.REASON
                                   else UNDELIVERED_WORDS.get(row.get('delivery_state'),row.get('delivery_state')))
        tail_sources={x for m in history for x in (m['_id'],m.get('platform_event_id')) if x}
        # Her last few thoughts here reach every turn (recent_thoughts, or still on screen): in view like these lines.
        tail_sources.update(m['_id'] for m in memory_records.of_kind(
            self.store,'monologue',scope=scope,status='active',by='formed_at').rows(
            newest_first=True,limit=RECENT_THOUGHTS,fields=['_id']))
        if source:
            for queued in message_records.inbound(self.store, scene['_id'], from_seq=source['scene_seq'],
                                                  by=None).rows(fields=['platform_event_id']):
                tail_sources.update((queued['_id'], queued.get('platform_event_id')))
        # The lines this turn delivers, for the presence cue (ADR-097 D2), before their numbers are dropped.
        history_lines=[(row.get('scene_seq'),row.get('text') or '',row.get('direction')) for row in history]
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
        own=[]
        brought_up=[]                    # her own items this turn's retrieval brought up (ADR-096)
        would_surface=[]                 # carried items it would have brought up, had they not been carried
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
            if self.pilot is not None and isinstance(event.get('text'),str):
                try:
                    # Queued only: scored off the reply path, written apart, never part of this context.
                    self.pilot.submit(query=event['text'],vector=self.retrieval.query_vector(event['text']),scope=scope,
                                      private_scope=visibility.owner_private_scope(persona)
                                          if session_class==visibility.OWNER_PRIVATE else None,
                                      scene=scene,session_class=session_class,
                                      turn_kind=turn_kind or event.get('episode_kind') or 'external',event_id=event['event_id'],
                                      recall=recall)
                except Exception:
                    pass
            if memory_tiers.ENABLED and self.pilot is not None and isinstance(event.get('text'),str):
                # ADR-062: two of the six slots for her own items at hand (a recall reaches put-away ones too).
                try:
                    _private=visibility.owner_private_scope(persona) if session_class==visibility.OWNER_PRIVATE else None
                    own,would_surface=memory_tiers.deliver(self.store,persona,self.pilot,self.retrieval,event['text'],
                                             {'global-safe',scope,*([_private] if _private else [])},scene['_id'],
                                             recall=recall,excerpt_chars=MEMORY_CHARS)
                except Exception:
                    own,would_surface=[],[]
                if own:
                    memories=memories[:memory_tiers.SLOTS-len(own)]
                brought_up=[item['_id'] for item in own]
                if not recall:
                    # ADR-097: what came back is counted (D5), and one line of presence for a word her other groups
                    # know may take a free own-item slot (D2).
                    try:
                        from . import crossing as _crossing
                        for item in own:
                            word=item['why'][len(memory_tiers.BROUGHT_BY.split('%s')[0]):-1] if item.get('why') else None
                            _crossing.fired(self.store,persona,'note',scene,event,ref=item['_id'],word=word,
                                            by='word' if word else 'meaning')
                        _cue=_crossing.cue(self.store,persona,scene,event,history_lines,own,
                                           schedule_rules.scene_timezone(self.store.config,scene),
                                           free=len(own)<memory_tiers.OWN_SLOTS)
                    except Exception:
                        _cue=None
                    if _cue:
                        own=[*own,_cue]
                        memories=memories[:memory_tiers.SLOTS-len(own)]
        else:
            readable=[('global-safe',1),(scope,scene['policy_epoch'])]
            if session_class==visibility.OWNER_PRIVATE:
                readable.append((visibility.owner_private_scope(persona),1))
            memories=memory_records.readable(self.store,readable,by='_id').rows(limit=6,fields=memory_records.UNVECTORED)
            retrieval_manifest={'path':'scoped_recent_development_fallback','vector_verified':False}
        # scope_key 一起给出：联动场景召回的记忆要说得清是从哪个场景来的，不然「他说过」会没头没尾。
        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','kind','source_event_ids','source_window','generated_at','status','historical_sources','speaker','scene_seq','occurred_at','scope_key','segment_index','segment_count','participants','source_by_speaker','attribution','corrected_by','entry_type','invented') if k in m} for m in memories]
        units={m['_id']:m for m in memories}
        memory_zone=schedule_rules.scene_timezone(self.store.config,scene)
        for fact in facts:
            # The whole unit stays readable through recall/read; the turn carries a bounded excerpt.
            fact['body_markdown']=excerpt(fact.get('body_markdown'),MEMORY_CHARS)
            unit=units.get(fact['_id']) or {}
            # When it was said, on the same clock face as her history lines, so today and yesterday read apart.
            when=self.when(unit,memory_zone,moment)
            if when:fact['when']=('盖到 '+when) if fact.get('epistemic_type')=='derived_summary' else when
            if fact.get('kind')=='monologue':
                # One of her past thoughts: what she did then (reasons.py).
                from . import reasons
                if unit.get('source')=='thinking':
                    # ADR-099: another model's summary, marked; short in a turn, longer when she recalls it.
                    fact['body_markdown']=reasons.shown(unit,MEMORY_CHARS,recall=bool(recall))
                then=reasons.then(self.store,unit)
                if then:fact['then']=then
            if fact.get('invented'):
                # Fixed mark on every injection of persona-authored, not shared, history (MEMORY §5).
                fact['body_markdown']=INVENTED_MARK+fact['body_markdown']
        # derived_summary 显式与 public_statement 同层：它是程序按原文整理的转述，既不是
        # 角色的看法也不是人物亲口陈述。摘要没有 scene_seq/segment_index，同层内不抢位。
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'derived_summary':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
        for fact in facts:
            # Only what she reads (ADR-060, her review 2026-10-14): where it comes from as a word, when it was said,
            # and the source ids she reads the original lines back by; storage state, ordering numbers and a second
            # copy of the time stay the program's.
            fact['from']=MEMORY_FROM.get(fact.pop('epistemic_type',None),'别处来的')
            for key in ('status','kind','scene_seq','segment_index','segment_count'):
                fact.pop(key,None)
            if not fact.get('historical_sources'):fact.pop('historical_sources',None)
            if fact.get('when'):
                fact.pop('occurred_at',None);fact.pop('generated_at',None)
        facts.extend(own)
        # A storage revision counts writes/tool calls, not conversational time.
        # Use each task's durable input timestamp, including legacy tasks, so
        # recently returned work is not hidden behind old high-write tasks.
        task_states=task_records.recent_with_inputs(self.store,scene['_id'],scope,scene['policy_epoch'])
        # Every open task (and every finished one whose result has not reached her), and only the last few others
        # (their results came back as their own turns).
        open_tasks=[task for task in task_states if task['_active'] or task['state']=='PAUSED'
                    or _handover.waiting(task)]
        task_states=open_tasks+[task for task in task_states if task not in open_tasks][:FINISHED_TASKS_SHOWN]
        paused=any(task['state']=='PAUSED' for task in task_states)
        carried_on=_handover.continuations(self.store,[task['_id'] for task in task_states])
        from .tasks import FIRST_PAGE_CHARS, task_pages
        for task in task_states:
            task.pop('_active',None)
            # A report longer than its first page reached her as that page; the rest she reads with task op page.
            if task.pop('_report_chars',0)>FIRST_PAGE_CHARS:
                row=task_records.get(self.store, task['_id'], fields=['result.text', 'intent_revision']) or {'_id':task['_id']}
                text=((row.get('result') or {}).get('text')) or ''
                pages=task_pages(self.store,row)
                if len(pages)>1:
                    task['report']='报告 %d 页（原文 %d 字），交回来时只给了第一页；其余用 task 的 page 翻读'%(len(pages),len(text))
            # A task's title is what she called it; the old goal text only when there is no title.
            if task.get('title'):
                task.pop('goal',None)
            elif task.get('goal'):
                task['goal']=excerpt(task['goal'],EXPERIENCE_TASK_CHARS)
            # Where it stands, in words (ADR-030 D7), instead of the raw fields.
            task['status']=_handover.status_words(task,carried_on.get(task['_id']))
            # The tier she chose and the one that ran it, in capability words (ADR-075); only where there are two.
            from . import action_tiers
            tier=task.pop('tier',None)
            if tier and action_tiers.offered():
                task['tier']=action_tiers.words(tier)
            running=task['state'] in ('READY','RUNNING')
            for key in ('state','feedback_state','cancel_reason','pause_reason','paused_at'):
                task.pop(key,None)
            if not running:
                continue
            # What the action brain reported on its own while working (report_progress), newest last.
            notes=task_records.thread(self.store,task['_id'],sender='action').rows(newest_first=True,limit=2,
                fields=['text'])
            if notes:
                task['progress_from_action']=[excerpt(row['text'],HISTORY_ROW_CHARS) for row in reversed(notes)]
        plan_rows=plan_records.of_conversation(self.store,scene['_id'],scope=scope,person=event['person_id'],
            epoch=scene['policy_epoch'],statuses=['CREATING','ACTIVE','SUSPENDED'],
            # Her rhythms belong to the program (ADR-012 §4.3); she tunes them with set_policy, never cancels them.
            not_kinds=['self_development','presence','settlement','condense']).rows(newest_first=True,limit=8,
            fields=['_id','intent','rule','scheduled_at','status','plan_version','timezone','tz_source',
                    'next_fire_at','created_at','updated_at','last_outcome'])
        # P3：计划行按这个场景的时区翻成人话再给她看——不让她自己拿 UTC 心算「明天九点」。
        # 已暂停（SUSPENDED）也列出来：不列就等于她不知道自己有一条挂着的安排没生效。
        schedule_zone=schedule_rules.scene_timezone(self.store.config,scene)
        plans=[schedule_rules.project(row,schedule_rules.scene_timezone(self.store.config,scene,row),
                                      moment) for row in plan_rows]
        # Recall is said in words only when it falls short (AGENTS.md: interpreted state); the score stays in the manifest.
        # A recall she asked for says what it held back because she still sees it, and where that is.
        in_view=(retrieval_manifest.get('in_view') or []) if recall else []
        held_back=None
        if in_view:
            said=sorted(filter(None,(self.said_at(u) for u in memory_records.many(self.store,in_view).each(
                fields=['kind','scene_seq','source_window','scope_key','occurred_at','formed_at','generated_at']))))
            earliest=schedule_rules.line_stamp(memory_zone,said[0]) if said else ''
            held_back='另有 %d 条相关的没重复给：都在你眼前这段对话里%s。'%(len(in_view),'（最早是 %s 那条）'%earliest if earliest else '')
        coverage_block=None
        if retrieval_manifest.get('coverage')=='insufficient' and not (held_back and not memories):
            coverage_block=('关于眼前这件事，你想不起相关的记忆；不要编，记不清就直说。' if not memories
                            else '想起来的这些和眼前的事关系不大：只能当灵感，不能当事实说。')
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 # How well she knows them (familiarity.py) and what she has written about them, in words.
                 'relationship':{**familiarity_words(self.store,event['person_id'],persona),
                                 'person':_understanding.person_view(self.store,event['person_id'],scope,person_head,moment),
                                 'here':((relation[1]['content'] or {}).get('body') if relation else None)
                                        or _understanding.NO_HERE},
                 'self_state_from_program':self_state,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'task_state_from_program':task_states,
                 'plans_from_program':plans,
                 # The clock changes every turn; how to write a plan does not, so it is its own block and a
                 # session that already holds it is not sent it again (context-delivery.js).
                 'clock_from_program':schedule_rules.local_clock(schedule_zone,moment),
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        if coverage_block:
            context['coverage_from_program']=coverage_block
        if held_back:
            context['held_back_from_program']=held_back
        thoughts=self.recent_thoughts(scope,schedule_rules.scene_timezone(self.store.config,scene))
        if thoughts:
            context['recent_thoughts_from_program']={'items':thoughts,
                'note':THOUGHTS_NOTE}
        if paused:
            context['task_continuation_from_program'] = (
                '「做到一半宿主重启停了」的是重启后等待操作者决定的旧行动，历史与回执仍保留。'
                '只有主人明确要继续时才可以用 task 的 message 接着做；'
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
                'note':'这个人在配置里与另一个入口是同一个人，关系与偏好只维护那一份；这一回合的理解更新'
                       '会写进 scope 那个场景的那一份，来源仍只取本轮场景里真实给过你的证据。'}
        if event.get('episode_kind') == 'self_development' and isinstance(event.get('night_stage'), dict):
            from .rhythm import night_stage_block
            context['night_stage_from_program']=night_stage_block(event['night_stage'])
        if event.get('episode_kind') == 'self_development':
            # ADR-011 §6.2: ideas from anywhere are read and decided only here.
            from .role_tools import ideas_block, ideas_left
            ideas=ideas_block(self.store,persona,moment)
            if ideas:
                more=ideas_left(self.store,persona,len(ideas))
                context['ideas_from_program']={'items':ideas,**({'more':more} if more else {}),
                    'note':IDEAS_NOTE}
        if event.get('episode_kind') in ('self_development', 'presence'):
            if event.get('task_id'):
                context['ongoing_development_task_id_from_program']=event['task_id']
            # Local owner opportunity may read the real scenes already bound to
            # this host. Keep source scene/author on each excerpt.
            allowed = {scene['_id']}
            for channel in self.store.config.get('channels', {}).values():
                allowed.update(route['scene_id'] for route in channel.get('routes', {}).values())
            # Owner 2026-10-06 (ADR-017): what other people say in public reaches home only through her own review
            # (ideas notebook, nightly settlement), never live. Here: everything from her private conversations,
            # and from the others only her own delivered lines; how the groups are going is in places_from_program.
            private = (visibility.owner_private_scenes(self.store.config) | {scene['_id']}) & allowed
            recent = message_records.said_across(self.store, private, allowed).rows(
                newest_first=True, limit=EXPERIENCE_MESSAGES,
                fields=['scene_id','author','direction','text','received_at','delivery_state'])
            for row in recent:
                row['text']=excerpt(row.get('text'),EXPERIENCE_MESSAGE_CHARS)
            # Headlines (owner, 2026-10-05): titles, states and the start of each report; recall reads more.
            tasks = task_records.of_conversations(self.store, list(allowed), by='finished_at').rows(
                newest_first=True, limit=EXPERIENCE_TASKS, fields=['scene_id','state','title','goal','failure_type',
                                                                    'result','feedback_state','finished_at'])
            for item in tasks:
                if item.get('title'):
                    item.pop('goal',None)
                elif item.get('goal'):
                    item['goal']=excerpt(item['goal'],EXPERIENCE_TASK_CHARS)
                result=item.pop('result',None)
                # A report of work from a public conversation may quote people there: home sees its headline only.
                if isinstance(result,dict) and result.get('text') and item.get('scene_id') in private:
                    item['report_start']=excerpt(result['text'],EXPERIENCE_TASK_CHARS)
            lineage=receipt_records.sink_of_kind(self.store,'self_development_publish',by='published_at').rows(
                newest_first=True,limit=EXPERIENCE_PUBLICATIONS,fields=['project','state','changed_files',
                'deleted_files','published_at','activated_at','task_id'])
            for row in lineage:
                # How much each publication changed, not every path (the receipt keeps the list).
                row['changed_files']=len(row.get('changed_files') or [])
                row['deleted_files']=len(row.get('deleted_files') or [])
            context['recent_experience_from_program'] = {
                'messages': list(reversed(recent)), 'tasks': tasks, 'publish_lineage':lineage,
                'note': EXPERIENCE_NOTE}
        if event.get('episode_kind') == 'presence' or (event.get('episode_kind') == 'scheduled'
                                                        and session_class == visibility.OWNER_PRIVATE):
            # ADR-012 §4.4: her groups in words, and what her recent visits came to. A plan of her own that
            # comes due at home may send her out too (2026-10-06): the same places, the same limits.
            from . import places
            from .render import model_and_policy as _places_model
            plan=plan_records.get(self.store, 'plan-asuna-presence') or {}
            _pm,_pp=_places_model(self.store,persona)
            date=places.local_date(self.store.config,_pm,_pp,moment)
            places_view=places.places_block(self.store,persona,_pm,_pp,plan,moment,date)
            if places_view:
                context['places_from_program']=places_view
            visits=places.last_visits_block(self.store,persona,plan,moment)
            if visits:
                context['last_visits_from_program']=visits
            if event.get('episode_kind')=='presence':
                # what her night turns changed since the last heartbeat (night.py)
                from . import night as _night
                from .ingress import episode_id as _night_episode
                changed=_night.block(self.store,persona,schedule_zone,moment,_night_episode(event))
                if changed:
                    context['night_from_program']=changed
            # who she still waits for in her groups (waiting.py): at home is where she thinks about it
            from . import waiting as _waiting
            still=_waiting.block(self.store,[sid for sid,_,_ in places.groups(self.store.config)],moment,persona,home=True)
            if still:
                context['waiting_from_program']=still
            # what her peer lines said that was not addressed to her, until she speaks there (ADR-045)
            from . import lines as _asides_lines
            asides=_asides_lines.asides(self.store,schedule_zone)
            if asides:
                context['peer_asides_from_program']=asides
        # ADR-013 §6: her peer lines and whether she has them open, at home and in the line's own conversation.
        from . import lines as _lines
        peer_lines=_lines.peer_lines(self.store)
        if peer_lines and (session_class==visibility.OWNER_PRIVATE
                           or event['scene_id'] in {line['scene_id'] for line in peer_lines}):
            from .persona_model import timezone as _line_zone
            from .render import model_and_policy as _line_model
            _lm,_lp=_line_model(self.store,persona)
            context['lines_from_program']=_lines.view(self.store,peer_lines,_line_zone(_lm,_lp,self.store.config)[0],moment)
            # What she has planned to do in each line from home (plan with line=…): her own words and the timing.
            for _item,_line in zip(context['lines_from_program']['items'],peer_lines):
                if _line['scene_id']==event['scene_id']:
                    continue
                _rows=plan_records.of_conversation(self.store,_line['scene_id'],statuses=['CREATING','ACTIVE'],
                    not_kinds=['self_development','presence','settlement','condense']).rows(newest_first=True,limit=3)
                if _rows:
                    _scene=scene_records.get(self.store, _line['scene_id']) or {'_id':_line['scene_id']}
                    _item['your_plans_there']=[{k:v for k,v in schedule_rules.project(r,schedule_rules.scene_timezone(
                        self.store.config,_scene,r),moment).items() if k in ('intent','description','next_fire_at')} for r in _rows]
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
            offer=outbound_media.offer(self.store,self.store.config,scene,session_class,event['person_id'],
                                     picked=(event.get('visit') or {}).get('artifact_id'))
            if offer:context['image_artifacts_from_program']=offer
            elif session_class==visibility.OWNER_PRIVATE:
                # Looking does not wait on sending: where none of her pictures can go out (her local chat), she
                # still sees her own newest ones listed, and read_image comes with them (role_tools.her_pictures).
                from .vision import vision_capability as _vision
                mine=outbound_media.own_pictures(self.store,moment) if _vision(self.store.config,'character')['supported'] else []
                if mine:context['your_pictures_from_program']={'items':mine,'note':outbound_media.OWN_PICTURES_NOTE}
        # ADR-092: the files her tasks registered that this conversation may send (a group whose adapter takes files).
        from . import outbound_files
        files=outbound_files.offer(self.store,scene)
        if files:context['file_artifacts_from_program']=files
        # ADR-017: whoever talks to her at home may send her on an errand; where it can go, and what came of the last ones
        # (program words only: nobody's reply comes home this way).
        if session_class==visibility.OWNER_PRIVATE and event.get('episode_kind') not in ('self_development','presence'):
            # Owner 2026-10-06: her own doings elsewhere, as words (heartbeats have recent_experience instead).
            from . import places as _places
            done_elsewhere=_places.elsewhere(self.store,persona,moment,{scene['_id']},visibility.owner_private_scenes(self.store.config))
            if done_elsewhere:
                context['elsewhere_from_program']=done_elsewhere
        if session_class==visibility.OWNER_PRIVATE and _errand_from_here(self.store,event):
            from . import places as _places
            targets=_places.errand_places(self.store,persona)
            if targets:
                context['errand_places_from_program']=targets
            errands=_places.errands_block(self.store,persona,moment)
            if errands:
                context['errands_from_program']=errands
        # ADR-016: her sticker shelf where stickers can go out (and at home, to tidy it), the platform's faces.
        from . import stickers as _stickers
        if _stickers.sends(scene):
            context['stickers_from_program']=_stickers.send_block(self.store,persona)
            if scene.get('kind')=='group':
                # Stickers people posted here lately, saved in her candidate pool (owner 2026-10-06).
                here=_stickers.candidates_block(self.store,moment,scene['_id'])
                if here:context['sticker_candidates_from_program']=here
            faces=_stickers.faces_block(self.store,scene)
            if faces:context['faces_from_program']=faces
        elif session_class==visibility.OWNER_PRIVATE and not event.get('episode_kind') in ('settlement',):
            # At home a sticker cannot be sent: the whole shelf comes in the turns that tidy it, its names otherwise
            # (measured 2026-10-16: 5,700 characters in every home turn, 7.8% of all she was sent; her answer: keep
            # the names, which are hers and what she remembers them by).
            tidying=event.get('episode_kind')=='self_development' or event.get('dice') in ('self_evaluation','review_dice')
            shelf=(_stickers.block(self.store,persona,scene,at_home=True) if tidying
                   else _stickers.names_block(self.store,persona))
            if shelf:context['stickers_from_program']=shelf
        # Owner 2026-10-07: her credential vault at home, names and notes only (credentials.py).
        if session_class==visibility.OWNER_PRIVATE and (event.get('episode_kind') or 'external') in ('external','task_feedback','self_development'):
            from . import credentials as _credentials
            vault=_credentials.listing()
            if vault:context['credentials_from_program']={'items':vault,'note':_credentials.CREDENTIALS_NOTE}
        # Owner 2026-10-06: her watchlist, and this line's speaker being on it.
        from . import watches as _watches
        watching=_watches.watching_block(self.store,persona,session_class,moment)
        if watching:context['watching_from_program']=watching
        watched=_watches.watched_block(self.store,event,session_class)
        if watched:context['watched_from_program']=watched
        # ADR-058: a heartbeat that rolled self evaluation brings her day in raw readings (home only).
        # ADR-070/071: once a week her tools and her own sections in full, with a floor: nine days without them and
        # any home heartbeat that reaches her carries the review, whatever it rolled.
        from . import tools_week as _tools_week
        reviewing=(event.get('episode_kind')=='presence' and session_class==visibility.OWNER_PRIVATE
                   and (event.get('dice')=='self_evaluation' or _tools_week.due(self.store,persona,moment)=='floor'))
        if reviewing:
            from . import self_review
            from .persona_model import effective as _review_effective, timezone as _review_zone
            from .render import model_and_policy as _review_model
            _model,_policy=_review_model(self.store,persona)
            _zone=_review_zone(_model,_policy,self.store.config)[0]
            _tag=_review_effective(_model,'self_review.tag',_policy)
            review=self_review.block(self.store,persona,_zone,moment)
            review['exchanges']=self_review.exchanges(self.store,persona,_zone,moment)
            weekly_tools=_tools_week.block(self.store,persona,moment)
            if weekly_tools:
                context['tools_week_from_program']=weekly_tools
                whole=self_review.cared(self.store,persona,_tag,whole=True)
                if whole:context['cared_from_program']={'items':whole}
                # Her tag matches exactly: the week says what it found, so a tag off by a character is seen (her ask).
                weekly_tools['sources']+=('；self_review.tag「%s」在 self、core 里找到 %d 节'%(_tag,len(whole or []))
                                          if _tag else '；人格模型里没有 self_review.tag')
            else:
                line=self_review.cared(self.store,persona,_tag)
                if line:review['cared']=line
            context['self_review_from_program']=review
            # ADR-073: a map of what she has, what she changed and why, and her attention as counts.
            from . import reflection_map as _map
            context['map_from_program']=_map.block(self.store,persona,moment,tag=_tag)
            if memory_tiers.ENABLED:
                # ADR-062 (her answer): once a week, her memory in three readings, no scores and no counts.
                weekly=memory_tiers.week(self.store,persona,schedule_rules.scene_timezone(self.store.config,scene),moment)
                if weekly:
                    context['memory_week_from_program']=weekly
        # ADR-058: a heartbeat that rolled review brings every roll since her last review (home only).
        if (event.get('dice')=='review_dice' and event.get('episode_kind')=='presence'
                and session_class==visibility.OWNER_PRIVATE):
            from . import dice as _dice
            occurrence=str(event.get('event_id') or '').split(':',1)[-1]
            context['dice_review_from_program']=_dice.review(self.store,persona,occurrence,moment)
        # ADR-052: her switches: at home all of them (and those that ended lately), elsewhere the ones on here.
        from . import switches as _switches
        switched=(_switches.home_block(self.store,persona,moment) if session_class==visibility.OWNER_PRIVATE
                  else _switches.here_block(self.store,scene['_id'],moment))
        if switched:context['switches_from_program']=switched
        if scene.get('kind')=='group':
            from . import waiting as _waiting
            still=_waiting.block(self.store,[scene['_id']],moment,persona)
            if still:context['waiting_from_program']=still
        # ADR-018: notes between her conversations -- the one that opened this turn, the others written to here,
        # what came of the ones she wrote here, and where a note from here can go.
        from . import notes as _notes
        from .ingress import episode_id as _note_episode
        note_kind=event.get('episode_kind') or 'external'
        first_note=_notes.opening_for(self.store,event) if note_kind in ('note','visit') else None
        this_turn=_note_episode(event)
        if first_note:
            context['note_from_program']=_notes.opening_block(self.store,persona,first_note,session_class,this_turn,moment)
        got=_notes.received_block(self.store,persona,scene['_id'],session_class,note_kind,this_turn,moment,skip=first_note)
        if got:context['notes_from_program']=got
        sent=_notes.sent_block(self.store,persona,scene['_id'],moment)
        if sent:context['notes_sent_from_program']=sent
        if scene.get('kind')=='group':
            # ADR-061 step 2: her questions in this group, by id, with who answered (labels and times).
            from . import questions as _group_questions
            here=_group_questions.group_block(self.store,persona,scene,moment)
            if here:context['questions_from_program']=here
        if session_class==visibility.OWNER_PRIVATE:
            # ADR-061: her questions still open, and once each one the program closed; a question whose note opened
            # this turn is named by its id only (the note carries its text).
            from . import questions as _questions
            _questions.migrate(self.store,persona)
            asked=_questions.block(self.store,persona,scene['_id'],moment,(first_note or {}).get('question'))
            if asked:context['questions_from_program']=asked
            from . import host_stops as _host_stops
            stops=_host_stops.listed(self.store,moment)
            away=_host_stops.block(self.store,schedule_zone,moment,persona,rows=stops)
            if away:context['host_from_program']=away
            shown_stops=[row['_id'] for row in stops]      # stamped shown_at when this turn commits (ADR-101)
            from . import restarts as _restarts
            restarted=_restarts.block(self.store,schedule_zone,moment)
            if restarted:context['restart_from_program']=restarted
        if note_kind!='consult':
            note_places=_notes.places_view(self.store,persona,scene['_id'],session_class,first_note)
            if note_places:context['note_places_from_program']=note_places
        if event.get('episode_kind')=='scheduled':
            plan=plan_records.get(self.store, event.get('scheduled_plan_id'),
                ['_id','intent','rule','last_occurrence_id','last_outcome','source_episode_id'],
                scene=scene['_id'],scope=scope,person=event['person_id'],epoch=scene['policy_epoch'])
            if not plan:raise Denied('SCHEDULE_PLAN_CONTEXT_MISSING')
            # Why she set it: her thought when she made the plan, as she wrote it (reasons.py, ADR-043).
            from . import reasons as _reasons
            then=_reasons.for_call(self.store,plan.pop('source_episode_id',None),'plan_id',plan['_id'])
            if then:plan['your_thought_then']=then
            context['scheduled_plan_from_program']=plan
        target_note=('只更新对当前说话人的理解：layer=person 写人那层（你在哪儿遇到他都看得到），layer=here 写这里那层'
                     + ('（只在这个对话里看得到）' if not target['shared'] else
                        '（配置认定他与另一个入口是同一个人，这里那层共用 %s 那一份）' % target['scope'])
                     + '；不修改全局人格或权限。' + _understanding.ASK)
        if retrieval_manifest.get('error'):
            context['retrieval_diagnostic_from_host']=retrieval_manifest
        if source and source.get('failure'):
            context['prior_input_failure_from_host']=source['failure']
        if event.get('group_context'):
            group = event['group_context']
            refs = [group.get('reply_message_id')]
            if group.get('topic_id'):
                anchor = message_records.of_event(self.store, scene['_id'], scene['policy_epoch'], group['topic_id'],
                                                  fields=['_id'])
                if anchor: refs.append(anchor['_id'])
            related = message_records.many(self.store, [r for r in refs if r], scene=scene['_id'],
                                           epoch=scene['policy_epoch']).rows(fields=RELATED_FIELDS)
            # P5：整条话题线（含没@她的旁听行）一并给出——接不上话题就谈不上要不要接话。
            seen = {row['_id'] for row in related}
            if group.get('topic_id'):
                for row in message_records.said(self.store, scene['_id'], scene['policy_epoch'],
                                                topic=group['topic_id']).rows(newest_first=True, limit=12,
                                                                              fields=RELATED_FIELDS):
                    if row['_id'] not in seen:
                        seen.add(row['_id'])
                        related.append(row)
                related.sort(key=lambda row: row.get('scene_seq') or 0)
            self._reply_context(related, scene)
            speaker_tail = message_records.inbound(self.store, scene['_id'], scene['policy_epoch'],
                author=event['person_id'], before=source['scene_seq']).rows(
                newest_first=True, limit=3,
                fields=['text','author','scene_seq','event.group_context','occurred_at','received_at']) \
                if source and event.get('episode_kind')!='visit' else []
            self._reply_context(speaker_tail, scene)
            for row in [*related, *speaker_tail]:
                for key in ('occurred_at', 'receipt_at', 'received_at'):
                    row.pop(key, None)
                # Her own line keeps its turn's id: the Host leaves it out while that turn is still visible.
                if row.get('direction')!='outbound':
                    row.pop('episode_id', None)
                row['text']=excerpt(row.get('text'),HISTORY_ROW_CHARS)
            continuity = {**group, 'related_messages': related,
                          'current_speaker_tail': list(reversed(speaker_tail))}
            if str(group.get('wake_reason') or '').startswith('proactive'):
                continuity['proactive_from_program'] = PROACTIVE_NOTE
            elif group.get('wake_reason') == 'chain' and isinstance(group.get('chain'), dict):
                # Owner 2026-10-06: a chain forming is when joining fits; she decides, once per chain.
                chain = group['chain']
                continuity['chain_from_program'] = {
                    'what': '同一张表情包或图' if chain.get('media') else excerpt(chain.get('what'), 60),
                    'people': '%d 个人接连发了这个' % int(chain.get('people') or 0),
                    'note': CHAIN_NOTE}
            elif group.get('wake_reason') == 'catchup_mention':
                continuity['caught_up_from_program'] = ('这句是断线时漏收、恢复后补读进来的旧话，当时 @ 了你或回了你；'
                    '它是什么时候说的看行上的时间。答之前先看群里后来怎么样了，现在还用不用答。')
            elif group.get('wake_reason') == 'awaited_answer':
                # Her own await_answer on her last line here: what she said she was waiting for, in her words.
                mine = message_records.spoken(self.store, scene['_id'], author=character_id(self.store.config)).first(
                    newest_first=True, fields=['episode_id'])
                waiting = ((episode_records.get(self.store,(mine or {}).get('episode_id'),fields=['await_answer']) or {})
                           .get('await_answer') or {}).get('why')
                continuity['awaited_from_program'] = {'you_were_waiting_for': excerpt(waiting, 200) if waiting else '',
                    'note': '你上一句 @ 了他或是在回他（或你说了在等回话）；这句没 @ 你也没引用你，是不是在回你由你判断。'}
            context['group_continuity_from_program'] = continuity
        model,policy=model_and_policy(self.store,persona)
        documents={'persona':system_ref['persona_doc_revision'],'voice':system_ref['voice_doc_revision']}
        ledgers=ledger_block(docs,session_class)
        if memory_tiers.ENABLED and not recall:
            # ADR-062: where her things are, in words, and what the program moved since this conversation was told.
            from .group_admin import notes_slug as _notes_slug
            context['things_from_program']=memory_tiers.Tiers(self.store,persona).things(
                session_class,scene,schedule_rules.scene_timezone(self.store.config,scene),moment,
                home=session_class==visibility.OWNER_PRIVATE,
                readable_docs={_notes_slug(scene['_id'])} if scene['kind']=='group' else set())
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
        if scene['kind']=='group':
            from . import group_members
            members=group_members.block(self.store,scene,persona)
            if members:context['members_from_program']=members
        from .ingress import episode_id as _episode_id
        # What she may cite that is not shown elsewhere: this turn's input id (its event id is in the event block), and
        # the document sections in a block of their own (her ask: she copies the doc refs), which stays the same from
        # turn to turn and so folds; the event's, a memory's or a task's id is in its own block and counts as well
        # (refs, ADR-056).
        context['ref_index']=['in-'+_episode_id(event)]
        doc_refs=list(dict.fromkeys([
            *['doc:%s#%s'%(item['doc'],section['section']) for item in ledgers for section in item['sections']],
            *['doc:persona#'+section['sid'] for section in carried_here['persona']]]))
        if doc_refs:context['doc_refs_from_program']=doc_refs
        manifest={'session_class':session_class,'documents':documents,'persona_revision':system_ref['persona_doc_revision'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'relationship_entity_key':relation[0]['_id'] if relation else target['entity']+'|'+target['scope'],'person_revision':person_head[0]['revision_id'] if person_head else None,'person_entity_key':person_entity+'|'+_understanding.PERSON_SCOPE,'linked_scenes':read['linked_scenes'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        if shown_stops:manifest.setdefault('told',{})['host_stops']=shown_stops
        if scene['kind']=='group':
            # ADR-082: a group is read by people. The person who starts the turn (and whoever's @ or reply to her waits
            # behind it) comes as an entry: familiarity, stance, her shorts; the full layers come with recall's person.
            for key in ('relationship','relationship_shared_from_program'):
                context.pop(key,None)
            # Whose own lines this turn shows (ids, before the rows read as labels): whom recall and understand_person
            # may name here; the program's lines are nobody's.
            # A visit's event person only authorizes the visit; it is not someone in the room.
            from .ingress import PROGRAM_AUTHOR
            manifest['present']=list(dict.fromkeys([*([] if event.get('episode_kind')=='visit' else [event['person_id']]),
                                                    *(row.get('author') for row in history
                                                                          if row.get('direction')!='outbound' and row.get('author')
                                                                          and row.get('author')!=PROGRAM_AUTHOR)]))
            if event.get('episode_kind','external')=='external':
                items,shown=_understanding.group_people(self.store,scene,event,persona,source)
                if items:
                    context['people_from_program']={'items':items,'note':PEOPLE_NOTE}
                manifest['people_shown']=shown
        else:
            # Available with or without a record: her first understanding of someone creates it.
            context['understanding_update_from_program']={
                'available':True,'target':target_note,
                'note':UNDERSTANDING_NOTE}
        from .grants import workspace_grant
        grant = workspace_grant(self.store.config, scene['_id'], event['person_id'], required=False)
        context['action_capabilities_from_program']={
            'available':bool(grant),'route':'用 delegate 把事交给行动脑；补话、接着做或叫停用 task（message、stop）。文件、网页、沙箱、原话检索和看图都是行动脑的事。',
            'cancellation_available':True,
            'network':'行动脑可以按需搜索公共网页并读取页面。',
            'delivery':'程序自动执行委托，结果作为独立事件返回当前场景；等待时仍可聊天。'}
        from .grants import development_granted
        if development_granted(self.store, scene, event, session_class):
            context['action_capabilities_from_program']['development'] = {
                'candidate':'持久的有效项目候选（代码、技能、提示、种子）；可委托行动脑检查、修改和自行发布。',
                'guide':'先读核心技能 asuna-self-improvement：改什么走哪层、怎么自检、怎么发布、什么会触发重启。'}
        from . import sandbox_backend
        if not sandbox_backend.available(self.store.config):
            # What she cannot hand over, said as such (ADR-010 D5); never how the machine is set up.
            context['action_capabilities_from_program']['not_available']=(
                '跑代码、改自己的能力、接管集成这几件事现在交不出去：没有可用的隔离环境。别答应要做这些。')
        elif session_class!=visibility.OWNER_PRIVATE:
            context['action_capabilities_from_program']['run_code']=(
                '在这里交出去的事，行动脑不能跑代码或命令；那只在主人那边做。别在这里答应跑代码。')
        # ADR-098: the placeholders by name and meaning (never their values), and which this place hands over.
        from . import local_roots as _local_roots
        context['action_capabilities_from_program']['paths']=_local_roots.context_line(
            session_class==visibility.OWNER_PRIVATE)
        context['action_capabilities_from_program']['history_query']=(
            '可委托行动脑查询当前授权场景保存的完整原话：字面检索覆盖全部消息并按 cursor 续页，返回原文、作者、时间及其来源；'
            '语义候选不等于全部原话，送达回执时间会标明是回执。需要引用原话时以查询结果为准，不凭印象复述。')
        from .vision import vision_capability
        if vision_capability(self.store.config)['supported']:
            context['action_capabilities_from_program']['read_image']=(
                '图片按 Pull 模式接：入站只带元数据与占位符，read_image(ref) 才把字节拉成这一回合真实的视觉输入；'
                '行动脑也有同一个工具，交代要按图做的事时把 ref 写进 brief。没调用就是没看过，占位符只证明那里有过一张图。')
        context['action_capabilities_from_program']['group_discussion']=(
            '可按需整理当前授权群指定时间／主题的讨论：参与者、后续更正、个人意见、未决事项与实际覆盖范围分开返回，'
            '每条带 message_id 供原文回读；分类是按字面线索的机械标注不是结论，more=true 表示只覆盖了部分'
            '（还有未读原文，或同一 reply 链的讨论流没走完），续页之后才能说整理完整；按 person '
            '整理时链上带进来的上下文发言可能不是那个人说的（标 thread_context）。措辞与取舍仍由你'
            '判断，不自动总结、不自动发言。')
        from .image_generation import available as image_available
        if image_available(self.store.config):
            context['action_capabilities_from_program']['image_generation']=(
                '行动脑能用本机的生图服务画图；画好的图登记成你自己的，之后可以随消息发出去（群里只发全年龄的图）。'
                '外部公开的生图服务也能用，但那样只能给链接。')
        from .integration import event_profile
        integration_profile = event_profile(self.store.config, event, self.store)
        if integration_profile == 'agent_home':
            context['action_capabilities_from_program']['integration'] = {
                'grant': '这条线的家里回合带窄集成授权：只有 integration_start（只启用已发布的适配器版本）和 '
                         'integration_status（只读）。没有试运行，也没有停止；RUNNING 不等于平台连上或发送成功。'}
        elif integration_profile:
            context['action_capabilities_from_program']['integration'] = {
                'grant': '本机 owner 工作域允许适配器试运行和启停。试运行用开发候选的冻结副本，启用只用已发布的版本；改适配器代码要有开发授权。仅配置端点可达；进程启动不证明平台发送。'}
        if event.get('episode_kind')=='visit':
            # ADR-012 §4.2: nobody called her; the room as it is now, and what she came for. The person on the
            # event only authorizes the turn, so no block speaks of a current speaker.
            from . import places
            context['visit_from_program']=places.visit_block(self.store,scene,event.get('visit') or {},moment)
            # ADR-049: how long this conversation is, and on a write_notes visit the phrases to work out.
            from . import condense
            upkeep={}
            if condense.size_words(scene):
                upkeep['conversation']=condense.size_words(scene)
            if (event.get('visit') or {}).get('intent') in ('write_notes','condense'):
                found=condense.phrases(self.store,scene,persona,condense.last_look(self.store,scene['_id'],
                                                                                   event.get('event_id')),moment)
                if found:
                    upkeep['phrases']=found
            if upkeep:
                context['visit_from_program']['upkeep']=upkeep
            for key in ('relationship','sender_identity','understanding_update_from_program'):
                context.pop(key,None)
        if not recall and scene.get('channel_id') and not _errands.is_errand_visit(event):
            # ADR-066: once, that home sent her here and what she said (the request stays home).
            told=_errands.told_block(self.store,scene['_id'])
            if told:context['errand_from_program']=told
        if event.get('episode_kind')=='note':
            # ADR-018 §5.1: a note's own turn at home. Nobody here sent it; the person on the event only authorizes it.
            for key in ('relationship','relationship_shared_from_program','sender_identity','understanding_update_from_program'):
                context.pop(key,None)
        if scene.get('kind')=='group':
            # How old the talk is and how much was said since (owner 2026-10-06): an old line must read as old.
            from . import places
            context['pace_from_program']=places.pace(self.store,scene,schedule_zone)
            # Platform notices held for this group since its last turn, once (notices.py).
            held=notices.take(self.store,scene,persona)
            if held:
                context['notices_from_program']=held
            # The lines she let pass at the gate since her last turn here, once (attend.py).
            passed=attend.take_passed(self.store,scene,persona)
            if passed:
                context['passed_from_program']=passed
            # Muted there: every turn in that group says so before she speaks (own_mute.py).
            muted=own_mute.line(self.store,scene,schedule_zone,moment)
            if muted:
                context['muted_here_from_program']=muted
            from . import condense
            condensed=condense.condensed_block(self.store,scene,event.get('event_id'),moment)
            if condensed:
                context['condensed_from_program']=condensed
        manifest['context_sha256']=sha(canonical(context))
        from .affect import AffectLedger
        ledger=AffectLedger(self.store,persona,model,policy)
        if ledger.enabled:
            # One heart per persona: the state is global; reasons, who and numbers stay owner-private (§6.5).
            m=ledger.model
            # Words only (AGENTS.md: interpreted state): her mood, its hints and reasons, and how to record one.
            from .affect import events_of, interpret, recording_guide
            where,mood=None,ledger.projection()
            if session_class==visibility.OWNER_PRIVATE:
                # ADR-018 §6: reasons she wrote outside say where she wrote them.
                titles,where={},{}
                for row in events_of(self.store,persona,
                        ids=[item['event_id'] for item in mood.get('contributions') or ()],
                        scopes_besides=[visibility.owner_private_scope(persona),'global-safe']).each(fields=['source_scope']):
                    scope_key=row.get('source_scope')
                    if scope_key not in titles:
                        titles[scope_key]=people.scene_title(scene_records.by_scope(self.store, scope_key))
                    where[row['_id']]='在%s记的'%titles[scope_key]
            read=interpret(m,mood,session_class,where,scope=scope)
            if read:                                    # ADR-086 D4: nothing at a quiet band outside home
                context['affect_from_program']=read
            context['how_to_record_from_program']=recording_guide(m)
            if scene.get('kind')!='group' and isinstance(context.get('relationship'),dict) and event.get('person_id'):
                # ADR-086 D1: her live feelings toward the person she is with, beside the relationship.
                felt=ledger.person_feelings(event['person_id'],session_class)
                if felt:
                    context['relationship']['feelings_toward']=felt
            proposals=ledger.proposals(scope,session_class)
            if proposals:
                context['affect_proposals_from_program']={'items':proposals,
                    'note':'情感评估路由给出的提案，只是建议：用 feel 逐条 accept、decline 或 edit（proposal_id 照抄）；过期的已明示，不再能采纳。'}
        from .role_tools import called, CALLED_NOTE
        if not recall and called({'episode_kind':event.get('episode_kind','external'),'person_id':event.get('person_id'),
                                  'context':{'event':event}}):
            # ADR-086 E2: someone called her; what she can choose, in her wording. The same text every time, so the
            # delivery sends it once per session.
            context['called_from_program']=CALLED_NOTE
        from .rhythm import rhythm_block, recent_phrasing
        owner=(self.store.config.get('chat') or {}).get('person_id')
        last=message_records.inbound(self.store,author=owner,by='received_at').first(
            newest_first=True,fields=['received_at']) if owner else None
        rhythm=rhythm_block(self.store,model,policy,session_class,moment=moment,owner_last_at=(last or {}).get('received_at'))
        if rhythm and rhythm.get('local_time')==(context.get('clock_from_program') or {}).get('now_local'):
            # The same moment on the same clock is already in clock_from_program.
            rhythm={key:value for key,value in rhythm.items() if key!='local_time'}
        if rhythm:
            context['rhythm_from_program']=rhythm
        own=[row.get('text','') for row in message_records.spoken(self.store,scene['_id']).rows(
             newest_first=True,limit=int(effective(model,'phrasing.window',policy) or 20),fields=['text'])]
        phrasing=recent_phrasing(own)
        if phrasing:
            context['recent_phrasing_from_program']={'repeated_4grams':phrasing,
                'note':'你最近常用这些说法；只是提示，不禁止，换不换由你。'}
        # A turn of hers here failed in the program since her last turn here (ADR-076 R4): said once.
        from . import faults
        fault=faults.her_line(self.store,scene,schedule_rules.scene_timezone(self.store.config,scene))
        if fault:
            context['fault_from_program']=fault
            manifest.setdefault('told',{})['fault']=scene['fault'].get('at')
        if scene.get('channel_id'):
            # How her words leave on a platform, and which lines are hers to answer now (coordinator._absorb).
            from . import channel_kinds
            from .role_tools import SPEAK_HARD_LINES
            replying=bool(channel_kinds.reply_parts(scene['_id']))
            most=int(effective(model,'speak.max_messages',policy) or 1)
            # How her words leave is said once, in her turn guide for this place (render: speaks); here only the
            # number that is this turn's.
            speak={**({'sent':REPLY_SENT%(most,SPEAK_HARD_LINES)} if replying else {}),
                   'new_lines':'这段对话里新来的话——包括你这回合中途才到的——你看见了就算你接住了：'
                               '要回就在这回合一起回，它们不会再单独叫你一次。'}
            # Her channel lost or regained a function she uses: said once here, at this turn (ADR-079 §9.7).
            from .capabilities import change_line
            leg=change_line(self.store,scene)
            if leg:
                speak['leg']=leg
            if session_class!=visibility.OWNER_PRIVATE:
                speak['one_self']=ONE_SELF          # ADR-018 §5.7: words only, nothing from elsewhere
            if replying and source and source.get('direction')=='inbound' and source.get('scene_seq') is not None:
                # ADR-079 §9.5: only in a turn where others spoke after the line that called her, their numbers to copy.
                from .capabilities import numbered
                later=[row['scene_seq'] for row in message_records.inbound(self.store,scene['_id'],
                       after=source['scene_seq'],no_notice=True).rows(fields=['scene_seq'])] \
                    if numbered(self.store,scene) else []
                if later:
                    shown='、'.join('〔%d〕'%n for n in later[:AMBIGUOUS_MAX])+('等' if len(later)>AMBIGUOUS_MAX else '')
                    speak['quote']=AMBIGUOUS%(len(later),shown)
            context['speak_from_program']=speak
            unsent=(scene.get('unsent') or {}) if replying else {}
            if unsent.get('text'):
                # ADR-064 phase 2: words she wrote in the body of her last turn here never left; said once.
                context['unsent_from_program']='没发出去：「%s」'%unsent['text']
                manifest.setdefault('told',{})['unsent']=unsent.get('episode_id')
        if event.get('episode_kind')=='settlement':
            from .rhythm import promotion_candidates
            from .affect import kind_label
            from .affect import SHORT_ID, amendments_of
            open_events=[{'event_id':e['_id'][:SHORT_ID],'feeling':kind_label(ledger.model,e.get('kind')),'why':e.get('why'),'ts':e.get('ts')}
                         for e in ledger.events() if e.get('open')
                         and not amendments_of(self.store,target=e['_id'],ops=['close','void']).first(fields=['_id'])] if ledger.enabled else []
            context['settlement_from_program']={'open_affect_events':open_events,
                'promotion_candidates':(memory_tiers.candidates(self.store,effective(model,'memory.promotion.window_days',policy) or 7)
                                        if memory_tiers.ENABLED else promotion_candidates(self.store,model,policy)),
                'promotion_quota':effective(model,'memory.promotion.daily_quota',policy) or 0,
                'note':'夜间沉淀：挂着的事可以 close / void（写理由）或保留；值得长期记住的可以 promote（fact/appraisal/signal + source_ids），配额与来源要求由程序检查。'}
            # Her notes that show every turn and are due for tidying (owner 2026-10-06, context_budget.py).
            if memory_tiers.ENABLED:
                # ADR-096: each group's notes refold at settlement (and on her writes), not every turn.
                _folds=memory_tiers.Tiers(self.store,persona)
                for _slug in docs.slugs('group:'):
                    _folds.refold(_slug,docs.read(_slug)[1],moment)
                # ADR-097: the word index of her groups' lines (a new generation, its learned words), its fire rows
                # past their keeping, then each place's common words counted again with the same cuts.
                from . import crossing as _crossing
                _crossing.build(self.store,moment)
                _crossing.prune(self.store,moment)
                _folds.rerate_all(moment)
                # ADR-062: the night list replaces the notes review (no tidy-three framing, no keep or drop).
                listed=memory_tiers.night_list(self.store,persona,moment)
                if listed:
                    context['night_list_from_program']=listed
            else:
                from .context_budget import review_block
                review=review_block(self.store,persona,moment)
                if review:
                    context['notes_review_from_program']=review
            # ADR-016: once a week, the stickers she kept and has not been sending; dropping is hers.
            from .stickers import review_block as _sticker_review
            shelf_review=_sticker_review(self.store,persona,moment)
            if shelf_review:
                context['stickers_review_from_program']=shelf_review
            # The candidate pool: what people posted in her groups, for her to look at and keep or let go.
            from .stickers import candidates_block as _candidates
            pool=_candidates(self.store,moment)
            if pool:
                context['sticker_candidates_from_program']=pool
        # Which writes and reads this turn allows (owner_private or public) is a program fact, stated plainly.
        context['session_class']=session_class
        # The ceiling applies to what a turn sends, not to what is prepared (coordinator._deliver, context_budget.py).
        from .context_budget import size as _size
        manifest['context_chars']=_size(context)
        people.relabel(context,scene,event['person_id'])
        context=order_context(context,effective(model,'recall_protocol.order',policy))
        manifest['context_sha256']=sha(canonical(context))
        manifest['system_ref']=system_ref
        # ADR-096: what this turn carried, counted nightly (carried_counts): its pair's sections, the group-notes
        # sections shown, and what its own retrieval brought up.
        manifest['carried']=_carried.manifest(carried_here,system_ref['place'],session_class,moment,
            notes=['doc:%s#%s'%(group_admin.notes_slug(scene['_id']),s['sid'])
                   for s in (context.get('group_notes_from_program') or {}).get('sections') or []],
            brought_up=brought_up,would_surface=would_surface)
        return system,context,manifest
