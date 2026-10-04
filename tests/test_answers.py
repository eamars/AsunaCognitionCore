"""Deterministic answer checks with honest repair (answers.py), wherever the program needs an answer to go on."""

import pytest

from asuna import answers
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from test_attend import gated_event, setup as group_setup

THINK = ('think', {'thought': '他问我心情，我挺好的。'})


def event(key='e', scene='dm-a', person='A', text='你心情怎么样？'):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text}


def test_thinking_alone_or_a_cut_answer_is_not_an_answer():
    assert answers.problem(LaneResult('', reasoning='想好了要说什么')) == '上一条只有思考，没有写出正文。'
    assert answers.problem(LaneResult('  \n')) == '上一条是空的，没有正文。'
    assert answers.problem(LaneResult('', finish_reason='length', reasoning='想了很久')) == '上一条到了长度上限还没写完：思考用完了长度，没有写出正文。'
    assert answers.problem(LaneResult('写了一半', finish_reason='length')) == '上一条到了长度上限还没写完。'
    assert answers.problem(LaneResult('好', tool_calls=[{'id': 't'}])) == '上一条调用了工具，这一步不能调用工具。'
    assert answers.problem(LaneResult('', tool_calls=[{'id': 't'}]), tools=True) is None
    assert answers.problem(LaneResult('好的', reasoning='想了想')) is None


def test_a_failed_check_goes_back_as_it_is_and_the_point_asks_again():
    replies = iter([LaneResult('', reasoning='想好了'), LaneResult('{"a": 1,}'), LaneResult('{"a": 1}')])
    notes, rejected = [], []

    def generate(attempt, note):
        notes.append(note)
        return next(replies)
    value, shaped = answers.ask(generate, '一个 JSON 对象', answers.json_object,
                                rejected=lambda attempt, issue, value: rejected.append(issue))
    assert shaped == {'a': 1} and notes[0] == ''
    assert notes[1] == '程序检查：上一条只有思考，没有写出正文。这一步要的是：一个 JSON 对象。请重新给出，只修这个问题，不改变你的意思。'
    assert notes[2].startswith('程序检查：上一条不是有效的 JSON：') and '第 1 行' in notes[2]
    assert len(rejected) == 2


def test_after_two_repairs_the_point_fails_with_the_named_problem():
    with pytest.raises(answers.Rejected) as caught:
        answers.ask(lambda attempt, note: LaneResult('', reasoning='还在想'), '要说的话')
    assert caught.value.problem == '上一条只有思考，没有写出正文。'


def test_a_failure_that_is_not_the_models_is_not_repaired():
    calls = []

    def generate(attempt, note):
        calls.append(attempt)
        return LaneResult('', finish_reason='error')
    value, shaped = answers.ask(generate, '要说的话')
    assert calls == [0] and value.finish_reason == 'error' and shaped is None


def test_a_thought_left_only_in_native_thinking_is_asked_again_in_the_same_turn(store):
    # Her monologue is the think tool; a turn that only "thought" in native reasoning is told so in the same turn.
    lane = FakeLane(store, [LaneResult('', reasoning='他问我心情，我挺好的'), FakeTurn([THINK], '挺好的呀。')])
    ep = Coordinator(store, lane).ingest(event())
    assert ep['state'] == 'COMMITTED' and ep['speech'] == '挺好的呀。'
    assert [call['phase'] for call in lane.calls] == ['TURN', 'REPAIR']
    repair = lane.calls[1]['messages'][-1]['content']
    assert repair == ('程序检查：这回合还没写心里话：先调用 think，再把要说的话写出来。'
                      '请在这一回合里改正，只修这个问题，不改变你的意思。')
    rejected = store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'turn.rejected'})
    assert rejected['payload']['attempt'] == 0 and rejected['payload']['problem'].startswith('这回合还没写心里话')
    thought = store.db.memory_units.find_one({'_id': ep['monologue_refs'][0]})
    assert thought['body_markdown'] == THINK[1]['thought']


def test_a_call_with_a_missing_field_is_told_which_and_fixed_in_the_same_turn(store):
    # The old DECIDE JSON check told her where the JSON broke; a tool call's refusal names the field instead.
    lane = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '查天气'}),
                                      ('delegate', {'title': '查天气', 'brief': '查明天本地的天气，告诉我要不要带伞。'})],
                                     '我让行动脑去查了。')])
    ep = Coordinator(store, lane).ingest(event(text='明天要带伞吗'))
    refused, fixed = lane.tool_results[1], lane.tool_results[2]
    assert not refused[5] and refused[4] == 'brief 要写内容。'
    assert fixed[5] and ep['task_ids'] == [fixed[4]['task']]
    assert store.db.tasks.count_documents({'episode_id': ep['_id']}) == 1
    assert ep['state'] == 'WAITING_TASK' and ep['speech'] == '我让行动脑去查了。'


def test_a_gate_answer_in_the_wrong_shape_is_asked_again(store):
    group_setup(store)
    gate = FakeLane(store, [LaneResult('我觉得可以说两句'), LaneResult('不理：他们在聊游戏')])
    coordinator = Coordinator(store, FakeLane(store, []))
    coordinator.attend = gate
    ep = coordinator.ingest(gated_event(20002, '今晚开黑吗'), persona='P1')
    assert ep['attend'] == {'choice': 'quiet', 'reason': '他们在聊游戏'}
    assert gate.calls[1]['messages'][-1]['content'].startswith('程序检查：上一条第一行是「我觉得可以说两句」，没有以「接话」或「不理」开头。')


def test_a_gate_that_never_answers_in_shape_lets_the_message_pass_and_says_why(store):
    group_setup(store)
    coordinator = Coordinator(store, FakeLane(store, []))
    coordinator.attend = FakeLane(store, [LaneResult('', reasoning='嗯……')] * 3)
    ep = coordinator.ingest(gated_event(20003, '有人吗', 'reply_in_active_topic'), persona='P1')
    assert ep['state'] == 'COMMITTED' and ep['attend']['choice'] == 'quiet'
    failed = store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'attend.failed'})
    assert failed['payload']['problem'] == '上一条只有思考，没有写出正文。'


def test_an_appraisal_that_is_not_a_json_array_is_told_so_and_asked_again(store):
    from asuna.affect import Appraiser
    from test_adr009_p3 import setup as affect_setup
    affect_setup(store)
    ep = Coordinator(store, FakeLane(store, [FakeTurn([THINK], '嗯。')])).ingest(event('appraise-1'))
    assert ep['state'] == 'COMMITTED'
    lane = FakeLane(store, [LaneResult('{"kind": "joy"}'), LaneResult('[]')])
    assert Appraiser(store, lane).run(ep['_id']) == []
    assert lane.calls[1]['messages'][-1]['content'].startswith('程序检查：上一条的最外层不是 JSON 数组。')
    assert not store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'affect.appraisal_failed'})


def test_a_mistyped_task_id_is_told_with_the_real_one(store):
    # Regression: a garbled task id was refused, and she only said she would start another task; the turn
    # ended without one. Now the refusal names the real id and she continues it in the same turn.
    first = Coordinator(store, FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气'})],
                                                         '去查了。')])).ingest(event('first'))
    real = first['task_ids'][0]
    task = store.db.tasks.find_one({'_id': real})
    store.put('tasks', {**task, 'state': 'RETURNED', 'feedback_state': 'DELIVERED', 'result': {'text': '明天有雨'}},
              expected=task['revision'], stream=real)
    garbled = real[:16] + 'f0f0f0f0'
    lane = FakeLane(store, [FakeTurn([THINK, ('message_action', {'task': garbled, 'message': '再看看后天'}),
                                      ('message_action', {'task': real, 'message': '再看看后天'})], '好，接着看后天。')])
    ep = Coordinator(store, lane).ingest(event('second', text='那后天呢'))
    refused, fixed = lane.tool_results[1], lane.tool_results[2]
    assert not refused[5]
    assert refused[4].startswith('「' + garbled + '」不是这个对话里的任务；可能是：' + real)
    assert fixed[5] and fixed[4]['continues'] == real
    continued = store.db.tasks.find_one({'_id': ep['task_ids'][0]})
    assert ep['task_ids'] == [fixed[4]['task']] and continued['continues_task_id'] == real
    assert ep['state'] == 'WAITING_TASK'
