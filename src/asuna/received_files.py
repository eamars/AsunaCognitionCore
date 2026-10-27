"""Files people send her (ADR-102): what she fetched is stored, and she keeps it or lets it go.

- **Storing** (`stash`): a fetched file becomes an artifacts row of its own kind, `received_file`, in the
  conversation's scope, `put_once` by sha256 within that kind: the file posted five times is stored once, and one equal
  to a file of hers never comes back as hers. The row keeps its origin for good (its source
  `received-file:<message id>:<index>`, its ref, the sender, the name, the sizes, the encoding, the marks).
- **Retention** (`media_life`'s RECEIVED cycle): the bytes go `KEEP_DAYS` after `days_from`, the moment of the last
  fetch or of `let_go`; the row stays, with `storage` `removed` and when its bytes went. A row with `kept_at` keeps its
  bytes.
- **Keeping** (`keep`, `let_go`, `kept`): within `QUOTA_BYTES` or `QUOTA_FILES`, whichever comes first. A keep over it is
  refused with the total and the `LEAST_READ` kept files read least recently that this call can let go; the others are
  counted, never named.

Every function that takes an artifact id also takes the scopes this call may reach (the fence, computed by the caller
as pictures' is) and checks them first, then ADR-105's mark: a row outside the fence is not found, whatever happened
to it. A kept file stays in its conversation's fence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .blobs import BlobStore, erased, erased_words, refuse_erased
from .outbound_files import removed, size_words
from .state import Denied, now

KIND = 'received_file'             # its own kind: put_once matches kind, so it is never matched to a file of hers
SOURCE = 'received-file:'          # the source id prefix (media_life.POLICY)
KEEP_DAYS = 3                      # the owner's decision 4 (ADR-102)
QUOTA_BYTES = 20 * 1024 * 1024
QUOTA_FILES = 50
LEAST_READ = 3
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)

NOT_FOUND = 'RECEIVED_FILE_NOT_FOUND: 这个对话里找不到这个文件；ref 照抄这个对话里给出的'
GONE_BEFORE_KEEP = ('RECEIVED_FILE_BYTES_GONE: 这个文件的字节在%s到期删了，留不下一份不在的字节；'
                    '先 read 一次（会从原处重新拉），拉回来了再 keep')
OVER_QUOTA = 'RECEIVED_FILE_OVER_QUOTA: 留不下：已经留着 %d 个文件，共 %s；最多留 %s 或 %d 个，加上这个（%s）就超了。%s'
LEAST_READ_HERE = '这里最久没读的：%s。放下一个（let_go）再留这个。'
OTHERS_ELSEWHERE = '另外 %d 个留在别的对话里，在那边才放得下。'
NONE_HERE = '留着的都在别的对话里，在那边才放得下。'
ALREADY_KEPT = '已经留着了（%s 留下的）'
KEPT = '留下了：不会到期删；现在留着 %d 个，共 %s（最多 %s 或 %d 个）。这个 ref 一直认得。'
NOT_KEPT = '这个文件本来就没留着，用不着放下'
LET_GO = '放下了：字节再留 %d 天，到 %s 删。'
REF_BY_MESSAGE = '从现在起 ref 靠它的消息找，到 %s 为止。'
REF_BY_MESSAGE_UNDATED = '从现在起 ref 靠它的消息找，消息在最近 %d 天里才找得到。'
REF_LOST = '它的消息已经超过 %d 天，从现在起这个 ref 就找不到了。'
LET_GO_ERASED = '从留着的里面拿掉了。'
QUOTA_LINE = '留着 %d 个，共 %s（最多 %s 或 %d 个）'


def source_of(message_id, index):
    return '%s%s:%d' % (SOURCE, message_id, int(index))


def stash(store, data, scope, *, message_id, index, name, sender, message_at=None, declared_size=None,
          encoding=None, marks=(), moment=None):
    """Store fetched bytes (already judged as text) in the conversation's scope; the same bytes there again are the
    row already stored, and their 3 days start again from this fetch."""
    from .vision import ref_of
    moment = moment or now()
    fields = {'ref': ref_of(message_id, index), 'name': str(name or '')[:255], 'sender': sender,
              'message_at': message_at, 'declared_size': declared_size, 'encoding': encoding, 'marks': list(marks),
              'days_from': moment}
    stored = BlobStore(store).put_once(data, scope, KIND, source_ids=[source_of(message_id, index)[:200]],
                                       fields=fields)
    if stored.get('deduplicated'):
        store.db.artifacts.update_one({'_id': stored['artifact_id']}, {'$set': {'days_from': moment}})
    return stored


def mark_read(store, artifact_id, scopes, moment=None):
    """A page of it was read: the time a quota refusal sorts by, written only inside the fence like everything here
    (her review of db192bdff79e: else another conversation's id could reorder whom a refusal names)."""
    store.db.artifacts.update_one({'_id': artifact_id, 'kind': KIND, 'state': 'DONE',
                                   'scope_key': {'$in': sorted(scopes)}}, {'$set': {'last_read_at': moment or now()}})


def _row(store, artifact_id, scopes):
    """The row inside the fence, else not found: the fence comes before anything the row could say."""
    row = store.db.artifacts.find_one({'_id': artifact_id, 'kind': KIND, 'state': 'DONE'})
    if not row or row.get('scope_key') not in set(scopes):
        raise Denied(NOT_FOUND)
    return row


def _kept_rows(store):
    """Every kept file whose bytes are stored, in all her conversations: what the quota counts."""
    return list(store.db.artifacts.find({'kind': KIND, 'kept_at': {'$exists': True}, 'storage': 'gridfs'}))


def _quota_words(rows):
    return QUOTA_LINE % (len(rows), size_words(sum(int(r.get('size') or 0) for r in rows)),
                         size_words(QUOTA_BYTES), QUOTA_FILES)


def _stamp(store, value, scene_id):
    from . import local_time
    return local_time.stamp(value, local_time.zone_of(store, scene_id))


def _entry(store, row, scene_id):
    entry = {'ref': row.get('ref'), 'name': row.get('name'), 'from': row.get('sender'),
             'size': size_words(row.get('size')), 'kept': _stamp(store, row.get('kept_at'), scene_id)}
    if row.get('kept_why'):
        entry['why'] = row['kept_why']
    return entry


def _when(value):
    """A stored time as a moment to sort by, never as text; one that cannot be read sorts first."""
    from .media_life import _moment
    return _moment(value) or EARLIEST


def _last_read(row):
    return row.get('last_read_at') or row.get('days_from') or row.get('created_at')


def keep(store, artifact_id, why, scopes, scene_id=None, moment=None):
    """Keep a file: its bytes are not removed until she lets it go; refused over the quota, in words she can act on."""
    row = _row(store, artifact_id, scopes)
    refuse_erased(store, row, scene_id)
    if removed(row):
        raise Denied(GONE_BEFORE_KEEP % _stamp(store, row.get('bytes_removed_at'), scene_id))
    why = str(why or '').strip()[:200]
    if row.get('kept_at'):
        if why:
            store.db.artifacts.update_one({'_id': row['_id']}, {'$set': {'kept_why': why}})
        return {'kept': True, 'note': ALREADY_KEPT % _stamp(store, row['kept_at'], scene_id)}
    rows = _kept_rows(store)
    size = int(row.get('size') or 0)
    if len(rows) + 1 > QUOTA_FILES or sum(int(r.get('size') or 0) for r in rows) + size > QUOTA_BYTES:
        raise Denied(_over_quota(store, rows, size, set(scopes), scene_id))
    change = {'kept_at': moment or now()}
    if why:
        change['kept_why'] = why
    store.db.artifacts.update_one({'_id': row['_id']}, {'$set': change})
    rows = _kept_rows(store)
    return {'kept': True, 'note': KEPT % (len(rows), size_words(sum(int(r.get('size') or 0) for r in rows)),
                                          size_words(QUOTA_BYTES), QUOTA_FILES)}


def _over_quota(store, rows, size, scopes, scene_id):
    here = sorted((r for r in rows if r.get('scope_key') in scopes), key=lambda r: _when(_last_read(r)))
    elsewhere = len(rows) - len(here)
    if here:
        named = '；'.join('「%s」（%s，%s，上次读 %s）' % (r.get('name'), r.get('ref'), size_words(r.get('size')),
                                                       _stamp(store, _last_read(r), scene_id))
                         for r in here[:LEAST_READ])
        tail = LEAST_READ_HERE % named + (OTHERS_ELSEWHERE % elsewhere if elsewhere else '')
    else:
        tail = NONE_HERE
    total = sum(int(r.get('size') or 0) for r in rows)
    return OVER_QUOTA % (len(rows), size_words(total), size_words(QUOTA_BYTES), QUOTA_FILES, size_words(size), tail)


def let_go(store, artifact_id, scopes, scene_id=None, moment=None):
    """End a keep: the bytes have their 3 days from now, and the ref is found by its message again, as long as that is
    found. An erased kept file is taken off the list with ADR-105's sentence."""
    from .media_life import _moment
    from .vision import REF_DAYS
    row = _row(store, artifact_id, scopes)
    if erased(row):
        store.db.artifacts.update_one({'_id': row['_id']}, {'$unset': {'kept_at': '', 'kept_why': ''}})
        return {'let_go': True, 'note': erased_words(store, row, scene_id) + LET_GO_ERASED}
    if not row.get('kept_at'):
        return {'let_go': False, 'note': NOT_KEPT}
    moment = moment or now()
    store.db.artifacts.update_one({'_id': row['_id']}, {'$set': {'days_from': moment, 'let_go_at': moment},
                                                        '$unset': {'kept_at': '', 'kept_why': ''}})
    start = _moment(moment)
    note = LET_GO % (KEEP_DAYS, _stamp(store, (start + timedelta(days=KEEP_DAYS)).isoformat(), scene_id))
    sent = _moment(row.get('message_at'))
    if sent is not None and sent + timedelta(days=REF_DAYS) <= start:
        note += REF_LOST % REF_DAYS
    elif sent is not None:
        note += REF_BY_MESSAGE % _stamp(store, (sent + timedelta(days=REF_DAYS)).isoformat(), scene_id)
    else:
        note += REF_BY_MESSAGE_UNDATED % REF_DAYS
    return {'let_go': True, 'note': note}


def kept(store, scopes, scene_id=None):
    """What she keeps that this call may reach, newest first; an erased one carries ADR-105's sentence, and the files
    kept in other conversations are counted, never named, with the quota's ruler (kept files whose bytes are stored),
    so the two counts on one screen add up (her review of db192bdff79e)."""
    scopes = set(scopes)
    rows = sorted(store.db.artifacts.find({'kind': KIND, 'kept_at': {'$exists': True}}),
                  key=lambda r: _when(r.get('kept_at')), reverse=True)
    entries = []
    for row in (r for r in rows if r.get('scope_key') in scopes):
        entry = _entry(store, row, scene_id)
        if erased(row):
            entry['erased'] = erased_words(store, row, scene_id)
        entries.append(entry)
    stored = _kept_rows(store)
    out = {'kept': entries, 'quota': _quota_words(stored)}
    elsewhere = sum(1 for r in stored if r.get('scope_key') not in scopes)
    if elsewhere:
        out['elsewhere'] = OTHERS_ELSEWHERE % elsewhere
    return out
