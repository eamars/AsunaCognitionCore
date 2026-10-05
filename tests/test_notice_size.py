"""Her turn notices stay small (owner, 2026-10-05): headlines, not audit ids or every path."""
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.tasks import bounded_result
from test_adr009_p2 import owner

THINK = ('think', {'thought': '看看最近的事。'})


def test_a_task_result_keeps_the_report_but_not_its_tool_record_ids():
    result = {'task_id': 't', 'text': '做完了。', 'finish_reason': 'stop', 'artifact_refs': ['tool-' + 'a' * 64] * 40}
    shown = bounded_result(result)
    assert shown['text'] == '做完了。' and shown['tool_records'] == 40 and 'artifact_refs' not in shown
    assert 'artifact_refs' in result, 'the stored result is unchanged'


def test_task_state_lists_every_open_task_and_only_the_last_finished(store):
    owner(store)
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    def task(key, state, at):
        store.put('tasks', {'_id': 'task-' + key, 'scene_id': 'dm-a', 'scope_key': scene['scope_key'],
            'policy_epoch': scene['policy_epoch'], 'state': state, 'title': key, 'goal': key * 50,
            'raw_input_refs': ['in-' + key], 'finished_at': at, 'request_key': 'task-' + key}, stream='task-' + key)
        store.put('messages', {'_id': 'in-' + key, 'received_at': at}, stream='in-' + key)
    for index in range(6):
        task('done%d' % index, 'RETURNED', '2026-10-05T00:0%d:00Z' % index)
    task('open', 'RUNNING', '2026-10-04T00:00:00Z')
    task('paused', 'PAUSED', '2026-10-04T00:00:01Z')
    lane = FakeLane(store, [FakeTurn([THINK], '嗯。')])
    ep = Coordinator(store, lane).ingest({'event_id': 'n1', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '在吗'})
    shown = [row['_id'] for row in ep['context']['task_state_from_program']]
    assert shown[:2] == ['task-open', 'task-paused'] or set(shown[:2]) == {'task-open', 'task-paused'}
    assert shown[2:] == ['task-done5', 'task-done4', 'task-done3'], 'only the last three finished'
    assert all('goal' not in row for row in ep['context']['task_state_from_program']), 'the title says what it is'


def test_self_improvement_sees_publication_counts_not_every_path(store):
    owner(store)
    store.put('sink_receipts', {'_id': 'self-publish-x', 'kind': 'self_development_publish', 'project': 'p',
        'state': 'ACTIVE', 'changed_files': ['a/%d.md' % index for index in range(30)], 'deleted_files': ['b.md'],
        'published_at': '2026-10-05T00:00:00Z', 'task_id': 'task-x'}, stream='task-x')
    lane = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'reason': '没什么要做的'})])])
    ep = Coordinator(store, lane).ingest({'event_id': 'self-development:size', 'scene_id': 'dm-a', 'person_id': 'A',
        'text': '这是一次内部自我开发机会。', 'episode_kind': 'self_development', 'adapter_id': 'self-development'})
    row = ep['context']['recent_experience_from_program']['publish_lineage'][0]
    assert row['changed_files'] == 30 and row['deleted_files'] == 1
