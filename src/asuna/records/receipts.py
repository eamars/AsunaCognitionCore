"""The owner of `lane_receipts` and `sink_receipts`: what a model lane answered for an operation (its result, kept so
a replay answers the same), and what a sink received (a publication's delivery, her self-development publications
and their states, the native inputs projected), read and written only through these operations.

`lane_get` and `sink_get` return a receipt as stored (`fields` names what to return, `_id` always comes back); an
id that is missing or not text finds nothing. The other reads are views (`View`: `rows`, `first`, `count`), in the
database's order unless an operation names its order. `save_lane` and `save_sink` are the revisioned writes
(`Store.put`).
"""
from ..store.words import AnyOf, Not, Range
from .view import ANY, View, fenced, is_text, texts

LANES, SINKS = 'lane_receipts', 'sink_receipts'


# Lane receipts.

def lane_get(store, operation, fields=None):
    """The lane's receipt of this operation, or None."""
    return store.collection(LANES).get(operation, fields) if is_text(operation) else None


def lane_of_sessions(store, session_ids):
    """The lane receipts of these sessions."""
    return View(store, LANES, {'session_id': AnyOf(texts(session_ids))}).rows()


def lane_invalidate(store, operation, deletion_id):
    """An erasure replaced this lane receipt by its invalidated form (its result and request gone)."""
    store.collection(LANES).replace({'_id': operation, 'schema_version': 1, 'scope_key': 'operator',
                                     'state': 'INVALIDATED', 'deletion_id': deletion_id})


def save_lane(store, receipt, **kwargs):
    """The revisioned write of a lane receipt (`Store.put`)."""
    return store.put(LANES, receipt, **kwargs)


# Sink receipts.

def sink_get(store, receipt_id, fields=None):
    """The sink's receipt with this id, or None."""
    return store.collection(SINKS).get(receipt_id, fields) if is_text(receipt_id) else None


def sinks(store, receipt_ids=None):
    """View: the sink receipts with these ids (None: every one)."""
    return View(store, SINKS, {} if receipt_ids is None else {'_id': AnyOf(texts(receipt_ids))})


def sink_of_kind(store, kind, *, state=None, states=None, project=ANY, besides=None, by=None):
    """View: the sink receipts of a kind (in a state or one of several; of a project; but one), ordered by `by`
    (None: the database's order)."""
    where = fenced({'kind': kind}, {'project': (project, is_text)})
    if where is not None:
        if state is not None:
            where['state'] = state
        if states is not None:
            where['state'] = AnyOf(list(states))
        if besides is not None:
            where['_id'] = Not(besides)
    return View(store, SINKS, where, ((by, 1),) if by else ())


def sink_window(store, *, gte=None, lte=None, lt=None):
    """View: the sink receipts received within these bounds (text times as the core writes them), ordered by when
    they were received, then by id."""
    bounds = {name: value for name, value in (('gte', gte), ('lte', lte), ('lt', lt)) if value is not None}
    return View(store, SINKS, {'received_at': Range(**bounds)} if bounds else {},
                (('received_at', 1), ('_id', 1)))


def save_sink(store, receipt, **kwargs):
    """The revisioned write of a sink receipt (`Store.put`)."""
    return store.put(SINKS, receipt, **kwargs)
