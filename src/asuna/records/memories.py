"""The owner of `memory_units`: her recall (the chat chunks of her conversations, their summaries, her thoughts,
imported entries) and its vector space, read and written only through these operations.

`get` returns a memory as stored (`fields` names what to return, or `Without(...)` what to leave out; `_id` always
comes back), within the fences given. None follows section 4's rule: an id or a fence (scope, epoch, character, turn,
a (scope, epoch) pair) given None, or a value not of its kind, finds nothing without a read; a pair that is not a text
scope and a number epoch is left out of the pairs, and no pair left finds nothing. A value condition (a kind, a status,
where a thought came from, a memory's epistemic type) given None finds the memories whose field is null or missing.
The other reads are views (`View`: `rows`, `each`, `first`, `count`), in the replaced read's order (none where it had
none). `save` is the revisioned write (`Store.put`); `tombstone`, `set_epoch` and `touch_salience` the erasure's and
recall's own writes. `nearest` is the space's exact vector search, its pairs an `Or` of the pairs' conditions.
"""
from ..store.catalog import Space
from ..store.words import And, AnyOf, Contains, Holds, HoldsAny, Increase, NoneOf, Not, Or, Set, Without
from .view import ANY, View, fenced, is_number, is_text, pinned, texts

COLLECTION = 'memory_units'
ALIVE, ERASED = 'active', 'tombstone'
# kind: her own thoughts in other conversations are searched apart from their talk (retrieval's own_thoughts).
SPACE = Space(name='asuna_memory_v1', collection=COLLECTION, path='embedding', dimensions=768,
              fields=('scope_key', 'character_id', 'status', 'policy_epoch', 'embedding_revision', 'kind'))
# The Web memory page's own time of a memory: the first of these it has (a summary when it was made, a line when it
# was said, a thought when she formed it).
OWN_TIME = ('generated_at', 'occurred_at', 'formed_at')
# A memory but its vector (`fields` of a read): what a recall reads of one.
UNVECTORED = Without(SPACE.path)


def _view(store, where, by=()):
    by = (by,) if isinstance(by, str) else tuple(by)
    return View(store, COLLECTION, where, tuple((path, 1) for path in by))


def _pairs(pairs):
    """The conditions of (scope, epoch) pairs, an `Or` of each pair's: None when no pair is a text scope and a number
    epoch (it holds nothing)."""
    branches = [{'scope_key': scope, 'policy_epoch': epoch} for scope, epoch in (tuple(pair) for pair in pairs)
                if is_text(scope) and is_number(epoch)]
    return Or(*branches) if branches else None


def _where(where, *, pairs=ANY, fences=None, pins=None):
    """`where` with its fences, value conditions and pairs, or None when one of them holds nothing (pairs given None
    included)."""
    where = fenced(where, fences or {})
    where = pinned(where, pins or {}) if where is not None else None
    if where is None or pairs is ANY:
        return where
    if not isinstance(pairs, (list, tuple, set)):
        return None
    either = _pairs(pairs)
    if either is None:
        return None
    return And(where, either) if where else either


def _fences(scope=ANY, epoch=ANY, episode=ANY, character=ANY):
    return {'scope_key': (scope, is_text), 'policy_epoch': (epoch, is_number), 'episode_id': (episode, is_text),
            'character_id': (character, is_text)}


def _pins(kind=ANY, status=ANY, source=ANY, epistemic=ANY):
    return {'kind': (kind, is_text), 'status': (status, is_text), 'source': (source, is_text),
            'epistemic_type': (epistemic, is_text)}


# Single records.

def get(store, memory_id, fields=None, *, pairs=ANY, scope=ANY, epoch=ANY, episode=ANY, character=ANY, kind=ANY,
        kinds=ANY, status=ANY, erased=ANY):
    """The memory with this id (in these (scope, epoch) pairs; of this scope, epoch, turn, character; of this kind or
    one of these; in this status; `erased=False`: not a tombstone), or None."""
    if not is_text(memory_id):
        return None
    if pairs is ANY and kinds is ANY and erased is ANY and all(
            value is ANY for value in (scope, epoch, episode, character, kind, status)):
        return store.collection(COLLECTION).get(memory_id, fields)
    where = {'_id': memory_id}
    if kinds is not ANY:
        if not isinstance(kinds, (list, tuple, set)):
            return None
        where['kind'] = AnyOf(texts(kinds))
    if erased is not ANY:
        where['status'] = Not(ERASED) if erased is False else ERASED
    where = _where(where, pairs=pairs, fences=_fences(scope, epoch, episode, character), pins=_pins(kind, status))
    return _view(store, where).first(fields=fields)


def summary_of(store, source_id, *, scope, epoch, fields=None):
    """The alive summary of a conversation's epoch that covers this line, or None."""
    if not is_text(source_id):
        return None
    where = _where({'kind': 'dialogue_summary', 'status': ALIVE, 'source_event_ids': Holds(source_id)},
                   fences=_fences(scope=scope, epoch=epoch))
    return _view(store, where).first(fields=fields)


# Views.

def many(store, memory_ids, *, pairs=ANY, scope=ANY, character=ANY, kind=ANY, status=ANY):
    """View: the memories with these ids (in these (scope, epoch) pairs; of this scope and character; of this kind; in
    this status)."""
    return _view(store, _where({'_id': AnyOf(texts(memory_ids))}, pairs=pairs,
                               fences=_fences(scope=scope, character=character), pins=_pins(kind, status)))


def readable(store, pairs, *, character=ANY, kind=ANY, by=()):
    """View: the alive memories in these (scope, epoch) pairs (of this character; of this kind), ordered by `by`."""
    return _view(store, _where({'status': ALIVE}, pairs=pairs, fences=_fences(character=character),
                               pins=_pins(kind=kind)), by)


def of_kind(store, kind, *, scope=ANY, scopes=ANY, character=ANY, source=ANY, status=ANY, by=()):
    """View: the memories of a kind (in a scope or one of these; of this character; from this source, as where a
    thought came from; in this status), ordered by `by`."""
    if not (scopes is ANY or isinstance(scopes, (list, tuple, set))):
        return _view(store, None)
    where = {} if scopes is ANY else {'scope_key': AnyOf(texts(scopes))}
    return _view(store, _where(where, fences=_fences(scope=scope, character=character),
                               pins=_pins(kind=kind, status=status, source=source)), by)


def pending_index(store, revision, *, scope=ANY, epoch=ANY):
    """View: the alive memories waiting for their vector (neither READY nor REFUSED), or embedded by another revision
    than `revision` (of this scope and epoch)."""
    waiting = Or({'embedding_status': NoneOf(['READY', 'REFUSED'])}, {'embedding_revision': Not(revision)})
    where = _where({'status': ALIVE}, fences=_fences(scope=scope, epoch=epoch))
    return _view(store, None if where is None else And(where, waiting))


def dependents(store, scope, sources):
    """View: the memories of a scope that depend on these sources or cite them."""
    where = fenced({}, {'scope_key': (scope, is_text)})
    sources = texts(sources)
    return _view(store, None if where is None else And(
        where, Or({'depends_on': HoldsAny(sources)}, {'source_event_ids': HoldsAny(sources)})))


def of_scope(store, scope):
    """View: every memory of a scope."""
    return _view(store, fenced({}, {'scope_key': (scope, is_text)}))


def alive(store):
    """View: every alive memory."""
    return _view(store, {'status': ALIVE})


def web_page(store, pairs, character, *, epistemic=ANY, search=None, skip=0, limit, fields):
    """The Web memory page's memories: the alive ones in these (scope, epoch) pairs of this character (of this
    epistemic type; whose text contains `search`, case-blind), newest first by their own time (OWN_TIME: the first of
    them a memory holds; those with none last), then by id; `limit` of them after `skip`. Each holds `fields` and its
    own time as `_memory_time`. Read as the matching memories' own times, ordered here, then the page's memories by
    id under the same condition (one that stopped matching between the two reads is left out)."""
    where = _where({'status': ALIVE}, pairs=pairs, fences=_fences(character=character), pins=_pins(epistemic=epistemic))
    if where is None or not limit:
        return []
    if search:
        where = And(where, {'body_markdown': Contains(search, case=False)})
    times = {row['_id']: _own_time(row) for row in _view(store, where).each(fields=list(OWN_TIME))}
    page = sorted(times, key=lambda key: (times[key] is not None, times[key] or '', key), reverse=True)
    page = page[skip:skip + limit]
    if not page:
        return []
    found = {row['_id']: row for row in _view(store, And(where, {'_id': AnyOf(page)})).each(
        fields=[*fields, *(path for path in OWN_TIME if path not in fields)])}
    rows = [found[key] for key in page if key in found]
    for row in rows:
        row['_memory_time'] = _own_time(row)
    return rows


def _own_time(row):
    return next((row[path] for path in OWN_TIME if row.get(path) is not None), None)


# Writes.

def save(store, memory, **kwargs):
    """The revisioned write of a whole memory (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, memory, **kwargs)


def tombstone(store, memory, deletion, epoch):
    """An erasure's tombstone in place of the memory: its id, scope and next revision, no text, no sources, the
    erasure's id and the conversation's new epoch."""
    store.collection(COLLECTION).replace({
        '_id': memory['_id'], 'schema_version': 1, 'revision': memory['revision'] + 1, 'scope_key': memory['scope_key'],
        'status': ERASED, 'deletion_id': deletion, 'body_markdown': '', 'source_event_ids': [], 'policy_epoch': epoch})


def set_epoch(store, memory_id, epoch):
    """Move a memory to an epoch (an erasure keeps what it did not erase readable in the new one)."""
    store.collection(COLLECTION).update({'_id': memory_id}, Set({'policy_epoch': epoch}))


def touch_salience(store, memory_id, moment, seq):
    """A real turn used the memory: one more reference, and when and at which position of its conversation."""
    store.collection(COLLECTION).update({'_id': memory_id}, [
        Increase('salience.ref_count'), Set({'salience.last_ref_at': moment, 'salience.last_ref_seq': seq})])


# The vector space.

def ensure_vectors(store, timeout=45):
    """The space's search index, made or brought up to the space's filter fields; True once it can be queried."""
    return store.ensure_vectors(SPACE, timeout)


def nearest(store, vector, k, pairs, *, character, revision, status=ALIVE, kind=ANY):
    """The k memories nearest to `vector` in these (scope, epoch) pairs, of this character, status and embedding
    revision (of this kind), best first as (id, cosine); exact. No pair finds nothing, without a search."""
    either = _pairs(pairs)
    if either is None:
        return []                                   # any of no pair: nothing matches
    values = {'character_id': character, 'status': status, 'embedding_revision': revision}
    if kind is not ANY:
        values['kind'] = kind
    return store.nearest(SPACE, vector, k, And(values, either))
