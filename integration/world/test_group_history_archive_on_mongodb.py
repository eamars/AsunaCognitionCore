"""On MongoDB: archived speech is read only through history, inside its fences (its scene and the linked ones, its
epoch, not erased), and never enters live cognition (leak)."""

import pytest

from asuna.history_query import HistoryQueryService
from asuna.familiarity import level
from asuna.memory import MemoryService
from asuna.history_query import query_history

pytestmark = pytest.mark.world                # `store` is the fixture world

BOT = '90000'
PERSON = 'qq:90101'
SCENE = 'qq:' + BOT + ':group:90001'


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


def test_archive_paging_names_link_fences_and_live_isolation(store):
    task = setup(store)
    linked = SCENE + '-linked'
    store.config['context_links'] = {SCENE: [linked]}
    before = level(store, PERSON)
    rows = [archived('archive-' + str(i), scene_seq=i) for i in range(1, 9)]
    rows += [archived('archive-linked', scene=linked), archived('archive-revoked', policy_epoch=2),
             archived('archive-deleted', deletion_id='erased'), archived('archive-stranger', scene=SCENE + '-stranger')]
    store.raw.messages.insert_many(rows)
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
    counts = {name: store.raw[name].count_documents({}) for name in store.raw.list_collection_names()}
    assert len(query(store, task, person='Historical speaker')['hits']) == 9
    assert len(query(store, task, person=PERSON)['hits']) == 9
    assert counts == {name: store.raw[name].count_documents({}) for name in counts}
    store.config['context_links'] = {}
    assert len(query(store, task)['hits']) == 8


