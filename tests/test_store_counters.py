"""Counters written outside a document's revision (state.COUNTER_FIELDS: a scene's sequence, a memory's salience, a
watch's sightings, a note's seen_in, a stored file's touches; the table is counter_bumps.py) move with atomic writes
while a writer holds an earlier read of the document. Putting that read back keeps what the counters reached; only a
put that starts the record over writes them, and a stored file's row never does (records.artifacts.save refuses it);
a stored file's touches (its last send and read) are updates of their own that every write of its row keeps. On the
unit run's store (conftest.py)."""
import pytest

from asuna.records import artifacts as artifact_records
from asuna.state import COUNTER_FIELDS, Conflict
from asuna.store.words import Increase, Set
from counter_bumps import BUMPS, NOW


def test_every_counter_collection_has_a_case():
    assert set(BUMPS) == set(COUNTER_FIELDS)
    assert all(set(BUMPS[name][0]) == set(fields) for name, fields in COUNTER_FIELDS.items())


def test_a_stored_file_is_never_started_over():
    with pytest.raises(ValueError, match='ARTIFACT_COUNTERS_KEPT'):
        artifact_records.save(None, {'_id': 'a'}, expected=1, reset_counters=True)


@pytest.mark.parametrize('collection', sorted(BUMPS))
def test_a_counter_moved_after_a_read_survives_the_put(store, collection):
    at_read, bump, after = BUMPS[collection]
    rows = store.collection(collection)
    store.put(collection, {'_id': 'counted', 'scope_key': 'global-safe', 'title': 'before', 'dropped': 1, **at_read})
    read = rows.get('counted')
    rows.update({'_id': 'counted'}, bump)
    edit = {k: v for k, v in read.items() if k != 'dropped'}
    store.put(collection, {**edit, 'title': 'after'}, expected=read['revision'])
    stored = rows.get('counted')
    assert {k: stored.get(k) for k in after} == after, 'the put carried the read counters back over the bump'
    assert stored['title'] == 'after' and 'dropped' not in stored and stored['revision'] == read['revision'] + 1
    with pytest.raises(Conflict):
        store.put(collection, {**edit, 'title': 'stale'}, expected=read['revision'])


def test_a_put_that_starts_the_record_over_writes_its_counters(store):
    rows = store.collection('watches')
    store.put('watches', {'_id': 'w', 'scope_key': 'global-safe', 'state': 'done', 'appeared': 0, 'last_seen_at': None})
    rows.update({'_id': 'w'}, [Set({'last_seen_at': NOW}), Increase('appeared')])
    current = rows.get('w')
    store.put('watches', {'_id': 'w', 'scope_key': 'global-safe', 'state': 'on', 'appeared': 0, 'last_seen_at': None},
              expected=current['revision'], reset_counters=True)
    stored = rows.get('w')
    assert stored['state'] == 'on' and stored['appeared'] == 0 and stored['last_seen_at'] is None


def test_a_touch_is_an_update_of_its_own(store):
    """A revisioned write keeps the touches as stored, so it can never write the first one: mark_sent and mark_read
    stay updates."""
    row = artifact_records.save(store, {'_id': 'f', 'scope_key': 'global-safe', 'kind': 'file', 'state': 'DONE'})
    artifact_records.save(store, {**row, 'last_sent_at': NOW}, expected=row['revision'])
    assert 'last_sent_at' not in store.collection('artifacts').get('f'), 'a kept field is not written by a put'
    artifact_records.mark_sent(store, 'f', 'file', NOW)
    assert store.collection('artifacts').get('f')['last_sent_at'] == NOW


def test_a_replace_keeps_the_touches(store):
    artifact_records.insert(store, {'_id': 'r', 'schema_version': 1, 'scope_key': 'global-safe', 'kind': 'x',
                                    'state': 'DONE'})
    artifact_records.mark_sent(store, 'r', 'x', NOW)
    assert artifact_records.replace(store, {'_id': 'r', 'schema_version': 1, 'scope_key': 'global-safe', 'kind': 'x',
                                            'state': 'ANSWERED', 'last_sent_at': '2026-10-01T00:00:00+00:00'})
    stored = store.collection('artifacts').get('r')
    assert stored['state'] == 'ANSWERED' and stored['last_sent_at'] == NOW
