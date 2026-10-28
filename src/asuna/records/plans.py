"""The owner of `plans`: what she and the program scheduled (her plans in a conversation, the rhythms of the
heartbeat, settlement, self-development and condensing, their next fire and last outcome), read and written only
through these operations.

`get` returns a plan as stored (`fields` names what to return, `_id` always comes back), within the fences given; an
id that is missing or not text finds nothing, and a fence of None finds the plans whose field is null or missing, as
the replaced reads' equality on None did. The other reads are views (`View`: `rows`, `each`, `first`, `count`), in
the replaced read's order (none where it had none). `save` is the revisioned write (`Store.put`).
"""
from ..store.words import AnyOf, NoneOf, Range
from .view import ANY, View, is_number, is_text, pinned, texts

COLLECTION = 'plans'


def _view(store, where, by=None):
    return View(store, COLLECTION, where, ((by, 1),) if by else ())


def _status(where, status, statuses):
    if status is not None:
        where['status'] = status
    if statuses is not None:
        where['status'] = AnyOf(list(statuses))
    return where


def get(store, plan_id, fields=None, *, scene=ANY, scope=ANY, person=ANY, epoch=ANY):
    """The plan with this id (of this conversation, scope, person, epoch), or None."""
    if not is_text(plan_id):
        return None
    if all(value is ANY for value in (scene, scope, person, epoch)):
        return store.collection(COLLECTION).get(plan_id, fields)
    where = pinned({'_id': plan_id}, {'scene_id': (scene, is_text), 'scope_key': (scope, is_text),
                                      'person_id': (person, is_text), 'policy_epoch': (epoch, is_number)})
    return _view(store, where).first(fields=fields)


def in_status(store, *, status=None, statuses=None, kinds=None):
    """View: the plans in a status or one of several (of these kinds)."""
    where = _status({}, status, statuses)
    if kinds is not None:
        where['kind'] = AnyOf(texts(kinds))
    return _view(store, where)


def due(store, until, *, not_kinds):
    """View: the active plans due by `until` (ISO text), not of these kinds."""
    return _view(store, {'status': 'ACTIVE', 'next_fire_at': Range(lte=until), 'kind': NoneOf(texts(not_kinds))})


def of_conversation(store, scene_id, *, scope=ANY, person=ANY, epoch=ANY, statuses=None, not_kinds=None,
                    by='created_at'):
    """View: a conversation's plans (of a scope, person and epoch; in these statuses; not of these kinds), in the
    order they were created."""
    where = _status({}, None, statuses)
    if not_kinds is not None:
        where['kind'] = NoneOf(texts(not_kinds))
    return _view(store, pinned(where, {'scene_id': (scene_id, is_text), 'scope_key': (scope, is_text),
                                       'person_id': (person, is_text), 'policy_epoch': (epoch, is_number)}), by)


def with_outcome(store, scene_id, kinds, outcome):
    """View: the plans of these kinds in a conversation whose last outcome was `outcome`."""
    return _view(store, pinned({'kind': AnyOf(texts(kinds)), 'last_outcome': outcome}, {'scene_id': (scene_id, is_text)}))


def count_status(store, status):
    """How many plans are in a status."""
    return _view(store, {'status': status}).count()


def save(store, plan, **kwargs):
    """The revisioned write of a whole plan (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, plan, **kwargs)
