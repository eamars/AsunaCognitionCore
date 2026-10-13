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
    assert sandbox_backend.chosen(store.config) == {'backend': 'none', 'reason': 'turned off in the settings', 'reason_code': 'off'}
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
    with pytest.raises(PermissionError, match='SANDBOX_UNAVAILABLE: .*turned off'):
        box.run(['python3', '-c', 'print(1)'])


def test_a_refused_command_says_which_limit_and_what_to_do():
    from asuna.sandbox import command_problem, launch_problem
    assert command_problem(['python3', '-c', 'print(1)']) is None
    assert 'argv 有 41 项，上限 40 项' in command_problem(['python3'] + ['x'] * 40)
    assert 'argv 一共 16001 字，上限 16000 字' in command_problem(['python3', '-c', 'x' * 15992])
    assert 'argv 第 2 项是 int' in command_problem(['python3', 7])
    said = launch_problem(['pwd'], 127, 'windows-acl-run: CreateProcessAsUserW failed (Win32 2): command: pwd')
    assert "没有叫 'pwd' 的程序" in said and '不经过 shell' in said and 'python3' in said


def test_her_commits_carry_her_own_name_and_nothing_waits_for_a_prompt():
    from asuna import sandbox_backend
    assert sandbox_backend.git_identity({}) == {} and sandbox_backend.git_identity({'character_git': {'name': 'A'}}) == {}
    who = sandbox_backend.git_identity({'character_git': {'name': 'Character', 'email': 'character@example.invalid'}})
    assert who == {'GIT_AUTHOR_NAME': 'Character', 'GIT_AUTHOR_EMAIL': 'character@example.invalid',
                   'GIT_COMMITTER_NAME': 'Character', 'GIT_COMMITTER_EMAIL': 'character@example.invalid'}
    env = sandbox_backend.environment(who)
    assert env['GIT_TERMINAL_PROMPT'] == '0' and env['GIT_AUTHOR_NAME'] == 'Character'


def test_a_command_may_ask_for_longer_and_a_stopped_one_keeps_what_it_printed(tmp_path, monkeypatch):
    # A full test run takes minutes: a call may ask for up to 600 s; one stopped by its time hands back its output
    # so far instead of nothing (owner 2026-10-13).
    from asuna import sandbox as sandbox_module
    from asuna.sandbox import RUN_SECONDS, run_seconds
    monkeypatch.setattr(sandbox_module, 'DATA', tmp_path)
    assert run_seconds(None) == RUN_SECONDS and run_seconds(240) == 240
    for bad in (0, 601, '60', True, 1.5):
        with pytest.raises(ValueError, match='INVALID_TIMEOUT'):
            run_seconds(bad)
    sandbox_backend.attach(lambda argv, root: argv)              # this test runs the command itself
    try:
        box = Sandbox(tmp_path / 'work' / 't1', config={'_host_sandbox': {'available': True}})
        script = box.task_dir / 'slow.py'
        script.write_text('import time\nprint("half done", flush=True)\ntime.sleep(30)\n', encoding='utf-8')
        result = box.run(['python3', '-u', '/task/slow.py'], 2)
        assert result['timed_out'] and 'half done' in result['stdout'] and '2 秒' in result['stopped']
        quick = box.run(['python3', '-c', 'print(1)'], 2)
        assert not quick['timed_out'] and 'stopped' not in quick and quick['stdout'].strip() == '1'
    finally:
        sandbox_backend.attach(None)


def test_a_command_can_use_temporary_folders_inside_its_own_folder():
    """Her scripts' tempfile.mkdtemp failed in the sandbox: the system temp folder is not writable there, and on Windows
    a 0o700 folder drops the inherited write grant (ADR-065)."""
    import shutil, uuid
    from asuna.config import DATA
    root = DATA / 'work' / ('temp-' + uuid.uuid4().hex)
    box = Sandbox(root / 't1', config={'_host_sandbox': {'available': True}})
    code = ("import sys, os, tempfile, pathlib\n"
            "d = tempfile.mkdtemp()\n"
            "pathlib.Path(d, 'x.txt').write_text('ok')\n"
            "with tempfile.TemporaryDirectory() as t: pathlib.Path(t, 'y').write_text('ok')\n"
            "print(os.path.realpath(d).startswith(os.path.realpath(sys.argv[1])), sorted(os.listdir(d)))")
    result = box.run(['python3', '-c', code, '/task'])
    try:
        assert result['exit_code'] == 0 and result['stdout'].strip() == "True ['x.txt']", result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_git_in_a_command_uses_a_tls_that_works_inside_the_sandbox():
    """Her git over HTTPS failed in the sandbox: Windows gives a restricted token no SSPI credentials, so Git for
    Windows' Schannel says SEC_E_NO_CREDENTIALS; git uses its OpenSSL there (ADR-065). No network: the effective
    setting is what git reads inside the confined command."""
    import shutil, sys, uuid
    from asuna.config import DATA
    if sys.platform != 'win32':
        assert 'GIT_CONFIG_COUNT' not in sandbox_backend.environment()   # other gits may have one TLS backend only
        return
    if not shutil.which('git'):
        pytest.skip('UNCHECKED, not passed: no git on PATH')
    root = DATA / 'work' / ('git-tls-' + uuid.uuid4().hex)
    box = Sandbox(root / 't1', config={'_host_sandbox': {'available': True}})
    result = box.run(['git', 'config', 'http.sslBackend'])
    try:
        assert result['exit_code'] == 0 and result['stdout'].strip() == 'openssl', result
    finally:
        shutil.rmtree(root, ignore_errors=True)

