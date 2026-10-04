"""Local adapter invariants. These tests do not create any Mongo database."""
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from asuna.native_worker import BusinessWorker, NativeLane
from asuna.state import Denied
from asuna.router import Router
from asuna.config import ROOT
from unittest.mock import patch
from concurrent.futures import Future


def test_worker_import_does_not_load_sdk_or_old_web():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import asuna.native_worker; "
        "assert 'asuna.dsh_lane' not in sys.modules; "
        "assert 'asuna.ui' not in sys.modules; "
        "assert not any(n.startswith('deepseek_harness') for n in sys.modules)"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_task_fence_ends_old_pending_stage_without_ending_its_successor():
    worker=BusinessWorker('unused'); events=[]; worker.emit=events.append
    old,new=Future(),Future()
    for future,revision in ((old,1),(new,2)):
        future.asuna_task={'_id':'task','intent_revision':revision}
        future.asuna_session_id='same-native-source'
    worker.pending={'old':old,'new':new}
    worker.task_fenced({'_id':'task','intent_revision':2},'task_revised')
    assert str(old.exception())=='STALE_TASK_FENCE' and not new.done()
    assert events==[{'kind':'task_fenced','token':'old','session_id':'same-native-source',
        'task_id':'task','intent_revision':2,'reason':'task_revised'}]
    worker.task_fenced({'_id':'task','intent_revision':2},'task_revised')
    assert len(events)==1


def test_tool_operation_cannot_inherit_mutable_session_successor_grant(tmp_path):
    worker=BusinessWorker('unused'); calls=[]
    worker.session=lambda _: {'lane':'executor','task_id':'successor'}
    def valid(task):
        if task['_id']=='old':raise Denied('STALE_TASK_FENCE')
    worker.app=SimpleNamespace(service=SimpleNamespace(valid=valid),broker=SimpleNamespace(
        bind=lambda session,task,cwd:calls.append((session,task['_id'],cwd)),
        call=lambda *args:{'accepted':True}))
    for token,task in (('old-stage','old'),('new-stage','successor')):
        future=Future();future.asuna_lane='executor';future.asuna_session_id='source'
        future.asuna_task={'_id':task};future.asuna_binding={'cwd':str(tmp_path)}
        future.asuna_broker_session=token
        worker.pending[token]=future
    args={'session_id':'source','call_id':'call','tool':'read_file','args':{'path':'note'}}
    with pytest.raises(Denied,match='NATIVE_OPERATION_NOT_ACTIVE'):worker.dispatch('tool',args)
    with pytest.raises(Denied,match='STALE_TASK_FENCE'):worker.dispatch('tool',{**args,'operation':'old-stage'})
    with pytest.raises(Denied,match='SESSION_MISMATCH'):
        worker.dispatch('tool',{**args,'operation':'new-stage','session_id':'other-source'})
    assert not calls
    assert worker.dispatch('tool',{**args,'operation':'new-stage'})=={'accepted':True}
    assert calls==[('new-stage','successor',tmp_path)]


def test_native_lane_does_not_invent_or_rebind_an_episode():
    ep = {'_id': 'ep-current'}
    store = SimpleNamespace(config={'workflow_timeout_seconds': 1}, db=SimpleNamespace(
        lane_receipts=SimpleNamespace(find_one=lambda query: None),
        episodes=SimpleNamespace(find_one=lambda query: ep)))
    ready = threading.Event(); ready.set()
    lane = NativeLane(SimpleNamespace(navigation_ready=ready), {'character': {'model': 'native-host'}}, store, None)
    with pytest.raises(ValueError, match='NATIVE_ROLE_SESSION_REQUIRED'):
        lane.generate('legacy-binding', 'ep-current:MONOLOGUE:0', 'MONOLOGUE', 'text', 'system')
    assert ep == {'_id': 'ep-current'}


def test_action_successor_uses_the_same_native_context_with_its_current_task_grant(tmp_path):
    class Rows:
        def __init__(self): self.rows = {}
        def find_one(self, query, **kwargs):
            return next((dict(row) for row in reversed(list(self.rows.values()))
                         if all(row.get(k) == v for k, v in query.items())), None)
    tables = {name: Rows() for name in ('tasks', 'episodes', 'sessions', 'messages', 'lane_receipts')}
    for index in (1, 2, 3):
        tables['tasks'].rows[f'task{index}'] = {'_id': f'task{index}', 'episode_id': f'ep{index}',
            'intent_revision': 1,
            'allowed_capabilities': ['read_file'] if index == 1 else []}
        tables['episodes'].rows[f'ep{index}'] = {'_id': f'ep{index}', 'scene_id': 'local', 'person_id': 'owner',
            'scope_key': 'scope', 'policy_epoch': 1, 'persona': 'fixture',
            'native_session_id': 'role' if index < 3 else 'another-role'}
    def put(name, values, **kwargs):
        values = {**values, 'revision': (tables[name].rows.get(values['_id']) or {}).get('revision', 0) + 1}
        tables[name].rows[values['_id']] = values
        return values
    config = {'workflow_timeout_seconds': 2, 'executor': {}}
    store = SimpleNamespace(config=config, db=SimpleNamespace(**tables), put=put,
                            authorize=lambda *_: {'policy_epoch': 1})
    worker = BusinessWorker('unused'); worker.app = SimpleNamespace(store=store,
        service=SimpleNamespace(lock=threading.RLock(),valid=lambda task:task),
        broker=SimpleNamespace(bindings={}))
    worker.navigation_ready.set(); worker.controller = SimpleNamespace(ingress_lock=threading.RLock(), reconfiguring=False)
    requests = []
    def emit(event):
        requests.append(event)
        worker.pending[event['token']].set_result({'content': 'native receipt', 'finish_reason': 'stop'})
    worker.emit = emit
    with patch('asuna.native_worker.workspace_grant', return_value={'workspace': str(tmp_path)}), \
         patch('asuna.native_worker.skills_directory', return_value=None), \
         patch('asuna.native_worker.skill_directories', return_value=[]):
        lane = NativeLane(worker, config, store, None, lane='executor')
        for index in (1, 2, 3):
            lane.generate('same-execution-binding', f'task{index}:execute:1', 'execution', 'context', 'system')
        before = len(requests)
        lane.generate('same-execution-binding', 'task1:execute:1', 'execution', 'context', 'system')
        assert len(requests) == before, 'saved results must not reopen a completed stage'
    assert requests[0]['session_id'] == requests[1]['session_id']
    assert requests[2]['session_id'] != requests[1]['session_id'], 'another native role is an isolation boundary'
    assert [r['binding']['task_id'] for r in requests] == ['task1', 'task2', 'task3']
    assert requests[1]['binding']['allowed_capabilities'] == []
    assert requests[1]['binding']['execution_binding'] == 'same-execution-binding'


def test_group_role_is_continuous_across_speakers_but_not_scenes_or_authorization_epochs():
    ep = {'scene_id': 'qq:bot:group:one', 'person_id': 'alice', 'persona': 'xiaoman',
          'policy_epoch': 1, 'character_context': None}
    session_id = BusinessWorker.role_session_id(ep)
    assert BusinessWorker.role_session_id({**ep, 'person_id': 'bob'}) == session_id
    for changed in ({'scene_id': 'qq:bot:group:two'}, {'scene_id': 'qq:bot:dm:alice'},
                    {'policy_epoch': 2}, {'character_context': 'explicit-reset'}):
        assert BusinessWorker.role_session_id({**ep, **changed}) != session_id


def test_summary_resolves_its_scene_parent_with_the_real_audit_scope():
    worker = BusinessWorker('unused')
    worker.navigation_ready.set()
    scene = {'_id': 'qq:bot:group:one', 'scope_key': 'group-scope', 'policy_epoch': 1,
             'members': ['member']}
    audits = []
    empty = SimpleNamespace(find_one=lambda _: None)
    config = {'workflow_timeout_seconds': 1, 'chat': {'persona': 'xiaoman'}, 'executor': {}}
    store = SimpleNamespace(config=config, db=SimpleNamespace(lane_receipts=empty, messages=empty,
        plans=empty, sessions=empty, scenes=SimpleNamespace(find_one=lambda _: scene)),
        authorize=lambda *_: scene, audit=lambda *args: audits.append(args))
    worker.app = SimpleNamespace(config=config, store=store)
    def stop_before_stage(session_id):
        assert session_id == BusinessWorker.role_session_id({
            'scene_id': scene['_id'], 'persona': 'xiaoman', 'policy_epoch': 1})
        raise RuntimeError('PROBE_STOP_BEFORE_HOST_STAGE')
    worker.continued_session = stop_before_stage
    with pytest.raises(RuntimeError, match='PROBE_STOP_BEFORE_HOST_STAGE'):
        NativeLane(worker, config, store, None, lane='summary').generate(
            'summary', 'summary:one', 'SUMMARY', 'source', 'instructions',
            scope_key=scene['scope_key'], policy_epoch=1)
    assert audits[0][-1] == scene['scope_key']


def test_group_actor_changes_reauthorize_while_action_task_actor_is_immutable():
    worker = BusinessWorker('unused')
    prior = {'_id': 'group', 'revision': 1, 'lane': 'character', 'scene_id': 'group',
             'person_id': 'alice', 'persona': 'xiaoman', 'cwd': 'authorized', 'policy_epoch': 1}
    calls = []
    def authorize(scene, person):
        calls.append((scene, person))
        if person not in ('alice', 'bob'):
            raise Denied('NOT_A_MEMBER')
        return {'policy_epoch': 1}
    worker.app = SimpleNamespace(store=SimpleNamespace(
        db=SimpleNamespace(sessions=SimpleNamespace(find_one=lambda _: prior)),
        authorize=authorize, put=lambda _, values, **kw: values))
    assert worker.bind_session('group', {**prior, 'person_id': 'bob'})['person_id'] == 'bob'
    assert calls[-1] == ('group', 'bob')
    with pytest.raises(Denied, match='NOT_A_MEMBER'):
        worker.bind_session('group', {**prior, 'person_id': 'outsider'})
    prior['lane'] = 'executor'
    with pytest.raises(Denied, match='NATIVE_BINDING_IDENTITY_CHANGED'):
        worker.bind_session('action', {**prior, 'person_id': 'bob'})


def test_bound_session_checks_current_authorization_epoch():
    worker = BusinessWorker('unused')
    record = {'scene_id': 'scene', 'person_id': 'person', 'policy_epoch': 1}
    worker.app = SimpleNamespace(store=SimpleNamespace(
        db=SimpleNamespace(sessions=SimpleNamespace(find_one=lambda query: record)),
        authorize=lambda scene, person: {'policy_epoch': 2}))
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        worker.session('native-session')


def test_qq_is_view_only_including_unbound_native_sessions():
    worker = BusinessWorker('unused')
    rows = [{'native_host': True, '_id': 'qq', 'scene_id': 'qq:bot:dm:one', 'lane': 'character'},
            {'native_host': True, '_id': 'local', 'scene_id': 'local', 'lane': 'character'},
            {'native_host': True, '_id': 'old-local', 'scene_id': 'local', 'lane': 'character', 'successor_id': 'local'}]
    worker.app = SimpleNamespace(config={'chat': {'scene_id': 'local'}}, store=SimpleNamespace(
        db=SimpleNamespace(sessions=SimpleNamespace(find=lambda _: rows))))
    policies = worker.dispatch('input_policies', {'sessions': [
        {'id': row['_id']} for row in rows] + [{'id': 'unbound-qq', 'cwd': str(ROOT / '.runtime/work/qq')}]})
    assert 'local' not in policies
    assert policies['qq'] == policies['unbound-qq']
    assert 'old-local' in policies


@pytest.mark.parametrize('workspace', ['qq', 'local'])
def test_web_input_requires_the_real_local_workspace(workspace, tmp_path):
    worker = BusinessWorker('unused')
    local = {'scene_id': 'local', 'person_id': 'owner', 'workspace': str(tmp_path / 'local')}
    worker.app = SimpleNamespace(config={'chat': local}, store=SimpleNamespace(
        db=SimpleNamespace(sessions=SimpleNamespace(find_one=lambda _: None))))
    accepted = []
    worker.controller = SimpleNamespace(submit=lambda text, **kw: accepted.append(text))
    args = {'session_id': 'new', 'cwd': str(tmp_path / workspace), 'text': 'draft', 'message_ids': ['message']}
    if workspace == 'qq':
        with pytest.raises(Denied, match='NATIVE_INPUT_WORKSPACE_MISMATCH'):
            worker.dispatch('input', args)
        assert not accepted
    else:
        worker.dispatch('input', args)
        assert accepted == ['draft']


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


def _alternate(dispatcher, worker, stage_wait=2, reply_wait=3):
    import time
    dispatcher.handle({'id': 1, 'method': 'tool', 'args': {'token': 'scene-a'}})
    dispatcher.handle({'id': 2, 'method': 'tool', 'args': {'token': 'scene-b'}})
    deadline = time.monotonic() + stage_wait
    while len([e for e in worker.emitted if e.get('kind') == 'stage']) < 2 and time.monotonic() < deadline:
        time.sleep(.01)
    dispatcher.handle({'id': 3, 'method': 'result', 'args': {'token': 'scene-b', 'value': 'B'}})
    dispatcher.handle({'id': 4, 'method': 'status', 'args': {}})
    dispatcher.handle({'id': 5, 'method': 'result', 'args': {'token': 'scene-a', 'value': 'A'}})
    deadline = time.monotonic() + reply_wait
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
    worker = StageWorker(wait=.3)
    dispatcher = native_worker.Dispatcher(worker, threads=1)
    try:
        replies = _alternate(dispatcher, worker, stage_wait=.2, reply_wait=.6)
    finally:
        dispatcher.close()
    assert str(replies.get(1, '')).startswith('TimeoutError'), replies     # the old routing starves
