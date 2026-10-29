"""On MongoDB: a record lacking a field of its collection's plain unique index is refused before anything is written,
and a whole one is written (ADR-104, design 3.5): a turn's (`episodes`), a session binding's (`sessions.binding_key`)
and a task's (`tasks.request_key`), through the shared layer's insert and its replace at a revision (the writes
`Store.put` makes). On the module's throwaway database (conftest.py); each owner's `save` is the unit run's
(tests/test_required_unique_fields.py)."""
import pytest

from asuna.store.errors import RecordInvalid
from conftest import emptied

BASE = {'_id': 'whole', 'schema_version': 1, 'revision': 1}
WHOLE = {'episodes': {**BASE, 'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'},
         'sessions': {**BASE, 'binding_key': 'binding'},
         'tasks': {**BASE, 'request_key': 'request'}}
CASES = [(collection, field) for collection, fields in (('episodes', ('scene_id', 'source_event_id', 'episode_kind')),
                                                        ('sessions', ('binding_key',)), ('tasks', ('request_key',)))
         for field in fields]


@pytest.fixture
def checked(settings, database):
    with emptied(settings, database) as store:
        store.ensure(list(WHOLE))
        yield store


@pytest.mark.parametrize('collection,field', CASES)
def test_a_record_lacking_a_unique_index_field_is_refused_on_mongodb(checked, collection, field):
    rows, whole = checked.collection(collection), WHOLE[collection]
    with pytest.raises(RecordInvalid) as caught:
        rows.insert({key: value for key, value in whole.items() if key != field} | {'_id': 'lacking'})
    assert str(caught.value).startswith('RECORD_REQUIRED')
    assert rows.count() == 0, 'nothing reached the server'
    rows.insert(whole)
    with pytest.raises(RecordInvalid) as caught:
        rows.replace({key: value for key, value in whole.items() if key != field} | {'revision': 2}, expected=1)
    assert str(caught.value).startswith('RECORD_REQUIRED')
    assert rows.get('whole')[field] == whole[field] and rows.get('whole')['revision'] == 1

