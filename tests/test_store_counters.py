"""Counters written outside a document's revision (state.COUNTER_FIELDS: a scene's sequence, a memory's salience, a
watch's sightings, a note's seen_in, a stored file's touches) move with atomic $inc/$set while a writer holds an earlier
read of the document. Putting that read back keeps what the counters reached; only a put that starts the record over
writes them, and a stored file's row is never started over (records.artifacts.save refuses it)."""
import pytest

from asuna.records import artifacts as artifact_records
from asuna.state import COUNTER_FIELDS, Conflict

# collection: (counters at the read, the atomic write its real writer makes, the counters after it)
BUMPS = {
    'scenes': ({'sequence': 3}, {'$inc': {'sequence': 1}}, {'sequence': 4}),                       # ingress, coordinator
    'memory_units': ({'salience': {'ref_count': 1}},                                                # retrieval
                     {'$inc': {'salience.ref_count': 1}, '$set': {'salience.last_ref_seq': 9}},
                     {'salience': {'ref_count': 2, 'last_ref_seq': 9}}),
    'watches': ({'appeared': 0, 'last_seen_at': None},                                              # watches.seen
                {'$set': {'last_seen_at': '2026-10-23T01:00:00+00:00'}, '$inc': {'appeared': 1}},
                {'appeared': 1, 'last_seen_at': '2026-10-23T01:00:00+00:00'}),
    'notes': ({'seen_in': ['ep-1']}, {'$addToSet': {'seen_in': 'ep-2'}}, {'seen_in': ['ep-1', 'ep-2']}),  # notes
    'artifacts': ({'last_sent_at': '2026-10-28T01:00:00+00:00', 'last_read_at': '2026-10-28T01:00:00+00:00'},
                  {'$set': {'last_sent_at': '2026-10-29T01:00:00+00:00',                          # mark_sent
                            'last_read_at': '2026-10-29T02:00:00+00:00'}},                        # mark_read
                  {'last_sent_at': '2026-10-29T01:00:00+00:00', 'last_read_at': '2026-10-29T02:00:00+00:00'}),
}


def test_every_counter_collection_has_a_case():
    assert set(BUMPS) == set(COUNTER_FIELDS)
    assert all(set(BUMPS[name][0]) == set(fields) for name, fields in COUNTER_FIELDS.items())


@pytest.mark.parametrize('collection', sorted(BUMPS))
def test_a_counter_moved_after_a_read_survives_the_put(store, collection):
    at_read, bump, after = BUMPS[collection]
    store.put(collection, {'_id': 'counted', 'scope_key': 'global-safe', 'title': 'before', 'dropped': 1, **at_read})
    read = store.db[collection].find_one({'_id': 'counted'})
    store.db[collection].update_one({'_id': 'counted'}, bump)
    edit = {k: v for k, v in read.items() if k != 'dropped'}
    store.put(collection, {**edit, 'title': 'after'}, expected=read['revision'])
    stored = store.db[collection].find_one({'_id': 'counted'})
    assert {k: stored.get(k) for k in after} == after, 'the put carried the read counters back over the bump'
    assert stored['title'] == 'after' and 'dropped' not in stored and stored['revision'] == read['revision'] + 1
    with pytest.raises(Conflict):
        store.put(collection, {**edit, 'title': 'stale'}, expected=read['revision'])


def test_a_put_that_starts_the_record_over_writes_its_counters(store):
    store.put('watches', {'_id': 'w', 'scope_key': 'global-safe', 'state': 'done', 'appeared': 0, 'last_seen_at': None})
    store.db.watches.update_one({'_id': 'w'}, {'$set': {'last_seen_at': '2026-10-23T01:00:00+00:00'},
                                               '$inc': {'appeared': 1}})
    current = store.db.watches.find_one({'_id': 'w'})
    store.put('watches', {'_id': 'w', 'scope_key': 'global-safe', 'state': 'on', 'appeared': 0, 'last_seen_at': None},
              expected=current['revision'], reset_counters=True)
    stored = store.db.watches.find_one({'_id': 'w'})
    assert stored['state'] == 'on' and stored['appeared'] == 0 and stored['last_seen_at'] is None


def test_a_stored_file_is_never_started_over():
    with pytest.raises(ValueError, match='ARTIFACT_COUNTERS_KEPT'):
        artifact_records.save(None, {'_id': 'a'}, expected=1, reset_counters=True)


def test_a_touch_is_an_update_of_its_own(store):
    """A revisioned write keeps the touches as stored, so it can never write the first one: mark_sent and mark_read
    stay updates."""
    row = artifact_records.save(store, {'_id': 'f', 'scope_key': 'global-safe', 'kind': 'file', 'state': 'DONE'})
    artifact_records.save(store, {**row, 'last_sent_at': '2026-10-29T01:00:00+00:00'}, expected=row['revision'])
    assert 'last_sent_at' not in store.db.artifacts.find_one({'_id': 'f'}), 'a kept field is not written by a put'
    artifact_records.mark_sent(store, 'f', 'file', '2026-10-29T01:00:00+00:00')
    assert store.db.artifacts.find_one({'_id': 'f'})['last_sent_at'] == '2026-10-29T01:00:00+00:00'


def test_a_replace_keeps_the_touches(store):
    artifact_records.insert(store, {'_id': 'r', 'schema_version': 1, 'scope_key': 'global-safe', 'kind': 'x',
                                    'state': 'DONE'})
    artifact_records.mark_sent(store, 'r', 'x', '2026-10-29T01:00:00+00:00')
    assert artifact_records.replace(store, {'_id': 'r', 'schema_version': 1, 'scope_key': 'global-safe', 'kind': 'x',
                                            'state': 'ANSWERED', 'last_sent_at': '2026-10-01T00:00:00+00:00'})
    stored = store.db.artifacts.find_one({'_id': 'r'})
    assert stored['state'] == 'ANSWERED' and stored['last_sent_at'] == '2026-10-29T01:00:00+00:00'
