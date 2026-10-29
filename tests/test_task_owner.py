"""records.tasks answers what the replaced reads answered (ADR-104 B6): the conversation context's task list in the
aggregate's order, and a fence of None matching a record whose field is missing."""
from asuna.records import messages as message_records
from asuna.records import tasks as task_records
from asuna import handover
from asuna.store.words import Unset


def task(store, task_id, **fields):
    return task_records.save(store, {'_id': task_id, 'request_key': task_id, 'scene_id': 'g', 'scope_key': 's',
                                     'policy_epoch': 1, **fields}, stream=task_id)


def line(store, line_id, received_at):
    message_records.save(store, {'_id': line_id, 'scene_id': 'g', 'direction': 'inbound', 'received_at': received_at},
                         stream=line_id)


def test_the_task_list_is_open_work_first_then_by_its_newest_input_then_by_id(store):
    """Running and queued first; then the newest input line's time, a task whose inputs are gone (or that has none)
    after every timed one; ties by id. Each row has what the list shows, `_active` and its report's length."""
    line(store, 'in-old', '2026-10-01T00:00:00+00:00')
    line(store, 'in-new', '2026-10-02T00:00:00+00:00')
    task(store, 't-done-new', state='RETURNED', raw_input_refs=['in-old', 'in-new'], result={'text': '好了'})
    task(store, 't-done-old', state='DONE', raw_input_refs='in-old', title='旧的')
    task(store, 't-gone-b', state='DONE', raw_input_refs=['in-gone'])
    task(store, 't-gone-a', state='BLOCKED')
    task(store, 't-running', state='RUNNING', raw_input_refs=['in-old'], goal='做着')
    task(store, 'elsewhere', state='READY', scene_id='other')
    rows = task_records.recent_with_inputs(store, 'g', 's', 1)
    assert [row['_id'] for row in rows] == ['t-running', 't-done-new', 't-done-old', 't-gone-a', 't-gone-b']
    assert rows[0]['_active'] == 1 and rows[1]['_active'] == 0
    assert rows[1]['_report_chars'] == 2 and rows[2]['_report_chars'] == 0 and rows[2]['title'] == '旧的'
    assert 'raw_input_refs' not in rows[0] and 'result' not in rows[1]


def test_a_conversation_of_none_and_a_feedback_of_none_keep_the_old_meaning(store):
    """`created(scenes=[])` is the replaced `$in: [None]`: the tasks of no conversation. A finished task whose feedback
    is null is not one whose result is waiting (the replaced `$nin: [..., None]`)."""
    task(store, 'no-place', state='DONE', created_at='2026-10-03T00:00:00+00:00')
    store.collection('tasks').update({'_id': 'no-place'}, Unset('scene_id'))          # a task of no conversation
    task(store, 'here', state='DONE', created_at='2026-10-03T00:00:00+00:00')
    found = task_records.created(store, '2026-10-01', scenes=[]).rows()
    assert [row['_id'] for row in found] == ['no-place']
    task(store, 'waiting', state='RETURNED', feedback_state='READY')
    task(store, 'null', state='RETURNED', feedback_state=None)
    task(store, 'taken', state='RETURNED', feedback_state='DELIVERED')
    assert [row['_id'] for row in handover.lost(store, ())] == ['waiting']
