"""Deterministic answer checks with honest repair (answers.py), wherever the program needs an answer to go on."""

import pytest

from asuna import answers
from asuna.lanes import LaneResult


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


def test_only_what_cannot_be_right_is_handed_back():
    assert answers.speech_problem(LaneResult(''), thought=True).startswith('这回合没有写要说的话')
    assert answers.speech_problem(LaneResult('好'), thought=False).startswith('这回合还没写心里话')
    assert answers.speech_problem(LaneResult('好', finish_reason='length'), thought=True).startswith('上一段到了长度上限')
    assert '整段重新写一遍' in answers.turn_note('x。')
