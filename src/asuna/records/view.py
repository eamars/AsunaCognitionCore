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


def none_or(where, path, value):
    """`where` and `path` equal to `value`, where a value of None stands for "has none": the field null or missing,
    as the replaced read's equality on null matched."""
    if value is not None:
        return {**where, path: value}
    return And(where, Or({path: IsNull()}, {path: Exists(False)})) if where else Or({path: IsNull()},
                                                                                    {path: Exists(False)})


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
