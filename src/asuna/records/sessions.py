"""The owner of `sessions`: the bindings of her native sessions (which conversation, lane, persona, epoch and working
folder a session belongs to, the sessions it continues and is continued by, its title and carry), read and written
only through these operations.

`get` returns a session as stored (`fields` names what to return, `_id` always comes back); an id that is missing or
not text finds nothing. The other reads are views (`View`: `rows`, `first`, `count`), in the database's order unless
an operation says otherwise. A conversation's character context of None means one with none: the session's field
null or missing. `save` is the revisioned write (`Store.put`).
"""
from ..store.words import AnyOf, Exists, Not, Set
from .view import ANY, View, fenced, is_number, is_text, none_or, texts

COLLECTION = 'sessions'
INVALIDATED = 'INVALIDATED'


def _view(store, where, order=()):
    return View(store, COLLECTION, where, order)


def get(store, session_id, fields=None, *, native=False):
    """The session with this id (`native`: only one the native Host binds), or None."""
    if not is_text(session_id):
        return None
    if not native:
        return store.collection(COLLECTION).get(session_id, fields)
    return _view(store, {'_id': session_id, 'native_host': True}).first(fields=fields)


def native(store, session_ids=None, *, lane=None, besides_scene=None):
    """View: the sessions the native Host binds (these ids; of a lane; not of a conversation)."""
    where = {}
    if session_ids is not None:
        where['_id'] = AnyOf(texts(session_ids))
    where['native_host'] = True
    if lane is not None:
        where['lane'] = lane
    if besides_scene is not None:
        where['scene_id'] = Not(besides_scene)
    return _view(store, where)


def successors(store, session_ids):
    """View: the sessions that continue these."""
    return _view(store, {'successor_id': AnyOf(texts(session_ids))})


def main(store, scene_id, *, lane=None, persona=ANY, epoch=ANY, context=ANY, fields=None):
    """The main conversation session the native Host binds for a conversation (of a lane; of a persona, epoch and
    character context: None, a session with none), or None."""
    if not is_text(scene_id):
        return None
    where = {'native_host': True, 'main_conversation': True, 'scene_id': scene_id}
    if lane is not None:
        where['lane'] = lane
    where = fenced(where, {'persona': (persona, is_text), 'policy_epoch': (epoch, is_number)})
    if where is None:
        return None
    if context is not ANY:
        if context is not None and not is_text(context):
            return None
        where = none_or(where, 'character_context', context)
    return _view(store, where).first(fields=fields)


def titled(store, scene_id, fields=None):
    """The main session of a conversation that has a native title, or None."""
    if not is_text(scene_id):
        return None
    return _view(store, {'scene_id': scene_id, 'main_conversation': True,
                         'native_title': Exists(True)}).first(fields=fields)


def of_task(store, *, broker, parents, scene, scope, epoch, person, persona, task=ANY):
    """The newest action session of an execution binding (`broker`: its broker session), continuing one of
    `parents`, of this conversation, scope, epoch, person and persona (and of this task), or None. Newest by when
    its binding was written, then by id."""
    where = fenced({'native_host': True, 'lane': 'executor'}, {'broker_session': (broker, is_text)})
    if where is None:
        return None
    where['parent_session_id'] = AnyOf(texts(parents))
    where = fenced(where, {'scene_id': (scene, is_text), 'scope_key': (scope, is_text),
                           'policy_epoch': (epoch, is_number), 'person_id': (person, is_text),
                           'persona': (persona, is_text), 'task_id': (task, is_text)})
    return _view(store, where, (('binding_updated_at', 1), ('_id', 1))).first(newest_first=True)


def of_scope(store, scope_key):
    """The sessions of a scope."""
    return _view(store, {'scope_key': scope_key} if is_text(scope_key) else None).rows()


def invalidate(store, session_id, deletion_id):
    """An erasure invalidated this session."""
    store.collection(COLLECTION).update({'_id': session_id}, Set({'state': INVALIDATED, 'deletion_id': deletion_id}))


def save(store, session, **kwargs):
    """The revisioned write of a whole session (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, session, **kwargs)
