"""The relevance gate (attend.py): a group turn nobody addressed to her asks 接话 or 不理 before any recall."""

import re

from asuna import attend
from asuna.channels import called_by_name
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from test_people import BOT, GROUP, SCENE, row, setup as people_setup


def setup(store):
    """The people tests' group, with members so turns are authorized."""
    scene = people_setup(store)
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'members': ['qq:20002', 'qq:20003', 'qq:20004', 'local-user']}})
    return {**scene, 'members': ['qq:20002', 'qq:20003', 'qq:20004', 'local-user']}


def gated_event(number, text, reason='proactive_unprompted', at='2026-10-04T01:00:00+00:00'):
    item = row(number, text, card='阿杰', at=at)
    event = {'event_id': 'evt-' + str(number) + text, 'scene_id': SCENE, 'person_id': 'qq:' + str(number),
             'text': text, 'channel': item['event']['channel'],
             'group_context': {'wake_reason': reason, 'topic_id': 't1', 'mentioned_account_ids': []},
             'raw': item['event']['raw']}
    return event


class Boom:
    def generate(self, *args, **kwargs):
        raise RuntimeError('model server unreachable')


def test_parse_takes_only_the_two_answers():
    assert attend.parse('接话：有人在问我刚才说的事') == {'choice': 'join', 'reason': '有人在问我刚才说的事'}
    assert attend.parse('\n不理：他们在聊游戏\n多余的') == {'choice': 'quiet', 'reason': '他们在聊游戏'}
    odd = attend.parse('我觉得可以说两句')
    assert odd['choice'] == 'quiet' and odd['unparsed'] == '我觉得可以说两句'
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'name_called'}})
    # ADR-086 E1: an @ or a reply to her is asked too, unless it answers what she waits for or asked; the ambiguous
    # looks stay asked.
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'mentioned_account'}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'reply_to_character'}})
    assert not attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'mentioned_account', 'answers_her': True}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'awaited_answer'}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'question_wait'}})
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'watched'}})
    assert not attend.gated({'kind': 'dm'}, {'group_context': {'wake_reason': 'proactive_unprompted'}})


def test_her_name_without_an_at_is_a_name_call(store):
    setup(store)
    assert called_by_name(store, '演示 你怎么看')
    assert not called_by_name(store, '大家怎么看')


def test_quiet_ends_the_turn_before_any_recall(store):
    setup(store)
    character = FakeLane(store, [])                                   # any full-turn stage would fail here
    gate = FakeLane(store, [LaneResult('不理：他们在聊游戏，我插不上话')])
    coordinator = Coordinator(store, character)
    coordinator.attend = gate
    event = gated_event(20002, '今晚开黑吗')
    ep = coordinator.ingest(event, persona='P1')
    assert ep['state'] == 'COMMITTED' and ep['attend'] == {'choice': 'quiet', 'reason': '他们在聊游戏，我插不上话'}
    assert ep['silent_reason'].startswith('不理') and ep['context'] == {} and character.calls == []
    message = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    assert message['processing_outcome'] == 'ATTEND_QUIET'
    sent = gate.calls[0]['messages'][-1]['content']
    assert '[阿杰 #1]' in sent and '20002' not in sent and BOT not in sent and GROUP not in sent
    assert attend.GATED['proactive_unprompted'] in sent and '不熟' in sent


def test_join_runs_the_full_turn_with_her_reason(store):
    setup(store)
    character = FakeLane(store, [FakeTurn([('think', {'thought': '有人叫我，想了想还是不说。'})])])
    coordinator = Coordinator(store, character)
    coordinator.attend = FakeLane(store, [LaneResult('接话：有人提到我')])
    ep = coordinator.ingest(gated_event(20002, '演示 你怎么看', 'name_called'), persona='P1')
    assert [call['phase'] for call in character.calls] == ['TURN']
    # In a group a turn that does not speak is silent; her reason is her thought.
    assert ep['state'] == 'COMMITTED' and ep['silent_reason'] == '这回合没有 speak'
    assert ep['attend']['choice'] == 'join' and ep['context']['attend_from_program'].endswith('有人提到我')
    assert '有人提到我' in character.calls[0]['messages'][-1]['content']
    assert store.db.messages.find_one({'_id': 'in-' + ep['_id']})['processing_outcome'] == 'ATTEND_JOIN'


def test_her_next_turn_there_lists_once_the_lines_she_let_pass_with_her_reason(store):
    """ADR-086 §16 (her ask): the line is already in her conversation, so the list says she looked and let it pass."""
    setup(store)
    character = FakeLane(store, [FakeTurn([('think', {'thought': '有人叫我。'})]), FakeTurn([('think', {'thought': '再看看。'})])])
    coordinator = Coordinator(store, character)
    coordinator.attend = FakeLane(store, [LaneResult('不理：他们在聊游戏'), LaneResult('接话：有人提到我'),
                                          LaneResult('接话：又有人提到我')])
    coordinator.ingest(gated_event(20002, '今晚开黑吗'), persona='P1')
    ep = coordinator.ingest(gated_event(20003, '演示 你怎么看', 'name_called', at='2026-10-04T01:05:00+00:00'), persona='P1')
    [item] = ep['context']['passed_from_program']['items']
    assert re.fullmatch(r'\[阿杰 #1\] \d{1,2}/\d{1,2} \d{2}:\d{2}：看过，没接（他们在聊游戏）', item), item
    assert '20002' not in item
    again = coordinator.ingest(gated_event(20003, '演示 还在吗', 'name_called', at='2026-10-04T01:06:00+00:00'), persona='P1')
    assert 'passed_from_program' not in again['context'], 'listed once'
    assert not store.db.artifacts.count_documents({'kind': attend.PASSED_KIND})


class Chunked:
    """A gate whose answer takes long enough for the memory chunker to stamp the line it is judging."""
    def __init__(self, store, lane):
        self.store, self.lane = store, lane

    def generate(self, *args, **kwargs):
        row = self.store.db.messages.find_one({'direction': 'inbound'}, sort=[('scene_seq', -1)])
        self.store.put('messages', {**row, 'memory_chunk_version': 2}, expected=row['revision'], stream='chunk')
        return self.lane.generate(*args, **kwargs)


def test_a_line_changed_while_the_gate_thinks_still_gets_its_turn(store):
    setup(store)
    character = FakeLane(store, [FakeTurn([('think', {'thought': '他在回我。'}), ('stay_silent', {'why': '不用说'})])])
    coordinator = Coordinator(store, character)
    coordinator.attend = Chunked(store, FakeLane(store, [LaneResult('接话：他在回我')]))
    ep = coordinator.ingest(gated_event(20002, '没有这东西', 'reply_in_active_topic'), persona='P1')
    assert ep['state'] == 'COMMITTED' and ep['attend']['choice'] == 'join'
    assert [call['phase'] for call in character.calls] == ['TURN']
    message = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    assert message['processing_outcome'] == 'ATTEND_JOIN' and message['memory_chunk_version'] == 2


def test_a_gate_that_cannot_answer_lets_the_message_pass_as_the_programs_failure_not_her_choice(store):
    setup(store)
    coordinator = Coordinator(store, FakeLane(store, []))
    coordinator.attend = Boom()
    ep = coordinator.ingest(gated_event(20003, '有人吗', 'reply_in_active_topic'), persona='P1')
    assert ep['state'] == 'COMMITTED' and ep['attend'] == {'choice': 'failed', 'reason': '没判出来：程序出错（RuntimeError）'}
    assert ep['silent_reason'].startswith('没判出来') and '不理' not in ep['silent_reason']
    assert store.db.messages.find_one({'_id': 'in-' + ep['_id']})['processing_outcome'] == 'ATTEND_FAILED'
    assert store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'attend.failed'})
    # Her home turns count it for a day, by group, in words.
    from datetime import datetime, timedelta, timezone
    from asuna import host_stops
    said = host_stops.block(store, 'UTC', datetime.now(timezone.utc), 'P1')
    assert said == {'missed_looks': host_stops.MISSED % (said['missed_looks'].split('：')[-1])}
    assert said['missed_looks'].endswith(' 1 次（程序出错 1）') and '不是你选的不理' in said['missed_looks']
    assert host_stops.block(store, 'UTC', datetime.now(timezone.utc) + timedelta(hours=25), 'P1') is None


def test_each_gate_question_has_its_own_session_and_its_repairs_stay_in_it():
    from asuna.native_worker import gate_session_id
    first, again = gate_session_id('c:g:1:P1', 'ep-1:ATTEND:0'), gate_session_id('c:g:1:P1', 'ep-2:ATTEND:0')
    assert first != again and first.startswith('asuna-attend-')
    assert gate_session_id('c:g:1:P1', 'ep-1:ATTEND:0:fix-1') == first


def test_an_addressed_line_is_asked_at_the_gate_and_stays_visible_when_let_pass(store):
    """ADR-086 E1: an @ or a reply to her meets the gate; 不理 is "not now": the line keeps its row, its verdict and
    her reason are in the audit, and the catch-up of her next turn there still shows it."""
    from asuna.attend import recent
    setup(store)
    character = FakeLane(store, [])                                   # no full turn runs
    coordinator = Coordinator(store, character)
    coordinator.attend = FakeLane(store, [LaneResult('不理：这会儿没劲头，回头再说')])
    ep = coordinator.ingest(gated_event(20004, '@演示 在吗', 'mentioned_account'), persona='P1')
    assert ep['state'] == 'COMMITTED' and ep['attend']['choice'] == 'quiet' and character.calls == []
    asked = coordinator.attend.calls[0]['messages'][-1]['content']
    assert '有人 @ 了你' in asked and '被 @ 了也可以不理' in asked
    message = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    assert message['processing_outcome'] == 'ATTEND_QUIET' and message['attend']['reason'] == '这会儿没劲头，回头再说'
    assert store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'attend.verdict', 'payload.choice': 'quiet'})
    scene = store.db.scenes.find_one({'_id': SCENE})
    lines, _ = recent(store, scene, message['scene_seq'])
    assert any('在吗' in line for line in lines), lines                 # her next look here still shows it


def test_a_gate_that_cannot_answer_an_addressed_line_falls_back_to_the_full_turn(store):
    """ADR-086 E1, her condition: a failed gate on an @ is not her 不理; the turn runs as before the gate asked."""
    setup(store)
    character = FakeLane(store, [FakeTurn([('think', {'thought': '有人 @ 我。'}), ('stay_silent', {'why': '不用说'})])])
    coordinator = Coordinator(store, character)
    coordinator.attend = Boom()
    ep = coordinator.ingest(gated_event(20004, '@演示 在吗', 'mentioned_account'), persona='P1')
    assert [call['phase'] for call in character.calls] == ['TURN'] and ep['state'] == 'COMMITTED'
    assert ep['attend']['choice'] == 'failed' and 'attend_from_program' not in ep['context']
    assert store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'attend.fallback'})
    assert store.db.messages.find_one({'_id': 'in-' + ep['_id']})['processing_outcome'] == 'ATTEND_FAILED'


def test_an_addressed_answer_to_what_she_waits_for_is_not_gated_but_an_ordinary_at_is(store):
    """ADR-086 E1, her condition: an @ or a reply to her from the person she is waiting on must wake her; an @ from
    anyone else is asked at the gate like the rest."""
    from datetime import datetime, timezone
    from asuna.config import character_id
    from test_watches import intake, world
    from test_group_admin import BOT, SCENE
    world(store)
    scene = store.db.scenes.find_one({'_id': SCENE})
    store.db.messages.insert_one({'_id': 'in-ep-ask', 'schema_version': 1, 'scene_id': SCENE, 'policy_epoch': scene['policy_epoch'],
                                  'scene_seq': 900, 'direction': 'inbound', 'author': 'qq:20002', 'text': '嗨'})
    store.db.messages.insert_one({'_id': 'out-901', 'schema_version': 1, 'scene_id': SCENE, 'policy_epoch': scene['policy_epoch'],
                                  'scene_seq': 901, 'direction': 'outbound', 'author': character_id(store.config),
                                  'delivery_state': 'DELIVERED', 'reply_to': 'in-ep-ask', 'episode_id': 'ep-ask', 'text': '你有空吗',
                                  'receipt_at': datetime.now(timezone.utc).isoformat()})
    store.db.episodes.insert_one({'_id': 'ep-ask', 'schema_version': 1, 'await_answer': {'why': '问他有没有空'}})
    line = intake(store)
    answer = line('20002', 'e-answer', mentions=[BOT])
    assert answer['group_context']['wake_reason'] == 'mentioned_account' and answer['group_context']['answers_her']
    assert not attend.gated({'kind': 'group'}, answer)
    other = line('20003', 'e-other', mentions=[BOT])
    assert other['group_context']['wake_reason'] == 'mentioned_account' and 'answers_her' not in other['group_context']
    assert attend.gated({'kind': 'group'}, other)


def test_catch_up_reaches_back_to_her_last_words_within_an_hour(store):
    from datetime import datetime, timezone
    from asuna.context import catch_up
    setup(store)
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc).timestamp()
    stamp = lambda minutes: datetime.fromtimestamp(now - minutes * 60, timezone.utc).isoformat()
    store.db.messages.insert_one({'_id': 'mine', 'scene_id': SCENE, 'direction': 'outbound', 'author': 'demo',
                                  'delivery_state': 'DELIVERED', 'scene_seq': 5, 'schema_version': 1})
    store.config['character_id'] = 'demo'
    # newest first: 30 lines in the last 25 minutes (after her line), then 10 from two hours ago
    rows = [{'_id': 'r%d' % n, 'scene_seq': 100 - n, 'received_at': stamp(n * 0.8)} for n in range(30)]
    rows += [{'_id': 'old%d' % n, 'scene_seq': 60 - n, 'received_at': stamp(120 + n)} for n in range(10)]
    kept = catch_up(store, {'_id': SCENE}, rows, now_ts=now)
    assert [row['_id'] for row in kept] == ['r%d' % n for n in range(30)]
    quiet = [{'_id': 'q%d' % n, 'scene_seq': 4 - n, 'received_at': stamp(90 + n)} for n in range(20)]
    assert len(catch_up(store, {'_id': SCENE}, quiet, now_ts=now)) == 12      # never fewer than the last 12


def test_a_line_she_waits_on_gets_one_look_at_the_asked_persons_next_line(store):
    """Owner 2026-10-06: a line addressed to someone (answered or @-tagged) waits by default, like a reply; she turns it
    off with await_answer wait=no. The addressed person; once; within AWAIT_SECONDS. Lines addressed elsewhere are not
    hers to look at."""
    from datetime import datetime, timedelta, timezone
    from asuna.channels import AWAIT_SECONDS, awaited_answer
    from asuna.config import character_id
    scene = setup(store)
    scene = store.db.scenes.find_one({'_id': SCENE})
    me = character_id(store.config)
    store.db.messages.insert_one({'_id': 'in-ep-ask', 'schema_version': 1, 'scene_id': SCENE, 'policy_epoch': scene['policy_epoch'],
                                  'scene_seq': 900, 'direction': 'inbound', 'author': 'qq:20002', 'text': '嗨'})

    def said(seconds_ago, waits=True, seq=901, text='', reply_to='in-ep-ask'):
        store.db.messages.delete_many({'direction': 'outbound', 'scene_id': SCENE})
        store.db.messages.insert_one({'_id': 'out-%d' % seq, 'schema_version': 1, 'scene_id': SCENE, 'policy_epoch': scene['policy_epoch'],
            'scene_seq': seq, 'direction': 'outbound', 'author': me, 'delivery_state': 'DELIVERED',
            'reply_to': reply_to, 'episode_id': 'ep-ask', 'text': text,
            'receipt_at': (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()})
        store.db.episodes.delete_many({'_id': 'ep-ask'})
        choice = {'await_answer': {'why': '问他怎么有空'}} if waits is True else {'await_answer': {'off': True}} if waits == 'off' else {}
        store.db.episodes.insert_one({'_id': 'ep-ask', 'schema_version': 1, **choice})

    said(30)
    assert awaited_answer(store, scene, 'qq:20002', [], None)                   # the asked person, unaddressed
    assert not awaited_answer(store, scene, 'qq:20003', [], None)               # someone else
    assert not awaited_answer(store, scene, 'qq:20002', ['20003'], None)        # @s someone else
    assert not awaited_answer(store, scene, 'qq:20002', [], 'm-other')          # quotes something
    said(AWAIT_SECONDS + 5)
    assert not awaited_answer(store, scene, 'qq:20002', [], None)               # too late: people moved on
    said(30, waits=False)
    assert awaited_answer(store, scene, 'qq:20002', [], None)                   # answering him waits by default
    said(30, waits='off')
    assert not awaited_answer(store, scene, 'qq:20002', [], None)               # she turned it off for this line
    if not store.db.scene_people.find_one({'scene_id': SCENE, 'handle': 1}):
        store.db.scene_people.insert_one({'_id': SCENE + '|qq:20002', 'schema_version': 1, 'scene_id': SCENE,
                                          'person': 'qq:20002', 'handle': 1})
    said(30, waits=False, reply_to='in-internal-visit', text='@[阿杰 #1] 你来看看')
    assert awaited_answer(store, scene, 'qq:20002', [], None)                   # an @-tag of hers waits for that person
    assert not awaited_answer(store, scene, 'qq:20003', [], None)
    said(30, waits=False, reply_to='in-internal-visit', text='大家晚上好')
    assert not awaited_answer(store, scene, 'qq:20002', [], None)               # a remark to nobody: no wait
    said(30)
    store.db.messages.insert_one({'_id': 'in-look', 'schema_version': 1, 'scene_id': SCENE, 'scene_seq': 902, 'direction': 'inbound',
                                  'author': 'qq:20002', 'event': {'group_context': {'wake_reason': 'awaited_answer'}}})
    assert not awaited_answer(store, scene, 'qq:20002', [], None)               # one look per line of hers
    assert attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'awaited_answer'}})


def test_the_gate_reads_her_core_her_notes_here_and_what_she_wrote_of_the_speaker_cut_the_same_every_time(store):
    """Owner and her, 2026-10-14: core sentences, not the persona's talking rules; this group's own context."""
    from asuna.documents import DocumentStore
    from asuna.group_admin import notes_slug
    scene = setup(store)
    docs = DocumentStore(store, 'P1')
    docs.apply('core', {'op': 'append_section', 'heading': '一', 'reason': '我是谁', 'visibility': 'public',
                        'inject': 'always', 'kind': 'working'}, '我愿意帮忙，也会说不想帮。',
               base_revision_id=None, author='character', mutation_id='core-1')
    docs.apply(notes_slug(SCENE), {'op': 'append_section', 'heading': '这群', 'reason': '记', 'visibility': 'public',
                                   'inject': 'always'}, '聊游戏为主。' + '细' * 900, base_revision_id=None,
               author='character', mutation_id='notes-1')
    key = 'relationship:qq:20002|' + scene['scope_key']
    store.db.state_heads.insert_one({'_id': key, 'schema_version': 1, 'revision_id': 'rev-u'})
    store.db.state_revisions.insert_one({'_id': 'rev-u', 'schema_version': 1, 'content': {'body': '阿杰说话快，爱开玩笑。'}})
    system = attend.system(store, 'P1')
    assert '我愿意帮忙' in system
    event = gated_event(20002, '今晚开黑吗')
    item = {**row(20002, '今晚开黑吗', card='阿杰'), 'scene_seq': 1}
    first = attend.material(store, scene, event, item, 'P1')
    assert first['your_notes_here'].startswith('这群：聊游戏为主。') and len(first['your_notes_here']) == attend.NOTES_CHARS + 1
    assert first['speaker_understanding'] == '阿杰说话快，爱开玩笑。'
    assert attend.material(store, scene, event, item, 'P1')['your_notes_here'] == first['your_notes_here'], 'the same cut'
