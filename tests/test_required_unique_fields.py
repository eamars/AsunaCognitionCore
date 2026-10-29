"""A record that lacks a field of its collection's plain unique index is refused before anything is written
(ADR-104, design 3.5: a plain unique index's fields are `required`). One case per field, on the in-memory adapter
(`[memory]`) and on the MongoDB adapter over the unit run's stand-in (`[stand-in]`), through the shared layer's write
that `Store.put` makes (insert, and replace at a revision), and once through each owner's `save`; and the catalog
declares each field `required`, in a unique index, so a later catalog edit cannot drop it silently."""
import uuid

import pymongo
import pytest

import conftest
from asuna.records import episodes as episode_records
from asuna.records import sessions as session_records
from asuna.records import tasks as task_records
from asuna.store import Checked
from asuna.store.catalog import CATALOG
from asuna.store.errors import RecordInvalid
from asuna.store.memory import MemoryAdapter
from asuna.store.mongodb import MongoAdapter

# (collection, field, a whole record that has every required field)
REQUIRED = [
    ('episodes', 'scene_id', {'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'}),
    ('episodes', 'source_event_id', {'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'}),
    ('episodes', 'episode_kind', {'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'}),
    ('sessions', 'binding_key', {'binding_key': 'native-host:s'}),
    ('tasks', 'request_key', {'request_key': 't'}),
]
IDS = ['%s.%s' % (name, field) for name, field, _ in REQUIRED]


@pytest.fixture(params=['memory', 'stand-in'])
def checked(request):
    """The shared layer over the core's catalog: the in-memory adapter, or the MongoDB adapter over the stand-in."""
    if request.param == 'memory':
        yield Checked(MemoryAdapter(seed=0), CATALOG)
        return
    client = pymongo.MongoClient(conftest.NO_SERVER)
    assert getattr(client, 'unit_run', False), 'the stand-in is not loaded: this run could reach a server'
    name = 'asuna_v2_test_required_' + uuid.uuid4().hex[:12]
    try:
        yield Checked(MongoAdapter(client, name), CATALOG)
    finally:
        client.drop_database(name)
        client.close()


def refused(call):
    with pytest.raises(RecordInvalid) as caught:
        call()
    assert str(caught.value).startswith('RECORD_REQUIRED'), str(caught.value)


@pytest.mark.parametrize('name, field, whole', REQUIRED, ids=IDS)
def test_a_record_lacking_a_unique_index_field_is_refused_and_nothing_is_written(checked, name, field, whole):
    rows = checked.collection(name)
    lacking = {key: value for key, value in whole.items() if key != field}
    refused(lambda: rows.insert({'_id': 'lacking', 'schema_version': 1, 'revision': 1, **lacking}))
    assert rows.get('lacking') is None
    rows.insert({'_id': 'whole', 'schema_version': 1, 'revision': 1, **whole})
    refused(lambda: rows.replace({'_id': 'whole', 'schema_version': 1, 'revision': 2, **lacking}, expected=1))
    assert rows.get('whole')[field] == whole[field]


SAVE = {'episodes': episode_records.save, 'sessions': session_records.save, 'tasks': task_records.save}


@pytest.mark.parametrize('name, field, whole', REQUIRED, ids=IDS)
def test_the_owner_s_save_refuses_a_record_lacking_the_field(store, name, field, whole):
    lacking = {key: value for key, value in whole.items() if key != field}
    refused(lambda: SAVE[name](store, {'_id': 'lacking', **lacking}, stream='lacking'))
    assert store.collection(name).get('lacking') is None


@pytest.mark.parametrize('name, field, whole', REQUIRED, ids=IDS)
def test_the_catalog_declares_the_field_required_in_a_unique_index(name, field, whole):
    declared = CATALOG.collection(name)
    assert declared.field(field) is not None and declared.field(field).required, (name, field)
    assert any(field in [path for path, _ in index.keys] and not index.only_where_present
               for index in declared.unique()), (name, field)

