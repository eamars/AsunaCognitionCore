"""How long stored media bytes live: every kind of stored picture and voice has an owner or an expiry.

Media is stored in the BlobStore (`artifacts` rows, GridFS bytes) for one of four reasons, named by the prefix of its
first source id:

- a copy pulled from a platform or a disk (`read_image`, a video's contact sheet): the platform or the disk is the
  source, so the copy expires after `PULLED_DAYS`, which is as long as `read_image` accepts its ref;
- a candidate in the sticker pool: kept while the pool or her shelf lists it (and for a day after it is stored);
- her records (a kept sticker, a picture she made or edited, one the owner sent at home): kept;
- a voice message's audio: kept only until its text is extracted, then deleted by voice.py, whatever came of it; the
  sweep leaves it alone.

A copy that a lasting row still names (her shelf, the pool, a message that sent it) is kept whatever its age.
`sweep` deletes the rest once at start and then daily; it reports what it removed and never raises for one bad row.
"""
from datetime import datetime, timedelta, timezone

PULLED_DAYS = 7
LISTED_GRACE_HOURS = 24          # a candidate's bytes are stored a moment before its pool row
PULLED, LISTED, RECORD, VOICE = 'pulled', 'listed', 'record', 'voice'
# source id prefix -> life cycle. A new kind of stored picture adds its prefix here (tests/test_media_life.py).
POLICY = {
    'in-': PULLED,               # read_image of a platform picture or a video (source: the message id)
    'file:': PULLED,             # read_image of a picture on disk
    'sticker-pool:': LISTED,     # a sticker pool candidate
    'sticker:': RECORD,          # a sticker on her shelf
    'integration:': RECORD,      # a picture she made
    'edit:': RECORD,             # a picture she edited
    'local-upload:': RECORD,     # a picture the owner sent her at home
    'voice:': VOICE,             # a voice message's audio until its text is extracted (voice.SOURCE, voice.drop_audio)
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
    """Delete expired pulled copies and unlisted pool candidates; returns {'pulled': n, 'listed': n, 'bytes': n}."""
    from bson import ObjectId
    from gridfs import GridFSBucket
    db = store.db
    bucket = GridFSBucket(db, bucket_name='artifact_blobs')
    moment = now or datetime.now(timezone.utc)
    cutoff = {PULLED: (moment - timedelta(days=PULLED_DAYS)).isoformat(),
              LISTED: (moment - timedelta(hours=LISTED_GRACE_HOURS)).isoformat()}
    keep = named(store)
    removed = {PULLED: 0, LISTED: 0, 'bytes': 0}
    for row in db.artifacts.find({'storage': 'gridfs'}, {'source_ids': 1, 'created_at': 1, 'gridfs_id': 1, 'size': 1}):
        cycle = life(row)
        if cycle in (RECORD, VOICE) or row['_id'] in keep:
            continue
        if str(row.get('created_at') or '') > cutoff[cycle]:
            continue
        try:
            if row.get('gridfs_id'):
                bucket.delete(ObjectId(row['gridfs_id']))
        except Exception:                       # noqa: BLE001 bytes already gone: the row still goes
            pass
        db.artifacts.delete_one({'_id': row['_id']})
        removed[cycle] += 1
        removed['bytes'] += int(row.get('size') or 0)
    return removed
