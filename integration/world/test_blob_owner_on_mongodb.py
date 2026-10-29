"""ADR-104 B8 on MongoDB, kept by ADR-104 decision 9 (a break would lose her data): an erasure deletes the blobs of its
own scopes and no other's."""
import io

import pytest

from asuna import blobs
from asuna.blobs import BlobStore
from asuna.records import artifacts as artifact_records

pytestmark = pytest.mark.world                # `store` is the fixture world

SCOPE, OTHER = 'scene:dm-a', 'scene:dm-b'


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
