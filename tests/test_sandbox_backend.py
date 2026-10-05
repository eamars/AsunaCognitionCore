"""ADR-010 D5: one sandbox backend per worker; without one, everything that needs it is off and said to be."""
import pytest

from asuna import sandbox_backend
from asuna.coordinator import Coordinator
from asuna.grants import development_granted
from asuna.lanes import FakeLane, FakeTurn
from asuna.sandbox import Sandbox
from test_adr009_p2 import owner


def test_settings_are_checked():
    for bad in ({'backend': 'docker'}, {'backend': 'auto', 'other': 1}, {'wsl_distro': 'Ubuntu; rm'}, 'none'):
        with pytest.raises(ValueError, match='INVALID_SANDBOX_SETTING'):
            sandbox_backend.validate(bad)
    sandbox_backend.validate({'backend': 'none', 'wsl_distro': 'Ubuntu-24.04'})


def test_none_turns_off_what_needs_a_sandbox_and_says_so(store, tmp_path):
    owner(store)
    store.config.update(sandbox={'backend': 'none'}, self_development={'enabled': True})
    store.config.pop('_sandbox', None)
    assert sandbox_backend.chosen(store.config) == {'backend': 'none', 'reason': 'turned off in the settings', 'distro': None}
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    assert development_granted(store, scene, {'person_id': 'A', 'episode_kind': 'external'}) is False
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '看看。'})], '好。')])
    coordinator = Coordinator(store, lane)
    ep = coordinator.ingest({'event_id': 'e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '帮我跑一下这段代码'})
    capabilities = ep['context']['action_capabilities_from_program']
    assert '没有可用的隔离环境' in capabilities['not_available'] and 'development' not in capabilities
    _, _, names = coordinator._grants(ep)
    assert 'sandbox_run' not in names
    with pytest.raises(PermissionError, match='SANDBOX_UNAVAILABLE'):
        sandbox_backend.require(store.config)


def test_a_sandbox_without_a_backend_refuses_to_run(tmp_path, monkeypatch):
    from asuna import sandbox as sandbox_module
    monkeypatch.setattr(sandbox_module, 'DATA', tmp_path)
    box = Sandbox(tmp_path / 'work' / 't1', config={'sandbox': {'backend': 'none'}})
    with pytest.raises(PermissionError, match='SANDBOX_UNAVAILABLE: turned off'):
        box.run(['python3', '-c', 'print(1)'])
