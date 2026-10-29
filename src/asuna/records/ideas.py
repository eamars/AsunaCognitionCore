"""The owner of `ideas`: her improvement-idea notebook (each idea, why, its state and what she decided), read and
written only through these operations.

`get` returns an idea as stored (`fields` names what to return; `_id` always comes back), within the fence given. None
follows section 4's rule: an id or the persona given None, or a value not of its kind, finds nothing without a read;
a state given None finds the ideas without one. `of_persona` is a view (`View`: `rows`, `each`, `first`, `count`),
in the replaced read's order (oldest first by `created_at`, or none; `newest_first` turns it). `save` is the
revisioned write (`Store.put`).
"""
from ..store.words import And, AnyOf, Contains, Or
from .view import ANY, View, fenced, is_text, pinned

COLLECTION = 'ideas'


def get(store, idea_id, fields=None, *, persona=ANY):
    """The idea with this id (of this persona), or None."""
    if not is_text(idea_id):
        return None
    if persona is ANY:
        return store.collection(COLLECTION).get(idea_id, fields)
    return View(store, COLLECTION, fenced({'_id': idea_id}, {'persona': (persona, is_text)})).first(fields=fields)


def of_persona(store, persona, *, state=ANY, search=None, by='created_at'):
    """View: a persona's ideas (in this state; whose idea or reason contains `search`, case kept), ordered by `by`
    (none: the database's order)."""
    where = pinned(fenced({}, {'persona': (persona, is_text)}), {'state': (state, is_text)})
    if where is not None and search:
        where = And(where, Or({'idea': Contains(search)}, {'why': Contains(search)}))
    return View(store, COLLECTION, where, ((by, 1),) if by else ())


def count(store, persona, states):
    """How many of a persona's ideas are in these states."""
    where = fenced({'state': AnyOf(list(states))}, {'persona': (persona, is_text)})
    return 0 if where is None else store.collection(COLLECTION).count(where)


def save(store, idea, **kwargs):
    """The revisioned write of an idea (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, idea, **kwargs)
