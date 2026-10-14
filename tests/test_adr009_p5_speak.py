"""ADR-009 P5 MongoDB tests: her reply's parts leave in order at typing pace (T5.4) and survive a crash (T5.9); words
written where only reply speaks never leave (ADR-064 phase 2); elsewhere her words are one message."""
from datetime import datetime
from types import SimpleNamespace
import threading

import pytest

from asuna import channel_kinds
from asuna.channels import Channels
from asuna.coordinator import Coordinator, UNSENT_NOTE
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, FakeTurn
from reply_parts import said
from test_adr009_p2 import THINK

PARTS = ('第一段，先说这个。', '第二段。', '第三段收尾。')
TARGET = {'type': 'dm', 'id': 'peer'}


def model(max_messages):
    return {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
            'speak': {'max_messages': max_messages, 'chars_per_second': 4, 'min_gap_s': 1, 'max_gap_s': 3}}


def channel_scene(store, monkeypatch=None):
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': 'dm-a', 'sender_id': 'peer', 'person_id': 'A', 'target': TARGET}}}}
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.put('scenes', {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    if monkeypatch:
        # A kind where she speaks only through reply (the QQ kind declares this; the test channel stands in for it).
        monkeypatch.setattr(channel_kinds, 'reply_parts',
                            lambda scene_id: ('text', 'sticker', 'picture') if scene_id == 'dm-a' else ())


def turn(store, key='one', crash=None, calls=None, channel=True, content=''):
    lane = FakeLane(store, [FakeTurn([THINK, *(calls if calls is not None else [said(*PARTS)])], content)])
    coordinator = Coordinator(store, lane)
    event = {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'}
    if channel:
        event['channel'] = {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-' + key}
        persist_input(store, event, managed=True)
    if crash:
        coordinator.crash = crash
    return coordinator, coordinator.ingest(event), lane


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


def test_T5_4_parts_pacing_claim_and_failure(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    _, ep, lane = turn(store)
    rows = outbound(store, ep['_id'])
    assert [r['_id'] for r in rows] == [ep['_id'] + ':speak:%d' % i for i in range(3)]
    assert [r['text'] for r in rows] == list(PARTS)
    assert all(r['delivery_state'] == 'QUEUED_EXTERNAL' and r['reply_part'] for r in rows)
    [result] = [row[4] for row in lane.tool_results if row[2] == 'speak']
    assert result['note'] == '发出 3 条，都排上了：1 text；2 text；3 text。送没送到看下一回合的历史。'
    times = [datetime.fromisoformat(r['not_before']) for r in rows[1:]]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    assert all(1 <= gap <= 3 for gap in gaps)
    bridge = channels(store)
    first = bridge.claim('replay')['items'][0]
    assert first['publication_id'] == rows[0]['_id']
    assert bridge.claim('replay') == {'items': []}, 'part 2 is not due yet'
    release(store, rows[1:2])
    assert bridge.claim('replay') == {'items': []}, 'part 2 waits for part 1 to settle'
    receipt(bridge, first, 'failed')
    states = [r['delivery_state'] for r in outbound(store, ep['_id'])]
    assert states == ['FAILED', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_AFTER_FAILURE']
    assert bridge.claim('replay') == {'items': []}


def test_T5_4_paced_parts_deliver_in_order_and_hold_the_line(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    _, ep, _ = turn(store)
    rows = outbound(store, ep['_id'])
    bridge = channels(store)
    for index in range(3):
        release(store, rows[index:index + 1])
        item = bridge.claim('replay')['items'][0]
        assert item['publication_id'] == rows[index]['_id']
        assert receipt(bridge, item, 'platform_accepted') == {'status': 'DELIVERED'}
    assert [r['delivery_state'] for r in outbound(store, ep['_id'])] == ['DELIVERED'] * 3


def test_T5_9_a_crash_between_parts_still_sends_what_reply_queued(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    calls = []

    def crash(point):
        if point == 'after_reply_part_publish' and not calls:
            calls.append(point)
            raise RuntimeError('crash between parts')
    with pytest.raises(RuntimeError, match='crash between parts'):
        turn(store, crash=crash)
    ep = store.db.episodes.find_one({'state': 'TURN'})
    before = outbound(store, ep['_id'])
    assert [r['delivery_state'] for r in before] == ['QUEUED_EXTERNAL', 'READY', 'READY']
    coordinator = Coordinator(store, FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'why': '说完了'})])]))
    coordinator.recover()
    after = outbound(store, ep['_id'])
    assert [r['_id'] for r in after] == [r['_id'] for r in before], 'no new rows on recovery'
    assert [r['delivery_state'] for r in after] == ['QUEUED_EXTERNAL'] * 3


def test_T5_9_sending_part_becomes_unknown_and_cancels_the_rest(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    _, ep, _ = turn(store)
    bridge = channels(store)
    bridge.claim('replay')                                  # part 1 is SENDING when the host dies
    bridge.recover_sending()
    states = [r['delivery_state'] for r in outbound(store, ep['_id'])]
    assert states == ['UNKNOWN', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_AFTER_FAILURE']


def test_one_wrong_part_sends_nothing_and_says_which(store, monkeypatch):
    store.config['persona_model'] = model(2)
    channel_scene(store, monkeypatch)
    bad = ('speak', {'parts': [{'kind': 'text', 'text': '好'}, {'kind': 'sticker', 'name': '没收着的'},
                               {'kind': 'text', 'text': '好'}, {'kind': 'text', 'text': '[分条]三'}]})
    _, ep, lane = turn(store, calls=[bad, said('一'), said('二'), said('二'), said('三')])
    results = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    refused = results[0][0]
    assert not results[0][1] and refused.startswith('这次一条都没发：')
    assert '第 2 条 sticker「没收着的」你没收着' in refused and '第 3 条这回合已经发过一样的' in refused
    assert '第 4 条：一个 text 就是一条消息' in refused and refused.endswith('改好再调用一次 speak。')
    assert results[1][1] and results[2][1]
    assert not results[3][1] and '已经发过一样的' in results[3][0], 'the same text twice in one turn'
    assert not results[4][1] and '最多 2 行' in results[4][0], 'her speak.max_messages counts lines across calls'
    assert [r['text'] for r in outbound(store, ep['_id'])] == ['一', '二']


def test_words_outside_reply_never_leave_come_back_once_and_are_told_next_time(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    lane = FakeLane(store, [FakeTurn([THINK], '这段写在正文里'), FakeTurn([], '还是写在正文里')])
    event = {'event_id': 'body-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-body-1'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert ep['state'] == 'COMMITTED' and outbound(store, ep['_id']) == []
    assert lane.calls[1]['messages'][-1]['content'] == UNSENT_NOTE % '这段写在正文里', 'handed back once, same turn'
    _, nxt, _ = turn(store, key='body-2')
    assert nxt['context']['unsent_from_program'] == '没发出去：「还是写在正文里」'
    _, again, _ = turn(store, key='body-3')
    assert 'unsent_from_program' not in again['context'], 'said once'


def test_words_also_sent_through_speak_are_not_unsent_and_stay_silent_needs_no_why_after_speaking(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    lane = FakeLane(store, [FakeTurn([THINK, said('就这样吧'), ('stay_silent', {})], said=['就这样吧'])])
    event = {'event_id': 'dup-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '然后呢',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-dup-1'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert len(lane.calls) == 1, 'nothing handed back'
    assert [ok for _, _, name, _, _, ok in lane.tool_results if name == 'stay_silent'] == [True]
    assert not (store.db.scenes.find_one({'_id': 'dm-a'}) or {}).get('unsent'), 'said through speak: not unsent'
    assert [r['text'] for r in outbound(store, ep['_id'])] == ['就这样吧']


def test_words_beside_stay_silent_come_back_too_and_a_reply_then_sends_them(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    words = '我觉得挺好\n\n就是贵了点，' + '真的' * 60
    lane = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'reason': '说完了'})], said=[words]),
                            FakeTurn([said('我觉得挺好'), ('stay_silent', {'reason': '说完了'})])])
    event = {'event_id': 'body-s', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你看呢',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-body-s'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert lane.calls[1]['messages'][-1]['content'] == UNSENT_NOTE % words, 'whole, as written; stay_silent drops nothing'
    assert ep['state'] == 'COMMITTED' and [r['text'] for r in outbound(store, ep['_id'])] == ['我觉得挺好']


def test_lines_count_in_every_message_blank_lines_and_code_do_not(store, monkeypatch):
    """Owner 2026-10-14: in online chat a line break is another message, so her limit counts lines."""
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    code = '看这个：' + chr(10) + '```' + chr(10) + 'print(1)' + chr(10) + 'print(2)' + chr(10) + '```'
    two = '第一行' + chr(10) + chr(10) + '第二行'
    _, ep, lane = turn(store, calls=[said(two), said('第三行', '第四行'), said(code)])
    results = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    assert results[0][1], 'a blank line is not a line'
    assert not results[1][1] and '第 2 条有 1 行（前面已经 3 行）' in results[1][0], 'two lines in one message count as two'
    assert not results[2][1], 'a code block is one line, its words another: over 3'
    assert [r['text'] for r in outbound(store, ep['_id'])] == [two]


def test_silence_says_how_many_parts_reply_sent(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    _, _, lane = turn(store, calls=[said('嗯'), ('stay_silent', {'why': '说完了'})])
    [result] = [row[4] for row in lane.tool_results if row[2] == 'stay_silent']
    assert result['sent'] == 'speak 这回合发了 1 条。'
    _, _, lane = turn(store, key='quiet', calls=[('stay_silent', {'why': '不说'})])
    [result] = [row[4] for row in lane.tool_results if row[2] == 'stay_silent']
    assert result['sent'] == '这回合 speak 一条都没发。'


def test_only_a_platform_turn_is_told_how_its_words_leave(store, monkeypatch):
    store.config['persona_model'] = model(3)
    _, local, _ = turn(store, key='local', calls=[], content='好', channel=False)
    assert 'speak_from_program' not in local['context']
    channel_scene(store)
    _, plain, _ = turn(store, key='plain', calls=[], content='好')
    assert set(plain['context']['speak_from_program']) == {'sent', 'new_lines', 'one_self'}     # ADR-018 §5.7
    assert '作一条消息发出去' in plain['context']['speak_from_program']['sent']
    channel_scene(store, monkeypatch)
    _, replying, _ = turn(store, key='replying')
    sent = replying['context']['speak_from_program']['sent']
    assert sent.startswith('这里只有 speak 发得出去') and '最多 3 行' in sent and '一个代码块算一行' in sent


def test_where_words_are_speech_everything_she_wrote_is_one_message(store):
    channel_scene(store)
    store.config['persona_model'] = model(3)
    lane = FakeLane(store, [FakeTurn([THINK, ('feel', {})], '他教没教我不好说。', said=['那必须的，被夸了我会更来劲。'])])
    event = {'event_id': 'said-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你最近的回复好快！',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-said-1'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert [r['text'] for r in outbound(store, ep['_id'])] == ['那必须的，被夸了我会更来劲。\n\n他教没教我不好说。']
