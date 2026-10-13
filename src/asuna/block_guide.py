"""What her turns' blocks are for, said once in her role system prompt (ADR-056 rule 1).

A notice carries what changes; the turn instruction (`prompts/turn.md`), what each block is for and the rules for
reading memories are fixed text, so they sit in the system prompt, which is fixed per conversation. A block whose
`note` is the one written here arrives without it; a note worded for this turn (another text) stays with its block.
"""
from __future__ import annotations

from .config import prompt_path


def notes():
    """block key -> the explanations it may carry (a block worded per place has more than one)."""
    from . import (affect, context, credentials, dice, developer_inbox, group_members, host_stops, lines, night, notes as
                   _notes, outbound_media, places, restarts, self_review, stickers, switches, waiting)
    return {
        'recent_thoughts_from_program': (context.THOUGHTS_NOTE,),
        'doc_refs_from_program': (context.DOC_REFS_NOTE,),
        'ideas_from_program': (context.IDEAS_NOTE,),
        'recent_experience_from_program': (context.EXPERIENCE_NOTE,),
        'notes_from_program': (_notes.RECEIVED_NOTE,),
        'notes_sent_from_program': (_notes.SENT_NOTE,),
        'developer_inbox_from_program': (developer_inbox.BLOCK_NOTE,),
        'members_from_program': (group_members.BLOCK_NOTE,),
        'your_pictures_from_program': (outbound_media.OWN_PICTURES_NOTE,),
        'credentials_from_program': (credentials.CREDENTIALS_NOTE,),
        'places_from_program': (places.PLACES_NOTE,),
        'last_visits_from_program': (places.VISITS_NOTE,),
        'errands_from_program': (places.ERRANDS_NOTE,),
        'elsewhere_from_program': (places.ELSEWHERE_NOTE,),
        'lines_from_program': (lines.VIEW_NOTE,),
        'peer_asides_from_program': (lines.ASIDES_NOTE,),
        'stickers_from_program': (stickers.HOME_NOTE, stickers.STICKERS_NOTE),
        'night_from_program': (night.NOTE,),
        'restart_from_program': (restarts.NOTE,),
        'host_from_program': (host_stops.NOTE,),
        'waiting_from_program': (waiting.NOTE,),
        'affect_from_program': (affect.PUBLIC_MOOD_NOTE,),
        'switches_from_program': (switches.NOTE,),
        'self_review_from_program': (self_review.NOTE,),
        'dice_review_from_program': (dice.REVIEW_NOTE,),
    }


# How the delivery's own lines read (context-delivery.js writes them without their explanation).
DELIVERY = (
    ('unchanged_from_program', '这些块和本会话前面给出的一样，没有变化，仍以前面那份为准。'),
    ('repeated_from_program', '已经在本会话里的消息、记忆和你自己写下的心里话不再重复列出；delivered_history、'
                              'group_continuity_from_program 里的原话、memories 和 recent_thoughts_from_program 只含新的。'
                              '同一句话一回合只给一次：在 delivered_history 里的，别的块不再列；任务的原话在眼前时只给'
                              ' original_input_id（那句的 _id）。'),
    ('restored_from_program', '对话刚压缩过，前面说没变、同前或不再重复的资料里，有的已经不在眼前了：这里列出的块在下面重新给出。'),
    ('same_as_before', '一个列表（一个块，或块里的一个列表）里，其余几条和本会话前面给出的一样，没再列出；后面写着它们的状态。'
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


def guide(config):
    """The fixed text of her turns: how a turn goes, what each block is, how to read memories."""
    from .context import MEMORY_SOURCE_RULES
    turn = prompt_path(config, 'turn.md').read_text(encoding='utf-8').strip()
    lines = ['# 每回合的资料', '带 _from_program 的块是程序事实；带 _at 的字段是本地钟点，和 clock_from_program 同一时区。'
             '下面是各块的说明，块里不再重复；某块自己带的 note 是这一回合特有的话，以它为准。']
    lines += ['- %s：%s' % pair for pair in DELIVERY]
    for key, texts in notes().items():
        lines.append('- %s：%s' % (key, '／'.join(texts)))
    lines += ['', '# 记忆的来源', MEMORY_SOURCE_RULES]
    return turn + '\n\n' + '\n'.join(lines)
