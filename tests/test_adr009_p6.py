"""ADR-009 P6 MongoDB tests: T6.2 audit and receipt dedupe (T6.1 history delivery is a plugin test)."""
import json
import threading
import types

import pytest

from asuna.audit import projection, replay, trace_contents, verify, verify_documents
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, LaneResult
from asuna.native_worker import NativeLane
from asuna.state import Store, content_digest, content_ref
from test_adr009_p2 import decide, owner


def big_message(store, text):
    scene = store.db.scenes.find_one_and_update({'_id': 'dm-a'}, {'$inc': {'sequence': 1}}, return_document=True)
    return store.put('messages', {'_id': 'big', 'scene_id': 'dm-a', 'scope_key': scene['scope_key'], 'policy_epoch': 1,
                                  'scene_seq': scene['sequence'], 'direction': 'inbound', 'author': 'A', 'text': text},
                     stream='t62')


def test_T6_2_large_documents_are_audited_by_reference(store):
    text = '长文' * 6000                                         # 36 KB of UTF-8
    doc = big_message(store, text)
    commit = store.db.audit_events.find_one({'stream_id': 't62', 'type': 'state.commit'})
    assert 'document' not in commit['payload'] and text not in json.dumps(commit, ensure_ascii=False)
    assert commit['payload']['content_sha256'] == content_digest('messages', doc) and commit['payload']['bytes'] > 16 * 1024
    events = list(store.db.audit_events.find({}))
    verify(events)
    assert verify_documents(events, store) >= 1
    target = Store(store.config, store.name + '_replay')
    store.derived_databases = [target.name]
    with pytest.raises(ValueError, match='REPLAY_CONTENT_MISSING'):
        replay(events, target)
    target.client.drop_database(target.name)
    assert replay(events, target, trace_contents(events, store))['sha256'] == projection(store)['sha256']
    store.db.messages.update_one({'_id': 'big'}, {'$set': {'text': text + '改'}})
    with pytest.raises(ValueError, match='AUDIT_DOCUMENT_TAMPERED: messages/big'):
        verify_documents(events, store)
    small = store.put('messages', {**store.db.messages.find_one({'_id': 'big'}), '_id': 'small', 'text': '短'}, stream='t62')
    store.db.messages.update_one({'_id': 'small'}, {'$set': {'text': '改短'}})
    with pytest.raises(ValueError, match='messages/small'):
        verify_documents(list(store.db.audit_events.find({})), store)
    assert small['revision'] == 1


def test_T6_2_phase_output_keeps_hashes_and_native_receipts_are_final(store, tmp_path):
    owner(store)
    store.config['chat']['workspace'] = str(tmp_path)
    lane = FakeLane(store, [LaneResult('私下想的长内容' * 50), decide(), LaneResult('好')])
    ep = Coordinator(store, lane).ingest({'event_id': 'e1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
    outputs = list(store.db.audit_events.find({'stream_id': ep['_id'], 'type': 'phase.output'}))
    assert outputs and all('content' not in e['payload'] for e in outputs)
    assert '私下想的长内容' not in json.dumps([e['payload'] for e in outputs], ensure_ascii=False)
    assert outputs[0]['payload']['content_sha256'] == content_ref('私下想的长内容' * 50)['content_sha256']
    store.put('episodes', {**store.db.episodes.find_one({'_id': ep['_id']}), 'native_session_id': 'role-1'},
              expected=store.db.episodes.find_one({'_id': ep['_id']})['revision'], stream=ep['_id'])
    generated = []

    class Worker:
        pending_lock = threading.Lock()
        pending = {}
        navigation_ready = threading.Event()
        navigation_ready.set()

        controller = types.SimpleNamespace(ingress_lock=threading.Lock(), reconfiguring=False)

        def continued_session(self, session_id):
            return session_id

        def bind_session(self, session_id, values):
            return {'_id': session_id, **values}

        def emit(self, request):
            # A repeated token is answered from the saved native stage result (same text, no new generation).
            generated.append(request['token'])
            self.pending[request['token']].set_result({'content': '原生回答', 'request_refs': ['role-1:7']})

    native = NativeLane(Worker(), {'character': {'model': 'native-host'}}, store, None)
    first = native.generate('b', ep['_id'] + ':EXTRA:0', 'EXTRA', 'text', 'system')
    receipt = store.db.lane_receipts.find_one({'_id': ep['_id'] + ':EXTRA:0'})
    assert first.content == '原生回答' and receipt['result']['content'] == '原生回答'
    commit = store.db.audit_events.find_one({'type': 'state.commit', 'payload.collection': 'lane_receipts',
                                             'stream_id': ep['_id'] + ':EXTRA:0'})
    assert commit is not None
    again = native.generate('b', ep['_id'] + ':EXTRA:0', 'EXTRA', 'text', 'system')
    assert again.content == '原生回答' and generated == [ep['_id'] + ':EXTRA:0'], 'a completed stage is never reopened'


def test_a_platform_turn_binds_its_role_session(store):
    """A channel turn carries no native session id: the real resolver binds one from the scene.
    Regression: the binding lacked scope_key and every QQ turn failed before any stage ran."""
    from asuna.native_worker import BusinessWorker
    owner(store)
    worker = types.SimpleNamespace(navigation_ready=threading.Event(), role_session_id=BusinessWorker.role_session_id,
                                   app=types.SimpleNamespace(store=store, config={'workflow_timeout_seconds': 1}))
    worker.navigation_ready.set()
    coordinator = Coordinator(store, FakeLane(store, [LaneResult('想一想'), decide(), LaneResult('好')]))
    coordinator.native_session_resolver = lambda ep: BusinessWorker.resolve_role_session(worker, ep)
    ep = coordinator.ingest({'event_id': 'e-channel', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
    episode = store.db.episodes.find_one({'_id': ep['_id']})
    assert episode['native_session_id'].startswith('asuna-role-') and episode['state'] != 'FAILED_RUNTIME'
    bound = store.db.audit_events.find_one({'stream_id': ep['_id'], 'type': 'native.context.bound'})
    assert bound and bound['scope_key'] == store.db.scenes.find_one({'_id': 'dm-a'})['scope_key']


def test_a_stage_that_times_out_stops_its_native_run(store, tmp_path):
    """Regression: on a stage timeout the worker stopped waiting but the native run went on, its tools
    refused, for half an hour; continuing the same task then met it still running in the same session."""
    owner(store)
    store.config['chat']['workspace'] = str(tmp_path)
    store.config['workflow_timeout_seconds'] = 0.2
    ep = Coordinator(store, FakeLane(store, [LaneResult('想一想'), decide(), LaneResult('好')])).ingest(
        {'event_id': 'e-timeout', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
    store.put('episodes', {**store.db.episodes.find_one({'_id': ep['_id']}), 'native_session_id': 'role-1'},
              expected=store.db.episodes.find_one({'_id': ep['_id']})['revision'], stream=ep['_id'])
    emitted = []

    class Worker:
        pending_lock = threading.Lock()
        pending = {}
        navigation_ready = threading.Event()
        navigation_ready.set()
        controller = types.SimpleNamespace(ingress_lock=threading.Lock(), reconfiguring=False)

        def continued_session(self, session_id):
            return session_id

        def bind_session(self, session_id, values):
            return {'_id': session_id, **values}

        def emit(self, request):
            emitted.append(request)          # the host never answers

    native = NativeLane(Worker(), {'character': {'model': 'native-host'}}, store, None)
    with pytest.raises(TimeoutError):
        native.generate('b', ep['_id'] + ':EXTRA:0', 'EXTRA', 'text', 'system')
    assert [e['kind'] for e in emitted] == ['stage', 'task_fenced']
    assert emitted[1] == {'kind': 'task_fenced', 'token': ep['_id'] + ':EXTRA:0', 'session_id': 'role-1',
                          'reason': 'STAGE_TIMEOUT'}
    assert Worker.pending == {}
