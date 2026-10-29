"""The fields of a plain unique index are required (ADR-104, design 3.5): the catalog declares each one `required`, so
a later catalog edit cannot drop it silently, and each owner's `save` refuses a record lacking one before anything is
written (on the unit run's store). The shared layer's insert and replace refuse it on MongoDB too
(integration/test_required_fields.py)."""

import pytest

from asuna.records import episodes as episode_records
from asuna.records import sessions as session_records
from asuna.records import tasks as task_records
from asuna.store.catalog import CATALOG
from asuna.store.errors import RecordInvalid

# (collection, field, a whole record that has every required field)
REQUIRED = [
    ('episodes', 'scene_id', {'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'}),
    ('episodes', 'source_event_id', {'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'}),
    ('episodes', 'episode_kind', {'scene_id': 'g', 'source_event_id': 'ev', 'episode_kind': 'external'}),
    ('sessions', 'binding_key', {'binding_key': 'native-host:s'}),
    ('tasks', 'request_key', {'request_key': 't'}),
]
IDS = ['%s.%s' % (name, field) for name, field, _ in REQUIRED]


@pytest.mark.parametrize('name, field, whole', REQUIRED, ids=IDS)
def test_the_catalog_declares_the_field_required_in_a_unique_index(name, field, whole):
    declared = CATALOG.collection(name)
    assert declared.field(field) is not None and declared.field(field).required, (name, field)
    assert any(field in [path for path, _ in index.keys] and not index.only_where_present
               for index in declared.unique()), (name, field)


SAVE = {'episodes': episode_records.save, 'sessions': session_records.save, 'tasks': task_records.save}


@pytest.mark.parametrize('name, field, whole', REQUIRED, ids=IDS)
def test_the_owners_save_refuses_a_record_lacking_the_field(store, name, field, whole):
    lacking = {key: value for key, value in whole.items() if key != field}
    with pytest.raises(RecordInvalid) as caught:
        SAVE[name](store, {'_id': 'lacking', **lacking}, stream='lacking')
    assert str(caught.value).startswith('RECORD_REQUIRED')
    assert store.collection(name).get('lacking') is None
