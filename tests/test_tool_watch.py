"""Every tool call of both brains is timed where the worker dispatches it (tool_watch.py): one `tool.time` row when it
ends, done, failed or raised; and a call past its limit is recorded once, with its thread's stack, a lane fault and a
Host log line. On the unit run's store."""
import threading
from concurrent.futures import Future
from queue import Queue
from types import SimpleNamespace

import pytest

from asuna import audit, tool_watch
from asuna.native_worker import BusinessWorker, NativeLane
from asuna.role_tools import Refused
from asuna.state import Denied
from asuna.tasks import ToolFailed
from test_data_child import Recorded

TASK = {'_id': 'task-w', 'scene_id': 's', 'scope_key': 'scene:s'}
EPISODE = {'_id': 'ep-w', 'scope_key': 'scene:s'}


def times(store, stream):
    rows = sorted(audit.events(store, 'tool.time', stream=stream).rows(), key=lambda row: row['seq'])
    for row in rows:
        assert row['scope_key'] == 'scene:s' and isinstance(row['payload']['duration_s'], float)
    return [(row['payload']['call_id'], row['payload']['tool'], row['payload']['outcome']) for row in rows]


def worker_on(store, monkeypatch, call):
    from asuna import local_time
    monkeypatch.setattr(local_time, 'zone_of', lambda *a: None)
    worker = BusinessWorker()
    worker.calls.attach(store, Recorded(), lambda stage, error: None)
    worker.session = lambda _: {'lane': 'executor'}
    worker.app = SimpleNamespace(service=SimpleNamespace(valid=lambda task: task), store=store,
                                 broker=SimpleNamespace(bind=lambda *a: None, call=call))
    future = Future()
    future.asuna_lane, future.asuna_session_id, future.asuna_task = 'executor', 'source', TASK
    future.asuna_binding, future.asuna_broker_session = {'cwd': '.'}, 'broker'
    worker.pending['stage'] = future
    return worker


def test_every_action_call_leaves_one_time_row_done_failed_or_raised(store, monkeypatch):
    def call(session, call_id, tool, args):
        if call_id == 'c-failed':
            raise ToolFailed('TASK_OPERATION_FAILED: 没有 a.txt')
        if call_id == 'c-raised':
            raise KeyError('scene_id')
        return {'files': []}
    worker = worker_on(store, monkeypatch, call)
    try:
        args = {'session_id': 'source', 'operation': 'stage', 'tool': 'list_files', 'args': {}}
        assert worker.dispatch('tool', {**args, 'call_id': 'c-done'}) == {'files': []}
        with pytest.raises(ToolFailed):
            worker.dispatch('tool', {**args, 'call_id': 'c-failed'})
        with pytest.raises(KeyError):
            worker.dispatch('tool', {**args, 'call_id': 'c-raised'})
        assert times(store, 'task-w') == [('c-done', 'list_files', 'done'), ('c-failed', 'list_files', 'failed'),
                                          ('c-raised', 'list_files', 'raised')]
        assert worker.calls.flight == {}
    finally:
        worker.calls.close()


def test_every_role_call_leaves_one_time_row_done_failed_or_raised(store):
    worker = BusinessWorker()
    worker.calls.attach(store, Recorded(), lambda stage, error: None)
    future = Future()
    future.asuna_calls = Queue()

    def handler(call_id, tool, args, **extra):
        if tool == 'refused':
            raise Refused('NOT_NOW: 这会儿不行')
        if tool == 'broken':
            raise RuntimeError('boom')
        if tool == 'last':
            future.set_result({'ended': True})
        return {'ok': True}, False
    future.asuna_handler = handler
    replies = [Future() for _ in range(4)]
    for call_id, tool, reply in zip(('r1', 'r2', 'r3', 'r4'), ('speak', 'refused', 'broken', 'last'), replies):
        future.asuna_calls.put(({'call_id': call_id, 'tool': tool, 'args': {}}, reply))
    try:
        assert NativeLane.wait(SimpleNamespace(worker=worker), future, 10, EPISODE) == {'ended': True}
        assert replies[0].result() == ({'ok': True}, False)
        assert isinstance(replies[1].exception(), Refused) and isinstance(replies[2].exception(), RuntimeError)
        assert times(store, 'ep-w') == [('r1', 'speak', 'done'), ('r2', 'refused', 'failed'),
                                        ('r3', 'broken', 'raised'), ('r4', 'last', 'done')]
    finally:
        worker.calls.close()


def test_a_call_past_its_limit_is_recorded_once_with_its_stack_a_fault_and_a_log_line(store, capsys):
    evidence, faults = Recorded(), []
    calls = tool_watch.Calls().attach(store, evidence, lambda stage, error: faults.append((stage, error)))
    release, inside = threading.Event(), threading.Semaphore(0)

    def held_in_the_body():
        inside.release()
        release.wait(10)

    def run(call_id, tool, args):
        with calls.timed('action', call_id, tool, args, TASK):
            held_in_the_body()
    threads = [threading.Thread(target=run, args=('slow', 'read_file', {})),
               threading.Thread(target=run, args=('cmd', 'sandbox_run', {'timeout': 30}))]
    try:
        for thread in threads:
            thread.start()
        assert inside.acquire(timeout=5) and inside.acquire(timeout=5), 'both calls are in their bodies'
        began = min(entry['started'] for entry in calls.flight.values())
        assert calls.look(began + 149) == [], 'within both limits'
        assert [entry['call_id'] for entry in calls.look(began + 151)] == ['cmd'], 'its own timeout plus 120 s'
        assert [entry['call_id'] for entry in calls.look(began + 601)] == ['slow']
        assert calls.look(began + 9999) == [], 'one record per call, never repeated'
        overruns = [payload for kind, payload in evidence.records if kind == 'host.tool_overrun']
        assert [(row['call_id'], row['tool'], row['brain'], row['stream'], row['limit_s']) for row in overruns] == [
            ('cmd', 'sandbox_run', 'action', 'task-w', 150), ('slow', 'read_file', 'action', 'task-w', 600)]
        assert all(any('held_in_the_body' in line for line in row['stack']) for row in overruns)
        assert faults == [('sandbox_run', 'overrun'), ('read_file', 'overrun')]
        assert capsys.readouterr().err.count('ASUNA_TOOL_OVERRUN') == 2
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
        calls.close()
    assert sorted(times(store, 'task-w')) == [('cmd', 'sandbox_run', 'done'), ('slow', 'read_file', 'done')]


def test_a_time_row_that_cannot_be_written_never_changes_the_call(store):
    evidence = Recorded()
    calls = tool_watch.Calls().attach(store, evidence, lambda stage, error: None)
    store.fail_audit = True
    try:
        with pytest.raises(Denied):
            with calls.timed('action', 'c', 'read_file', {}, TASK):
                raise Denied('STALE_TASK_FENCE')
        with calls.timed('action', 'd', 'read_file', {}, TASK):
            pass
    finally:
        store.fail_audit = False
        calls.close()
    assert [payload['call_id'] for kind, payload in evidence.records if kind == 'host.tool_time_failed'] == ['c', 'd']
