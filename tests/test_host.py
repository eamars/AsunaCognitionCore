"""Host contracts on isolated Mongo; fake model receipts, never real QQ sends."""
import json
from types import SimpleNamespace

import pytest

from asuna.chat import Chat, SceneQueue
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.ingress import persist_input, input_state, episode_id
from asuna.lanes import FakeLane, LaneResult
from asuna.resources import workspace_grant
from asuna.router import Router
from asuna.state import Denied


def event(key='one', text='input'):
    return {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': text}


def responses():
    return [LaneResult('private'), LaneResult(json.dumps({'next': 'speak', 'goal': 'reply',
            'constraints': [], 'recall_query': '', 'speak_before_action': False})), LaneResult('public')]


def controller(store, tmp_path, coordinator):
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=coordinator.character, router=Router(store, coordinator))
    return Chat(app, {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': 'test'}, lambda _: None)


def test_receive_persists_without_context_or_worker_and_dedupes(store, tmp_path):
    class UnavailableContext:
        def prepare(self, *args):
            raise RuntimeError('retrieval unavailable')
    lane = FakeLane(store, [])
    coordinator = Coordinator(store, lane, context=UnavailableContext())
    chat = controller(store, tmp_path, coordinator)
    accepted = chat.receive(event())
    assert chat.receive(event())['status'] == 'duplicate'
    assert chat.pending.qsize() == 1 and not lane.calls
    source = store.db.messages.find_one({'_id': 'in-' + accepted['episode_id']})
    assert source['text'] == 'input' and source['ingress_state'] == 'ACCEPTED'
    with pytest.raises(RuntimeError, match='retrieval unavailable'):
        coordinator.ingest(event())
    assert store.db.messages.count_documents({'platform_event_id': 'one'}) == 1
    with pytest.raises(Denied, match='CONTENT_CONFLICT'):
        chat.receive(event(text='changed'))


def test_persisted_current_and_future_inputs_do_not_leak_into_history(store):
    coordinator = Coordinator(store, FakeLane(store, responses()))
    first, _ = persist_input(store, event('first', 'first-input'), managed=True)
    second, _ = persist_input(store, event('second', 'second-input'), managed=True)
    _, context, _ = ContextBuilder(store).prepare(event('first', 'first-input'))
    assert not context['delivered_history']
    coordinator.ingest(event('first', 'first-input'))
    _, context, _ = ContextBuilder(store).prepare(event('second', 'second-input'))
    assert [m['text'] for m in context['delivered_history']] == ['first-input', 'public']


def test_restart_recovers_native_operation_receipt_without_new_generation(store, tmp_path):
    lane = FakeLane(store, responses())
    def crash(point):
        if point == 'after_lane_delivery':
            raise RuntimeError('simulated process interruption')
    coordinator = Coordinator(store, lane, crash=crash)
    persist_input(store, event(), managed=True)
    input_state(store, episode_id(event()), 'PROCESSING')
    with pytest.raises(RuntimeError, match='process interruption'):
        coordinator.ingest(event())
    assert len(lane.calls) == 1
    resumed = Coordinator(store, lane)
    chat = controller(store, tmp_path, resumed)
    chat.recover_inputs()
    chat.recover_inputs()
    assert chat.pending.qsize() == 1
    chat.worker.start()
    try:
        chat.pending.join()
        assert len(lane.calls) == 3  # The recorded first phase was reused.
        assert store.db.messages.count_documents({'direction': 'outbound', 'delivery_state': 'DELIVERED'}) == 1
        assert store.db.messages.find_one({'_id': 'in-' + episode_id(event())})['ingress_state'] == 'COMPLETE'
    finally:
        chat.stop()


def test_restart_does_not_run_input_after_policy_revocation(store, tmp_path):
    persist_input(store, event(), managed=True)
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.put('scenes', {**scene, 'policy_epoch': 2}, expected=scene['revision'])
    lane = FakeLane(store, [])
    chat = controller(store, tmp_path, Coordinator(store, lane))
    chat.recover_inputs()
    chat.worker.start()
    try:
        chat.pending.join()
        row = store.db.messages.find_one({'_id': 'in-' + episode_id(event())})
        assert row['ingress_state'] == 'FAILED' and 'INPUT_POLICY_STALE' in row['failure']
        assert not lane.calls
    finally:
        chat.stop()


def test_failed_preprocessing_resumes_original_input_without_rag_dependency(store,tmp_path):
    incoming=event('original-failure','原始目标')
    row,_=persist_input(store,incoming,managed=True)
    input_state(store,row['episode_id'],'FAILED',failure='prior retrieval TypeError')
    class BrokenRetrieval:
        def search(self,*args,**kwargs):raise TypeError('optional retrieval unavailable')
    lane=FakeLane(store,responses())
    coordinator=Coordinator(store,lane,context=ContextBuilder(store,BrokenRetrieval()))
    chat=controller(store,tmp_path,coordinator)
    chat.recover_inputs();chat.worker.start()
    try:
        chat.pending.join()
        saved=store.db.messages.find_one({'_id':row['_id']})
        assert saved['ingress_state']=='COMPLETE' and saved['text']=='原始目标'
        assert store.db.messages.count_documents({'platform_event_id':'original-failure'})==1
        context=store.db.episodes.find_one({'_id':row['episode_id']})['context']
        assert context['memories']==[] and 'optional retrieval unavailable' in context['retrieval_diagnostic_from_host']['error']
        assert context['prior_input_failure_from_host']=='prior retrieval TypeError'
        assert len(lane.calls)==3
    finally:chat.stop()


def test_resources_never_fall_back_to_owner_workspace(store):
    local = store.config['chat']
    assert workspace_grant(store.config, local['scene_id'], local['person_id']) == local
    assert workspace_grant(store.config, 'dm-b', 'B', required=False) == {}
    with pytest.raises(Denied, match='WORKSPACE_NOT_AUTHORIZED'):
        workspace_grant(store.config, 'dm-b', 'B')


def test_retrieval_handles_null_timestamps_and_large_authorized_scope(store,tmp_path):
    from asuna.retrieval import Retrieval
    retrieval=Retrieval(store,Evidence(tmp_path/'retrieval'))
    def unavailable(*args):raise RuntimeError('embedding unavailable in local check')
    retrieval.embed=unavailable
    base={'scope_key':'scene:dm-a','policy_epoch':1,'character_id':'xiaoman','status':'active','revision':1,'schema_version':1,
          'body_markdown':'历史材料','embedding_status':'PENDING','source_event_ids':[],'occurred_at':None}
    store.db.memory_units.insert_many([{**base,'_id':'null-'+str(i)} for i in range(4100)])
    try:
        rows,manifest=retrieval.search('scene:dm-a',1,'当前查询')
        assert manifest['lexical_candidate_count']==4096
        assert manifest['cache_disabled_for_bounded_sample']
        assert not manifest['vector_verified']
        assert all(m['scope_key'] in ('scene:dm-a','global-safe') for m in rows)
        assert store.db.memory_units.count_documents({'_id':{'$regex':'^null-'}})==4100
    finally:retrieval.close()


def test_scene_queue_is_ordered_and_does_not_starve_other_scene():
    queue = SceneQueue()
    for scene, sequence in [('A', 1), ('A', 2), ('A', 3), ('B', 1)]:
        queue.put(({'scene_id': scene}, sequence))
    received = []
    while not queue.empty():
        value, sequence = queue.get_nowait()
        received.append((value['scene_id'], sequence))
        queue.task_done()
    assert received == [('A', 1), ('A', 2), ('B', 1), ('A', 3)]
    assert queue.unfinished_tasks == 0


def test_feedback_recovers_receipt_and_keeps_original_platform_reply_target(store, tmp_path):
    from asuna.channels import Channels
    from asuna.tasks import TaskService
    target = {'type': 'dm', 'id': 'peer'}
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': 'dm-a', 'sender_id': 'peer', 'person_id': 'A', 'target': target}}}}
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.put('scenes', {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    decision = {'next': 'delegate', 'goal': 'check', 'constraints': [], 'recall_query': '', 'speak_before_action': False}
    lane = FakeLane(store, [LaneResult('private'), LaneResult(json.dumps(decision)), *responses()])
    coordinator = Coordinator(store, lane)
    incoming = {**event(), 'channel': {'id': 'replay', 'account_id': 'bot', 'target': target, 'platform_event_id': 'original-platform-id'}}
    persist_input(store, incoming, managed=True)
    episode = coordinator.ingest(incoming)
    service = TaskService(store)
    task = service.claim(episode['task_id'])
    store.put('artifacts', {'_id': 'observation', 'task_id': task['_id'], 'intent_revision': 1,
                           'scope_key': task['scope_key'], 'state': 'DONE'})
    task = service.finish(task, {'task_id': task['_id'], 'intent_revision': 1, 'status': 'done',
            'facts': [{'text': 'controlled replay result', 'evidence_refs': ['observation']}],
            'artifact_refs': ['observation'], 'effect_receipts': [], 'uncertainties': [],
            'unmet_items': [], 'needs_decision': None})
    def crash(point):
        if point == 'after_lane_delivery':
            raise RuntimeError('feedback interrupted')
    coordinator.crash = crash
    with pytest.raises(RuntimeError, match='feedback interrupted'):
        service.feedback(task, coordinator)
    coordinator.crash = lambda _: None
    feedback = service.feedback(task, coordinator)
    assert feedback['state'] == 'COMMITTED' and len(lane.calls) == 5
    chat = controller(store, tmp_path, coordinator)
    channels = Channels(chat)
    item = channels.claim('replay')['items'][0]
    assert item['reply_to'] == 'original-platform-id' and item['target'] == target
    assert item['text'] == 'public'
    assert not store.db.sink_receipts.count_documents({})
