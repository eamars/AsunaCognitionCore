"""The blob owner (ADR-104 B8, design 5.11): bytes go into the store's blob interface, are read back in pieces and
compared with what was written before their `artifacts` row exists; bytes that read back otherwise are deleted and no
row is written, so a row never names bytes that differ from its hash. Erasure by scope deletes the scope's blobs and
no other's."""
import io

import pytest

from asuna import blobs
from asuna.blobs import BlobStore
from asuna.records import artifacts as artifact_records

SCOPE, OTHER = 'scene:dm-a', 'scene:dm-b'


def test_bytes_that_read_back_otherwise_are_deleted_and_leave_no_row(store, monkeypatch):
    before = store.blobs.of_scope(SCOPE)
    monkeypatch.setattr(blobs, 'open', lambda store, blob_id: io.BytesIO(b'other bytes'))   # what the store read back
    for put in (lambda: BlobStore(store).put_stream(io.BytesIO(b'the bytes'), SCOPE, 'file'),
                lambda: BlobStore(store).put(b'the bytes', SCOPE, 'file')):
        with pytest.raises(ValueError, match='ARTIFACT_STORED_BYTES_MISMATCH'):
            put()
    assert store.blobs.of_scope(SCOPE) == before, 'the written blobs were deleted'
    assert artifact_records.of_kind(store, 'file').rows() == [], 'no row names bytes that were not verified'


def test_a_verified_blob_is_named_by_its_row_and_an_erasure_deletes_only_its_scopes(store):
    here = BlobStore(store).put_stream(io.BytesIO(b'x' * (blobs.STREAM_PIECE + 7)), SCOPE, 'file')
    there = BlobStore(store).put(b'elsewhere', OTHER, 'file')
    rows = {key: artifact_records.get(store, key) for key in (here['artifact_id'], there['artifact_id'])}
    assert rows[here['artifact_id']]['size'] == blobs.STREAM_PIECE + 7
    assert all(row['storage'] == artifact_records.STORED and blobs.exists(store, row[artifact_records.BLOB_FIELD])
               for row in rows.values())
    assert BlobStore(store).erase_scope(SCOPE, 'erase-test') == 1
    assert not blobs.exists(store, rows[here['artifact_id']][artifact_records.BLOB_FIELD])
    assert blobs.exists(store, rows[there['artifact_id']][artifact_records.BLOB_FIELD])
    assert artifact_records.get(store, here['artifact_id'])['storage'] == artifact_records.ERASED
    assert blobs.delete(store, rows[here['artifact_id']][artifact_records.BLOB_FIELD]) is False, 'already gone'
