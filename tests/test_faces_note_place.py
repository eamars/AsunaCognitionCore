"""ADR-103 (the owner, 2026-10-30): the 小黄脸 note is said only where faces can go.

`faces_from_program` arrives only where the platform declares its own faces and stickers can leave the conversation
(context.py, stickers.has_faces). Its explanation used to sit in the guide of every conversation -- her local chat,
her agent line and every development line included -- so the writing half was read where a face cannot be sent.
The filter is mechanical: the same condition that adds the block, not a judgement the model is asked to make.
"""
from asuna import block_guide, channel_kinds, render, stickers
from test_people import BOT, GROUP

HOME_SCENE = {'_id': 'scene:local-dm', 'kind': 'dm'}

# What a conversation with no QQ no longer pays for: that line and its newline off the guide, measured here
# 2026-10-30 (6,509 characters with it, 6,142 without). A re-worded note has to come back and move this number,
# the way a grown tool description has to raise its line in tests/test_tool_budget.py.
FACES_LINE = 367


def qq_scene(kind='group'):
    return {'_id': channel_kinds.get('qq').scene_id(BOT, kind, GROUP if kind == 'group' else BOT),
            'channel_id': 'qq', 'kind': kind}


def test_the_faces_note_is_said_only_where_faces_can_go():
    assert '小黄脸' in block_guide.guide({}, faces=True)
    assert '小黄脸' not in block_guide.guide({}, faces=False)
    assert 'faces_from_program' in block_guide.notes(faces=True)
    assert 'faces_from_program' not in block_guide.notes(faces=False)
    assert len(block_guide.guide({}, faces=True)) - len(block_guide.guide({}, faces=False)) == FACES_LINE


def test_only_the_faces_line_is_filtered():
    kept, without = block_guide.notes(faces=True), block_guide.notes(faces=False)
    assert set(kept) - set(without) == {'faces_from_program'}
    assert all(kept[key] == without[key] for key in without)


def test_has_faces_is_exactly_when_the_block_can_arrive():
    assert stickers.has_faces(qq_scene()) and stickers.has_faces(qq_scene('dm'))
    assert not stickers.has_faces(HOME_SCENE)                       # her local chat: no channel at all
    for kind in (type('NoFaces', (), {'KIND': 'nofaces', 'STICKERS': True}),      # sends stickers, no faces table
                 type('FacesOnly', (), {'KIND': 'facesonly', 'FACES': {'笑': '1'}})):   # names them, cannot send
        channel_kinds._KINDS[kind.KIND] = kind
        try:
            assert not stickers.has_faces({'_id': '%s:1:group:7' % kind.KIND, 'channel_id': kind.KIND, 'kind': 'group'})
        finally:
            channel_kinds._KINDS.pop(kind.KIND, None)


def test_the_block_never_repeats_its_explanation():
    stripped = block_guide.strip({'faces_from_program': {'seen_here': ['微笑'], 'note': stickers.FACES_NOTE}})
    assert stripped['faces_from_program'] == {'seen_here': ['微笑']}


class _NoStore:
    config = {}

    def audit(self, *args, **kwargs):
        pass


def test_an_older_system_ref_renders_the_guide_as_it_was_written():
    """A ref from before the flag said the note in every conversation: re-rendering it must not drift."""
    ref = {'render_sha256': 'never-cached', 'carried': {'persona': [], 'voice': []}}
    assert '小黄脸' in render.system_for(_NoStore(), dict(ref))
    assert '小黄脸' not in render.system_for(_NoStore(), dict(ref, faces=False))
