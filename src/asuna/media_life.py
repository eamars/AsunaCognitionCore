"""How long stored media bytes live: every kind of stored picture has an owner or an expiry.

A picture is stored in the BlobStore (`artifacts` rows, GridFS bytes) for one of three reasons, named by the prefix
of its first source id:

- a copy pulled from a platform or a disk (`read_image`, a video's contact sheet): the platform or the disk is the
  source, so the copy expires after `PULLED_DAYS`, which is as long as `read_image` accepts its ref;
- a candidate in the sticker pool: kept while the pool or her shelf lists it (and for a day after it is stored);
- her records (a kept sticker, a picture she made or edited, one the owner sent at home): kept.

A copy that a lasting row still names (her shelf, the pool, a message that sent it) is kept whatever its age.

A file a task registered to send (`outbound_files`) keeps its bytes `outbound_files.KEEP_DAYS` after it was last
sent, or after it was registered when it never was, and while a message still on its way names it; then its bytes
go and its row stays as the record, with `storage` `removed` and `bytes_removed_at`.
`sweep` deletes the rest once at start and then daily; it reports what it removed and never raises for one bad row.
"""
from datetime import datetime, timedelta, timezone

PULLED_DAYS = 7
LISTED_GRACE_HOURS = 24          # a candidate's bytes are stored a moment before its pool row
PULLED, LISTED, RECORD, OFFERED = 'pulled', 'listed', 'record', 'offered'
# source id prefix -> life cycle. A new kind of stored picture adds its prefix here (tests/test_media_life.py).
POLICY = {
    'in-': PULLED,               # read_image of a platform picture or a video (source: the message id)
    'file:': PULLED,             # read_image of a picture on disk
    'sticker-pool:': LISTED,     # a sticker pool candidate
    'sticker:': RECORD,          # a sticker on her shelf
    'integration:': RECORD,      # a picture she made
    'edit:': RECORD,             # a picture she edited
    'local-upload:': RECORD,     # a picture the owner sent her at home
    'task-file:': OFFERED,       # a file a task registered to send (outbound_files)
}


def life(row):
    """The life cycle of an artifacts row: by its first source id; anything not listed is kept."""
    source = next(iter(row.get('source_ids') or ()), '')
    return next((cycle for prefix, cycle in POLICY.items() if str(source).startswith(prefix)), RECORD)


def named(store):
    """Artifact ids a lasting row names."""
    db = store.db
    ids = set(db.stickers.distinct('artifact_id')) | set(db.sticker_pool.distinct('artifact_id'))
    ids |= set(db.messages.distinct('attachment.artifact_id', {'attachment.artifact_id': {'$exists': True}}))
    return ids


def sweep(store, now=None):
    """Delete expired pulled copies and unlisted pool candidates, and the bytes of files past their days; returns
    {'pulled': n, 'listed': n, 'files': n, 'bytes': n, 'failed': n}, `failed` the rows that could not be swept."""
    from gridfs import GridFSBucket
    from .channels import Channels
    from .outbound_files import KEEP_DAYS
    db = store.db
    bucket = GridFSBucket(db, bucket_name='artifact_blobs')
    moment = now or datetime.now(timezone.utc)
    cutoff = {PULLED: (moment - timedelta(days=PULLED_DAYS)).isoformat(),
              LISTED: (moment - timedelta(hours=LISTED_GRACE_HOURS)).isoformat(),
              OFFERED: (moment - timedelta(days=KEEP_DAYS)).isoformat()}
    keep = named(store)
    going = set(db.messages.distinct('file.artifact_id', {'file.artifact_id': {'$exists': True},
                                                          'delivery_state': {'$in': list(Channels.PART_ON_ITS_WAY)}}))
    removed = {PULLED: 0, LISTED: 0, 'files': 0, 'bytes': 0, 'failed': 0}
    for row in db.artifacts.find({'storage': 'gridfs'}, {'source_ids': 1, 'created_at': 1, 'gridfs_id': 1, 'size': 1,
                                                         'last_sent_at': 1}):
        try:
            _sweep_one(db, bucket, row, moment, cutoff, keep, going, removed)
        except Exception:                       # noqa: BLE001 one bad row is counted; the rows after it still go
            removed['failed'] += 1
    return removed


def _sweep_one(db, bucket, row, moment, cutoff, keep, going, removed):
    from bson import ObjectId
    from .outbound_files import REMOVED
    cycle = life(row)
    size = _size(row)
    if cycle == OFFERED:
        if row['_id'] in going or str(row.get('last_sent_at') or row.get('created_at') or '') > cutoff[OFFERED]:
            return
        try:
            if row.get('gridfs_id'):
                bucket.delete(ObjectId(row['gridfs_id']))
        except Exception:                       # noqa: BLE001 bytes already gone: the row still says so
            pass
        db.artifacts.update_one({'_id': row['_id']}, {'$set': {'storage': REMOVED, 'bytes_removed_at': moment.isoformat()},
                                                      '$unset': {'gridfs_id': ''}})
        removed['files'] += 1
        removed['bytes'] += size
        return
    if cycle == RECORD or row['_id'] in keep:
        return
    if str(row.get('created_at') or '') > cutoff[cycle]:
        return
    try:
        if row.get('gridfs_id'):
            bucket.delete(ObjectId(row['gridfs_id']))
    except Exception:                           # noqa: BLE001 bytes already gone: the row still goes
        pass
    db.artifacts.delete_one({'_id': row['_id']})
    removed[cycle] += 1
    removed['bytes'] += size


def _size(row):
    """A row's recorded size in bytes; 0 when it is not a number (the count is a report, never a reason to stop)."""
    try:
        return int(row.get('size') or 0)
    except (TypeError, ValueError):
        return 0
