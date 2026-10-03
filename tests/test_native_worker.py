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


def test_worker_import_does_not_load_sdk_or_old_web():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import asuna.native_worker; "
        "assert 'asuna.dsh_lane' not in sys.modules; "
        "assert 'asuna.ui' not in sys.modules; "
        "assert not any(n.startswith('deepseek_harness') for n in sys.modules)"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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
