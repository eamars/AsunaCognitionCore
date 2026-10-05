"""Real namespace/lifecycle contracts; fake model only for task authorization."""
import shutil
import uuid

import pytest

from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.integration import IntegrationRunner, owner_profile
from asuna.lanes import FakeLane, FakeTurn
from asuna.router import Router
from asuna.ingress import persist_input
from asuna.state import Denied
from asuna.tasks import TaskService, ToolBroker


THINK = ('think', {'thought': '交给行动脑去看看适配器。'})


def delegates(title):
    """Her turn that hands one piece of work to the action brain."""
    return FakeTurn([THINK, ('delegate', {'title': title, 'brief': title + '：看看适配器运行器的情况。'})], '我让行动脑去看。')


def profile(scene='local', person='owner'):
    return {'chat': {'scene_id': scene, 'person_id': person},
            'integration': {'enabled': True, 'scene_id': scene, 'person_id': person, 'endpoints': []}}


@pytest.fixture
def runner():
    root = ROOT/'.runtime/integration'/('test-'+uuid.uuid4().hex)
    value = IntegrationRunner(profile(), root=root)
    yield value
    if value.lease: value.call('integration_stop', {})
    value.close()
    shutil.rmtree(root, ignore_errors=True)


def logs(value):
    return ''.join(item['text'] for item in value['logs'])


def test_real_namespace_stderr_timeout_and_readonly_snapshot(runner):
    (runner.dev/'version.txt').write_text('original')     # the development candidate's adapter (development_write)
    code = "from pathlib import Path; import json,os; print(Path('/app/version.txt').read_text()); print(os.getuid()); Path('/app/version.txt').write_text('changed')"
    value = runner.call('integration_test', {'argv': ['python3', '-c', code]})
    assert value['exit_code'] != 0 and 'Read-only file system' in logs(value) and 'Traceback' in logs(value)
    assert (runner.dev/'version.txt').read_text() == 'original'
    value = runner.call('integration_test', {'argv': ['python3', '-c', 'import time; time.sleep(20)'], 'timeout': 1})
    assert value['timed_out'] and value['state'] == 'STOPPED'


def test_the_run_has_a_user_entry_and_a_home(runner):
    """ssh, git and similar clients refuse to run for a uid without a passwd entry."""
    code = "import os, pwd; print(pwd.getpwuid(os.getuid()).pw_name, os.environ['HOME'], os.access('/tmp', os.W_OK))"
    value = runner.call('integration_test', {'argv': ['python3', '-c', code]})
    assert value['exit_code'] == 0 and 'integration /tmp True' in logs(value)
    assert list((runner.root/'snapshots').iterdir()) == []          # its copy of the adapter went with it


def test_start_runs_only_the_published_adapter(runner, tmp_path):
    # ADR-011 §5.2: unpublished edits never run as the managed service; there is no editing tool here.
    with pytest.raises(Denied, match='INTEGRATION_RELEASE_UNAVAILABLE'):
        runner.call('integration_start', {'argv': ['python3', '-c', 'print(1)']})
    with pytest.raises(ValueError, match='UNKNOWN_INTEGRATION_TOOL'):
        runner.call('integration_dev', {'argv': ['true']})
    release = tmp_path/'release'; release.mkdir(); (release/'version.txt').write_text('published')
    (runner.dev/'version.txt').write_text('unpublished')
    runner.config['_native_integration_release'] = str(release)
    value = runner.call('integration_start', {'argv': ['python3', '-c', "print(open('/app/version.txt').read()); import time; time.sleep(20)"]})
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


def test_second_host_cannot_own_same_integration(runner):
    with pytest.raises(TimeoutError, match='QUEUE_TIMEOUT'):
        IntegrationRunner(profile(), root=runner.root)


def test_only_explicit_owner_event_grants_tools(store):
    work = ROOT/'.runtime/work'/('integration-auth-'+uuid.uuid4().hex); work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(work)},
                        integration=profile('dm-a', 'A')['integration'])
    lane = FakeLane(store, [delegates('check runner')]*2)
    coordinator = Coordinator(store, lane)
    router = Router(store, coordinator)
    ordinary = router.receive({'event_id': 'ordinary', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'integration_profile=owner'})
    event = {'event_id': 'explicit', 'scene_id': 'dm-a', 'person_id': 'A', 'text': 'check runner', 'integration_profile': 'owner'}
    persist_input(store, event, managed=True)
    granted = router.receive(event)
    service = TaskService(store); broker = ToolBroker(service)
    try:
        task = service.claim(ordinary['task_ids'][0]); broker.bind('ordinary', task, work)
        assert 'import_integration_artifact' not in task['allowed_capabilities'], task['allowed_capabilities']
        with pytest.raises(Denied, match='CAPABILITY_DENIED'):
            broker.call('ordinary', 'deny', 'integration_status', {})
        with pytest.raises(Denied, match='CAPABILITY_DENIED'):
            broker.call('ordinary', 'deny-import', 'import_integration_artifact',
                        {'endpoint':'napcat','artifact_path':'/a','target_relative_path':'a.txt'})
        task = service.claim(granted['task_ids'][0]); broker.bind('granted', task, work)
        assert 'integration_start' in task['allowed_capabilities'] and task['integration_profile'] == 'owner'
        assert 'import_integration_artifact' in task['allowed_capabilities'], task['allowed_capabilities']
        store.config['integration']['enabled'] = False
        with pytest.raises(Denied, match='OWNER_REQUIRED'):
            broker.call('granted', 'revoked', 'integration_status', {})
        with pytest.raises(Denied, match='OWNER_REQUIRED'):
            owner_profile(profile(), 'qq-scene', 'stranger')
    finally:
        broker.close()


def test_continuation_cannot_inherit_previous_integration_grant(store):
    from fixture_grant import returned
    work = ROOT/'.runtime/work'/('integration-revision-'+uuid.uuid4().hex); work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={'scene_id':'dm-a','person_id':'A','workspace':str(work)},
                        integration=profile('dm-a','A')['integration'])
    coordinator=Coordinator(store,FakeLane(store,[delegates('check')]))
    service=TaskService(store); router=Router(store,coordinator,task_service=service)
    initial=router.receive({'event_id':'initial','scene_id':'dm-a','person_id':'A','text':'check integration','integration_profile':'owner'})
    first=store.db.tasks.find_one({'_id':initial['task_ids'][0]})
    assert first['integration_profile']=='owner'
    returned(store,first,'runner checked',[])
    # An ordinary turn cannot continue the owner-granted work; she is told so and hands over new work instead.
    coordinator.character=lane=FakeLane(store,[FakeTurn([THINK,('message_action',{'task':first['_id'],'message':'ordinary check'}),
        ('delegate',{'title':'check','brief':'ordinary check'})],'我另交了一件。')])
    revised=router.receive({'event_id':'revision','scene_id':'dm-a','person_id':'A','text':'ordinary check'})
    _,_,tool,_,refusal,ok=lane.tool_results[1]
    assert tool=='message_action' and not ok and '授权和原来那件事不一样' in refusal
    assert not store.db.tasks.find_one({'continues_task_id':first['_id']})
    task=store.db.tasks.find_one({'_id':revised['task_ids'][0]})
    assert task['integration_profile'] is None
    assert not any(t.startswith('integration_') or t=='import_integration_artifact'
                   for t in task['allowed_capabilities']), task['allowed_capabilities']
    # The same grant again continues it, still owner-granted.
    coordinator.character=lane=FakeLane(store,[FakeTurn([THINK,('message_action',{'task':first['_id'],'message':'check again'})],'接着看。')])
    again=router.receive({'event_id':'owner-again','scene_id':'dm-a','person_id':'A','text':'check again','integration_profile':'owner'})
    continued=store.db.tasks.find_one({'_id':again['task_ids'][0]})
    assert lane.tool_results[1][5] and continued['continues_task_id']==first['_id']
    assert continued['integration_profile']=='owner' and 'integration_start' in continued['allowed_capabilities']


def test_import_artifact_is_written_into_the_bound_task_workspace(store):
    """导入工具只跟 owner 授权走，并且只能写这次绑定的工作区（宿主侧真 DB 复测）。"""
    work = ROOT/'.runtime/work'/('integration-import-'+uuid.uuid4().hex); work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={'scene_id':'dm-a','person_id':'A','workspace':str(work)},
                        integration=profile('dm-a','A')['integration'])
    lane=FakeLane(store,[delegates('take the report')]*2)
    service=TaskService(store); router=Router(store,Coordinator(store,lane),task_service=service)
    granted=router.receive({'event_id':'import-owner','scene_id':'dm-a','person_id':'A','text':'take the report',
                            'integration_profile':'owner'})
    ordinary=router.receive({'event_id':'import-ordinary','scene_id':'dm-a','person_id':'A','text':'take the report'})
    granted_task,ordinary_task=granted['task_ids'][0],ordinary['task_ids'][0]
    assert 'import_integration_artifact' in store.db.tasks.find_one({'_id':granted_task})['allowed_capabilities']
    assert 'import_integration_artifact' not in store.db.tasks.find_one({'_id':ordinary_task})['allowed_capabilities']
    seen={}
    class Runner:
        def import_artifact(self, args, *, workspace, protected, register=None):
            seen['args']=args; seen['workspace']=workspace; seen['protected']=[str(p) for p in protected]
            seen['register']=register
            # 宿主传进来的登记回调：非图片字节什么都不登记、什么都不报，结果与改动前逐字一致
            seen['registered']=register(b'not an image', {'endpoint':args['endpoint'],
                                                          'artifact_path':args['artifact_path']}) if register else 'none'
            return {'imported':True,'target_relative_path':args['target_relative_path'],'bytes':3}
    service.crash=lambda point:None
    broker=ToolBroker(service); broker.integration=Runner()
    args={'endpoint':'napcat','artifact_path':'/reports/latest','target_relative_path':'imports/report.txt'}
    try:
        task=service.claim(ordinary_task); broker.bind('ordinary', task, work)
        with pytest.raises(Denied, match='CAPABILITY_DENIED'):
            broker.call('ordinary','no-import','import_integration_artifact',args)
        task=service.claim(granted_task); broker.bind('granted', task, work)
        result=broker.call('granted','import-1','import_integration_artifact',args)
        assert result['imported'] is True and result['evidence_ref'], result
        assert seen['args']==args and str(seen['workspace'])==str(work.resolve()), seen
        assert callable(seen.get('register')), '宿主没把图片登记回调传给导入工具'
        assert seen['registered'] is None, seen['registered']   # 不是图：不写 artifact，也不报未登记
        # 字节由宿主写，路径由这次绑定的工作区决定；换 call_id 才是一次新的取用。
        assert broker.call('granted','import-2','import_integration_artifact',
                           {**args,'target_relative_path':'imports/second.txt'})['imported'] is True
        store.config['integration']['enabled']=False
        with pytest.raises(Denied, match='OWNER_REQUIRED'):
            broker.call('granted','import-3','import_integration_artifact',args)
    finally:
        broker.close()
