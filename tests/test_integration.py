"""Real namespace/lifecycle contracts; fake model only for task authorization."""
import json
import time
import uuid

import pytest

from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.integration import IntegrationRunner, owner_profile
from asuna.lanes import FakeLane, LaneResult
from asuna.router import Router
from asuna.ingress import persist_input
from asuna.state import Denied
from asuna.tasks import TaskService, ToolBroker


def profile(scene='local', person='owner'):
    return {'chat': {'scene_id': scene, 'person_id': person},
            'integration': {'enabled': True, 'scene_id': scene, 'person_id': person, 'endpoints': []}}


@pytest.fixture
def runner():
    value = IntegrationRunner(profile(), root=ROOT/'.runtime/integration'/('test-'+uuid.uuid4().hex))
    yield value
    if value.lease: value.call('integration_stop', {})
    value.close()


def logs(value):
    return ''.join(item['text'] for item in value['logs'])


def test_real_namespace_stderr_timeout_and_readonly_snapshot(runner):
    runner.call('integration_dev', {'argv': ['python3', '-c', "from pathlib import Path; Path('version.txt').write_text('original')"]})
    code = "from pathlib import Path; import json,os; print(Path('/app/version.txt').read_text()); print(os.getuid()); Path('/app/version.txt').write_text('changed')"
    value = runner.call('integration_test', {'argv': ['python3', '-c', code]})
    assert value['exit_code'] != 0 and 'Read-only file system' in logs(value) and 'Traceback' in logs(value)
    assert (runner.dev/'version.txt').read_text() == 'original'
    value = runner.call('integration_test', {'argv': ['python3', '-c', 'import time; time.sleep(20)'], 'timeout': 1})
    assert value['timed_out'] and value['state'] == 'STOPPED'


def test_enable_restores_frozen_version_and_close_stops_children(runner):
    script = "from pathlib import Path\nimport time\nprint('version-one',flush=True)\nwhile True:\n Path('/data/heartbeat').write_text(str(time.time()))\n time.sleep(.05)\n"
    (runner.dev/'service.py').write_text(script)
    value = runner.call('integration_start', {'argv': ['python3', 'service.py']})
    assert value['state'] == 'RUNNING' and 'version-one' in logs(value)
    (runner.dev/'service.py').write_text("print('half-written-new-version')")
    with pytest.raises(Denied, match='ALREADY_RUNNING'):
        runner.call('integration_start', {'argv': ['python3', 'service.py']})
    runner.close()
    heartbeat = runner.root/'service-data/heartbeat'
    stopped = heartbeat.read_text(); time.sleep(.15)
    assert heartbeat.read_text() == stopped
    restored = IntegrationRunner(profile(), root=runner.root)
    try:
        restored.restore()
        assert restored.status()['state'] == 'RUNNING'
        assert 'version-one' in logs(restored.status()) and 'half-written' not in logs(restored.status())
        restored.call('integration_stop', {})
        restored.close()
        third = IntegrationRunner(profile(), root=runner.root)
        third.restore()
        assert third.active is None
        third.close()
    finally:
        restored.close()


def test_changed_network_profile_does_not_autorestore(runner):
    runner.call('integration_start', {'argv': ['python3', '-c', 'import time; time.sleep(20)']})
    runner.close()
    changed = profile(); changed['integration']['adapter_config'] = {'token': 'new-authority'}
    other = IntegrationRunner(changed, root=runner.root)
    other.restore()
    assert other.active is None and 'PROFILE_CHANGED' in other.status()['error']
    other.close()


def test_second_host_cannot_own_same_integration(runner):
    with pytest.raises(TimeoutError, match='QUEUE_TIMEOUT'):
        IntegrationRunner(profile(), root=runner.root)


def test_only_explicit_owner_event_grants_tools(store):
    work = ROOT/'.runtime/work'/('integration-auth-'+uuid.uuid4().hex); work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(work)},
                        integration=profile('dm-a', 'A')['integration'])
    decision = {'next': 'delegate', 'goal': 'check runner', 'constraints': [], 'recall_query': '', 'speak_before_action': False}
    lane = FakeLane(store, [LaneResult('inspect'), LaneResult(json.dumps(decision))]*2)
    coordinator = Coordinator(store, lane)
    router = Router(store, coordinator)
    ordinary = router.receive({'event_id': 'ordinary', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'integration_profile=owner'})
    event = {'event_id': 'explicit', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'check runner', 'integration_profile': 'owner'}
    persist_input(store, event, managed=True)
    granted = router.receive(event)
    service = TaskService(store); broker = ToolBroker(service)
    try:
        task = service.claim(ordinary['task_id']); broker.bind('ordinary', task, work)
        with pytest.raises(Denied, match='CAPABILITY_DENIED'):
            broker.call('ordinary', 'deny', 'integration_status', {})
        task = service.claim(granted['task_id']); broker.bind('granted', task, work)
        assert 'integration_start' in task['allowed_capabilities'] and task['integration_profile'] == 'owner'
        store.config['integration']['enabled'] = False
        with pytest.raises(Denied, match='OWNER_REQUIRED'):
            broker.call('granted', 'revoked', 'integration_status', {})
        with pytest.raises(Denied, match='OWNER_REQUIRED'):
            owner_profile(profile(), 'qq-scene', 'stranger')
    finally:
        broker.close()


def test_revision_cannot_inherit_previous_integration_grant(store):
    work = ROOT/'.runtime/work'/('integration-revision-'+uuid.uuid4().hex); work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={'scene_id':'dm-a','person_id':'A','workspace':str(work)},
                        integration=profile('dm-a','A')['integration'])
    decision={'next':'delegate','goal':'check','constraints':[],'recall_query':'','speak_before_action':False}
    lane=FakeLane(store,[LaneResult('plan'),LaneResult(json.dumps(decision))]*2)
    service=TaskService(store); router=Router(store,Coordinator(store,lane),task_service=service)
    initial=router.receive({'event_id':'initial','scene_id':'dm-a','person_id':'A','text':'check integration','integration_profile':'owner'})
    revised=router.receive({'event_id':'revision','scene_id':'dm-a','person_id':'A','text':'ordinary check','supersedes_task_id':initial['task_id']})
    task=store.db.tasks.find_one({'_id':revised['task_id']})
    assert task['intent_revision']==2 and task['integration_profile'] is None
    assert not any(t.startswith('integration_') for t in task['allowed_capabilities'])
