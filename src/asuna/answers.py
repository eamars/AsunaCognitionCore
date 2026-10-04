"""Deterministic checks on a model's answer wherever the program needs one to continue (owner 2026-10-05).

A role stage, the relevance gate, an appraisal, an action report and a dialogue summary each need a usable
answer before the program can go on. The checks are deterministic: the answer stopped on its own, it has
text (thinking alone is not an answer), and it has the shape that point needs. A failed check goes back to
the model as it is, in the same session, the way DSH returns a failed tool call: what was wrong and what this
point needs. The point then asks again, at most REPAIRS times, and after that fails with the named problem.

Failures that are not the model's (a transport error after DSH's own retries, an interrupted or cancelled
turn) are returned unchanged for the caller's existing handling; there is nothing to tell the model.
"""
from __future__ import annotations

REPAIRS = 2
MODEL_FINISHES = ('stop', 'length')


class Rejected(Exception):
    """The answer still failed its check after REPAIRS repairs."""

    def __init__(self, problem, value):
        super().__init__(problem)
        self.problem, self.value = problem, value


def problem(value, tools=False):
    """What is wrong with one finished answer, in words for the model; None when it can be used.

    `tools`: tool calls count as an answer (the action brain); elsewhere they are not allowed."""
    text = (value.content or '').strip()
    thought = bool((value.reasoning or '').strip())
    if value.finish_reason == 'length':
        return '上一条到了长度上限还没写完' + ('：思考用完了长度，没有写出正文。' if not text else '。')
    if value.tool_calls and not tools:
        return '上一条调用了工具，这一步不能调用工具。'
    if not text and not (tools and value.tool_calls):
        return '上一条只有思考，没有写出正文。' if thought else '上一条是空的，没有正文。'
    return None


def note(issue, need):
    """The program's words back to the model after a failed check."""
    return '程序检查：' + issue + '这一步要的是：' + need + '。请重新给出，只修这个问题，不改变你的意思。'


def ask(generate, need, shape=None, tools=False, rejected=None):
    """Run `generate(attempt, note)` until its answer passes; returns (value, shaped).

    `generate` gets the attempt number (0 first) and the program's note for a repair ('' first).
    `shape(text)` returns what the caller uses from a passing answer, or raises ValueError whose message
    says, in words for the model, what is wrong. `rejected(attempt, issue, value)` is called for each failed
    check (the caller's audit). Raises Rejected after REPAIRS repairs."""
    message = ''
    for attempt in range(REPAIRS + 1):
        value = generate(attempt, message)
        if value.finish_reason not in MODEL_FINISHES:
            return value, None
        issue = problem(value, tools)
        shaped = None
        if issue is None and shape:
            try:
                shaped = shape(value.content.strip())
            except ValueError as exc:
                issue = str(exc)
        if issue is None:
            return value, shaped
        if rejected:
            rejected(attempt, issue, value)
        message = note(issue, need)
    raise Rejected(issue, value)


def json_object(text, what='JSON 对象'):
    """Parse one JSON object, with the parser's own position when it is not one."""
    import json
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError('上一条不是有效的 JSON：%s（第 %d 行第 %d 列）。' % (exc.msg, exc.lineno, exc.colno)) from None
    if not isinstance(value, dict):
        raise ValueError('上一条的最外层不是' + what + '。')
    return value


def json_list(text):
    import json
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError('上一条不是有效的 JSON：%s（第 %d 行第 %d 列）。' % (exc.msg, exc.lineno, exc.colno)) from None
    if not isinstance(value, list):
        raise ValueError('上一条的最外层不是 JSON 数组。')
    return value
