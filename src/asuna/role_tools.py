"""Her mind's tools: what the character brain may do in one native turn (ADR-011 §3, §5.1).

The character brain thinks, remembers, feels, writes down, plans, hands work to the action brain,
and speaks or stays silent. A turn is one native DSH turn: she calls `think` first, then any of
the tools the program exposed for this turn, and her last text without a tool call is what she
says. Every call reaches the worker (native_worker.py) on the coordinator's own thread, so effects
run one at a time, inside the turn's episode, exactly where the old DECIDE fields ran.

Rules shared by every tool:
- The program decides which tools a turn has (`exposed`); an unexposed tool is refused in words.
- A refused call is a tool error she reads in the same turn (`Refused`): what was wrong and what she
  can do instead. It never fails the turn.
- The native `tool_call_id` is the effect key: a replay of the same call after a crash returns the
  recorded result; calling again in the same turn is a new action.
- Model-facing text is Chinese (the core prompts' language until ADR-010); the UI never shows it.
"""
from __future__ import annotations

import json
from pathlib import Path

from .documents import DocumentError, DocumentStore, WRITE_STAGE_OPS
from .evidence import canonical, sha
from .state import Conflict, Denied
from . import visibility
from .vision import inline_summary as picture_receipt
from .context_budget import SINGLE_BODY_CHARS

THOUGHT_CHARS = 300
# What she is told is THOUGHT_CHARS; refused only past this. Most refusals were a few characters over a count a
# model cannot keep exactly (owner 2026-10-06), and each cost her a full retry.
THOUGHT_HARD_CHARS = 360
RECALLS_PER_TURN = 3
CALLS_PER_TURN = 12
IDEAS_PER_TURN = 3
IDEA_CHARS = 500
GROUP_NOTE_OPS = ('append_section', 'replace_section', 'set_tags')
VISIT_FROM = ('presence', 'scheduled')            # turns at home that may send her out (owner-private only)
# Hand-offs in a row without anyone speaking (task result -> delegate -> result ...): a loop stops here (ADR-018 §3.3).
DELEGATION_DEPTH_MAX = 6
# The tools a turn always has; the rest follow the turn's kind, scene and grants (`exposed`).
CONSULT = 'consult'


class Refused(Exception):
    """A call she can correct herself: the message says, in words for her, what to do instead."""


def _s(description, **extra):
    return {'type': 'string', 'description': description, **extra}


AFFECT_FIELDS = {
    'kind': _s('心情的种类：how_to_record_from_program.kinds 里的一种，可省略'),
    'intensity': _s('多强：how_to_record_from_program.intensity 里的一个词'),
    'arousal': _s('多激动：how_to_record_from_program.arousal 里的一个词，可省略'),
    'direction': _s('好或坏；种类本身带好坏时不写', enum=['好', '坏']),
    'ref': _s('触动你的那件事：ref_index 里的 id'),
    'why': _s('来由'),
    'cost': _s('代价，可省略'),
    'open': {'type': 'boolean', 'description': '没解决、要挂着的事写 true'},
}

TOOLS = {
    'think': {
        'description': ('写下这回合的心里话：注意到了什么、心里什么感觉、打算怎么做。用你自己的口吻写两三句心里话，'
                        '%d 字以内，不是完整的推理过程。每回合第一步必须先调用它；心里话会存档，下一回合你能看到最近几段。'
                        % THOUGHT_CHARS),
        'parameters': {'thought': _s('心里话', required=True)},
    },
    'recall': {
        'description': ('回想：按一句话搜你的记忆，或读自己文档里某一节的原文。每回合最多 %d 次。'
                        '记不起来就直说，不要编。' % RECALLS_PER_TURN),
        'parameters': {'query': _s('想找什么，用一句话说', required=True),
                       'sections': {'type': 'array', 'description': '要读原文的文档节（至多 3 条）',
                                    'items': {'type': 'object', 'additionalProperties': False, 'properties': {
                                        'doc': _s('文档，如 persona、voice', required=True),
                                        'sid': _s('节的 sid', required=True)}}}},
    },
    'delegate': {
        'description': ('把一件要在世界里做的事交给行动脑：查资料、查完整原话、跑代码、改文件、生图、改能力。'
                        'title 是简短标题；brief 是给行动脑的完整交代：要什么、为什么、有什么限制和要注意的。'
                        '行动脑看不到你的上下文，只看到 brief 和对方的原话。交出去以后你可以照常聊天，'
                        '结果回来会再叫你；没做完的事不要说成做完了。'),
        'parameters': {'title': _s('简短标题', required=True), 'brief': _s('给行动脑的完整交代', required=True)},
    },
    'message_action': {
        'description': ('给已经交给行动脑的一件事补话：补充信息、改目标，或者让已经做完的事接着做。'
                        'task 照抄 task_state_from_program 里那件事的 _id。还在做的，行动脑下一步就看到；'
                        '已经做完的，会接着原来的过程再做一轮，结果回来会再叫你。'),
        'parameters': {'task': _s('任务 _id', required=True), 'message': _s('要对行动脑说的话', required=True)},
    },
    'stop_action': {
        'description': '叫停一件还在做或暂停着的事。只在对方明确要取消、或你确定不该再做时用；转换话题、说不急都不是取消。',
        'parameters': {'task': _s('任务 _id', required=True), 'reason': _s('为什么叫停', required=True)},
    },
    'answer_action': {
        'description': ('回答行动脑刚才问你的问题。这是给行动脑的回答，不会发给任何人。'
                        '缺什么资料、拿不准，就照实说。回答后这回合结束。'),
        'parameters': {'answer': _s('你的回答', required=True)},
    },
    'stay_silent': {
        'description': ('这回合不说话，直接结束回合：这回合一个字都不会发出去，只写在思考里的话不算说过。'
                        '只在确实不用回应时用，不代表出错。'),
        'parameters': {'reason': _s('为什么不说', required=True)},
    },
    'quote': {
        'description': ('群里这回合你说的第一句要不要引用叫你的那条。不调时程序这样定：那条之后别人又说过话才引用，'
                        '否则直接发（群里的人大多不引用）。发 bot 命令（如 #napcat）这类要裸发的就选 none。'),
        'parameters': {'how': _s('引用还是不引用', required=True, enum=['source', 'none'])},
    },
    'await_answer': {
        'description': ('等不等回话。群里你这回合的话 @ 了谁、或是在回谁，程序默认等他：发出去后大约三分钟里，'
                        '他下一句哪怕没 @ 你、没引用你，也会叫你看一眼（接话／不理），一句话只看一次。'
                        'wait=no 关掉这回合的等待（比如只是随口一句、不需要他回）；'
                        '没 @ 谁也没在回谁、却想等这里谁的回话，就 wait=yes。只管你这一句、这个群、三分钟；'
                        '想几个小时里、在哪儿都知道某个人开口，用 watch。'),
        'parameters': {'wait': _s('等还是不等', required=True, enum=['yes', 'no']),
                       'why': _s('wait=yes 时：在等什么回话，一句话')},
    },
    'credential': {
        'description': ('保险箱：有人给你密码、口令、令牌、账号这类凭据时，用 keep 收进去（name 起个短名，如 enlighten；note 写它是干什么的；'
                        'env 是环境变量名到值，如 {"ENLIGHTEN_EMAIL": "…", "ENLIGHTEN_PASSWORD": "…"}）。收进去以后值谁都看不到，'
                        '包括你自己和行动脑；要用就交代行动脑在 sandbox_run 里写 credentials 这个名字。值只在 keep 这一次出现：'
                        '交代、回话、文档、想法本里都不要写值。drop 按名字删掉。只在家里有。'),
        'parameters': {'op': _s('做什么', required=True, enum=['keep', 'drop']),
                       'name': _s('凭据的短名（小写字母、数字、连字符）', required=True),
                       'note': _s('keep 用：它是干什么的，一句话（不写值）'),
                       'env': {'type': 'object', 'additionalProperties': True,      # DSH: boolean only
                               'description': 'keep 用：环境变量名（大写）→ 值（都是字符串）'}},
    },
    'watch': {
        'description': ('盯一个人：on 把这个对话里看得到的一个人加进 watch 名单（person 写他的标签、#编号或名字），'
                        '之后他在你任何一个对话里说话，你都会在他说话的那个对话里知道（群里会叫你看一眼，接不接由你）。'
                        'mode=once（默认）他第一次说话就叫你，然后不盯了；burst 他每次沉默十分钟以上再开口都叫你，到期为止。'
                        'hours 盯多久（1–72）。最多同时盯 5 个人，到期自己停；off 停掉一个（id 照抄 watching_from_program）。'
                        '等刚说的那句的回话不用盯：@ 了或回了谁，程序本来就会等他三分钟（await_answer）。'),
        'parameters': {'op': _s('做什么', required=True, enum=['on', 'off']),
                       'person': _s('on 用：这个对话里的人（标签、#编号或名字）'),
                       'hours': {'type': 'integer', 'description': 'on 用：盯多少小时，1–72'},
                       'mode': _s('on 用：once 或 burst，默认 once', enum=['once', 'burst']),
                       'why': _s('on 可写：为什么盯他，一句话（家里写的只在家里看得到）'),
                       'id': _s('off 用：watching_from_program 里的 id')},
    },
    'attach_image': {
        'description': ('给这回合要说的话配一张图，随话一起发出去。artifact_id 只能照抄 image_artifacts_from_program '
                        '里列出的值；正文里不要写文件名、路径或「见图」。一回合最多一张，再调用就换成新的那张。'),
        'parameters': {'artifact_id': _s('图片 artifact_id', required=True), 'why': _s('为什么发这张', required=True)},
    },
    'sticker': {
        'description': ('整理你的表情包架子（stickers_from_program）。keep：收下一个表情包——ref 照抄群里表情包下面标的'
                        '「表情包 ref」（att-…），或你自己画的图的 artifact_id（blob-…）；起个名字（name），写一句什么时候用'
                        '（when）。只有表情包能收，照片不行；架子满了先 drop 一个。drop：按名字放下一个。'
                        'rename：改名字（new_name）或用法（when）。sticker_candidates_from_program 里的候选：先 read_image 看过，'
                        '再 keep 并写 candidate。remember：看过但不想收的表情包（ref 或 candidate），记个名字和一句它在说什么'
                        '（when），以后再有人发它，下面会标你认得它，不用再看；记错了再 remember 一次就改了。'
                        '收下和记住的名字、说明在群里也会被看到。发的时候不用这个工具：在要说的话里单独写一行「[表情包:名字]」。'),
        'parameters': {'op': _s('做什么', required=True, enum=['keep', 'drop', 'rename', 'remember']),
                       'name': _s('表情包的名字（keep 时是你起的新名字），12 字以内', required=True),
                       'ref': _s('keep/remember 用：表情包 ref（att-…）；keep 也可以是你自己画的图的 artifact_id（blob-…）'),
                       'candidate': _s('keep/remember 用：候选池里的 candidate（照抄 sticker_candidates_from_program，先看过）'),
                       'when': _s('keep、remember 必填，rename 可改：什么时候用它／它在说什么，40 字以内'),
                       'new_name': _s('rename 用：新名字')},
    },
    'write_document': {
        'description': ('写你自己的文档（人格、口吻、活账、工作文档；群笔记只在那个群里）。正文直接写在 body 里：'
                        'replace_section 写修订后的整节，append_section 写新的一节，correction 写更正说明（原条目不改）；'
                        'set_tags 只改 visibility/inject/tags（replace_section 同时给了这些也会照改）；adopt_seed 接收人格包里更新的种子。'
                        '没写 visibility 的新节按 owner_private 保存。visibility 也决定你哪些回合用得上这一节：public 的节群里和别人私聊里的'
                        '回合也读得到，owner_private 的只在家里的回合读得到。每回合自动带上的只有 persona 和 voice 里 inject=always 的节'
                        '（其他文档要 recall 才读得到），有上限：'
                        '不常用的节改成 on_demand 收起来（还在，recall 能读）。不写对用户的台词，不把没发生的事写成发生过。'),
        'parameters': {
            'doc': _s('文档，如 persona、voice、group_notes', required=True),
            'op': _s('操作', required=True, enum=['replace_section', 'append_section', 'correction', 'set_tags', 'adopt_seed']),
            'reason': _s('为什么改', required=True),
            'sid': _s('目标节的 sid（replace_section、correction、set_tags 用）'),
            'heading': _s('新节的标题（append_section 用）'),
            'body': _s('这一节的正文（markdown，不要标题行）'),
            'tags': {'type': 'array', 'items': {'type': 'string'}, 'description': '标签'},
            'visibility': _s('哪些回合读得到：public＝你所有的回合（包括在群里的）；owner_private＝只在家里的回合（自动带上只限 persona、voice 的 always 节）', enum=['public', 'owner_private']),
            'inject': _s('什么时候放进上下文', enum=['always', 'on_demand', 'never']),
        },
    },
    'update_self': {
        'description': ('改你的自我描述：character_core 是跨场景的长期自我，current_self 是近期的自我理解。'
                        '写完整的新正文；不必为了完成什么而改。'),
        'parameters': {'target': _s('改哪一份', required=True, enum=['character_core', 'current_self']),
                       'body': _s('完整的新正文', required=True), 'reason': _s('为什么改', required=True)},
    },
    'understand_person': {
        'description': ('更新你对当前说话人的理解：写完整的新理解正文，保留仍然成立的旧理解，分清对方说过的、你判断的和'
                        '已核实的。只在这次真有值得留下的变化时用，不为了被夸而每轮更新。'),
        'parameters': {'body': _s('完整的新理解', required=True)},
    },
    'set_policy': {
        'description': '调整你自己声明过的一个参数（persona-model 里的 policy key）。',
        'parameters': {'key': _s('参数名', required=True), 'value': {'type': 'json', 'description': '新的值', 'required': True},
                       'reason': _s('为什么改', required=True)},
    },
    'pin_memory': {
        'description': '让一条记忆一直容易被想起（或取消）。memory_id 照抄 ref_index 里的记忆 id。',
        'parameters': {'memory_id': _s('记忆 id', required=True), 'pinned': {'type': 'boolean', 'required': True}},
    },
    'feel': {
        'description': ('记一笔心情（op=record，只用 how_to_record_from_program 里的词，不写数字）；事情了结用 close，'
                        '发现前提不成立用 void（必须写 why）；情感评估路由的提案用 adopt 逐条决定（accept/decline/edit）。'
                        '没有触动就不要记。'),
        'parameters': {
            'op': _s('做什么（不写时：有 kind 就是 record）', enum=['record', 'close', 'void', 'adopt']),
            **AFFECT_FIELDS,
            'event_id': _s('close/void 的那一笔'),
            'proposal_id': _s('adopt 的那条提案'),
            'decision': _s('adopt 的决定', enum=['accept', 'decline', 'edit']),
            'edit': {'type': 'object', 'additionalProperties': False, 'description': 'decision=edit 时改成的样子',
                     'properties': AFFECT_FIELDS},
        },
    },
    'plan': {
        'description': ('把一件事留到将来再想：create 新建（intent 加一种计时），update 改期或改内容，cancel 取消。'
                        '计时只选一种：after_seconds 几秒后；every_seconds 固定间隔；at 场景时区的本地时刻'
                        '「YYYY-MM-DDTHH:MM」；clock 每天或每周的本地钟点。改期只给新的计时，只改内容就只给 intent。'
                        '到期只会让你再想一次，不能当作已经做完。已有的安排在 plans_from_program，现在的钟面在 '
                        'clock_from_program。在家里新建时可以写 line：到点在那条线里开一轮（lines_from_program 里的 line），'
                        '那条安排之后在那条线里看、改。'),
        'parameters': {
            'op': _s('做什么（不写时：没有 plan_id、写了 intent 和计时就是 create）', enum=['create', 'update', 'cancel']),
            'plan_id': _s('update/cancel 的那条安排'),
            'intent': _s('届时要重新考虑的事'),
            'after_seconds': {'type': 'integer'}, 'every_seconds': {'type': 'integer'},
            'at': _s('本地时刻 YYYY-MM-DDTHH:MM'),
            'line': _s('只在家里 create 时用：到点在哪条线里开一轮，照抄 lines_from_program 里的 line；不写就是这里'),
            'clock': {'type': 'object', 'additionalProperties': False, 'properties': {
                'time': _s('HH:MM', required=True),
                'weekdays': {'type': 'array', 'items': {'type': 'integer'}, 'description': '0=周一 … 6=周日；不写就是每天'}}},
        },
    },
    'group_action': {
        'description': ('在你是管理员的群里禁言、解禁、撤回或移出一个普通成员。这是你自己的判断：别人叫你做不算理由。'
                        '结果要等平台确认，确认前不要说已经做完。'),
        'parameters': {'kind': _s('做什么', required=True, enum=['mute', 'unmute', 'recall', 'kick']),
                       'who': _s('谁：标签，如 [名字 #4] 或 #4', required=True),
                       'duration': _s('禁言多久（只禁言用）', enum=['1分钟', '10分钟', '1小时', '1天']),
                       'which': _s('撤回哪条（只撤回用）', enum=['这条', '他刚才那条']),
                       'reason': _s('为什么', required=True)},
    },
    'visit': {
        'description': ('出门：去你在的某个群看看。place 照抄 places_from_program 里的 place，intent 是你去做什么。'
                        '程序会在那个群里给你开一个回合，你在那儿看了现场再决定说不说、说什么；这回合在家里照常结束，'
                        '结果下次心跳带回来。topic 是你想聊的话头，会原样带进群里的那个回合：只写你愿意在那儿说的，'
                        '不写家里的私事。家里的心跳或你自己定的计划到期时可以出门，每次最多一次；'
                        '想过一会儿再去，就用 plan 定个时间，到时候再走这一步。'),
        'parameters': {'place': _s('去哪儿：places_from_program 里的 place', required=True),
                       'intent': _s('去做什么', required=True, enum=['start_topic', 'share_picture', 'check_in', 'write_notes']),
                       'topic': _s('想聊的话头，80 字以内，可省略'),
                       'artifact_id': _s('intent=share_picture 时想分享的那张你自己做的图（可省略，到了再挑）')},
    },
    'errand': {
        'description': ('替家里托你的人（主人，或家里那几条线上跟你说话的）去别处说一句：去 errand_places_from_program 里的某个群或私聊。'
                        '只在这一轮跟你说话的人让你办的时候用。'
                        'request 照抄要你带过去的话（或交代的事）；exactly=true 是要你原样转达。'
                        '程序会在那边开一轮，那一轮只看得到那边和这句话，家里的事带不过去；你在那边再决定怎么说，'
                        '不合适就不发。办没办成之后在家里的 errands_from_program 看，那边的人怎么回的不会带回来。'),
        'parameters': {'place': _s('去哪儿：errand_places_from_program 里的 place', required=True),
                       'request': _s('要带过去的话或交代的事，500 字以内', required=True),
                       'exactly': {'type': 'boolean', 'description': '要原样转达时为 true'},
                       'artifact_id': _s('要一起带过去的一张你自己做的图（image_artifacts_from_program 或 your_pictures_from_program 里的；可省略）')},
    },
    'pass_note': {
        'description': ('给别的对话里的你写一张便条（你在家里，写的便条算你自己的决定）：家里的另一条线，或你在的某个群、'
                        '某个人的私聊。to 照抄 note_places_from_program 里的 place。那边的回合会读到它，知道是你在家里写的，'
                        '不会当成那边有人说的话；那边的人看不到便条，但那一轮的你可能照着说出来，所以只写你愿意在那边说的。'
                        'mode=wake 马上叫醒那边（排在那边手上的事后面，不插队）；next_time 等那边下次有回合时看到。'
                        '不写 mode 按那个地方的默认。叫醒一个群算一次出门。300 字以内，一回合最多两张。'),
        'parameters': {'to': _s('送到哪儿：note_places_from_program 里的 place', required=True),
                       'text': _s('便条：你自己的话，300 字以内', required=True),
                       'mode': _s('wake 或 next_time，可省略', enum=['wake', 'next_time'])},
    },
    'leave_note': {
        'description': ('给别的对话里的你留一张便条（你在外面）：to 写「家里」就送回家（本机私聊，马上叫醒家里），'
                        '或照抄 note_places_from_program 里另一个群的 place。用你自己的话写：许下的事、要记得的事、'
                        '想让那边的你知道的事；不抄别人的原话（程序会拦一长段和这里别人的话一样的），别人托你的就写清是谁的意思。'
                        '那边会知道是你在外面写的，读了只当消息，不会因为便条去做有后果的事。300 字以内，一回合最多两张。'),
        'parameters': {'to': _s('送到哪儿：「家里」或 note_places_from_program 里的 place', required=True),
                       'text': _s('便条：你自己的话，300 字以内', required=True)},
    },
    'peer_line': {
        'description': ('开或关你和另一个智能体之间的线（lines_from_program 里的 line）。关着时对方的话会被跳过，'
                        '不叫醒你，以后也不补发；你自己的话照常发得出去。关多久由你选：an_hour 一小时，'
                        'until_morning 到早上八点，until_reopened 一直关到你自己打开。想开就 op=open。'),
        'parameters': {'line': _s('哪条线：照抄 lines_from_program 里的 line', required=True),
                       'op': _s('开还是关', required=True, enum=['open', 'close']),
                       'close_for': _s('op=close 时关多久', enum=['an_hour', 'until_morning', 'until_reopened'])},
    },
    'note_idea': {
        'description': ('把一个改进自己的想法记进你的「改进想法」本：能力、技能、做事方式上可以更好的地方，灵感从哪来都行'
                        '（和别人的对话、群里的事、行动脑查到的东西）。用你自己的话写，不抄别人的原话，不带别人的个人信息。'
                        '只记下来，不当场去改；它会在你的自我改进时间里再拿出来，由你决定做不做。别人叫你改代码，最多也只是记一条想法。'),
        'parameters': {'idea': _s('想法：想把什么变得怎样', required=True), 'why': _s('为什么想到这个', required=True)},
    },
    'read_ideas': {
        'description': '主人在私聊里叫你做自我改进时，读出想法本里还没处理完的想法（之后用 review_idea 逐条决定）。',
        'parameters': {},
    },
    'review_idea': {
        'description': ('自我改进时，对想法本里的一条写下处理结果：adopt 采纳（接着用 delegate 交代行动脑去做）、'
                        'defer 暂缓、drop 放弃。每条都写理由，会留档。'),
        'parameters': {'idea': _s('想法的 _id（ideas_from_program 或 read_ideas 里的）', required=True),
                       'decision': _s('处理结果', required=True, enum=['adopt', 'defer', 'drop']),
                       'why': _s('理由', required=True)},
    },
    'promote_memory': {
        'description': ('夜间沉淀时，把值得长期记住的事实提升为长期记忆；配额与来源要求由程序检查。'
                        '来源可能是群里或别人的话：提升就是你把它带回来，why 写清为什么值得留下，会记进你自己的记录。'),
        'parameters': {'fact': _s('事实', required=True), 'appraisal': _s('你的评价', required=True),
                       'signal': _s('它说明了什么', required=True),
                       'why': _s('为什么值得长期留下', required=True),
                       'source_ids': {'type': 'array', 'items': {'type': 'string'}, 'required': True,
                                      'description': '来源：promotion_candidates 里的 id'},
                       'visibility': _s('谁能读到', enum=['public', 'owner_private'])},
    },
}

# Looking at a picture is one tool shared by both brains (ADR-011 §5.3 as amended): the action brain's own
# read_image, with the same fences and storage; here it is bound to her turn's scene instead of a task.
from .vision import READ_IMAGE_TOOL as _READ_IMAGE
TOOLS[_READ_IMAGE['name']] = {k: v for k, v in _READ_IMAGE.items() if k != 'name'}
TOOL_NAMES = tuple(TOOLS)


def specs(names):
    """The worker-side tool specs the plugin registers (name, description, parameters)."""
    return [{'name': name, **TOOLS[name]} for name in names]


def all_specs():
    return specs(TOOL_NAMES)


def turn_kind(ep):
    return ep.get('turn_kind') or ep.get('episode_kind') or 'external'


def exposed(store, ep):
    """The tools this turn has, decided by the program from the turn's kind, scene and grants (§2.6)."""
    context = ep.get('context') or {}
    kind = turn_kind(ep)
    cls = (ep.get('manifest') or {}).get('session_class', visibility.PUBLIC)
    names = ['think', 'recall']
    if kind == CONSULT:
        return names + ['answer_action']
    if her_pictures(store, ep):
        names.append('read_image')
    names += ['stay_silent', 'note_idea']
    note_tool = ['pass_note' if cls == visibility.OWNER_PRIVATE else 'leave_note'] \
        if context.get('note_places_from_program') else []
    if kind == 'note':
        from . import notes
        first = notes.opening(store, ep) if ep.get('_id') else None
        if (first or {}).get('trust') != notes.TRUSTED:
            # ADR-018 §5.4: a note from outside is a message. Its turn reads, answers, notes down and replies back;
            # nothing with consequences (a wish to act goes into the notebook for her self-improvement review).
            names += note_tool
            if context.get('affect_from_program'):
                names.append('feel')
            return names + ['watch']
    # Her notebook is read and decided in her self-improvement turns, and when the owner asks in private.
    if kind == 'self_development' and (context.get('ideas_from_program') or {}).get('items'):
        names.append('review_idea')
    elif cls == visibility.OWNER_PRIVATE and kind not in ('presence', 'settlement', 'scheduled', 'note'):
        names += ['read_ideas', 'review_idea']
    capabilities = context.get('action_capabilities_from_program') or {}
    tasks = context.get('task_state_from_program') or []
    if capabilities.get('available'):
        names.append('delegate')
        if tasks:
            names.append('message_action')
    # A paused task is open work in her context, so she can close it as well (ADR-011 §7.1).
    if any(task.get('state') in ('READY', 'RUNNING', 'PAUSED') for task in tasks):
        names.append('stop_action')
    if context.get('image_artifacts_from_program'):
        names.append('attach_image')
    if context.get('stickers_from_program') or context.get('stickers_review_from_program')             or context.get('sticker_candidates_from_program'):
        names.append('sticker')
    scene_kind = (store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1}) or {}).get('kind')
    if cls == visibility.OWNER_PRIVATE or scene_kind == 'group':
        names.append('write_document')
    if cls == visibility.OWNER_PRIVATE and kind in ('external', 'task_feedback'):
        names.append('credential')            # her credential vault: filed at home only (credentials.py)
    if scene_kind in ('group', 'dm') or context.get('watching_from_program'):
        names.append('watch')
    if scene_kind == 'group':
        names.append('await_answer')
        if kind not in ('visit', 'scheduled', 'presence', 'settlement'):
            names.append('quote')                 # her first line quotes the line that called her, or not          # her line asks someone: their next unaddressed line gets her a look
    if cls == visibility.OWNER_PRIVATE:
        names += ['update_self', 'set_policy', 'pin_memory']
    if kind not in ('presence', 'settlement', 'self_development', 'visit', 'note') and (
            context.get('understanding_update_from_program') or {}).get('available'):
        names.append('understand_person')
    if context.get('affect_from_program'):
        names.append('feel')
    names.append('plan')
    if ((context.get('your_place_from_program') or {}).get('admin')):
        names.append('group_action')
    if kind == 'settlement':
        names.append('promote_memory')
    if (context.get('lines_from_program') or {}).get('items'):
        names.append('peer_line')
    # ADR-017: in a home conversation, whoever is talking to her may send her on an errand to another chat.
    if cls == visibility.OWNER_PRIVATE and kind == 'external' and context.get('errand_places_from_program'):
        names.append('errand')
    # ADR-012 §4.2: from a heartbeat at home, or a plan of hers due there, she may go and see one of her groups.
    if kind in VISIT_FROM and cls == visibility.OWNER_PRIVATE and (context.get('places_from_program') or {}).get('items'):
        names.append('visit')
    # ADR-018: a note to another of her conversations, wherever there is somewhere it may go from this turn.
    return names + note_tool


STICKER_LOOKED_NOTE = ('这是个表情包。想以后再见到它不用再看：用 sticker 的 remember 记个名字和一句它在说什么'
                       '（ref 照抄）；想收着自己发就 keep。都不想就不用管。')


def offered_pictures(ep):
    """The artifact ids her turn may send (image_artifacts_from_program): she may also look at them."""
    from .stickers import candidate_ids
    items = ((ep.get('context') or {}).get('image_artifacts_from_program') or {}).get('items') or ()
    return tuple(item['artifact_id'] for item in items if isinstance(item, dict) and item.get('artifact_id'))         + candidate_ids(ep.get('context'))                 # sticker candidates: she looks before she keeps


def her_pictures(store, ep):
    """Whether she can look at a picture this turn: her own route takes images and the conversation's recent
    pictures (the same window read_image reads) include one that can be pulled."""
    from .vision import scene_attachments, vision_capability
    if not vision_capability(store.config, 'character')['supported']:
        return False
    if offered_pictures(ep) or ((ep.get('context') or {}).get('your_pictures_from_program') or {}).get('items'):
        return True                       # she can look before she sends, and at her own pictures at home
    try:
        listing = scene_attachments(store, ep, store.config)
    except Denied:
        return False
    return any(item.get('pullable') for item in listing['attachments'])


# Words for the refusals she is most likely to meet; any other code is passed on as it is.
WORDS = {
    'DOC_WRITE_REQUIRES_OWNER_PRIVATE': '这份文档只能在家里（本机、主人私聊这类可信的对话）改。',
    'GROUP_NOTES_ONLY_IN_ITS_GROUP': '群笔记在那个群里用 doc=group_notes 写，夜间整理时用列出的 doc 写；只能 append_section、replace_section 或 set_tags。',
    'NOTE_OVER_LIMIT': '这份笔记已经超出每回合上限很多了，先整理（改短、合并，或用 set_tags 把不常用的节收起来）再加新的。',
    'DOC_SECTION_NOT_FOUND': '没有这一节；先用 recall 看清 sid。',
    'DOC_BODY_REQUIRED': '这个操作要在 body 里写正文。',
    'DOC_HEADING_REQUIRED': '新的一节要有 heading。',
    'DOC_REASON_REQUIRED': '要写 reason：为什么改。',
    'DOC_OP_NOT_ALLOWED': '这份文档不能这样改。',
    'DOC_NOT_FOUND': '没有这份文档；新文档只能用 append_section 开始。',
    'DOC_SEED_NOT_FOUND': '人格包里没有这份种子。',
    'BASE_REVISION_STALE': '这份文档在这回合里被改过了；先 recall 读最新的那一节再改。',
    'PERSONA_RENDER_OVER_BUDGET': '人格渲染会超出预算；先精简别的节。',
    'PIN_REQUIRES_OWNER_PRIVATE': '置顶记忆只能在家里（本机、主人私聊这类可信的对话）做。',
    'PIN_MEMORY_NOT_READABLE': '这条记忆读不到或已经不在了。',
    'PIN_MEMORY_NOT_IN_CONTEXT': '只能置顶这回合上下文 ref_index 里的记忆。',
    'POLICY_SET_REQUIRES_OWNER_PRIVATE': '参数只能在家里（本机、主人私聊这类可信的对话）改。',
    'PROMOTE_ONLY_IN_SETTLEMENT': '提升长期记忆只在夜间沉淀时做。',
    'PROMOTION_QUOTA': '今天提升长期记忆的配额用完了。',
    'PROMOTION_SOURCES_INSUFFICIENT': '来源不够：要来自足够多的不同回合和日期。',
    'ATTACH_TARGET_NOT_ALLOWED': '这里不能带图：私聊和你在的群能带（群和别人的私聊只发你自己做的图）。',
    'ATTACH_ARTIFACT_NOT_IN_CONTEXT': '只能用 image_artifacts_from_program 里列出的 artifact_id。',
    'ATTACHMENT_NOT_HER_OWN': '群里和别人的私聊里只能发你自己做的图。',
    'GROUP_ACTION_NOT_A_GROUP': '这里不是群。',
    'GROUP_ACTION_DISABLED': '这个群关掉了管理动作。',
    'GROUP_ACTION_NOT_AN_ADMIN': '你在这个群不是管理员。',
    'VISIT_PLACE_UNKNOWN': '没有这个地方；照抄 places_from_program 里的 place。',
    'VISIT_NOT_NOW': '现在去不了那里。',
    'VISIT_OFF': '出门现在没开。',
    'VISIT_PICTURE_NOT_HERS': '只能带你自己做的图；到了群里那个回合再挑也行。',
    'STICKER_SHELF_FULL': '表情包架子满了：先用 drop 放下一个不想要的，再收。',
    'STICKER_NAME_TAKEN': '架子上已经有这个名字了：换一个名字。',
    'STICKER_NAME_INVALID': '名字不合适。',
    'STICKER_WHEN_INVALID': '要写一句什么时候用它。',
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
    'CREDENTIALS_UNAVAILABLE': '这会儿保险箱连不上（宿主没提供凭据存储）。',
    'WATCH_HOURS_INVALID': 'hours 是 1 到 72 之间的整数。',
    'WATCH_MODE_INVALID': 'mode 是 once 或 burst。',
    'WATCH_PERSON_NOT_HERE': '这个对话里找不到这个人：照抄他的标签或 #编号。',
    'WATCH_PERSON_UNCLEAR': '这个名字对得上不止一个人：用标签里的 #编号。',
    'WATCH_LIST_FULL': 'watch 名单满了（最多 5 个）：先 off 一个。',
    'WATCH_NOT_FOUND': '名单上没有这个 id：照抄 watching_from_program 里的 id。',
    'STICKER_NO_FINGERPRINT': '这个表情包平台没给能认出它的标记，记不住；想留着就 keep。',
    'STICKER_CANDIDATE_GONE': '这个候选已经不在池子里了（挤掉了或收过了）。',
    'STICKER_NOT_ON_SHELF': '架子上没有这个名字：照抄 stickers_from_program 里的名字。',
    'STICKER_NOTHING_TO_CHANGE': 'rename 要写 new_name 或 when。',
    'ERRAND_PLACE_UNKNOWN': '没有这个地方；照抄 errand_places_from_program 里的 place。',
    'ERRAND_LIMIT': '今天替人跑腿的次数用完了，明天再办。',
    'ERRAND_ONLY_AT_HOME': '只有在家里（本机、主人私聊这类可信的对话）才能接差事。',
    'ERRAND_PICTURE_NOT_HERS': '差事只能带你自己做的图。',
    'ERRAND_ONLY_WHEN_ASKED': '差事只在家里有人跟你说话、让你去办的那一轮接；自己想去，用 visit。',
    'IMAGE_ATTACHMENT_NOT_IN_SCENE': '这个对话最近的图里没有这个 ref：照抄图旁标的 ref；太早的图看不到了。',
    'IMAGE_NOT_PULLABLE': '这张图拉不到。',
    'IMAGE_SOURCE_UNAVAILABLE': '这张图的来源已经没有了。',
    'IMAGE_FETCH_FAILED': '这张图没拉下来（链接可能过期了）。',
    'IMAGE_TOO_LARGE': '这张图太大，看不了。',
    'IMAGE_TYPE_UNSUPPORTED': '这不是能看的图片格式。',
    'VISION_ROUTE_UNSUPPORTED': '你现在的模型看不了图；要看就交给行动脑，把 ref 一起交代。',
}


def words(exc):
    code = getattr(exc, 'code', None) or str(exc).split(':', 1)[0].strip() or type(exc).__name__
    detail = getattr(exc, 'detail', '') or (str(exc).split(':', 1)[1].strip() if ':' in str(exc) else '')
    said = WORDS.get(code)
    return (said + (' （' + code + (': ' + detail if detail else '') + '）') if said
            else code + (': ' + detail if detail else ''))


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
        done = (ep.get('tool_calls') or {}).get(call_id)
        if done:
            if done['tool'] != name or done['args_sha256'] != sha(canonical(args)):
                raise Refused('CALL_ID_REUSED')
            if done.get('refused'):
                raise Refused(done['refused'])
            return done['result'], bool(done.get('conclude'))
        try:
            if name not in TOOLS or name not in (ep.get('turn_tools') or ()):
                raise Refused('这回合没有 %s 这个工具。能用的是：%s。' % (name, '、'.join(ep.get('turn_tools') or ())))
            if not isinstance(args, dict):
                raise Refused('参数要是一个对象。')
            if name != 'think' and not ep.get('turn_thought'):
                raise Refused('先用 think 写下这回合的心里话，再做别的。')
            if len(ep.get('tool_calls') or {}) >= CALLS_PER_TURN:
                raise Refused('这回合的工具调用已经到上限（%d 次）：这回合先到这里，写下要说的话或用 stay_silent 结束。'
                              % CALLS_PER_TURN)
            result, conclude = getattr(self, 'tool_' + name)(ep, call_id, args)
        except Refused as exc:
            self._record(ep_id, call_id, name, args, refused=str(exc))
            raise
        except (Denied, Conflict, DocumentError, ValueError) as exc:
            message = words(exc)
            self._record(ep_id, call_id, name, args, refused=message)
            raise Refused(message) from None
        # A picture's bytes go back to the turn only: the record keeps the receipt (the bytes are in the blob store).
        self._record(ep_id, call_id, name, args, conclude=conclude,
                     result=picture_receipt(result) if name == _READ_IMAGE['name'] else result)
        return result, conclude

    def _record(self, ep_id, call_id, name, args, *, result=None, refused=None, conclude=False):
        c = self.coordinator
        ep = self.store.db.episodes.find_one({'_id': ep_id})
        calls = dict(ep.get('tool_calls') or {})
        calls[call_id] = {'tool': name, 'args_sha256': sha(canonical(args)), 'seq': len(calls),
                          **({'refused': refused} if refused else {'result': result}),
                          **({'conclude': True} if conclude else {})}
        c._update(ep, tool_calls=calls)
        self.store.audit(ep_id, 'role_tool', {'call_id': call_id, 'tool': name, 'args': args,
                                              **({'refused': refused} if refused else {'result': result})},
                         ep['scope_key'])

    def _fresh(self, ep):
        return self.store.db.episodes.find_one({'_id': ep['_id']})

    def _cls(self, ep):
        return (ep.get('manifest') or {}).get('session_class', visibility.PUBLIC)

    def _text(self, args, field, limit, *, required=True):
        value = args.get(field)
        if value is None and not required:
            return None
        if not isinstance(value, str) or not value.strip():
            raise Refused('%s 要写内容。' % field)
        if len(value) > limit:
            raise Refused('%s 太长了（%d 字），%d 字以内。' % (field, len(value), limit))
        return value.strip()

    # ── mind ────────────────────────────────────────────────────────
    def tool_think(self, ep, call_id, args):
        thought = self._text(args, 'thought', 100000)
        if len(thought) > THOUGHT_HARD_CHARS:
            raise Refused('心里话 %d 字，超过 %d 字：精简到 %d 字以内，只留要点；详细的推演留在思考里。'
                          % (len(thought), THOUGHT_CHARS, THOUGHT_CHARS))
        from .config import character_id
        memory_id = 'mono-' + ep['_id'] + ':' + call_id
        if not self.store.db.memory_units.find_one({'_id': memory_id}):
            self.store.put('memory_units', {'_id': memory_id, 'character_id': character_id(self.store.config),
                'kind': 'monologue', 'scope_key': ep['scope_key'], 'policy_epoch': ep['policy_epoch'],
                'body_markdown': thought, 'epistemic_type': 'character_interpretation',
                'source_event_ids': [ep['source_event_id']], 'depends_on': [ep['source_event_id']],
                'episode_id': ep['_id'], 'status': 'active', 'embedding_status': 'PENDING'}, stream=ep['_id'])
        ep = self._fresh(ep)
        self.coordinator._update(ep, turn_thought=True,
                                 monologue_refs=[*dict.fromkeys([*(ep.get('monologue_refs') or []), memory_id])])
        return {'saved': True, 'note': '已存档。'}, False

    def tool_recall(self, ep, call_id, args):
        query = self._text(args, 'query', 500)
        count = int(ep.get('recall_count') or 0)
        if count >= RECALLS_PER_TURN:
            raise Refused('这回合已经回想了 %d 次：用已经想起来的回答，记不清就直说。' % RECALLS_PER_TURN)
        sections = args.get('sections') or []
        if not isinstance(sections, list) or len(sections) > 3 or any(
                not isinstance(item, dict) or not isinstance(item.get('doc'), str) or not isinstance(item.get('sid'), str)
                for item in sections):
            raise Refused('sections 是至多 3 条 {doc, sid}。')
        c = self.coordinator
        event = {'event_id': ep['source_event_id'], 'scene_id': ep['scene_id'], 'person_id': ep['person_id'], 'text': query}
        _, recalled, manifest = c.context.prepare(event, ep['persona'], recall=True)
        documents, missing = read_sections(self.store, ep, sections, self._cls(ep))
        ep = self._fresh(ep)
        c._update(ep, recall_count=count + 1,
                  recalled=[*(ep.get('recalled') or []), *[m.get('_id') for m in recalled.get('memories') or []]])
        result = {'query': query, 'memories': recalled.get('memories') or []}
        if recalled.get('coverage_from_program'):
            result['coverage'] = recalled['coverage_from_program']
        if documents:
            result['documents'] = documents
        if missing:
            result['not_read'] = missing
        return result, False

    def tool_stay_silent(self, ep, call_id, args):
        reason = self._text(args, 'reason', 1000)
        self.coordinator._update(self._fresh(ep), silent={'reason': reason})
        return {'silent': True, 'note': '这回合什么都没发出去。'}, True

    def tool_quote(self, ep, call_id, args):
        how = args.get('how')
        if how not in ('source', 'none'):
            raise Refused('how 是 source（引用叫你的那条）或 none（不引用）。')
        self.coordinator._update(self._fresh(ep), quote=how)
        return {'note': '这回合第一句会引用叫你的那条。' if how == 'source' else '这回合说的话都不带引用。'}, False

    def tool_credential(self, ep, call_id, args):
        from . import credentials
        if args.get('op') == 'keep':
            return credentials.keep(args.get('name'), args.get('note'), args.get('env')), False
        if args.get('op') == 'drop':
            return credentials.drop(args.get('name')), False
        raise Refused('op 是 keep 或 drop。')

    def tool_watch(self, ep, call_id, args):
        from . import watches
        op = args.get('op')
        if op == 'on':
            if (self.store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1}) or {}).get('kind') not in ('group', 'dm'):
                raise Refused('只能在看得到这个人的对话里盯他（群或私聊）。')
            return watches.add(self.store, ep, ep['persona'], self._cls(ep), args), False
        if op == 'off':
            return watches.stop(self.store, ep['persona'], args.get('id')), False
        raise Refused('op 是 on 或 off。')

    def tool_await_answer(self, ep, call_id, args):
        wait = args.get('wait', 'yes')
        if wait not in ('yes', 'no'):
            raise Refused('wait 是 yes 或 no。')
        if wait == 'no':
            self.coordinator._update(self._fresh(ep), await_answer={'off': True})
            return {'note': '这回合不等回话。'}, False
        why = self._text(args, 'why', 200)
        self.coordinator._update(self._fresh(ep), await_answer={'why': why})
        return {'note': '这句发出去后约三分钟里，你 @ 的人、你回的人（都没有时这里任何人）下一句没 @ 你也会叫你看一眼。'}, False

    def tool_answer_action(self, ep, call_id, args):
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
        task = self.coordinator.delegate(ep, call_id, title, brief)
        return {'task': task['_id'], 'state': '已交给行动脑，正在排队',
                'note': '结果回来会再叫你；在那之前不要说已经做完。'}, False

    def _own_task(self, ep, task_id):
        if not isinstance(task_id, str) or not task_id:
            raise Refused('task 要照抄 task_state_from_program 里的 _id。')
        task = self.store.db.tasks.find_one({'_id': task_id, 'scene_id': ep['scene_id'],
                                             'requester_id': ep['person_id'], 'policy_epoch': ep['policy_epoch']})
        if not task:
            close = [row['_id'] for row in self.store.db.tasks.find(
                {'scene_id': ep['scene_id'], 'requester_id': ep['person_id'], 'policy_epoch': ep['policy_epoch'],
                 '_id': {'$regex': '^' + __import__('re').escape(task_id[:12])}}, {'_id': 1}).limit(3)]
            raise Refused('「%s」不是这个对话里的任务%s。照 task_state_from_program 原样抄 _id。'
                          % (task_id, '；可能是：' + '、'.join(close) if close else ''))
        return task

    def tool_message_action(self, ep, call_id, args):
        self._depth(ep)
        task = self._own_task(ep, args.get('task'))
        from . import credentials
        message = credentials.scrub(self._text(args, 'message', 20000))
        outcome = self.coordinator.message_action(ep, call_id, task, message)
        return outcome, False

    def tool_stop_action(self, ep, call_id, args):
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
                                     route='character', offered=offered_pictures(ep))
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
        cls = self._cls(ep)
        scene = self.store.db.scenes.find_one({'_id': ep['scene_id']},
                                              {'_id': 1, 'channel_id': 1, 'kind': 1, 'scope_key': 1, 'members': 1})
        allowed, reason = outbound_media.target_allowed(self.store.config, scene, cls)
        if not allowed:
            raise Denied('ATTACH_TARGET_NOT_ALLOWED: ' + reason)
        offered = (ep.get('context') or {}).get('image_artifacts_from_program') or {}
        if artifact not in {row.get('artifact_id') for row in offered.get('items') or [] if isinstance(row, dict)}:
            raise Denied('ATTACH_ARTIFACT_NOT_IN_CONTEXT: ' + artifact)
        mine_only = outbound_media.own_only(self.store.config, scene, cls)
        meta = outbound_media.accept_artifact(self.store, BlobStore(self.store), artifact,
            [] if mine_only else outbound_media.image_scopes(self.store, self.store.config, scene, cls, ep.get('person_id')),
            produced_only=mine_only)
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
        raise Refused('op 是 keep、drop、rename 或 remember。')

    # ── her own records ─────────────────────────────────────────────
    def tool_write_document(self, ep, call_id, args):
        from .render import budget_gate
        item = {k: v for k, v in args.items() if k != 'body' and v is not None}
        if not isinstance(item.get('doc'), str) or not item['doc']:
            raise Refused('doc 要写文档名。')
        cls = self._cls(ep)
        if item['doc'] == 'group_notes':
            from .group_admin import notes_slug
            scene = self.store.db.scenes.find_one({'_id': ep['scene_id']}, {'kind': 1})
            if (scene or {}).get('kind') != 'group' or item.get('op') not in GROUP_NOTE_OPS:
                raise Denied('GROUP_NOTES_ONLY_IN_ITS_GROUP')
            item = {**item, 'doc': notes_slug(ep['scene_id'])}
        elif cls != visibility.OWNER_PRIVATE:
            raise Denied('DOC_WRITE_REQUIRES_OWNER_PRIVATE')
        if item['doc'].startswith('group:'):
            # A group's notes are read in that group: always public. She may tuck a section away (on_demand), and
            # tidy them by name from her nightly settlement (context_budget.review_block).
            if item.get('op') not in GROUP_NOTE_OPS:
                raise Denied('GROUP_NOTES_ONLY_IN_ITS_GROUP')
            item = {**item, 'visibility': 'public'}
            if item['op'] == 'append_section' or 'inject' in item:
                item['inject'] = item['inject'] if item.get('inject') in ('always', 'on_demand') else 'always'
        docs = DocumentStore(self.store, ep['persona'])
        slug = item['doc']
        base = docs.read(slug)[0]
        mutation_id = f"{ep['_id']}:write:{call_id}"
        if item.get('op') == 'adopt_seed':
            kind, text = _seed_text(self.store, slug)
            if text is None:
                raise DocumentError('DOC_SEED_NOT_FOUND', slug)
            outcome = docs.adopt_seed(slug, kind, text, base_revision_id=base, author='character',
                                      mutation_id=mutation_id, reason=item.get('reason') or 'adopt package seed')
            return {'doc': slug, 'op': 'adopt_seed', **{k: v for k, v in outcome.items() if k != 'revision'}}, False
        body = args.get('body') if item.get('op') in WRITE_STAGE_OPS else None
        revision = docs.apply(slug, item, body, base_revision_id=base, author='character', mutation_id=mutation_id,
                              budget=budget_gate(self.store, ep['persona']))
        result = {'doc': slug, 'op': item['op'], 'revision_id': revision['_id'], 'sid': item.get('sid'),
                  'heading': item.get('heading'), 'note': '已写下。'}
        sections = (docs.read(slug)[1] or {}).get('sections', [])
        if item['op'] in ('append_section', 'correction') and sections:
            result['sid'] = sections[-1]['sid']          # the new section's sid, for a later replace or set_tags
        written = next((s for s in sections if s['sid'] == result['sid']), None) if result['sid'] else None
        if written:
            result['now'] = {'visibility': written['visibility'], 'inject': written['inject']}   # what the section is now
        return result, False

    def tool_update_self(self, ep, call_id, args):
        from .self_state import SelfState
        target = args.get('target')
        body = self._text(args, 'body', SINGLE_BODY_CHARS)
        self._text(args, 'reason', 2000)
        committed = SelfState(self.store).commit(self._fresh(ep), target, body, mutation=f"self-state:{ep['_id']}:{call_id}")
        return {**committed, 'note': '已保存，之后的回合都能读到。'}, False

    def tool_understand_person(self, ep, call_id, args):
        from .memory import MemoryService
        from .queue import database_effects_lock
        from .tasks import require_current_feedback
        body = self._text(args, 'body', SINGLE_BODY_CHARS)
        if not ((ep.get('context') or {}).get('understanding_update_from_program') or {}).get('available'):
            raise Denied('UNDERSTANDING_UPDATE_NOT_AVAILABLE')
        if (ep.get('understanding_update') or {}).get('state') == 'COMMITTED':
            raise Refused('这回合已经更新过一次对这个人的理解了。')
        saved = self.store.db.state_revisions.find_one({'mutation_id': ep['_id'] + ':understanding'}, {'_id': 1})
        if saved:
            # Saved before this turn was interrupted: once per episode, never a second revision.
            update = {'state': 'COMMITTED', 'accepted_revision': saved['_id']}
            self.coordinator._update(self._fresh(ep), understanding_update=update)
            return {'state': 'COMMITTED', 'note': '这回合中断前已经保存过这次理解。'}, False
        with database_effects_lock(self.store.name):
            require_current_feedback(self.store, ep)
            update = MemoryService(self.store).commit_understanding(self._fresh(ep), body)
        self.coordinator._update(self._fresh(ep), understanding_update=update)
        return {k: update.get(k) for k in ('state', 'reason') if update.get(k)}, False

    def tool_set_policy(self, ep, call_id, args):
        from .policy import PolicyStore
        from .render import model_and_policy
        if self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Denied('POLICY_SET_REQUIRES_OWNER_PRIVATE')
        key = self._text(args, 'key', 200)
        reason = self._text(args, 'reason', 2000)
        if 'value' not in args:
            raise Refused('要写 value。')
        model, _ = model_and_policy(self.store, ep['persona'])
        policy = PolicyStore(self.store, ep['persona'], model)
        spec_what = policy.validate([{'key': key, 'value': args['value'], 'what': reason[:300]}])
        what = ((model.get('policy_keys') or {}).get(key) or {}).get('what') or spec_what[key]['what']
        revision = policy.set([{'key': key, 'value': args['value'], 'what': what}], base_revision_id=policy.read()[0],
                              reason=reason, author='character', mutation_id=f"{ep['_id']}:policy_set:{call_id}",
                              sources=[ep['source_event_id']])
        scheduler = self.coordinator.scheduler
        result = {'key': key, 'value': args['value'], 'revision_id': revision['_id']}
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

    def tool_pin_memory(self, ep, call_id, args):
        if self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Denied('PIN_REQUIRES_OWNER_PRIVATE')
        memory_id = self._text(args, 'memory_id', 300)
        pinned = args.get('pinned')
        if not isinstance(pinned, bool):
            raise Refused('pinned 是 true 或 false。')
        memory = self.store.db.memory_units.find_one({'_id': memory_id})
        readable = {ep['scope_key'], 'global-safe', visibility.owner_private_scope(ep['persona'])}
        if not memory or memory.get('status') != 'active' or memory.get('scope_key') not in readable:
            raise Denied('PIN_MEMORY_NOT_READABLE: ' + memory_id)
        if memory_id not in {*((ep.get('context') or {}).get('ref_index') or []), *(ep.get('recalled') or [])}:
            raise Denied('PIN_MEMORY_NOT_IN_CONTEXT: ' + memory_id)
        self.store.put('memory_units', {**memory, 'pinned': pinned}, expected=memory['revision'], stream=ep['_id'])
        return {'memory_id': memory_id, 'pinned': pinned}, False

    def tool_feel(self, ep, call_id, args):
        from .affect import AffectLedger, kind_label
        from .render import model_and_policy
        ledger = AffectLedger(self.store, ep['persona'], *model_and_policy(self.store, ep['persona']))
        if not ledger.enabled:
            raise Refused('你没有情感账。')
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
                raise Refused('decision 是 accept、decline 或 edit。')
            if item['decision'] == 'edit':
                if not isinstance(args.get('edit'), dict):
                    raise Refused('decision=edit 时要写 edit。')
                item['edit'] = args['edit']
            row = ledger.adopt(ep, 0, item, cls, key=key)
            return {'proposal_id': item['proposal_id'], 'decision': item['decision'],
                    'event_id': row['_id'] if row else None}, False
        raise Refused('op 是 record、close、void 或 adopt。')

    def tool_plan(self, ep, call_id, args):
        from . import schedule_rules
        from .queue import database_effects_lock
        from .tasks import require_current_feedback
        c = self.coordinator
        if not c.scheduler:
            raise Refused('现在没有定时服务，安排不了。')
        timing = {k: args[k] for k in ('after_seconds', 'every_seconds', 'at', 'clock') if args.get(k) is not None}
        op = args.get('op') or ('create' if args.get('intent') and timing and not args.get('plan_id') else None)
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
                        raise Refused('只有在家里才能把安排挂到一条线上。')
                    wanted = self._text(args, 'line', 80)
                    where = next((item for item in lines.peer_lines(self.store) if item['label'] == wanted), None)
                    if not where:
                        raise Refused('没有这条线；照抄 lines_from_program 里的 line。')
                plan = run(lambda: c.scheduler.create(ep, spec, plan_id='plan-' + sha(canonical([ep['_id'], call_id]))[:32],
                                                      where=where))
            elif op in ('update', 'cancel'):
                plan_id = self._text(args, 'plan_id', 200)
                row = planned.get(plan_id)
                if not row:
                    raise Refused('「%s」不在 plans_from_program 里；照那里原样抄 plan_id。' % plan_id)
                if op == 'cancel':
                    plan = run(lambda: c.scheduler.cancel(plan_id, ep['scene_id'], ep['person_id'], ep['policy_epoch']))
                else:
                    if row.get('status') not in ('CREATING', 'ACTIVE'):
                        raise Refused('这条安排现在是 %s，改期只对着还生效的；要再安排就新建一条。' % row.get('status'))
                    spec = {**({'intent': args['intent']} if args.get('intent') else {}), **({'schedule': timing} if timing else {})}
                    plan = run(lambda: c.scheduler.update(ep, plan_id, spec))
            else:
                raise Refused('op 是 create、update 或 cancel。')
        except ValueError as exc:
            # 换算/校验类失败（时间已过、钟点不存在、形状不对）回给她自己改，带上现在的钟面。
            clock = schedule_rules.local_clock(schedule_rules.scene_timezone(
                self.store.config, self.store.db.scenes.find_one({'_id': ep['scene_id']})), schedule_rules.now_utc())
            raise Refused('没安排成：%s。现在是 %s（%s，%s）。' % (exc, clock['now_local'], clock['weekday'],
                                                            clock['timezone'])) from None
        return {'plan_id': plan['_id'], 'status': plan['status'], 'scheduled_at': plan.get('scheduled_at'),
                'next_fire_at': plan.get('next_fire_at'), 'timezone': plan.get('timezone'),
                'plan_version': plan.get('plan_version', 1)}, False

    def tool_group_action(self, ep, call_id, args):
        from . import group_admin
        item = {k: args[k] for k in ('kind', 'who', 'duration', 'which', 'reason') if args.get(k) is not None}
        return group_admin.queue(self.store, ep, 0, item, key='group_action:' + call_id), False

    def tool_visit(self, ep, call_id, args):
        from . import places
        if turn_kind(ep) not in VISIT_FROM or self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Refused('只有在家里的心跳或你自己定的计划到期时才能出门。')
        if any(call.get('tool') == 'visit' and 'result' in call for call in (ep.get('tool_calls') or {}).values()):
            raise Refused('这一拍已经出过一次门了；下一拍再去别处。')
        place = self._text(args, 'place', 40)
        intent = args.get('intent')
        if intent not in places.VISIT_INTENTS:
            raise Refused('intent 是 %s 之一。' % '、'.join(places.VISIT_INTENTS))
        topic = self._text(args, 'topic', places.TOPIC_CHARS, required=False)
        artifact = self._text(args, 'artifact_id', 200, required=False)
        if artifact and intent != 'share_picture':
            raise Refused('只有 intent=share_picture 才带 artifact_id。')
        if not self.coordinator.scheduler:
            raise Refused('现在没有定时服务，出不了门。')
        return self.coordinator.scheduler.visit(ep, place, intent, topic, artifact), False

    def tool_errand(self, ep, call_id, args):
        from .places import ERRAND_CHARS
        if self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Denied('ERRAND_ONLY_AT_HOME')
        if turn_kind(ep) != 'external':
            raise Denied('ERRAND_ONLY_WHEN_ASKED')
        place = self._text(args, 'place', 40)
        request = self._text(args, 'request', ERRAND_CHARS)
        artifact = self._text(args, 'artifact_id', 200, required=False)
        if not self.coordinator.scheduler:
            raise Refused('现在没有定时服务，办不了。')
        return self.coordinator.scheduler.errand(ep, call_id, place, request, bool(args.get('exactly')), artifact), False

    # ── notes between her conversations (ADR-018) ───────────────────
    def _note(self, ep, call_id, args, cls):
        from . import credentials, notes
        if not self.coordinator.scheduler:
            raise Refused('现在没有定时服务，便条送不出去。')
        args = {**args, 'text': credentials.scrub(str(args.get('text') or ''))}     # never a credential value
        try:
            return self.coordinator.scheduler.note(ep, cls, args, call_id), False
        except notes.NoteRefused as exc:
            self.store.audit(ep['_id'], 'note.refused', {'code': exc.code, 'to': str(args.get('to') or '')[:40]},
                             ep['scope_key'])
            raise Refused(str(exc)) from None

    def tool_pass_note(self, ep, call_id, args):
        if self._cls(ep) != visibility.OWNER_PRIVATE:
            raise Refused('在外面用 leave_note。')
        return self._note(ep, call_id, args, visibility.OWNER_PRIVATE)

    def tool_leave_note(self, ep, call_id, args):
        if self._cls(ep) == visibility.OWNER_PRIVATE:
            raise Refused('在家里用 pass_note。')
        return self._note(ep, call_id, args, visibility.PUBLIC)

    # ── her own peer lines (ADR-013 §6) ─────────────────────────────
    def tool_peer_line(self, ep, call_id, args):
        from . import lines
        from .persona_model import timezone as persona_zone
        from .render import model_and_policy
        wanted = self._text(args, 'line', 80)
        line = next((item for item in lines.peer_lines(self.store) if item['label'] == wanted), None)
        if not line:
            raise Refused('没有这条线；照抄 lines_from_program 里的 line。')
        op = args.get('op')
        if op not in ('open', 'close'):
            raise Refused('op 是 open 或 close。')
        if op == 'close' and args.get('close_for') not in lines.CLOSE_FOR:
            raise Refused('关的时候要选 close_for：%s。' % '、'.join(lines.CLOSE_FOR))
        model, policy = model_and_policy(self.store, ep['persona'])
        zone = persona_zone(model, policy, self.store.config)[0]
        lines.set_line(self.store, line['scene_id'], closed=op == 'close', choice=args.get('close_for'), zone=zone,
                       by='character:' + ep['_id'])
        return {'line': line['label'], 'state': lines.describe(lines.closed_until(self.store, line['scene_id']), zone)}, False

    # ── her improvement ideas (ADR-011 §6.2) ────────────────────────
    def tool_note_idea(self, ep, call_id, args):
        idea = self._text(args, 'idea', IDEA_CHARS)
        why = self._text(args, 'why', IDEA_CHARS)
        noted = [call for call in (ep.get('tool_calls') or {}).values() if call.get('tool') == 'note_idea' and 'result' in call]
        if len(noted) >= IDEAS_PER_TURN:
            raise Refused('这回合已经记了 %d 条想法，先到这里。' % IDEAS_PER_TURN)
        row = note_idea(self.store, ep['persona'], idea, why, key=[ep['_id'], call_id],
                        source={'by': 'character', 'scene_id': ep['scene_id'], 'episode_id': ep['_id'],
                                'turn': turn_kind(ep)})
        return {'noted': row['_id'], 'note': '记下了。它会在你的自我改进时间里再拿出来，现在不用去改。'}, False

    def tool_read_ideas(self, ep, call_id, args):
        from . import schedule_rules
        items = ideas_block(self.store, ep['persona'], schedule_rules.now_utc())
        more = ideas_left(self.store, ep['persona'], len(items))
        return {'items': items, **({'more': more} if more else {}),
                'note': '逐条用 review_idea 写下处理结果；采纳的用 delegate 交代行动脑去做。'
                if items else '想法本里没有还没处理完的想法。'}, False

    def tool_review_idea(self, ep, call_id, args):
        idea_id = self._text(args, 'idea', 200)
        decision = args.get('decision')
        why = self._text(args, 'why', IDEA_CHARS)
        if decision not in ('adopt', 'defer', 'drop'):
            raise Refused('decision 是 adopt、defer 或 drop。')
        row = self.store.db.ideas.find_one({'_id': idea_id, 'persona': ep['persona']})
        if not row or row.get('state') not in ('open', 'deferred'):
            raise Refused('「%s」不是想法本里还没处理完的一条；照 ideas_from_program 或 read_ideas 里的原样抄 _id。' % idea_id)
        state = {'adopt': 'adopted', 'defer': 'deferred', 'drop': 'dropped'}[decision]
        from .state import now
        self.store.put('ideas', {**row, 'state': state, 'decisions': [*(row.get('decisions') or []),
            {'decision': decision, 'why': why, 'episode_id': ep['_id'], 'at': now()}]},
            expected=row['revision'], stream=idea_id)
        note = {'adopt': '采纳了：用 delegate 把要做的事交代给行动脑。', 'defer': '暂缓了，下次自我改进时还会看到它。',
                'drop': '放弃了，理由已留档。'}[decision]
        return {'idea': idea_id, 'state': state, 'note': note}, False

    def tool_promote_memory(self, ep, call_id, args):
        item = {k: args[k] for k in ('fact', 'appraisal', 'signal', 'why', 'source_ids', 'visibility') if args.get(k) is not None}
        for field in ('fact', 'appraisal', 'signal', 'why'):
            self._text(item, field, 2000)
        if not isinstance(item.get('source_ids'), list) or not item['source_ids'] or not all(
                isinstance(x, str) for x in item['source_ids']):
            raise Refused('source_ids 是来源 id 的列表。')
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


def ideas_block(store, persona, moment, limit=20):
    """Her notebook for a self-improvement turn, in words: open ideas first (oldest first), then deferred ones, so
    ideas she put off never crowd out new ones (ideas_left counts what the limit leaves out)."""
    from datetime import datetime
    from .config import ago
    from .people import People
    people = People(store, persona)
    rows = list(store.db.ideas.find({'persona': persona, 'state': 'open'}).sort('created_at', 1).limit(limit))
    rows += list(store.db.ideas.find({'persona': persona, 'state': 'deferred'}).sort('created_at', 1)
                 .limit(limit - len(rows))) if len(rows) < limit else []
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
                      **({'when': ago(hours)} if hours is not None else {}),
                      **({'deferred_before': row['decisions'][-1]['why']} if row.get('state') == 'deferred' and row.get('decisions') else {})})
    return items


def ideas_left(store, persona, shown):
    """Words for the open or deferred ideas a listing of ``shown`` items leaves out, or None."""
    waiting = store.db.ideas.count_documents({'persona': persona, 'state': {'$in': ['open', 'deferred']}})
    return '还有 %d 条没列出，处理掉几条就会轮到它们。' % (waiting - shown) if waiting > shown else None


def _seed_text(store, slug):
    for seed in (store.config.get('persona_contribution') or {}).get('seeds', []):
        if seed.get('slug') == slug:
            return seed['kind'], Path(seed['path']).read_text(encoding='utf-8')
    return None, None


def read_sections(store, ep, items, cls):
    """recall with sections: readable section text, and what could not be read (in words)."""
    docs, out, missing = DocumentStore(store, ep['persona']), [], []
    for item in items:
        _, content = docs.read(item['doc'])
        section = next((s for s in (content or {}).get('sections', []) if s['sid'] == item['sid']), None)
        if not section:
            missing.append('%s#%s：没有这一节' % (item['doc'], item['sid']))
        elif not visibility.readable(section['visibility'], cls):
            missing.append('%s#%s：这里读不到' % (item['doc'], item['sid']))
        else:
            out.append({'doc': item['doc'], 'sid': section['sid'], 'heading': section['heading'],
                        'body': section['body'], 'visibility': section['visibility']})
    return out, missing


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
        raise Denied('PROMOTION_QUOTA: %d' % quota)
    picked = selections(store, effective(model, 'memory.promotion.window_days', policy) or 7)
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
        raise Denied('PROMOTION_SOURCES_INSUFFICIENT: %d turns / %d dates; need %d / %d'
                     % (len(episodes), len(dates), need_roots, need_dates))
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
    return {'memory_id': doc['_id'], 'scope_key': scope}
