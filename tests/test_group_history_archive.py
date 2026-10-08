"""Archived speech is explicitly readable without entering live cognition."""
from types import SimpleNamespace

import pytest
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from asuna.channels import Channels
from asuna.history_query import HistoryQueryService
from asuna.ingress import persist_input
from asuna.channels import group_context
from asuna.context import ContextBuilder
from asuna.familiarity import level
from asuna.memory import MemoryService
from asuna.history_query import query_history

BOT = '900000000'
PERSON = 'qq:900000101'
SCENE = 'qq:' + BOT + ':group:900000001'
OLD = '2026-05-01T01:00:00Z'
NEW = '2026-06-01T01:00:00Z'


@pytest.fixture(scope='module', autouse=True)
def mongo_available():
    from asuna.config import load
    try:
        with MongoClient(load()['mongo_uri'], serverSelectionTimeoutMS=2000, timeoutMS=3000) as client:
            client.admin.command('ping')
    except ConnectionFailure:
        pytest.skip('MongoDB unavailable; archive integration checks not run')


def setup(store):
    store.put('scenes', {'_id': SCENE, 'scene_id': SCENE, 'kind': 'group',
        'scope_key': 'scene:' + SCENE, 'policy_epoch': 1, 'sequence': 0, 'members': [PERSON]})
    return {'scene_id': SCENE, 'scope_key': 'scene:' + SCENE, 'policy_epoch': 1}


def archived(key='archive-fixture', scene=SCENE, **extra):
    return {'_id': key, 'schema_version': 1, 'scene_id': 'archive:' + scene,
        'scope_key': 'scene:' + scene, 'policy_epoch': 1, 'scene_seq': 1,
        'direction': 'archived', 'author': PERSON, 'text': '  old group words\n',
        'occurred_at': '2026-05-01T01:00:00.000000+00:00', 'historical_display_name': 'Historical speaker',
        'legacy': {'display_name': 'Historical speaker'}, **extra}


def query(store, task, **args):
    return HistoryQueryService(store).query_for_task(task, {
        'since': '2026-01-01', 'until': '2026-09-01', 'include_semantic': False, **args})


def test_archive_recall_is_attributed_and_read_only(store, runtime_work):
    task = setup(store)
    store.db.messages.insert_many([archived(), archived('archive-other', scene=SCENE + '-other')])
    before = {name: store.db[name].count_documents({}) for name in store.db.list_collection_names()}
    result = query(store, task)
    assert [hit['message_id'] for hit in result['hits']] == ['archive-fixture']
    assert result['hits'][0]['text'] == '  old group words\n'
    assert 'Historical speaker' in result['hits'][0]['who']
    assert result['hits'][0]['archived'] is True
    assert {name: store.db[name].count_documents({}) for name in before} == before


def test_archive_paging_names_link_fences_and_live_isolation(store, runtime_work):
    task = setup(store)
    linked = SCENE + '-linked'
    store.config['context_links'] = {SCENE: [linked]}
    before = level(store, PERSON)
    rows = [archived('archive-' + str(i), scene_seq=i) for i in range(1, 9)]
    rows += [archived('archive-linked', scene=linked), archived('archive-revoked', policy_epoch=2),
             archived('archive-deleted', deletion_id='erased'), archived('archive-stranger', scene=SCENE + '-stranger')]
    store.db.messages.insert_many(rows)
    assert level(store, PERSON) == before
    assert MemoryService(store).chunk(SCENE) == []
    assert query_history(None, store, task, since='2026-01-01')['hits'] == []
    observed = []
    cursor = None
    while True:
        page = query(store, task, limit=3, **({'cursor': cursor} if cursor else {}))
        observed += [hit['message_id'] for hit in page['hits']]
        if not page['more']:
            break
        assert page['next_cursor'] != cursor
        cursor = page['next_cursor']
    assert len(observed) == len(set(observed)) == 9
    assert 'archive-linked' in observed
    counts = {name: store.db[name].count_documents({}) for name in store.db.list_collection_names()}
    assert len(query(store, task, person='Historical speaker')['hits']) == 9
    assert len(query(store, task, person=PERSON)['hits']) == 9
    assert counts == {name: store.db[name].count_documents({}) for name in counts}
    store.config['context_links'] = {}
    assert len(query(store, task)['hits']) == 8


def test_archive_media_and_timestamp_boundary(store, runtime_work):
    task = setup(store)
    store.db.messages.insert_one(archived(text='', occurred_at='2026-05-01T00:00:00.123456+00:00',
        legacy={'attachments': [{'base64_data': 'x' * 40000}]}))
    page = query(store, task, since='2026-05-01', until='2026-05-02')
    assert len(page['hits']) == 1 and page['hits'][0]['text'] == ''
    assert 'base64_data' not in str(page)


def test_archive_transport_trim_resumes_after_last_delivered_row(store, runtime_work):
    task = setup(store)
    store.db.messages.insert_many([archived('long-' + str(i), scene_seq=i, text='x' * 14000)
                                   for i in range(1, 5)])
    ids, cursor = [], None
    for _ in range(8):
        page = query(store, task, limit=4, **({'cursor': cursor} if cursor else {}))
        ids += [hit['message_id'] for hit in page['hits']]
        if not page['more']:
            break
        cursor = page['next_cursor']
    assert ids == ['long-4', 'long-3', 'long-2', 'long-1']


def test_reply_uses_latest_same_scene_parent_not_later_than_reply(store, runtime_work):
    task = setup(store)
    store.db.messages.insert_many([
        {'_id': key, 'schema_version': 1, 'scene_id': sid, 'policy_epoch': 1, 'scene_seq': seq,
         'direction': direction, 'author': 'demo' if direction == 'outbound' else PERSON,
         'text': key, 'occurred_at' if direction == 'inbound' else 'receipt_at': stamp,
         'delivery_state': 'DELIVERED' if direction == 'outbound' else 'RECEIVED',
         **({'event': {'channel': {'platform_event_id': '42'}}} if direction == 'inbound'
            else {'platform_message_id': '42', 'episode_id': key})}
        for key, sid, seq, direction, stamp in [
            ('old-self', SCENE, 1, 'outbound', OLD), ('new-human', SCENE, 2, 'inbound', NEW),
            ('future-self', SCENE, 3, 'outbound', '2026-08-01T00:00:00Z'),
            ('other-human', SCENE + '-other', 4, 'inbound', '2026-06-02T00:00:00Z')]])
    at = '2026-07-01T00:00:00Z'
    ctx = group_context(store, {'scene_id': SCENE}, {'account_id': BOT, 'reply_to': '42', 'occurred_at': at}, 'reply')
    assert ctx['reply_message_id'] == 'new-human' and ctx['wake_reason'] != 'reply_to_character'
    scene = store.db.scenes.find_one({'_id': SCENE})
    rows = ContextBuilder(store)._reply_context([{'platform_reply_to': '42', 'occurred_at': at}], scene)
    assert rows[0]['reply_to_message']['_id'] == 'new-human'


def test_reused_platform_id_and_catchup_cross_real_ingress(store, runtime_work):
    setup(store)
    route = {'scene_id': SCENE, 'target': {'type': 'group', 'id': '900000001'},
             'members': {'900000101': {'person_id': PERSON}}}
    store.config['channels'] = {'qq': {'account_id': BOT, 'routes': {'g': route}}}

    def receive(event):
        message, fresh = persist_input(store, event)
        return {'status': 'accepted' if fresh else 'duplicate', 'id': message['_id']}

    channel = Channels(SimpleNamespace(app=SimpleNamespace(store=store), receive=receive))
    body = {'route_id': 'g', 'account_id': BOT, 'sender_id': '900000101', 'group_id': '900000001',
            'event_id': '42', 'text': 'same greeting', 'occurred_at': OLD}
    first = channel._receive('qq', body)
    later = channel._receive('qq', {**body, 'occurred_at': NEW})
    replay = channel._receive('qq', {**body, 'occurred_at': NEW,
                                  'raw': {'asuna_catchup': {'reason': 'reconnect', 'fetched_at': NEW}}})
    assert first['status'] == later['status'] == 'accepted'
    assert first['id'] != later['id']
    assert replay == {'status': 'duplicate', 'id': later['id']}
