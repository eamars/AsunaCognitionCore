"""The catalog declares each field of a plain unique index `required` (ADR-104, design 3.5), so a later catalog edit
cannot drop it silently. That a record lacking one is refused before anything is written is shown on MongoDB
(integration/test_required_fields.py)."""

import pytest

from asuna.store.catalog import CATALOG

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

