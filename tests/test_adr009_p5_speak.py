"""ADR-009 P5 MongoDB tests: her reply's parts leave in order at typing pace (T5.4) and survive a crash (T5.9); words
written where only reply speaks never leave (ADR-064 phase 2); elsewhere her words are one message."""
from datetime import datetime
from types import SimpleNamespace
import threading

import pytest

from asuna import channel_kinds, role_tools
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
    assert bridge.claim('replay')['items'] == [], 'part 2 is not due yet'
    release(store, rows[1:2])
    assert bridge.claim('replay')['items'] == [], 'part 2 waits for part 1 to settle'
    receipt(bridge, first, 'failed')
    states = [r['delivery_state'] for r in outbound(store, ep['_id'])]
    assert states == ['FAILED', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_AFTER_FAILURE']
    assert bridge.claim('replay')['items'] == []


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


def test_a_part_queued_after_an_earlier_part_failed_is_cancelled_when_it_comes_up(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    _, ep, _ = turn(store)
    rows = outbound(store, ep['_id'])
    # The live race of 2026-10-21: part 1 failed before parts 2 and 3 were queued, so cancel_after did not reach them
    # and the line stopped for good behind part 2.
    first = store.db.messages.find_one({'_id': rows[0]['_id']})
    store.put('messages', {**first, 'delivery_state': 'FAILED', 'failure': 'PLATFORM_REFUSED'},
              expected=first['revision'], stream=first['episode_id'])
    release(store, rows[1:])
    assert channels(store).claim('replay')['items'] == []
    assert [r['delivery_state'] for r in outbound(store, ep['_id'])] == [
        'FAILED', 'CANCELLED_AFTER_FAILURE', 'CANCELLED_AFTER_FAILURE']


def test_a_waiting_part_holds_its_own_conversation_and_no_other(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    store.config['channels']['replay']['routes']['peer-b'] = {
        'scene_id': 'dm-b', 'sender_id': 'peer-b', 'person_id': 'B', 'target': {'type': 'dm', 'id': 'peer-b'}}
    scene = store.db.scenes.find_one({'_id': 'dm-b'})
    store.put('scenes', {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    _, ep, _ = turn(store)
    bridge = channels(store)
    sending = bridge.claim('replay')['items'][0]            # part 1 is on its way; parts 2 and 3 wait for it
    lane = FakeLane(store, [FakeTurn([THINK], '好的，收到。')])
    event = {'event_id': 'b-one', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '在吗',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': {'type': 'dm', 'id': 'peer-b'},
                         'platform_event_id': 'p-b-one'}}
    persist_input(store, event, managed=True)
    other = Coordinator(store, lane).ingest(event)
    [line] = outbound(store, other['_id'])
    # Queued behind the waiting parts, as the shared queue orders them.
    last = max(r['scene_seq'] for r in outbound(store, ep['_id']))
    store.put('messages', {**line, 'scene_seq': last + 100}, expected=line['revision'], stream=line['episode_id'])
    release(store, outbound(store, ep['_id'])[1:])
    item = bridge.claim('replay')['items'][0]
    assert item['publication_id'] == line['_id'], 'the other conversation is not held by her waiting parts'
    assert sending['publication_id'] == outbound(store, ep['_id'])[0]['_id']
    assert [r['delivery_state'] for r in outbound(store, ep['_id'])][1:] == ['QUEUED_EXTERNAL'] * 2


def test_conversations_take_turns_by_when_their_lines_were_queued(store, monkeypatch):
    store.config['persona_model'] = model(1)
    channel_scene(store, monkeypatch)
    store.config['channels']['replay']['routes']['peer-b'] = {
        'scene_id': 'dm-b', 'sender_id': 'peer-b', 'person_id': 'B', 'target': {'type': 'dm', 'id': 'peer-b'}}
    scene = store.db.scenes.find_one({'_id': 'dm-b'})
    store.put('scenes', {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    event = {'event_id': 'b-one', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '在吗',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': {'type': 'dm', 'id': 'peer-b'},
                         'platform_event_id': 'p-b-one'}}
    persist_input(store, event, managed=True)
    other = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '好的，收到。')])).ingest(event)
    [early] = outbound(store, other['_id'])
    _, ep, _ = turn(store, calls=[said('嗯，在。')])
    release(store, outbound(store, ep['_id']))
    [late] = outbound(store, ep['_id'])
    assert early['queued_at'] and late['queued_at'], 'a line records when it was queued'
    # Each conversation counts its own lines: the one queued first can carry the larger number.
    store.put('messages', {**early, 'scene_seq': late['scene_seq'] + 100, 'queued_at': '2026-01-01T00:00:00+00:00'},
              expected=early['revision'], stream=early['episode_id'])
    bridge = channels(store)
    first = bridge.claim('replay')['items'][0]
    assert first['publication_id'] == early['_id'], 'the line queued first goes first'
    assert receipt(bridge, first, 'platform_accepted') == {'status': 'DELIVERED'}
    assert bridge.claim('replay')['items'][0]['publication_id'] == late['_id']


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
    # Past her usual (speak.max_messages) it is sent and the result gives the numbers (ADR-084).
    assert results[4][1] and results[4][0]['lines'] == '这回合已说 3 行（你平时 2 行以内，硬线 6）'
    assert [r['text'] for r in outbound(store, ep['_id'])] == ['一', '二', '三']


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
    # Told, not pushed: leaving it is a stated choice, and speaking is speak (ADR-064, 2026-10-26).
    assert '让它留着' in UNSENT_NOTE and '不用再调用工具把它发出去' in UNSENT_NOTE and UNSENT_NOTE.endswith('用 speak。')
    _, nxt, _ = turn(store, key='body-2')
    assert nxt['context']['unsent_from_program'] == '没发出去：「还是写在正文里」'
    _, again, _ = turn(store, key='body-3')
    assert 'unsent_from_program' not in again['context'], 'said once'


def test_words_also_sent_through_speak_are_not_unsent_and_the_turn_ends_when_she_stops_calling_tools(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    lane = FakeLane(store, [FakeTurn([THINK, said('就这样吧')], said=['就这样吧'])])
    event = {'event_id': 'dup-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '然后呢',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-dup-1'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert len(lane.calls) == 1, 'nothing handed back'
    assert not (store.db.scenes.find_one({'_id': 'dm-a'}) or {}).get('unsent'), 'said through speak: not unsent'
    assert [r['text'] for r in outbound(store, ep['_id'])] == ['就这样吧']


def test_words_written_without_speak_come_back_whole_and_a_speak_then_sends_them(store, monkeypatch):
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    words = '我觉得挺好\n\n就是贵了点，' + '真的' * 60
    lane = FakeLane(store, [FakeTurn([THINK], said=[words]), FakeTurn([said('我觉得挺好')])])
    event = {'event_id': 'body-s', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你看呢',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-body-s'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert lane.calls[1]['messages'][-1]['content'] == UNSENT_NOTE % words, 'whole, as written'
    assert ep['state'] == 'COMMITTED' and [r['text'] for r in outbound(store, ep['_id'])] == ['我觉得挺好']
    assert not (store.db.scenes.find_one({'_id': 'dm-a'}) or {}).get('unsent'), 'she spoke: what she left out is hers'


def test_a_turn_that_spoke_ends_in_words_that_are_not_unsent(store, monkeypatch):
    """ADR-076 R10: where only speak speaks, the turn ends with words, which are its ending, not lost speech."""
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    lane = FakeLane(store, [FakeTurn([THINK, said('好呀')], '嗯，说完了')])
    event = {'event_id': 'end-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '一起吗',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-end-1'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert len(lane.calls) == 1 and [r['text'] for r in outbound(store, ep['_id'])] == ['好呀']
    assert not (store.db.scenes.find_one({'_id': 'dm-a'}) or {}).get('unsent')
    assert not store.db.audit_events.find_one({'type': 'turn.unsent_body', 'stream_id': ep['_id']})
    ending = store.db.audit_events.find_one({'type': 'turn.ending_body', 'stream_id': ep['_id']})
    assert ending and ending['payload']['chars'] == len('嗯，说完了'), 'kept as a count for the operator'
    _, nxt, _ = turn(store, key='end-2')
    assert 'unsent_from_program' not in nxt['context']


def test_lines_count_in_every_message_blank_lines_and_code_do_not(store, monkeypatch):
    """Owner 2026-10-14: in online chat a line break is another message, so her limit counts lines."""
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    code = '看这个：' + chr(10) + '```' + chr(10) + 'print(1)' + chr(10) + 'print(2)' + chr(10) + '```'
    two = '第一行' + chr(10) + chr(10) + '第二行'
    _, ep, lane = turn(store, calls=[said(two), said('第三行', '第四行'), said(code), said('第七行')])
    results = [(row[4], row[5]) for row in lane.tool_results if row[2] == 'speak']
    assert results[0][1] and results[0][0]['lines'].startswith('这回合已说 2 行'), 'a blank line is not a line'
    assert results[1][1] and results[1][0]['lines'].startswith('这回合已说 4 行')
    assert results[2][1] and results[2][0]['lines'].startswith('这回合已说 6 行'), 'a code block is one line, its words another'
    assert not results[3][1] and '第 1 条有 1 行（前面已经 6 行）' in results[3][0], 'the hard line, 6'
    assert [r['text'] for r in outbound(store, ep['_id'])] == [two, '第三行', '第四行', code]


def test_where_only_speak_speaks_silence_is_not_calling_it_and_the_guide_says_so_once(store, monkeypatch):
    """Owner 2026-10-19: on a platform stay_silent goes (a turn without speak is silent); at home it stays, where
    what she writes is what is said. The rule is said once, in the guide for the place (ADR-076 R10)."""
    from asuna import role_tools
    from asuna.block_guide import ENDING, WORDS
    from asuna.render import system_for
    store.config['persona_model'] = model(3)
    _, home, _ = turn(store, key='home', calls=[], content='好', channel=False)
    assert 'stay_silent' in role_tools.abilities(store, home)
    home_system = system_for(store, home['system_ref'])
    assert WORDS[False] in home_system and ENDING[False] in home_system
    channel_scene(store, monkeypatch)
    _, ep, lane = turn(store, key='quiet', calls=[])
    assert 'stay_silent' not in role_tools.abilities(store, ep) and 'speak' in role_tools.abilities(store, ep)
    assert ep['state'] == 'COMMITTED' and outbound(store, ep['_id']) == [] and len(lane.calls) == 1
    system = system_for(store, ep['system_ref'])
    assert WORDS[True] in system and ENDING[True] in system and 'stay_silent' not in system.split('# 每回合的资料')[0]


def test_only_a_platform_turn_is_told_how_its_words_leave(store, monkeypatch):
    store.config['persona_model'] = model(3)
    _, local, _ = turn(store, key='local', calls=[], content='好', channel=False)
    assert 'speak_from_program' not in local['context']
    channel_scene(store)
    _, plain, _ = turn(store, key='plain', calls=[], content='好')
    # How words leave is said once, in her turn guide for the place; the notice adds only this turn's number.
    assert set(plain['context']['speak_from_program']) == {'new_lines', 'one_self'}     # ADR-018 §5.7
    channel_scene(store, monkeypatch)
    _, replying, _ = turn(store, key='replying')
    sent = replying['context']['speak_from_program']['sent']
    assert sent.startswith('一回合 speak 的 text') and '平时 3 行以内，硬线 6 行' in sent and '一个代码块算一行' in sent


def test_where_words_are_speech_everything_she_wrote_is_one_message(store):
    channel_scene(store)
    store.config['persona_model'] = model(3)
    lane = FakeLane(store, [FakeTurn([THINK, ('feel', {})], '他教没教我不好说。', said=['那必须的，被夸了我会更来劲。'])])
    event = {'event_id': 'said-1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你最近的回复好快！',
             'channel': {'id': 'replay', 'account_id': 'bot', 'target': TARGET, 'platform_event_id': 'p-said-1'}}
    persist_input(store, event, managed=True)
    ep = Coordinator(store, lane).ingest(event)
    assert [r['text'] for r in outbound(store, ep['_id'])] == ['那必须的，被夸了我会更来劲。\n\n他教没教我不好说。']


def test_the_line_cap_counts_only_lines_that_left_or_may_still_leave(store):
    """Her ask (2026-10-20): a part that failed, was cancelled after a failure, or that she took back while queued
    gives its lines back, also when the platform reports the failure after the call; UNKNOWN may have left."""
    states = ['DELIVERED', 'FAILED', 'CANCELLED_AFTER_FAILURE', role_tools.CANCELLED_BY_HER, 'UNKNOWN', 'QUEUED_EXTERNAL']
    for index, state in enumerate(states):
        store.put('messages', {'_id': 'ep-lines:speak:%d' % index, 'episode_id': 'ep-lines', 'phase': 'SPEAK',
                               'reply_part': True, 'delivery_state': state, 'text': '第%d句\n第二行' % index,
                               **({'sticker': {'kind': 'market'}} if state == 'QUEUED_EXTERNAL' else {})}, stream='ep-lines')
    assert role_tools.spoken(store, {'_id': 'ep-lines'}) == (4, ['第0句 第二行', '第4句 第二行'])


def test_tool_calls_past_the_usual_carry_the_numbers_and_the_hard_line_ends_the_turn(store, monkeypatch):
    """ADR-084 step 7 (owner and her, 2026-10-20): from the 10th call each result gives the numbers; the 24th is refused
    with the warning that the next is the last; the 25th runs and the turn ends after it, so a loop stops."""
    store.config['persona_model'] = model(3)
    channel_scene(store, monkeypatch)
    thoughts = [('think', {'thought': '再想一下 %d' % index}) for index in range(30)]
    _, ep, lane = turn(store, calls=thoughts)
    rows = [(row[4], row[5]) for row in lane.tool_results]
    assert len(rows) == 25, 'nothing runs after the 25th'
    assert 'calls' not in rows[8][0] and rows[9][0]['calls'] == '这回合第 10 次工具调用（提醒线 9，硬线 24，还剩 14 次）'
    assert rows[20][0]['calls'].endswith('还剩 3 次），先想清楚哪一步不做')
    assert not rows[23][1] and '到了硬线（24）' in rows[23][0] and '下一次是最后一次' in rows[23][0]
    assert rows[24][1] and rows[24][0]['ended'].startswith('这回合的工具调用过了硬线（24）')
