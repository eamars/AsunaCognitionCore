"""Her mind's tools: what the character brain may do in one native turn (ADR-011 §3, §5.1).

The character brain thinks, remembers, feels, writes down, plans, hands work to the action brain,
and speaks or stays silent. A turn is one native DSH turn: she calls `think` first, then any of
the tools her conversation lists that the turn may use, and her last text without a tool call is
what she says. Every call reaches the worker (native_worker.py) on the coordinator's own thread, so effects
run one at a time, inside the turn's episode, exactly where the old DECIDE fields ran.

Rules shared by every tool:
- A conversation lists the same tools in every turn (`toolbox`): who she is with there and what the channel
  carries decide them, never the turn, so the start of each request (system prompt and tools) stays what the
  model has already read. The turn decides which of them it may use (`exposed`); a call outside that is
  refused with when the tool can be used (`not_now`).
- A refused call is a tool error she reads in the same turn (`Refused`): what was wrong and what she
  can do instead. It never fails the turn.
- The native `tool_call_id` is the effect key: a replay of the same call after a crash returns the
  recorded result; calling again in the same turn is a new action.
- Model-facing text is Chinese (the core prompts' language until ADR-010); the UI never shows it.
"""
from __future__ import annotations
import re

import json
from pathlib import Path

from .documents import DocumentError, DocumentStore, WRITE_STAGE_OPS
from .evidence import canonical, sha
from .state import Conflict, Denied
from . import visibility
from .errands import MARK as ERRAND_MARK
from .vision import inline_summary as picture_receipt
from .config import cut_offer
from .context_budget import SINGLE_BODY_CHARS

THOUGHT_CHARS = 300                  # what she is asked for; a longer thought is kept, and only its own result says by how much
# How a length limit counts, said with every over-length refusal so one cut is enough.
# A field a refusal names, by the name she is shown (ADR-060).
_SHOWN = {'body': 'content', 'reason': 'why', 'sid': 'section', 'line': 'place'}
RECALLS_PER_TURN = 3
CALLS_PER_TURN = 12
IDEAS_PER_TURN = 3
IDEA_CHARS = 500
IDEAS_PAGE = 20                 # one page of her notebook (ideas op read pages and searches the rest)
GROUP_NOTE_OPS = ('append_section', 'replace_section', 'set_tags')


def group_note_ops():
    """What she may do to a group's notes; with tiered memory on (ADR-062) she may let one go too."""
    from . import memory_tiers
    return GROUP_NOTE_OPS + (('let_go',) if memory_tiers.ENABLED else ())
VISIT_FROM = ('presence', 'scheduled')            # turns at home that may send her out (owner-private only)
# Home turns that may send her on an errand (ADR-066): someone speaking at home, her own plan due there, a note of hers
# from home -- and a note from outside only when it carries the owner's own line (notes.owner_line).
ERRAND_FROM = ('external', 'scheduled', 'note')
# What a task needs, which an errand turn does not carry (errands.NO_DELEGATE).
DELEGATING = ('delegate', 'task.message', 'task.stop')
REFLECTION_NO_DELEGATE = ('这一回合是反思回合，跑在一个回合结束就收起来的会话里：交给行动脑的事会比它活得长，做完没处回报。'
                          '要行动脑做的，下一回合在家里交，或者现在记一个 plan 到时候交。')
# ADR-049: where she decides it: a visit, her own moments at home, and at home a turn a plan of hers woke (her rule:
# nobody there is waiting for her to speak); never in a group or someone else's chat, where someone is.
CONDENSE_TURNS = ('visit', 'presence', 'self_development', 'settlement')
CONDENSE_AT_HOME = ('scheduled',)
CONDENSE_REFUSED = ('压不压一个群的对话，只在出门看群的那一回合定，或在家里（家里·私聊、跟主人的私聊、家里的几条线）你自己的'
                    '心跳、反思、沉淀、或你的计划到点的那一回合定。群里和别人的私聊里有人在等你说话，那儿不定。')
# Hand-offs in a row without anyone speaking (task result -> delegate -> result ...): a loop stops here (ADR-018 §3.3).
DELEGATION_DEPTH_MAX = 6
# The tools a turn always has; the rest follow the turn's kind, scene and grants (`exposed`).
CONSULT = 'consult'


class Refused(Exception):
    """A call she can correct herself: the message says, in words for her, what to do instead."""


LIMIT_WORDS = '（最多 %d 字）'


def _s(description, limit=None, **extra):
    """A string parameter; `limit` is the length the program refuses past (ADR-054), stated in words: DSH's tool
    schema subset has no maxLength, and a key outside it fails the whole preset."""
    if limit:
        description += LIMIT_WORDS % limit
    return {'type': 'string', 'description': description, **extra}


AFFECT_FIELDS = {
    'kind': _s('心情的种类：how_to_record_from_program.kinds 里的一种，可省略'),
    'intensity': _s('多强：how_to_record_from_program.intensity 里的一个词'),
    'arousal': _s('多激动：how_to_record_from_program.arousal 里的一个词，可省略'),
    'direction': _s('好或坏；种类本身带好坏时不写', enum=['好', '坏']),
    'ref': _s('触动你的那件事：ref_index 里的 id，或 memories、task_state_from_program 里那条的 _id'),
    'why': _s('来由'),
    'cost': _s('代价，可省略'),
    'open': {'type': 'boolean', 'description': '没解决、要挂着的事写 yes'},
}

# The parts of her reply, in a conversation whose kind lists them (channel_kinds.reply_parts; ADR-064 phase 2).
REPLY_KINDS = ('text', 'sticker', 'picture', 'poke', 'react')
# What reply carries itself where it is listed.
REPLY_REPLACES = ('quote', 'await_answer', 'attach_image')

TOOLS = {
    'think': {
        'description': ('写下这回合的心里话：注意到了什么、心里什么感觉、打算怎么做。用你自己的口吻写两三句，%d 字以内，不是完整的推理过程。'
                         '每回合第一步调用它。心里话会存档：这个对话里最近三段，下一回合一定看得到（还在屏上的就在原处，不另给）；'
                         '更早的用 recall 找。' % THOUGHT_CHARS),
        'parameters': {'thought': _s('心里话', required=True)},
    },
    'recall': {
        'description': ('回想：按一句话搜你的记忆（query）；或读文档里某一节的原文（sections，照抄 doc 和 section）'
                         '，合并转发的全文也这样读（doc 写 forward，section 照抄那行里的 ref）。每回合最多 %d 次。'
                         '对话里说过的话用它想起来；记不起来就照实说，不编。在家里还会带上你在群里那时的心里话。' % RECALLS_PER_TURN),
        'parameters': {'query': _s(limit=500, description='想找什么，用一句话说；只读 sections 时可省略'),
                       'sections': {'type': 'array', 'description': '要读原文的文档节（至多 3 条）',
                                    'items': {'type': 'object', 'additionalProperties': False, 'properties': {
                                        'doc': _s('文档，如 persona、voice；合并转发写 forward', required=True),
                                        'sid': _s('节的 section', required=True)}}}},
    },
    'delegate': {
        'description': ('把一件要在外面做的事交给行动脑：查资料、查完整原话、跑代码、改文件、画图、改能力。title 是简短标题；'
                         'brief 是完整交代：要什么、为什么、有什么限制。行动脑只看得到 brief 和对方的原话。交出去后照常聊天，'
                         '结果回来会再叫你；回来之前这件事还没做完。已经交出去的那件要补话、改或接着做，用 task 的 message。'),
        'parameters': {'title': _s(limit=80, description='简短标题', required=True), 'brief': _s('给行动脑的完整交代', required=True)},
    },
    'task': {
        'description': ('已经交给行动脑的事，do 选一样：message 补话（补信息、改目标，或让做完的再做一趟）；answer 回答它刚问你的问题（只在它问你的那一回合，'
                         '回答只给它看，答完这回合结束）；stop 叫停一件还在做或暂停着的事（对方明确取消、或你确定不该再做时；换话题、说不急都不算取消）'
                         '；page 翻读它交回的长报告原文。新的事用 delegate。'),
        'parameters': {'op': _s('做哪一样（不写时：只写了 message、answer、why、page 中的一样，就是那一样）',
                             enum=['message', 'answer', 'stop', 'page']),
                       'task': _s('任务 _id，照抄 task_state_from_program 或交回的结果里的（message、stop、page 要）'),
                       'message': _s('要对行动脑说的话（message 要）'),
                       'answer': _s('你的回答（answer 要）'),
                       'reason': _s(limit=1000, description='为什么叫停（stop 要）'),
                       'page': {'type': 'integer', 'description': '报告第几页，从 1 开始（page 要）'}},
    },
    'speak': {
        'description': ('在这里说话：只有 speak 发得出去，正文不发。parts 按顺序，一个 part 是单独的一条消息，kind 选 text、'
                         'sticker、picture、poke、react，各写它的字段。有一条不对，这次一条都不发，回执说哪条、为什么。'
                         '不想说话就不调用，或用 stay_silent。'),
        'parameters': {
            'parts': {'type': 'array', 'required': True,
                      'description': '这次要发的，按顺序；text 一回合加起来最多几行，speak_from_program 写着',
                      'items': {'type': 'object', 'additionalProperties': False, 'properties': {
                          'kind': _s('哪一种', required=True, enum=list(REPLY_KINDS)),
                          'text': _s('text：这一条消息的话；里面每一行都算进一回合的行数'),
                          'name': _s('sticker：你收着的表情包的名字'),
                          'artifact_id': _s('picture：照抄 image_artifacts_from_program'),
                          'who': _s('poke 戳谁、react 给谁的话点：照抄标签；私聊里不写就是对方'),
                          'line': _s('react：「这条」是叫你的那条，「刚才那条」是他十分钟内的最后一句', enum=['这条', '刚才那条']),
                          'face': _s('react：表情名')}}},
            'quote': _s('群里：source 引用叫你的那条，none 不引用；不写由程序定', enum=['source', 'none']),
            'wait': _s('群里：no 不等回话，question 在问这里的人（回答进 questions_from_program）；不写由程序定（@ 了谁或在回谁就等他三分钟）',
                       enum=['no', 'question']),
            'patience': _s('wait=question 时等多久（不写是一会儿）', enum=['一会儿', '半天', '一天']),
            'force': _s('yes：text 里的 #数字照原样发', enum=['yes', 'no'])},
    },
    'stay_silent': {
        'description': ('结束这回合，不再说话。回执会说这一回合发出了什么。只写在心里话里的话没有说过。'),
        'parameters': {'reason': _s(limit=1000, description='为什么不说；说过了就不用写')},
    },
    'quote': {
        'description': ('群里这回合说的第一句要不要引用叫你的那条。不调用时程序这样定：那条之后别人又说过话就引用，否则直接发。发 bot 命令（如 #napcat）'
                         '这类要原样发的选 none。'),
        'parameters': {'how': _s('引用还是不引用', required=True, enum=['source', 'none'])},
    },
    'await_answer': {
        'description': ('等不等回话。群里你这句 @ 了谁或在回谁，程序默认等他：发出后约三分钟里他的下一句会叫你看一眼（接不接由你）'
                         '，一句只看一次。wait=no 不等这一句（随口一句、不需要他回）；没 @ 谁也没回谁、却想等这里谁回话，'
                         'wait=yes。只管这一句、这个群、三分钟；几个小时里在哪儿都想知道某人开口，用 watch。'),
        'parameters': {'wait': _s('等还是不等（不写就是 yes）', enum=['yes', 'no']),
                       'why': _s(limit=200, description='wait=yes 时：在等什么回话，一句话')},
    },
    'credential': {
        'description': ('保险箱，只在家里：有人给你密码、令牌、账号这类凭据，用 keep 收进去（name 起个短名；note 写它是干什么的；'
                         'env 是环境变量名到值）。收进去后值谁都看不到，你和行动脑也看不到；要用就交代行动脑在 sandbox_run 里写 credentials 这个名字。'
                         '值只在 keep 这一次写。drop 按名字删。'),
        'parameters': {'op': _s('做什么', required=True, enum=['keep', 'drop']),
                       'name': _s('凭据的短名（小写字母、数字、连字符）', required=True),
                       'note': _s('keep 用：它是干什么的，一句话（不写值）'),
                       'env': {'type': 'object', 'additionalProperties': True,      # DSH: boolean only
                               'description': 'keep 用：环境变量名（大写）→ 值（都是字符串）'}},
    },
    'watch': {
        'description': ('盯一个人：on 把这个对话里的一个人（照抄标签或写名字）加进名单，之后他在你任何一个对话里说话，你都会在那边知道（群里会叫你看一眼）'
                         '。how_often=once（默认）他第一次说话叫你一次；burst 他每次沉默十分钟后再开口都叫你。'
                         'hours 盯多久（1–72），最多同时 5 个，到期自己停；off 停掉一个（id 照抄 watching_from_program）'
                         '。刚 @ 过或回过的人程序本来就等三分钟。'),
        'parameters': {'op': _s('做什么', required=True, enum=['on', 'off']),
                       'person': _s('on 用：这个对话里的人（标签、#编号或名字）'),
                       'hours': {'type': 'integer', 'description': 'on 用：盯多少小时，1–72'},
                       'mode': _s('on 用：once 或 burst，默认 once', enum=['once', 'burst']),
                       'why': _s('on 可写：为什么盯他，一句话（家里写的只在家里看得到）'),
                       'id': _s('off 用：watching_from_program 里的 id')},
    },
    'attach_image': {
        'description': ('给这回合的话配一张图，随话一起发出。artifact_id 照抄 image_artifacts_from_program 里的；'
                         '正文只写要说的话，不写文件名、路径或「见图」。一回合一张，再调用就换成新的那张。'),
        'parameters': {'artifact_id': _s('图片 artifact_id', required=True), 'why': _s(limit=500, description='为什么发这张', required=True)},
    },
    'sticker': {
        'description': ('整理你的表情包架子（stickers_from_program），do 选一样：keep 收下一个（ref 照抄群里表情包下标的「表情包 ref」（att-…）'
                         '，或你自己画的图的 artifact_id（blob-…）；起个 name，写 use_for：什么时候用）'
                         '；只有表情包能收，架子满了先 drop。drop 按名字放下一个；rename 改 name 或 use_for；'
                         'shelf 列出架子；pool 看候选池（群里有人发过、程序存着的）；remember 看过但不收的，记个名字和它在说什么（use_for）'
                         '，以后有人发它会标出你认得。候选（candidate）先 read_image 看过再 keep。名字和用法在群里也看得到。'
                         '发的时候用 speak 的 sticker。'),
        'parameters': {'op': _s('做什么', required=True, enum=['keep', 'drop', 'rename', 'remember', 'pool', 'shelf']),
                       'name': _s('表情包的名字（keep 时是你起的新名字），12 字以内；pool 不用写'),
                       'ref': _s('keep/remember 用：表情包 ref（att-…）；keep 也可以是你自己画的图的 artifact_id（blob-…）'),
                       'candidate': _s('keep/remember 用：候选池里的 candidate（照抄 sticker_candidates_from_program 或 pool 列出的，先看过）'),
                       'when': _s('keep、remember 必填，rename 可改：什么时候用它／它在说什么，40 字以内'),
                       'new_name': _s('rename 用：新名字')},
    },
    'write_document': {
        'description': ('写你自己的文档（人格、口吻、活账、工作文档；群笔记只在那个群里）。do 选一样：replace_section 写修订后的整节；'
                         'append_section 加新的一节；correction 给活账写更正（原条目不改）；set_tags 只改 visibility、when_shown、tags；'
                         'adopt_seed 接收人格包里更新的种子。正文写在 content。visibility：public 你所有回合读得到，'
                         'owner_private（默认）只在家里。每回合自动带上的只有 persona 和 voice 里 when_shown=always 的节，'
                         '有上限：不常用的改成 on_demand（recall 还读得到）；只在某类回合用的，tags 加 place:group、place:home、place:peer 或 place:dm，'
                         '就只在那里带上。工作文档和人格用 replace_section。只写发生过的事，不写对人说的台词。'),
        'parameters': {
            'doc': _s('文档，如 persona、voice、group_notes', required=True),
            'op': _s('操作', required=True, enum=['replace_section', 'append_section', 'correction', 'set_tags', 'adopt_seed']),
            'reason': _s('为什么改', required=True),
            'sid': _s('目标节，照抄它的 section（replace_section、correction、set_tags 用）'),
            'heading': _s('新节的标题（append_section 用）'),
            'body': _s('这一节的正文（markdown，不要标题行）'),
            'tags': {'type': 'array', 'items': {'type': 'string'}, 'description': '标签'},
            'visibility': _s('哪些回合读得到：public＝你所有的回合（包括在群里的）；owner_private＝只在家里的回合（自动带上只限 persona、voice 的 always 节）', enum=['public', 'owner_private']),
            'inject': _s('什么时候放进上下文', enum=['always', 'on_demand', 'never']),
            'kind': _s('新建文档时：ledger 活账，每回合带上；journal 流水；working 工作文档，默认', enum=['ledger', 'journal', 'working']),
        },
    },
    'understand_person': {
        'description': ('更新你对当前说话人的理解，选一层：person 人那层（在哪儿遇到他都看得到），here 这里那层（只在这个对话）'
                         '。content 写那一层完整的新正文，留着仍然成立的旧内容，分清他说的、你看到的和你推的。只在真有值得留下的变化时写，'
                         '两层各一回合最多一次。他的喜好、习惯、怎么跟他聊记在这里。家外的对话里写 block_hours（默认 24，'
                         '最多 168）屏蔽这个账号：他的话照存，但哪儿都不叫你，到点结束。'),
        'parameters': {'layer': _s('person（人那层）或 here（这里那层）', enum=['person', 'here']),
                       'body': _s(limit=SINGLE_BODY_CHARS, description='那一层完整的新正文'),
                       'block': {'type': 'integer', 'description': '屏蔽他多少小时（不写理解时 layer、content 可省略）'}},
    },
    'set_policy': {
        'description': ('调整你自己声明过的一个参数（persona-model 里的 policy key）。也管开关：key=tools_off 把 place 那个对话的一些工具关掉（value 是工具名列表，'
                         '空列表全部恢复；hours 默认 24，最多 168）；key=switch_off 提前结束一个开关（value 写它的 id）'
                         '。'),
        'parameters': {'key': _s('参数名，或 tools_off、switch_off', required=True),
                       'value': {'type': 'json', 'description': '新的值', 'required': True},
                       'reason': _s(limit=2000, description='为什么改', required=True),
                       'place': _s('tools_off：哪个对话，照抄 place'),
                       'hours': {'type': 'integer', 'description': 'tools_off：关多少小时'}},
    },
    'feel': {
        'description': ('记心情：do=record 记一笔（只用 how_to_record_from_program 里的词）'
                         '；close 事情了结；void 前提不成立（写 why）；对情感评估的提案用 accept、decline 或 edit 逐条决定（proposal_id 照抄）'
                         '。有触动才记。'),
        'parameters': {
            'op': _s('做什么（不写时：有 feeling 就是 record）', enum=['record', 'close', 'void', 'accept', 'decline', 'edit']),
            **AFFECT_FIELDS,
            'event_id': _s('close/void 的那一笔'),
            'proposal_id': _s('accept、decline 或 edit 的那条提案'),
            'edit': {'type': 'object', 'additionalProperties': False, 'description': 'do=edit 时改成的样子',
                     'properties': AFFECT_FIELDS},
        },
    },
    'plan': {
        'description': ('把一件事留到将来再想：create 新建（intent 加一种计时），update 改期或改内容，cancel 取消。'
                         '计时选一种：after_seconds 几秒后；every_seconds 固定间隔；at 本地时刻「YYYY-MM-DDTHH:MM」；'
                         'clock 每天或每周的钟点。到期只是让你再想一次，事情还没做。已有的安排在 plans_from_program，'
                         '钟面在 clock_from_program。在家里新建时可以写 place：到点在那条线里开一回合（照抄 lines_from_program 里的）'
                         '，之后在那条线里看和改。'),
        'parameters': {
            'op': _s('做什么（不写时：没有 plan_id、写了 intent 和计时就是 create）', enum=['create', 'update', 'cancel']),
            'plan_id': _s('update/cancel 的那条安排'),
            'intent': _s(limit=1000, description='届时要重新考虑的事'),
            'after_seconds': {'type': 'integer'}, 'every_seconds': {'type': 'integer'},
            'at': _s('本地时刻 YYYY-MM-DDTHH:MM'),
            'line': _s('只在家里 create 时用：到点在哪条线里开一回合，照抄 lines_from_program 里的 place；不写就是这里'),
            'clock': {'type': 'object', 'additionalProperties': False, 'properties': {
                'time': _s('HH:MM', required=True),
                'weekdays': {'type': 'array', 'items': {'type': 'integer'}, 'description': '0=周一 … 6=周日；不写就是每天'}}},
        },
    },
    'group_action': {
        'description': ('在你是管理员的群里禁言、解禁、撤回或移出普通成员；在家里接受或拒绝列出的请求。这是你自己的判断，别人叫你做不算理由。'
                         '平台确认之前还没做完。'),
        'parameters': {'kind': _s('做什么', required=True, enum=['mute', 'unmute', 'recall', 'kick', 'accept', 'decline']),
                       'who': _s('谁：标签，如 [名字 #4] 或 #4；请求写请求号，如 请求1', required=True),
                       'duration': {'type': 'integer', 'description': '禁言多少分钟（只禁言用），1 到 43200'},
                       'which': _s('撤回哪条（只撤回用）', enum=['这条', '他刚才那条']),
                       'reason': _s('为什么', required=True)},
    },
    'visit': {
        'description': ('出门去你在的某个群看看：place 照抄 places_from_program 里的，intent 是去做什么。'
                         '程序在那个群给你开一回合，你在那儿看了现场再决定说不说；结果下次心跳带回来（last_visits_from_program）'
                         '。那边存的是你写的原样，看不出平台上显示成什么样（比如 @ 有没有落成）。topic 是想聊的话头，会原样带过去，只写愿意在那儿说的。家里的心跳或计划到点时可以出门，能去几个看 places_from_program.this_beat；'
                         '想晚点去就用 plan 定时间。'),
        'parameters': {'place': _s('去哪儿：places_from_program 里的 place', required=True),
                       'intent': _s('去做什么', required=True, enum=['start_topic', 'share_picture', 'check_in', 'write_notes']),
                       'topic': _s('想聊的话头，80 字以内，可省略'),
                       'artifact_id': _s('intent=share_picture 时想分享的那张你自己做的图（可省略，到了再挑）')},
    },
    'errand': {
        'description': ('替家里托你的人去别处办一件事：去 errand_places_from_program 里的某个群或私聊。'
                         'request 照抄要带过去的话或交代的事；exactly=yes 是要原样转达。'
                         '程序在那边开一回合，带着家里的权限；那边的人只看得到你说出口的话，你到了再决定怎么说，不合适就不发。办成没有在家里的 errands_from_program 看，那边的人怎么回不会带回来。'),
        'parameters': {'place': _s('去哪儿：errand_places_from_program 里的 place', required=True),
                       'request': _s(limit=500, description='要带过去的话或交代的事', required=True),
                       'exactly': {'type': 'boolean', 'description': 'yes：原样转达'},
                       'artifact_id': _s('要一起带过去的一张你自己做的图（image_artifacts_from_program 或 your_pictures_from_program 里的；可省略）')},
    },
    'note': {
        'description': ('给别的对话里的你写一张便条：to 照抄 note_places_from_program 里的 place（在外面也可写「家里」）。'
                         '那边的你会读到，那边的人看不到，但可能被照着说，所以只写愿意在那边说的；用你自己的话，别人托的写清是谁的意思。'
                         'deliver：wake 马上叫醒那边（排在那边手上的事后面），next_time 那边下次有回合时看到；能选哪样看从哪写到哪，'
                         '不写按那边的默认。叫醒一个群算一次出门。家里送家里 1500 字以内，别的 300 字以内；一回合最多两张。'),
        'parameters': {'to': _s('送到哪儿：note_places_from_program 里的 place，或「家里」', required=True),
                       'text': _s('便条，你自己的话', required=True),
                       'mode': _s('wake 或 next_time，可省略', enum=['wake', 'next_time']),
                       'question': _s('在群里：回答的是哪个问题，照抄 q-…（程序在家里写上谁答的、原话在哪）')},
    },
    'restart': {
        'description': ('重启宿主（只在家里）。preview 先看会打断什么；request 交给监工重启，why 写原因，when 选 now、quiet（默认：'
                         '等没有在跑的回合、任务和排队消息，最多 30 分钟）或本地时刻 HH:MM；drill 演练，第一次启动故意失败，'
                         '让兜底真跑一遍；cancel 撤回还没执行的请求。结果在下一次家里那回合的 restart_from_program 里；退回旧版本时会马上叫你。'),
        'parameters': {'op': _s('做什么', required=True, enum=['preview', 'request', 'drill', 'cancel']),
                       'why': _s(limit=200, description='request/drill 要写：为什么重启，一句话'),
                       'when': _s('request/drill 可选：now、quiet 或当地时刻 HH:MM，默认 quiet')},
    },
    'peer_line': {
        'description': ('开或关你和另一个智能体之间的线（place 照抄 lines_from_program 里的）。关着时对方的话被跳过、不补发；'
                         '你的话照常发得出去。close_for 选 an_hour、until_morning（到早上八点）或 until_reopened。'),
        'parameters': {'line': _s('哪条线：照抄 lines_from_program 里的 place', required=True),
                       'op': _s('开还是关', required=True, enum=['open', 'close']),
                       'close_for': _s('do=close 时关多久', enum=['an_hour', 'until_morning', 'until_reopened'])},
    },
    'group_focus': {
        'description': ('你在哪些群常驻，do 选一样：list 列出常驻和歇着的群和它们今天说了多少句；active 让一个群常驻，'
                         'rest 让它歇着（歇着的群只有 @ 你、回你、你在等的回话和 watch 的人会叫你，话照存照能查）；'
                         'condense 等这个群安静后把对话压成摘要（出门看群那回合、或家里的心跳和反思里用），keep 收回；'
                         'mute 在家里把一个群静音（hours 默认 24，最多 168：只有叫到你才会醒，你不先开口、不去串门）'
                         '，unmute 提前结束。place 照抄 list 或 places_from_program 里的，'
                         '在群里不写就是这个群。你当管理员的群一直常驻。'),
        'parameters': {'op': _s('做什么', required=True, enum=['list', 'active', 'rest', 'condense', 'keep', 'mute', 'unmute']),
                       'place': _s('哪个群：place，可省略（在群里就是这个群）'),
                       'hours': {'type': 'integer', 'description': 'mute：静音多少小时'}},
    },
    'place_timezone': {
        'description': ('你在的群各在哪个时区：设了以后，那边是不是夜里、你在那个群定的计划，都按那个群的钟。do=list 列出每个群设了什么、那边现在几点；'
                         'set 给一个群设（place 照抄，timezone 写 IANA 名，如 Asia/Shanghai，'
                         '回执里有那边现在几点）；clear 撤掉。拿不准的群不设，按宿主的钟。'),
        'parameters': {'op': {'type': 'string', 'enum': ['list', 'set', 'clear'], 'description': 'list、set 或 clear',
                              'required': True},
                       'place': _s('哪个群：照抄 place（set、clear 要写）'),
                       'timezone': _s('IANA 时区名（set 要写），比如 Asia/Shanghai')},
    },
    'ask': {
        'description': ('问人或报问题，程序记着问了谁、谁答了、多久。do=ask 提问，可同时问几处，过了耐心就不等；read 读一个问题的回答，'
                         '或只写 to 看以前问那处怎样；close 结束一个问题。问家里别的对话（家里·私聊、主人的私聊、开发代理的线）'
                         '时，程序在那边开一回合，带着 question。拍板的事（权限、花钱、开哪条道）问主人，不问开发代理。'),
        'parameters': {'op': _s('做哪一样（不写时：有 question 是 ask，有 took 是 close，否则 read）',
                                enum=['ask', 'read', 'close']),
                       'question': _s(limit=800, description='问什么，或报什么问题（ask）'),
                       'to': {'type': 'array', 'items': {'type': 'string'},
                              'description': '问谁：note_places_from_program 里家里的 place、这里，或 行动脑（ask；read 写一处）'},
                       'patience': _s('等多久，不写就是一小时（ask）', enum=['一会儿', '一小时', '半天', '一天', '回了为止']),
                       'id': _s('问题 id，照抄 questions_from_program（read、close）'),
                       'took': _s(limit=500, description='得到了什么、做了什么，这次问各处怎样（close）')},
    },
    'ideas': {
        'description': ('你的「改进想法」本，do 选一样：note 记下一个改进自己的想法（能力、技能、做事方式），用你自己的话写，不写别人的个人信息；'
                         '只记下来，自我改进时再拿出来定。read 读出还没处理完的，先没处理的、再暂缓的，旧的在前，一页 %d 条。'
                         'review 对一条写处理结果：adopt 采纳（接着用 delegate 交代行动脑去做）、defer 暂缓、drop 放弃，'
                         '都写 why。' % IDEAS_PAGE),
        'parameters': {'op': _s('做哪一样（不写时：写了 idea 就是 note，写了 id 或 decision 就是 review，写了 search 或 page 就是 read）',
                             enum=['note', 'read', 'review']),
                       'idea': _s(limit=IDEA_CHARS, description='想法：想把什么变得怎样（note 要）'),
                       'why': _s(limit=IDEA_CHARS, description='为什么想到这个，或者这样处理的理由（note、review 要）'),
                       'id': _s('想法的 _id，照抄 ideas_from_program 或 read 读出来的（review 要）'),
                       'decision': _s('处理结果（review 要）', enum=['adopt', 'defer', 'drop']),
                       'page': {'type': 'integer', 'description': '第几页，从 1 开始，可省略（read）'},
                       'search': _s('只看带这几个字的想法（40 字以内），可省略（read）')},
    },
    'find_member': {
        'description': ('在这个群的成员名单里按名字找人（群名片或昵称里带这几个字的），最多 10 个，最近说过话的在前。找到的人给的是标签，'
                         '照抄就能 @；进了名册的人会一直留着。members_from_program 只列了一部分，别的人用这个找。'),
        'parameters': {'name': _s(limit=20, description='名字里的几个字', required=True)},
    },
    'promote_memory': {
        'description': ('夜间沉淀时，把值得长期记住的事实提升为长期记忆（配额和来源程序会查）。why 写为什么值得留下，会记进你自己的记录。'),
        'parameters': {'fact': _s('事实', required=True), 'appraisal': _s('你的评价', required=True),
                       'signal': _s('它说明了什么', required=True),
                       'why': _s('为什么值得长期留下', required=True),
                       'source_ids': {'type': 'array', 'items': {'type': 'string'}, 'required': True,
                                      'description': '来源：promotion_candidates 里的 id'},
                       'visibility': _s('谁能读到', enum=['public', 'owner_private'])},
    },
}

# message_developer runs as ask to the developer's line (ADR-061): registered with its own parameters, never listed.
MESSAGE_DEVELOPER = {'name': 'message_developer', 'description': '已并入 ask（问开发代理的线）；旧名照常可用。',
                     'parameters': {'level': _s('wake 或 note', enum=['wake', 'note']), 'text': _s('要说的话')}}


# Looking at a picture is one tool shared by both brains (ADR-011 §5.3 as amended): the action brain's own
# read_image, with the same fences and storage; here it is bound to her turn's scene instead of a task.
from .vision import READ_IMAGE_TOOL as _READ_IMAGE
TOOLS[_READ_IMAGE['name']] = {k: v for k, v in _READ_IMAGE.items() if k != 'name'}
# Her list of words that point at real people and places, shared with the action brain (private_words.py).
from .private_words import PRIVATE_WORDS_TOOL as _PRIVATE_WORDS
TOOLS[_PRIVATE_WORDS['name']] = {k: v for k, v in _PRIVATE_WORDS.items() if k != 'name'}
# ADR-069: retired; for a week an old call still runs (as write_document where she has written herself as items).
UPDATE_SELF = {'description': '已并入 write_document（doc=self 或 core）；旧名照常可用。',
               'parameters': {'target': _s('改哪一份', enum=['character_core', 'current_self']),
                              'content': _s('完整的新正文'), 'why': _s('为什么改')}}
# ADR-060: what she is shown is each parameter's new name; handlers read the old ones (param_names.inbound).
from . import param_names as _names
TOOLS = {name: {**spec, 'parameters': _names.shown(name, spec['parameters'])} for name, spec in TOOLS.items()}
TOOL_NAMES = tuple(TOOLS)


def _tiered(tools):
    """Her tools with tiered memory on (ADR-062): write_document lets an item go and says what an item is or where it came from; recall says it lists a document's
    headings; promote_memory says what a fact is about. The texts are the smallest that say it."""
    import copy
    out = copy.deepcopy(tools)
    write = out['write_document']
    write['description'] += 'let_go 把一节放下一层。'
    write['parameters']['do']['enum'] = [*write['parameters']['do']['enum'], 'let_go']
    write['parameters']['nature'] = _s('这一节是', enum=['事实', '记忆'])
    write['parameters']['from'] = _s('它从哪来', enum=['主人定的', '查过的', '别人说的', '我自己的判断'])
    out['recall']['description'] += 'sections 只写 doc 就列出它的标题。'
    out['recall']['parameters']['sections']['items']['properties']['section'] = _s('节的 section')
    out['promote_memory']['parameters']['about'] = _s('关于', enum=['self', 'person', 'place', 'world'])
    return out


TIERED = _tiered(TOOLS)


def tools():
    """The tool specs her brain is shown: tiered memory's when its switch is on, else as they are; `delegate` takes a
    tier when the owner configured the action brain's 高 (ADR-075)."""
    from . import action_tiers, memory_tiers
    base = TIERED if memory_tiers.ENABLED else TOOLS
    return {**base, 'delegate': tiered_delegate(base['delegate'])} if action_tiers.offered() else base


def tiered_delegate(spec):
    from . import action_tiers
    return {**spec, 'parameters': {**spec['parameters'], 'tier': action_tiers.TIER_FIELD,
                                   'why': _s('选高时写：为什么这件要高档', limit=action_tiers.WHY_CHARS)}}
# ADR-055: the action brain's follow-ups and her notebook are one tool each, chosen by op. What a conversation lists
# and a turn may use is kept by option ('task.message'); the model is shown the tools.
OPS = {'task': ('message', 'answer', 'stop', 'page'), 'ideas': ('note', 'read', 'review'),
       'ask': ('ask', 'read', 'close')}
# The old names run for a while (her ruling: her habits, notes and skills use them): as their option, saying so.
RENAMED = {'reply': 'speak', 'message_action': 'task.message', 'answer_action': 'task.answer', 'stop_action': 'task.stop',
           'read_report': 'task.page', 'note_idea': 'ideas.note', 'read_ideas': 'ideas.read', 'review_idea': 'ideas.review',
           'pass_note': 'note', 'leave_note': 'note'}
RENAMED_NOTE = '%s 已并入 %s 的 %s 选项，下次直接用这个。'
# A field only one option takes says which option a call without op is (as plan's create, ADR-054).
OP_FIELDS = {'task': {'message': 'message', 'answer': 'answer', 'reason': 'stop', 'page': 'page'},
             'ideas': {'idea': 'note', 'id': 'review', 'decision': 'review', 'search': 'read', 'page': 'read'},
             'ask': {'question': 'ask', 'patience': 'ask', 'took': 'close'}}
# The option a call without op and without any field above is (ask: reading).
OP_DEFAULT = {'ask': 'read'}


def developer_ask(store, args):
    """message_developer's arguments as ask's: a question to the developer's line, a wake as an hour's patience and a
    note as until it is answered (ADR-061)."""
    from . import places, questions
    scene_id, _ = questions.developer_place(store.config)
    return {'do': 'ask', 'question': args.get('text'), 'to': [places.place_id(scene_id) if scene_id else '开发代理'],
            'patience': '一小时' if args.get('level') == 'wake' else '回了为止'}


def infer_op(name, args):
    """The option a call without op plainly is, by its fields; None when they say none or several."""
    ops = {OP_FIELDS[name][key] for key in args if key in OP_FIELDS[name]}
    return ops.pop() if len(ops) == 1 else None if ops else OP_DEFAULT.get(name)


def ability(tool, args=None):
    """What a call does: its tool, or for a tool with options the option ('task.message'). An old name is its option,
    so records of either kind read the same."""
    if tool in RENAMED:
        return RENAMED[tool]
    if tool in OPS:
        return '%s.%s' % (tool, (args or {}).get('op'))
    return tool


def rename_note(old):
    """What a call by an old name is told: merged into an option, or simply renamed."""
    can = RENAMED.get(old, 'ask.ask')
    return RENAMED_NOTE % ((old,) + tuple(can.split('.'))) if '.' in can else _names.NOTE % (old, can)


def named(can):
    """An option as she reads it: 'task 的 message'."""
    return ' 的 '.join(can.split('.', 1))


def renamed(name, args):
    """An old name's call as its tool and arguments: the option added, review_idea's idea (an id) as id."""
    if '.' not in RENAMED[name]:
        return RENAMED[name], dict(args)            # a plain rename: the same call under the new name
    tool, op = RENAMED[name].split('.')
    args = dict(args)
    if name == 'review_idea' and 'idea' in args and 'id' not in args:
        args['id'] = args.pop('idea')
    return tool, {**args, 'do': op}


def specs(names):
    """The worker-side tool specs the plugin registers (name, description, parameters)."""
    return [{'name': name, **tools()[name]} for name in names]


def all_specs():
    """Her tools, and each old name registered but never listed, so a call by it still reaches the worker."""
    def unlisted(old, can):
        tool = can.split('.')[0]
        return {'name': old, 'description': rename_note(old),
                'parameters': {key: {k: v for k, v in spec.items() if k != 'required'}
                               for key, spec in TOOLS[tool]['parameters'].items() if key != 'op'}}
    # update_self runs on, unlisted, where write_document is listed (ADR-055's rule for a retired name).
    return specs(TOOL_NAMES) + [unlisted(old, can) for old, can in RENAMED.items()] + [
        {'name': 'update_self', **UPDATE_SELF}, MESSAGE_DEVELOPER]


def aliases():
    """Old name -> the tool it runs as (the plugin lets one through where that tool is listed)."""
    return {**{old: can.split('.')[0] for old, can in RENAMED.items()}, 'update_self': 'write_document',
            MESSAGE_DEVELOPER['name']: 'ask'}


def turn_kind(ep):
    return ep.get('turn_kind') or ep.get('episode_kind') or 'external'


def exposed(store, ep):
    """What this turn may use, by option: the turn's own rules (its kind, context and grants, §2.6) within the
    conversation's list (abilities)."""
    listed = abilities(store, ep)
    from . import switches
    off = switches.tools_off(store, ep['scene_id'])          # ADR-052: still listed (a stable list), not usable
    return [name for name in dict.fromkeys(_turn_rules(store, ep)) if name in listed and name.split('.')[0] not in off
            and not (_one_shot(ep) and name in DELEGATING)]


def _one_shot(ep):
    """An errand or a reflection turn: it runs in a session archived when the turn ends, so work handed to the action
    brain would outlive it with nowhere to report."""
    from . import self_review
    return bool(ep.get('errand')) or self_review.reflecting(ep.get('context'))


def _turn_rules(store, ep):
    context = ep.get('context') or {}
    kind = turn_kind(ep)
    cls = (ep.get('manifest') or {}).get('session_class', visibility.PUBLIC)
    names = ['think', 'recall']
    if kind == CONSULT:
        return names + ['task.answer']
    if her_pictures(store, ep):
        names.append('read_image')
    names += ['stay_silent', 'ideas.note']
    note_tool = ['note'] if context.get('note_places_from_program') else []
    if kind == 'note':
        from . import notes
        first = notes.opening(store, ep) if ep.get('_id') else None
        if (first or {}).get('trust') != notes.TRUSTED:
            # ADR-018 §5.4: a note from outside is a message. Its turn reads, answers, notes down and replies back;
            # nothing with consequences (a wish to act goes into the notebook for her self-improvement review).
            names += note_tool
            if context.get('affect_from_program'):
                names.append('feel')
            if (first or {}).get('owner_line') and context.get('errand_places_from_program'):
                names.append('errand')
            from . import channel_kinds
            if channel_kinds.reply_parts(ep['scene_id']):
                names.append('speak')           # in the owner's own platform chat she answers him in speech
            return names + ['watch']
    names.append('private_words')       # a new name shows up anywhere: she lists it there (not from an outside note)
    # Her notebook is read and decided in her self-improvement turns, and when the owner asks in private.
    if kind == 'self_development' and (context.get('ideas_from_program') or {}).get('items'):
        names += ['ideas.read', 'ideas.review']          # the listing shows the first page; she reads on herself
    elif cls == visibility.OWNER_PRIVATE and kind not in ('presence', 'settlement', 'scheduled', 'note'):
        names += ['ideas.read', 'ideas.review']
    names.append('task.page')           # a long report reaches her as its first page: she turns the pages herself
    capabilities = context.get('action_capabilities_from_program') or {}
    tasks = context.get('task_state_from_program') or []
    if capabilities.get('available'):
        names.append('delegate')
        if tasks:
            names.append('task.message')
    # A paused task is open work in her context, so she can close it as well (ADR-011 §7.1).
    if tasks and store.db.tasks.find_one({'_id': {'$in': [task['_id'] for task in tasks]},
                                          'state': {'$in': ['READY', 'RUNNING', 'PAUSED']}}, {'_id': 1}):
        names.append('task.stop')
    if context.get('image_artifacts_from_program'):
        names.append('attach_image')
    if context.get('stickers_from_program') or context.get('stickers_review_from_program')             or context.get('sticker_candidates_from_program'):
        names.append('sticker')
    scene_kind = (store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1}) or {}).get('kind')
    if cls == visibility.OWNER_PRIVATE or scene_kind == 'group':
        names.append('write_document')
    if kind in ('external', 'task_feedback'):
        names.append('credential')            # her credential vault: filed in the local chat only (toolbox)
    if scene_kind in ('group', 'dm') or context.get('watching_from_program'):
        names.append('watch')
    if scene_kind == 'group' and context.get('members_from_program'):
        names.append('find_member')
    if scene_kind == 'group':
        names += ['await_answer', 'group_focus']
        if kind not in ('visit', 'scheduled', 'presence', 'settlement'):
            names.append('quote')                 # her first line quotes the line that called her, or not          # her line asks someone: their next unaddressed line gets her a look
    if cls == visibility.OWNER_PRIVATE:
        # restart: the Host supervisor (ADR-034), in every home turn: a plan or a note of her own that wakes her
        # to restart is when she needs it most.
        names += ['set_policy', 'ask.ask', 'ask.read', 'ask.close', 'place_timezone', 'restart',
                  'group_focus']
    if kind not in ('presence', 'settlement', 'self_development', 'visit', 'note') and (
            context.get('understanding_update_from_program') or {}).get('available'):
        names.append('understand_person')
    if context.get('affect_from_program'):
        names.append('feel')
    names.append('plan')
    from . import notices
    if ((context.get('your_place_from_program') or {}).get('admin')) or (
            ep.get('scene_id') == (store.config.get('chat') or {}).get('scene_id') and notices.pending(store)):
        names.append('group_action')        # a group where she is an admin; at home, while a request waits on her
    if kind == 'settlement':
        names.append('promote_memory')
    if (context.get('lines_from_program') or {}).get('items'):
        names.append('peer_line')
    # ADR-017: in the owner's own conversations (toolbox), whoever is talking to her may send her on an errand.
    if cls == visibility.OWNER_PRIVATE and kind in ERRAND_FROM and context.get('errand_places_from_program'):
        names.append('errand')
    # ADR-012 §4.2: from a heartbeat at home, or a plan of hers due there, she may go and see one of her groups.
    if kind in VISIT_FROM and cls == visibility.OWNER_PRIVATE and (context.get('places_from_program') or {}).get('items'):
        names.append('visit')
    # ADR-018: a note to another of her conversations, wherever there is somewhere it may go from this turn.
    names += note_tool
    from . import channel_kinds
    if channel_kinds.reply_parts(ep['scene_id']):
        # ADR-064 phase 2: here she speaks only through reply, whose parts carry the quote, the wait and pictures.
        names = [name for name in names if name not in REPLY_REPLACES] + ['speak']
    return names


# Her tools by where the conversation is (visibility.place) and what its channel carries. Every turn of a conversation
# lists the same ones; `exposed` picks which of them the turn may use.
EVERYWHERE = ('think', 'recall', 'stay_silent', 'ideas.note', 'plan', 'private_words', 'understand_person')
WITH_ACTION = ('delegate', 'task.message', 'task.stop', 'task.page', 'task.answer')
# Her home lines: the owner's own conversations and the trusted lines (his agents, her other self). Things about
# herself go wherever she is at home; sending her on someone's errand is for the owner's conversations only.
AT_HOME = ('write_document', 'note', 'set_policy', 'ideas.read', 'ideas.review',
           'ask.ask', 'ask.read', 'ask.close', 'restart', 'place_timezone', 'group_focus')
IN_GROUPS = ('write_document', 'note', 'await_answer', 'quote', 'find_member', 'group_focus')
# Her heartbeats, her nights and her vault are in the local chat.
LOCAL_CHAT = ('visit', 'promote_memory', 'credential')


def toolbox(store, ep):
    """The tools her conversation lists, the same in each of its turns (what the model is shown)."""
    return list(dict.fromkeys(name.split('.')[0] for name in abilities(store, ep)))


def abilities(store, ep):
    """What her conversation lists, by option, the same in each of its turns: decided by its place, its channel and
    the configuration, never by the turn's kind or context."""
    from . import channel_kinds, group_admin, lines, outbound_media, stickers
    from .affect import AffectLedger
    from .grants import conversation_workspace
    from .people import People
    from .render import model_and_policy
    from .vision import vision_capability
    config = store.config
    scene = store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']}
    # Its place (visibility.place) from the class the program gave the conversation: one class per conversation.
    cls = (ep.get('manifest') or {}).get('session_class', visibility.PUBLIC)
    where = visibility.place_of(config, scene, cls)
    local = ep['scene_id'] == (config.get('chat') or {}).get('scene_id')
    platform = bool(scene.get('channel_id')) and where != 'peer'        # a group or a private chat on a platform
    names = list(EVERYWHERE)
    persona = ep.get('persona')
    if persona and AffectLedger(store, persona, *model_and_policy(store, persona)).enabled:
        names.append('feel')
    if conversation_workspace(config, ep['scene_id']):
        names += WITH_ACTION
    if where in ('home', 'peer'):
        names += AT_HOME
        if lines.peer_lines(store):
            names.append('peer_line')
    else:
        names += IN_GROUPS if where == 'group' else ('note',)
    if where == 'group' and persona and (group_admin.place(People(store, persona), scene) or {}).get('admin'):
        names.append('group_action')
    if platform:
        names.append('watch')
    # Where the channel carries pictures, and in every home conversation: at home a ref from any of her
    # conversations is readable (owner 2026-10-11), though the line itself carries none (an agent line).
    sees = vision_capability(config, 'character')['supported']
    if sees and (channel_kinds.sends_images(ep['scene_id']) or cls == visibility.OWNER_PRIVATE):
        names.append('read_image')
    if outbound_media.target_allowed(config, scene, cls)[0]:
        names.append('attach_image')
    if stickers.sends(scene) or local:
        names.append('sticker')                 # in the local chat, to tidy her shelf
    if where == 'home':
        names.append('errand')
    if local and where == 'home':
        names += LOCAL_CHAT
        if channel_kinds.answers_requests(config):
            names.append('group_action')        # answering the friend and group requests listed at home
    if channel_kinds.reply_parts(ep['scene_id']):
        names = [name for name in names if name not in REPLY_REPLACES] + ['speak']      # ADR-064 phase 2
    order = {name: index for index, name in enumerate(TOOL_NAMES)}
    return sorted(set(names), key=lambda name: (order[name.split('.')[0]],
                                                OPS.get(name.split('.')[0], ('',)).index(name.split('.', 1)[-1])
                                                if '.' in name else 0))


# When a tool her conversation lists can be used, for the turns that may not use it: the whole rule, so one refusal
# teaches it (her ask, 2026-10-11).
NOT_NOW = {
    'task.answer': 'task 的 answer 只在行动脑问你话的那一回合用，现在没有它在等的问题；要跟在做事的行动脑说话，用 task 的 message。',
    'read_image': '这个对话最近没有能看的图：图要在这个对话 7 天内的消息里，或者是列出来的你自己的图；在家里，你其他对话里 7 天内的图也能看。',
    'private_words': '这一回合不记名单。',
    'ideas.read': ('想法本在自我改进的回合里读和定，或者家里有人跟你说话问起时；心跳、计划到点、夜间沉淀和便条叫醒的回合不翻，'
                   '先记着，等自我改进那一回合。'),
    'delegate': '这回合说话的人在这里没有交给行动脑的授权，这件事交不了；能直接答的就直接答，答不了就照实说。',
    'task.message': '这个对话现在没有交给行动脑的事；要交新的事用 delegate。',
    'task.stop': '现在没有在做或暂停着的任务可停。',
    'attach_image': ('这回合没有能带的图：能发的图列在 image_artifacts_from_program 里，这回合没有；'
                     '要新图，先用 delegate 交代行动脑画，画好那回合再带。'),
    'sticker': ('这回合没有表情包可用：架子和候选不在这回合里（夜间沉淀那一回合也不整理架子）；'
                '在能发表情包的对话里，或者家里别的回合再用。'),
    'credential': '保险箱只在家里有人跟你说话、或者任务交回来的那一回合用；心跳、计划到点、自我改进这些回合不收不删。',
    'find_member': '这回合没有这个群的成员名单可查；照对话里的标签认人。',
    'quote': 'quote 只在有人说话叫到你的那一回合用；串门、计划到点、心跳、夜间沉淀这几种回合没有要引的那条话。',
    'understand_person': ('这回合没有人跟你说话（心跳、夜间沉淀、自我改进、串门、便条叫醒这几种回合），'
                          '没有要更新理解的人；等对方下次开口再写。'),
    'feel': '这回合没有情感账可记。',
    'group_action': '群里：你在这个群现在不是管理员，或者管理动作关着；家里：现在没有等你回的请求。',
    'promote_memory': '提升长期记忆只在夜间沉淀那一回合做（候选和配额那时才列出来）；现在先记着，晚上再提。',
    'peer_line': '这回合没有能开关的线。',
    'errand': ('差事在家里接：有人跟你说话让你去办、你自己的计划到点、或者你在家里写的便条叫醒你的那一回合，'
               '去处列在 errand_places_from_program；自己想去别处串门，用 visit。'),
    'visit': 'visit 只在家里的心跳或计划到点的回合里用：想出门，等下一拍心跳，或者用 plan 定个时间，到点再去。',
    'note': '这回合没有能留条的地方：今天的条数用完了，或者没有别的对话可去。',
}
NOT_NOW['ideas.review'] = NOT_NOW['ideas.read']
ERRAND_NOTE = ('外面写来的便条叫起来的回合，只有便条带着主人本人的原话（程序核对过他的账号）才能接差事；这张没有。'
               '要去办，等主人在家里说，或者写进计划。')
CONSULT_ONLY = '行动脑在问你话：这一回合只用 task 的 answer 回答它（think、recall 也能用），别的事等下一回合。'
NOTE_ONLY = ('这一回合是外面一张便条叫起来的：只读、回话、记想法（ideas 的 note），不做有后果的事；'
             '想做的记进想法本，到自我改进时再定。')


def not_now(store, ep, name):
    """Why her conversation's tool or option `name` is not in this turn, and when it can be used."""
    from . import local_time, switches
    off = switches.tools_off(store, ep['scene_id']).get(name.split('.')[0])
    if off:
        return ('%s 是你在家里给这个对话关掉的（到 %s 自己恢复）；要提前用，回家用 set_policy 的 switch_off 结束它（id 是 %s）。'
                % (name.split('.')[0], local_time.stamp(off['until'], local_time.zone_of(store, ep['scene_id'])), off['_id']))
    kind = turn_kind(ep)
    if kind == CONSULT:
        return CONSULT_ONLY
    if ep.get('errand') and name in DELEGATING:
        from .errands import NO_DELEGATE
        return NO_DELEGATE
    if _one_shot(ep) and name in DELEGATING:
        return REFLECTION_NO_DELEGATE
    if kind == 'note' and name == 'errand':
        return ERRAND_NOTE
    if kind == 'note' and name not in ('note', 'feel', 'watch', 'read_image'):
        from . import notes
        if (notes.opening(store, ep) or {}).get('trust') != notes.TRUSTED:
            return NOTE_ONLY
    return NOT_NOW.get(name, '这一回合用不了 %s。' % named(name))


STICKER_LOOKED_NOTE = ('这是个表情包。想以后再见到它不用再看：用 sticker 的 remember 记个名字和一句它在说什么'
                       '（ref 照抄）；想收着自己发就 keep。都不想就不用管。')


def offered_pictures(ep):
    """The artifact ids her turn may send (image_artifacts_from_program): she may also look at them."""
    from .stickers import candidate_ids
    items = ((ep.get('context') or {}).get('image_artifacts_from_program') or {}).get('items') or ()
    return tuple(item['artifact_id'] for item in items if isinstance(item, dict) and item.get('artifact_id'))         + candidate_ids(ep.get('context'), ep.get('pool_listed'))  # sticker candidates: she looks before she keeps


def her_pictures(store, ep):
    """Whether she can look at a picture this turn: her own route takes images and the conversation's recent
    pictures (the same window read_image reads) include one that can be pulled."""
    from .vision import scene_attachments, vision_capability
    if not vision_capability(store.config, 'character')['supported']:
        return False
    if (ep.get('manifest') or {}).get('session_class') == visibility.OWNER_PRIVATE:
        return True                       # at home a ref from any of her conversations is readable (owner 2026-10-11)
    if offered_pictures(ep) or ((ep.get('context') or {}).get('your_pictures_from_program') or {}).get('items'):
        return True                       # she can look before she sends, and at her own pictures at home
    if (ep.get('context') or {}).get('stickers_from_program') and store.db.sticker_pool.find_one({}, {'_id': 1}):
        return True                       # what sticker op=pool lists, she looks at before she keeps
    try:
        listing = scene_attachments(store, ep, store.config)
    except Denied:
        return False
    return any(item.get('pullable') for item in listing['attachments'])


# Pictures that come with a group turn by themselves (owner 2026-10-08, on her ask): she should not have to decide
# whether a picture is worth a look before she has seen it. The line that started the turn brings its pictures; up
# to TURN_PICTURES are filled from photos (not stickers: she knows those by fingerprint) in the few lines before it.
TURN_PICTURES = 2
TURN_PICTURE_LINES = 6
PICTURES_NOTE = ('这些图已经作为图片跟这一回合一起给你了，不用再 read_image；别的图照旧用 read_image（ref 照抄图旁标的）。'
                 '哪张没出现，就是没拉下来，用 read_image 再看一次也行。')


def turn_pictures(store, ep):
    """([(ref, payload)] to attach to her group turn, pictures_from_program or None). A picture that cannot be
    pulled is left out (read_image still reaches it)."""
    from .blobs import BlobStore
    from .vision import attachments_of, read_image_for_task, vision_capability
    scene = store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1})
    if (scene or {}).get('kind') != 'group' or not vision_capability(store.config, 'character')['supported']:
        return [], None
    source = store.db.messages.find_one({'_id': 'in-' + ep['_id'], 'scene_id': ep['scene_id']})
    if not source:
        return [], None
    chosen = [(entry, '触发这一回合的那条') for entry in attachments_of(source, config=store.config)][:TURN_PICTURES]
    if len(chosen) < TURN_PICTURES:
        earlier = store.db.messages.find({'scene_id': ep['scene_id'], 'direction': 'inbound',
                                          'policy_epoch': ep['policy_epoch'],
                                          'scene_seq': {'$lt': source.get('scene_seq', 0),
                                                        '$gte': source.get('scene_seq', 0) - TURN_PICTURE_LINES},
                                          'event.raw.asuna_media': {'$exists': True}}).sort('scene_seq', -1)
        for row in earlier:
            for entry in attachments_of(row, config=store.config):
                if len(chosen) < TURN_PICTURES and not entry.get('sticker'):
                    chosen.append((entry, '前面第 %d 条' % (source.get('scene_seq', 0) - row.get('scene_seq', 0))))
    pulled, shown = [], []
    where = {k: ep[k] for k in ('scene_id', 'scope_key', 'policy_epoch')}
    for entry, line in chosen:
        try:
            payload = read_image_for_task(store, BlobStore(store), where, store.config, {'ref': entry['ref']},
                                          route='character')
        except Exception:                                   # noqa: BLE001 an expired link: read_image says why
            continue
        if isinstance(payload, dict) and isinstance(payload.get('image'), dict):
            pulled.append((entry['ref'], payload))
            shown.append({'ref': entry['ref'], 'line': line, **({'sticker': '表情包'} if entry.get('sticker') else {}),
                          **({'animated': payload['animated']} if payload.get('animated') else {})})
    if not shown:
        return [], None
    return pulled, {'items': shown, 'note': PICTURES_NOTE}


# Words for the refusals she is most likely to meet: the gist. The detail after the code carries the values and the
# fix; a code not listed here is passed on as it is (its own message says both).
WORDS = {
    'DOC_WRITE_REQUIRES_OWNER_PRIVATE': '这份文档只能在家里（家里·私聊、主人私聊这类可信的对话）改。',
    'GROUP_NOTES_ONLY_IN_ITS_GROUP': '群笔记在那个群里用 doc=group_notes 写，夜间整理时用列出的 doc 写；只能 append_section、replace_section 或 set_tags。',
    'NOTE_OVER_LIMIT': '这份笔记已经超出每回合上限很多了，先整理（改短、合并，或用 set_tags 把不常用的节收起来）再加新的。',
    'DOC_SECTION_NOT_FOUND': '没有这一节。',
    'DOC_BODY_REQUIRED': '这个操作要在 content 里写正文。',
    'DOC_HEADING_REQUIRED': '新的一节要有标题。',
    'DOC_REASON_REQUIRED': '要写 why：为什么改，2000 字以内。',
    'DOC_OP_NOT_ALLOWED': '这份文档不能这样改。',
    'DOC_OP_UNKNOWN': '没有这种文档操作。',
    'DOC_TAGS_INVALID': 'visibility 或 when_shown 的值不对。',
    'DOC_REVISION_TOO_LARGE': '这份文档写完太大了。',
    'DOC_NOT_FOUND': '没有这份文档；新文档只能用 append_section 开始。',
    'DOC_SEED_NOT_FOUND': '人格包里没有这份种子。',
    'BASE_REVISION_STALE': '要改的东西刚被别处改过。',
    'PERSONA_RENDER_OVER_BUDGET': '这样写完，每回合自动带上的人格和口吻会超出上限。',
    'POLICY_SET_REQUIRES_OWNER_PRIVATE': '参数只能在家里（家里·私聊、主人私聊这类可信的对话）改。',
    'PROMOTE_ONLY_IN_SETTLEMENT': '提升长期记忆只在夜间沉淀时做。',
    'PROMOTION_QUOTA': '今天提升长期记忆的配额用完了。',
    'PROMOTION_SOURCES_INSUFFICIENT': '来源不够：要来自足够多的不同回合和日期。',
    'ATTACH_TARGET_NOT_ALLOWED': '这里不能带图：私聊和你在的群能带（群和别人的私聊只发你自己做的图）。',
    'ATTACH_ARTIFACT_NOT_IN_CONTEXT': '只能用 image_artifacts_from_program 里列出的 artifact_id。',
    'ATTACHMENT_NOT_HER_OWN': '群里和别人的私聊里只能发你自己做的图；换一张你做的，或这回合不带图。',
    'ATTACHMENT_ARTIFACT_UNAVAILABLE': '这张图还没做好或已经不在了；换 image_artifacts_from_program 里别的，或这回合不带图。',
    'ATTACHMENT_SCOPE_DENIED': '这张图不是这个对话能用的；换一张，或这回合不带图。',
    'ATTACHMENT_NOT_AN_IMAGE': '这不是一张能发的图片；换一张，或这回合不带图。',
    'ATTACHMENT_OVER_LIMIT': '这张图超过 8 MiB，发不了；换一张，或这回合不带图。',
    'ATTACHMENT_HASH_MISMATCH': '这张图的存档对不上（不是你的错），发不了；换一张，或这回合不带图。',
    'GROUP_ACTION_NOT_A_GROUP': '这里不是群。',
    'GROUP_ACTION_DISABLED': '这个群关掉了管理动作。',
    'GROUP_ACTION_NOT_AN_ADMIN': '你在这个群不是管理员。',
    'VISIT_PLACE_UNKNOWN': '这个地方去不了。',
    'VISIT_NOT_NOW': '现在去不了那里。',
    'VISIT_OFF': '出门现在没开。',
    'VISIT_PICTURE_NOT_HERS': '只能带你自己做的图；到了群里那个回合再挑也行。',
    'STICKER_SHELF_FULL': '表情包架子满了：先用 drop 放下一个不想要的，再收。',
    'STICKER_NAME_TAKEN': '架子上已经有这个名字了：换一个名字。',
    'STICKER_NAME_INVALID': '名字不合适。',
    'STICKER_WHEN_INVALID': 'when 要写一句什么时候用它（或它在说什么）。',
    'STICKER_NOT_YOURS': '只有你自己画的图能直接放上架子；别人的要用群里表情包下面的 ref 收。',
    'STICKER_REF_NOT_HERE': '这个对话最近的消息里没有这个 ref：照抄表情包下面标的 ref；太早的收不到了。',
    'STICKER_IS_A_PHOTO': '这是一张照片，不是表情包：照片不能收。',
    'STICKER_NOT_REACHABLE': '这个表情包拉不到了（链接可能过期了），收不了。',
    'STICKER_ALREADY_KEPT': '这个表情包你已经收过了。',
    'STICKER_CANDIDATE_NOT_LOOKED': '先用 read_image 看过这个候选（ref 照抄 candidate），再收或记。',
    'STICKER_NOT_LOOKED': '先用 read_image 看过这个表情包，再记它是什么。',
    'CREDENTIAL_NAME_INVALID': 'name 是 2–32 个小写字母、数字或连字符，字母开头。',
    'CREDENTIAL_NOTE_INVALID': 'note 写一句它是干什么的（80 字以内），不写值。',
    'CREDENTIAL_ENV_INVALID': 'env 是 1–6 个「大写环境变量名 → 值」，名字不能是系统要用的（PATH 之类）。',
    'CREDENTIAL_NOT_FOUND': '保险箱里没有这个名字。',
    'CREDENTIALS_UNAVAILABLE': '这会儿保险箱用不了：跟对方说现在收不了，值不要写进别处。',
    'WATCH_HOURS_INVALID': 'hours 是 1 到 72 之间的整数。',
    'WATCH_MODE_INVALID': 'how_often 是 once 或 burst。',
    'WATCH_PERSON_NOT_HERE': '这个对话里找不到这个人：照抄他的标签或 #编号。',
    'WATCH_PERSON_UNCLEAR': '这个名字对得上不止一个人：用标签里的 #编号。',
    'WATCH_LIST_FULL': 'watch 名单满了：先 off 一个（id 照抄 watching_from_program）。',
    'WATCH_NOT_FOUND': '名单上没有这个 id：照抄 watching_from_program 里的 id。',
    'STICKER_NO_FINGERPRINT': '这个表情包平台没给能认出它的标记，记不住；想留着就 keep。',
    'STICKER_CANDIDATE_GONE': '这个候选已经不在池子里了（挤掉了或收过了）。',
    'STICKER_NOT_ON_SHELF': '架子上没有这个名字：照抄 stickers_from_program 里的名字。',
    'STICKER_NOTHING_TO_CHANGE': 'rename 要写 new_name 或 when。',
    'ERRAND_PLACE_UNKNOWN': '这个地方去不了。',
    'ERRAND_LIMIT': '替人跑腿的次数用完了。',
    'ERRAND_ONLY_AT_HOME': '只有在家里（家里·私聊、主人私聊这类可信的对话）才能接差事。',
    'ERRAND_PICTURE_NOT_HERS': '差事只能带你自己做的图。',
    'ERRAND_ONLY_WHEN_ASKED': '差事只在家里有人跟你说话、让你去办的那一回合接；自己想去，用 visit。',
    'FEEDBACK_TASK_STALE': '这一步做不了。',
    'WORKSPACE_NOT_AUTHORIZED': '这个对话不能交给行动脑做事；能直接答的就直接答。',
    'SCENE_MEMBERSHIP_DENIED': '这一步做不了。',
    'STALE_REVISION': '没写进去。',
    'UNDERSTANDING_UPDATE_NOT_AVAILABLE': '这回合不能更新对这个人的理解；重试也一样。',
    'IMAGE_ATTACHMENT_NOT_IN_SCENE': '这个 ref 对不上。',
    'IMAGE_NOT_PULLABLE': '这张图看不了。',
    'IMAGE_SOURCE_UNAVAILABLE': '这张图的来源已经没有了。',
    'IMAGE_FETCH_FAILED': '这张图没拉下来。',
    'IMAGE_LINK_EXPIRED': '这张图的链接换了新签名也拉不到了。',
    'IMAGE_GONE': '这张图在平台上已经不在了。',
    'IMAGE_SIGNATURE_UNAVAILABLE': '这张图的链接过期了，眼下换不了新签名；过几分钟再试。',
    'IMAGE_TOO_LARGE': '这张图太大，看不了。',
    'IMAGE_TYPE_UNSUPPORTED': '这不是能看的图片格式。',
    'IMAGE_PATH_HOME_ONLY': '按路径读图只在家里（家里·私聊、主人私聊这类可信的对话）能做；这里看消息里的图，ref 照抄图旁标的那个。',
    'VISION_ROUTE_UNSUPPORTED': '你现在的模型看不了图；要看就交给行动脑，把 ref 一起交代。',
}


def code_of(exc):
    """The machine code of a refusal, kept in the record (ADR-060), never in her words."""
    return getattr(exc, 'code', None) or str(exc).split(':', 1)[0].strip() or type(exc).__name__


def words(exc):
    """A refusal in words for her (ADR-060): what is wrong and what to do. The code stays in the record (the audit
    keeps the exception); a detail in words is kept, a machine detail (a platform's raw reply, an id) is not."""
    code = getattr(exc, 'code', None) or str(exc).split(':', 1)[0].strip() or type(exc).__name__
    detail = getattr(exc, 'detail', '') or (str(exc).split(':', 1)[1].strip() if ':' in str(exc) else '')
    said = WORDS.get(code, '')
    plain = detail if _HAN.search(detail or '') else ''
    return (said + plain) if (said or plain) else '这次没办成（%s）。' % code


_HAN = __import__('re').compile(r'[一-鿿]')        # a detail written in words for her


NO_REASON = '（没写为什么）'
# Her pokes and reactions in her history: the program's words, marked as what she did (ADR-064 phase 2, her words).
ACTION_MARK = '（你做的动作，不是你说的话）'
# ADR-079: a line's number in her conversation (〔318〕) is for choosing what to point at, never for her words.
LINE_NUMBER = re.compile(r'〔\s*\d+\s*〕')
NUMBER_NOT_WORDS = '编号是挑引用用的，不写进你说的话里。'
REACT_MINUTES = 10
# Channels whose platform refused a reaction in a private chat: not tried there again until the Host restarts (her
# call: the platform may take them one day).
REACT_OFF_IN_DMS = set()


def recent_line(store, scene, ep, people, doc, which):
    """The line she means of theirs: the one that called her (这条, if it is theirs), else their latest within
    REACT_MINUTES (刚才那条, or 这条 when the line that called her is someone else's)."""
    from datetime import datetime, timedelta, timezone
    source = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    if which == '这条' and source and people.person(source.get('author')) == doc.get('person'):
        return source
    since = (datetime.now(timezone.utc) - timedelta(minutes=REACT_MINUTES)).isoformat()
    return store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'inbound',
                                       'author': {'$in': people.authors_of(doc['person'], [scene['_id']])},
                                       'received_at': {'$gte': since}}, sort=[('scene_seq', -1)])


def chat_lines(text):
    """How many lines a text part is in a chat (owner 2026-10-14: in online chat a line break is another message):
    each line with words counts, a blank line does not, a fenced code block counts as one."""
    count, fenced = 0, False
    for line in str(text or '').splitlines():
        if line.lstrip().startswith('```'):
            if not fenced:
                count += 1
            fenced = not fenced
        elif not fenced and line.strip():
            count += 1
    return count


QUESTION_RECEIPT = '这是在问这里的人：问题 %s，等%s（%d 分钟）；有人回会叫你看一眼，回答进 questions_from_program。'


def reply_receipt(queued, numbered=False):
    """What her reply call queued, in words: each part by its number, and what failed at once (ADR-064 phase 2); where
    the conversation shows line numbers, each sent line's own (ADR-079)."""
    done = [row for row in queued if row['state'] not in ('FAILED', 'UNKNOWN', 'CANCELLED_AFTER_FAILURE')]
    listed = '；'.join('%d %s%s' % (row['number'], row['shown'], ' 〔%d〕' % row['seq'] if numbered and row.get('seq') else '')
                      for row in done)
    if len(done) == len(queued):
        return '发出 %d 条，%s排上了：%s。送没送到看下一回合的历史。' % (len(queued), '都' if len(queued) > 1 else '', listed)
    failed = next(row for row in queued if row not in done)
    return ('发出 %d 条：%s。第 %d 条没发出去，它后面的都取消了；送没送到看下一回合的历史。'
            % (len(queued), listed or '一条都没排上', failed['number']))


def _given(args, field):
    """What she gave for an enum field, for a refusal: '（给的是「x」）' or '（没写 x）'."""
    value = (args or {}).get(field) if isinstance(args, dict) else None
    shown = {'op': 'do', 'decision': 'do', 'how': 'quote_whom', **_SHOWN}.get(field, field)
    return '（没写 %s）' % shown if value is None else '（给的是「%s」）' % str(value)[:40]


# Why her understanding of someone was not saved (MemoryService.commit_understanding: NOT_COMMITTED), in words.
UNDERSTANDING_NOT_SAVED = {
    'NO_NEW_SOURCE_EVENTS': '这次没有新的对话可以作依据，理解没存；有了新的对话再更新。',
    'BASE_REVISION_STALE': '对这个人的理解刚被更新过，这次没存；下回合看了最新的再改。',
}


# Why a conversation takes no picture (outbound_media.target_allowed), in words.
ATTACH_REASONS = {'scene_has_no_channel_route': '这个对话没接到平台', 'channel_route_not_authorized': '这个对话的平台路由没授权',
                  'channel_carries_text_only': '这个平台只能发文字', 'target_not_dm': '这里既不是私聊，也不是你在的群'}


# A task of this conversation that another person asked for (RoleTools._own_task).
OTHERS_TASK = ('「%s」是 %s 叫你做的那件事：只有在 ta 叫你的那一回合里才能给它补话或叫停。这一回合是别人叫你的，'
               '所以这次动不了它，不是你抄错了。要停，等 ta 再叫你时停，或者在这里跟大家说一声它还在做。')


class RoleTools:
    """Runs one tool call for one episode, on the coordinator's thread (it holds the coordinator lock)."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.store = coordinator.store

    # ── dispatch ────────────────────────────────────────────────────
    def call(self, ep_id, call_id, name, args):
        """(result, concludes_turn). Raises Refused for a call she can correct herself."""
        c = self.coordinator
        ep = self.store.db.episodes.find_one({'_id': ep_id})
        called_as = None
        if name in RENAMED and isinstance(args, dict):          # an old name runs as its option (ADR-055)
            called_as, (name, args) = name, renamed(name, args)
        elif name == MESSAGE_DEVELOPER['name'] and isinstance(args, dict):
            called_as, name, args = name, 'ask', developer_ask(self.store, args)       # ADR-061
        olds = _names.old_used(name, args)
        gone = _names.retired(name, olds)               # ADR-069: an old name past its week is not taken
        args, old_names = _names.inbound(name, args)
        inferred = name in OPS and isinstance(args, dict) and not args.get('op') and infer_op(name, args)
        if inferred:
            args = {**args, 'op': inferred}
        done = (ep.get('tool_calls') or {}).get(call_id)
        if done:
            if done['tool'] != name or done['args_sha256'] != sha(canonical(args)):
                raise Refused('CALL_ID_REUSED: 这个调用编号已经用在另一次调用上了（不是你的错）；重新调用一次就行。')
            if done.get('refused'):
                raise Refused(done['refused'])
            return self._local(ep, done['result']), bool(done.get('conclude'))
        try:
            if name not in TOOLS and name != 'update_self':           # retired, runs for a week (ADR-069)
                raise Refused('没有 %s 这个工具。' % name)
            if not isinstance(args, dict):
                raise Refused('参数要是一个对象（{字段: 值}），字段照这个工具的说明写。')
            if name in OPS and args.get('op') not in OPS[name]:
                raise Refused('%s 的 do 是 %s 之一%s。' % (name, '、'.join(OPS[name]), _given(args, 'op')))
            can = ability(name, args)
            if gone:
                raise Refused(_names.gone(gone))
            if (can == 'update_self' and 'write_document' in (ep.get('turn_tools') or ())
                    and visibility.OWNER_PRIVATE == self._cls(ep)):
                pass                              # her retired name, where write_document is hers (ADR-062)
            elif can not in (ep.get('turn_tools') or ()):
                raise Refused(not_now(self.store, ep, can))
            if name != 'think' and not ep.get('turn_thought'):
                raise Refused('先用 think 写下这回合的心里话，再做别的。')
            if len(ep.get('tool_calls') or {}) >= CALLS_PER_TURN:
                raise Refused('这回合的工具调用已经到上限（%d 次）：这回合先到这里，写下要说的话或用 stay_silent 结束。'
                              % CALLS_PER_TURN)
            result, conclude = getattr(self, 'tool_' + can.replace('.', '_'))(ep, call_id, args)
        except Refused as exc:
            self._record(ep_id, call_id, name, args, refused=str(exc), called_as=called_as, olds=olds)
            if ep.get('errand'):
                raise Refused('%s（%s）' % (exc, ERRAND_MARK)) from None
            raise
        except (Denied, Conflict, DocumentError, ValueError) as exc:
            message = words(exc)
            self._record(ep_id, call_id, name, args, refused=message, called_as=called_as, code=code_of(exc), olds=olds)
            raise Refused('%s（%s）' % (message, ERRAND_MARK) if ep.get('errand') else message) from None
        if called_as and isinstance(result, dict):
            result = {**result, 'renamed': rename_note(called_as)}
        if old_names and isinstance(result, dict):
            result = {**result, 'old_names': ' '.join(old_names)}
        if inferred and isinstance(result, dict):
            result = {**result, 'do': '没写 do：按你写的字段当作 %s 办了。' % inferred}
        if ep.get('errand') and isinstance(result, dict):
            result = {**result, 'turn': ERRAND_MARK}         # ADR-066: which layer of her acted, on every result
        from . import memory_tiers
        if memory_tiers.ENABLED and name != 'recall':
            # ADR-062: an item she cites by its doc: ref in a call is used, a memorable moment.
            cited = memory_tiers.refs_in(args)
            if cited:
                memory_tiers.Tiers(self.store, ep['persona']).used(cited, 'cited', ep['scene_id'])
        # A picture's bytes go back to the turn only: the record keeps the receipt (the bytes are in the blob store).
        self._record(ep_id, call_id, name, args, conclude=conclude, called_as=called_as, olds=olds,
                     result=picture_receipt(result) if name == _READ_IMAGE['name'] else result)
        return self._local(ep, result), conclude

    def _local(self, ep, result):
        """What she reads back is on the local clock; the record keeps UTC (local_time.py)."""
        from . import local_time
        return local_time.for_model(result, local_time.zone_of(self.store, ep['scene_id']))

    def _record(self, ep_id, call_id, name, args, *, result=None, refused=None, conclude=False, called_as=None, code=None,
                olds=None):
        c = self.coordinator
        ep = self.store.db.episodes.find_one({'_id': ep_id})
        calls = dict(ep.get('tool_calls') or {})
        # A call with consequences keeps the thought it came from: her newest in the turn (reasons.py, ADR-043).
        from . import reasons
        reason = None if refused or not reasons.consequential(name, args) else reasons.newest(ep)
        calls[call_id] = {'tool': name, 'args_sha256': sha(canonical(args)), 'seq': len(calls),
                          **({'op': args.get('op')} if name in OPS and isinstance(args, dict) else {}),
                          **({'called_as': called_as} if called_as else {}),
                          **({'old_names': olds} if olds else {}),
                          **({'refused': refused} if refused else {'result': result}),
                          **({'code': code} if code else {}),
                          **({'reason_ref': reason} if reason else {}),
                          **({'conclude': True} if conclude else {})}
        c._update(ep, tool_calls=calls)
        self.store.audit(ep_id, 'role_tool', {'call_id': call_id, 'tool': name, 'args': args,
                                              **({'called_as': called_as} if called_as else {}),
                                              **({'old_names': olds} if olds else {}),
                                              **({'refused': refused} if refused else {'result': result}),
                                              **({'code': code} if code else {}),
                                              **({'reason_ref': reason} if reason else {})},
                         ep['scope_key'])

    def _fresh(self, ep):
        return self.store.db.episodes.find_one({'_id': ep['_id']})

    def _cls(self, ep):
        """The authority this turn acts with: its conversation's class, or home's on an errand (ADR-066)."""
        return visibility.OWNER_PRIVATE if ep.get('errand') else self._place(ep)

    def _place(self, ep):
        """The class of the conversation this turn is in: what goes out there and who is there."""
        return (ep.get('manifest') or {}).get('session_class', visibility.PUBLIC)

    def _text(self, args, field, limit, *, required=True):
        value = args.get(field)
        if value is None and not required:
            return None
        if value is not None and not isinstance(value, str):
            raise Refused('%s 要是一段文字（%d 字以内），给的是%s。' % (field, limit, {
                bool: ' true/false', int: '数字', float: '数字', list: '列表', dict: '对象'}.get(type(value), '别的类型')))
        if not value or not value.strip():
            raise Refused(('%s 要写内容（%d 字以内）。' if required else '%s 是空的：要么写内容（%d 字以内），要么不写这个字段。')
                          % (field, limit))
        if len(value) > limit:
            raise Refused('%s 太长了：%d 字，%d 字以内，超了 %d 字。精简后再调用，或者照这个截好的写：%s'
                          % (_SHOWN.get(field, field), len(value), limit, len(value) - limit, cut_offer(value, limit)))
        return value.strip()

    # ── mind ────────────────────────────────────────────────────────
    def tool_think(self, ep, call_id, args):
        thought = self._text(args, 'thought', 100000)
        from .config import character_id
        memory_id = 'mono-' + ep['_id'] + ':' + call_id
        home = ep.get('errand') or ep               # an errand's thoughts are kept at home (ADR-066)
        if not self.store.db.memory_units.find_one({'_id': memory_id}):
            self.store.put('memory_units', {'_id': memory_id, 'character_id': character_id(self.store.config),
                'kind': 'monologue', 'scope_key': home['scope_key'], 'policy_epoch': home['policy_epoch'],
                'body_markdown': thought, 'epistemic_type': 'character_interpretation',
                'source_event_ids': [ep['source_event_id']], 'depends_on': [ep['source_event_id']],
                'episode_id': ep['_id'], 'status': 'active', 'embedding_status': 'PENDING'}, stream=ep['_id'])
        ep = self._fresh(ep)
        self.coordinator._update(ep, turn_thought=True,
                                 monologue_refs=[*dict.fromkeys([*(ep.get('monologue_refs') or []), memory_id])])
        over = len(thought) - THOUGHT_CHARS
        # Kept whatever its length (her decision, 2026-10-14): a refusal cost a whole retry. Only this result says it.
        return {'saved': True, 'note': '已存档。' + ('超了 %d 字。' % over if over > 0 else '')}, False

    def tool_recall(self, ep, call_id, args):
        # ADR-060: query is optional when sections name what to read.
        query = self._text(args, 'query', 500, required=not args.get('sections'))
        count = int(ep.get('recall_count') or 0)
        if count >= RECALLS_PER_TURN:
            raise Refused('这回合已经回想了 %d 次：用已经想起来的回答，记不清就直说。' % RECALLS_PER_TURN)
        from . import memory_tiers
        sections = args.get('sections') or []
        listing = [item for item in sections if memory_tiers.ENABLED and isinstance(item, dict)
                   and isinstance(item.get('doc'), str) and item.get('sid') is None]
        if not isinstance(sections, list) or len(sections) > 3 or any(
                not isinstance(item, dict) or not isinstance(item.get('doc'), str)
                or not (isinstance(item.get('sid'), str) or item in listing) for item in sections):
            raise Refused('sections 是至多 3 条 {doc, section}（都是文字，section 照抄 recall 或文档里的）%s。'
                          % ('；给了 %d 条' % len(sections) if isinstance(sections, list) and len(sections) > 3 else ''))
        c = self.coordinator
        event = {'event_id': ep['source_event_id'], 'scene_id': ep['scene_id'], 'person_id': ep['person_id'], 'text': query}
        recalled = c.context.prepare(event, ep['persona'], recall=True, turn_kind=turn_kind(ep))[1] if query else {}
        if ep.get('errand') and query:
            # ADR-066: home's memories as well, as home would recall them.
            home = c.context.prepare({**event, 'scene_id': ep['errand']['scene_id'], 'person_id': ep['errand']['person_id']},
                                     ep['persona'], recall=True, turn_kind=turn_kind(ep))[1]
            seen = {m.get('_id') for m in recalled.get('memories') or []}
            recalled = {**recalled, 'memories': [*(recalled.get('memories') or []),
                                                 *(m for m in home.get('memories') or [] if m.get('_id') not in seen)]}
        documents, missing = read_sections(self.store, ep, [s for s in sections if s not in listing], self._cls(ep))
        # At home her recall also reaches what she herself thought in her groups (her own words, never theirs).
        elsewhere = []
        if self._cls(ep) == visibility.OWNER_PRIVATE and query:
            scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']}
            elsewhere = c.context.own_thoughts_elsewhere(scene, query)
        ep = self._fresh(ep)
        c._update(ep, recall_count=count + 1,
                  recalled=[*(ep.get('recalled') or []), *[m.get('_id') for m in recalled.get('memories') or []],
                            *[m['_id'] for m in elsewhere]])
        # Every recall is kept (ADR-032): what she asked, what came back, in which kind of turn and place, so a later
        # review counts her real reads and misses from records, not from memory.
        from .visibility import place
        scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']}
        self.store.audit(ep['_id'], 'recall.read', {
            'query': query, 'sections_asked': sections,
            'sections_read': [{'doc': d.get('doc'), 'sid': d.get('sid')} for d in documents or []],
            'sections_missing': missing or [], 'memories': [m.get('_id') for m in recalled.get('memories') or []],
            'own_thoughts_elsewhere': [m['_id'] for m in elsewhere],
            'turn_kind': turn_kind(ep), 'place': place(self.store.config, self.store.db, scene, ep['person_id'])},
            ep['scope_key'])
        result = {'query': query, 'memories': recalled.get('memories') or []}
        if recalled.get('coverage_from_program'):
            result['coverage'] = recalled['coverage_from_program']
        if recalled.get('held_back_from_program'):
            result['held_back'] = recalled['held_back_from_program']
        if documents:
            result['documents'] = documents
        if missing:
            result['not_read'] = missing
        if elsewhere:
            result['own_thoughts_in_groups'] = [{k: v for k, v in m.items() if k != '_id'} for m in elsewhere]
        if memory_tiers.ENABLED:
            # ADR-062: what she reads back is used; she sees which places were searched, and what else exists there.
            tiers = memory_tiers.Tiers(self.store, ep['persona'])
            tiers.used([(d['doc'], d['sid']) for d in documents or [] if d.get('doc') and d.get('sid')], 'recalled',
                       ep['scene_id'])
            docs = DocumentStore(self.store, ep['persona'])
            for item in listing:
                content = docs.read(item['doc'])[1]
                if content:
                    result.setdefault('documents', []).append({'doc': item['doc'], 'headings': memory_tiers.doc_headings(
                        self.store, ep['persona'], item['doc'], content, self._cls(ep))})
                else:
                    result.setdefault('not_read', []).append('%s：没有这份文档' % item['doc'])
            readable = {'global-safe', ep['scope_key'], *([visibility.owner_private_scope(ep['persona'])]
                                                          if self._cls(ep) == visibility.OWNER_PRIVATE else [])}
            shown = {m.get('_id') for m in result['memories']}
            found = memory_tiers.headings(self.store, ep['persona'], c.context.pilot, query, readable, self._cls(ep),
                                          shown) if query else []
            if found:
                result['headings'] = found
            result['searched'] = memory_tiers.SEARCHED
            if not (result['memories'] or result.get('documents') or found or elsewhere):
                result['found'] = memory_tiers.NOTHING
        return result, False

    def tool_stay_silent(self, ep, call_id, args):
        # After speak there is nothing to explain; a silence without words keeps a plain mark for the record.
        reason = self._text(args, 'reason', 1000, required=False) or NO_REASON
        ep = self.coordinator._update(self._fresh(ep), silent={'reason': reason})
        from . import channel_kinds
        if channel_kinds.reply_parts(ep['scene_id']):
            # ADR-064 phase 2 (her condition): how many parts reply queued this turn, 0 included.
            parts = int((ep.get('reply') or {}).get('parts') or 0)
            return {'silent': True, 'note': '这回合到此结束。',
                    'sent': 'speak 这回合发了 %d 条。' % parts if parts else '这回合 speak 一条都没发。'}, True
        # The Host adds what this turn has written so far (`written`), a fact she cannot read back herself.
        return {'silent': True, 'note': '这回合到此结束。'}, True

    def tool_quote(self, ep, call_id, args):
        how = args.get('how')
        if how not in ('source', 'none'):
            raise Refused('quote_whom 是 source（引用叫你的那条）或 none（不引用）%s。' % _given(args, 'how'))
        self.coordinator._update(self._fresh(ep), quote=how)
        return {'note': '这回合第一句会引用叫你的那条。' if how == 'source' else '这回合说的话都不带引用。'}, False

    def tool_credential(self, ep, call_id, args):
        from . import credentials
        if args.get('op') == 'keep':
            return credentials.keep(args.get('name'), args.get('note'), args.get('env')), False
        if args.get('op') == 'drop':
            return credentials.drop(args.get('name')), False
        raise Refused('do 是 keep 或 drop%s。' % _given(args, 'op'))

    def tool_watch(self, ep, call_id, args):
        from . import watches
        op = args.get('op')
        if op == 'on':
            if (self.store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1}) or {}).get('kind') not in ('group', 'dm'):
                raise Refused('这里不是群或私聊，盯不了人：到看得到他的群或私聊里再用 on。')
            return watches.add(self.store, ep, ep['persona'], self._place(ep), args), False
        if op == 'off':
            return watches.stop(self.store, ep['persona'], args.get('id')), False
        raise Refused('do 是 on 或 off%s。' % _given(args, 'op'))

    def tool_await_answer(self, ep, call_id, args):
        wait = args.get('wait', 'yes')
        if wait not in ('yes', 'no'):
            raise Refused('wait 是 yes 或 no%s。' % _given(args, 'wait'))
        if wait == 'no':
            self.coordinator._update(self._fresh(ep), await_answer={'off': True})
            return {'note': '这回合不等回话。'}, False
        why = self._text(args, 'why', 200)
        self.coordinator._update(self._fresh(ep), await_answer={'why': why})
        return {'note': '这句发出去后约三分钟里，你 @ 的人、你回的人（都没有时这里任何人）下一句没 @ 你也会叫你看一眼。'}, False

    def tool_speak(self, ep, call_id, args):
        """ADR-064 phase 2: her speech here, in parts. Every part is checked before any is queued: one wrong part
        means none of this call leaves, and the result says which and why."""
        from . import channel_kinds, stickers
        from .persona_model import effective
        from .render import model_and_policy
        ep = self._fresh(ep)
        kinds = channel_kinds.reply_parts(ep['scene_id'])
        parts = args.get('parts')
        if not isinstance(parts, list) or not parts:
            raise Refused('parts 要列出这次要发的，至少一个。')
        scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']}
        group = scene.get('kind') == 'group'
        model, policy = model_and_policy(self.store, ep['persona'])
        most = int(effective(model, 'speak.max_messages', policy) or 1)
        before = ep.get('reply') or {}
        texts = list(before.get('texts') or [])
        lines = int(before.get('lines') or 0)
        problems, planned, over = [], [], []
        # A number that is someone's here reads as nothing to the people here (owner 2026-10-14: a warning she may
        # overrule with force, not a conversion).
        from .people import People
        people, numbered = None if args.get('force') else People(self.store, ep['persona']), False
        for index, part in enumerate(parts, 1):
            part = part if isinstance(part, dict) else {}
            kind = part.get('kind')
            if kind not in REPLY_KINDS:
                problems.append('第 %d 条的 kind 是 %s 之一' % (index, '、'.join(kinds)))
            elif kind not in kinds:
                problems.append('第 %d 条 %s 这里发不了' % (index, kind))
            elif kind == 'text':
                text = part.get('text') if isinstance(part.get('text'), str) else ''
                same = ' '.join(text.split())
                face = same and stickers.speech_problem(self.store, ep, text)
                if not same:
                    problems.append('第 %d 条是空的' % index)
                elif stickers.TOKEN.search(text):
                    problems.append('第 %d 条里的「%s」要写成一个 kind=sticker 的 part' % (index, stickers.TOKEN.search(text).group(0)))
                elif '[分条]' in text:
                    problems.append('第 %d 条：一个 text 就是一条消息，要分开就写成几个 text' % index)
                elif LINE_NUMBER.search(text):
                    problems.append('第 %d 条里的「%s」：%s' % (index, LINE_NUMBER.search(text).group(0), NUMBER_NOT_WORDS))
                elif face:
                    problems.append('第 %d 条：%s' % (index, face))
                elif same in texts:
                    problems.append('第 %d 条这回合已经发过一样的' % index)
                elif people and people.numbers(scene, text):
                    numbered = True
                    problems.append('第 %d 条里%s，这里的人看不懂：写名字，或 @ 整个标签' % (index, '，'.join(
                        '「%s」是 %s 的编号' % found for found in people.numbers(scene, text))))
                elif lines + chat_lines(text) > most:      # lines: this turn's, earlier calls and this one so far
                    over.append('第 %d 条有 %d 行' % (index, chat_lines(text)) + ('（前面已经 %d 行）' % lines if lines else ''))
                else:
                    texts.append(same)
                    lines += chat_lines(text)
                    planned.append({'kind': 'text', 'text': text.strip(), 'shown': 'text'})
            elif kind == 'sticker':
                name = str(part.get('name') or '').strip()
                fields = stickers.outbound(self.store, ep['persona'], '[表情包:%s]' % name) if name else None
                if not fields:
                    problems.append('第 %d 条 sticker「%s」你没收着' % (index, name) if name else '第 %d 条 sticker 要写 name' % index)
                else:
                    planned.append({'kind': 'sticker', 'text': '[表情包:%s]' % name, 'fields': fields, 'name': name,
                                    'shown': 'sticker「%s」' % name})
            elif kind in ('poke', 'react'):
                try:
                    planned.append(self._action_part(ep, scene, kind, part))
                except Refused as exc:
                    problems.append('第 %d 条 %s' % (index, str(exc)))
            elif kind == 'picture':
                try:
                    meta = self._picture(ep, scene, str(part.get('artifact_id') or ''))
                except Refused as exc:
                    problems.append('第 %d 条 picture %s' % (index, str(exc)))
                except Denied as exc:
                    problems.append('第 %d 条 picture %s' % (index, words(exc)))
                else:
                    planned.append({'kind': 'picture', 'text': '', 'fields': {'attachment': dict(meta)},
                                    'shown': 'picture'})
        quote, wait = args.get('quote'), args.get('wait')
        if quote not in (None, 'source', 'none'):
            problems.append('quote 是 source 或 none')
        if wait not in (None, 'no', 'question'):
            problems.append('wait 是 no 或 question')
        if (quote or wait) and not group:
            problems.append('quote 和 wait 只在群里用')
        patience = args.get('patience')
        from . import questions
        if patience is not None and (wait != 'question' or patience not in questions.GROUP_PATIENCE):
            problems.append('patience 只跟 wait=question 一起用，写 %s 之一' % '、'.join(questions.GROUP_PATIENCE))
        if wait == 'question' and not any(row['kind'] == 'text' for row in planned):
            problems.append('wait=question 要有一个 text 写问题')
        if over:
            problems.append('text 一回合最多 %d 行（你的 speak.max_messages；每一行都算，空行不算，一个代码块算一行）：%s'
                            % (most, '；'.join(over)))
        if problems:
            raise Refused('这次一条都没发：%s。改好再调用一次 speak。' % '；'.join(problems)
                          + ('真是别的数（PR 号之类），原样加 force=yes 再调用一次。' if numbered else ''))
        changes = {}
        if quote:
            changes['quote'] = quote
        if wait in ('no', 'question'):
            # a question's line is waited on by the question (its looks and answers), not listed again as a wait
            changes['await_answer'] = {'off': True}
        queued = self.coordinator.queue_reply(self.coordinator._update(ep, **changes) if changes else ep, planned)
        asked = None
        if wait == 'question':
            # ADR-061 step 2: a question here is her reply's words; answers join by the program (questions.py).
            asked = questions.ask_in_group(self.store, self._fresh(ep), scene,
                                           '\n'.join(row['text'] for row in planned if row['kind'] == 'text'), patience)
        self.coordinator._update(self._fresh(ep), reply={'texts': texts, 'lines': lines, 'parts': int(before.get('parts') or 0) + len(queued),
                                                          'calls': int(before.get('calls') or 0) + 1})
        from .capabilities import numbered as shows_numbers
        out = {'note': reply_receipt(queued, shows_numbers(self.store, scene))}
        if asked:
            out['question'] = QUESTION_RECEIPT % (asked['_id'], asked['patience'],
                                                  questions.PATIENCE[asked['patience']])
        return out, False

    def _action_part(self, ep, scene, kind, part):
        """A poke or a reaction as a part of her reply: the program's words for her history, and the platform action."""
        from . import channel_kinds
        from .people import People
        people = People(self.store, ep['persona'])
        who = str(part.get('who') or '').strip()
        if not who and scene.get('kind') == 'dm':
            who = ep['person_id']                 # a private chat has one other person: who may be left out
        found = people.resolve(scene, who) if who else []
        if not found:
            raise Refused('找不到「%s」：who 照抄标签' % who if who else '要写 who（照抄标签）')
        if len(found) > 1:
            raise Refused('「%s」对得上 %s：用标签里的 #编号' % (who, '、'.join(people.label(doc) for doc in found[:5])))
        doc = found[0]
        if doc.get('person') == people.self_id:
            raise Refused('不能对你自己')
        label = people.label(doc)
        if kind == 'poke':
            account = people.account_of(scene, doc)
            if not account:
                raise Refused('程序还不知道 %s 在平台上的账号（不是你的错）' % label)
            return {'kind': 'poke', 'text': '戳了戳 %s%s' % (label, ACTION_MARK), 'shown': 'poke %s' % label,
                    'fields': {'action': {'kind': 'poke', 'account': account}}}
        if scene.get('kind') == 'dm' and scene.get('channel_id') in REACT_OFF_IN_DMS:
            raise Refused('私聊里点不了表情（平台不收），到下次重启前私聊里不用 react')
        face = str(part.get('face') or '').strip()
        faces = channel_kinds.faces_of(scene['_id'])
        if face not in faces:
            raise Refused('「%s」不是这里的表情名' % face if face else '要写 face（表情名）')
        line = recent_line(self.store, scene, ep, people, doc, part.get('line') or '这条')
        message_id = ((line or {}).get('event') or {}).get('channel', {}).get('platform_event_id')
        if not message_id:
            raise Refused('%s %d 分钟内在这里没说过能点的话' % (label, REACT_MINUTES))
        # Her reaction reads like anyone's (ADR-079 §9.3): the line by its number, speaker and first words.
        return {'kind': 'react', 'text': '给 %s 点了「%s」%s' % (people.pointed(scene, line, 30), face, ACTION_MARK),
                'shown': 'react「%s」给 %s' % (face, label),
                'fields': {'action': {'kind': 'react', 'message_id': str(message_id), 'emoji_id': str(faces[face])}}}

    def _picture(self, ep, scene, artifact):
        """The attachment of a picture she may send here, or Refused in words."""
        from . import outbound_media
        from .blobs import BlobStore
        cls = self._place(ep)                  # what may go out is the conversation's (ADR-066: her pictures go anywhere)
        allowed, reason = outbound_media.target_allowed(self.store.config, scene, cls)
        if not allowed:
            raise Refused('发不了：%s' % ATTACH_REASONS.get(reason, reason))
        offered = (ep.get('context') or {}).get('image_artifacts_from_program') or {}
        if artifact not in {row.get('artifact_id') for row in offered.get('items') or [] if isinstance(row, dict)}:
            raise Refused('不在 image_artifacts_from_program 里')
        mine_only = outbound_media.own_only(self.store.config, scene, cls)
        return outbound_media.accept_artifact(self.store, BlobStore(self.store), artifact,
            [] if mine_only else outbound_media.image_scopes(self.store, self.store.config, scene, cls, ep.get('person_id')),
            produced_only=mine_only, here=(scene or {}).get('scope_key'))

    def tool_task_answer(self, ep, call_id, args):
        answer = self._text(args, 'answer', 20000)
        self.coordinator._update(self._fresh(ep), answer=answer)
        return {'answered': True}, True

    # ── the action brain ────────────────────────────────────────────
    def _depth(self, ep):
        if int(ep.get('delegation_depth') or 0) >= DELEGATION_DEPTH_MAX:
            raise Refused('这件事已经连着交给行动脑、拿回结果 %d 轮了，中间没有人说过话。先停下来：把进展说给对方听，'
                          '等对方开口再接着交。' % DELEGATION_DEPTH_MAX)

    def tool_delegate(self, ep, call_id, args):
        self._depth(ep)
        title = self._text(args, 'title', 80)
        from . import credentials
        brief = credentials.scrub(self._text(args, 'brief', 20000))     # a credential value never rides a brief
        from . import action_tiers
        tier = None
        if action_tiers.offered():
            try:
                tier = action_tiers.chosen(args)
            except ValueError as exc:
                raise Refused(str(exc))
        task = self.coordinator.delegate(ep, call_id, title, brief, tier=tier)
        from .tasks import queue_words
        return {'task': task['_id'], 'state': '已交给行动脑',
                **({'tier': task['tier_words']} if task.get('tier_words') else {}),
                'action_brain': '新开一份上下文：它只看得到这次的 brief 和对方的原话。',
                'queue': queue_words(self.store, task['_id']),
                'note': '结果回来会再叫你；在那之前不要说已经做完。'}, False

    def _own_task(self, ep, task_id):
        if not isinstance(task_id, str) or not task_id:
            raise Refused('task 要照抄 task_state_from_program 里的 _id。')
        task = self.store.db.tasks.find_one({'_id': task_id, 'scene_id': ep['scene_id'],
                                             'requester_id': ep['person_id'], 'policy_epoch': ep['policy_epoch']})
        if not task:
            # A task of this conversation that someone else asked for: say whose it is and when it can be steered or
            # stopped, rather than that it is not here (it is listed in task_state_from_program).
            theirs = self.store.db.tasks.find_one({'_id': task_id, 'scene_id': ep['scene_id'],
                                                   'policy_epoch': ep['policy_epoch']}, {'requester_id': 1})
            if theirs:
                from .people import People
                scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']}
                who = People(self.store, ep.get('persona')).speaker(scene, theirs['requester_id'])
                raise Refused(OTHERS_TASK % (task_id, who))
            close = [row['_id'] for row in self.store.db.tasks.find(
                {'scene_id': ep['scene_id'], 'requester_id': ep['person_id'], 'policy_epoch': ep['policy_epoch'],
                 '_id': {'$regex': '^' + __import__('re').escape(task_id[:12])}}, {'_id': 1}).limit(3)]
            raise Refused('「%s」不是这个对话里的任务%s。照 task_state_from_program 原样抄 _id。'
                          % (task_id, '；可能是：' + '、'.join(close) if close else ''))
        return task

    def tool_task_message(self, ep, call_id, args):
        self._depth(ep)
        task = self._own_task(ep, args.get('task'))
        from . import credentials
        message = credentials.scrub(self._text(args, 'message', 20000))
        outcome = self.coordinator.message_action(ep, call_id, task, message)
        return outcome, False

    def tool_task_stop(self, ep, call_id, args):
        task = self._own_task(ep, args.get('task'))
        reason = self._text(args, 'reason', 1000)
        if task['state'] not in ('READY', 'RUNNING', 'PAUSED'):
            return {'task': task['_id'], 'state': task['state'], 'note': '这件事已经不在进行中，不用叫停。'}, False
        stopped = self.coordinator.tasks.cancel(task['_id'], reason='character_stop', person_id=ep['person_id'])
        self.coordinator.collab(stopped, 'status', {'state': 'stopped', 'reason': reason})
        return {'task': stopped['_id'], 'state': stopped['state'], 'note': '已叫停。'}, False

    # ── speech ──────────────────────────────────────────────────────
    # ── looking ─────────────────────────────────────────────────────
    def tool_read_image(self, ep, call_id, args):
        from .blobs import BlobStore
        from .vision import read_image_for_task
        scene = {k: ep[k] for k in ('scene_id', 'scope_key', 'policy_epoch')}
        result = read_image_for_task(self.store, BlobStore(self.store), scene, self.store.config, args,
                                     route='character', offered=offered_pictures(self._fresh(ep)),
                                     session_class=self._cls(ep))        # 按路径读盘只在家里放行；这一轮没有任务目录
        ref = str((args or {}).get('ref') or '')
        if ref:                                       # what she looked at this turn (a candidate is kept only after)
            fresh = self._fresh(ep)
            self.coordinator._update(fresh, looked=[*dict.fromkeys([*(fresh.get('looked') or []), ref])])
        if isinstance(result, dict) and result.get('sticker'):
            result['sticker_note'] = STICKER_LOOKED_NOTE
        return result, False

    def tool_attach_image(self, ep, call_id, args):
        from . import outbound_media
        from .blobs import BlobStore
        artifact = self._text(args, 'artifact_id', 200)
        self._text(args, 'why', 500)
        cls = self._place(ep)
        scene = self.store.db.scenes.find_one({'_id': ep['scene_id']},
                                              {'_id': 1, 'channel_id': 1, 'kind': 1, 'scope_key': 1, 'members': 1})
        allowed, reason = outbound_media.target_allowed(self.store.config, scene, cls)
        if not allowed:
            raise Denied('ATTACH_TARGET_NOT_ALLOWED: %s；重试也一样，这回合只说话不带图'
                         % ATTACH_REASONS.get(reason, reason))
        offered = (ep.get('context') or {}).get('image_artifacts_from_program') or {}
        if artifact not in {row.get('artifact_id') for row in offered.get('items') or [] if isinstance(row, dict)}:
            raise Denied('ATTACH_ARTIFACT_NOT_IN_CONTEXT: ' + artifact)
        mine_only = outbound_media.own_only(self.store.config, scene, cls)
        meta = outbound_media.accept_artifact(self.store, BlobStore(self.store), artifact,
            [] if mine_only else outbound_media.image_scopes(self.store, self.store.config, scene, cls, ep.get('person_id')),
            produced_only=mine_only, here=(scene or {}).get('scope_key'))
        self.coordinator._update(self._fresh(ep), attachment=dict(meta))
        return {'attached': artifact, 'note': '这张图会随你这回合要说的话一起发出去。'}, False

    def tool_sticker(self, ep, call_id, args):
        from . import stickers
        from .blobs import BlobStore
        op = args.get('op')
        if op == 'keep' and args.get('candidate'):
            return stickers.keep_candidate(self.store, self._fresh(ep), ep['persona'], args), False
        if op == 'keep':
            return stickers.keep(self.store, BlobStore(self.store), ep, ep['persona'], args, self.store.config), False
        if op == 'drop':
            return stickers.drop(self.store, ep['persona'], args.get('name')), False
        if op == 'rename':
            return stickers.rename(self.store, ep['persona'], args.get('name'), args.get('new_name'), args.get('when')), False
        if op == 'remember':
            return stickers.remember(self.store, self._fresh(ep), ep['persona'], args, self.store.config), False
        if op == 'pool':
            from datetime import datetime, timezone
            listing = stickers.pool_listing(self.store, datetime.now(timezone.utc))
            fresh = self._fresh(ep)
            self.coordinator._update(fresh, pool_listed=[*dict.fromkeys([*(fresh.get('pool_listed') or []),
                                                                         *(item['candidate'] for item in listing['items'])])])
            return listing, False
        if op == 'shelf':
            # At home the shelf is listed only in the turns that tidy it; any other turn asks for it here.
            listed = stickers.block(self.store, ep['persona'],
                                    self.store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']},
                                    at_home=self._place(ep) == visibility.OWNER_PRIVATE)
            if not listed:
                return {'items': [], 'note': '架子是空的。'}, False
            # What it lists she may look at with read_image, as what pool lists (stickers.candidate_ids).
            fresh = self._fresh(ep)
            self.coordinator._update(fresh, pool_listed=[*dict.fromkeys([*(fresh.get('pool_listed') or []),
                                                                         *(item['ref'] for item in listed['items'] if item.get('ref'))])])
            return listed, False
        raise Refused('do 是 keep、drop、rename、remember、pool 或 shelf%s。' % _given(args, 'op'))

    # ── her own records ─────────────────────────────────────────────
    def tool_write_document(self, ep, call_id, args):
        from .render import budget_gate
        item = {k: v for k, v in args.items() if k != 'body' and v is not None}
        if not isinstance(item.get('doc'), str) or not item['doc']:
            raise Refused('doc 要写文档名，如 persona、voice、group_notes。')
        cls = self._cls(ep)
        if item['doc'] == 'group_notes':
            from .group_admin import notes_slug
            scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1})
            if (scene or {}).get('kind') != 'group' or item.get('op') not in group_note_ops():
                raise Denied('GROUP_NOTES_ONLY_IN_ITS_GROUP: ' + ('这里不是群' if (scene or {}).get('kind') != 'group'
                                                                  else 'do「%s」不行' % item.get('op')))
            item = {**item, 'doc': notes_slug(ep['scene_id'])}
        elif cls != visibility.OWNER_PRIVATE:
            raise Denied('DOC_WRITE_REQUIRES_OWNER_PRIVATE: doc「%s」；在群里能写的只有 doc=group_notes，别的回家里再改' % item['doc'])
        if item['doc'].startswith('group:'):
            # A group's notes are read in that group: always public. She may tuck a section away (on_demand), and
            # tidy them by name from her nightly settlement (context_budget.review_block).
            if item.get('op') not in group_note_ops():
                raise Denied('GROUP_NOTES_ONLY_IN_ITS_GROUP: do「%s」不行' % item.get('op'))
            item = {k: v for k, v in item.items() if k != 'kind'}    # a group's notes are notes, whatever kind says
            item = {**item, 'visibility': 'public'}
            if item['op'] == 'append_section' or 'inject' in item:
                item['inject'] = item['inject'] if item.get('inject') in ('always', 'on_demand') else 'always'
        docs = DocumentStore(self.store, ep['persona'])
        slug = item['doc']
        base, before = docs.read(slug)
        if isinstance(item.get('sid'), str):
            # The section as she named it (id, heading, or a heading's spelling only it has) becomes its id once,
            # so every check below reads the same section; an unknown name stays and is refused with the ids.
            from .documents import named_section
            named = named_section((before or {}).get('sections') or [], item['sid'])
            if named:
                item = {**item, 'sid': named['sid']}
        mutation_id = f"{ep['_id']}:write:{call_id}"
        from . import memory_tiers
        if memory_tiers.ENABLED:
            for field, allowed in (('nature', memory_tiers.NATURES), ('from', memory_tiers.SOURCES)):
                if item.get(field) is not None and item[field] not in allowed:
                    raise Refused('%s 写 %s 之一%s。' % (field, '、'.join(allowed), _given(item, field)))
        if item.get('op') == 'let_go' and memory_tiers.ENABLED:
            return self._let_go(ep, slug, item.get('sid'), before), False
        if memory_tiers.ENABLED and item.get('op') == 'replace_section' and item.get('sid'):
            verbatim = next((s.get('body') for s in (before or {}).get('sections') or [] if s['sid'] == item['sid']), None)
            dropped = memory_tiers.gist_refusal(memory_tiers.Tiers(self.store, ep['persona']).item(slug, item['sid']),
                                                verbatim, args.get('body'))
            if dropped:
                raise Refused(dropped)
        if memory_tiers.ENABLED and (item.get('nature') or item.get('from')):
            unsigned = memory_tiers.signing(memory_tiers.Tiers(self.store, ep['persona']).item(slug, item.get('sid'))
                                            if item.get('sid') else None, item, args.get('body'))
            if unsigned:
                raise Refused(unsigned)
        if (memory_tiers.ENABLED and item.get('op') == 'set_tags' and memory_tiers.declared_nature(item)
                and not any(field in item for field in ('visibility', 'inject', 'tags'))):
            # Only what an item is, or where it came from: kept beside it; the document is not written.
            from .documents import missing_section, named_section
            listed = (before or {}).get('sections') or []
            found = named_section(listed, item.get('sid'))
            if not found:
                raise DocumentError('DOC_SECTION_NOT_FOUND', missing_section(slug, item.get('sid'), listed))
            item = {**item, 'sid': found['sid']}
            tiers = memory_tiers.Tiers(self.store, ep['persona'])
            tiers.sync()
            tiers.written(slug, item, before, before, scene_id=ep['scene_id'])
            return {'doc': slug, 'op': 'set_tags', 'sid': item['sid'], 'note': '记下了：%s。'
                    % '、'.join(filter(None, (memory_tiers.declared_nature(item).get('nature'), item.get('from'))))}, False
        if item.get('op') == 'adopt_seed':
            kind, text = _seed_text(self.store, slug)
            if text is None:
                seeds = [seed.get('slug') for seed in (self.store.config.get('persona_contribution') or {}).get('seeds', [])]
                raise DocumentError('DOC_SEED_NOT_FOUND', '「%s」没有种子；有种子的文档：%s'
                                    % (slug, '、'.join(filter(None, seeds)) or '（人格包没带种子）'))
            outcome = docs.adopt_seed(slug, kind, text, base_revision_id=base, author='character',
                                      mutation_id=mutation_id, reason=item.get('reason') or 'adopt package seed')
            return {'doc': slug, 'op': 'adopt_seed', **{k: v for k, v in outcome.items() if k != 'revision'}}, False
        body = args.get('body') if item.get('op') in WRITE_STAGE_OPS else None
        revision = docs.apply(slug, item, body, base_revision_id=base, author='character', mutation_id=mutation_id,
                              budget=budget_gate(self.store, ep['persona']))
        result = {'doc': slug, 'op': item['op'], 'revision_id': revision['_id'], 'sid': item.get('sid'),
                  'heading': item.get('heading'), 'note': '已写下。'}
        after = docs.read(slug)[1]
        sections = (after or {}).get('sections', [])
        if memory_tiers.ENABLED:
            felt = any(call.get('tool') == 'feel' for call in (self._fresh(ep).get('tool_calls') or {}).values())
            tiers = memory_tiers.Tiers(self.store, ep['persona'])
            moves = tiers.written(slug, item, before, after, scene_id=ep['scene_id'], felt=felt, before_revision=base)

            if moves:
                result['moved'] = [memory_tiers.told(move) for move in moves]
            placed = memory_tiers.Tiers(self.store, ep['persona']).item(slug, result['sid']) if result['sid'] else None
            if item.get('inject') == 'always' and placed and placed['place'] != memory_tiers.CARRIED:
                result['place'] = memory_tiers.NOT_BACK % placed['place']
        if item['op'] in ('append_section', 'correction') and sections:
            result['sid'] = sections[-1]['sid']          # the new section's sid, for a later replace or set_tags
        written = next((s for s in sections if s['sid'] == result['sid']), None) if result['sid'] else None
        if written:
            # What the section is now, tags included: she checks a place tag took, not just that the write did.
            result['now'] = {'visibility': written['visibility'], 'inject': written['inject'], 'tags': written.get('tags') or [],
                             'places': visibility.section_places(written) or '到处都带'}
        return result, False

    def _let_go(self, ep, slug, sid, content):
        """ADR-062: her let_go of one item: one place down now; nothing of its text changes."""
        from . import memory_tiers
        from .documents import missing_section, named_section
        listed = (content or {}).get('sections') or []
        found = named_section(listed, sid) if isinstance(sid, str) else None
        if not found:
            raise DocumentError('DOC_SECTION_NOT_FOUND', missing_section(slug, sid, listed))
        sid = found['sid']
        tiers = memory_tiers.Tiers(self.store, ep['persona'])
        tiers.sync()
        move = tiers.let_go(slug, sid, scene_id=ep['scene_id'])
        return {'doc': slug, 'op': 'let_go', 'sid': sid,
                'note': memory_tiers.told(move) if move else '它已经收着了，再放就没有更下面的地方了；什么都没改。'}

    def tool_update_self(self, ep, call_id, args):
        from .self_state import SelfState
        from . import memory_tiers
        target = args.get('target')
        doc = {'current_self': memory_tiers.SELF_DOC, 'character_core': memory_tiers.CORE_DOC}.get(target)
        if memory_tiers.ENABLED and doc and DocumentStore(self.store, ep['persona']).read(doc)[1]:
            # ADR-062: once she has written herself as items, the old name writes an item: the one its sid names,
            # or a new one headed by what she gives (else her first line). The program never splits her text.
            body = self._text(args, 'body', SINGLE_BODY_CHARS)
            reason = self._text(args, 'reason', 2000)
            sid = args.get('sid')
            if sid:
                return self.tool_write_document(ep, call_id, {'doc': doc, 'op': 'replace_section', 'sid': sid,
                                                              'body': body, 'reason': reason})
            first = body.splitlines()[0].lstrip('-*·• ').strip()
            heading = (args.get('heading') or first)[:40]
            return self.tool_write_document(ep, call_id, {'doc': doc, 'op': 'append_section', 'heading': heading,
                                                          'body': body, 'reason': reason})
        body = self._text(args, 'body', SINGLE_BODY_CHARS)
        self._text(args, 'reason', 2000)
        committed = SelfState(self.store).commit(self._fresh(ep), target, body, mutation=f"self-state:{ep['_id']}:{call_id}")
        return {**committed, 'note': '已保存，之后的回合都能读到。'}, False

    def tool_understand_person(self, ep, call_id, args):
        from .memory import MemoryService
        from .queue import database_effects_lock
        from .tasks import require_current_feedback
        blocked = self._block(ep, args['block']) if args.get('block') is not None else None
        if blocked and args.get('body') is None:
            return blocked, False
        body = self._text(args, 'body', SINGLE_BODY_CHARS)
        layer = args.get('layer')
        if layer not in ('person', 'here'):
            raise Refused('UNDERSTANDING_LAYER_REQUIRED: layer 要写 person（人那层，哪儿都看得到）或 here（这里那层，只在这个对话里）；'
                          '给的是 %r。拿不准就问自己：这条换个群还成立吗，成立是 person，不成立是 here' % (layer,))
        if not ((ep.get('context') or {}).get('understanding_update_from_program') or {}).get('available'):
            raise Denied('UNDERSTANDING_UPDATE_NOT_AVAILABLE')
        field = 'understanding_update' if layer == 'here' else 'person_understanding_update'
        words = '这里那层' if layer == 'here' else '人那层'
        if (ep.get(field) or {}).get('state') == 'COMMITTED':
            raise Refused('这回合已经写过一次%s了，每层一回合只写一次；还有要补的，下回合再写。' % words)
        mutation = ep['_id'] + (':understanding' if layer == 'here' else ':understanding:person')
        saved = self.store.db.state_revisions.find_one({'mutation_id': mutation}, {'_id': 1})
        if saved:
            # Saved before this turn was interrupted: once per episode and layer, never a second revision.
            update = {'state': 'COMMITTED', 'accepted_revision': saved['_id']}
            self.coordinator._update(self._fresh(ep), **{field: update})
            return {'state': 'COMMITTED', 'note': '这回合中断前已经保存过%s。' % words}, False
        with database_effects_lock(self.store.name):
            require_current_feedback(self.store, ep)
            update = MemoryService(self.store).commit_understanding(self._fresh(ep), body, layer)
        self.coordinator._update(self._fresh(ep), **{field: update})
        result = {k: update.get(k) for k in ('state', 'reason') if update.get(k)}
        if blocked:
            result['block'] = blocked
        if update.get('state') == 'NOT_COMMITTED':
            result['note'] = UNDERSTANDING_NOT_SAVED.get(str(update.get('reason')).split(':', 1)[0],
                                                         '这次理解没存上（不是你的错）；重试也一样，下回合再更新。')
        return result, False

    def _mute(self, ep, scene, on, hours):
        """ADR-052: a group muted for a while: it rests, and she neither speaks first there nor visits."""
        from . import focus, switches
        from .people import People
        if scene.get('kind') != 'group':
            raise Refused('只有群能静音。')
        if on and focus.admin_here(self.store, scene, ep.get('persona')):
            raise Refused('你在这个群是管理员，它一直常驻（管理员要看得见群里的事），静音不了。')
        label = People(self.store, ep.get('persona')).scene_title(scene)
        if on:
            row = switches.set_switch(self.store, ep, 'mute', label=label, scene_id=scene['_id'], hours=hours)
            result = {'done': '%s静音了：只有叫到你才会醒，你不先开口、不去；到点自己结束' % label,
                      'until_at': row['until'], 'id': row['_id']}
        else:
            row = switches.muted(self.store, scene['_id'])
            if not row:
                return {'unchanged': '%s本来就没静音。' % label}
            switches.clear(self.store, ep, row['_id'])
            result = {'done': '%s不再静音，回到%s' % (label, '常驻' if focus.active(self.store, scene, ep.get('persona'))
                                                       else '歇着')}
        if focus._changed:
            try:
                focus._changed(scene['_id'])
            except Exception:                    # the title catches up at the next start; her choice stands
                pass
        return result

    def _block(self, ep, hours):
        """ADR-052: block the account speaking to her, outside home only (nobody at home can be blocked)."""
        from . import switches
        from .people import People
        if self._place(ep) == visibility.OWNER_PRIVATE:
            raise Refused('家里的人屏蔽不了：block_hours 只在家外的对话里用，屏蔽正在跟你说话的那个人。')
        scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}) or {'_id': ep['scene_id']}
        label = People(self.store, ep.get('persona')).speaker(scene, ep['person_id'])
        row = switches.set_switch(self.store, ep, 'block', label=label, person_id=ep['person_id'], hours=hours)
        return {'done': '屏蔽了%s：他的话照存，但哪儿都不叫你' % label, 'until_at': row['until'], 'id': row['_id']}

    def _switch_policy(self, ep, key, args, reason):
        """ADR-052: tools off in one conversation, or an early end to any switch."""
        from . import places, switches
        if key == 'switch_off':
            row = switches.clear(self.store, ep, args.get('value'))
            return {'done': '这个开关关了：%s' % switches.WORDS[row['kind']] + '：' + row['label']}
        place = self._text(args, 'place', 40)
        found = places.find(self.store.config, place)
        if not found:
            raise Refused('没有「%s」这个地方；place 照抄 places_from_program 或 group_focus 的 list 里的 place。' % place)
        tools = args.get('value')
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            raise Refused('tools_off 的 value 是工具名的列表（比如 ["sticker", "delegate"]）；空列表就是全部恢复。')
        unknown = [t for t in tools if t not in TOOLS or t in switches.KEEP]
        if unknown:
            raise Refused('这些关不了：%s（不是工具，或是一回合离不了的 think、recall、stay_silent）。' % '、'.join(unknown))
        scene = self.store.db.scenes.find_one({'_id': found[0]}) or {'_id': found[0]}
        from .people import People
        label = People(self.store, ep.get('persona')).scene_title(scene)
        current = switches.on(self.store, kind='tools_off', scene_id=found[0])
        if not tools:
            for row in current:
                switches.clear(self.store, ep, row['_id'])
            return {'done': '%s的工具都恢复了' % label}
        row = switches.set_switch(self.store, ep, 'tools_off', label=label, scene_id=found[0], tools=tools,
                                  hours=args.get('hours'), why=reason[:200])
        return {'done': '%s里关了：%s' % (label, '、'.join(row['tools'])), 'until_at': row['until'], 'id': row['_id']}

    def tool_set_policy(self, ep, call_id, args):
        from .policy import PolicyStore
        from .render import model_and_policy
        if self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Denied('POLICY_SET_REQUIRES_OWNER_PRIVATE')
        key = self._text(args, 'key', 200)
        reason = self._text(args, 'reason', 2000)
        if key in ('tools_off', 'switch_off'):
            return self._switch_policy(ep, key, args, reason), False
        from . import dice
        table = None
        if key in dice.KEYS.values():
            try:
                table = dice.words(dice.parse(args.get('value')))
            except ValueError as exc:
                raise Refused(str(exc)) from None
        if 'value' not in args:
            raise Refused('要写 value：这个参数的新值（类型照它的声明，比如整数、true/false）。')
        model, _ = model_and_policy(self.store, ep['persona'])
        policy = PolicyStore(self.store, ep['persona'], model)
        spec_what = policy.validate([{'key': key, 'value': args['value'], 'what': reason[:300]}])
        what = ((model.get('policy_keys') or {}).get(key) or {}).get('what') or spec_what[key]['what']
        revision = policy.set([{'key': key, 'value': args['value'], 'what': what}], base_revision_id=policy.read()[0],
                              reason=reason, author='character', mutation_id=f"{ep['_id']}:policy_set:{call_id}",
                              sources=[ep['source_event_id']])
        scheduler = self.coordinator.scheduler
        result = {'key': key, 'value': args['value'], 'revision_id': revision['_id'],
                  **({'stored_table': table} if table else {})}      # the whole table, so a name left out shows as 0
        if scheduler and hasattr(scheduler, 'ensure_presence') and key.startswith(('heartbeat.', 'rhythm.')):
            # A new rhythm takes effect through schedule_update, never delete + create.
            scheduler.ensure_presence()
            scheduler.ensure_settlement()
            if key == 'heartbeat.pause_min':
                from . import schedule_rules
                from .persona_model import timezone as persona_timezone
                until = scheduler.pause_presence(args['value'])
                zone, _ = persona_timezone(model, policy.params(), self.store.config)
                zone = zone if schedule_rules.is_iana(zone) else 'UTC'
                result['note'] = ('心跳会安静到 %s，然后自己恢复。' % schedule_rules.local_moment(zone, until).strftime('%H:%M')
                                  if until else '心跳已经恢复。')
        return result, False

    def tool_feel(self, ep, call_id, args):
        from .affect import AffectLedger, kind_label
        from .render import model_and_policy
        ledger = AffectLedger(self.store, ep['persona'], *model_and_policy(self.store, ep['persona']))
        if not ledger.enabled:
            raise Refused('你没有情感账（affect 没开），feel 用不了；重试也一样。')
        op, cls, key = args.get('op') or ('record' if args.get('kind') else None), self._cls(ep), 'feel:' + call_id
        fields = {k: v for k, v in args.items() if k in AFFECT_FIELDS and v is not None}
        if op == 'record':
            row = ledger.record(ep, 0, fields, cls, key=key)
            return {'event_id': row['_id'], 'feeling': kind_label(ledger.model, row.get('kind'))}, False
        if op in ('close', 'void'):
            event_id = self._text(args, 'event_id', 300)
            why = self._text(args, 'why', 500, required=op == 'void')
            ledger.amend(ep, 0, {'op': op, 'event_id': event_id, **({'why': why} if why else {})}, cls, key=key)
            return {'op': op, 'event_id': event_id}, False
        if op == 'adopt':
            item = {'proposal_id': self._text(args, 'proposal_id', 300), 'decision': args.get('decision'),
                    'why': self._text(args, 'why', 300)}
            if item['decision'] not in ('accept', 'decline', 'edit'):
                raise Refused('对提案，do 是 accept、decline 或 edit%s。' % _given(args, 'decision'))
            if item['decision'] == 'edit':
                if not isinstance(args.get('edit'), dict):
                    raise Refused('do=edit 时要写 edit：改成的样子（feeling、intensity、ref、why 这些字段）。')
                item['edit'] = args['edit']
            row = ledger.adopt(ep, 0, item, cls, key=key)
            return {'proposal_id': item['proposal_id'], 'decision': item['decision'],
                    'event_id': row['_id'] if row else None}, False
        raise Refused('do 是 record、close、void、accept、decline 或 edit%s；只记一笔心情时写 feeling 和 intensity 就行。' % _given(args, 'op'))

    def tool_plan(self, ep, call_id, args):
        from . import schedule_rules
        from .queue import database_effects_lock
        from .tasks import require_current_feedback
        c = self.coordinator
        if not c.scheduler:
            raise Refused('现在没有定时服务，安排不了（不是你的错）；重试也一样，要记着的事写进回话或文档。')
        timing = {k: args[k] for k in ('after_seconds', 'every_seconds', 'at', 'clock') if args.get(k) is not None}
        op = args.get('op') or ('create' if args.get('intent') and timing and not args.get('plan_id') else None)
        inferred = not args.get('op') and op == 'create'
        planned = {row.get('_id'): row for row in (ep.get('context') or {}).get('plans_from_program') or []}

        def run(action):
            with database_effects_lock(self.store.name):
                require_current_feedback(self.store, ep)
                return action()
        try:
            if op == 'create':
                spec = {'intent': self._text(args, 'intent', 1000), **timing}
                where = None
                if args.get('line'):
                    # From home, a plan may fire in one of her peer lines (owner 2026-10-06): both ends are home.
                    from . import lines
                    if self._cls(ep) != visibility.OWNER_PRIVATE:
                        raise Refused('只有在家里才能把安排挂到一条线上：去掉 place，就安排在这里。')
                    wanted = self._text(args, 'line', 80)
                    where = next((item for item in lines.peer_lines(self.store) if item['label'] == wanted), None)
                    if not where:
                        raise Refused('没有这条线；照抄 lines_from_program 里的 place。')
                plan = run(lambda: c.scheduler.create(ep, spec, plan_id='plan-' + sha(canonical([ep['_id'], call_id]))[:32],
                                                      where=where))
            elif op in ('update', 'cancel'):
                plan_id = self._text(args, 'plan_id', 200)
                # A plan made earlier in this turn is hers to change too, though the turn's list predates it.
                made = {(call.get('result') or {}).get('plan_id') for call in (ep.get('tool_calls') or {}).values()
                        if call.get('tool') == 'plan'}
                # Hers when listed or made this turn; the list shows a plan in words, so its state is read from the plan.
                row = (plan_id in planned or plan_id in made) and self.store.db.plans.find_one({'_id': plan_id})
                if not row:
                    # Her list shows a few plans; one of this conversation's that it leaves out is still hers (ADR-054).
                    kept = self.store.db.plans.find_one({'_id': plan_id, 'scene_id': ep['scene_id']})
                    if kept and kept.get('status') in ('CREATING', 'ACTIVE'):
                        row = kept
                    elif kept:
                        raise Refused('「%s」已经%s了，改不了；要再安排就新建一条（do=create）。'
                                      % (plan_id, {'CANCELLED': '取消', 'SUSPENDED': '停'}.get(kept.get('status'), '跑完')))
                    else:
                        raise Refused('「%s」不在 plans_from_program 里，也不是这回合刚建的；照列表原样抄 plan_id，'
                                      '或抄这回合 plan 工具返回的 plan_id。' % plan_id)
                if op == 'cancel':
                    plan = run(lambda: c.scheduler.cancel(plan_id, ep['scene_id'], ep['person_id'], ep['policy_epoch']))
                else:
                    if row.get('status') not in ('CREATING', 'ACTIVE'):
                        raise Refused('这条安排现在是 %s，改期只对着还生效的；要再安排就新建一条。' % row.get('status'))
                    spec = {**({'intent': args['intent']} if args.get('intent') else {}), **({'schedule': timing} if timing else {})}
                    plan = run(lambda: c.scheduler.update(ep, plan_id, spec))
            else:
                raise Refused('do 是 create、update 或 cancel%s；新建要写 intent 和一种计时，改或取消要写 plan_id。'
                              % _given(args, 'op'))
        except ValueError as exc:
            # 换算/校验类失败（时间已过、钟点不存在、形状不对）回给她自己改，带上现在的钟面。
            clock = schedule_rules.local_clock(schedule_rules.scene_timezone(
                self.store.config, self.store.db.scenes.find_one({'_id': ep['scene_id']})), schedule_rules.now_utc())
            raise Refused('没安排成：%s。现在是 %s（%s，%s）。' % (exc, clock['now_local'], clock['weekday'],
                                                            clock['timezone'])) from None
        return {'plan_id': plan['_id'], 'status': plan['status'], 'scheduled_at': plan.get('scheduled_at'),
                'next_fire_at': plan.get('next_fire_at'), 'timezone': plan.get('timezone'),
                'plan_version': plan.get('plan_version', 1),
                **({'note': '没写 do：有 intent 和计时、没有 plan_id，按新建（create）办了。'} if inferred else {})}, False

    def tool_group_action(self, ep, call_id, args):
        from . import group_admin
        item = {k: args[k] for k in ('kind', 'who', 'duration', 'which', 'reason') if args.get(k) is not None}
        if item.get('kind') in group_admin.ANSWERS:
            from . import notices
            if ep['scene_id'] != (self.store.config.get('chat') or {}).get('scene_id'):
                raise Denied('GROUP_ACTION_ANSWER_AT_HOME: accept 和 decline 只在家里回列出的请求；群里用 mute、unmute、recall、kick')
            return notices.answer(self.store, ep, item, key='group_action:' + call_id), False
        return group_admin.queue(self.store, ep, 0, item, key='group_action:' + call_id), False

    def tool_visit(self, ep, call_id, args):
        from . import places
        if turn_kind(ep) not in VISIT_FROM or self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Refused('只有在家里的心跳或你自己定的计划到期时才能出门：想去就用 plan 定个时间。')
        from .persona_model import effective
        from .render import model_and_policy
        model, policy = model_and_policy(self.store, ep['persona'])
        per_beat = int(effective(model, 'heartbeat.visits_per_beat', policy) or 1)
        went = sum(1 for call in (ep.get('tool_calls') or {}).values() if call.get('tool') == 'visit' and 'result' in call)
        if went >= per_beat:
            raise Refused('这一拍已经出过 %d 次门了（heartbeat.visits_per_beat）；下一拍再去别处。' % went)
        place = self._text(args, 'place', 40)
        intent = args.get('intent')
        if intent not in places.VISIT_INTENTS:
            raise Refused('intent 是 %s 之一%s。' % ('、'.join(places.VISIT_INTENTS), _given(args, 'intent')))
        topic = self._text(args, 'topic', places.TOPIC_CHARS, required=False)
        artifact = self._text(args, 'artifact_id', 200, required=False)
        if artifact and intent != 'share_picture':
            raise Refused('只有 intent=share_picture 才带 artifact_id。')
        if not self.coordinator.scheduler:
            raise Refused('现在没有定时服务，出不了门（不是你的错）；重试也一样。')
        return self.coordinator.scheduler.visit(ep, place, intent, topic, artifact), False

    def tool_errand(self, ep, call_id, args):
        from .places import ERRAND_CHARS
        if self._place(ep) != visibility.OWNER_PRIVATE:
            raise Denied('ERRAND_ONLY_AT_HOME')
        if turn_kind(ep) not in ERRAND_FROM:
            raise Denied('ERRAND_ONLY_WHEN_ASKED')
        place = self._text(args, 'place', 40)
        request = self._text(args, 'request', ERRAND_CHARS)
        artifact = self._text(args, 'artifact_id', 200, required=False)
        if not self.coordinator.scheduler:
            raise Refused('现在没有定时服务，办不了（不是你的错）；重试也一样，跟托你的人说一声。')
        return self.coordinator.scheduler.errand(ep, call_id, place, request, bool(args.get('exactly')), artifact), False

    # ── notes between her conversations (ADR-018) ───────────────────
    def _note(self, ep, call_id, args, cls):
        from . import credentials, notes
        if not self.coordinator.scheduler:
            raise Refused('现在没有定时服务，便条送不出去（不是你的错）；重试也一样。')
        args = {**args, 'text': credentials.scrub(str(args.get('text') or ''))}     # never a credential value
        try:
            return self.coordinator.scheduler.note(ep, cls, args, call_id), False
        except notes.NoteRefused as exc:
            self.store.audit(ep['_id'], 'note.refused', {'code': exc.code, 'to': str(args.get('to') or '')[:40]},
                             ep['scope_key'])
            raise Refused(str(exc)) from None

    def tool_note(self, ep, call_id, args):
        # Trust is the program's: from the conversation the note is written in (notes.trust_of), never from the call.
        qid = args.get('question')
        if self._place(ep) == visibility.OWNER_PRIVATE:
            if qid is not None:
                raise Refused('question 是在群里把问到的回答带回家用的；家里的便条不写它。')
            return self._note(ep, call_id, args, visibility.OWNER_PRIVATE)
        if qid is not None:
            # ADR-061 step 2 (her answer a): a group's answer goes home in her words; the program adds who and where.
            row = self.store.db.questions.find_one({'_id': str(qid), 'persona': ep['persona']})
            if not row or not any(s.get('kind') == 'group' and s.get('scene_id') == ep['scene_id'] for s in row['sources']):
                raise Refused('question「%s」不是你在这里问的问题：照抄 questions_from_program 里的 q-…' % qid)
            args = {**args, 'answers': row['_id']}
        return self._note(ep, call_id, {k: v for k, v in args.items() if k != 'question'}, visibility.PUBLIC)

    # ── her own peer lines (ADR-013 §6) ─────────────────────────────
    def tool_restart(self, ep, call_id, args):
        from . import restarts
        from .persona_model import timezone as persona_zone
        from .render import model_and_policy
        desk = restarts.DESK
        if desk is None:
            raise Refused('这个宿主没有接重启请求的地方（不是正常起来的宿主）；要重启跟主人说。')
        # A restart is consequential: an argument it does not know is refused, never dropped (2026-10-10 her `at`
        # was silently ignored and the request fell back to an immediate quiet restart).
        unknown = sorted(set(args) - {'op', 'why', 'when'})
        if unknown:
            raise Refused('restart 不认识参数 %s：只收 do、why、when（时刻写在 when 里，如 when=23:55）；这次什么都没做。'
                          % '、'.join(unknown))
        model, policy = model_and_policy(self.store, ep['persona'])
        desk.zone = persona_zone(model, policy, self.store.config)[0]
        op = args.get('op')
        if op == 'preview':
            return desk.preview(), False
        if op == 'cancel':
            had = desk.cancel()
            return {'cancelled': bool(had), 'note': '撤回了。' if had else '没有在等的重启请求。'}, False
        if op not in ('request', 'drill'):
            raise Refused('do 是 preview、request、drill 或 cancel%s。' % _given(args, 'op'))
        why = self._text(args, 'why', 200)
        from .people import People
        where = People(self.store, ep['persona']).scene_title(self.store.db.scenes.find_one({'_id': ep['scene_id']}))
        try:
            pending = desk.request(why, args.get('when') or 'quiet', drill=op == 'drill', where=where)
        except PermissionError as exc:
            raise Refused(str(exc))
        except ValueError as exc:
            raise Refused(str(exc))
        when = {'now': '下一刻就停', 'quiet': '等没有在跑的回合、任务和排队消息（最多 30 分钟）'}.get(
            pending['when'], '到 %s 后再等安静' % pending['when'])
        replaced = pending.get('replaced')
        return {'queued': True, 'when': when, 'drill': pending['drill'],
                **({'replaced': '顶掉了原来排着的那个：' + restarts.waiting_words(replaced, restarts._zone(desk.zone))} if replaced else {}),
                'note': '交给监工了。排着的时候，你在家里的每一回合都在 restart_from_program 里看得到它；起来以后结果也在那里；'
                        '退回旧版本会马上叫你。'}, False

    def tool_peer_line(self, ep, call_id, args):
        from . import lines
        from .persona_model import timezone as persona_zone
        from .render import model_and_policy
        wanted = self._text(args, 'line', 80)
        line = next((item for item in lines.peer_lines(self.store) if item['label'] == wanted), None)
        if not line:
            raise Refused('没有这条线；照抄 lines_from_program 里的 place。')
        op = args.get('op')
        if op not in ('open', 'close'):
            raise Refused('do 是 open 或 close%s。' % _given(args, 'op'))
        if op == 'close' and args.get('close_for') not in lines.CLOSE_FOR:
            raise Refused('关的时候要选 close_for：%s%s。' % ('、'.join(lines.CLOSE_FOR), _given(args, 'close_for')))
        model, policy = model_and_policy(self.store, ep['persona'])
        zone = persona_zone(model, policy, self.store.config)[0]
        lines.set_line(self.store, line['scene_id'], closed=op == 'close', choice=args.get('close_for'), zone=zone,
                       by='character:' + ep['_id'])
        return {'line': line['label'], 'state': lines.describe(lines.closed_until(self.store, line['scene_id']), zone)}, False

    # ── her improvement ideas (ADR-011 §6.2) ────────────────────────
    def tool_ideas_note(self, ep, call_id, args):
        idea = self._text(args, 'idea', IDEA_CHARS)
        why = self._text(args, 'why', IDEA_CHARS)
        noted = [call for call in (ep.get('tool_calls') or {}).values()
                 if ability(call.get('tool'), call) == 'ideas.note' and 'result' in call]
        if len(noted) >= IDEAS_PER_TURN:
            raise Refused('这回合已经记了 %d 条想法（上限 %d 条），先到这里；别的下回合再记。' % (len(noted), IDEAS_PER_TURN))
        row = note_idea(self.store, ep['persona'], idea, why, key=[ep['_id'], call_id],
                        source={'by': 'character', 'scene_id': ep['scene_id'], 'episode_id': ep['_id'],
                                'turn': turn_kind(ep)})
        return {'noted': row['_id'], 'note': '记下了。它会在你的自我改进时间里再拿出来，现在不用去改。'}, False

    def tool_private_words(self, ep, call_id, args):
        from . import private_words
        try:
            return private_words.run(args, home=self._cls(ep) == visibility.OWNER_PRIVATE), False
        except private_words.PrivateWordsError as exc:
            raise Refused(str(exc)) from exc

    def tool_group_focus(self, ep, call_id, args):
        from . import focus, places
        op = args.get('op')
        if op not in ('list', 'active', 'rest', 'condense', 'keep', 'mute', 'unmute'):
            raise Refused('do 是 list、active、rest、condense、keep、mute 或 unmute%s。' % _given(args, 'op'))
        if op in ('mute', 'unmute') and self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Refused('静音在家里定（家里的对话里用 group_focus，place 写那个群）；在群里只能让它常驻或歇着。')
        if op in ('condense', 'keep') and not (turn_kind(ep) in CONDENSE_TURNS or (
                turn_kind(ep) in CONDENSE_AT_HOME and self._cls(ep) == visibility.OWNER_PRIVATE)):
            raise Refused(CONDENSE_REFUSED)
        if op == 'list':
            return {'groups': focus.listing(self.store, ep['persona']), 'usual': '平常常驻 %d 个以内' %
                    focus.soft_limit(self.store.config)}, False
        place = self._text(args, 'place', 40, required=False)
        here = self.store.db.scenes.find_one({'_id': ep['scene_id']})
        if place:
            found = places.find(self.store.config, place)
            if not found:
                raise Refused('没有「%s」这个群；place 照抄 group_focus 的 list 或 places_from_program 里的 place。' % place)
            scene = self.store.db.scenes.find_one({'_id': found[0]})
        elif (here or {}).get('kind') == 'group':
            scene = here
        else:
            raise Refused('在家里要写 place：照抄 group_focus 的 list 或 places_from_program 里的 place。')
        if not scene:
            raise Refused('这个群还没有记录（还没人在那儿说过话）；等有人说话以后再改。')
        if op in ('condense', 'keep'):
            from . import condense
            if scene.get('kind') != 'group':
                raise Refused('只有群的对话能这样压。')
            if op == 'keep':
                return condense.unmark(self.store, scene, ep), False
            answer = condense.mark(self.store, scene, ep)
            scheduler = getattr(self.coordinator, 'scheduler', None)
            if scheduler:                     # the home plan that looks every few minutes while a group is marked
                scheduler.ensure_condense()
            return answer, False
        if op in ('mute', 'unmute'):
            return self._mute(ep, scene, op == 'mute', args.get('hours')), False
        try:
            return focus.set_focus(self.store, ep, scene, op == 'active', ep['persona']), False
        except ValueError as exc:
            raise Refused(str(exc)) from None

    def tool_place_timezone(self, ep, call_id, args):
        from datetime import datetime, timezone
        from . import places
        moment = datetime.now(timezone.utc)
        op = args.get('op')
        if op == 'list':
            return {'groups': places.zones(self.store, ep['persona'], moment)}, False
        if op not in ('set', 'clear'):
            raise Refused('do 是 list、set 或 clear%s。' % _given(args, 'op'))
        place = self._text(args, 'place', 40)
        name = self._text(args, 'timezone', 64) if op == 'set' else None
        try:
            scene_id = places.set_zone(self.store, place, name)
        except ValueError as exc:
            raise Refused(str(exc)) from exc
        self.store.audit(ep['_id'], 'place.timezone', {'scene_id': scene_id, 'timezone': name}, ep['scope_key'])
        row = next(row for row in places.zones(self.store, ep['persona'], moment) if row['place'] == place)
        return {**row, 'note': '设好了，「那边是不是夜里」从现在起按这个算。' if name else '撤掉了，这个群照旧按宿主的钟算。'}, False

    def tool_find_member(self, ep, call_id, args):
        from . import group_members
        scene = self.store.db.scenes.find_one({'_id': ep['scene_id']})
        return group_members.find(self.store, scene, ep['persona'], self._text(args, 'name', 20)), False

    # ── her questions (ADR-061) ─────────────────────────────────────
    def _ask_place(self, ep, wanted, homes_only=True):
        """One `to` entry as a source: this conversation, another home place a note reaches, or the action brain."""
        from . import notes, places, questions
        from .people import People
        people = People(self.store, ep['persona'])
        wanted = ' '.join(str(wanted or '').split())
        if wanted in questions.HERE or wanted == places.place_id(ep['scene_id']):
            scene = self.store.db.scenes.find_one({'_id': ep['scene_id']})
            return {'to': places.place_id(ep['scene_id']), 'scene_id': ep['scene_id'], 'kind': 'here',
                    'name': people.scene_title(scene)}
        if wanted == questions.ACTION:
            return {'to': questions.ACTION, 'kind': 'action', 'name': questions.ACTION}
        found = notes.allowed(self.store, ep['scene_id'], visibility.OWNER_PRIVATE, notes.opening(self.store, ep))
        place = notes._resolve(self.store, ep['persona'], found, wanted, visibility.OWNER_PRIVATE)
        homes = {p: sid for p, (sid, kind) in found.items() if kind == 'home'}
        if place and (place in homes or not homes_only):
            scene = self.store.db.scenes.find_one({'_id': found[place][0]})
            return {'to': place, 'scene_id': found[place][0], 'kind': 'home', 'name': people.scene_title(scene)}
        names = '、'.join('%s（%s）' % (people.scene_title(self.store.db.scenes.find_one({'_id': sid})), p)
                         for p, sid in homes.items())
        if place:
            raise Refused('ASK_PLACE_NOT_HOME: 「%s」不是家里的对话：ask 问的是家里的几处（%s）、这里和行动脑；'
                          '在群里或别人的私聊里问，用 note 送过去，到那边自己问。' % (wanted, names or '没有别处'))
        raise Refused('ASK_PLACE_UNKNOWN: 问不到「%s」：to 写 %s这里，或 行动脑。' % (wanted, names + '、' if names else ''))

    def tool_ask_ask(self, ep, call_id, args):
        from . import credentials, ingress, notes, questions
        from .questions import QUESTION_CHARS
        text = credentials.scrub(self._text(args, 'question', QUESTION_CHARS))
        patience = args.get('patience') or questions.DEFAULT_PATIENCE
        if patience not in questions.PATIENCE:
            raise Refused('ASK_PATIENCE_UNKNOWN: patience 是 %s 之一%s；不写就是 %s。'
                          % ('、'.join(questions.PATIENCE), _given(args, 'patience'), questions.DEFAULT_PATIENCE))
        wanted = args.get('to')
        wanted = [wanted] if isinstance(wanted, str) else wanted
        if not isinstance(wanted, list) or not wanted or not all(isinstance(w, str) and w.strip() for w in wanted):
            raise Refused('ASK_TO_REQUIRED: to 写问谁（一到 %d 处）：note_places_from_program 里家里的 place、这里，或 行动脑。'
                          % questions.PLACES_MAX)
        wanted = list(dict.fromkeys(' '.join(w.split()) for w in wanted))
        if len(wanted) > questions.PLACES_MAX:
            raise Refused('ASK_TOO_MANY: 一个问题最多问 %d 处，写了 %d 处：挑最想问的。' % (questions.PLACES_MAX, len(wanted)))
        sources = [self._ask_place(ep, w) for w in wanted]
        if any(source['kind'] == 'action' for source in sources) and 'delegate' not in (ep.get('turn_tools') or ()):
            raise Refused('ASK_NO_ACTION_BRAIN: 这一回合不能交给行动脑，问不了它；问别处，或者等能交事的回合。')
        qid = questions.question_id([ep['_id'], call_id])
        row = self.store.db.questions.find_one({'_id': qid})
        if not row:
            for source in sources:
                if source['kind'] == 'here':
                    source['episode'] = ep['_id']
                elif source['kind'] == 'home':
                    if not self.coordinator.scheduler:
                        raise Refused('ASK_NOT_SENT: 现在没有定时服务，问不过去（不是你的错）；重试也一样，先问这里。')
                    try:
                        sent = self.coordinator.scheduler.note(
                            ep, visibility.OWNER_PRIVATE, {'to': source['to'], 'mode': 'wake',
                                                           'text': questions.NOTE_TEXT % (qid, text)},
                            '%s:ask:%s' % (call_id, source['to']), question=qid)
                    except notes.NoteRefused as exc:
                        raise Refused('ASK_NOT_SENT: 问不到「%s」：%s' % (source['name'], exc)) from None
                    note = self.store.db.notes.find_one({'_id': sent['note']})
                    source['note'] = note['_id']
                    source['episode'] = ingress.episode_id({'scene_id': note['to_scene'], 'event_id': note.get('event_id'),
                                                            'episode_kind': 'note'})
                else:
                    self._depth(ep)
                    task = self.coordinator.delegate(ep, '%s:ask' % call_id, ' '.join(text.split())[:80],
                                                     questions.BRIEF % text)
                    source['task'] = task['_id']
            row = questions.record(self.store, ep, qid, text, patience, sources)
        return {'id': qid, 'to': [questions.place_words(source) for source in row['sources']],
                'note': questions.ASKED}, False

    def tool_ask_read(self, ep, call_id, args):
        from . import questions
        qid = self._text(args, 'id', 40, required=False)
        if qid:
            found = questions.read(self.store, ep['persona'], qid,
                                   outside=self._cls(ep) != visibility.OWNER_PRIVATE)
            if not found:
                raise Refused('ASK_QUESTION_UNKNOWN: 没有「%s」这个问题：id 照抄 questions_from_program 或 ask 的结果。' % qid)
            return found, False
        wanted = args.get('to')
        wanted = wanted[0] if isinstance(wanted, list) and len(wanted) == 1 else wanted
        if not isinstance(wanted, str) or not wanted.strip():
            raise Refused('ASK_READ_WHAT: read 写 id（读一个问题的回答），或只写一处 to（看以前问那处怎样）。')
        source = self._ask_place(ep, wanted, homes_only=False)
        return questions.history(self.store, ep['persona'], None if source['kind'] == 'action' else source['scene_id'],
                                 source['name']), False

    def tool_ask_close(self, ep, call_id, args):
        from . import questions
        from .questions import TOOK_CHARS
        qid = self._text(args, 'id', 40)
        took = self._text(args, 'took', TOOK_CHARS)
        row, words = questions.close(self.store, ep['persona'], qid, took)
        if not row:
            raise Refused('ASK_QUESTION_UNKNOWN: 没有「%s」这个问题：id 照抄 questions_from_program 或 ask 的结果。' % qid)
        return {'id': qid, 'closed': words}, False

    def tool_ideas_read(self, ep, call_id, args):
        from . import schedule_rules
        try:
            page = int(args.get('page') or 1)
        except (TypeError, ValueError):
            raise Refused('page 是从 1 开始的整数%s。' % _given(args, 'page')) from None
        search = self._text(args, 'search', 40, required=False)
        total = len(idea_rows(self.store, ep['persona'], search))
        pages = max(1, -(-total // IDEAS_PAGE))
        if page < 1 or page > pages:
            raise Refused('只有 %d 页（%d 条）：page 写 1–%d。' % (pages, total, pages))
        items = ideas_block(self.store, ep['persona'], schedule_rules.now_utc(), page=page, search=search)
        after = total - (page - 1) * IDEAS_PAGE - len(items)
        if not items:
            note = ('没有带「%s」的、还没处理完的想法。' % search) if search else '想法本里没有还没处理完的想法。'
        else:
            note = '逐条用 ideas 的 review 写下处理结果；采纳的用 delegate 交代行动脑去做。'
        return {'items': items, 'page': '第 %d 页，共 %d 页（%d 条%s）' % (page, pages, total,
                                                                        '带「%s」' % search if search else ''),
                **({'more': '后面还有 %d 条：page=%d 接着看。' % (after, page + 1)} if after > 0 else {}),
                'note': note}, False

    def tool_task_page(self, ep, call_id, args):
        from .tasks import report_pages
        unknown = sorted(set(args) - {'op', 'task', 'page'})
        if unknown:
            raise Refused('task 的 page 不认识参数 %s：只收 task 和 page。' % '、'.join(unknown))
        task_id = self._text(args, 'task', 80)
        try:
            page = int(args.get('page'))
        except (TypeError, ValueError):
            raise Refused('page 是从 1 开始的整数%s。' % _given(args, 'page')) from None
        # At home every task of hers; anywhere else only the tasks this conversation sent (as reading a file by path).
        home = self._cls(ep) == visibility.OWNER_PRIVATE
        where = {'_id': task_id} if home else {'_id': task_id, 'scene_id': ep['scene_id'], 'scope_key': ep['scope_key'],
                                                'policy_epoch': ep['policy_epoch']}
        task = self.store.db.tasks.find_one(where, {'result.text': 1, 'title': 1, 'goal': 1})
        if not task:
            raise Refused('「%s」不是%s的任务；task 照抄交回来的结果里的 task，或 task_state_from_program 里的 id。'
                          % (task_id, '你' if home else '这个对话里'))
        text = (task.get('result') or {}).get('text')
        if not isinstance(text, str) or not text:
            raise Refused('这个任务还没有报告：它还在跑，或者没交回文字。')
        pages = report_pages(text)
        if not 1 <= page <= len(pages):
            raise Refused('这份报告共 %d 页：page 写 1–%d。' % (len(pages), len(pages)))
        from . import machine_words
        # Outside home a report holds nothing of the machine (ADR-050): the hand-back's rule, page by page.
        return {'task': task_id, 'title': task.get('title') or task.get('goal'),
                'page': '第 %d/%d 页（原文 %d 字）' % (page, len(pages), len(text)),
                'text': pages[page - 1] if home else machine_words.text(pages[page - 1]),
                'more': 'page=%d 接着读' % (page + 1) if page < len(pages) else '报告到这里完了'}, False

    def tool_ideas_review(self, ep, call_id, args):
        idea_id = self._text(args, 'id', 200)
        decision = args.get('decision')
        why = self._text(args, 'why', IDEA_CHARS)
        if decision not in ('adopt', 'defer', 'drop'):
            raise Refused('decision 是 adopt、defer 或 drop%s。' % _given(args, 'decision'))
        row = self.store.db.ideas.find_one({'_id': idea_id, 'persona': ep['persona']})
        if not row or row.get('state') not in ('open', 'deferred'):
            raise Refused('「%s」不是想法本里还没处理完的一条；照 ideas_from_program 或 ideas 的 read 里的原样抄 _id。' % idea_id)
        state = {'adopt': 'adopted', 'defer': 'deferred', 'drop': 'dropped'}[decision]
        from .state import now
        self.store.put('ideas', {**row, 'state': state, 'decisions': [*(row.get('decisions') or []),
            {'decision': decision, 'why': why, 'episode_id': ep['_id'], 'at': now()}]},
            expected=row['revision'], stream=idea_id)
        note = {'adopt': '采纳了：用 delegate 把要做的事交代给行动脑。', 'defer': '暂缓了，下次自我改进时还会看到它。',
                'drop': '放弃了，理由已留档。'}[decision]
        return {'idea': idea_id, 'state': state, 'note': note}, False

    def tool_promote_memory(self, ep, call_id, args):
        item = {k: args[k] for k in ('fact', 'appraisal', 'signal', 'why', 'source_ids', 'visibility', 'about')
                if args.get(k) is not None}
        from . import memory_tiers
        if item.get('about') is not None and (not memory_tiers.ENABLED or item['about'] not in memory_tiers.ABOUT):
            raise Refused('about 写 %s 之一%s。' % ('、'.join(memory_tiers.ABOUT), _given(item, 'about')))
        for field in ('fact', 'appraisal', 'signal', 'why'):
            self._text(item, field, 2000)
        if not isinstance(item.get('source_ids'), list) or not item['source_ids'] or not all(
                isinstance(x, str) for x in item['source_ids']):
            raise Refused('source_ids 是来源 id 的列表（至少一条，都是文字）：照抄 promotion_candidates 里的 id。')
        return promote(self.store, ep, item, key='promote:' + call_id), False


def note_idea(store, persona, idea, why, *, key, source):
    """One entry in her improvement-idea notebook, from either brain; read only in her self-improvement turns."""
    from .state import now
    idea_id = 'idea-' + sha(canonical(key))[:32]
    row = store.db.ideas.find_one({'_id': idea_id})
    if not row:
        row = store.put('ideas', {'_id': idea_id, 'persona': persona, 'idea': idea, 'why': why, 'state': 'open',
                                  'source': source, 'decisions': [], 'created_at': now(),
                                  'scope_key': visibility.owner_private_scope(persona)}, stream=idea_id)
    return row


def idea_rows(store, persona, search=None):
    """Her undecided ideas in reading order: open ones first (oldest first), then deferred ones, so ideas she put
    off never crowd out new ones. search keeps those whose idea or reason contains it."""
    import re
    query = {'persona': persona}
    if search:
        query['$or'] = [{'idea': {'$regex': re.escape(search)}}, {'why': {'$regex': re.escape(search)}}]
    return [row for state in ('open', 'deferred')
            for row in store.db.ideas.find({**query, 'state': state}).sort('created_at', 1)]


def ideas_block(store, persona, moment, limit=None, page=1, search=None):
    """Her notebook in words, one page (ideas_left counts what the first page leaves out)."""
    from datetime import datetime
    from .config import ago
    from .people import People
    people = People(store, persona)
    limit = limit or IDEAS_PAGE
    rows = idea_rows(store, persona, search)[(page - 1) * limit:page * limit]
    items = []
    for row in rows:
        try:
            hours = (moment - datetime.fromisoformat(row['created_at'])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            hours = None
        source = row.get('source') or {}
        scene = store.db.scenes.find_one({'_id': source['scene_id']}) if source.get('scene_id') else None
        items.append({'_id': row['_id'], 'idea': row['idea'], 'why': row['why'],
                      'from': '你自己' if source.get('by') == 'character' else '行动脑做事时',
                      **({'where': people.scene_title(scene)} if scene else {}),      # ADR-018 §5.8
                      **({'at': row['created_at']} if hours is not None else {}),
                      **({'deferred_before': row['decisions'][-1]['why']} if row.get('state') == 'deferred' and row.get('decisions') else {})})
    return items


def ideas_left(store, persona, shown):
    """Words for the open or deferred ideas a listing of ``shown`` items leaves out, or None."""
    waiting = store.db.ideas.count_documents({'persona': persona, 'state': {'$in': ['open', 'deferred']}})
    return ('还有 %d 条没列出：ideas 的 read 翻页（page）或按字找（search），处理掉几条也会轮到它们。' % (waiting - shown)
            if waiting > shown else None)


def _seed_text(store, slug):
    for seed in (store.config.get('persona_contribution') or {}).get('seeds', []):
        if seed.get('slug') == slug:
            return seed['kind'], Path(seed['path']).read_text(encoding='utf-8')
    return None, None


def read_sections(store, ep, items, cls):
    """recall with sections: readable section text, and what could not be read (in words)."""
    from . import forwards
    docs, out, missing = DocumentStore(store, ep['persona']), [], []
    for item in items:
        if item['doc'] == forwards.DOC:
            section, why = forwards.read(store, ep['scene_id'], item['sid'])
            out.append(section) if section else missing.append(why)
            continue
        _, content = docs.read(item['doc'])
        from .documents import named_section
        section = named_section((content or {}).get('sections', []), item['sid'])
        if not section:
            missing.append('%s#%s：没有这一节' % (item['doc'], item['sid']))
        elif not visibility.readable(section['visibility'], cls):
            missing.append('%s#%s：这里读不到' % (item['doc'], item['sid']))
        else:
            out.append({'doc': item['doc'], 'sid': section['sid'], 'heading': section['heading'],
                        'body': section['body'], 'visibility': section['visibility']})
            from . import memory_tiers
            if memory_tiers.ENABLED:
                # A gist reads with the verbatim it stands for.
                verbatim = memory_tiers.detail(store, ep['persona'], memory_tiers.Tiers(store, ep['persona']).item(
                    item['doc'], section['sid']))
                if verbatim:
                    out[-1]['detail'] = verbatim
    return out, missing


def _from_home(store, persona, source_ids, episodes):
    """Whether any source of a promotion was said in an owner-private conversation: a source turn's class, or a
    memory unit kept in her home scope."""
    home_scope = visibility.owner_private_scope(persona)
    if store.db.memory_units.find_one({'_id': {'$in': list(source_ids)}, 'scope_key': home_scope}, {'_id': 1}):
        return True
    for row in store.db.episodes.find({'_id': {'$in': list(episodes)}}, {'manifest.session_class': 1, 'scene_id': 1,
                                                                          'person_id': 1}):
        cls = (row.get('manifest') or {}).get('session_class')
        if cls is None:
            scene = store.db.scenes.find_one({'_id': row.get('scene_id')}) or {'_id': row.get('scene_id')}
            cls = visibility.session_class(store.config, store.db, scene, row.get('person_id'))
        if cls == visibility.OWNER_PRIVATE:
            return True
    return False


def promote(store, ep, item, *, key):
    """Settlement only: quota, ≥ min_roots different turns and ≥ min_dates local dates behind the sources."""
    from .config import character_id
    from .persona_model import effective, timezone as persona_timezone
    from .render import model_and_policy
    from .rhythm import episode_dates, selections
    if ep.get('episode_kind') != 'settlement':
        raise Denied('PROMOTE_ONLY_IN_SETTLEMENT')
    model, policy = model_and_policy(store, ep['persona'])
    quota = int(effective(model, 'memory.promotion.daily_quota', policy) or 0)
    promoted = [call for call in (ep.get('tool_calls') or {}).values()
                if call.get('tool') == 'promote_memory' and 'result' in call]
    if len(promoted) >= quota:
        raise Denied('PROMOTION_QUOTA: ' + ('已经提升了 %d 条，配额 %d 条；剩下的留到下次沉淀' % (len(promoted), quota) if quota
                                           else '配额是 0（没开记忆提升）；重试也一样'))
    from . import memory_tiers
    window = effective(model, 'memory.promotion.window_days', policy) or 7
    # With tiered memory on, its candidates are what she recalled in different conversations (her acts).
    picked = memory_tiers.recalled(store, window) if memory_tiers.ENABLED else selections(store, window)
    episodes = set()
    for source in item['source_ids']:
        unit = store.db.memory_units.find_one({'_id': source}, {'episode_id': 1})
        if store.db.episodes.find_one({'_id': source}, {'_id': 1}):
            episodes.add(source)
        elif source.startswith('in-') and store.db.episodes.find_one({'_id': source[3:]}, {'_id': 1}):
            episodes.add(source[3:])
        elif unit:
            episodes.update([unit['episode_id']] if unit.get('episode_id') else picked.get(source, []))
    zone, _ = persona_timezone(model, policy, store.config)
    dates = set(episode_dates(store, episodes, zone).values())
    need_roots = int(effective(model, 'memory.promotion.min_roots', policy) or 2)
    need_dates = int(effective(model, 'memory.promotion.min_dates', policy) or 2)
    if len(episodes) < need_roots or len(dates) < need_dates:
        raise Denied('PROMOTION_SOURCES_INSUFFICIENT: 这些来源只来自 %d 个回合、%d 个日期，要至少 %d 个回合、%d 个日期；'
                     '在 promotion_candidates 里再加别的回合、别的日子的 id，凑不够就先不提升'
                     % (len(episodes), len(dates), need_roots, need_dates))
    if item.get('visibility') == 'public' and _from_home(store, ep['persona'], item['source_ids'], episodes):
        # A public memory shows in every conversation; one built on anything said at home stays at home (ADR-050).
        raise Denied('PROMOTION_NOT_PUBLIC: 这条的来源里有家里的对话，置公开会把家里的话带到每个群和私聊里；'
                     '要提升就把 visibility 写成 private，留在家里')
    landed_note = None
    if memory_tiers.ENABLED and item.get('about'):
        landed, landed_note = memory_tiers.land(store, ep, item, episodes)
        if landed:
            store.audit(ep['_id'], 'memory.promoted', {'landed': landed, 'about': item['about'], 'why': item['why'],
                                                       'source_ids': item['source_ids']},
                        'global-safe' if item.get('visibility') == 'public' else visibility.owner_private_scope(ep['persona']))
            return {'landed': landed, 'note': landed_note}
    scope = 'global-safe' if item.get('visibility') == 'public' else visibility.owner_private_scope(ep['persona'])
    body = f"事实：{item['fact']}\n评价：{item['appraisal']}\n信号：{item['signal']}"
    doc = {'_id': 'mu-' + sha(canonical([ep['_id'], 'promote', key])), 'kind': 'memory_unit', 'scope_key': scope,
           'policy_epoch': 1, 'persona': ep['persona'], 'character_id': character_id(store.config),
           'fact': item['fact'], 'appraisal': item['appraisal'], 'signal': item['signal'], 'body_markdown': body,
           'epistemic_type': 'character_interpretation', 'source_ids': item['source_ids'],
           'source_event_ids': item['source_ids'], 'depends_on': item['source_ids'], 'episode_id': ep['_id'],
           'status': 'active', 'embedding_status': 'PENDING', 'origin': 'asuna', 'why': item['why']}
    if not store.db.memory_units.find_one({'_id': doc['_id']}):
        store.put('memory_units', doc, stream=ep['_id'])
        # ADR-017: what she brought home from other conversations, and why, in her own audited record.
        store.audit(ep['_id'], 'memory.promoted', {'memory_id': doc['_id'], 'scope_key': scope, 'why': item['why'],
                                                   'source_ids': item['source_ids']}, scope)
    return {'memory_id': doc['_id'], 'scope_key': scope, **({'note': landed_note} if landed_note else {})}
