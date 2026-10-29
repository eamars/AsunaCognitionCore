"""Real lifecycle contracts under the Host sandbox (conftest's DSH runner); fake model only for task authorization."""
import shutil
import uuid

import pytest

from asuna.config import DATA, ROOT
from asuna.integration import IntegrationRunner, owner_profile
from asuna.state import Denied
from asuna import channel_kinds

# The two home lines the narrow grant is about. The kind registry is global and these tests decide
# on a scene's kind, so both kinds load here (test_agent_line.py loads `agent` the same way).
channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python',
                    'module': 'agent_line'},
                   {'python': ROOT / 'packages' / 'channels' / 'dsh-peer' / 'python',
                    'module': 'dsh_peer'}])
AGENT_SCENE, AGENT_PERSON = 'agent:home:dm:claude-code', 'agent:claude-code'
PEER_SCENE, PEER_PERSON = 'dsh:home:dm:peer', 'dsh:peer'


def profile(scene='local', person='owner'):
    return {'chat': {'scene_id': scene, 'person_id': person},
            'integration': {'enabled': True, 'scene_id': scene, 'person_id': person, 'endpoints': []},
            '_host_sandbox': {'available': True}}


@pytest.fixture
def runner():
    root = DATA/'integration'/('test-'+uuid.uuid4().hex)
    value = IntegrationRunner(profile(), root=root)
    yield value
    if value.lease: value.call('integration_stop', {})
    value.close()
    shutil.rmtree(root, ignore_errors=True)


def logs(value):
    return ''.join(item['text'] for item in value['logs'])


def test_stderr_timeout_and_a_snapshot_the_run_cannot_change(runner):
    (runner.dev/'version.txt').write_text('original')     # the development candidate's adapter (development_write)
    code = "from pathlib import Path; print(Path('version.txt').read_text()); Path('version.txt').write_text('changed')"
    value = runner.call('integration_test', {'argv': ['python3', '-c', code]})
    assert value['exit_code'] != 0 and 'PermissionError' in logs(value) and 'Traceback' in logs(value)
    assert (runner.dev/'version.txt').read_text() == 'original'
    value = runner.call('integration_test', {'argv': ['python3', '-c', 'import time; time.sleep(20)'], 'timeout': 1})
    assert value['timed_out'] and value['state'] == 'STOPPED'


def test_start_runs_only_the_published_adapter(runner, tmp_path):
    # ADR-011 §5.2: unpublished edits never run as the managed service; there is no editing tool here.
    with pytest.raises(Denied, match='INTEGRATION_RELEASE_UNAVAILABLE'):
        runner.call('integration_start', {'argv': ['python3', '-c', 'print(1)']})
    with pytest.raises(ValueError, match='UNKNOWN_INTEGRATION_TOOL'):
        runner.call('integration_dev', {'argv': ['true']})
    release = tmp_path/'release'; release.mkdir(); (release/'version.txt').write_text('published')
    (runner.dev/'version.txt').write_text('unpublished')
    runner.config['_native_integration_release'] = str(release)
    value = runner.call('integration_start', {'argv': ['python3', '-c', "print(open('version.txt').read()); import time; time.sleep(20)"]})
    assert value['state'] == 'RUNNING'
    import time
    deadline = time.monotonic() + 5
    while 'published' not in logs(runner.status()) and time.monotonic() < deadline:
        time.sleep(.1)
    assert 'unpublished' not in logs(runner.status()) and 'published' in logs(runner.status())
    # A test run's copy of the adapter is removed when it ends; the service's own copy stays.
    runner.call('integration_test', {'argv': ['python3', '-c', 'print(2)']})
    assert [entry.name for entry in (runner.root/'snapshots').iterdir()] == [runner.active_snapshot]


def test_changed_network_profile_does_not_autorestore(runner, tmp_path):
    runner.config['_native_integration_release'] = str(tmp_path)
    runner.call('integration_start', {'argv': ['python3', '-c', 'import time; time.sleep(20)']})
    runner.close()
    changed = profile(); changed['integration']['adapter_config'] = {'token': 'new-authority'}
    other = IntegrationRunner(changed, root=runner.root)
    other.restore()
    assert other.active is None and 'PROFILE_CHANGED' in other.status()['error']
    other.close()


def test_an_enabled_channel_adapter_starts_by_itself_once_and_a_stop_is_kept(tmp_path, monkeypatch):
    from asuna import channel_kinds
    from conftest import QQ_CHANNEL
    channel_kinds.load([QQ_CHANNEL])
    configured = profile(); configured['integration']['adapter_config'] = {'host': {'channel_id': 'qq'}}
    root = DATA/'integration'/('test-'+uuid.uuid4().hex)
    try:
        first = IntegrationRunner(configured, root=root)
        assert first.service_argv() == ['python3', '/app/adapter.py', '--service']       # what the QQ package declares
        monkeypatch.setattr(IntegrationRunner, 'service_argv', lambda self: ['python3', '-c', 'import time; time.sleep(20)'])
        first.restore()                                        # no published adapter yet: says so, starts nothing
        assert first.active is None and 'INTEGRATION_RELEASE_UNAVAILABLE' in first.status()['error']
        first.config['_native_integration_release'] = str(tmp_path)
        first.restore()
        assert first.active.snapshot()['state'] == 'RUNNING'
        first.call('integration_stop', {}); first.close()
        again = IntegrationRunner({**configured, '_native_integration_release': str(tmp_path)}, root=root)
        again.restore()
        assert again.active is None                            # stopped once, it stays stopped
        again.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_second_host_cannot_own_same_integration(runner):
    with pytest.raises(TimeoutError, match='QUEUE_TIMEOUT'):
        IntegrationRunner(profile(), root=runner.root)


def test_the_owners_own_platform_dm_carries_the_workspace_grant():
    """Owner 2026-10-06: LAN devices from the owner's DM too; someone else's DM, or another speaker, never."""
    from asuna.integration import owner_dm
    config = {**profile(), 'canonical_persons': {'qq:1': 'owner'},
              'channels': {'qq': {'routes': {'me': {'scene_id': 'qq:9:dm:1', 'target': {'type': 'dm', 'id': '1'}, 'person_id': 'qq:1'},
                                             'b': {'scene_id': 'qq:9:dm:2', 'target': {'type': 'dm', 'id': '2'}, 'person_id': 'qq:2'},
                                             'g': {'scene_id': 'qq:9:group:5', 'target': {'type': 'group', 'id': '5'}}}}}}
    assert owner_profile(config, 'qq:9:dm:1', 'qq:1')['enabled'] and owner_profile(config, 'local', 'owner')
    assert not owner_dm(config, 'qq:9:dm:2', 'qq:2') and not owner_dm(config, 'qq:9:group:5', 'qq:1')
    for scene, person in (('qq:9:dm:2', 'qq:2'), ('qq:9:dm:1', 'qq:2'), ('qq:9:group:5', 'qq:1')):
        with pytest.raises(Denied, match='INTEGRATION_OWNER_REQUIRED'):
            owner_profile(config, scene, person)


# ── the narrow agent_home grant (ADR-033's agent line; owner 2026-10-11, through Claude) ──────────────
# What the scene earns: the owner's own chat or DM keeps the full grant; a home round woken on an agent
# line gets `agent_home`, which carries integration_start and integration_status and nothing else.


