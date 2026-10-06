"""The relevance gate (attend.py): a group turn nobody addressed to her asks 接话 or 不理 before any recall."""

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
    assert not attend.gated({'kind': 'group'}, {'group_context': {'wake_reason': 'mentioned_account'}})
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
    character = FakeLane(store, [FakeTurn([('think', {'thought': '有人叫我，想了想还是不说。'}),
                                           ('stay_silent', {'reason': '想了想还是不说'})])])
    coordinator = Coordinator(store, character)
    coordinator.attend = FakeLane(store, [LaneResult('接话：有人提到我')])
    ep = coordinator.ingest(gated_event(20002, '演示 你怎么看', 'name_called'), persona='P1')
    assert [call['phase'] for call in character.calls] == ['TURN']
    assert ep['state'] == 'COMMITTED' and ep['silent_reason'] == '想了想还是不说'
    assert ep['attend']['choice'] == 'join' and ep['context']['attend_from_program'].endswith('有人提到我')
    assert '有人提到我' in character.calls[0]['messages'][-1]['content']
    assert store.db.messages.find_one({'_id': 'in-' + ep['_id']})['processing_outcome'] == 'ATTEND_JOIN'


def test_a_gate_that_cannot_answer_lets_the_message_pass(store):
    setup(store)
    coordinator = Coordinator(store, FakeLane(store, []))
    coordinator.attend = Boom()
    ep = coordinator.ingest(gated_event(20003, '有人吗', 'reply_in_active_topic'), persona='P1')
    assert ep['state'] == 'COMMITTED' and ep['attend']['choice'] == 'quiet'
    assert store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'attend.failed'})


def test_addressed_messages_skip_the_gate(store):
    setup(store)
    character = FakeLane(store, [FakeTurn([('think', {'thought': '有人 @ 我，看到了，不用说。'}),
                                           ('stay_silent', {'reason': '不用说'})])])
    coordinator = Coordinator(store, character)
    coordinator.attend = FakeLane(store, [])
    ep = coordinator.ingest(gated_event(20004, '@演示 在吗', 'mentioned_account'), persona='P1')
    assert [call['phase'] for call in character.calls] == ['TURN'] and 'attend' not in ep
    assert ep['state'] == 'COMMITTED' and coordinator.attend.calls == []


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
