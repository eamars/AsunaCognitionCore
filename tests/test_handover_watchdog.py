"""ADR-030: the program's watchdog over handovers between the brains catches definite failures and nothing else."""
import time
from types import SimpleNamespace

from asuna import developer_inbox, handover
from asuna.state import now
from asuna.tasks import TaskService
from asuna.lanes import FakeLane, FakeTurn
from fixture_grant import returned
from test_chat import make_chat, delegating, turn


def setup(store, tmp_path, *turns):
    """Her local chat with one delegated task in it (still READY), and the chat worker running."""
    lane = FakeLane(store, [delegating('需要查资料。', '读取资料'), *turns])
    chat, output = make_chat(store, tmp_path, lane)
    service = TaskService(store)
    entries = []
    service.on_collab = lambda task, entry: entries.append(entry)
    chat.app.service = service
    chat.app.coordinator = chat.app.router.coordinator
    chat.settings['workspace'] = str(tmp_path)
    store.config['chat'] = {**store.config['chat'], **chat.settings}
    chat.worker.start()
    episode = chat.submit('帮我查资料。')
    chat.pending.join()
    task = store.db.tasks.find_one({'episode_id': episode['episode_id']})
    return chat, service, task, entries, lane


def finish(store, service, task, text='执行侧报告'):
    return returned(store, service.claim(task['_id']), text, [])


def handbacks(entries):
    return [(entry['state'], entry.get('cause'), bool(entry.get('short')), bool(entry.get('final')))
            for entry in entries if entry['kind'] == 'handback']


def settle(chat):
    chat.sweep()
    chat.pending.join()


def test_normal_operation_costs_nothing(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path, turn('结果到了。', '查到了。'))
    try:
        assert handover.lost(store, set()) == [] and handover.orphaned(store, None) == []
        chat.hand_back(finish(store, service, task))
        chat.pending.join()
        assert store.db.tasks.find_one({'_id': task['_id']})['feedback_state'] == 'DELIVERED'
        calls = len(lane.calls)
        settle(chat)
        assert len(lane.calls) == calls and handbacks(entries) == [('handing', None, False, False), ('taken', None, False, False)]
    finally:
        chat.stop()


def test_a_result_on_its_way_or_a_run_still_going_is_left_alone_however_slow(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path)
    try:
        assert handover.lost(store, set()) == [], 'a queued task has no clock'
        claimed = service.claim(task['_id'])
        assert claimed['started_at']
        assert handover.orphaned(store, None) == [], 'a long run with its lease renewed is not a failure'
        done = returned(store, claimed, '执行侧报告', [])
        assert handover.lost(store, {task['_id']}) == [], 'a result queued behind her other turns is on its way'
        assert [row['_id'] for row in handover.lost(store, set())] == [done['_id']]
    finally:
        chat.stop()


def test_a_result_lost_in_a_restart_is_handed_back_in_full(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path, turn('结果到了。', '查到了。'))
    try:
        finish(store, service, task)                     # finished; its queued hand-back died with the old worker
        assert handover.cause(store, store.db.tasks.find_one({'_id': task['_id']})) == 'restart'
        settle(chat)
        assert store.db.tasks.find_one({'_id': task['_id']})['feedback_state'] == 'DELIVERED'
        assert handbacks(entries) == [('handing', None, False, False), ('taken', None, False, False)]
    finally:
        chat.stop()


def test_a_hand_back_that_keeps_failing_goes_full_then_short_then_tells_the_developer(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path, turn('结果到了。', '查到了。'))
    real = chat.app.router.coordinator.ingest
    failing = {'short': False}

    def ingest(event, **kwargs):
        if event.get('episode_kind') == 'task_feedback' and (failing['short'] or not event['event_id'].endswith(':short')):
            raise TypeError('Object of type ObjectId is not JSON serializable')
        return real(event, **kwargs)

    chat.app.router.coordinator.ingest = ingest
    try:
        chat.hand_back(finish(store, service, task, '报告' * 2000))
        chat.pending.join()
        assert handover.next_step(store, store.db.tasks.find_one({'_id': task['_id']})) == handover.FULL
        settle(chat)
        assert handover.next_step(store, store.db.tasks.find_one({'_id': task['_id']})) == handover.SHORT
        settle(chat)
        given = store.db.tasks.find_one({'_id': task['_id']})
        assert given['feedback_state'] == 'DELIVERED', 'the short version reached her'
        short = store.db.episodes.find_one({'source_event_id': handover.result_event_id(task, True)})
        text = repr(short['context'])
        assert '只给了开头，原文 4000 字共 1 页' in text and 'read_report' in text, 'a cut report says it was cut and how to read on'
        assert 'read_report' in lane.calls[-1]['tools'], 'and that turn has the tool to read on'
        assert 'observations' not in text, 'the short version carries no tool records'
        assert [state for state, *_ in handbacks(entries)] == ['handing', 'missed', 'handing', 'missed', 'handing', 'taken']
        assert handbacks(entries)[-2] == ('handing', None, True, False)
    finally:
        chat.stop()


def test_when_the_short_version_fails_too_the_developer_is_told_and_the_watchdog_stops(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path)
    real = chat.app.router.coordinator.ingest

    def ingest(event, **kwargs):
        if event.get('episode_kind') == 'task_feedback':
            raise TypeError('broken')
        return real(event, **kwargs)

    chat.app.router.coordinator.ingest = ingest
    try:
        chat.hand_back(finish(store, service, task))
        chat.pending.join()
        for _ in range(3):
            settle(chat)
        given = store.db.tasks.find_one({'_id': task['_id']})
        assert given['feedback_state'] == 'UNDELIVERABLE'
        assert handbacks(entries)[-1] == ('missed', 'report', False, True)
        note = store.db.developer_inbox.find_one({})
        assert note['source'] == {'by': 'program', 'task_id': task['_id']} and note['level'] == developer_inbox.NOTE
        assert developer_inbox.block(store, store.config['chat']['persona']) is None, 'not shown to her as hers'
        count = len(entries)
        settle(chat)
        assert len(entries) == count and store.db.developer_inbox.count_documents({}) == 1, 'nothing more is tried'
        assert handover.status_words(given).endswith('要再看就用 message_action 让它重跑')
    finally:
        chat.stop()


def test_when_her_turn_on_the_result_failed_the_short_version_comes_next(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path, turn('结果到了。', '查到了。'))
    try:
        done = finish(store, service, task)
        store.put('episodes', {'_id': 'ep-failed-turn', 'source_event_id': handover.result_event_id(done),
                               'episode_kind': 'task_feedback', 'state': 'FAILED_RUNTIME', 'task_id': task['_id']},
                  stream='ep-failed-turn')
        assert handover.cause(store, done) == 'turn' and handover.next_step(store, done) == handover.SHORT
        settle(chat)
        assert store.db.tasks.find_one({'_id': task['_id']})['feedback_state'] == 'DELIVERED'
        assert handbacks(entries)[0] == ('handing', None, True, False)
    finally:
        chat.stop()


def test_an_orphaned_run_is_closed_and_handed_back_as_not_finished(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path, turn('它断了。', '行动脑断了，我去看看。'))
    try:
        claimed = service.claim(task['_id'])
        store.db.tasks.update_one({'_id': task['_id']}, {'$set': {'lease_expires_at': time.time() - 1}})
        assert handover.orphaned(store, task['_id']) == [], 'the run this worker is running is not an orphan'
        settle(chat)
        closed = store.db.tasks.find_one({'_id': task['_id']})
        assert closed['state'] == 'BLOCKED' and closed['failure_type'] == 'ORPHANED'
        assert closed['feedback_state'] == 'DELIVERED' and closed['fencing_token'] > claimed['fencing_token']
    finally:
        chat.stop()


def test_a_result_whose_scene_changed_is_settled_once_not_retried(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path)
    try:
        finish(store, service, task)
        store.db.scenes.update_one({'_id': task['scene_id']}, {'$inc': {'policy_epoch': 1}})
        settle(chat)
        assert store.db.tasks.find_one({'_id': task['_id']})['feedback_state'] == 'SUPPRESSED'
        assert handover.lost(store, set()) == []
    finally:
        chat.stop()


def test_her_task_list_says_where_each_task_stands_in_words():
    words = handover.status_words
    assert words({'state': 'READY'}) == '排着队，还没开始跑'
    assert words({'state': 'RUNNING'}) == '在跑'
    assert words({'state': 'RETURNED', 'feedback_state': 'DELIVERED'}) == '跑完了，结果已经交给你'
    assert words({'state': 'RETURNED', 'feedback_state': 'READY'}) == '跑完了，结果还没交到你手上：报告存着，程序会交给你'
    assert words({'state': 'BLOCKED', 'feedback_state': 'UNDELIVERABLE'}).startswith('没做成，但结果交不到你手上')
    assert words({'state': 'PAUSED'}).startswith('做到一半宿主重启停了')
    assert words({'state': 'CANCELLED', 'cancel_reason': 'host_stop'}).endswith('message_action 接着做')


def test_a_task_carried_on_by_a_later_one_points_to_it():
    assert handover.status_words({'state': 'RETURNED', 'feedback_state': 'DELIVERED'}, 'task-later') == \
        '后来接着做了一轮，以 task-later 那条为准'
    assert handover.status_words({'state': 'RUNNING'}, 'task-later') == '在跑'


def test_continuations_names_the_newest_task_that_carries_one_on(store):
    for task_id, created in (('task-b', '2026-10-09T00:01:00+00:00'), ('task-c', '2026-10-09T00:02:00+00:00')):
        store.put('tasks', {'_id': task_id, 'request_key': task_id, 'continues_task_id': 'task-a', 'created_at': created},
                  stream=task_id)
    assert handover.continuations(store, ['task-a', 'task-z']) == {'task-a': 'task-c'}
