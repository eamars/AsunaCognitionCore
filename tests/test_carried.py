"""ADR-096: what she carries is measured as it is carried. One function says what reaches a turn of each (place, class)
pair and every reader uses it; each pair has its own identity budget, gated on every path that changes what is
carried; a write says the room left; a group's notes fold by last surfacing, pins never; what was carried is counted."""

import pytest

from asuna import context_budget, memory_tiers


@pytest.fixture(autouse=True)
def tiers_on(monkeypatch):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)


# ---- a group's notes fold -----------------------------------------------------------
def note(sid, chars, **extra):
    return {'sid': sid, 'heading': sid, 'body': '字' * chars, 'inject': 'always', **extra}


def test_over_the_limit_what_surfaced_longest_ago_folds_first_and_a_pin_never_folds():
    sections = [note('anchor', 900, pin=True), note('a', 900), note('b', 900), note('c', 900)]
    kept, about = context_budget.note_view(sections, 2400, order=['anchor', 'a', 'c', 'b'])
    assert [s['sid'] for s in kept] == ['anchor', 'b'], 'a then c folded; the pin, longest unused, stays'
    assert [s['sid'] for s in about['not_shown']] == ['a', 'c'] and '2 节' in about['over_limit']
    assert 'pins_over' not in about
    pins = [note('p1', 1500, pin=True), note('p2', 1500, pin=True), note('x', 100)]
    kept, about = context_budget.note_view(pins, 2400, order=['p1', 'p2', 'x'])
    assert [s['sid'] for s in kept] == ['p1', 'p2'] and about['pins_over'].startswith('置顶的节加起来就有 3004 字')
    assert about['fullness'] == '超了', 'pins still count inside the limit'


