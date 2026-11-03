"""ADR-112 §12: an action stage at its limit asks her and is cut only if she does not decide; a start keeps the queue
and hands an interrupted or paused task back to her."""
from concurrent.futures import Future
from queue import Queue
from types import SimpleNamespace

from asuna import time_up
from asuna.host import RuntimeHost
from asuna.native_worker import NativeLane
from asuna.records import tasks as task_records
from asuna.tasks import INTERRUPTED, NOT_STARTED, TaskService

BLOCK = 1800


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def running(store, task_id='task-long', **extra):
    store.config['workflow_timeout_seconds'] = BLOCK      # config.load's default
    store.put('tasks', {'_id': task_id, 'request_key': task_id, 'scope_key': 'scope-home', 'state': 'RUNNING', 'tool_steps': 90,
                        'fencing_token': 1, 'intent_revision': 1, 'scene_id': 'local-dm', 'created_at': '2026-11-03T00:00:00+00:00',
                        **extra})
    return task_records.get(store, task_id)


def audits(store, kind):
    return [row['payload'] for row in store.collection('audit_events').find({'type': kind})]


def staged(store, clock):
    service = TaskService(store)
    asked = []
    stage = time_up.StageClock(service, running(store), BLOCK,
                               lambda task, minutes, key: asked.append((minutes, int(key.rsplit(':', 1)[1]))), clock=clock)
    return service, stage, asked


def test_a_stage_at_its_limit_asks_her_and_more_lets_the_same_run_go_on(store):
    clock = Clock()
    service, stage, asked = staged(store, clock)
    clock.t += BLOCK - 1
    assert not stage.due() and asked == []
    clock.t += 1
    assert not stage.due() and asked == [(30, 1)]                 # asked, not cut: the stage goes on
    assert task_records.get(store, 'task-long')['time_up']['ask'] == 1
    clock.t += time_up.TIME_UP_WINDOW - 1
    assert not stage.due()                                        # still within the window
    words, given = time_up.grant(service, task_records.get(store, 'task-long'), lambda: False)
    assert given and words == time_up.GRANTED % 30
    task = task_records.get(store, 'task-long')
    assert task['time_more'] == 1 and 'time_up' not in task
    assert not stage.due()                                        # the deadline moved one block on
    assert [row['outcome'] for row in audits(store, 'task.time_up_outcome')] == ['more']
    clock.t = 1000.0 + 2 * BLOCK
    assert not stage.due() and asked[-1] == (60, 2)               # asked again at the new deadline


def test_a_window_with_no_more_cuts_the_stage_as_before(store):
    clock = Clock()
    service, stage, asked = staged(store, clock)
    clock.t += BLOCK
    assert not stage.due() and asked
    clock.t += 120                                   # her turn starts two minutes on: the window runs from there
    assert time_up.started(service, 'task-long')['time_up']['turn_at']
    assert not stage.due()
    clock.t += time_up.TIME_UP_WINDOW - 1
    assert not stage.due()
    clock.t += 1
    assert stage.due()
    assert [row['outcome'] for row in audits(store, 'task.time_up_outcome')] == ['cut']
    assert 'time_up' not in task_records.get(store, 'task-long')


def test_a_stage_whose_ask_never_reaches_her_works_on_one_block_and_is_cut_as_not_asked(store):
    clock = Clock()
    _, stage, _ = staged(store, clock)
    clock.t += BLOCK
    stage.due()
    clock.t += time_up.TIME_UP_WINDOW              # her other turns hold her: the stage goes on working
    assert not stage.due()
    clock.t += BLOCK - time_up.TIME_UP_WINDOW
    assert stage.due()
    assert [row['outcome'] for row in audits(store, 'task.time_up_outcome')] == ['not_asked']


def test_each_stage_of_a_task_asks_her_with_its_own_key(store):
    service = TaskService(store)
    keys = []
    task = running(store)
    for _ in range(2):                               # a task's later stage (a fix attempt, a further round)
        clock = Clock()
        stage = time_up.StageClock(service, task, BLOCK, lambda t, m, key: keys.append(key), clock=clock)
        clock.t += BLOCK
        stage.due()
        stage.ended()
    assert len(set(keys)) == 2


def test_a_stage_that_reports_while_she_is_asked_ends_as_always(store):
    clock = Clock()
    _, stage, _ = staged(store, clock)
    clock.t += BLOCK
    stage.due()
    stage.ended()
    assert [row['outcome'] for row in audits(store, 'task.time_up_outcome')] == ['ended']
    assert 'time_up' not in task_records.get(store, 'task-long')


def test_more_is_refused_while_a_restart_waits_and_outside_an_ask(store):
    service = TaskService(store)
    task = running(store)
    assert time_up.grant(service, task, lambda: False) == (time_up.NOT_NOW, False)
    task = running(store, 'task-asked', time_up={'ask': 1, 'at': 'now'})
    assert time_up.grant(service, task, lambda: True) == (time_up.RESTART_PENDING, False)
    assert not task_records.get(store, 'task-asked').get('time_more')


def test_the_wait_keeps_the_stage_past_its_deadline_while_she_decides_and_returns_its_result(store):
    clock = Clock()
    service, stage, asked = staged(store, clock)
    future = Future()
    future.asuna_calls, future.asuna_handler = Queue(), None
    future.asuna_task = task_records.get(store, 'task-long')
    ticks = []

    def due():
        ticks.append(1)
        if len(ticks) == 1:
            clock.t += BLOCK                     # the deadline passes: she is asked
        elif len(ticks) == 2:
            time_up.grant(service, task_records.get(store, 'task-long'), lambda: False)
        elif len(ticks) == 3:
            future.set_result({'report': 'done'})     # the same run reports
        return type(stage).due(stage)
    stage.due = due
    lane = SimpleNamespace(lane='executor', worker=None, time_up_clock=lambda task, timeout: stage)
    assert NativeLane.wait(lane, future, BLOCK, {'_id': 'ep-x'}) == {'report': 'done'}
    assert asked == [(30, 1)]
    assert [row['outcome'] for row in audits(store, 'task.time_up_outcome')] == ['more']


def recovering(store, scheduled):
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None))
    host.app = SimpleNamespace(store=store, service=TaskService(store))
    host.controller = SimpleNamespace(_schedule=scheduled.append)
    return host


def from_home(store, task_id, state, **extra):
    store.put('messages', {'_id': 'in-' + task_id, 'host_managed': True, 'event': {'episode_kind': 'external'}})
    store.put('tasks', {'_id': task_id, 'request_key': task_id, 'scope_key': 'scope-home', 'state': state, 'fencing_token': 1,
                        'intent_revision': 1, 'scene_id': 'local-dm', 'policy_epoch': 1,
                        'raw_input_refs': ['in-' + task_id], **extra})


def test_a_start_keeps_the_queue_and_hands_a_cut_task_back_to_her(store):
    from_home(store, 'task-queued-later', 'READY', created_at='2026-11-03T02:00:00+00:00')
    from_home(store, 'task-queued-first', 'READY', created_at='2026-11-03T01:00:00+00:00')
    from_home(store, 'task-cut', 'RUNNING', tool_steps=38)
    scheduled = []
    recovering(store, scheduled)._recover_tasks()
    assert scheduled == ['task-queued-first', 'task-queued-later']
    assert task_records.get(store, 'task-queued-first')['state'] == 'READY'
    cut = task_records.get(store, 'task-cut')
    assert (cut['state'], cut['failure_type'], cut['feedback_state']) == ('BLOCKED', 'HostRestart', 'READY')
    assert cut['result']['text'] == INTERRUPTED and cut['fencing_token'] == 2


def test_a_start_hands_each_old_paused_task_back_once_and_runs_none(store):
    from_home(store, 'task-paused-queued', 'PAUSED', pause_reason='host_restart', paused_state='READY')
    from_home(store, 'task-paused-running', 'PAUSED', pause_reason='host_restart', paused_state='RUNNING')
    scheduled = []
    recovering(store, scheduled)._recover_tasks()
    assert scheduled == []
    queued, ran = task_records.get(store, 'task-paused-queued'), task_records.get(store, 'task-paused-running')
    assert (queued['state'], queued['result']['text']) == ('BLOCKED', NOT_STARTED)
    assert (ran['state'], ran['result']['text']) == ('BLOCKED', INTERRUPTED)
    assert not any(key.startswith('pause') for key in (*queued, *ran))
    before = (queued['revision'], ran['revision'])
    recovering(store, scheduled)._recover_tasks()
    assert (task_records.get(store, 'task-paused-queued')['revision'],
            task_records.get(store, 'task-paused-running')['revision']) == before


def test_the_turn_at_a_limit_offers_only_its_choices_and_acts_on_that_task_alone(store):
    from asuna import role_tools
    ep = {'_id': 'ep-time', 'episode_kind': 'task_time', 'task_id': 'task-long', 'scene_id': 'local-dm',
          'person_id': 'owner', 'context': {}}
    rules = role_tools._turn_rules(store, ep)
    assert {'task.more', 'task.message', 'task.stop'} <= set(rules) and 'speak' not in rules and 'delegate' not in rules
    tools = SimpleNamespace(_asked_about=role_tools.RoleTools._asked_about)
    assert role_tools.RoleTools._asked_about(tools, ep, {'_id': 'task-long'}) == {'_id': 'task-long'}
    try:
        role_tools.RoleTools._asked_about(tools, ep, {'_id': 'task-other'})
        raise AssertionError('another task was let through')
    except role_tools.Refused as refused:
        assert 'task-long' in str(refused)


def test_her_words_in_that_turn_steer_the_running_task_and_never_continue_a_finished_one(store):
    from asuna import role_tools
    from asuna.coordinator import Coordinator, TIME_UP_BACK
    coordinator = Coordinator(store, None)
    sent = []
    coordinator.on_action_message = lambda task, message: sent.append(message['text'])
    ep = {'_id': 'ep-time', 'episode_kind': 'task_time', 'task_id': 'task-long', 'scene_id': 'local-dm',
          'person_id': 'owner'}
    task = running(store, integration_profile='owner', development_grant=True)
    outcome = coordinator.message_action(ep, 'call-1', task, '收尾，交报告')
    assert outcome['state'] == '行动脑下一步就会看到这句话' and sent == ['收尾，交报告']
    store.put('tasks', {**task_records.get(store, 'task-long'), 'state': 'RETURNED'},
              expected=task_records.get(store, 'task-long')['revision'])
    try:
        coordinator.message_action(ep, 'call-2', task_records.get(store, 'task-long'), '再做一趟')
        raise AssertionError('a finished task was continued from the turn at its limit')
    except role_tools.Refused as refused:
        assert str(refused) == TIME_UP_BACK


def test_what_she_is_told_at_the_limit_is_words(store):
    task = running(store, time_more=1)
    store.put('tasks', {'_id': 'task-behind', 'request_key': 'task-behind', 'state': 'READY', 'scene_id': 'local-dm',
                        'scope_key': 'scope-home'})
    said = time_up.facts(store, task, minutes=30, block=BLOCK, activity={'ended': 7, 'since_last': 6, 'running': 0})
    assert said['ran'] == '这一段已经跑了约 30 分钟（每段上限 30 分钟）' and said['steps'] == '这件事一共用了 90 步工具'
    assert said['lately'] == '最近 5 分钟用了 7 次工具，最后一次在 6 秒前'
    assert said['queue'].startswith('后面还有 1 件在排（来自') and said['more_so_far'] == '你已经给它加过 1 次时'
    assert time_up.lately({'ended': 0, 'since_last': None, 'running': 0}) == '最近 5 分钟没有用工具（这一段还没用过）'


def test_more_reaches_her_in_the_turn_at_a_limit(store):
    """Review (11-03): exposed() keeps only what the conversation lists; more missing from the list was never offered."""
    from asuna import role_tools
    ep = {'_id': 'ep-time', 'episode_kind': 'task_time', 'task_id': 'task-long', 'scene_id': 'local-dm',
          'person_id': 'owner', 'context': {}}
    offered = set(role_tools._turn_rules(store, ep)) - set(role_tools.EVERYWHERE)
    assert offered == {'task.more', 'task.message', 'task.stop'} and offered <= set(role_tools.WITH_ACTION)


def test_an_old_paused_task_whose_work_had_finished_keeps_its_own_result(store):
    """Review (11-03): such a row once went back by the start's unpause loop; marked interrupted, its report was lost."""
    from_home(store, 'task-paused-done', 'PAUSED', pause_reason='host_restart', paused_state='RETURNED',
              paused_feedback_state='WAITING', result={'status': 'done', 'text': '做完了'})
    recovering(store, [])._recover_tasks()
    done = task_records.get(store, 'task-paused-done')
    assert (done['state'], done['feedback_state'], done['result']['text']) == ('RETURNED', 'READY', '做完了')


def test_a_clock_that_fails_cuts_the_stage_through_the_fence(store):
    """Review (11-03): an error inside the clock left wait as something other than the limit, so no fence was sent."""
    future = Future()
    future.asuna_calls, future.asuna_handler = Queue(), None
    future.asuna_task = running(store)
    broken = SimpleNamespace(due=lambda: (_ for _ in ()).throw(RuntimeError('store down')), ended=lambda: None)
    lane = SimpleNamespace(lane='executor', worker=None, time_up_clock=lambda task, timeout: broken)
    try:
        NativeLane.wait(lane, future, BLOCK, {'_id': 'ep-x'})
        raise AssertionError('the stage was not cut')
    except TimeoutError as cut:
        assert str(cut) == 'NATIVE_STAGE_TIMEOUT'


def test_she_settles_a_returned_task_herself_and_her_list_says_her_judgment(store):
    """ADR-112 §12.10: a task handed back interrupted whose work she had delivered another way."""
    from asuna import handover
    from asuna.tasks import SETTLED_WORDS, SETTLE_NOT_YET, SETTLE_RUNNING, SETTLE_WELL
    service = TaskService(store)
    from_home(store, 'task-back', 'BLOCKED', feedback_state='DELIVERED', failure_type='HostRestart',
              result={'status': 'blocked', 'text': INTERRUPTED})
    from_home(store, 'task-lost', 'BLOCKED', feedback_state='UNDELIVERABLE')
    from_home(store, 'task-never-handed', 'BLOCKED')               # no hand-back record at all (feedback_state None)
    from_home(store, 'task-waiting', 'BLOCKED', feedback_state='READY')
    from_home(store, 'task-done', 'RETURNED', feedback_state='DELIVERED')
    from_home(store, 'task-busy', 'RUNNING')
    assert service.settle('task-busy', 'done', 'ep-1') == SETTLE_RUNNING
    assert service.settle('task-done', 'done', 'ep-1') == SETTLE_WELL
    assert service.settle('task-waiting', 'dropped', 'ep-1') == SETTLE_NOT_YET
    assert service.settle('task-never-handed', 'done', 'ep-1') == SETTLE_NOT_YET
    assert service.settle('task-back', 'done', 'ep-1') == SETTLED_WORDS['done'] % '宿主重启打断'
    back = task_records.get(store, 'task-back')
    assert back['state'] == 'BLOCKED' and back['settled']['as'] == 'done'           # nothing re-runs, its state stays
    assert handover.status_words(back) == '你判定已经办完（原：宿主重启打断）'
    assert service.settle('task-back', 'dropped', 'ep-2') == SETTLED_WORDS['dropped'] % '宿主重启打断'   # the later stands
    assert task_records.get(store, 'task-back')['settled']['as'] == 'dropped'
    assert len(audits(store, 'task.settled')) == 2                                    # each one is history
    service.settle('task-lost', 'done', 'ep-3')                 # a result that never reached her can be settled too
    assert handover.status_words(task_records.get(store, 'task-lost')) == '你判定已经办完（原：没做成；结果没送到你手上）'
    assert handover.status_words(back, 'task-later') == '后来接着做了一趟，以 task-later 那条为准'
    assert 'settled' not in task_records.get(store, 'task-waiting')


def test_settle_is_offered_where_message_is_and_never_in_a_turn_about_a_running_task(store):
    from asuna import role_tools
    assert 'task.settle' in role_tools.WITH_ACTION and 'settle' in role_tools.OPS['task']
    ep = {'_id': 'ep-time', 'episode_kind': 'task_time', 'task_id': 'task-long', 'scene_id': 'local-dm',
          'person_id': 'owner', 'context': {}}
    assert 'task.settle' not in role_tools._turn_rules(store, ep)
