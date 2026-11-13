"""ADR-129: her local Web chat has speak beside body text. A turn there says one thing (speak's parts, else its body),
needs no call to stay silent, and puts no rule on how she speaks; the page reads what a speak call sent only through
that call's own record. On the unit run's store holding the fixture world (conftest.py)."""
import pytest

from asuna import role_tools
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.records import episodes as episode_records
from asuna.records import scenes as scene_records
from asuna.state import Denied

LOCAL, OWNER, PERSONA = 'local-dm', 'local-user', 'P1'
THINK = ('think', {'thought': '他在等我回话。'})


@pytest.fixture
def home(world, tmp_path):
    """The fixture world with her local Web chat."""
    world.config['chat'] = {**world.config['chat'], 'scene_id': LOCAL, 'person_id': OWNER, 'persona': PERSONA,
                            'workspace': str(tmp_path / 'local')}
    scene_records.save(world, {'_id': LOCAL, 'kind': 'dm', 'scope_key': 'scene:' + LOCAL, 'policy_epoch': 1,
                               'sequence': 0, 'members': [OWNER]})
    return world


def run(store, *turns, key='e1', text='在吗', kind='external'):
    lane = FakeLane(store, list(turns))
    ep = Coordinator(store, lane).ingest({'event_id': key, 'scene_id': LOCAL, 'person_id': OWNER, 'text': text,
                                          'episode_kind': kind}, persona=PERSONA)
    return ep, lane


def outbound(store, ep):
    return sorted(store.collection('messages').find({'episode_id': ep['_id'], 'direction': 'outbound'}),
                  key=lambda row: row['scene_seq'])


def audits(store, ep, kind):
    return [row['payload'] for row in store.collection('audit_events').find({'type': kind, 'stream_id': ep['_id']})]


def test_a_home_turn_that_speaks_sends_its_parts_and_keeps_its_body(home):
    ep, _ = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '回来啦'},
                                                             {'kind': 'text', 'text': '今天怎么样'}]})],
                               '（自言自语）'))
    assert ep['state'] == 'COMMITTED'
    assert [row['text'] for row in outbound(home, ep)] == ['回来啦', '今天怎么样']
    assert audits(home, ep, 'turn.ending_body') == [{'chars': len('（自言自语）'), 'parts': 2}]
    assert not audits(home, ep, 'turn.rejected')


def test_a_home_turn_with_no_speak_and_no_words_ends_silent_and_a_consult_is_still_handed_back(home):
    ep, lane = run(home, FakeTurn([THINK], ''))
    assert ep['state'] == 'COMMITTED' and outbound(home, ep) == []
    assert not audits(home, ep, 'turn.rejected') and len(lane.calls) == 1
    # The action brain waits for her answer: a consult turn there with none is handed back, as before.
    done = episode_records.get(home, ep['_id'])
    consult = home.put('episodes', {**{k: v for k, v in done.items() if k not in ('revision', 'tool_calls', 'reply')},
                                    '_id': 'ep-consult', 'source_event_id': 'consult-1', 'episode_kind': 'consult',
                                    'state': 'PREPARED'}, stream='ep-consult')
    lane = FakeLane(home, [FakeTurn([THINK], '')] * 3)
    after = Coordinator(home, lane).advance(consult['_id'])
    assert after['state'] == 'FAILED_PROTOCOL' and 'INVALID_TURN_OUTPUT' in after['failure']
    assert [row['problem'] for row in audits(home, consult, 'turn.rejected')][:1] == [
        '你还没回答行动脑：用 task 的 answer 写下回答；这里写的正文不会发给任何人。']


def test_a_home_turn_cut_at_its_length_limit_is_not_her_silence(home):
    # No speak and no body, cut: handed back as before, and what she writes then is her speech.
    ep, lane = run(home, FakeTurn([THINK], '', finish_reason='length'), FakeTurn([], '刚才没说完，回来啦'))
    assert [row['problem'] for row in audits(home, ep, 'turn.rejected')] == ['上一段到了长度上限还没写完。']
    assert ep['state'] == 'COMMITTED' and [row['text'] for row in outbound(home, ep)] == ['刚才没说完，回来啦']
    # Parts already left: the turn commits whatever its finish.
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '回来啦'}]})], '',
                                  finish_reason='length'), key='e2')
    assert ep['state'] == 'COMMITTED' and not audits(home, ep, 'turn.rejected') and len(lane.calls) == 1
    assert [row['text'] for row in outbound(home, ep)] == ['回来啦']


def test_home_speak_has_no_line_rules_and_still_refuses_a_text_sent_twice(home):
    seven = '\n'.join('第%d行' % n for n in range(1, 8))
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': seven},
                                                               {'kind': 'text', 'text': '看〔12〕那句'}]}),
                                   ('speak', {'parts': [{'kind': 'text', 'text': seven}]})], ''))
    done = [result for *_, result, ok in lane.tool_results if ok]
    refused = [result for *_, result, ok in lane.tool_results if not ok]
    assert [row['text'] for row in outbound(home, ep)] == [seven, '看〔12〕那句']
    assert 'lines' not in done[-1]                               # no line count at home (her line 0433)
    assert len(refused) == 1 and '这回合已经发过一样的' in refused[0]


def test_stay_silent_at_home_is_refused_in_the_worker_and_left_out_of_her_aliases(home):
    ep, lane = run(home, FakeTurn([THINK, ('stay_silent', {'reason': '不想说'})], '那我说一句'))
    assert [ok for *_, name, _args, _result, ok in lane.tool_results if name == 'stay_silent'] == [False]
    assert [row['text'] for row in outbound(home, ep)] == ['那我说一句']       # the turn went on: its body is speech
    assert 'stay_silent' not in role_tools.session_aliases(LOCAL)
    assert role_tools.session_aliases('qq:1:group:2')['stay_silent'] == 'speak'   # where only speak speaks, as before


def test_the_page_reads_only_the_rows_a_call_s_own_record_names(home):
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '一'}]}),
                                   ('speak', {'parts': [{'kind': 'text', 'text': '二'}]})], ''))
    calls = [call_id for operation, call_id, name, *_ in lane.tool_results if name == 'speak']
    operation = lane.tool_results[0][0]
    first = role_tools.sent_parts(home, LOCAL, operation, calls[0])
    assert [part['text'] for part in first['parts']] == ['一']
    assert [part['text'] for part in role_tools.sent_parts(home, LOCAL, operation, calls[1])['parts']] == ['二']
    # Not her call in this conversation, not a speak call, or a call whose record names no rows: nothing.
    assert role_tools.sent_parts(home, 'dm-a', operation, calls[0]) is None
    assert role_tools.sent_parts(home, LOCAL, operation, lane.tool_results[0][1]) is None      # her think
    assert role_tools.sent_parts(home, LOCAL, 'ep-other:TURN', calls[0]) is None
    with pytest.raises(Denied):
        role_tools.sent_picture(home, LOCAL, operation, calls[0], 0)      # a text: no picture to serve
