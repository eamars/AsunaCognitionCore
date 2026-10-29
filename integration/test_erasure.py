"""On MongoDB: an operator erasure (ADR-009 E20, ADR-105). It deletes a conversation's stored bytes and marks each of
its rows erased, and no other; a privacy erasure marks them with its own deletion id and redacts every other row of
the scope; it keeps the unique keys, fences the scope's context at a new epoch, tombstones the memory and leaves an
audit chain that verifies; her next turn neither fails nor sees what went. On a throwaway database holding the fixture
world (conftest.py)."""
import json

from asuna import blobs as blobs_mod
from asuna.audit import verify
from asuna.blobs import BlobStore
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from asuna.privacy import PrivacyService
from asuna.records import scenes as scene_records
from asuna import audit
from asuna.store.words import Set, Unset

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(32, 128))
THOUGHT = ('think', {'thought': 'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})


def event(key='e', scene='dm-a', person='A', text='我回来了。'):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text}


def normal(store):
    """One ordinary character turn: her thought, then what she says."""
    lane = FakeLane(store, [FakeTurn([THOUGHT], '回来了。')])
    return Coordinator(store, lane), lane


def scopes(store):
    rows = sorted(scene_records.all(store, fields=['_id', 'scope_key']), key=lambda row: row['_id'])
    return rows[0], rows[1]


def picture(store, scope, source='in-ep-1', body=PNG):
    return BlobStore(store).put(body + source.encode(), scope, 'image', source_ids=[source])['artifact_id']


def test_an_erasure_marks_each_row_of_its_scope_and_no_other(world):
    store = world
    rows = store.collection('artifacts')
    here, there = scopes(store)
    blobs = BlobStore(store)
    kept_name = picture(store, here['scope_key'], 'in-ep-a')
    rows.update({'_id': kept_name}, Set({'name': 'notes.md'}))
    expired = picture(store, here['scope_key'], 'in-ep-b')
    blobs_mod.delete(store, rows.get(expired)['gridfs_id'])                  # as the sweep does
    rows.update({'_id': expired}, [Set({'storage': 'removed'}), Unset('gridfs_id')])
    other = picture(store, there['scope_key'], 'in-ep-c')
    rows.insert({'_id': 'not-a-blob', 'schema_version': 1, 'kind': 'channel_admission', 'scope_key': here['scope_key']})
    deleted = blobs.erase_scope(here['scope_key'], 'erase-test')
    assert deleted == 1, 'the one GridFS file of the scope (the removed row had none left)'
    for row_id in (kept_name, expired):
        row = rows.get(row_id)
        assert row['storage'] == 'erased' and row['erased_at'] and row['deletion_id'] == 'erase-test'
        assert 'gridfs_id' not in row
    assert rows.get(kept_name)['name'] == 'notes.md', 'the row keeps its name (the owner)'
    assert rows.get(other)['storage'] == 'gridfs'
    assert 'storage' not in rows.get('not-a-blob')
    assert store.blobs.of_scope(here['scope_key']) == []
    assert len(store.blobs.of_scope(there['scope_key'])) == 1


def test_privacy_erasure_marks_the_rows_with_its_own_deletion_id(world):
    store = world
    rows = store.collection('artifacts')
    c, _ = normal(store)
    c.ingest(event())
    memory = store.collection('memory_units').get('M09')
    row_id = picture(store, memory['scope_key'])
    rows.update({'_id': row_id}, Set({'name': 'a.png'}))
    rows.insert({'_id': 'task-output', 'schema_version': 1, 'scope_key': memory['scope_key'], 'kind': 'task_report',
                 'state': 'DONE', 'text': 'a paraphrase of the chat'})
    result = PrivacyService(store).delete_memory('M09', operator=True)
    row = rows.get(row_id)
    assert row['storage'] == 'erased' and row['deletion_id'] == result['deletion_id']
    assert row['name'] == 'a.png' and row['kind'] == 'image' and row['size'] and row['created_at'], \
        'the marked row keeps its name, size and when (ADR-105)'
    other = rows.get('task-output')
    assert other['state'] == 'INVALIDATED' and other['text'] == '[deleted]', 'any other row of the scope is redacted'


def test_E20_erasure_preserves_unique_keys_and_refences_context(world):
    store = world
    c, lane = normal(store)
    c.ingest(event())
    c, lane = normal(store)
    c.ingest(event('second'))
    result = PrivacyService(store).delete_memory('M09', operator=True)
    assert result['policy_epoch'] == 2
    assert store.collection('episodes').count({'state': 'INVALIDATED'}) == 2
    assert store.collection('memory_units').get('M09')['status'] == 'tombstone'
    verify(audit.events(store, by=None).rows())
    c, lane = normal(store)
    assert c.ingest(event('third'))['state'] == 'COMMITTED'
    assert 'PRIVATE_A_CANARY' not in json.dumps(lane.calls)
