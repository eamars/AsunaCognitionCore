"""The data child (data_children.py, data_worker.py): the action brain's history search and discussion digest run in a
child process with a deadline, so a job that spins never holds the worker's interpreter lock.

In process (no Host): the job function against the in-memory adapter, refusals and conversion. Through ToolBroker.call
against a scripted child speaking the frames: past the deadline, busy, will not start; each closes FAILED with its
words. One process test: a real data child given a job that spins is killed at its deadline while the parent's socket
round trips stay near their figure alone (an in-process spinning thread, the 10-30 case, is the control)."""
import os
import socket
import statistics
import sys
import textwrap
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from asuna import data_children, data_worker
from asuna.discussion_digest import DIGEST_TOOL_NAME
from asuna.history_query import HISTORY_TOOL_NAME
from asuna.media_children import Child
from asuna.records import artifacts as artifact_records
from asuna.records import messages as message_records
from asuna.records import people as people_records
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from asuna.state import Conflict, Denied

PYTHON = getattr(sys, '_base_executable', None) or sys.executable
BOT, GROUP = '100357', '300941'
SCENE = 'qq:%s:group:%s' % (BOT, GROUP)
PEER, ACCOUNT = 'qq:100853', '100853'
EPOCH = 7


class Recorded:
    def __init__(self):
        self.records = []

    def record(self, kind, payload):
        self.records.append((kind, payload))


@pytest.fixture(autouse=True)
def no_host():
    """Each test starts as no Host does: jobs in this process, unless the test sets a child."""
    data_children.DATA = None
    yield
    if data_children.DATA is not None:
        data_children.DATA.close()
    data_children.DATA = None


def seeded(store):
    """A group, one line of a peer in it, and a task of that group."""
    scene_records.save(store, {'_id': SCENE, 'scene_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE,
                               'policy_epoch': EPOCH, 'sequence': 1})
    message_records.save(store, {
        '_id': 'line-1', 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': EPOCH, 'scene_seq': 1,
        'text': '雾灯坏了，明天去修', 'author': PEER, 'direction': 'inbound', 'delivery_state': 'RECEIVED',
        'occurred_at': '2026-09-22T12:00:00Z', 'received_at': '2026-09-22T12:00:00Z', 'adapter_id': 'fixture',
        'platform_event_id': 'pe-1',
        'event': {'channel': {'id': 'qq', 'sender_id': ACCOUNT, 'target': {'type': 'group', 'id': GROUP}}}})
    return task_records.save(store, {
        '_id': 'task-data', 'request_key': 'task-data', 'state': 'RUNNING', 'scene_id': SCENE,
        'scope_key': 'scene:' + SCENE, 'policy_epoch': EPOCH, 'requester_id': PEER, 'intent_revision': 1,
        'fencing_token': 'fence', 'lease_expires_at': time.time() + 600, 'tool_steps': 0,
        'allowed_capabilities': [HISTORY_TOOL_NAME, DIGEST_TOOL_NAME]}, stream='task-data')


WINDOW = {'since': '2000-01-01', 'until': '2999-12-31T23:59:59Z', 'include_semantic': False}


def test_in_process_the_job_reads_the_history_and_writes_what_the_tool_writes(world):
    task = seeded(world)
    evidence = Recorded()
    result = data_children.run(HISTORY_TOOL_NAME, task, dict(WINDOW), world.config, world.name, evidence)
    assert [hit['message_id'] for hit in result['hits']] == ['line-1'], result
    assert people_records.label(world, SCENE + '|' + PEER), 'the label row the history read writes'
    digest = data_children.run(DIGEST_TOOL_NAME, task, {k: v for k, v in WINDOW.items()}, world.config, world.name,
                               evidence)
    assert digest['degraded'] is False and digest['coverage']['read'] == 1, digest


@pytest.mark.parametrize('kind', [Denied, Conflict, PermissionError, ValueError])
def test_a_refusal_comes_back_with_its_class_and_words(world, monkeypatch, kind):
    task = seeded(world)

    def refuse(self, job):
        raise kind('SOME_REFUSAL: 这是她要读的话')
    monkeypatch.setattr(data_worker.Services, 'run', refuse)
    with pytest.raises(kind) as raised:
        data_children.run(HISTORY_TOOL_NAME, task, {}, world.config, world.name, Recorded())
    assert type(raised.value) is kind and str(raised.value) == 'SOME_REFUSAL: 这是她要读的话'


def test_a_result_that_is_not_json_comes_back_converted_with_its_evidence(world, monkeypatch):
    task = seeded(world)
    when = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    def odd(self, job):
        self.evidence.record('retrieval.selection', {'at': when})
        return {'at': when, 'id': SimpleNamespace(x=1)}
    monkeypatch.setattr(data_worker.Services, 'run', odd)
    evidence = Recorded()
    result = data_children.run(HISTORY_TOOL_NAME, task, {}, world.config, world.name, evidence)
    assert result == {'at': str(when), 'id': str(SimpleNamespace(x=1))}
    assert evidence.records == [('retrieval.selection', {'at': str(when)})], 'recorded by the worker, once'


# ---- the routing in ToolBroker.call, against a scripted child ---------------------------------------------------------
SCRIPT = textwrap.dedent('''
    import os, sys, threading, time
    from asuna.media_children import read_frame, write_frame
    from asuna.media_worker import _watch
    threading.Thread(target=_watch, args=(os.getppid(),), daemon=True).start()
    out, inp = sys.stdout.buffer, sys.stdin.buffer
    if sys.argv[1] == 'fail-start':
        write_frame(out, {'ready': False, 'error': 'ImportError'}); sys.exit(1)
    write_frame(out, {'ready': True, 'pid': os.getpid()})
    while True:
        try:
            read_frame(inp)
        except EOFError:
            sys.exit(0)
        time.sleep(60)
''')


def broker_on(store, tmp_path):
    from asuna.tasks import TaskService, ToolBroker
    task = seeded(store)
    broker = ToolBroker(TaskService(store), Recorded())
    broker.bindings['session'] = (task, SimpleNamespace(task_dir=tmp_path, protected_paths=[]))
    return broker, task


@pytest.mark.parametrize('case', ['timeout', 'busy', 'unavailable'])
def test_a_call_the_child_did_not_finish_closes_failed_with_its_words(world, tmp_path, monkeypatch, case):
    from asuna.tasks import ToolFailed
    script = tmp_path / 'child.py'
    script.write_text(SCRIPT, encoding='utf-8')
    monkeypatch.setattr(data_children, 'DEADLINE', 1)
    faults = []
    child = Child('data', command=[PYTHON, str(script), 'fail-start' if case == 'unavailable' else 'serve'], tries=1,
                  lock_wait=0.5, start_seconds=10, fault=lambda stage, error: faults.append((stage, error)))
    data_children.DATA = child.start()
    if case == 'busy':
        child.lock.acquire()                     # another job holds the child for longer than this one waits
    broker, task = broker_on(world, tmp_path)
    try:
        with pytest.raises(ToolFailed) as failed:
            broker.call('session', 'call-1', HISTORY_TOOL_NAME, dict(WINDOW))
    finally:
        if case == 'busy':
            child.lock.release()
    words = {'timeout': data_children.TIMEOUT, 'busy': data_children.BUSY, 'unavailable': data_children.UNAVAILABLE}
    assert str(failed.value) == words[case]
    receipt = next(row for row in world.collection('artifacts').find() if row.get('task_id') == task['_id'])
    assert receipt['state'] == 'FAILED' and receipt['error'] == words[case]
    assert faults == {'timeout': [('decode', 'deadline')], 'busy': [],
                      'unavailable': [('start', 'start_failed')]}[case]


def test_the_broker_routes_both_tools_and_nothing_else_reaches_the_services(world, tmp_path, monkeypatch):
    """The call goes through data_children.run with the task's binding and the worker's own config and database."""
    seen = []

    def run(tool, task, args, config, database, evidence):
        seen.append((tool, task['_id'], config is world.config, database))
        return {'hits': []}
    monkeypatch.setattr(data_children, 'run', run)
    broker, task = broker_on(world, tmp_path)
    broker.call('session', 'call-h', HISTORY_TOOL_NAME, dict(WINDOW))
    broker.call('session', 'call-d', DIGEST_TOOL_NAME, dict(WINDOW))
    assert seen == [(HISTORY_TOOL_NAME, task['_id'], True, world.name), (DIGEST_TOOL_NAME, task['_id'], True, world.name)]
    assert artifact_records.get(world, next(row['_id'] for row in world.collection('artifacts').find()))['state'] == 'DONE'


# ---- one process test: a real data child spinning, and the parent's round trips ---------------------------------------
SPIN = textwrap.dedent('''
    import os, sys
    from asuna import data_worker

    def run(self, job):
        if job['args'].get('spin'):
            while True:                          # the 10-30 loop: pure Python, never ending
                pass
        return {'served_by': os.getpid()}
    data_worker.Services.run = run
    sys.exit(data_worker.main(sys.argv[1:]))
''')


def round_trips(count):
    """The median seconds of one byte there and back over a local socket pair, echoed by a thread of this process."""
    left, right = socket.socketpair()

    def echo():
        while True:
            data = right.recv(1)
            if not data:
                return
            right.sendall(data)
    echoing = threading.Thread(target=echo, daemon=True)
    echoing.start()
    times = []
    for _ in range(count):
        began = time.perf_counter()
        left.sendall(b'x')
        left.recv(1)
        times.append(time.perf_counter() - began)
    left.close()
    echoing.join(5)
    right.close()
    return statistics.median(times)


def test_a_spinning_job_is_killed_at_its_deadline_and_never_slows_the_worker(world, monkeypatch):
    began = time.monotonic()
    task = seeded(world)
    monkeypatch.setattr(data_children, 'DEADLINE', 4)
    faults = []
    child = Child('data', command=[PYTHON, '-X', 'utf8', '-c', SPIN, str(os.getpid())], tries=1, lock_wait=5,
                  start_seconds=15, fault=lambda stage, error: faults.append((stage, error)))
    data_children.DATA = child.start()
    first = child.proc.pid
    alone = round_trips(200)
    # The control: a thread of this process spinning, as the digest loop did inside the worker.
    stop = threading.Event()

    def spin():
        while not stop.is_set():
            pass
    spinner = threading.Thread(target=spin, daemon=True)
    spinner.start()
    try:
        in_process = round_trips(20)
    finally:
        stop.set()
        spinner.join(5)
    answers = []
    job = threading.Thread(target=lambda: answers.append(data_children.run(
        HISTORY_TOOL_NAME, task, {'spin': True}, world.config, world.name, Recorded())))
    job.start()
    time.sleep(0.5)                                  # the job is in the child, spinning
    in_child = round_trips(200)
    job.join(15)
    after = data_children.run(HISTORY_TOOL_NAME, task, {}, world.config, world.name, Recorded())
    took = time.monotonic() - began
    print('round trip median, alone %.4f ms, child spinning %.4f ms, thread spinning %.4f ms; %.1f s in all'
          % (alone * 1e3, in_child * 1e3, in_process * 1e3, took))
    assert answers == [{'error': data_children.TIMEOUT}] and faults == [('decode', 'deadline')]
    assert after['served_by'] not in (first, None), 'the next job is served by a fresh child'
    assert in_process > 10 * alone, 'the measurement sees a spinning thread of this process (the control)'
    assert in_child < 5 * alone and in_child < in_process / 10, 'a spinning child does not slow this process'
    assert took < 20
