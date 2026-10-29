"""On MongoDB: a record lacking a field of its collection's plain unique index is refused before anything is written,
and a whole one is written (ADR-104, design 3.5): a turn's (`episodes`), a session binding's (`sessions.binding_key`)
and a task's (`tasks.request_key`). On a throwaway `asuna_v2_test_*` database of synthetic records (conftest.py),
dropped at the end, failures included; skipped when no server is named or it cannot be reached."""
import pytest

from asuna.store import Checked, adapters
from asuna.store.catalog import CATALOG
from asuna.store.errors import RecordInvalid
from conftest import throwaway_name

BASE = {'_id': 'whole', 'schema_version': 1, 'revision': 1}
WHOLE = {'episodes': {**BASE, 'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'},
         'sessions': {**BASE, 'binding_key': 'binding'},
         'tasks': {**BASE, 'request_key': 'request'}}
CASES = [(collection, field) for collection, fields in (('episodes', ('scene_id', 'source_event_id', 'episode_kind')),
                                                        ('sessions', ('binding_key',)), ('tasks', ('request_key',)))
         for field in fields]


@pytest.fixture
def checked(settings):
    name = throwaway_name('required')
    adapter = adapters.open(settings, name)
    try:
        store = Checked(adapter, CATALOG)
        store.ensure(list(WHOLE))
        yield store
    finally:
        adapter.close()
        adapters.drop(settings, name)
        assert name not in adapters.module(settings).databases(settings)


@pytest.mark.parametrize('collection,field', CASES)
def test_a_record_lacking_a_unique_index_field_is_refused_on_mongodb(checked, collection, field):
    rows, whole = checked.collection(collection), WHOLE[collection]
    with pytest.raises(RecordInvalid) as caught:
        rows.insert({key: value for key, value in whole.items() if key != field} | {'_id': 'lacking'})
    assert str(caught.value).startswith('RECORD_REQUIRED')
    assert rows.count() == 0, 'nothing reached the server'
    rows.insert(whole)
    assert rows.get('whole')[field] == whole[field]
