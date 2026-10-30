"""Host contracts on isolated Mongo; fake model receipts, never real QQ sends."""
import os
from queue import Queue
import threading
from types import SimpleNamespace


from asuna.chat import SceneQueue
from asuna.host import RuntimeHost, _workspace_overlaps
from asuna.records import receipts as receipt_records
from asuna.state import Conflict


def test_workspace_overlap_check_preserves_ancestor_and_sibling_rules(tmp_path):
    root = tmp_path.resolve()
    existing = [root / 'local', root / 'channels' / 'member-0', root / 'channels' / 'member' / 'child']
    ordered = sorted(os.path.normcase(str(path)) for path in existing)
    known = set(ordered)
    for candidate in [root / 'channels' / 'member', root / 'channels' / 'member' / 'child' / 'next',
                      root / 'local' / 'nested', root / 'channels']:
        assert _workspace_overlaps(candidate, ordered, known)
    for candidate in [root / 'channels' / 'member-1', root / 'channels' / 'other']:
        assert not _workspace_overlaps(candidate, ordered, known)


def applied(monkeypatch, receipt):
    """Her core publication still APPLIED (a receipt), or none (None), as the receipts' owner answers."""
    monkeypatch.setattr(receipt_records, 'sink_of_kind', lambda store, kind, **where: SimpleNamespace(
        first=lambda **kw: receipt))


def test_restart_waits_for_active_action_but_not_durable_queue(monkeypatch):
    recorded = []
    evidence = SimpleNamespace(record=lambda kind, payload: recorded.append(kind))
    host = RuntimeHost({}, evidence)
    applied(monkeypatch, {'_id': 'publish-receipt'})
    host.app = SimpleNamespace(store=SimpleNamespace())
    queue = Queue()
    queue.put(('queued-task', 1))
    host.controller = SimpleNamespace(active=None, active_task='running-task', calls_in_flight=lambda: 0, pending=Queue(),
                                      task_queue=queue, state_lock=threading.Lock(),
                                      restart_pending=host.restart_pending)
    host._maybe_restart_after_publish()
    assert host.restart_pending.is_set() and not host.restart_requested.is_set()
    assert recorded == ['restart.pending', 'restart.blocked']
    host.controller.active_task = None
    host._maybe_restart_after_publish()
    assert host.restart_requested.is_set() and host.shutdown_requested.is_set()
    assert not queue.empty() and recorded[-1] == 'restart.requested'


def test_a_restarted_native_worker_does_not_restart_again_for_the_publication_it_is_loading(monkeypatch):
    """Regression: a worker restarted for a publication saw that publication still APPLIED during its own
    startup (the Host reports what it loaded only after initialization), asked for another restart, stopped
    taking work, and the Host, still restarting, never honored it: every later input waited forever."""
    recorded = []
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: recorded.append(kind)), awaits_activation=True)
    applied(monkeypatch, {'_id': 'publish-receipt'})
    host.app = SimpleNamespace(store=SimpleNamespace())
    host.controller = SimpleNamespace(active=None, active_task=None, calls_in_flight=lambda: 0, pending=Queue(),
                                      task_queue=Queue(), state_lock=threading.Lock(),
                                      restart_pending=host.restart_pending)
    host._maybe_restart_after_publish()
    assert not host.restart_pending.is_set() and not host.shutdown_requested.is_set() and recorded == []
    host.activation_settled.set()          # publication.activated: what is APPLIED now is a new publication
    host._maybe_restart_after_publish()
    assert host.restart_requested.is_set() and recorded == ['restart.pending', 'restart.requested']

def test_a_publication_restart_waits_for_a_call_its_closed_task_left_in_flight(monkeypatch):
    """Regression (10-30 23:37): her task's stage was cut at its limit while its publish call was in flight; the
    restart was asked 233 ms after the task closed, cut the call, and no worker recorded the publication it made."""
    recorded = []
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: recorded.append((kind, payload))))
    applied(monkeypatch, {'_id': 'publish-receipt'})
    host.app, host.schedule, flight = SimpleNamespace(store=SimpleNamespace()), None, [1]
    host.controller = SimpleNamespace(active=None, active_task=None, calls_in_flight=lambda: flight[0],
                                      pending=Queue(), task_queue=Queue(), state_lock=threading.Lock(),
                                      restart_pending=host.restart_pending)
    host._after_turn()                     # the cut task's turn has ended; its call has not
    assert host.restart_pending.is_set() and not host.restart_requested.is_set()
    assert recorded[-1][0] == 'restart.blocked' and recorded[-1][1]['calls_in_flight'] == 1
    watch = threading.Thread(target=host._watch_published_restart, daemon=True)
    watch.start()
    try:
        flight[0] = 0                      # the call ends, and no turn ends with it
        assert host.shutdown_requested.wait(5), 'the pending restart is asked once the last call ends'
    finally:
        host._restart_watch_stop.set()
        watch.join(5)
    assert host.restart_requested.is_set() and recorded[-1][0] == 'restart.requested'


def test_after_every_turn_the_host_also_checks_her_heartbeat(monkeypatch):
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None))
    applied(monkeypatch, None)
    host.app = SimpleNamespace(store=SimpleNamespace())
    watched = []
    host.schedule = SimpleNamespace(watch_rhythm=lambda: watched.append('checked'))
    host._after_turn()
    assert watched == ['checked']


def test_scene_queue_is_ordered_and_does_not_starve_other_scene():
    queue = SceneQueue()
    for scene, sequence in [('A', 1), ('A', 2), ('A', 3), ('B', 1)]:
        queue.put(({'scene_id': scene}, sequence))
    received = []
    while not queue.empty():
        value, sequence = queue.get_nowait()
        received.append((value['scene_id'], sequence))
        queue.task_done()
    assert received == [('A', 1), ('A', 2), ('B', 1), ('A', 3)]
    assert queue.unfinished_tasks == 0


