"""Local adapter invariants. These tests do not create any Mongo database."""
from types import SimpleNamespace

import pytest
from asuna.native_worker import BusinessWorker, prune_host_reports, KEPT_HOST_REPORTS
from asuna.state import Denied
from asuna.router import Router
from asuna.config import ROOT
from concurrent.futures import Future


def test_task_fence_ends_old_pending_stage_without_ending_its_successor():
    worker=BusinessWorker(); events=[]; worker.emit=events.append
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
    worker=BusinessWorker(); calls=[]
    worker.session=lambda _: {'lane':'executor','task_id':'successor'}
    def valid(task):
        if task['_id']=='old':raise Denied('STALE_TASK_FENCE')
    worker.app=SimpleNamespace(service=SimpleNamespace(valid=valid),broker=SimpleNamespace(
        bind=lambda session,task,cwd:calls.append((session,task['_id'],cwd)),
        call=lambda *args:{'accepted':True}),
        store=SimpleNamespace(config={},db=SimpleNamespace(scenes=SimpleNamespace(find_one=lambda *a,**k:None))))
    for token,task in (('old-stage','old'),('new-stage','successor')):
        future=Future();future.asuna_lane='executor';future.asuna_session_id='source'
        future.asuna_task={'_id':task,'scene_id':'s'};future.asuna_binding={'cwd':str(tmp_path)}
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


def test_group_role_is_continuous_across_speakers_but_not_scenes_or_authorization_epochs():
    ep = {'scene_id': 'qq:bot:group:one', 'person_id': 'alice', 'persona': 'xiaoman',
          'policy_epoch': 1, 'character_context': None}
    session_id = BusinessWorker.role_session_id(ep)
    assert BusinessWorker.role_session_id({**ep, 'person_id': 'bob'}) == session_id
    for changed in ({'scene_id': 'qq:bot:group:two'}, {'scene_id': 'qq:bot:dm:alice'},
                    {'policy_epoch': 2}, {'character_context': 'explicit-reset'}):
        assert BusinessWorker.role_session_id({**ep, **changed}) != session_id


def test_group_actor_changes_reauthorize_while_action_task_actor_is_immutable():
    worker = BusinessWorker()
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
    worker = BusinessWorker()
    record = {'scene_id': 'scene', 'person_id': 'person', 'policy_epoch': 1}
    worker.app = SimpleNamespace(store=SimpleNamespace(
        db=SimpleNamespace(sessions=SimpleNamespace(find_one=lambda query: record)),
        authorize=lambda scene, person: {'policy_epoch': 2}))
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        worker.session('native-session')


def test_qq_is_view_only_including_unbound_native_sessions():
    worker = BusinessWorker()
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
    worker = BusinessWorker()
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




def test_a_tool_error_is_its_own_words_and_a_fault_says_it_is_not_hers():
    from asuna.native_worker import error_text
    refusal = ValueError('INVALID_COMMAND: argv 有 41 项，上限 40；合并参数或写成脚本再跑')
    assert error_text('tool', refusal) == str(refusal)                       # no class name before her words
    assert error_text('role_tool', Denied('STALE_TASK_FENCE')) == 'STALE_TASK_FENCE'
    fault = error_text('tool', KeyError('scene_id'))
    assert fault.startswith('TOOL_FAULT: ') and "KeyError: 'scene_id'" in fault and '不是参数写错' in fault
    assert error_text('tool', RuntimeError('ENOENT: no such file')).startswith('TOOL_FAULT: ')   # not a code
    assert error_text('status', KeyError('x')) == "KeyError: 'x'"            # only tool calls are told how to act


def test_the_session_binding_names_its_conversations_clock():
    """web_search (a Host tool) puts publication times on this clock, as every time a model reads is."""
    worker = BusinessWorker()
    record = {'_id': 'native-session', 'scene_id': 'scene', 'person_id': 'person', 'policy_epoch': 1}
    worker.app = SimpleNamespace(store=SimpleNamespace(config={'timezone': 'Pacific/Auckland'},
        db=SimpleNamespace(sessions=SimpleNamespace(find_one=lambda query: record),
                           scenes=SimpleNamespace(find_one=lambda query: None)),
        authorize=lambda scene, person: {'policy_epoch': 1}))
    binding = worker.dispatch('session', {'session_id': 'native-session'})
    assert binding['timezone'] == 'Pacific/Auckland' and binding['utc_offset_minutes'] in (720, 780)
    assert binding['scene_id'] == 'scene'


def test_a_worker_start_keeps_only_the_newest_host_reports(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr('asuna.native_worker.DATA', tmp_path)
    reports = tmp_path / 'reports'
    for index in range(KEPT_HOST_REPORTS + 3):
        folder = reports / ('native-host-%02d' % index); folder.mkdir(parents=True)
        (folder / 'events.jsonl').write_text('{}', encoding='utf-8')
        os.utime(folder, (1000 + index, 1000 + index))
    (reports / 'other-run').mkdir()
    prune_host_reports()
    kept = sorted(p.name for p in reports.iterdir())
    assert kept == ['native-host-%02d' % i for i in range(3, KEPT_HOST_REPORTS + 3)] + ['other-run']
