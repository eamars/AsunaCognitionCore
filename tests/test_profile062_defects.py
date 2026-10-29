"""Defects the ADR-062 prompt profile found in her live notices (2026-10-13): a block that changes every turn with
nothing new in it is sent again every turn, so what it says must change only with its content."""

from asuna.rhythm import recent_phrasing


def test_her_repeated_phrases_read_in_the_same_order_whatever_their_counts():
    a, b, c = '今天天气', '一起去吧', '晚安好梦'           # one 4-gram each
    first = recent_phrasing([a, a, a, a, b, b, b, c, c, c])
    second = recent_phrasing([a, a, a, b, b, b, b, b, c, c, c, c])
    assert first == second == sorted(first)


