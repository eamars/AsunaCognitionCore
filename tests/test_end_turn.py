"""ADR-131: end_turn ends her turn and does nothing else. Listed in every conversation and never switched off; it runs
before every check (no thought first, not the call cap, its fields ignored); a turn it ended is not handed back, and
what that turn leaves is still recorded; a consult, whose end is task.answer, refuses it. On the unit run's store
holding the fixture world (conftest.py), with test_adr129_one_rule's local chat and agent line."""
from asuna import block_guide, channel_kinds, faults, role_tools, switches
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.records import episodes as episode_records

from test_adr129_one_rule import LINE, LOCAL, THINK, audits, home, outbound, run  # noqa: F401 (home is a fixture)

END = ('end_turn', {})


def results(lane, name):
    return [(result, ok) for *_, tool, _args, result, ok in lane.tool_results if tool == name]


def test_end_turn_is_listed_everywhere_never_switched_off_and_not_a_deed(home):
    for scene in (LOCAL, LINE, 'qq:10001:group:20002'):
        listed = role_tools.toolbox(home, {'scene_id': scene, 'manifest': {'session_class': 'owner_private'}})
        assert 'end_turn' in listed, (scene, listed)
    assert 'end_turn' in switches.KEEP and 'end_turn' in faults.NOT_DEEDS


def test_her_words_reach_her_as_she_wrote_them(home):
    # Her 0501 (D9): the result is not stay_silent's old line; her turn guide keeps both ends, in every turn's prompt.
    assert role_tools.END_TURN_NOTE == '这一回合结束了。'
    assert '就调用 `end_turn`' in block_guide.ENDING and '也可以什么都不调用' in block_guide.ENDING
    ep, lane = run(home, FakeTurn([END], ''))
    assert block_guide.ENDING in lane.calls[0]['messages'][0]['content']
    assert results(lane, 'end_turn') == [({'note': '这一回合结束了。'}, True)]


def test_it_ends_the_turn_at_once_with_no_thought_first_and_its_fields_ignored(home):
    ep, lane = run(home, FakeTurn([('end_turn', {'reason': '不想说'}),
                                   ('speak', {'parts': [{'kind': 'text', 'text': '不该发出去'}]})], ''))
    assert results(lane, 'end_turn') == [({'note': role_tools.END_TURN_NOTE}, True)]
    assert results(lane, 'speak') == []                       # the turn ended with the step that called it
    assert ep['state'] == 'COMMITTED' and outbound(home, ep) == [] and len(lane.calls) == 1
    assert not audits(home, ep, 'turn.rejected')
    assert episode_records.get(home, ep['_id'])['silent_reason'] == '这回合没有 speak'


def test_after_speak_it_ends_the_turn_and_the_parts_are_out(home):
    ep, lane = run(home, FakeTurn([THINK, ('speak', {'parts': [{'kind': 'text', 'text': '回来啦'}]}), END], ''),
                   scene=LINE)
    assert [row['text'] for row in outbound(home, ep)] == ['回来啦']
    assert ep['state'] == 'COMMITTED' and len(lane.calls) == 1 and not audits(home, ep, 'turn.rejected')


def test_its_turn_is_not_handed_back_for_words_left_unsent_and_her_next_turn_still_says_so(home):
    ep, lane = run(home, FakeTurn([THINK, END], said=['我说一句']), scene=LINE)
    assert ep['state'] == 'COMMITTED' and outbound(home, ep) == []
    assert not audits(home, ep, 'turn.rejected') and len(lane.calls) == 1
    after, _ = run(home, FakeTurn([THINK, END], ''), key='e2', scene=LINE)
    assert episode_records.get(home, after['_id'])['context']['unsent_from_program'] == '没发出去：「我说一句」'


def test_where_qq_asks_for_a_thought_a_turn_it_ended_is_not_handed_back(home, monkeypatch):
    real = channel_kinds.reply_parts
    monkeypatch.setattr(channel_kinds, 'reply_parts', lambda scene: ('text',) if scene == LOCAL else real(scene))
    ep, lane = run(home, FakeTurn([], ''), FakeTurn([THINK], ''))
    assert [row['problem'] for row in audits(home, ep, 'turn.rejected')] == ['no_thought']     # QQ's rule is on
    ep, lane = run(home, FakeTurn([END], ''), key='e2')
    assert ep['state'] == 'COMMITTED' and not audits(home, ep, 'turn.rejected') and len(lane.calls) == 1


def test_the_call_cap_does_not_refuse_it(home):
    thoughts = [('think', {'thought': '第%d个念头。' % n}) for n in range(1, role_tools.CALLS_HARD)]
    ep, lane = run(home, FakeTurn([*thoughts, END], ''))
    assert len(lane.tool_results) == role_tools.CALLS_HARD
    assert results(lane, 'end_turn') == [({'note': role_tools.END_TURN_NOTE}, True)]
    assert ep['state'] == 'COMMITTED' and not audits(home, ep, 'turn.rejected')


def about_a_task(store, ep, kind):
    done = episode_records.get(store, ep['_id'])
    return store.put('episodes', {**{k: v for k, v in done.items() if k not in ('revision', 'tool_calls', 'reply')},
                                  '_id': 'ep-' + kind, 'source_event_id': kind + '-1', 'episode_kind': kind,
                                  'state': 'PREPARED'}, stream='ep-' + kind)


def test_a_consult_and_a_time_up_turn_refuse_it_and_keep_their_own_end(home):
    # A consult's end is task.answer (D2); a time-up turn decides its task with more, message or stop (her 0501).
    ep, _ = run(home, FakeTurn([THINK, END], ''))
    lane = FakeLane(home, [FakeTurn([THINK, END], '')] * 3)
    after = Coordinator(home, lane).advance(about_a_task(home, ep, 'consult')['_id'])
    refused = results(lane, 'end_turn')
    assert refused and all(not ok and result.startswith(role_tools.CONSULT_ONLY) for result, ok in refused)
    recorded = episode_records.get(home, 'ep-consult')['tool_calls'].values()
    assert {call.get('code') for call in recorded if call['tool'] == 'end_turn'} == {'NOT_NOW'}
    assert after['state'] == 'FAILED_PROTOCOL' and 'INVALID_TURN_OUTPUT' in after['failure']
    lane = FakeLane(home, [FakeTurn([THINK, END], '')])
    after = Coordinator(home, lane).advance(about_a_task(home, ep, role_tools.TASK_TIME)['_id'])
    assert results(lane, 'end_turn') == [(role_tools.TIME_UP_ONLY, False)]
    assert after['state'] == 'COMMITTED'
