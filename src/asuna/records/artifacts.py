"""The owner of `artifacts`: the rows of what she and the program keep apart from the conversation (stored files and
pictures with their bytes' manifest, the action brain's tool records, held notices and passed lines, requests and
group actions, a channel's admissions and declared functions, a peer line's state), read and written only through
these operations.

`get` returns a row as stored (`fields` names what to return; `_id` always comes back), within the fences given.
None follows section 4's rule: an id or a fence (the task and its revision, the conversation, the scope or scopes,
the channel) given None, or a value not of its kind, finds nothing without a read; a value condition (a kind, a
state, a storage, a tool) given None finds the rows whose field is null or missing. The other reads are views
(`View`: `rows`, `each`, `first`, `count`), in the replaced read's order (none where it had none). `save` is the
revisioned write (`Store.put`); `insert` and `replace` the unrevisioned ones of the rows written so; the other writes
change named fields of one row, or a scope's rows at its erasure.

Two names are stored in her data as the MongoDB era wrote them and stay (renaming them is a data migration): a row
whose bytes are in the blob store says `storage` `STORED` ('gridfs'), and names its blob in `BLOB_FIELD`
('gridfs_id').
"""
from ..store.words import AddToSet, AnyOf, Exists, Holds, NonEmpty, Not, Range, Set, Unset
from .view import ANY, View, fenced, is_number, is_text, pinned, redact, texts

COLLECTION = 'artifacts'
STORED = 'gridfs'               # a row's `storage` while its bytes are in the blob store (a stored name)
BLOB_FIELD = 'gridfs_id'        # the field naming its blob (a stored name)
REMOVED = 'removed'             # a row's `storage` once its bytes expired (the row stays as the record)
ERASED = 'erased'               # a row's `storage` once a privacy erasure deleted its bytes (ADR-105)


def _view(store, where, by=()):
    by = (by,) if isinstance(by, str) else tuple(by)
    return View(store, COLLECTION, where, tuple((path, 1) for path in by))


def _where(where, *, fences=None, pins=None, scopes=None):
    """`where` with its fences, its scopes (an any-of, when given) and its value conditions, or None when one of them
    holds nothing."""
    where = fenced(where, fences or {})
    if where is not None and scopes is not None:
        where['scope_key'] = AnyOf(texts(scopes))
    return pinned(where, pins or {}) if where is not None else None


def _fences(task=ANY, revision=ANY, scene=ANY, scope=ANY, channel=ANY):
    return {'task_id': (task, is_text), 'intent_revision': (revision, is_number), 'scene_id': (scene, is_text),
            'scope_key': (scope, is_text), 'channel_id': (channel, is_text)}


def _pins(kind=ANY, state=ANY, storage=ANY, tool=ANY):
    return {'kind': (kind, is_text), 'state': (state, is_text), 'storage': (storage, is_text),
            'tool': (tool, is_text)}


# Single records.

def get(store, artifact_id, fields=None, *, kind=ANY, state=ANY, storage=ANY, task=ANY, revision=ANY, scopes=None):
    """The row with this id (of this kind, in this state and storage; of this task and its revision; in one of these
    scopes), or None."""
    if not is_text(artifact_id):
        return None
    if scopes is None and all(value is ANY for value in (kind, state, storage, task, revision)):
        return store.collection(COLLECTION).get(artifact_id, fields)
    where = _where({'_id': artifact_id}, fences=_fences(task=task, revision=revision), pins=_pins(kind, state, storage),
                   scopes=scopes)
    return _view(store, where).first(fields=fields)


def by_content(store, sha256, kind, *, scope=ANY, scopes=None, state=ANY, storage=ANY, source=ANY, by=(),
               newest_first=False, fields=None):
    """The first row holding these bytes (their sha256) of a kind (in this scope or one of these; in this state and
    storage; listing this source), by `by` (`newest_first` turns it); None when there is none."""
    if not is_text(sha256):
        return None
    where = {'sha256': sha256}
    if source is not ANY:
        if not is_text(source):
            return None
        where['source_ids'] = Holds(source)
    where = _where(where, fences=_fences(scope=scope), pins=_pins(kind, state, storage), scopes=scopes)
    return _view(store, where, by).first(newest_first=newest_first, fields=fields)


def answer(store, kind, answer_id):
    """The row of a kind that this answer settles (a request her group action answered), or None."""
    if not is_text(answer_id):
        return None
    return _view(store, _where({'answer': answer_id}, pins=_pins(kind=kind))).first()


# Views.

def by_ids(store, artifact_ids, *, storage=ANY):
    """View: the rows with these ids (in this storage)."""
    return _view(store, _where({'_id': AnyOf(texts(artifact_ids))}, pins=_pins(storage=storage)))


def of_task(store, task_id, revision, *, state=ANY, states=None):
    """View: the rows of a task's revision (its tool records) in this state or one of these."""
    where = {} if states is None else {'state': AnyOf(list(states))}
    return _view(store, _where(where, fences=_fences(task=task_id, revision=revision), pins=_pins(state=state)))


def of_tasks(store, task_ids):
    """View: the rows of these tasks."""
    return _view(store, {'task_id': AnyOf(texts(task_ids))})


def of_kind(store, kind, *, state=ANY, storage=ANY, scope=ANY, scopes=None, source=ANY, by=()):
    """View: the rows of a kind (in this state and storage; in this scope or one of these; listing this source),
    ordered by `by`."""
    where = {}
    if source is not ANY:
        if not is_text(source):
            return _view(store, None)
        where['source_ids'] = Holds(source)
    return _view(store, _where(where, fences=_fences(scope=scope), pins=_pins(kind, state, storage), scopes=scopes),
                 by)


def of_scene(store, kind, scene_id, *, by='received_at'):
    """View: the rows of a kind held for a conversation (notices, passed lines), by when they came."""
    return _view(store, _where({}, fences=_fences(scene=scene_id), pins=_pins(kind=kind)), by)


def admission(store, kind, channel_id, state, *, claimed_since=ANY, by=()):
    """View: a channel's rows of a kind in a state (claimed at or after `claimed_since`, an ISO time), ordered by
    `by`: the outbox's group actions, the one in flight and the next queued."""
    where = {}
    if claimed_since is not ANY:
        if not is_text(claimed_since):
            return _view(store, None)
        where['claimed_at'] = Range(gte=claimed_since)
    return _view(store, _where(where, fences=_fences(channel=channel_id), pins=_pins(kind=kind, state=state)), by)


def kept(store, kind, *, stored=False, state=ANY, ref=ANY, scopes=None):
    """View: the kept rows of a kind (`stored`: whose bytes are in the blob store; in this state; of this ref; in one
    of these scopes)."""
    where = {'kept_at': Exists(True)}
    if ref is not ANY:
        if not is_text(ref):
            return _view(store, None)
        where['ref'] = ref
    if stored:
        where['storage'] = STORED
    return _view(store, _where(where, pins=_pins(kind=kind, state=state), scopes=scopes))


def with_copies(store, kind, *, besides_storage):
    """View: the rows of a kind with copies in task folders, whose storage is not `besides_storage`."""
    return _view(store, _where({'storage': Not(besides_storage), 'copies': NonEmpty()}, pins=_pins(kind=kind)))


def stored(store):
    """View: every row whose bytes are in the blob store."""
    return _view(store, {'storage': STORED})


def count_tool(store, tool, state):
    """How many rows of a tool are in a state."""
    return _view(store, _where({}, pins=_pins(state=state, tool=tool))).count()


# Writes.

def save(store, row, **kwargs):
    """The revisioned write of a whole row (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, row, **kwargs)


def redact_scope(store, scope, deletion, epoch):
    """An erasure of a scope's rows (`view.redact`); a row whose bytes the erasure deleted (`ERASED`) keeps its marks
    (ADR-105: its name, size, sender and when stay, and every reader says it was erased)."""
    redact(store, COLLECTION, scope, deletion, epoch, left=lambda row: row.get('storage') == ERASED)


def insert(store, row):
    """A new row written as it is, without a revision (a held notice, a passed line, a channel's declared functions)."""
    store.collection(COLLECTION).insert(row)


def replace(store, row):
    """The row of this id replaced by `row`, as it is; False when there is none."""
    return store.collection(COLLECTION).replace(row)


def delete(store, artifact_id):
    """Delete one row."""
    return store.collection(COLLECTION).delete({'_id': artifact_id})


def delete_many(store, artifact_ids, *, kind=ANY):
    """Delete the rows with these ids (of this kind); how many went."""
    where = _where({'_id': AnyOf(texts(artifact_ids))}, pins=_pins(kind=kind))
    return 0 if where is None else store.collection(COLLECTION).delete(where, many=True)


def _set(store, artifact_id, change, where=None):
    return store.collection(COLLECTION).update({'_id': artifact_id, **(where or {})}, change)


def mark_read(store, artifact_id, kind, scopes, moment):
    """A page of a stored file of a kind was read (only inside these scopes, in state DONE): `last_read_at`."""
    return _set(store, artifact_id, Set({'last_read_at': moment}),
                {'kind': kind, 'state': 'DONE', 'scope_key': AnyOf(texts(scopes))})


def mark_sent(store, artifact_id, kind, moment):
    """A row of a kind was sent: `last_sent_at`."""
    return _set(store, artifact_id, Set({'last_sent_at': moment}), {'kind': kind})


def restore_bytes(store, artifact_id, blob_id, moment):
    """Bytes fetched again are back on a row whose bytes expired, if it is still `REMOVED`; whether it was."""
    done = _set(store, artifact_id, [Set({'storage': STORED, BLOB_FIELD: blob_id, 'refetched_at': moment}),
                                     Unset('bytes_removed_at')], {'storage': REMOVED})
    return bool(done.changed)


def bytes_removed(store, artifact_id, moment):
    """A row's bytes went (expired): `storage` `REMOVED` with when, its blob no longer named."""
    return _set(store, artifact_id, [Set({'storage': REMOVED, 'bytes_removed_at': moment}), Unset(BLOB_FIELD)])


def erase_scope(store, scope, moment, deletion):
    """Every row of a scope whose bytes are stored or expired, marked `ERASED` by this erasure (ADR-105)."""
    if not is_text(scope):
        return None
    return store.collection(COLLECTION).update(
        {'scope_key': scope, 'storage': AnyOf([STORED, REMOVED])},
        [Set({'storage': ERASED, 'erased_at': moment, 'deletion_id': deletion}), Unset(BLOB_FIELD)], many=True)


def set_days_from(store, artifact_id, moment, *, source=None):
    """A stored file's days start again from `moment` (and it lists `source` too)."""
    change = [Set({'days_from': moment})]
    if source is not None:
        change.append(AddToSet('source_ids', source))
    return _set(store, artifact_id, change)


def set_fields(store, artifact_id, values):
    """Set these fields of a row (a kept file's `kept_at` and `kept_why`)."""
    return _set(store, artifact_id, Set(values))


def keep_why(store, artifact_id, why):
    return _set(store, artifact_id, Set({'kept_why': why}))


def unkeep(store, artifact_id):
    """A kept file is kept no more (an erased one leaves the list)."""
    return _set(store, artifact_id, Unset('kept_at', 'kept_why'))


def let_go(store, artifact_id, moment):
    """A kept file let go: its days start from `moment`."""
    return _set(store, artifact_id, [Set({'days_from': moment, 'let_go_at': moment}), Unset('kept_at', 'kept_why')])


def set_received_from(store, artifact_id, origin):
    """Where a file a task registered came from (a received file with its bytes)."""
    return _set(store, artifact_id, Set({'received_from': origin}))


def add_copy(store, artifact_id, path):
    """A copy of a stored file in a task folder."""
    return _set(store, artifact_id, AddToSet('copies', path))


def set_copies(store, artifact_id, copies):
    return _set(store, artifact_id, Set({'copies': list(copies)}))
