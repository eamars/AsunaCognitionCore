"""How long stored media bytes live: every kind of stored picture has an owner or an expiry.

A picture is stored in the BlobStore (`artifacts` rows, the blob store's bytes) for one of three reasons, named by the prefix
of its first source id:

- a copy pulled from a platform or a disk (`read_image`, a video's contact sheet): the platform or the disk is the
  source, so the copy expires after `PULLED_DAYS`, which is as long as `read_image` accepts its ref;
- a candidate in the sticker pool: kept while the pool or her shelf lists it (and for a day after it is stored);
- her records (a kept sticker, a picture she made or edited, one the owner sent at home): kept.

A copy that a lasting row still names (her shelf, the pool, a message that sent it) is kept whatever its age.

A file a task registered to send (`outbound_files`) keeps its bytes `outbound_files.KEEP_DAYS` after it was last
sent, or after it was registered when it never was, and while a message still on its way names it; then its bytes
go and its row stays as the record, with `storage` `removed` and `bytes_removed_at`.
A file someone sent her (`received_files`) keeps its bytes `received_files.KEEP_DAYS` after it was last fetched or
let go (`days_from`, else `created_at`); a kept one (`kept_at`) is not removed. Its row stays, as a task file's does.
`sweep` deletes the rest once at start and then daily; it reports what it removed and never raises for one bad row.
"""
from datetime import datetime, timedelta, timezone
from . import clock

PULLED_DAYS = 7
LISTED_GRACE_HOURS = 24          # a candidate's bytes are stored a moment before its pool row
PULLED, LISTED, RECORD, OFFERED, RECEIVED = 'pulled', 'listed', 'record', 'offered', 'received'
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
    'received-file:': RECEIVED,  # a file someone sent her, fetched when she read it (received_files)
}


def life(row):
    """The life cycle of an artifacts row: by its first source id; anything not listed is kept."""
    source = next(iter(row.get('source_ids') or ()), '')
    return next((cycle for prefix, cycle in POLICY.items() if str(source).startswith(prefix)), RECORD)


def named(store):
    """Artifact ids a lasting row names."""
    from . import stickers
    from .records import messages as message_records
    ids = stickers.artifact_ids(store)
    ids |= set(message_records.artifact_refs(store, 'attachment'))
    return ids


def sweep(store, now=None):
    """Delete expired pulled copies, unlisted pool candidates and the bytes of files past their days.

    Returns {'pulled': n, 'listed': n, 'files': n, 'received': n, 'bytes': n, 'failed': n, 'undated': n}: `files` the
    task files and `received` the received files whose bytes went, `failed` the rows that could not be swept, `undated`
    the rows kept because their time cannot be read (a time not known is never old)."""
    from .channels import Channels
    from .outbound_files import KEEP_DAYS
    from .received_files import KEEP_DAYS as RECEIVED_DAYS
    moment = now or clock.now()
    cutoff = {PULLED: moment - timedelta(days=PULLED_DAYS),
              LISTED: moment - timedelta(hours=LISTED_GRACE_HOURS),
              OFFERED: moment - timedelta(days=KEEP_DAYS),
              RECEIVED: moment - timedelta(days=RECEIVED_DAYS)}
    keep = named(store)
    from .records import messages as message_records
    going = set(message_records.artifact_refs(store, 'file', states=Channels.PART_ON_ITS_WAY))
    removed = {PULLED: 0, LISTED: 0, 'files': 0, RECEIVED: 0, 'copies': 0, 'bytes': 0, 'failed': 0, 'undated': 0}
    from .records import artifacts as artifact_records
    for row in artifact_records.stored(store).each(fields=['source_ids', 'created_at', artifact_records.BLOB_FIELD,
                                                           'size', 'last_sent_at', 'kept_at', 'days_from']):
        try:
            _sweep_one(store, row, moment, cutoff, keep, going, removed)
        except Exception:                       # noqa: BLE001 one bad row is counted; the rows after it still go
            removed['failed'] += 1
    from .received_files import drop_copies
    copies, stuck = drop_copies(store)          # received files' copies in task folders go with their bytes
    removed['copies'] += copies
    removed['failed'] += stuck
    return removed


def _sweep_one(store, row, moment, cutoff, keep, going, removed):
    from .records import artifacts as artifact_records
    cycle = life(row)
    if cycle == OFFERED:
        if row['_id'] in going or not _older(row.get('last_sent_at') or row.get('created_at'), cutoff[OFFERED], removed):
            return
        _remove_bytes(store, row, moment, removed, 'files')
        return
    if cycle == RECEIVED:
        if row.get('kept_at') or not _older(row.get('days_from') or row.get('created_at'), cutoff[RECEIVED], removed):
            return
        _remove_bytes(store, row, moment, removed, RECEIVED)
        return
    if cycle == RECORD or row['_id'] in keep:
        return
    if not _older(row.get('created_at'), cutoff[cycle], removed):
        return
    _delete_bytes(store, row)                   # bytes already gone: the row still goes
    artifact_records.delete(store, row['_id'])
    removed[cycle] += 1
    removed['bytes'] += _size(row)


def _delete_bytes(store, row):
    """A row's blob deleted when it names one; bytes already gone, or a blob that cannot be deleted now, leave the
    row's own change to go on."""
    from . import blobs
    from .records import artifacts as artifact_records
    try:
        if row.get(artifact_records.BLOB_FIELD):
            blobs.delete(store, row[artifact_records.BLOB_FIELD])
    except Exception:                           # noqa: BLE001 the row's change goes on
        pass


def _remove_bytes(store, row, moment, removed, count):
    """A file's bytes go and its row stays as the record, with `storage` `removed` and `bytes_removed_at`."""
    from .records import artifacts as artifact_records
    _delete_bytes(store, row)                   # bytes already gone: the row still says so
    artifact_records.bytes_removed(store, row['_id'], moment.isoformat())
    removed[count] += 1
    removed['bytes'] += _size(row)


def _older(value, cutoff, removed):
    """Whether a stored time is before the cutoff. A time that cannot be read (missing, not a time) is kept and counted
    in `undated`: a time not known is never old. A stored Date and an ISO string compare as moments, not as text; a
    stored time should carry its offset, and one without it (a naive Date, a string with no offset) is read as UTC,
    as the writers' `state.now()` gives it, never as undated."""
    moment = _moment(value)
    if moment is None:
        removed['undated'] += 1
        return False
    return moment < cutoff


def _moment(value):
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# Written out on purpose, apart from the keys `sweep` returns: the test holds the two lists equal, so a count added to
# the sweep and forgotten here fails it. Derive this from that list and the test can no longer fail (review M3b, 2026-10-27).
RECORDED = ('pulled', 'listed', 'files', 'received', 'copies', 'failed', 'undated')


def worth_recording(removed):
    """Whether a sweep's report is recorded as `media.swept`: something was removed, could not be swept, or was kept
    because its time cannot be read. A sweep that only found nothing to do leaves no record."""
    return any(removed.get(key) for key in RECORDED)


def _size(row):
    """A row's recorded size in bytes; 0 when it is not a number (the count is a report, never a reason to stop)."""
    try:
        return int(row.get('size') or 0)
    except (TypeError, ValueError):
        return 0
