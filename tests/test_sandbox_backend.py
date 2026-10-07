"""Commands run under the Host's own sandbox (owner 2026-10-06): DSH confines writes; which sessions may run commands
at all is decided by the tools a task is given."""
import pytest

from asuna import sandbox_backend
from asuna.coordinator import Coordinator
from asuna.grants import development_granted
from asuna.lanes import FakeLane, FakeTurn
from asuna.sandbox import Sandbox
from conftest import HOST_SANDBOX
from test_adr009_p2 import owner


def test_settings_are_checked():
    for bad in ({'backend': 'wsl-bwrap'}, {'backend': 'auto', 'wsl_distro': 'Ubuntu'}, 'none'):
        with pytest.raises(ValueError, match='INVALID_SANDBOX_SETTING'):
            sandbox_backend.validate(bad)
    sandbox_backend.validate({'backend': 'none'})


def test_the_host_decides_whether_commands_can_run():
    assert sandbox_backend.chosen({'_host_sandbox': {'available': False, 'reason': 'no provider'}}) == \
        {'backend': 'none', 'reason': 'no provider'}
    assert sandbox_backend.chosen({})['backend'] == 'none'
    assert sandbox_backend.chosen({'sandbox': {'backend': 'none'}, '_host_sandbox': {'available': True}})['reason'] \
        == 'turned off in the settings'
    sandbox_backend.attach(lambda argv, root: ['runner', root, '--', *argv])
    assert sandbox_backend.chosen({'_host_sandbox': {'available': True}})['backend'] == 'dsh'
    assert sandbox_backend.confine({'_host_sandbox': {'available': True}}, ['x'], 'C:/r') == ['runner', 'C:/r', '--', 'x']


def test_none_turns_off_what_needs_a_sandbox_and_says_so(store, tmp_path):
    owner(store)
    store.config.update(sandbox={'backend': 'none'}, self_development={'enabled': True})
    assert sandbox_backend.chosen(store.config) == {'backend': 'none', 'reason': 'turned off in the settings'}
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


def test_commands_are_for_the_owners_own_scenes(store):
    owner(store)
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '看看。'})], '好。')] * 2)
    coordinator = Coordinator(store, lane)
    mine = coordinator.ingest({'event_id': 'e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '帮我跑一下'})
    theirs = coordinator.ingest({'event_id': 'e2', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '帮我跑一下'})
    assert ('sandbox_run' in coordinator._grants(mine)[2]) == HOST_SANDBOX
    assert 'sandbox_run' not in coordinator._grants(theirs)[2]
    assert '不能跑代码' in theirs['context']['action_capabilities_from_program']['run_code']


@pytest.mark.skipif(not HOST_SANDBOX, reason='no Host sandbox runner here')
def test_a_command_writes_only_its_task_folder_and_names_it_task():
    import shutil, uuid
    from asuna.config import DATA
    root = DATA / 'work' / ('confine-' + uuid.uuid4().hex)   # the real data folder: the system temp folder holds
    box = Sandbox(root / 't1', config={'_host_sandbox': {'available': True}})   # the runner's own temp
    sibling = root / 't2'
    sibling.mkdir(parents=True)
    code = ("import sys, pathlib; pathlib.Path(sys.argv[1], 'inside.txt').write_text('ok')\n"
            "try:\n open(sys.argv[2], 'w').write('x'); print('escaped')\nexcept PermissionError: print('denied')")
    result = box.run(['python3', '-c', code, '/task', str(sibling / 'out.txt')])
    try:
        assert result['exit_code'] == 0 and result['stdout'].strip() == 'denied', result
        assert (root / 't1' / 'inside.txt').read_text() == 'ok' and not (sibling / 'out.txt').exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_sandbox_without_a_backend_refuses_to_run(tmp_path, monkeypatch):
    from asuna import sandbox as sandbox_module
    monkeypatch.setattr(sandbox_module, 'DATA', tmp_path)
    box = Sandbox(tmp_path / 'work' / 't1', config={'sandbox': {'backend': 'none'}})
    with pytest.raises(PermissionError, match='SANDBOX_UNAVAILABLE: turned off'):
        box.run(['python3', '-c', 'print(1)'])
