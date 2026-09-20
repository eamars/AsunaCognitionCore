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
    store.config.update(task_mode='workspace', chat={**store.config['chat'], 'workspace': str(work), 'read_only_paths': ['notes']})
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
        broker.call('workspace', 'end', 'task_status', {'status': 'done'})
        with pytest.raises(Denied, match='TASK_ALREADY_REPORTED'):
            broker.call('workspace', 'too-late', 'write_file', {'path': 'late.txt', 'text': 'late'})
        assert not (work / 'late.txt').exists()
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
            broker.call(session, 'status', 'task_status', {'status': 'done'})
            return LaneResult(narrative)

    try:
        done = Executor(service, ActionLane(), broker).run(ep['task_id'], work)
        assert done['state'] == 'DONE'
        fact = done['result']['facts'][0]
        assert fact['text'] == narrative
        for ref in fact['evidence_refs']:
            assert store.db.artifacts.find_one({'_id': ref, 'task_id': done['_id'], 'state': 'DONE'})
        assert (work / '便条.txt').read_text(encoding='utf-8') == '原文保持不变'
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
