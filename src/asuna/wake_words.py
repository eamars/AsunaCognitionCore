"""What woke her when no one spoke (ADR-108 D5): one versioned table by episode kind.

A turn the program opened carries no `speaker`: the person on its event only authorized it, and a head that names them as
speaking beside the action brain's text is the precondition for taking that text as theirs. It carries
`woken_by_program` instead, saying what woke her and who wrote the event's text. A person's line keeps `speaker`.

The words are program text for the character brain: 你 is her. Bump WAKE_VERSION with any change to them.
"""
WAKE_VERSION = 1

# Episode kind -> the words. `note` names the place the note was written in (a %s).
WAKE_WORDS = {
    'task_feedback': '你交给行动脑的事交回了结果；event 里是行动脑写的',
    'consult': '行动脑做事时有话问你；event 里是行动脑写的',
    'scheduled': '你自己定的计划到点了',
    'visit': '你自己出门来这里看看',
    'presence': '心跳到了',
    'self_development': '自我改进的时候到了',
    'settlement': '夜里的沉淀',
    'note': '你在%s写的便条到了',
}
SOMEWHERE_ELSE = '别处'
# A kind added later and not yet in the table still reads as what it is: not a person speaking. A test holds that every
# kind the program opens a turn with has words of its own (tests/test_woken_by_program.py).
GENERIC = '不是有人在跟你说话，是程序叫醒了你'


def woken_by(store, persona, event):
    """The words for a program-woken turn, or None for a person's line (the kind `external`, which keeps `speaker`)."""
    kind = event.get('episode_kind') or 'external'
    if kind == 'external':
        return None
    words = WAKE_WORDS.get(kind)
    if words is None:
        return GENERIC
    if kind != 'note':
        return words
    from . import notes
    from .people import People
    from .records import scenes as scene_records
    first = notes.opening_for(store, event) or {}
    scene = scene_records.get(store, first['from_scene']) if first.get('from_scene') else None
    return words % (People(store, persona).scene_title(scene) if scene else SOMEWHERE_ELSE)
