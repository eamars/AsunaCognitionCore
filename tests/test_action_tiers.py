"""ADR-075: her action brain in two tiers, told by what each can do. 高 is offered only when the owner configured its
route; 低 is the default; 高 needs a why; a hard failure on 高 falls to 低 for the rest of the job and never rises;
she is told in capability words, and a clock is a retry clock or none."""
import json

import pytest

from asuna import action_tiers, role_tools

IMPLEMENTATION = ('本地', 'API', 'api', '额度', '提供方', '模型')


@pytest.fixture
def offered(monkeypatch):
    monkeypatch.setattr(action_tiers, 'CONFIGURED', True)
    monkeypatch.setattr(action_tiers, 'REST', None)


def test_what_she_reads_of_a_job_names_chosen_and_ran_and_why_they_differ():
    assert action_tiers.words({'chosen': '低', 'ran': '低'}) == '低'
    assert action_tiers.words({'chosen': '高', 'ran': '高', 'why': 'x'}) == '高'
    line = action_tiers.words({'chosen': '高', 'ran': '低', 'fell': {'reason': 'refused', 'mid_run': True}})
    assert line.startswith('选了高，跑的是低：这件高档没接') and '做到一半' in line and '会慢一些' in line
    assert action_tiers.words({'chosen': '高', 'ran': '低', 'fell': {'reason': 'busy', 'mid_run': False}}) == '选了高，跑的是低：高档忙'
    for reason in action_tiers.REASONS.values():
        assert not any(word in reason for word in IMPLEMENTATION)


def test_the_week_counts_tiers_and_puts_each_why_beside_what_happened():
    tasks = [{'state': 'RETURNED', 'tool_steps': 40, 'tier': {'chosen': '高', 'ran': '高', 'why': '改到一半可能换路'}},
             {'state': 'RETURNED', 'tool_steps': 12, 'tier': {'chosen': '高', 'ran': '低', 'why': '多步',
                                                               'fell': {'reason': 'refused', 'mid_run': True}}},
             {'state': 'BLOCKED', 'tool_steps': 3, 'tier': {'chosen': '低', 'ran': '低'}}, {'state': 'RETURNED'}]
    week = action_tiers.weekly(tasks)
    assert week['chosen'] == {'低': 1, '高': 2} and week['ran'] == {'低': 2, '高': 1}
    assert week['fell'] == {'这件高档没接': 1} and week['fell_mid_run'] == 1
    assert week['why_beside'][1] == {'why': '多步', 'ran': '低', 'steps': 12, 'state': 'RETURNED'}
    assert action_tiers.weekly([{'state': 'RETURNED'}]) is None


def test_her_tool_budget_grows_by_the_tier_only_when_offered(offered):
    base = len(json.dumps(role_tools.TOOLS['delegate'], ensure_ascii=False))
    tiered = len(json.dumps(role_tools.tools()['delegate'], ensure_ascii=False))
    assert 150 <= tiered - base <= 260, tiered - base                    # ADR-075: about 190 characters


