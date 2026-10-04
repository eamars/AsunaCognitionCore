"""Workspace mode contracts; C2 live evidence is separate from these test doubles."""
import json
import uuid

import pytest

from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.evidence import sha
from asuna.lanes import FakeLane, LaneResult
from asuna.state import Denied
from asuna.tasks import TaskService, ToolBroker, Executor


def setup_workspace(store):
    work = ROOT / '.runtime/work' / ('workspace-test-' + uuid.uuid4().hex)
    (work / 'notes').mkdir(parents=True)
    (work / 'notes/source.txt').write_text('原文保持不变', encoding='utf-8')
    store.config.update(task_mode='workspace', chat={**store.config['chat'], 'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(work), 'read_only_paths': ['notes']})
    decision = {'next': 'delegate', 'goal': '另写便条', 'constraints': ['保留原文'], 'recall_query': '', 'speak_before_action': False}
    coordinator = Coordinator(store, FakeLane(store, [LaneResult('先读再写。'), LaneResult(json.dumps(decision))]))
    ep = coordinator.ingest({'event_id': 'workspace-task', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '根据原文另写一份便条。'})
    service = TaskService(store)
    return work, ep, service, ToolBroker(service)


def test_generic_files_protect_sources_and_leave_original_traceback(store):
    work, ep, service, broker = setup_workspace(store)
    try:
        task = service.claim(ep['task_id'])
        broker.bind('workspace', task, work)
        failed = broker.call('workspace', 'protected', 'write_file', {'path': 'notes/source.txt', 'text': '不应写入', 'overwrite': True})
        assert failed['error'] == 'TASK_OPERATION_FAILED'
        assert 'Read-only file system' in failed['execution']['stderr']
        assert 'Traceback' in failed['execution']['stderr']
        assert (work / 'notes/source.txt').read_text(encoding='utf-8') == '原文保持不变'
        result = broker.call('workspace', 'new', 'write_file', {'path': '普通便条.txt', 'text': '这不是 stats.py'})
        assert result['written']
        assert (work / '普通便条.txt').read_text(encoding='utf-8') == '这不是 stats.py'
        # ADR-008 closes actions through the native turn result. A retired
        # business status tool cannot grant authority or terminate the task.
        with pytest.raises(Denied, match='CAPABILITY_DENIED'):
            broker.call('workspace', 'end', 'task_status', {'status': 'done'})
        current=store.db.tasks.find_one({'_id':task['_id']})
        assert current['state'] == 'RUNNING'
        store.put('tasks',{**current,'tool_steps':64},expected=current['revision'])
        broker.call('workspace', 'after-status', 'write_file', {'path': 'late.txt', 'text': 'continued'})
        assert (work / 'late.txt').read_text() == 'continued'
    finally:
        broker.close()


def test_executor_accepts_natural_language_and_attaches_actual_receipts(store):
    work, ep, service, broker = setup_workspace(store)
    narrative = '便条已单独写好，原文仍在。附带说明也属于自然语言，不会因为多了一个字段而丢掉结果。'

    class ActionLane:
        def generate(self, binding, operation, phase, text, system):
            assert 'result_schema' not in text
            session = 's-' + sha(binding.encode())[:40]
            broker.call(session, 'read', 'read_file', {'path': 'notes/source.txt'})
            broker.call(session, 'write', 'write_file', {'path': '便条.txt', 'text': '原文保持不变'})
            return LaneResult(narrative)

    try:
        done = Executor(service, ActionLane(), broker).run(ep['task_id'], work)
        assert done['state'] == 'RETURNED' and done['result']['finish_reason'] == 'stop'
        assert 'declared_status' not in done['result']
        fact = done['result']['facts'][0]
        assert fact['text'] == narrative
        for ref in fact['evidence_refs']:
            assert store.db.artifacts.find_one({'_id': ref, 'task_id': done['_id'], 'state': 'DONE'})
        assert (work / '便条.txt').read_text(encoding='utf-8') == '原文保持不变'
        decision={'next':'delegate','goal':'继续这份便条','constraints':[],'recall_query':'','speak_before_action':False,'continue_task_id':done['_id']}
        follow=Coordinator(store,FakeLane(store,[LaneResult('继续原会话'),LaneResult(json.dumps(decision))])).ingest(
            {'event_id':'continue','scene_id':'dm-a','person_id':'A','text':'继续刚才的工作'})
        continuation=store.db.tasks.find_one({'_id':follow['task_id']})
        assert continuation['execution_binding']==f"task:{done['_id']}:{done['scope_key']}:{done['policy_epoch']}:{done['intent_revision']}"
    finally:
        broker.close()


def test_only_explicit_current_scene_decision_can_cancel_task(store):
    work, ep, service, broker = setup_workspace(store)
    try:
        task = service.claim(ep['task_id'])
        broker.bind('workspace', task, work)
        cancel = {'next': 'speak', 'goal': '停止用户叫停的任务', 'constraints': [], 'recall_query': '',
                  'speak_before_action': False, 'cancel_task_id': task['_id']}
        lane = FakeLane(store, [LaneResult('尊重当前用户撤销。'), LaneResult(json.dumps(cancel)), LaneResult('已停下。')])
        result = Coordinator(store, lane).ingest({'event_id': 'cancel-task', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '刚才的任务先停下。'})
        assert result['state'] == 'COMMITTED'
        assert result['control_result']['actual_state'] == 'CANCELLED'
        with pytest.raises(Denied, match='STALE_TASK_FENCE'):
            broker.call('workspace', 'late', 'write_file', {'path': 'late.txt', 'text': 'late'})
        foreign_lane = FakeLane(store, [LaneResult('不具备这个任务的上下文。'), LaneResult(json.dumps(cancel))])
        with pytest.raises(Denied, match='CANCEL_TASK_NOT_IN_CURRENT_CONTEXT'):
            Coordinator(store, foreign_lane).ingest({'event_id': 'foreign-cancel', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '停止别人的任务。'})
    finally:
        broker.close()


@pytest.mark.parametrize('internal', [False, True])
def test_restart_paused_task_can_only_continue_from_new_local_request(store, internal):
    work, ep, service, broker = setup_workspace(store)
    try:
        task = service.claim(ep['task_id'])
        paused = service.pause_for_restart(task['_id'])
        decision = {'next': 'delegate', 'goal': '继续原目标', 'constraints': [], 'recall_query': '',
                    'speak_before_action': False, 'continue_task_id': task['_id']}
        lane = FakeLane(store, [LaneResult('核实暂停记录'), LaneResult(json.dumps(decision)),
                               LaneResult('旧行动仍暂停。')])
        incoming = {'event_id': 'paused-continue', 'scene_id': 'dm-a', 'person_id': 'A',
                    'text': '继续之前暂停的工作'}
        if internal:
            incoming.update(episode_kind='self_development', adapter_id='self-development')
        result = Coordinator(store, lane).ingest(incoming)
        assert store.db.tasks.find_one({'_id': task['_id']})['state'] == 'PAUSED'
        assert 'PAUSED 是重启后等待操作者决定' in lane.calls[0]['messages'][-1]['content']
        if internal:
            assert result['state'] == 'COMMITTED' and result['control_result']['accepted'] is False
            assert store.db.tasks.count_documents({}) == 1
        else:
            continuation = store.db.tasks.find_one({'_id': result['task_id']})
            assert continuation['continues_task_id'] == task['_id']
            assert continuation['execution_binding'] == paused['execution_binding']
            assert continuation['state'] == 'READY'
    finally:
        broker.close()


@pytest.mark.parametrize('running', [False, True])
def test_character_redirects_live_task_in_place_and_fences_prior_revision(store, running):
    work, first, service, broker = setup_workspace(store)
    try:
        task = service.claim(first['task_id']) if running else store.db.tasks.find_one({'_id': first['task_id']})
        notices = []
        service.on_fenced = lambda row, reason: notices.append((row['_id'], row['intent_revision'], reason))
        decision = {'next':'delegate','goal':'保留原文，先核对另一份','constraints':['只读'],
                    'recall_query':'','speak_before_action':False,'continue_task_id':task['_id']}
        role = Coordinator(store, FakeLane(store, [LaneResult('按新要求继续原行动。'), LaneResult(json.dumps(decision))]), task_service=service)
        event = {'event_id':'redirect-live','scene_id':'dm-a','person_id':'A','text':'继续刚才的工作，优先核对另一份。'}
        revised = role.ingest(event)
        current = store.db.tasks.find_one({'_id':task['_id']})
        assert revised['state']=='WAITING_TASK' and revised['task_id']==task['_id']
        assert current['state']=='READY' and current['intent_revision']==2 and current['goal']==decision['goal']
        assert current['execution_binding']==f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:1"
        assert store.db.tasks.count_documents({})==1 and notices==[(task['_id'],2,'task_revised')]
        with pytest.raises(Denied,match='STALE_TASK_FENCE'):service.valid(task)
        role.ingest(event)
        assert store.db.tasks.find_one({'_id':task['_id']})['intent_revision']==2 and len(notices)==1
    finally:
        broker.close()


