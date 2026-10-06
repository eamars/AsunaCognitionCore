"""ADR-009 P5 MongoDB tests: T5.4 multi-segment speech, T5.9 segment crash recovery."""
from datetime import datetime
from types import SimpleNamespace
import threading

import pytest

from asuna.channels import Channels
from asuna.coordinator import Coordinator
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import THINK

SPEECH = '第一段，先说这个。\n---split---\n第二段。\n---split---\n第三段收尾。'
TARGET = {'type': 'dm', 'id': 'peer'}


def model(max_messages):
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
            'speak': {'max_messages': max_messages, 'split_marker': '---split---', 'chars_per_second': 4,
                      'min_gap_s': 1, 'max_gap_s': 3}}


def channel_scene(store):
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': 'dm-a', 'sender_id': 'peer', 'person_id': 'A', 'target': TARGET}}}}
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.put('scenes', {**scene, 'channel_id': 'replay'}, expected=scene['revision'])


def turn(store, key='one', crash=None, speech=SPEECH, channel=True):
    lane = FakeLane(store, [FakeTurn([THINK], speech)])
    coordinator = Coordinator(store, lane)
    event = {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'}
    if channel:
        event['channel'] = {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-' + key}
        persist_input(store, event, managed=True)
    if crash:
        coordinator.crash = crash
    return coordinator, coordinator.ingest(event)


def outbound(store, ep_id):
    return list(store.db.messages.find({'episode_id': ep_id, 'phase': 'SPEAK'}).sort('scene_seq', 1))


def channels(store):
    return Channels(SimpleNamespace(app=SimpleNamespace(store=store), stopping=threading.Event(), reconfiguring=False))


def release(store, rows):
    """Move pacing into the past so the test does not sleep."""
    for row in rows:
        fresh = store.db.messages.find_one({'_id': row['_id']})
        store.put('messages', {**fresh, 'not_before': '2000-01-01T00:00:00+00:00'}, expected=fresh['revision'],
                  stream=fresh['episode_id'])


def receipt(bridge, item, status):
    body = {'attempt_id': item['attempt_id'], 'status': status, 'response': {}}
    if status == 'platform_accepted':
        body['platform_message_id'] = 'm-' + item['publication_id']
    return bridge.receipt('replay', item['publication_id'], body)


def test_T5_4_segments_pacing_claim_and_failure(store):
    store.config['persona_model'] = model(3)
    channel_scene(store)
    _, ep = turn(store)
    rows = outbound(store, ep['_id'])
    assert [r['_id'] for r in rows] == [ep['_id'] + ':speak:%d' % i for i in range(3)]
    assert [r['text'] for r in rows] == ['第一段，先说这个。', '第二段。', '第三段收尾。']
    assert all(r['delivery_state'] == 'QUEUED_EXTERNAL' and r['segment_count'] == 3 for r in rows)
    times = [datetime.fromisoformat(r['not_before']) for r in rows]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    assert all(1 <= gap <= 3 for gap in gaps) and gaps[0] == 9 / 4
    bridge = channels(store)
    first = bridge.claim('replay')['items'][0]
    assert first['publication_id'] == rows[0]['_id']
    assert bridge.claim('replay') == {'items': []}, 'segment 2 is not due yet'
    release(store, rows[1:2])
    assert bridge.claim('replay') == {'items': []}, 'segment 2 waits for segment 1 to settle'
    receipt(bridge, first, 'failed')
    states = [r['delivery_state'] for r in outbound(store, ep['_id'])]
    assert states == ['FAILED', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_AFTER_FAILURE']
    assert bridge.claim('replay') == {'items': []}


def test_T5_4_paced_segments_deliver_in_order_and_hold_the_line(store):
    store.config['persona_model'] = model(3)
    channel_scene(store)
    _, ep = turn(store)
    rows = outbound(store, ep['_id'])
    bridge = channels(store)
    for index in range(3):
        release(store, rows[index:index + 1])
        item = bridge.claim('replay')['items'][0]
        assert item['publication_id'] == rows[index]['_id']
        assert receipt(bridge, item, 'platform_accepted') == {'status': 'DELIVERED'}
    assert [r['delivery_state'] for r in outbound(store, ep['_id'])] == ['DELIVERED'] * 3


def test_T5_9_crash_after_first_segment_resumes_in_order(store):
    store.config['persona_model'] = model(3)
    channel_scene(store)
    calls = []

    def crash(point):
        if point == 'after_segment_publish' and not calls:
            calls.append(point)
            raise RuntimeError('crash between segments')
    with pytest.raises(RuntimeError, match='crash between segments'):
        turn(store, crash=crash)
    ep = store.db.episodes.find_one({'state': 'SPEAK_ACCEPTED'})
    before = outbound(store, ep['_id'])
    assert [r['delivery_state'] for r in before] == ['QUEUED_EXTERNAL', 'READY', 'READY']
    coordinator = Coordinator(store, FakeLane(store, []))
    coordinator.recover()
    after = outbound(store, ep['_id'])
    assert [r['_id'] for r in after] == [r['_id'] for r in before], 'no new rows on recovery'
    assert [r['delivery_state'] for r in after] == ['QUEUED_EXTERNAL'] * 3
    assert store.db.episodes.find_one({'_id': ep['_id']})['state'] == 'COMMITTED'


def test_T5_9_sending_segment_becomes_unknown_and_cancels_the_rest(store):
    store.config['persona_model'] = model(3)
    channel_scene(store)
    _, ep = turn(store)
    bridge = channels(store)
    bridge.claim('replay')                                  # segment 1 is SENDING when the host dies
    bridge.recover_sending()
    states = [r['delivery_state'] for r in outbound(store, ep['_id'])]
    assert states == ['UNKNOWN', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_AFTER_FAILURE']


def test_she_marks_where_a_message_ends_and_code_leaves_whole():
    from asuna.rhythm import SPLIT_MARKER, split_speech
    assert SPLIT_MARKER == '[分条]'
    assert split_speech('哈哈哈这个我懂 [分条] 不过说真的', SPLIT_MARKER, 3) == ['哈哈哈这个我懂', '不过说真的']
    code = '先看日志：\n```\ngrep x [分条] app.log\n```'
    assert split_speech('好 [分条]\n' + code, SPLIT_MARKER, 3) == ['好', code]          # a marker in code is text
    assert split_speech('一[分条]二[分条]三[分条]四', SPLIT_MARKER, 3) == ['一', '二', '三\n四']
    assert split_speech('一段话\n\n又一段', SPLIT_MARKER, 3) == ['一段话\n\n又一段']      # blank lines never split
    assert split_speech('一[分条]二', SPLIT_MARKER, 1) == ['一[分条]二']                # one message: untouched


def test_only_a_platform_turn_is_told_how_its_words_leave(store):
    store.config['persona_model'] = model(3)
    _, local = turn(store, key='local', speech='好', channel=False)
    assert 'speak_from_program' not in local['context']
    channel_scene(store)
    _, qq = turn(store, key='qq', speech='好')
    speak = qq['context']['speak_from_program']
    assert '---split---' in speak['messages'] and '最多 3 条' in speak['messages'] and '代码块' in speak['messages']
    assert '不会再单独叫你' in speak['new_lines'] and '工具调用旁边' in speak['sent']
    store.config['persona_model'] = model(1)
    _, one = turn(store, key='one-message', speech='好')
    assert set(one['context']['speak_from_program']) == {'sent', 'new_lines', 'one_self'}     # ADR-018 §5.7


def test_everything_she_wrote_in_the_turn_is_said(store):
    channel_scene(store)
    for count, texts in ((3, ['那必须的，被夸了我会更来劲。', '他教没教我不好说。']),
                         (1, ['那必须的，被夸了我会更来劲。\n\n他教没教我不好说。'])):
        store.config['persona_model'] = model(count)
        lane = FakeLane(store, [FakeTurn([THINK, ('feel', {})], '他教没教我不好说。', said=['那必须的，被夸了我会更来劲。'])])
        event = {'event_id': 'said-%d' % count, 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你最近的回复好快！',
                 'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-said-%d' % count}}
        persist_input(store, event, managed=True)
        ep = Coordinator(store, lane).ingest(event)
        assert [r['text'] for r in outbound(store, ep['_id'])] == texts
