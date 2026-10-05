"""Workspace mode contracts; C2 live evidence is separate from these test doubles."""
import uuid

import pytest

from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.evidence import sha
from asuna.lanes import FakeLane, FakeTurn, LaneResult
from asuna.state import Denied
from asuna.tasks import TaskService, ToolBroker, Executor


THINK = ('think', {'thought': '先读原文再写，原文要保留。'})
BRIEF = '根据 notes/source.txt 另写一份便条；保留原文，不改原文。'


def setup_workspace(store):
    work = ROOT / '.runtime/work' / ('workspace-test-' + uuid.uuid4().hex)
    (work / 'notes').mkdir(parents=True)
    (work / 'notes/source.txt').write_text('原文保持不变', encoding='utf-8')
    store.config.update(task_mode='workspace', chat={**store.config['chat'], 'scene_id': 'dm-a', 'person_id': 'A', 'workspace': str(work), 'read_only_paths': ['notes']})
    turn = FakeTurn([THINK, ('delegate', {'title': '另写便条', 'brief': BRIEF})], '先读再写。')
    coordinator = Coordinator(store, FakeLane(store, [turn]))
    ep = coordinator.ingest({'event_id': 'workspace-task', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '根据原文另写一份便条。'})
    service = TaskService(store)
    return work, ep, service, ToolBroker(service)


def test_generic_files_protect_sources_and_leave_original_traceback(store):
    work, ep, service, broker = setup_workspace(store)
    try:
        task = service.claim(ep['task_ids'][0])
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
    first_messages = []

    class ActionLane:
        def generate(self, binding, operation, phase, text, system, **kwargs):
            first_messages.append(text)
            assert 'result_schema' not in text
            session = 's-' + sha(binding.encode())[:40]
            broker.call(session, 'read', 'read_file', {'path': 'notes/source.txt'})
            broker.call(session, 'write', 'write_file', {'path': '便条.txt', 'text': '原文保持不变'})
            return LaneResult(narrative)

    try:
        done = Executor(service, ActionLane(), broker).run(ep['task_ids'][0], work)
        # ADR-011 §4: the action brain's first message is her brief; the program's facts follow, marked as such.
        assert first_messages[0].startswith(BRIEF) and '—— 程序附注（不是她说的话）——' in first_messages[0]
        assert done['state'] == 'RETURNED' and done['result']['finish_reason'] == 'stop'
        assert 'declared_status' not in done['result']
        fact = done['result']['facts'][0]
        assert fact['text'] == narrative
        for ref in fact['evidence_refs']:
            assert store.db.artifacts.find_one({'_id': ref, 'task_id': done['_id'], 'state': 'DONE'})
        assert (work / '便条.txt').read_text(encoding='utf-8') == '原文保持不变'
        # Her message to the finished task continues it in the same action session.
        turn = FakeTurn([THINK, ('message_action', {'task': done['_id'], 'message': '继续这份便条'})], '继续原会话')
        follow = Coordinator(store, FakeLane(store, [turn])).ingest(
            {'event_id':'continue','scene_id':'dm-a','person_id':'A','text':'继续刚才的工作'})
        continuation = store.db.tasks.find_one({'_id': follow['task_ids'][0]})
        assert continuation['continues_task_id'] == done['_id'] and continuation['brief'] == '继续这份便条'
        assert continuation['execution_binding']==f"task:{done['_id']}:{done['scope_key']}:{done['policy_epoch']}:{done['intent_revision']}"
    finally:
        broker.close()


def test_only_explicit_current_scene_decision_can_cancel_task(store):
    work, ep, service, broker = setup_workspace(store)
    try:
        task = service.claim(ep['task_ids'][0])
        broker.bind('workspace', task, work)
        stop = ('stop_action', {'task': task['_id'], 'reason': '他说刚才的任务先停下'})
        # Another conversation without tasks of its own has no stop_action at all.
        foreign = FakeLane(store, [FakeTurn([THINK, stop], '这不是我能停的。')])
        other = Coordinator(store, foreign).ingest({'event_id': 'foreign-cancel', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '停止别人的任务。'})
        assert 'stop_action' not in foreign.calls[0]['tools'] and foreign.tool_results[1][4:] == ('NOT_EXPOSED', False)
        assert other['state'] == 'COMMITTED'
        # With a task of its own it has the tool, but naming another conversation's task is refused in words.
        store.config['channels']['fixture']['routes']['dm-b'] = {'scene_id': 'dm-b', 'sender_id': 'B', 'person_id': 'B',
            'target': {'type': 'dm', 'id': 'B'}, 'workspace': str(work), 'read_only_paths': ['notes']}
        foreign = FakeLane(store, [FakeTurn([THINK, ('delegate', {'title': '自己的事', 'brief': '看看工作区里有什么文件。'})], '我去看看。'),
                                   FakeTurn([THINK, stop], '我只能管这里的事。')])
        other = Coordinator(store, foreign)
        own = other.ingest({'event_id': 'foreign-own', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '看看工作区。'})
        other = other.ingest({'event_id': 'foreign-stop', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '也停掉 A 的任务。'})
        assert own['state'] == 'WAITING_TASK' and 'stop_action' in foreign.calls[1]['tools']
        refused = foreign.tool_results[-1]
        assert refused[2] == 'stop_action' and not refused[5] and '不是这个对话里的任务' in refused[4]
        assert other['state'] == 'COMMITTED'
        assert store.db.tasks.find_one({'_id': task['_id']})['state'] == 'RUNNING'
        # Her explicit stop in the task's own conversation cancels and fences it.
        lane = FakeLane(store, [FakeTurn([THINK, stop], '已停下。')])
        result = Coordinator(store, lane).ingest({'event_id': 'cancel-task', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '刚才的任务先停下。'})
        assert result['state'] == 'COMMITTED'
        assert lane.tool_results[1][5] and lane.tool_results[1][4]['state'] == 'CANCELLED'
        assert store.db.tasks.find_one({'_id': task['_id']})['cancel_reason'] == 'character_stop'
        with pytest.raises(Denied, match='STALE_TASK_FENCE'):
            broker.call('workspace', 'late', 'write_file', {'path': 'late.txt', 'text': 'late'})
    finally:
        broker.close()


@pytest.mark.parametrize('internal', [False, True])
def test_restart_paused_task_can_only_continue_from_new_local_request(store, internal):
    work, ep, service, broker = setup_workspace(store)
    try:
        task = service.claim(ep['task_ids'][0])
        paused = service.pause_for_restart(task['_id'])
        turn = FakeTurn([THINK, ('message_action', {'task': task['_id'], 'message': '继续原目标，先核实已有结果。'})],
                        '旧行动仍暂停。')
        lane = FakeLane(store, [turn])
        incoming = {'event_id': 'paused-continue', 'scene_id': 'dm-a', 'person_id': 'A',
                    'text': '继续之前暂停的工作'}
        if internal:
            incoming.update(episode_kind='self_development', adapter_id='self-development')
        result = Coordinator(store, lane).ingest(incoming)
        assert store.db.tasks.find_one({'_id': task['_id']})['state'] == 'PAUSED'
        assert 'PAUSED 是重启后等待操作者决定' in lane.calls[0]['messages'][-1]['content']
        _, _, tool, _, outcome, ok = lane.tool_results[1]
        assert tool == 'message_action'
        if internal:
            assert not ok and '只有本机主人明确要继续时才能接着做' in outcome
            assert result['state'] == 'COMMITTED' and not result.get('task_ids')
            assert store.db.tasks.count_documents({}) == 1
        else:
            assert ok
            continuation = store.db.tasks.find_one({'_id': result['task_ids'][0]})
            assert continuation['continues_task_id'] == task['_id']
            assert continuation['execution_binding'] == paused['execution_binding']
            assert continuation['state'] == 'READY'
    finally:
        broker.close()


@pytest.mark.parametrize('running', [False, True])
def test_her_message_reaches_a_live_task_in_place_without_a_new_revision(store, running):
    """ADR-011 §4: message_action to a READY/RUNNING task is steered into its action session, not a revision."""
    work, first, service, broker = setup_workspace(store)
    task = store.db.tasks.find_one({'_id': first['task_ids'][0]})
    message = '优先核对另一份；原文仍然只读。'
    notices, steered, seen, said = [], [], [], {}
    service.on_fenced = lambda row, reason: notices.append((row['_id'], row['intent_revision'], reason))
    turn = FakeTurn([THINK, ('message_action', {'task': task['_id'], 'message': message})], '我跟它说了。')
    role = Coordinator(store, FakeLane(store, [turn]), task_service=service)
    role.on_action_message = lambda row, sent: steered.append((row['_id'], sent['text']))
    event = {'event_id':'redirect-live','scene_id':'dm-a','person_id':'A','text':'继续刚才的工作，优先核对另一份。'}

    class ActionLane:
        def generate(self, binding, operation, phase, text, system, **kwargs):
            seen.append((operation, text))
            if running and len(seen) == 1:
                said['ep'] = role.ingest(event)        # she speaks while the action brain is working
                assert store.db.tasks.find_one({'_id': task['_id']})['state'] == 'RUNNING'
                return LaneResult('原文读过了。')
            return LaneResult('按她补充的先核对了另一份。')

    try:
        if not running:
            said['ep'] = role.ingest(event)
            assert store.db.tasks.find_one({'_id': task['_id']})['state'] == 'READY'
        done = Executor(service, ActionLane(), broker).run(task['_id'], work)
        assert said['ep']['state'] == 'COMMITTED' and not said['ep'].get('task_ids')
        assert steered == [(task['_id'], message)]
        row = store.db.task_messages.find_one({'task_id': task['_id']})
        assert row['from'] == 'character' and row['text'] == message and row['delivered'] is True
        if running:
            # Words that arrived after the run's first message get one more round in the same session.
            assert len(seen) == 2 and seen[1][0] == seen[0][0] + ':more:1'
            assert seen[1][1].startswith('她在你做事时补充了') and message in seen[1][1]
        else:
            assert len(seen) == 1 and '她后来又补充：\n' + message in seen[0][1]
        # Same task, same revision, nothing fenced: the run finishes with her words in it.
        assert done['state'] == 'RETURNED' and done['result']['text'] == '按她补充的先核对了另一份。'
        assert done['intent_revision'] == 1 and store.db.tasks.count_documents({}) == 1 and notices == []
        role.ingest(event)
        assert store.db.task_messages.count_documents({'task_id': task['_id']}) == 1 and len(steered) == 1
    finally:
        broker.close()
