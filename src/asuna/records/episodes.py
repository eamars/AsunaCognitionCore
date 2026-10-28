"""The owner of `episodes`: her turns (what woke her, what she was given, what she thought, said and called, and the
state the turn reached), read and written only through these operations.

`get` returns a turn as stored (`fields` names what to return, `_id` always comes back), within the fences given; an
id or a fence (conversation, scope, epoch, persona, person, native session) that is missing or not of its kind finds
nothing. A turn's kind is required, never null or missing, so a kind of None finds nothing too. The other reads are
views (`View`: `rows`, `first`, `count`), in the database's order, as the replaced reads had none. `save` is the
revisioned write (`Store.put`).
"""
from ..store.words import AnyOf, Exists, Not
from .view import ANY, View, fenced, is_number, is_text, texts

COLLECTION = 'episodes'
# The states of a turn that ended with her answer: it committed, or it waits on the task it handed work to.
ANSWERED = ('COMMITTED', 'WAITING_TASK')


def _view(store, where):
    return View(store, COLLECTION, where)


def get(store, episode_id, fields=None, *, persona=ANY, scene=ANY, scope=ANY, person=ANY, epoch=ANY, session=ANY,
        carried=False):
    """The turn with this id (of this persona, conversation, scope, person, epoch or native session; `carried`: one
    whose system reference names the sections it carried), or None."""
    if not is_text(episode_id):
        return None
    fences = {'native_session_id': (session, is_text), 'scope_key': (scope, is_text), 'scene_id': (scene, is_text),
              'person_id': (person, is_text), 'policy_epoch': (epoch, is_number), 'persona': (persona, is_text)}
    if all(value is ANY for value, _ in fences.values()) and not carried:
        return store.collection(COLLECTION).get(episode_id, fields)
    where = fenced({}, fences)
    if where is None:
        return None
    where['_id'] = episode_id
    if carried:
        where['system_ref.carried'] = Exists(True)
    return _view(store, where).first(fields=fields)


def many(store, episode_ids, *, states=None):
    """View: the turns with these ids (in these states)."""
    where = {'_id': AnyOf(texts(episode_ids))}
    if states is not None:
        where['state'] = AnyOf(list(states))
    return _view(store, where)


def of_source(store, source_event_id, *, kind=ANY, scene=ANY, fields=None):
    """The turn a source event opened (of this kind, in this conversation), or None."""
    if not is_text(source_event_id):
        return None
    where = fenced({}, {'scene_id': (scene, is_text)})
    if where is None:
        return None
    where['source_event_id'] = source_event_id
    if kind is not ANY:
        if not is_text(kind):
            return None
        where['episode_kind'] = kind
    return _view(store, where).first(fields=fields)


def of_kind(store, kind, *, scenes=None):
    """View: the turns of a kind (in these conversations)."""
    if not is_text(kind):
        return _view(store, None)
    where = {'episode_kind': kind}
    if scenes is not None:
        where['scene_id'] = AnyOf(texts(scenes))
    return _view(store, where)


def open(store, states, *, kind=ANY, not_kind=None):
    """View: the turns in these states (of a kind, or of any kind but one)."""
    where = {'state': AnyOf(list(states))}
    if kind is not ANY:
        if not is_text(kind):
            return _view(store, None)
        where['episode_kind'] = kind
    if not_kind is not None:
        where['episode_kind'] = Not(not_kind)
    return _view(store, where)


def answered(store, person_ids, limit=None):
    """How many turns she answered these people with words (at most `limit`)."""
    return _view(store, {'person_id': AnyOf(texts(person_ids)), 'state': AnyOf(list(ANSWERED)),
                         'speech': Exists(True)}).count(limit)


def of_scope(store, scope_key, fields=None):
    """The turns of a scope."""
    return _view(store, {'scope_key': scope_key} if is_text(scope_key) else None).rows(fields=fields)


def save(store, episode, **kwargs):
    """The revisioned write of a whole turn (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, episode, **kwargs)
