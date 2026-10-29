"""What the owners of `episodes`, `sessions` and the receipts share: a named read (`View`) and the checks of a fence.

A view is a question with its order, answered through its verbs `rows` (`each` as they come), `first` and `count`.
Its order is the sort the replaced read wrote (none: the database's order); `newest_first` turns it. A view
whose condition is None is a question nothing can answer (a fence that holds nothing): every verb answers it without
a read.
"""
from ..store.words import And, Exists, IsNull, Or

ANY = object()          # a fence not given (None given is a fence that holds nothing)


def is_text(value):
    return isinstance(value, str) and bool(value)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def texts(values):
    return [value for value in values if is_text(value)]


def fenced(where, fences):
    """`where` with each fence given ({field: (value, kind check)}), or None when one holds nothing (a value missing or
    not of its kind)."""
    for path, (value, holds) in fences.items():
        if value is ANY:
            continue
        if not holds(value):
            return None
        where[path] = value
    return where


def pinned(where, pins):
    """The condition `where` with each value condition given ({field: (value, kind check)}), where a value of None
    stands for "has none": the field null or missing, as the replaced read's equality on null matched. None when
    `where` is None or a value is not of its kind (it holds nothing). A fence given None is `fenced`'s: nothing."""
    if where is None:
        return None
    nones = []
    for path, (value, holds) in pins.items():
        if value is ANY:
            continue
        if value is None:
            nones.append(Or({path: IsNull()}, {path: Exists(False)}))
        elif not holds(value):
            return None
        else:
            where[path] = value
    if not nones:
        return where
    return And(where, *nones) if where else (nones[0] if len(nones) == 1 else And(*nones))


# What a privacy erasure keeps of a record of the erased scope (ADR-105): its identity, state and hashes, never a body.
REDACTION_KEEPS = ('_id', 'schema_version', 'revision', 'scope_key', 'scene_id', 'source_event_id', 'episode_kind',
                   'publication_key', 'request_key', 'binding_key', 'content_hash', 'scene_seq', 'direction', 'author',
                   'adapter_id', 'platform_event_id')


def redact(store, collection, scope, deletion, epoch, *, left=lambda doc: False):
    """An erasure of `scope` in one collection: each record of the scope but those `left` holds is replaced whole by
    the fields kept (REDACTION_KEEPS), the deletion's id, its marks and the scope's new policy epoch. No revision and no
    commit: an erasure is a declared rebase, not a revision. A scope given None, or not text, changes nothing."""
    if not is_text(scope):
        return
    rows = store.collection(collection)
    for doc in rows.find({'scope_key': scope}):
        if left(doc):
            continue
        kept = {key: doc[key] for key in REDACTION_KEEPS if key in doc}
        kept.update(deletion_id=deletion, state='INVALIDATED', delivery_state='REDACTED', text='[deleted]',
                    policy_epoch=epoch)
        rows.replace(kept)


class View:
    """A named read on one collection: its condition and its order ((field, 1 | -1), ...)."""

    def __init__(self, store, collection, where, order=()):
        self.store, self.collection, self.where, self.order = store, collection, where, tuple(order)

    def _sort(self, newest_first):
        return tuple((path, -direction) for path, direction in self.order) if newest_first else self.order

    def each(self, newest_first=False, limit=None, skip=0, fields=None):
        """The rows, read as they come."""
        if self.where is None:
            return iter(())
        return self.store.collection(self.collection).find(self.where, self._sort(newest_first), skip, limit, fields)

    def rows(self, newest_first=False, limit=None, skip=0, fields=None):
        return list(self.each(newest_first, limit, skip, fields))

    def first(self, newest_first=False, fields=None):
        return next(iter(self.rows(newest_first, 1, 0, fields)), None)

    def count(self, limit=None):
        return 0 if self.where is None else self.store.collection(self.collection).count(self.where, limit)
