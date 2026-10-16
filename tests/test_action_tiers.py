"""ADR-075: her action brain in two tiers, told by what each can do. 高 is offered only when the owner configured its
route; 低 is the default; 高 needs a why; a hard failure on 高 falls to 低 for the rest of the job and never rises;
she is told in capability words, and a clock is a retry clock or none."""
import json
import types
from datetime import datetime, timedelta, timezone

import pytest

from asuna import action_tiers, role_tools
from asuna.lanes import FakeLane, FakeTurn
from asuna.native_worker import BusinessWorker
from test_adr011_turns import THINK, event, run

IMPLEMENTATION = ('本地', 'API', 'api', '额度', '提供方', '模型')


@pytest.fixture
def offered(monkeypatch):
    monkeypatch.setattr(action_tiers, 'CONFIGURED', True)
    monkeypatch.setattr(action_tiers, 'REST', None)


def delegate(store, args, key='e'):
    coordinator, lane = run(store, FakeTurn([THINK, ('delegate', {'title': '查天气', 'brief': '查明天的天气', **args})], '去查了。'))
    ep = coordinator.ingest(event(key))
    [(_, _, _, _, result, ok)] = [r for r in lane.tool_results if r[2] == 'delegate']
    task = store.db.tasks.find_one({'_id': ep['task_ids'][0]}) if ep.get('task_ids') else None
    return coordinator, result, ok, task


def test_without_a_configured_high_tier_nothing_changes(store):
    assert not action_tiers.offered()
    assert 'tier' not in role_tools.tools()['delegate']['parameters']
    _, result, ok, task = delegate(store, {})
    assert ok and 'tier' not in result and 'tier' not in task


def test_with_one_delegate_takes_a_tier_in_capability_words_and_low_is_the_default(store, offered):
    params = role_tools.tools()['delegate']['parameters']
    assert params['tier']['enum'] == ['低', '高'] and '不写就是低' in params['tier']['description']
    assert '80' in params['why']['description']
    shown = json.dumps(params['tier'], ensure_ascii=False) + params['why']['description']
    assert not any(word in shown for word in IMPLEMENTATION)
    _, result, ok, task = delegate(store, {})
    assert ok and task['tier'] == {'chosen': '低', 'ran': '低'} and 'tier' not in result


def test_high_needs_a_why_and_the_refusal_gives_the_two_lines(store, offered):
    _, result, ok, task = delegate(store, {'tier': '高'})
    assert not ok and task is None
    assert '选高要写 why' in result and action_tiers.LINES['低'] in result and action_tiers.LINES['高'] in result
    _, result, ok, task = delegate(store, {'tier': '高', 'why': '要改三个文件，改到一半可能得换路'}, key='e2')
    assert ok and task['tier'] == {'chosen': '高', 'ran': '高', 'why': '要改三个文件，改到一半可能得换路'}
    assert result['tier'] == '交给高档'


def test_a_job_sent_to_high_while_it_rests_runs_low_and_is_told_a_retry_clock_or_none(store, offered, monkeypatch):
    until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    monkeypatch.setattr(action_tiers, 'REST', {'reason': 'down', 'until': until})
    _, result, ok, task = delegate(store, {'tier': '高', 'why': '多步'})
    assert ok and task['tier']['ran'] == '低' and task['tier']['fell']['reason'] == 'down'
    assert result['tier'].startswith('高档这会儿用不了，最早 ') and result['tier'].endswith('再试；这件按低档做')
    monkeypatch.setattr(action_tiers, 'REST', {'reason': 'owner', 'until': None})
    _, result, _, _ = delegate(store, {'tier': '高', 'why': '多步'}, key='e2')
    assert action_tiers.NO_CLOCK in result['tier'] and '最早' not in result['tier']
    assert not any(word in result['tier'] for word in IMPLEMENTATION)
    # a rest past its clock is over
    monkeypatch.setattr(action_tiers, 'REST', {'reason': 'down', 'until': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    _, result, _, task = delegate(store, {'tier': '高', 'why': '多步'}, key='e3')
    assert task['tier']['ran'] == '高'


def test_what_she_reads_of_a_job_names_chosen_and_ran_and_why_they_differ():
    assert action_tiers.words({'chosen': '低', 'ran': '低'}) == '低'
    assert action_tiers.words({'chosen': '高', 'ran': '高', 'why': 'x'}) == '高'
    line = action_tiers.words({'chosen': '高', 'ran': '低', 'fell': {'reason': 'refused', 'mid_run': True}})
    assert line.startswith('选了高，跑的是低：这件高档没接') and '做到一半' in line and '会慢一些' in line
    assert action_tiers.words({'chosen': '高', 'ran': '低', 'fell': {'reason': 'busy', 'mid_run': False}}) == '选了高，跑的是低：高档忙'
    for reason in action_tiers.REASONS.values():
        assert not any(word in reason for word in IMPLEMENTATION)


def test_the_worker_records_a_fall_once_and_a_rest_from_the_plugin(store, offered):
    _, _, _, task = delegate(store, {'tier': '高', 'why': '多步'})
    worker = BusinessWorker()
    worker.app = types.SimpleNamespace(store=store, config=store.config)
    assert worker.dispatch('tier.fell', {'task_id': task['_id'], 'reason': 'refused', 'mid_run': True, 'code': 'PI_AI_ERROR'})
    fell = store.db.tasks.find_one({'_id': task['_id']})['tier']
    assert fell['ran'] == '低' and fell['fell']['reason'] == 'refused' and fell['fell']['mid_run'] is True
    worker.dispatch('tier.fell', {'task_id': task['_id'], 'reason': 'down'})           # already fallen: unchanged
    assert store.db.tasks.find_one({'_id': task['_id']})['tier']['fell']['reason'] == 'refused'
    assert store.db.audit_events.count_documents({'type': 'tier.fell'}) == 1
    until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    worker.dispatch('tier.rest', {'reason': 'down', 'until': until, 'code': 'TIMEOUT'})
    assert action_tiers.resting() == {'reason': 'down', 'until': until}
    worker.dispatch('tier.rest', {})
    assert action_tiers.resting() is None and store.db.audit_events.count_documents({'type': 'tier.rest'}) == 2


def test_a_continuation_keeps_a_fallen_job_low_and_a_fresh_context_starts_at_the_chosen_tier(store, offered):
    coordinator, _, _, first = delegate(store, {'tier': '高', 'why': '多步'})
    fell = {**first['tier'], 'ran': '低', 'fell': {'reason': 'refused', 'mid_run': True, 'at': 'x'}}
    recent = datetime.now(timezone.utc).isoformat()
    store.put('tasks', {**first, 'tier': fell, 'state': 'RETURNED', 'feedback_state': 'DELIVERED', 'result': {'text': '好了'},
                        'finished_at': recent}, expected=first['revision'], stream=first['_id'])
    coordinator.character = FakeLane(store, [FakeTurn([THINK, ('task', {'do': 'message', 'task': first['_id'], 'message': '再看看'})], '好。')])
    second = coordinator.ingest(event('e2', text='再看看'))
    continued = store.db.tasks.find_one({'_id': second['task_ids'][0]})
    assert continued['tier']['ran'] == '低' and continued['tier']['chosen'] == '高' and 'fresh_context' not in continued
    # 高's idle minutes decide a fresh context for a job that ran at 高
    store.config['action_high_idle_minutes'] = 5
    store.config['action_idle_minutes'] = 600
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    ran_high = {**first['tier']}
    row = store.db.tasks.find_one({'_id': first['_id']})
    store.put('tasks', {**row, 'tier': ran_high, 'finished_at': old}, expected=row['revision'], stream=row['_id'])
    coordinator.character = FakeLane(store, [FakeTurn([THINK, ('task', {'do': 'message', 'task': first['_id'], 'message': '还有'})], '好。')])
    third = coordinator.ingest(event('e3', text='还有'))
    fresh = store.db.tasks.find_one({'_id': third['task_ids'][0]})
    assert fresh['fresh_context']['limit'] == 5 and fresh['tier']['ran'] == '高'


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


def test_the_owners_thread_view_carries_the_tier_given_and_the_one_that_ran(store, offered):
    _, _, _, task = delegate(store, {'tier': '高', 'why': '多步'})
    emitted = []
    worker = BusinessWorker()
    worker.app = types.SimpleNamespace(store=store, config=store.config)
    worker.parent_session = lambda task: 'role-1'
    worker.emit = emitted.append
    worker.collab(task, {'id': 'status:x', 'kind': 'status', 'state': 'running'})
    assert emitted[-1]['entry']['tier'] == {'chosen': '高', 'ran': '高'}
    worker.dispatch('tier.fell', {'task_id': task['_id'], 'reason': 'down', 'mid_run': True})
    worker.collab(task, {'id': 'status:y', 'kind': 'status', 'state': 'done'})       # the stale task in hand: read fresh
    assert emitted[-1]['entry']['tier'] == {'chosen': '高', 'ran': '低', 'reason': 'down', 'mid_run': True}
    plain = {**task, '_id': 'task-none'}
    store.db.tasks.insert_one({'_id': 'task-none', 'schema_version': 1})
    worker.collab(plain, {'id': 'status:z', 'kind': 'status', 'state': 'done'})
    assert 'tier' not in emitted[-1]['entry']                                        # a job without tiers shows none
    store.db.tasks.delete_one({'_id': 'task-none'})
