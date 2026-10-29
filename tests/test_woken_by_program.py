"""ADR-108 D5, A3 and A2: a turn the program opened says what woke her and carries no `speaker`; a line from the local
chat is numbered in its notice; every line shows its number, whatever its channel can quote."""
from asuna import capabilities, wake_words
from asuna.context import CONTEXT_HEAD, local_line, order_context
from asuna.ingress import CORE_NOTICE_KINDS, INTERNAL_KINDS
from asuna.people import People
from asuna.wake_words import GENERIC, WAKE_WORDS, woken_by
from asuna.records import scenes as scene_records
from test_people import BOT, SCENE, row


def setup(store):
    """A QQ group scene whose channel declares nothing, and a local owner (the neutral model reads him as 本机用户)."""
    store.config['chat'] = {**store.config.get('chat', {}), 'person_id': 'local-user', 'persona': 'demo',
                            'display_name': '演示'}
    store.config.pop('persona_model', None)
    scene_records.save(store, {'_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE,
                               'channel_account_id': BOT, 'policy_epoch': 1, 'sequence': 0, 'members': ['qq:20002']})
    return scene_records.get(store, SCENE)


def test_every_kind_the_program_opens_a_turn_with_has_words_of_its_own():
    kinds = {*INTERNAL_KINDS, *CORE_NOTICE_KINDS, 'consult'}
    assert sorted(kinds - set(WAKE_WORDS)) == [], 'a kind the program opens a turn with needs its words (wake_words.py)'
    assert 'external' not in WAKE_WORDS, 'a person speaking keeps speaker'


def test_a_persons_line_keeps_speaker_and_a_program_woken_turn_has_none(store):
    scene = setup(store)
    people = People(store, 'demo')
    spoken = people.relabel({'person_id': 'qq:20002', 'event': {'text': 'hi'}}, scene, 'qq:20002')
    assert 'speaker' in spoken and 'person_id' not in spoken
    woken = people.relabel({'person_id': 'qq:20002', 'event': {'text': '结果'}}, scene, 'qq:20002', speaking=False)
    assert 'speaker' not in woken and 'person_id' not in woken, 'the person only authorized it; the head names no one'
    assert woken_by(store, 'demo', {'episode_kind': 'external'}) is None
    assert woken_by(store, 'demo', {}) is None, 'no kind is a person speaking'
    assert woken_by(store, 'demo', {'episode_kind': 'task_feedback'}) == WAKE_WORDS['task_feedback']
    assert woken_by(store, 'demo', {'episode_kind': 'scheduled'}) == WAKE_WORDS['scheduled']
    assert woken_by(store, 'demo', {'episode_kind': 'a_kind_added_later'}) == GENERIC


def test_a_note_names_the_place_it_was_written_in(store):
    scene = setup(store)
    words = woken_by(store, 'demo', {'episode_kind': 'note', 'note': {'id': 'no-such-note'}})
    assert words == WAKE_WORDS['note'] % wake_words.SOMEWHERE_ELSE, 'a note that cannot be found says so'


def test_woken_by_program_takes_the_head_slot_speaker_had():
    ordered = order_context({'event': {}, 'woken_by_program': 'x', 'scene': 's', 'session_class': 'c'})
    assert list(ordered)[:3] == ['scene', 'woken_by_program', 'session_class']
    assert CONTEXT_HEAD.index('woken_by_program') == CONTEXT_HEAD.index('speaker') + 1


def test_a_local_chat_line_is_numbered_in_its_notice_and_nothing_else_is():
    local = {'scene_seq': 12, 'event': {}}
    assert local_line(local, {'episode_kind': 'external'}) == '〔12〕'
    assert local_line(local, {}) == '〔12〕'
    assert local_line({'scene_seq': 12, 'event': {'channel': {'id': 'qq'}}}, {}) is None, 'a channel line has its label line'
    assert local_line(local, {'episode_kind': 'task_feedback'}) is None, 'a program-woken turn has no calling line'
    assert local_line(None, {}) is None and local_line({'event': {}}, {}) is None


def test_every_line_shows_its_number_though_its_channel_cannot_quote(store):
    scene = setup(store)
    capabilities.forget()
    assert capabilities.can_quote(store, scene) is False, 'nothing declared: no quoting here'
    people = People(store, 'demo')
    line = row(20002, '一句话', card='阿杰')
    line['scene_seq'] = 7
    assert '〔7〕' in people.transcript(scene, line)
    assert people.pointed(scene, line).startswith('〔7〕 ')
    capabilities.forget()


# ADR-108 D1: a line that came into her view during a turn is hers there only where the turn can answer in that
# conversation; otherwise it keeps its own turn.
def _seen_by(store, tools):
    from types import SimpleNamespace
    from asuna.coordinator import Coordinator
    from asuna.ingress import persist_input
    from asuna.records import messages as message_records
    scene = scene_records.get(store, SCENE) or setup(store)
    line, _ = persist_input(store, {'event_id': 'evt-seen', 'scene_id': SCENE, 'person_id': 'qq:20002',
                                    'text': '你在吗'}, managed=True)
    ep = {'_id': 'ep-turn', 'scene_id': SCENE, 'scope_key': scene['scope_key'], 'turn_tools': tools}
    Coordinator._absorb(SimpleNamespace(store=store), ep, [line['_id']])
    return message_records.get(store, line['_id'], scene=SCENE).get('absorbed_by')


def test_a_line_seen_in_a_turn_that_can_speak_there_is_that_turns(store):
    setup(store)
    assert _seen_by(store, ['think', 'speak']) == 'ep-turn'


def test_a_line_seen_in_a_turn_that_cannot_speak_there_keeps_its_own_turn(store):
    setup(store)
    assert _seen_by(store, ['think', 'task.answer']) is None
    assert _seen_by(store, None) is None
