"""Real lifecycle contracts under the Host sandbox (conftest's DSH runner); fake model only for task authorization."""
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
from asuna import channel_kinds

# The two home lines the narrow grant is about. The kind registry is global and these tests decide
# on a scene's kind, so both kinds load here (test_agent_line.py loads `agent` the same way).
channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python',
                    'module': 'agent_line'},
                   {'python': ROOT / 'packages' / 'channels' / 'dsh-peer' / 'python',
                    'module': 'dsh_peer'}])
AGENT_SCENE, AGENT_PERSON = 'agent:home:dm:claude-code', 'agent:claude-code'
PEER_SCENE, PEER_PERSON = 'dsh:home:dm:peer', 'dsh:peer'


THINK = ('think', {'thought': '交给行动脑去看看适配器。'})


def delegates(title):
    """Her turn that hands one piece of work to the action brain."""
    return FakeTurn([THINK, ('delegate', {'title': title, 'brief': title + '：看看适配器运行器的情况。'})], '我让行动脑去看。')


def profile(scene='local', person='owner'):
    return {'chat': {'scene_id': scene, 'person_id': person},
            'integration': {'enabled': True, 'scene_id': scene, 'person_id': person, 'endpoints': []},
            '_host_sandbox': {'available': True}}


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
    root = ROOT/'.runtime/integration'/('test-'+uuid.uuid4().hex)
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


def test_only_explicit_owner_event_grants_tools(store, runtime_work):
    work = runtime_work('integration-auth'); work.mkdir(parents=True)
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


def test_continuation_cannot_inherit_previous_integration_grant(store, runtime_work):
    from fixture_grant import returned
    work = runtime_work('integration-revision'); work.mkdir(parents=True)
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


def test_import_artifact_is_written_into_the_bound_task_workspace(store, runtime_work):
    """导入工具只跟 owner 授权走，并且只能写这次绑定的工作区（宿主侧真 DB 复测）。"""
    work = runtime_work('integration-import'); work.mkdir(parents=True)
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


class Runner:
    """The broker's runner stand-in: it records what a granted call reached, and launches nothing."""

    def __init__(self):
        self.calls = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        return {'state': 'STOPPED'}


class Recorder:
    """Records what a due plan hands the controller, so a test can read the event itself."""

    def __init__(self):
        self.events = []

    def receive(self, event):
        self.events.append(event)
        return {'status': 'accepted'}

    def offer_internal(self, *args, **visit):
        pass

    def offer_self_development(self, event_id, **kwargs):
        pass


def agent_world(store, work):
    """An agent line and the old home line as configured channels, each with a workspace. The integration
    profile stays bound to the local chat (dm-a/A) — the narrow grant still has to pass that binding."""
    store.config.update(task_mode='workspace',
                        chat={'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(work)},
                        integration=profile('dm-a', 'A')['integration'])
    store.config['channels']['agent'] = {'account_id': 'home', 'token': 'a' * 32, 'routes': {
        'claude-code': {'person_id': AGENT_PERSON, 'scene_id': AGENT_SCENE, 'sender_id': 'claude-code',
                        'display_name': 'Claude（开发助手）', 'target': {'type': 'dm', 'id': 'claude-code'},
                        'workspace': str(work)}}}
    store.config['channels']['dsh'] = {'account_id': 'home', 'token': 'd' * 32, 'routes': {
        'peer': {'person_id': PEER_PERSON, 'scene_id': PEER_SCENE, 'sender_id': 'peer',
                 'target': {'type': 'dm', 'id': 'peer'}, 'workspace': str(work)}}}
    for scene, person in ((AGENT_SCENE, AGENT_PERSON), (PEER_SCENE, PEER_PERSON)):
        store.put('scenes', {'_id': scene, 'scene_id': scene, 'kind': 'dm', 'members': [person],
                             'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'sequence': 0,
                             'channel_id': scene.split(':')[0], 'channel_account_id': 'home'})


LINE_TARGET = {'agent': {'type': 'dm', 'id': 'claude-code'}, 'dsh': {'type': 'dm', 'id': 'peer'}}


def line_event(event_id, scene, person, kind, text):
    """What a channel's own envelope looks like after Channels.receive built it (the grant is never in it)."""
    return {'event_id': event_id, 'scene_id': scene, 'person_id': person, 'text': text,
            'channel': {'id': kind, 'account_id': 'home', 'target': LINE_TARGET[kind],
                        'platform_event_id': 'p-' + event_id}}


def delegated(store, lane, event, work):
    """One turn on a line that hands work to the action brain: (coordinator, task service, task row)."""
    coordinator = Coordinator(store, lane)
    episode = Router(store, coordinator).receive(event)
    task_id = episode['task_ids'][0]
    return coordinator, TaskService(store), store.db.tasks.find_one({'_id': task_id})


def test_an_agent_line_round_delegates_with_start_and_status_only(store, runtime_work):
    work = runtime_work('integration-agent-home'); work.mkdir(parents=True)
    agent_world(store, work)
    _, _, task = delegated(store, FakeLane(store, [delegates('把适配器拉起来')]),
                           line_event('agent-ask', AGENT_SCENE, AGENT_PERSON, 'agent', '把 QQ 适配器拉起来'), work)
    assert task['integration_profile'] == 'agent_home'
    capabilities = task['allowed_capabilities']
    assert 'integration_start' in capabilities and 'integration_status' in capabilities
    for tool in ('integration_test', 'integration_stop', 'import_integration_artifact'):
        assert tool not in capabilities, capabilities
    # 落盘那条输入带同一个值：同一个 event_id 重投时 ingress 按值比对，两处必须算出同一个
    stored = store.db.messages.find_one({'_id': 'in-' + task['episode_id']})
    assert stored['event']['integration_profile'] == 'agent_home'


def test_a_narrow_grant_task_is_refused_a_tool_its_profile_does_not_carry(store, runtime_work):
    work = runtime_work('integration-agent-test'); work.mkdir(parents=True)
    agent_world(store, work)
    _, service, task = delegated(store, FakeLane(store, [delegates('试跑一下适配器')]),
                                 line_event('agent-test', AGENT_SCENE, AGENT_PERSON, 'agent', '试跑一下适配器'), work)
    assert task['integration_profile'] == 'agent_home'                    # 窄授权确实给了
    assert 'integration_test' not in task['allowed_capabilities']       # 第一道：能力面就没有它
    # 把能力面补回去，钉住第二道：白名单不看能力面，profile 里没有就是不给。
    store.db.tasks.update_one({'_id': task['_id']}, {'$set': {
        'allowed_capabilities': [*task['allowed_capabilities'], 'integration_test']}})
    task = service.claim(task['_id'])
    broker = ToolBroker(service); broker.bind('narrow', task, work); broker.integration = Runner()
    with pytest.raises(Denied, match='INTEGRATION_TASK_GRANT_REQUIRED'):
        broker.call('narrow', 'test-1', 'integration_test', {'argv': ['python3', '-c', 'print(1)']})


def test_the_owner_round_still_delegates_with_the_full_set(store, runtime_work):
    work = runtime_work('integration-owner-full'); work.mkdir(parents=True)
    store.config.update(task_mode='workspace', chat={'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(work)},
                        integration=profile('dm-a', 'A')['integration'])
    _, _, task = delegated(store, FakeLane(store, [delegates('看看适配器')]),
                           {'event_id': 'owner-ask', 'scene_id': 'dm-a', 'person_id': 'A',
                            'text': '看看适配器', 'integration_profile': 'owner'}, work)
    assert task['integration_profile'] == 'owner'
    assert {'integration_test', 'integration_start', 'integration_stop', 'integration_status',
            'import_integration_artifact'} <= set(task['allowed_capabilities'])


def test_a_narrow_task_answered_on_its_own_line_is_not_refused(store, runtime_work):
    from fixture_grant import returned
    work = runtime_work('integration-agent-continue'); work.mkdir(parents=True)
    agent_world(store, work)
    coordinator, service, task = delegated(
        store, FakeLane(store, [delegates('看看适配器')]),
        line_event('agent-continue', AGENT_SCENE, AGENT_PERSON, 'agent', '看看适配器'), work)
    done = returned(store, service.claim(task['_id']), '适配器在跑，日志里没有报错。', [])
    coordinator.character = FakeLane(store, [FakeTurn(
        [THINK, ('message_action', {'task': task['_id'], 'message': '再看一眼状态'})], '我让它再看一眼。')])
    feedback = service.feedback(done, coordinator)
    # 补话开了新任务，那一回合就挂在它上面：关键是没被当成授权不一致拒掉。
    assert feedback['state'] in ('COMMITTED', 'WAITING_TASK'), feedback['state']
    said = store.db.messages.find_one({'event.episode_kind': 'task_feedback', 'scene_id': AGENT_SCENE})
    assert said['event']['integration_profile'] == 'agent_home'         # 反馈回合拿得到同一个值
    actions = [entry for entry in coordinator.character.tool_results if entry[2] == 'message_action']
    assert actions and actions[0][5] is True, actions                     # 544 不再判成授权不一致
    continued = store.db.tasks.find_one({'continues_task_id': task['_id']})
    assert continued and continued['integration_profile'] == 'agent_home', continued


def test_the_old_home_line_is_not_an_agent_line(store, runtime_work):
    work = runtime_work('integration-peer-line'); work.mkdir(parents=True)
    agent_world(store, work)
    assert channel_kinds.home(PEER_SCENE) and channel_kinds.home(AGENT_SCENE)   # home() 分不开这两条线
    _, _, task = delegated(store, FakeLane(store, [delegates('看看适配器')]),
                           line_event('peer-ask', PEER_SCENE, PEER_PERSON, 'dsh', '旧居：帮我看看适配器'), work)
    assert task['integration_profile'] is None
    assert not ({'integration_test', 'integration_start', 'integration_stop', 'integration_status',
                 'import_integration_artifact'} & set(task['allowed_capabilities']))


def test_a_narrow_grant_task_can_read_status_but_cannot_stop(store, runtime_work):
    work = runtime_work('integration-agent-status'); work.mkdir(parents=True)
    agent_world(store, work)
    _, service, task = delegated(store, FakeLane(store, [delegates('看下适配器状态')]),
                                 line_event('agent-status', AGENT_SCENE, AGENT_PERSON, 'agent', '看下适配器状态'), work)
    task = service.claim(task['_id'])
    broker = ToolBroker(service); broker.bind('narrow', task, work); runner = Runner(); broker.integration = runner
    assert broker.call('narrow', 'status-1', 'integration_status', {})['state'] == 'STOPPED'
    assert runner.calls == [('integration_status', {})]
    with pytest.raises(Denied, match='CAPABILITY_DENIED'):
        broker.call('narrow', 'stop-1', 'integration_stop', {})
    assert [call[0] for call in runner.calls] == ['integration_status']


def test_a_plan_made_from_an_agent_line_round_carries_no_grant_yet(store, runtime_work):
    """第一版定死：agent_home 回合挂的计划，到期事件里不带 integration_profile（行为差异，不是漏改）。"""
    import threading
    import types
    from asuna.schedule import ScheduleService
    from test_adr009_p5_rhythm import NativeLane, fire
    work = runtime_work('integration-agent-plan'); work.mkdir(parents=True)
    agent_world(store, work)
    episode = Router(store, Coordinator(store, FakeLane(store, [FakeTurn([THINK], '好。')]))).receive(
        line_event('agent-plan', AGENT_SCENE, AGENT_PERSON, 'agent', '记得看一眼适配器'))
    source = store.db.messages.find_one({'_id': 'in-' + episode['_id']})
    assert source['event']['integration_profile'] == 'agent_home'         # 挂计划的这一回合确实是窄授权回合
    service = ScheduleService.__new__(ScheduleService)
    service.store, service.lane, service.controller = store, NativeLane(), Recorder()
    service.deliver_lock, service.rhythm_lock = threading.RLock(), threading.RLock()
    service.app = types.SimpleNamespace(config=store.config)
    plan = service.create(episode, {'intent': '看一眼适配器', 'after_seconds': 60})
    assert plan['integration_profile'] is None
    fire(service, plan)
    assert service.controller.events, '计划没有到期'
    assert all('integration_profile' not in event for event in service.controller.events), service.controller.events


def test_a_broken_binding_refuses_a_declared_grant_and_leaves_a_trace(store):
    """声明了 owner、集成绑定却和本机聊天对不上：还是不授权（返回 None），但这一笔在审计里看得见。"""
    from asuna.integration import event_profile
    config = profile('dm-a', 'A')
    config['integration']['person_id'] = 'someone-else'                 # 绑定坏了：配置问题，不是参数问题
    event = {'event_id': 'broken-binding', 'scene_id': 'dm-a', 'person_id': 'A',
             'text': 'take the report', 'integration_profile': 'owner'}
    assert event_profile(config, event, store) is None                   # 行为不变：悄悄没授权，不往外抛
    row = store.db.audit_events.find_one({'type': 'integration.grant_refused'})
    assert row is not None and row['payload']['reason'] == 'INTEGRATION_PROFILE_BINDING_MISMATCH', row
    assert row['payload']['declared'] == 'owner' and row['payload']['event_id'] == 'broken-binding'
    assert row['scope_key'] == 'scene:dm-a'
    assert event_profile(config, event) is None                          # 没有 store 的用法照旧，只是没地方记
