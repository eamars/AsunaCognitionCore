"""Local adapter invariants. These tests do not create any Mongo database."""
import threading
from types import SimpleNamespace

import pytest
from asuna.native_worker import BusinessWorker, prune_host_reports, KEPT_HOST_REPORTS
from asuna.state import Denied
from asuna.router import Router
from asuna.records import scenes as scene_records
from asuna.records import sessions as session_records
from asuna.config import DATA, ROOT
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


def test_tool_operation_cannot_inherit_mutable_session_successor_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_records, 'get', lambda *a, **k: None)
    worker=BusinessWorker(); calls=[]
    worker.session=lambda _: {'lane':'executor','task_id':'successor'}
    def valid(task):
        if task['_id']=='old':raise Denied('STALE_TASK_FENCE')
    worker.app=SimpleNamespace(service=SimpleNamespace(valid=valid),broker=SimpleNamespace(
        bind=lambda session,task,cwd:calls.append((session,task['_id'],cwd)),
        call=lambda *args:{'accepted':True}),
        store=SimpleNamespace(config={}))
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


def test_group_actor_changes_reauthorize_while_action_task_actor_is_immutable(monkeypatch):
    worker = BusinessWorker()
    prior = {'_id': 'group', 'revision': 1, 'lane': 'character', 'scene_id': 'group',
             'person_id': 'alice', 'persona': 'xiaoman', 'cwd': 'authorized', 'policy_epoch': 1}
    calls = []
    def authorize(scene, person):
        calls.append((scene, person))
        if person not in ('alice', 'bob'):
            raise Denied('NOT_A_MEMBER')
        return {'policy_epoch': 1}
    monkeypatch.setattr(scene_records, 'authorize', lambda store, scene, person: authorize(scene, person))
    monkeypatch.setattr(session_records, 'get', lambda store, session_id, fields=None, native=False: prior)
    worker.app = SimpleNamespace(store=SimpleNamespace(put=lambda _, values, **kw: values))
    assert worker.bind_session('group', {**prior, 'person_id': 'bob'})['person_id'] == 'bob'
    assert calls[-1] == ('group', 'bob')
    with pytest.raises(Denied, match='NOT_A_MEMBER'):
        worker.bind_session('group', {**prior, 'person_id': 'outsider'})
    prior['lane'] = 'executor'
    with pytest.raises(Denied, match='NATIVE_BINDING_IDENTITY_CHANGED'):
        worker.bind_session('action', {**prior, 'person_id': 'bob'})


def test_bound_session_checks_current_authorization_epoch(monkeypatch):
    worker = BusinessWorker()
    record = {'scene_id': 'scene', 'person_id': 'person', 'policy_epoch': 1}
    monkeypatch.setattr(scene_records, 'authorize', lambda store, scene, person: {'policy_epoch': 2})
    monkeypatch.setattr(session_records, 'get', lambda store, session_id, fields=None, native=False: record)
    worker.app = SimpleNamespace(store=SimpleNamespace())
    with pytest.raises(Denied, match='NATIVE_SESSION_EPOCH_CHANGED'):
        worker.session('native-session')


def test_qq_is_view_only_including_unbound_native_sessions(monkeypatch):
    worker = BusinessWorker()
    rows = [{'native_host': True, '_id': 'qq', 'scene_id': 'qq:bot:dm:one', 'lane': 'character'},
            {'native_host': True, '_id': 'local', 'scene_id': 'local', 'lane': 'character'},
            {'native_host': True, '_id': 'old-local', 'scene_id': 'local', 'lane': 'character', 'successor_id': 'local'}]
    monkeypatch.setattr(session_records, 'native', lambda store, *a, **k: SimpleNamespace(rows=lambda **kw: rows))
    worker.app = SimpleNamespace(config={'chat': {'scene_id': 'local'}}, store=SimpleNamespace())
    policies = worker.dispatch('input_policies', {'sessions': [
        {'id': row['_id']} for row in rows] + [{'id': 'unbound-qq', 'cwd': str(DATA / 'work/qq')}]})
    assert 'local' not in policies
    assert policies['qq'] == policies['unbound-qq']
    assert 'old-local' in policies


@pytest.mark.parametrize('workspace', ['qq', 'local'])
def test_web_input_requires_the_real_local_workspace(workspace, tmp_path, monkeypatch):
    worker = BusinessWorker()
    local = {'scene_id': 'local', 'person_id': 'owner', 'workspace': str(tmp_path / 'local')}
    monkeypatch.setattr(session_records, 'get', lambda store, session_id, fields=None, native=False: None)
    worker.app = SimpleNamespace(config={'chat': local}, store=SimpleNamespace())
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
def test_only_private_host_input_preserves_native_binding(channel, monkeypatch):
    captured = []
    monkeypatch.setattr(scene_records, 'authorize', lambda *_: {'_id': 'scene', 'scope_key': 'scope', 'kind': 'dm'})
    store = SimpleNamespace(config={}, audit=lambda *_: None)
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


def test_the_session_binding_names_its_conversations_clock(monkeypatch):
    """web_search (a Host tool) puts publication times on this clock, as every time a model reads is."""
    worker = BusinessWorker()
    record = {'_id': 'native-session', 'scene_id': 'scene', 'person_id': 'person', 'policy_epoch': 1}
    monkeypatch.setattr(scene_records, 'get', lambda *a, **k: None)
    monkeypatch.setattr(scene_records, 'authorize', lambda store, scene, person: {'policy_epoch': 1})
    monkeypatch.setattr(session_records, 'get', lambda store, session_id, fields=None, native=False: record)
    worker.app = SimpleNamespace(store=SimpleNamespace(config={'timezone': 'Etc/GMT-9'}))
    binding = worker.dispatch('session', {'session_id': 'native-session'})
    assert binding['timezone'] == 'Etc/GMT-9' and binding['utc_offset_minutes'] == 540
    assert binding['scene_id'] == 'scene'


def host_reports(tmp_path, monkeypatch, ages_hours, records=1):
    """Report folders of starts that last wrote `ages_hours` ago, newest first, `records` files each."""
    import os
    from asuna import clock
    monkeypatch.setattr('asuna.native_worker.DATA', tmp_path)
    now, folders = clock.now().timestamp(), []
    for index, age in enumerate(ages_hours):
        folder = tmp_path / 'reports' / ('native-host-%03d' % index)
        folder.mkdir(parents=True)
        for n in range(records):
            (folder / ('%05d-x.json' % n)).write_text('{}', encoding='utf-8')
        os.utime(folder, (now - age * 3600, now - age * 3600))
        folders.append(folder)
    return folders


def test_host_reports_of_a_restart_loop_outlive_the_loop(tmp_path, monkeypatch):
    """Regression (10-30): eleven starts in 31 minutes, and each start kept only the newest five reports, so the
    reports of the loop's first starts were gone within minutes. Every start of the last two days stays; past
    them, the newest five, as before."""
    loop = [n / 60 for n in range(0, 36, 3)]                  # twelve starts, one every 3 minutes
    folders = host_reports(tmp_path, monkeypatch, loop + [50, 60, 70])
    (tmp_path / 'reports' / 'other-run').mkdir()
    pruned = prune_host_reports(folders[0])
    kept = sorted(p.name for p in (tmp_path / 'reports').iterdir())
    assert kept == sorted(f.name for f in folders[:len(loop)]) + ['other-run']
    assert (pruned['kept'], pruned['removed'], pruned['removed_wanted']) == (len(loop), 3, 0)
    quiet = host_reports(tmp_path / 'quiet', monkeypatch, [0, 100, 200, 300, 400, 500, 600])
    prune_host_reports(quiet[0])
    assert sorted(p.name for p in (tmp_path / 'quiet' / 'reports').iterdir()) == [f.name for f in quiet[:KEPT_HOST_REPORTS]]


def test_host_reports_past_their_bound_go_oldest_first_and_say_so(tmp_path, monkeypatch):
    """The disk bound holds over the time rule; what it removes leaves no gap, and the start says it removed evidence
    the rule would have kept."""
    from asuna import native_worker
    monkeypatch.setattr(native_worker, 'HOST_REPORTS_MOST_RECORDS', 10)
    folders = host_reports(tmp_path, monkeypatch, [0, .1, .2, .3, .4], records=3)
    pruned = prune_host_reports(folders[0])
    assert sorted(p.name for p in (tmp_path / 'reports').iterdir()) == [f.name for f in folders[:3]]
    assert (pruned['kept'], pruned['kept_records'], pruned['removed_wanted']) == (3, 9, 2)
    monkeypatch.setattr(native_worker, 'HOST_REPORTS_MOST', 2)
    assert prune_host_reports(folders[0])['removed_wanted'] == 1, 'and by starts'


def test_one_long_run_keeps_its_newest_records_and_their_chain(tmp_path):
    """A Host run that never restarts must not grow without end: only the newest `keep` records stay."""
    import json
    from asuna.evidence import Evidence
    evidence = Evidence(tmp_path / 'native-host-x', keep=3, pinned=('runtime.ready',))
    ready = evidence.record('runtime.ready', {})
    names = [evidence.record('lane.ready', {'n': n}) for n in range(7)]
    kept = sorted(p.name for p in (tmp_path / 'native-host-x').iterdir())
    assert kept == [ready] + names[-3:], "the start's proof of life stays"
    kept = kept[1:]
    rows = [json.loads((tmp_path / 'native-host-x' / name).read_text(encoding='utf-8')) for name in kept]
    assert [row['prev_hash'] for row in rows[1:]] == [row['event_hash'] for row in rows[:-1]], 'the kept ones still chain'
    unbounded = Evidence(tmp_path / 'attempt')
    for n in range(5):
        unbounded.record('x', {'n': n})
    assert len(list((tmp_path / 'attempt').iterdir())) == 5, 'an attempt keeps everything'


@pytest.mark.parametrize('member', [True, False])
def test_the_owner_writes_on_an_agent_line_he_joins(member, tmp_path, monkeypatch):
    """ADR-051: the composer is open on an agent line whose members include the owner; his words go to that line."""
    from asuna import channel_kinds
    channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'agent-line' / 'python', 'module': 'agent_line'}])
    line = {'native_host': True, '_id': 'line', 'scene_id': 'agent:home:dm:claude-code', 'person_id': 'agent:claude-code',
            'lane': 'character', 'cwd': str(tmp_path / 'agent')}
    qq = {'native_host': True, '_id': 'qq', 'scene_id': 'qq:bot:dm:one', 'lane': 'character', 'cwd': str(tmp_path / 'qq')}
    rows = {'line': line, 'qq': qq}
    members = ['agent:claude-code'] + (['owner'] if member else [])
    worker = BusinessWorker()
    monkeypatch.setattr(scene_records, 'get', lambda *a, **k: {'members': members})
    worker.app = SimpleNamespace(config={'chat': {'scene_id': 'local', 'person_id': 'owner', 'workspace': str(tmp_path / 'local')}},
        store=SimpleNamespace())
    monkeypatch.setattr(session_records, 'native',
                        lambda store, *a, **k: SimpleNamespace(rows=lambda **kw: list(rows.values())))
    monkeypatch.setattr(session_records, 'get', lambda store, session_id, fields=None, native=False: rows.get(session_id))
    accepted = []
    worker.controller = SimpleNamespace(submit=lambda text, **kw: accepted.append((text, kw['scene_id'])))
    policies = worker.dispatch('input_policies', {'sessions': [{'id': 'line', 'cwd': line['cwd']}, {'id': 'qq'}]})
    assert 'qq' in policies and ('line' not in policies) == member
    args = {'session_id': 'line', 'cwd': line['cwd'], 'text': '我也在', 'message_ids': ['m1']}
    if member:
        worker.dispatch('input', args)
        assert accepted == [('我也在', 'agent:home:dm:claude-code')]
    else:
        with pytest.raises(Denied, match='NATIVE_INPUT_WORKSPACE_MISMATCH'):
            worker.dispatch('input', args)
    with pytest.raises(Denied, match='NATIVE_INPUT_WORKSPACE_MISMATCH'):
        worker.dispatch('input', {**args, 'session_id': 'qq', 'cwd': qq['cwd']})


class Asked:
    """A lock that says when a thread starts to wait for it."""
    def __init__(self, inner):
        self.inner, self.asked = inner, threading.Event()

    def __enter__(self):
        self.asked.set()
        return self.inner.__enter__()

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    @property
    def holder(self):
        return getattr(self.inner, 'holder', None)


class Evidence:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def record(self, kind, payload):
        if self.fail:
            raise OSError('EVIDENCE_UNAVAILABLE')
        self.rows.append((kind, payload))


def stage_worker(effects, evidence=None):
    worker = BusinessWorker()
    worker.controller = SimpleNamespace(ingress_lock=threading.RLock(), reconfiguring=False)
    worker.app = SimpleNamespace(service=SimpleNamespace(lock=effects, valid=lambda task: task),
                                 evidence=evidence or Evidence())
    return worker


def executor_future():
    future = Future()
    future.asuna_lane = 'executor'
    return future


def hold(lock, seconds=None, name='tool-call'):
    """A thread that holds `lock` until released (or for `seconds`); returns (thread, release)."""
    release, taken = threading.Event(), threading.Event()

    def run():
        with lock:
            taken.set()
            release.wait(seconds if seconds is not None else 10)
    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    assert taken.wait(5)
    return thread, release


def test_a_stage_waiting_for_the_effects_lock_does_not_hold_the_ingress_fence():
    """A tool call that holds the effects lock delays only the stages that need it: an inbound line takes the
    ingress fence at once while a task's stage waits."""
    effects = Asked(threading.RLock())
    worker = stage_worker(effects)
    holder, release = hold(effects.inner)
    stage = threading.Thread(target=worker.register_stage, args=('op', executor_future(), {'_id': 'task'}),
                             daemon=True)
    try:
        stage.start()
        assert effects.asked.wait(5)
        assert worker.controller.ingress_lock.acquire(timeout=1), 'an admission waited behind the effects lock'
        worker.controller.ingress_lock.release()
        assert 'op' not in worker.pending
    finally:
        release.set()
        stage.join(5)
        holder.join(5)
    assert 'op' in worker.pending


def test_a_long_wait_for_the_effects_lock_is_recorded_once_and_a_short_one_not_at_all(monkeypatch):
    from asuna import native_worker
    from asuna.queue import _DatabaseEffectsLock, effects_lock_path
    from asuna.testing import remove_lock_files
    monkeypatch.setattr(native_worker, 'EFFECTS_WAIT_SECONDS', 0.2)
    name = 'asuna_v2_test_effects_wait'
    effects = _DatabaseEffectsLock(name)
    try:
        evidence = Evidence()
        worker = stage_worker(effects, evidence)
        holder, _ = hold(effects, seconds=0.5)
        worker.register_stage('long', executor_future(), {'_id': 'task'})
        holder.join(5)
        worker.register_stage('short', executor_future(), {'_id': 'task'})
        [(kind, payload)] = evidence.rows
        assert kind == 'host.effects_lock_wait'
        assert payload['lane'] == 'executor' and payload['holder'] == 'tool-call' and payload['seconds'] >= 0.2
        assert set(worker.pending) == {'long', 'short'}
        failing = stage_worker(effects, Evidence(fail=True))
        holder, _ = hold(effects, seconds=0.5)
        failing.register_stage('unrecorded', executor_future(), {'_id': 'task'})
        holder.join(5)
        assert 'unrecorded' in failing.pending, 'a failure to record is not the stage\'s'
    finally:
        remove_lock_files(effects_lock_path(name))


def test_a_started_worker_supersedes_a_publication_it_did_not_load(store):
    """Regression (10-30): her second core publication landed while the worker that was stopping for the first
    never recorded it. The started worker reported only the second as loaded; the first stayed APPLIED and asked
    for a worker restart after every turn, each one revoking her running tasks."""
    from asuna.records import receipts as receipt_records
    for _id, project in (('first-core', 'core'), ('waiting-channel', 'napcat-qq')):
        receipt_records.save_sink(store, {'_id': _id, 'kind': 'self_development_publish', 'state': 'APPLIED',
                                          'project': project, 'task_id': 'task'}, stream='task')
    worker = BusinessWorker()
    worker.app = SimpleNamespace(store=store)
    worker.host = SimpleNamespace(_complete_activations=lambda: None, activation_settled=threading.Event())
    worker.dispatch('publication.activated', {'publications': [
        {'receipt_id': 'second-core', 'project': 'core', 'state': 'ACTIVE', 'activated_at': 'now'}]})
    first = receipt_records.sink_get(store, 'first-core')
    assert (first['state'], first['superseded_by']) == ('SUPERSEDED', 'second-core')
    assert receipt_records.sink_get(store, 'waiting-channel')['state'] == 'APPLIED'
    assert receipt_records.sink_of_kind(store, 'self_development_publish', state='APPLIED', project='core').first() is None


def test_a_started_worker_gives_her_task_the_publication_no_worker_recorded(store, monkeypatch):
    """Regression (10-30 23:37): the worker that asked for her publication stopped before the Host's answer came back.
    The next start wrote the publication as a recovery with no task, so her task kept a failed call and she was never
    told the publication had gone through."""
    from asuna.host import RuntimeHost
    from asuna.records import receipts as receipt_records
    from asuna.records import tasks as task_records
    monkeypatch.setattr(task_records, 'get', lambda store, task_id, **kw:
                        {'_id': 'task-p', 'scope_key': 'scene:s'} if task_id == 'task-p' else None)
    offered = []
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None), awaits_activation=True)
    host.app = SimpleNamespace(store=store)
    host.controller = SimpleNamespace(offer_self_development=lambda event_id, **kw: offered.append(
        (event_id, kw['task_id'], kw['trusted_context_events'][0]['state'])))
    worker = BusinessWorker()
    worker.app, worker.host = SimpleNamespace(store=store), host
    loaded = {'state': 'ACTIVE', 'activated_at': 'now', 'candidate': 'c', 'changed_files': ['a.py'], 'boot_probe': {}}
    worker.dispatch('publication.activated', {'publications': [
        {**loaded, 'receipt_id': 'hers', 'project': 'core',
         'origin': {'task_id': 'task-p', 'scope_key': 'scene:s', 'intent_revision': 2}},
        {**loaded, 'receipt_id': 'install', 'project': 'napcat-qq'}]})
    hers = receipt_records.sink_get(store, 'hers')
    assert (hers['kind'], hers['task_id'], hers['scope_key'], hers['state']) == (
        'self_development_publish', 'task-p', 'scene:s', 'ACTIVE')
    assert receipt_records.sink_get(store, 'install')['kind'] == 'native_recovery_publish'
    assert offered == [('self-development:publish:hers', 'task-p', 'ACTIVE')]
