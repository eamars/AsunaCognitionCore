"""ADR-030 on MongoDB, kept by ADR-104 decision 9 (a break would lose her data): a result lost in a restart is handed
back in full."""

import pytest

from asuna import handover
from asuna.tasks import TaskService
from asuna.lanes import FakeLane

from turn_parts import delegating, make_chat, returned, turn

pytestmark = pytest.mark.world                # `store` is the fixture world


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
    task = store.raw.tasks.find_one({'episode_id': episode['episode_id']})
    return chat, service, task, entries, lane


def finish(store, service, task, text='执行侧报告'):
    return returned(store, service.claim(task['_id']), text, [])


def handbacks(entries):
    return [(entry['state'], entry.get('cause'), bool(entry.get('short')), bool(entry.get('final')))
            for entry in entries if entry['kind'] == 'handback']


def settle(chat):
    chat.sweep()
    chat.pending.join()


def test_a_result_lost_in_a_restart_is_handed_back_in_full(store, tmp_path):
    chat, service, task, entries, lane = setup(store, tmp_path, turn('结果到了。', '查到了。'))
    try:
        finish(store, service, task)                     # finished; its queued hand-back died with the old worker
        assert handover.cause(store, store.raw.tasks.find_one({'_id': task['_id']})) == 'restart'
        settle(chat)
        assert store.raw.tasks.find_one({'_id': task['_id']})['feedback_state'] == 'DELIVERED'
        assert handbacks(entries) == [('handing', None, False, False), ('taken', None, False, False)]
    finally:
        chat.stop()


