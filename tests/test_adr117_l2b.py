"""ADR-117 L2b: the stored fields a turn's blocks read instead of whole stores are written where the fact is made. A
finished task's result carries its report's length and pages (what the task list says, silently wrong otherwise); a
group's name is written by the line that carries it, the newest one's kept. On the unit run's store holding the
fixture world (conftest.py)."""
from asuna.ingress import persist_input
from asuna.lanes import FakeLane, LaneResult
from asuna.people import People
from asuna.records import artifacts as artifact_records
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from asuna.tasks import Executor, TaskService, task_pages

REPORT = '\n'.join('## 第%d部分\n' % n + '这一部分的内容，一行一行写下去。\n' * 80 for n in range(1, 5))


class Broker:
    def bind(self, session, task, workspace):
        pass


def queued(world, task_id):
    scene = scene_records.get(world, 'dm-a')
    line = persist_input(world, {'event_id': 'ask-' + task_id, 'scene_id': 'dm-a', 'person_id': 'A', 'text': '查一下'})[0]
    task_records.save(world, {'_id': task_id, 'request_key': task_id, 'state': 'READY', 'scene_id': 'dm-a',
                              'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'], 'requester_id': 'A',
                              'episode_id': line['episode_id'], 'raw_input_refs': [line['_id']], 'intent_revision': 1,
                              'fencing_token': 0, 'goal': '查一下', 'tool_steps': 0}, stream=task_id)


def test_a_finished_task_carries_its_reports_length_and_pages(world):
    service = TaskService(world)
    queued(world, 't-long')
    running = service.claim('t-long')
    for n in range(20):                       # tool records enough for pages of their own
        artifact_records.save(world, {'_id': 'call-%d' % n, 'scope_key': running['scope_key'], 'task_id': 't-long',
                                      'intent_revision': 1, 'tool': 'write_file', 'args': {}, 'input_hash': str(n),
                                      'state': 'DONE', 'result': {'wrote': 'x' * 700}}, stream='t-long')
    Executor(service, FakeLane(world, [LaneResult(content=REPORT)]), Broker())._run_claimed(running, 'w', lambda: None)
    done = task_records.get(world, 't-long')
    assert done['state'] == 'RETURNED'
    assert done['result']['chars'] == len(REPORT)
    assert done['result']['pages'] == len(task_pages(world, done)) > 3, 'the report\'s pages and its records\''
    queued(world, 't-cut')
    service.claim('t-cut')
    cut = service.interrupted_by_restart('t-cut')['result']
    assert (cut['chars'], cut['pages']) == (len(cut['text']), 1), 'every finish writes them'
    [shown] = [row for row in task_records.recent_with_inputs(world, 'dm-a', running['scope_key'], 1)
               if row['_id'] == 't-long']
    assert (shown['_report_chars'], shown['_report_pages']) == (done['result']['chars'], done['result']['pages'])


def test_a_groups_name_is_its_newest_named_lines(world):
    def line(event_id, raw=None):
        persist_input(world, {'event_id': event_id, 'scene_id': 'g1', 'person_id': 'A', 'text': 'hi',
                              **({'raw': raw} if raw is not None else {})})
    line('n1', {'group_name': 'First'})
    line('n2', {'group_name': 'Renamed'})
    line('n3', {})                                       # a line without the name changes nothing
    line('n4')
    scene = scene_records.get(world, 'g1')
    assert scene['name'] == 'Renamed'
    assert People(world).scene_title(scene) == '群聊「Renamed」'
    assert People(world).scene_title({'_id': 'g1', 'kind': 'group'}) == '群聊「Renamed」', 'a row read without it'
    assert People(world).scene_title(scene_records.get(world, 'g2')) == '一个群聊', 'never named'
