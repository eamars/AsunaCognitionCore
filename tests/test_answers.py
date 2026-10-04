"""Deterministic answer checks with honest repair (answers.py), wherever the program needs an answer to go on."""
import json

import pytest

from asuna import answers
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from test_attend import gated_event, setup as group_setup
from test_engineering_m1 import decision, event


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


def test_a_monologue_written_only_as_thinking_is_asked_again_in_her_session(store):
    lane = FakeLane(store, [LaneResult('', reasoning='他问我心情，我挺好的'), LaneResult('他问我心情，我挺好的。'),
                            decision(), LaneResult('挺好的呀。')])
    ep = Coordinator(store, lane).ingest(event())
    assert ep['state'] == 'COMMITTED' and ep['speech'] == '挺好的呀。'
    assert [call['phase'] for call in lane.calls] == ['MONOLOGUE', 'MONOLOGUE', 'DECIDE', 'SPEAK']
    repair = lane.calls[1]['messages'][-1]['content']
    assert repair == ('程序检查：上一条只有思考，没有写出正文。这一步要的是：1–4 句第一人称独白，写在正文里。'
                      '请重新给出，只修这个问题，不改变你的意思。')
    rejected = store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'phase.rejected'})
    assert rejected['payload']['phase'] == 'MONOLOGUE' and rejected['payload']['attempt'] == 0


def test_a_decision_that_is_not_valid_json_is_told_where(store):
    good = json.loads(decision().content)
    lane = FakeLane(store, [LaneResult('想说一句'), LaneResult(json.dumps(good)[:-1]), LaneResult(json.dumps(good)),
                            LaneResult('回来了。')])
    ep = Coordinator(store, lane).ingest(event())
    assert ep['state'] == 'COMMITTED' and ep['decision']['next'] == 'speak'
    repair = lane.calls[2]['messages'][-1]['content']
    assert repair.startswith('程序检查：上一条不是有效的 JSON：') and 'DECIDE' in repair


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
    ep = Coordinator(store, FakeLane(store, [LaneResult('想。'), decision(), LaneResult('嗯。')])).ingest(event('appraise-1'))
    lane = FakeLane(store, [LaneResult('{"kind": "joy"}'), LaneResult('[]')])
    assert Appraiser(store, lane).run(ep['_id']) == []
    assert lane.calls[1]['messages'][-1]['content'].startswith('程序检查：上一条的最外层不是 JSON 数组。')
    assert not store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'affect.appraisal_failed'})


def test_a_mistyped_task_id_is_told_with_the_real_one(store):
    # Regression: a garbled continue_task_id passed DECIDE, the continuation was refused, and she only said
    # she would start another task; the turn ended without one.
    first = Coordinator(store, FakeLane(store, [LaneResult('想。'), decision(), LaneResult('好。')])).ingest(event('first'))
    real = 'task-' + first['_id']
    store.db.tasks.insert_one({'_id': real, 'scene_id': 'dm-a', 'requester_id': 'A', 'policy_epoch': first['policy_epoch'],
                               'scope_key': first['scope_key'], 'state': 'RETURNED', 'intent_revision': 1, 'schema_version': 1})
    garbled = real[:16] + 'f0f0f0f0'
    wrong = json.loads(decision().content) | {'continue_task_id': garbled}
    lane = FakeLane(store, [LaneResult('想继续。'), LaneResult(json.dumps(wrong)), decision(), LaneResult('好。')])
    ep = Coordinator(store, lane).ingest(event('second', text='继续'))
    assert ep['state'] == 'COMMITTED'
    repair = lane.calls[2]['messages'][-1]['content']
    assert repair.startswith('程序检查：continue_task_id「' + garbled + '」不是这个对话里的任务；可能是：' + real)
