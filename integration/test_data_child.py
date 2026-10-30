"""The data child on MongoDB (data_children.py, data_worker.py): a real child process opens its own Store on the
server, reads a group's history for a task and writes the label row the read writes. On the module's throwaway
database (conftest.py), three synthetic records."""
import time

from asuna import channel_kinds, data_children
from asuna import config as settings_of
from asuna.config import DATA, ROOT
from asuna.history_query import HISTORY_TOOL_NAME
from asuna.records import messages as message_records
from asuna.records import people as people_records
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records

BOT, GROUP = '100357', '300941'
SCENE = 'qq:%s:group:%s' % (BOT, GROUP)
PEER, ACCOUNT = 'qq:100853', '100853'
EPOCH = 7


class Recorded:
    def __init__(self):
        self.records = []

    def record(self, kind, payload):
        self.records.append((kind, payload))


def test_the_data_child_reads_and_writes_on_the_server(store):
    channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}])
    config = {**settings_of.load(ROOT / 'config' / 'local.example.json', dsh_home=DATA / 'asuna-dsh'),
              'mongo_uri': store.config['mongo_uri'], 'database': store.name, 'allowed_databases': []}
    scene_records.save(store, {'_id': SCENE, 'scene_id': SCENE, 'kind': 'group', 'scope_key': 'scene:' + SCENE,
                               'policy_epoch': EPOCH, 'sequence': 1})
    message_records.save(store, {
        '_id': 'line-1', 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': EPOCH, 'scene_seq': 1,
        'text': '雾灯坏了，明天去修', 'author': PEER, 'direction': 'inbound', 'delivery_state': 'RECEIVED',
        'occurred_at': '2026-09-22T12:00:00Z', 'received_at': '2026-09-22T12:00:00Z', 'adapter_id': 'fixture',
        'platform_event_id': 'pe-1',
        'event': {'channel': {'id': 'qq', 'sender_id': ACCOUNT, 'target': {'type': 'group', 'id': GROUP}}}})
    task = task_records.save(store, {
        '_id': 'task-data', 'request_key': 'task-data', 'state': 'RUNNING', 'scene_id': SCENE,
        'scope_key': 'scene:' + SCENE, 'policy_epoch': EPOCH, 'requester_id': PEER, 'intent_revision': 1,
        'fencing_token': 'fence', 'lease_expires_at': time.time() + 600, 'tool_steps': 0}, stream='task-data')
    data_children.start()
    try:
        window = {'since': '2000-01-01', 'until': '2999-12-31T23:59:59Z', 'include_semantic': False}
        result = data_children.run(HISTORY_TOOL_NAME, task, window, config, store.name, Recorded())
        child = data_children.DATA.proc.pid if data_children.DATA.proc else None
    finally:
        data_children.stop()
        data_children.DATA = None
    assert child is not None, 'answered by a child process'
    assert [hit['message_id'] for hit in result['hits']] == ['line-1'], result
    assert people_records.label(store, SCENE + '|' + PEER), 'the label row the child wrote is on the server'
