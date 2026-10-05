"""Host contracts on isolated Mongo; fake model receipts, never real QQ sends."""
import json
import os
from queue import Queue
import threading
from types import SimpleNamespace

import pytest

from asuna.chat import Chat, SceneQueue
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.ingress import persist_input, input_state, episode_id
from asuna.host import RuntimeHost, _workspace_overlaps
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.grants import workspace_grant
from asuna.router import Router
from asuna.state import Conflict, Denied
from fixture_grant import returned


def event(key='one', text='input'):
    return {'event_id': key, 'scene_id': 'dm-a', 'person_id': 'A', 'text': text}


def test_workspace_overlap_check_preserves_ancestor_and_sibling_rules(tmp_path):
    root = tmp_path.resolve()
    existing = [root / 'local', root / 'channels' / 'member-0', root / 'channels' / 'member' / 'child']
    ordered = sorted(os.path.normcase(str(path)) for path in existing)
    known = set(ordered)
    for candidate in [root / 'channels' / 'member', root / 'channels' / 'member' / 'child' / 'next',
                      root / 'local' / 'nested', root / 'channels']:
        assert _workspace_overlaps(candidate, ordered, known)
    for candidate in [root / 'channels' / 'member-1', root / 'channels' / 'other']:
        assert not _workspace_overlaps(candidate, ordered, known)


def test_restart_waits_for_active_action_but_not_durable_queue():
    recorded = []
    evidence = SimpleNamespace(record=lambda kind, payload: recorded.append(kind))
    host = RuntimeHost({}, evidence)
    host.app = SimpleNamespace(store=SimpleNamespace(db=SimpleNamespace(
        sink_receipts=SimpleNamespace(find_one=lambda query: {'_id': 'publish-receipt'}))))
    queue = Queue()
    queue.put(('queued-task', 1))
    host.controller = SimpleNamespace(active=None, active_task='running-task', pending=Queue(),
                                      task_queue=queue, state_lock=threading.Lock(),
                                      restart_pending=host.restart_pending)
    host._maybe_restart_after_publish()
    assert host.restart_pending.is_set() and not host.restart_requested.is_set()
    assert recorded == ['restart.pending', 'restart.blocked']
    host.controller.active_task = None
    host._maybe_restart_after_publish()
    assert host.restart_requested.is_set() and host.shutdown_requested.is_set()
    assert not queue.empty() and recorded[-1] == 'restart.requested'



def test_a_restarted_native_worker_does_not_restart_again_for_the_publication_it_is_loading():
    """Regression: a worker restarted for a publication saw that publication still APPLIED during its own
    startup (the Host reports what it loaded only after initialization), asked for another restart, stopped
    taking work, and the Host, still restarting, never honored it: every later input waited forever."""
    recorded = []
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: recorded.append(kind)), awaits_activation=True)
    host.app = SimpleNamespace(store=SimpleNamespace(db=SimpleNamespace(
        sink_receipts=SimpleNamespace(find_one=lambda query: {'_id': 'publish-receipt'}))))
    host.controller = SimpleNamespace(active=None, active_task=None, pending=Queue(), task_queue=Queue(),
                                      state_lock=threading.Lock(), restart_pending=host.restart_pending)
    host._maybe_restart_after_publish()
    assert not host.restart_pending.is_set() and not host.shutdown_requested.is_set() and recorded == []
    host.activation_settled.set()          # publication.activated: what is APPLIED now is a new publication
    host._maybe_restart_after_publish()
    assert host.restart_requested.is_set() and recorded == ['restart.pending', 'restart.requested']

def test_after_every_turn_the_host_also_checks_her_heartbeat():
    host = RuntimeHost({}, SimpleNamespace(record=lambda kind, payload: None))
    host.app = SimpleNamespace(store=SimpleNamespace(db=SimpleNamespace(
        sink_receipts=SimpleNamespace(find_one=lambda query: None))))
    watched = []
    host.schedule = SimpleNamespace(watch_rhythm=lambda: watched.append('checked'))
    host._after_turn()
    assert watched == ['checked']


def think(thought='private'):
    return ('think', {'thought': thought})


def responses():
    """One ordinary character turn: her private thought, then the public speech."""
    return [FakeTurn([think()], 'public')]


def delegating(thought='original', title='inspect'):
    """A turn that hands work to the action brain and says nothing yet."""
    return FakeTurn([think(thought), ('delegate', {'title': title, 'brief': title + ' the controlled fixture'}),
                     ('stay_silent', {'reason': 'wait for the result'})])


def controller(store, tmp_path, coordinator):
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=coordinator.character, router=Router(store, coordinator))
    return Chat(app, {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': 'test'}, lambda _: None)


def test_receive_persists_without_context_or_worker_and_dedupes(store, tmp_path):
    class UnavailableContext:
        def prepare(self, *args, **kwargs):
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


def test_reply_history_identifies_recipient_without_cross_scene_lookup(store):
    incoming = event('reply', 'Have you replied to @B?')
    incoming['group_context'] = {'reply_to':'answer-id', 'reply_message_id':'answer',
                                 'mentioned_account_ids':['bot','B']}
    # Same platform ID in another scene must not supply the reply's author/body.
    store.put('messages', {'_id':'foreign','scene_id':'dm-b','scope_key':'scene:dm-b',
        'policy_epoch':1,'direction':'inbound','author':'B','text':'private canary',
        'event':{'channel':{'platform_event_id':'question-id'}}})
    store.put('messages', {'_id':'question','scene_id':'dm-a','scope_key':'scene:dm-a',
        'policy_epoch':1,'scene_seq':1,'direction':'inbound','author':'A','text':'my question',
        'event':{'channel':{'platform_event_id':'question-id'}}})
    store.put('messages', {'_id':'answer','scene_id':'dm-a','scope_key':'scene:dm-a',
        'policy_epoch':1,'scene_seq':2,'direction':'outbound','author':'demo','text':'my answer',
        'delivery_state':'DELIVERED','platform_message_id':'answer-id','platform_reply_to':'question-id'})
    _, context, _ = ContextBuilder(store).prepare(incoming)
    answer = next(row for row in context['delivered_history'] if row['_id']=='answer')
    question = next(row for row in context['delivered_history'] if row['_id']=='question')
    assert 'author' not in answer['reply_to_message'] and answer['reply_to_message']['speaker']==question['speaker']
    assert answer['reply_to_message']['text']=='my question'
    assert context['group_continuity_from_program']['related_messages'][0]['reply_to_message']==answer['reply_to_message']
    assert 'private canary' not in json.dumps(context)


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
    assert len(lane.calls) == 1 and store.db.lane_receipts.count_documents({}) == 1
    resumed = Coordinator(store, lane)
    chat = controller(store, tmp_path, resumed)
    chat.recover_inputs()
    chat.recover_inputs()
    assert chat.pending.qsize() == 1
    chat.worker.start()
    try:
        chat.pending.join()
        assert len(lane.calls) == 1  # The recorded turn's receipt was reused; no new generation.
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
        assert len(lane.calls)==1
    finally:chat.stop()


def test_resources_never_fall_back_to_owner_workspace(store):
    local = store.config['chat']
    assert workspace_grant(store.config, local['scene_id'], local['person_id']) == local
    assert workspace_grant(store.config, 'dm-b', 'B', required=False) == {}
    with pytest.raises(Denied, match='WORKSPACE_NOT_AUTHORIZED'):
        workspace_grant(store.config, 'dm-b', 'B')


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


def channel_feedback(store):
    """A delegation from a channel DM whose task has returned; (coordinator, lane, service, task, target)."""
    from asuna.tasks import TaskService
    target = {'type': 'dm', 'id': 'peer'}
    work = store.config['channels']['fixture']['routes']['dm-a']['workspace']
    store.config['channels'] = {'replay': {'token': 'x' * 32, 'account_id': 'bot', 'routes': {
        'peer': {'scene_id': 'dm-a', 'sender_id': 'peer', 'person_id': 'A', 'target': target, 'workspace': work}}}}
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    store.put('scenes', {**scene, 'channel_id': 'replay'}, expected=scene['revision'])
    lane = FakeLane(store, [delegating('private', 'check'), *responses()])
    coordinator = Coordinator(store, lane)
    incoming = {**event(), 'channel': {'id': 'replay', 'account_id': 'bot', 'target': target, 'platform_event_id': 'original-platform-id'}}
    persist_input(store, incoming, managed=True)
    episode = coordinator.ingest(incoming)
    service = TaskService(store)
    task = service.claim(episode['task_ids'][0])
    store.put('artifacts', {'_id': 'observation', 'task_id': task['_id'], 'intent_revision': 1, 'tool': 'read_file',
                           'result': {'text': 'observed'}, 'scope_key': task['scope_key'], 'state': 'DONE'})
    return coordinator, lane, service, returned(store, task, 'controlled replay result', ['observation']), target


def assert_feedback_replies_to_the_original_platform_event(store, tmp_path, coordinator, target):
    from asuna.channels import Channels
    chat = controller(store, tmp_path, coordinator)
    item = Channels(chat).claim('replay')['items'][0]
    assert item['reply_to'] == 'original-platform-id' and item['target'] == target
    assert item['text'] == 'public'
    assert not store.db.sink_receipts.count_documents({})


def test_feedback_recovers_receipt_and_keeps_original_platform_reply_target(store, tmp_path):
    coordinator, lane, service, task, target = channel_feedback(store)
    def crash(point):
        if point == 'after_lane_delivery':
            raise RuntimeError('feedback interrupted')
    coordinator.crash = crash
    with pytest.raises(RuntimeError, match='feedback interrupted'):
        service.feedback(task, coordinator)
    coordinator.crash = lambda _: None
    # The feedback turn's recorded receipt answers the retry: no new generation (the lane has no third turn).
    feedback = service.feedback(task, coordinator)
    assert feedback['state'] == 'COMMITTED' and len(lane.calls) == 2
    assert_feedback_replies_to_the_original_platform_event(store, tmp_path, coordinator, target)


def test_feedback_reply_keeps_original_platform_reply_target(store, tmp_path):
    """The reply-target half of the test above, without the interruption, so it stays guarded."""
    coordinator, lane, service, task, target = channel_feedback(store)
    feedback = service.feedback(task, coordinator)
    assert feedback['state'] == 'COMMITTED' and len(lane.calls) == 2
    assert_feedback_replies_to_the_original_platform_event(store, tmp_path, coordinator, target)


def test_returned_task_feedback_queue_continues_failed_role_stage_without_new_episode(store,tmp_path):
    import time
    from asuna.tasks import TaskService
    # The feedback turn stops before it is finished (not her mistake): FAILED_PROTOCOL, then the
    # queue continues the same episode in a resumed turn that carries the original error.
    lane=FakeLane(store,[delegating('original thought','inspect evidence'),
        LaneResult('incomplete',finish_reason='max-tokens'),
        FakeTurn([think('我先核对已返回的结果。')],'结果已核对。')])
    coordinator=Coordinator(store,lane)
    episode=coordinator.ingest(event('feedback-source'))
    service=TaskService(store)
    task=service.claim(episode['task_ids'][0])
    store.put('artifacts',{'_id':'feedback-observation','task_id':task['_id'],'tool':'read_file','result':{'text':'observed'},
        'intent_revision':1,'scope_key':task['scope_key'],'state':'DONE'})
    task=returned(store,task,'verified',['feedback-observation'])
    chat=controller(store,tmp_path,coordinator)
    chat.app.service=service
    chat.app.coordinator=coordinator
    chat.worker.start()
    chat.pending.put(({'_feedback_task':task['_id'],'event_id':task['_id']+':feedback',
        'scene_id':task['scene_id'],'person_id':task['requester_id']},episode['_id']))
    deadline=time.monotonic()+5
    try:
        while time.monotonic()<deadline:
            current=store.db.tasks.find_one({'_id':task['_id']})
            if current.get('feedback_state')=='DELIVERED':break
            time.sleep(.05)
        else: pytest.fail('original feedback did not continue through the queue')
    finally:
        chat.stopping.set()
        chat.worker.join(timeout=5)
    resumed=store.db.episodes.find_one({'_id':current['feedback_episode']})
    assert resumed['state']=='COMMITTED'
    assert store.db.audit_events.count_documents({'stream_id':resumed['_id'],'type':'phase.failed'})==1
    assert store.db.audit_events.count_documents({'stream_id':resumed['_id'],'type':'feedback.continued'})==1
    assert resumed['turn_generation']==1
    assert store.db.tasks.count_documents({})==1
    assert store.db.messages.count_documents({'episode_id':resumed['_id'],'direction':'inbound'})==1
    assert store.db.messages.count_documents({'episode_id':resumed['_id'],'direction':'outbound'})==1
    assert store.db.episodes.find_one({'_id':episode['_id']})['state']=='COMMITTED'
    assert len(lane.calls)==3
    assert [call['phase'] for call in lane.calls]==['TURN','TURN','TURN']
    assert lane.calls[2]['messages'][0]==lane.calls[1]['messages'][0]
    # The resumed turn continues the same episode: its note names the original error, not a new instruction.
    resumed_note=lane.calls[2]['messages'][-1]['content']
    assert '宿主上次中断了这一回合（不是新的用户指令' in resumed_note and 'TURN_NOT_FINISHED' in resumed_note
    assert 'TURN_NOT_FINISHED' not in lane.calls[1]['messages'][-1]['content']
    # Same episode, same prepared context: the result is not ingested again as a new input.
    assert resumed_note.split('\n',1)[0]==lane.calls[1]['messages'][-1]['content'].split('\n',1)[0]
    receipts=[row['_id'] for row in store.db.lane_receipts.find({'_id':{'$regex':'^'+resumed['_id']}}).sort('_id',1)]
    assert receipts==[resumed['_id']+':TURN',resumed['_id']+':TURN:resume:1']


@pytest.mark.parametrize('invalidate', ['cancel', 'pause'])
def test_inflight_feedback_stops_after_task_authority_is_withdrawn(store, invalidate):
    from concurrent.futures import ThreadPoolExecutor
    from asuna.tasks import TaskService
    entered, released = threading.Event(), threading.Event()
    class PausedLane(FakeLane):
        def generate(self, *args, **kwargs):
            result = super().generate(*args, **kwargs)
            if len(self.calls) == 2:
                entered.set()
                assert released.wait(5)
            return result
    lane = PausedLane(store, [delegating(),
        FakeTurn([think('late feedback thought')], 'must not be published'),
        FakeTurn([think('must not be generated')], 'must not be generated')])
    coordinator = Coordinator(store, lane)
    original = coordinator.ingest(event('inflight-feedback'))
    service = TaskService(store)
    task = service.claim(original['task_ids'][0])
    store.put('artifacts', {'_id': 'feedback-observation', 'task_id': task['_id'], 'tool': 'read_file',
        'result': {'text': 'observed'}, 'intent_revision': 1, 'scope_key': task['scope_key'], 'state': 'DONE'})
    task = returned(store, task, 'checked', ['feedback-observation'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.feedback, task, coordinator)
        try:
            assert entered.wait(5)
            if invalidate == 'cancel':
                service.cancel(task['_id'], operator=True)
            else:
                service.pause_for_restart(task['_id'])
        finally:
            released.set()
        feedback = pending.result(timeout=5)
    current = store.db.tasks.find_one({'_id': task['_id']})
    assert feedback['state'] == 'SUPPRESSED'
    assert current['state'] == ('CANCELLED' if invalidate == 'cancel' else 'PAUSED')
    assert current['feedback_state'] == ('SUPPRESSED' if invalidate == 'cancel' else 'PAUSED')
    assert [call['phase'] for call in lane.calls[1:]] == ['TURN']
    assert store.db.messages.count_documents({'direction': 'outbound'}) == 0
    assert store.db.tasks.count_documents({}) == 1
    assert store.db.lane_receipts.count_documents({}) == 2, 'retain the actual in-flight output'
    assert coordinator.advance(feedback['_id'])['state'] == 'SUPPRESSED'
    assert len(lane.calls) == 2


@pytest.mark.parametrize('state', ['READY', 'RUNNING', 'RETURNED'])
def test_host_restart_pauses_unfinished_actions_and_never_queues_old_feedback(store, tmp_path, state):
    from asuna.tasks import TaskService
    lane = FakeLane(store, [delegating()])
    coordinator = Coordinator(store, lane)
    incoming = event('restart-action')
    persist_input(store, incoming, managed=True)
    original = coordinator.ingest(incoming)
    service = TaskService(store)
    task = store.db.tasks.find_one({'_id': original['task_ids'][0]})
    if state != 'READY':
        task = service.claim(task['_id'])
    if state == 'RETURNED':
        task = store.put('tasks', {**task, 'state': 'RETURNED', 'feedback_state': 'READY',
            'result': {'facts': [{'text': 'existing result'}]}}, expected=task['revision'])
    chat = controller(store, tmp_path, coordinator)
    chat.app.service = service
    entries = []
    service.on_collab = lambda task, entry: entries.append((task['_id'], entry))
    host = RuntimeHost(store.config, chat.app.evidence)
    host.app, host.controller = chat.app, chat
    host._recover_tasks()
    paused = store.db.tasks.find_one({'_id': task['_id']})
    assert paused['state'] == 'PAUSED' and paused['paused_state'] == state
    # Her thread says so, rather than still reading as queued or running.
    assert [(task_id, entry['kind'], entry['state']) for task_id, entry in entries] == [(task['_id'], 'status', 'paused')]
    assert paused['feedback_state'] == 'PAUSED'
    assert paused['fencing_token'] > task['fencing_token']
    assert paused.get('result') == task.get('result')
    assert chat.pending.empty() and chat.task_queue.empty() and len(lane.calls) == 1
    host._recover_tasks()
    assert store.db.tasks.find_one({'_id': task['_id']})['revision'] == paused['revision']


def test_restart_reconciles_delivered_feedback_without_pausing_completed_work(store, tmp_path):
    from asuna.tasks import TaskService
    coordinator = Coordinator(store, FakeLane(store, [delegating()]))
    incoming = event('completed-feedback')
    persist_input(store, incoming, managed=True)
    original = coordinator.ingest(incoming)
    assert original['state'] == 'WAITING_TASK'
    task = store.db.tasks.find_one({'_id': original['task_ids'][0]})
    store.put('episodes', {'_id': 'finished-feedback', 'state': 'COMMITTED'})
    task = store.put('tasks', {**task, 'state': 'RETURNED', 'feedback_state': 'DELIVERED',
        'feedback_episode': 'finished-feedback'}, expected=task['revision'])
    chat = controller(store, tmp_path, coordinator)
    chat.app.service = TaskService(store)
    host = RuntimeHost(store.config, chat.app.evidence)
    host.app, host.controller = chat.app, chat
    host._recover_tasks()
    assert store.db.tasks.find_one({'_id': task['_id']})['state'] == 'RETURNED'
    assert store.db.episodes.find_one({'_id': original['_id']})['state'] == 'COMMITTED'
    assert chat.pending.empty() and chat.task_queue.empty()
