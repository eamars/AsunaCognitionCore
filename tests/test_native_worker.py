"""Local adapter invariants. These tests do not create any Mongo database."""
import subprocess
import sys
from types import SimpleNamespace

import pytest
from asuna.native_worker import BusinessWorker, NativeLane
from asuna.state import Denied
from asuna.router import Router


def test_worker_import_does_not_load_sdk_or_old_web():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import asuna.native_worker; "
        "assert 'asuna.dsh_lane' not in sys.modules; "
        "assert 'asuna.ui' not in sys.modules; "
        "assert not any(n.startswith('deepseek_harness') for n in sys.modules)"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_native_lane_does_not_invent_or_rebind_an_episode():
    ep = {'_id': 'ep-current'}
    store = SimpleNamespace(db=SimpleNamespace(
        lane_receipts=SimpleNamespace(find_one=lambda query: None),
        episodes=SimpleNamespace(find_one=lambda query: ep)))
    lane = NativeLane(SimpleNamespace(), {'character': {'model': 'native-host'}}, store, None)
    with pytest.raises(ValueError, match='NATIVE_ROLE_SESSION_REQUIRED'):
        lane.generate('legacy-binding', 'ep-current:MONOLOGUE:0', 'MONOLOGUE', 'text', 'system')
    assert ep == {'_id': 'ep-current'}


def test_bound_session_checks_current_authorization_epoch():
    worker = BusinessWorker('unused')
    record = {'scene_id': 'scene', 'person_id': 'person', 'policy_epoch': 1}
    worker.app = SimpleNamespace(store=SimpleNamespace(
        db=SimpleNamespace(sessions=SimpleNamespace(find_one=lambda query: record)),
        authorize=lambda scene, person: {'policy_epoch': 2}))
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        worker.session('native-session')


@pytest.mark.parametrize('channel', [None, {'id': 'qq'}])
def test_only_private_host_input_preserves_native_binding(channel):
    captured = []
    store = SimpleNamespace(config={}, authorize=lambda *_: {'_id': 'scene', 'scope_key': 'scope', 'kind': 'dm'},
                            audit=lambda *_: None)
    coordinator = SimpleNamespace(ingest=lambda event, **_: captured.append(event) or {'state': 'COMMITTED'})
    event = {'event_id': 'id', 'scene_id': 'scene', 'person_id': 'person', 'text': 'hello',
             'native_session_id': 'native-session', 'native_message_ids': ['native-message']}
    if channel:
        event['channel'] = channel
    Router(store, coordinator).receive(event)
    assert ('native_session_id' in captured[0]) == (channel is None)


class StageWorker:
    """Dispatch double: a 'tool' call waits for its stage result, as CONSULT does."""
    app = None

    def __init__(self, wait=5):
        import threading
        self.pending, self.emitted, self.wait = {}, [], wait
        self.lock = threading.Lock()

    def emit(self, value):
        with self.lock:
            self.emitted.append(value)

    def dispatch(self, method, args):
        from concurrent.futures import Future
        if method == 'tool':
            future = Future()
            self.pending[args['token']] = future
            self.emit({'kind': 'stage', 'token': args['token']})
            return future.result(timeout=self.wait)
        if method == 'result':
            self.pending[args['token']].set_result(args['value'])
            return {'accepted': True}
        return method


def _alternate(dispatcher, worker):
    import time
    dispatcher.handle({'id': 1, 'method': 'tool', 'args': {'token': 'scene-a'}})
    dispatcher.handle({'id': 2, 'method': 'tool', 'args': {'token': 'scene-b'}})
    deadline = time.monotonic() + 2
    while len([e for e in worker.emitted if e.get('kind') == 'stage']) < 2 and time.monotonic() < deadline:
        time.sleep(.01)
    dispatcher.handle({'id': 3, 'method': 'result', 'args': {'token': 'scene-b', 'value': 'B'}})
    dispatcher.handle({'id': 4, 'method': 'status', 'args': {}})
    dispatcher.handle({'id': 5, 'method': 'result', 'args': {'token': 'scene-a', 'value': 'A'}})
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not {1, 2, 4} <= {e.get('id') for e in worker.emitted if 'value' in e}:
        time.sleep(.01)
    return {e['id']: e.get('value', e.get('error')) for e in worker.emitted if 'id' in e}


def test_T7_2_single_dispatch_thread_two_scenes_alternate_without_deadlock(monkeypatch):
    import concurrent.futures
    import threading
    from asuna import native_worker
    waits = []
    original = concurrent.futures.Future.result

    def watched(self, timeout=None):
        waits.append(threading.current_thread().name)
        return original(self, timeout)
    monkeypatch.setattr(concurrent.futures.Future, 'result', watched)
    worker = StageWorker()
    dispatcher = native_worker.Dispatcher(worker, threads=1)
    try:
        replies = _alternate(dispatcher, worker)
    finally:
        dispatcher.close()
    assert replies[1] == 'A' and replies[2] == 'B' and replies[4] == 'status', replies
    assert waits and not any(name.startswith('asuna-dispatch') for name in waits), waits


def test_T7_2_counterexample_replies_queued_behind_their_waiter_deadlock(monkeypatch):
    from asuna import native_worker
    monkeypatch.setattr(native_worker, 'REPLIES', frozenset())
    monkeypatch.setattr(native_worker, 'DETACHED', frozenset())
    worker = StageWorker(wait=.5)
    dispatcher = native_worker.Dispatcher(worker, threads=1)
    try:
        replies = _alternate(dispatcher, worker)
    finally:
        dispatcher.close()
    assert str(replies.get(1, '')).startswith('TimeoutError'), replies     # the old routing starves
