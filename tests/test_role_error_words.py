"""Refusals the character brain reads carry the real values and the fix (tool error convention)."""
import pytest

from asuna import affect, render, schedule, schedule_rules
from asuna.documents import missing_section
from asuna.persona_model import writable_keys
from asuna.policy import PolicyStore
from asuna.state import Denied


def test_a_plan_intent_over_the_limit_says_its_length_and_the_limit():
    assert schedule.intent_problem('x' * 1132) == 'intent 1132 字，要求 800 字以内，超了 332 字；精简到 800 字以内，删哪段你自己定'
    assert 'intent 要写' in schedule.intent_problem('  ')


def test_a_timing_says_what_was_given():
    with pytest.raises(ValueError, match='INVALID_SCHEDULE_SPEC: 给了 at、clock'):
        schedule_rules.normalize_rule({'at': '2030-01-01T08:00', 'clock': {'time': '08:00'}})
    with pytest.raises(ValueError, match='every_seconds 给的是 30；要 60…'):
        schedule_rules.normalize_rule({'every_seconds': 30})
    with pytest.raises(ValueError, match='time「25:00」超出'):
        schedule_rules.normalize_rule({'clock': {'time': '25:00'}})


class _NoStore:
    """A store the checks never read: validating a write reads no head."""


def test_an_undeclared_policy_key_lists_the_writable_ones_and_a_bad_value_its_range():
    policy = PolicyStore(_NoStore(), 'P1', {'policy_keys': {}})
    with pytest.raises(Denied) as exc:
        policy.validate([{'key': 'heartbeat.nope', 'value': 1, 'what': 'x'}])
    assert 'heartbeat.visits_per_beat' in str(exc.value) and 'heartbeat.enabled' not in str(exc.value)
    assert 'heartbeat.enabled' not in writable_keys({})
    with pytest.raises(ValueError, match='POLICY_VALUE_RANGE: heartbeat.visits_per_beat 给的是 5，要的是整数，1–3'):
        policy.validate([{'key': 'heartbeat.visits_per_beat', 'value': 5, 'what': 'x'}])


def test_an_over_budget_write_names_the_pair_its_gap_the_way_out_and_only_that_pair_s_sections(store):
    # Her finding (2026-10-21): a home rule over the budget pointed her at a group rule, which is not in the home render.
    from asuna import carried, visibility

    def section(sid, body, **extra):
        return {'sid': sid, 'heading': sid, 'body': body, 'visibility': 'public', 'inject': 'always', **extra}
    docs = {'persona': {'sections': [section('big', '字' * 300), section('small', '字' * 10),
                                     section('group_rule', '字' * 250, tags=['place:group'])]},
            'voice': {'sections': [section('tone', '字' * 100)]}, 'self': None, 'core': None}
    said = carried.over_words(store, 'P1', ('home', visibility.OWNER_PRIVATE), 420, 430, 410, docs)
    assert said.startswith('家里 现在超 10 token，这次改动会让它更长。要腾地方：let_go 一节，或者把它写短。')
    assert said.index('「big」') < said.index('「tone」') and 'group_rule' not in said
    group = carried.over_words(store, 'P1', ('group', visibility.PUBLIC), 400, 420, 410, docs)
    assert group.startswith('外面的群 这次改动会让它超 10 token。') and '「group_rule」' in group


def test_a_missing_section_lists_the_sids_there_are():
    assert missing_section('voice', 'x', [{'sid': 'a'}, {'sid': 'b'}]) == '「voice」里没有 section「x」；有的是：a、b，照抄一个'


def test_a_feeling_without_intensity_is_a_refusal_naming_the_words():
    with pytest.raises(affect.AffectError, match='没写 intensity；intensity 只能是 轻微、明显、强烈'):
        affect.from_words({}, {'kind': '', 'direction': '好'})
