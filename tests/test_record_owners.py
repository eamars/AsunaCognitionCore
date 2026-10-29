"""A collection whose owner has moved onto the store is reached only through that owner (ADR-104's B13 guard): the
call-site census finds no direct database call on it anywhere, nor on the blob store's bucket. Which module names a
collection to the store is the static check's (test_store_boundary.py)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / 'docs' / 'development_plans' / 'ADR-104-database-connector' / 'design' / 'call_site_map.py'
OWNERS = {'scenes': 'src/asuna/records/scenes.py', 'messages': 'src/asuna/records/messages.py',
          'episodes': 'src/asuna/records/episodes.py', 'sessions': 'src/asuna/records/sessions.py',
          'lane_receipts': 'src/asuna/records/receipts.py', 'sink_receipts': 'src/asuna/records/receipts.py',
          'tasks': 'src/asuna/records/tasks.py', 'task_messages': 'src/asuna/records/tasks.py',
          'plans': 'src/asuna/records/plans.py', 'memory_units': 'src/asuna/records/memories.py',
          'artifacts': 'src/asuna/records/artifacts.py',
          'state_heads': 'src/asuna/records/heads.py', 'state_revisions': 'src/asuna/records/heads.py',
          'journal_entries': 'src/asuna/documents.py', 'journal_revisions': 'src/asuna/documents.py',
          'identities': 'src/asuna/records/people.py', 'scene_people': 'src/asuna/records/people.py',
          'ideas': 'src/asuna/records/ideas.py'}
# The blob store: only the adapter reaches it (`blobs.py` through the store's blob interface), so the census finds no
# call on its bucket or its two collections anywhere.
BLOBS = ('gridfs:artifact_blobs', 'artifact_blobs.files', 'artifact_blobs.chunks')
# dbread is her MongoDB read tool (ADR-104 decision 9): its place lookup reads scenes over its own client.
ALLOWED = {'src/asuna/dbread.py'}
# The census puts every call of the store's vector search on memory_units: in its owner that is the owner's own call,
# and in the adapter's integration tests it searches the contract suite's own collection.
VECTORS = ('Store.nearest', 'Store.ensure_vectors')


def elsewhere(row):
    return not (row['method'] in VECTORS and (row['file'] == OWNERS[row['collection']]
                                              or row['file'].startswith('integration/')))


def census():
    spec = importlib.util.spec_from_file_location('call_site_map', CENSUS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.census()


def test_no_direct_database_call_reaches_a_moved_collection():
    found = ['%s:%s %s' % (row['file'], row['line'], row['method']) for row in census()
             if row['collection'] in OWNERS and row['file'] not in ALLOWED and elsewhere(row)]
    assert found == [], 'call the owner (%s) instead: %s' % (', '.join(OWNERS.values()), found[:10])


def test_no_code_reaches_the_blob_store_but_through_the_blob_interface():
    found = ['%s:%s %s' % (row['file'], row['line'], row['method']) for row in census()
             if row['collection'] in BLOBS and row['file'] not in ALLOWED]
    assert found == [], 'call asuna.blobs (BlobStore, open, delete, exists) instead: %s' % found[:10]


