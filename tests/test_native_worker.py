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
