"""What her turns' blocks are for, said once in her role system prompt (ADR-056 rule 1).

A notice carries what changes; the turn instruction (`prompts/turn.md`), what each block is for and the rules for
reading memories are fixed text, so they sit in the system prompt, which is fixed per conversation. A block whose
`note` is the one written here arrives without it; a note worded for this turn (another text) stays with its block.
"""
from __future__ import annotations

from .config import prompt_path


def notes():
    """block key -> the explanations it may carry (a block worded per place has more than one)."""
    from . import (affect, attend, context, credentials, dice, group_members, host_stops, lines, night, notes as _notes, notices,
                   outbound_media, places, questions, restarts, self_review, stickers, switches, waiting)
    return {
        'recent_thoughts_from_program': (context.THOUGHTS_NOTE,),
        'understanding_update_from_program': (context.UNDERSTANDING_NOTE,),
        'people_from_program': (context.PEOPLE_NOTE,),
        'doc_refs_from_program': (context.DOC_REFS_NOTE,),
        'ideas_from_program': (context.IDEAS_NOTE,),
        'recent_experience_from_program': (context.EXPERIENCE_NOTE,),
        'notes_from_program': (_notes.RECEIVED_NOTE,),
        'notes_sent_from_program': (_notes.SENT_NOTE,),
        'notices_from_program': (notices.HELD_NOTE,),
        'passed_from_program': (attend.PASSED_NOTE,),
        'questions_from_program': (questions.BLOCK_NOTE,),
        'members_from_program': (group_members.BLOCK_NOTE,),
        'your_pictures_from_program': (outbound_media.OWN_PICTURES_NOTE,),
        'credentials_from_program': (credentials.CREDENTIALS_NOTE,),
        'places_from_program': (places.PLACES_NOTE,),
        'last_visits_from_program': (places.VISITS_NOTE,),
        'errands_from_program': (places.ERRANDS_NOTE,),
        'elsewhere_from_program': (places.ELSEWHERE_NOTE,),
        'lines_from_program': (lines.VIEW_NOTE,),
        'peer_asides_from_program': (lines.ASIDES_NOTE,),
        'stickers_from_program': (stickers.HOME_NOTE, stickers.SEND_NOTE),
        'night_from_program': (night.NOTE,),
        'restart_from_program': (restarts.NOTE,),
        'host_from_program': (host_stops.NOTE,),
        'waiting_from_program': (waiting.NOTE,),
        'affect_from_program': (affect.PUBLIC_MOOD_NOTE,),
        'switches_from_program': (switches.NOTE,),
        'self_review_from_program': (self_review.NOTE,),
        'dice_review_from_program': (dice.REVIEW_NOTE,),
        **_tiered_notes(),
    }


def _tiered_notes():
    """The blocks tiered memory adds (ADR-062), only when its switch is on."""
    from . import memory_tiers
    if not memory_tiers.ENABLED:
        return {}
    return {'things_from_program': (memory_tiers.THINGS_NOTE,), 'night_list_from_program': (memory_tiers.NIGHT_NOTE,),
            'memory_week_from_program': (memory_tiers.WEEK_NOTE,)}


# How the delivery's own lines read (context-delivery.js writes them without their explanation).
DELIVERY = (
    ('unchanged_from_program', '这些块和本会话前面给出的一样，没有变化，仍以前面那份为准。'),
    ('repeated_from_program', '本会话里已经有的消息、记忆和你的心里话不再列：delivered_history、group_continuity_from_program '
                              '的原话、memories 和 recent_thoughts_from_program 只给新的；一句话一回合只给一次；任务的原话在眼前时'
                              '只给 original_input_id（那句的 _id）。'),
    ('restored_from_program', '对话刚压缩过，前面说没变、同前或不再重复的资料里，有的已经不在眼前了：这里列出的块在下面重新给出。'),
    ('same_as_before', '一个列表（一个块，或块里的一个列表）里，其余几条和本会话前面给出的一样，没再列出；后面写着它们的状态和编号，'
                       '要对哪条做事就照抄它的编号。'
                       '等你处理的那几条总会列出来。'),
)


def strip(context):
    """The context without the explanations the guide already gives."""
    known = notes()
    out = {}
    for key, value in context.items():
        if isinstance(value, dict) and value.get('note') in known.get(key, ()):
            value = {k: v for k, v in value.items() if k != 'note'}
        out[key] = value
    return out


# How her words leave, said once for the conversation (turn.md's {words} and {ending}): where only speak speaks
# (a channel that declares reply parts), or where what she writes is what is said.
WORDS = {False: '你用工具做事；写在正文里的话会按顺序发给对方，和工具调用写在同一步的也一样。',
         True: '你用工具做事；这里只有 speak 发得出去，正文不发：写在正文里的话只是你自己的。'}
ENDING = {False: '结束：还有话要说，写一段只有要说的话的正文；说完了或这回合不说话，调用 stay_silent。',
          True: '结束：要说的话都用 speak 说；说完了或这回合不说话，就不再调用工具：这一回合到此为止，不算漏了什么。'}


def guide(config, speaks=False):
    """The fixed text of her turns: how a turn goes, what each block is, how to read memories. `speaks`: the
    conversation speaks only through speak."""
    from .context import MEMORY_SOURCE_RULES
    turn = prompt_path(config, 'turn.md').read_text(encoding='utf-8').strip()
    turn = turn.replace('{words}', WORDS[bool(speaks)]).replace('{ending}', ENDING[bool(speaks)])
    lines = ['# 每回合的资料', '带 _from_program 的块是程序事实；带 _at 的字段是本地钟点，和 clock_from_program 同一时区。'
             '下面是各块的说明，块里不再重复；某块自己带的 note 是这一回合特有的话，以它为准。']
    lines += ['- %s：%s' % pair for pair in DELIVERY]
    for key, texts in notes().items():
        lines.append('- %s：%s' % (key, '／'.join(texts)))
    lines += ['', '# 记忆的来源', MEMORY_SOURCE_RULES]
    from . import memory_tiers
    if memory_tiers.ENABLED:
        lines += ['', '# 记忆放在哪', memory_tiers.TOLD]          # ADR-062 §4.3: once per conversation
    return turn + '\n\n' + '\n'.join(lines)
