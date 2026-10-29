"""The owner of `plans`: what she and the program scheduled (her plans in a conversation, the rhythms of the
heartbeat, settlement, self-development and condensing, their next fire and last outcome), read and written only
through these operations.

`get` returns a plan as stored (`fields` names what to return, `_id` always comes back), within the fences given.
None follows section 4's rule: an id or a fence (conversation, scope, person, epoch) given None finds nothing without a
read; a value condition (a status, a last outcome) given None finds the plans whose field is null or missing. The
other reads are views (`View`: `rows`, `each`, `first`, `count`), in the replaced read's order (none where it had
none). `save` is the revisioned write (`Store.put`).
"""
from ..store.words import AnyOf, NoneOf, Range
from .view import ANY, View, fenced, is_number, is_text, pinned, texts

COLLECTION = 'plans'


def _view(store, where, by=None):
    return View(store, COLLECTION, where, ((by, 1),) if by else ())


def _fences(scene=ANY, scope=ANY, person=ANY, epoch=ANY):
    return {'scene_id': (scene, is_text), 'scope_key': (scope, is_text), 'person_id': (person, is_text),
            'policy_epoch': (epoch, is_number)}


def get(store, plan_id, fields=None, *, scene=ANY, scope=ANY, person=ANY, epoch=ANY):
    """The plan with this id (of this conversation, scope, person, epoch), or None."""
    if not is_text(plan_id):
        return None
    if all(value is ANY for value in (scene, scope, person, epoch)):
        return store.collection(COLLECTION).get(plan_id, fields)
    return _view(store, fenced({'_id': plan_id}, _fences(scene, scope, person, epoch))).first(fields=fields)


def _listed(values):
    return isinstance(values, (list, tuple, set))


def in_status(store, *, status=ANY, statuses=ANY, kinds=ANY):
    """View: the plans in a status (None: none) or one of several (of these kinds)."""
    if not (statuses is ANY or _listed(statuses)) or not (kinds is ANY or _listed(kinds)):
        return _view(store, None)
    where = {}
    if statuses is not ANY:
        where['status'] = AnyOf(list(statuses))
    if kinds is not ANY:
        where['kind'] = AnyOf(texts(kinds))
    return _view(store, pinned(where, {'status': (status, is_text)}))


def due(store, until, *, not_kinds):
    """View: the active plans due by `until` (ISO text), not of these kinds."""
    if not is_text(until):
        return _view(store, None)
    return _view(store, {'status': 'ACTIVE', 'next_fire_at': Range(lte=until), 'kind': NoneOf(texts(not_kinds))})


def of_conversation(store, scene_id, *, scope=ANY, person=ANY, epoch=ANY, statuses=ANY, not_kinds=None,
                    by='created_at'):
    """View: a conversation's plans (of a scope, person and epoch; in these statuses; not of these kinds), in the
    order they were created."""
    if not (statuses is ANY or _listed(statuses)):
        return _view(store, None)
    where = {} if statuses is ANY else {'status': AnyOf(list(statuses))}
    if not_kinds is not None:
        where['kind'] = NoneOf(texts(not_kinds))
    return _view(store, fenced(where, _fences(scene_id, scope, person, epoch)), by)


def with_outcome(store, scene_id, kinds, outcome):
    """View: the plans of these kinds in a conversation whose last outcome was `outcome`."""
    where = fenced({'kind': AnyOf(texts(kinds))}, {'scene_id': (scene_id, is_text)})
    return _view(store, pinned(where, {'last_outcome': (outcome, is_text)}))


def count_status(store, status):
    """How many plans are in a status."""
    return _view(store, pinned({}, {'status': (status, is_text)})).count()


def save(store, plan, **kwargs):
    """The revisioned write of a whole plan (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, plan, **kwargs)
