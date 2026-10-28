"""The owner of `scenes`: a conversation's record (its kind, members, scope and epoch, its position counter, and the
marks the program keeps on it), read and written only through these operations.

`get` and the other reads return records as stored (`fields` names what to return, `_id` always comes back); a
missing id or scope finds nothing. `next_seq` is the conversation's position counter, raised in one step. `save` is the
revisioned write (`Store.put`). The other writes each change one mark of the record.
"""
from ..store.words import AnyOf, Exists, Increase, Larger, Not, Set, Unset

COLLECTION = 'scenes'
MEMBERSHIP_DENIED = 'SCENE_MEMBERSHIP_DENIED: 这个人不在这个对话的成员里（或对话已经不在），这一步不能代他做；重试也一样'


def _rows(store):
    return store.collection(COLLECTION)


def _text(value):
    return isinstance(value, str) and bool(value)


# Reads.

def get(store, scene_id, fields=None):
    """The conversation with this id, or None."""
    return _rows(store).get(scene_id, fields) if _text(scene_id) else None


def by_scope(store, scope_key, *, kind=None, epoch=None, fields=None):
    """A conversation of this scope (of this kind, at this epoch), or None."""
    if not _text(scope_key):
        return None
    where = {'scope_key': scope_key, **({'kind': kind} if kind is not None else {}),
             **({'policy_epoch': epoch} if epoch is not None else {})}
    return next(_rows(store).find(where, fields=fields, limit=1), None)


def of_kind(store, kind, *, besides=None, fields=None):
    """Every conversation of this kind (`dm`, `group`, ...), but `besides`."""
    where = {'kind': kind, **({'_id': Not(besides)} if _text(besides) else {})}
    return list(_rows(store).find(where, fields=fields))


def many(store, scene_ids, *, kind=None, fields=None):
    """The conversations with these ids (of this kind)."""
    ids = [scene_id for scene_id in scene_ids if _text(scene_id)]
    return list(_rows(store).find({'_id': AnyOf(ids), **({'kind': kind} if kind is not None else {})}, fields=fields))


def in_scopes(store, scope_keys, fields=None):
    """The conversations of these scopes."""
    keys = [key for key in scope_keys if _text(key)]
    return list(_rows(store).find({'scope_key': AnyOf(keys)}, fields=fields))


def all(store, fields=None):
    """Every conversation."""
    return list(_rows(store).find({}, fields=fields))


def condense_wanted(store):
    """The groups she marked to have their conversation condensed."""
    return list(_rows(store).find({'condense_wanted': Exists(True), 'kind': 'group'}))


def channel_scenes(store, kind):
    """One conversation of this kind on a channel (its id only), or None."""
    return next(_rows(store).find({'kind': kind, 'channel_id': Exists(True)}, fields=['_id'], limit=1), None)


def authorize(store, scene_id, person_id):
    """The conversation, when this person is one of its members; else SCENE_MEMBERSHIP_DENIED."""
    from ..state import Denied           # the refusal the core's callers catch; an owner imports only the store
    scene = get(store, scene_id)
    if not scene or person_id not in scene['members']:
        raise Denied(MEMBERSHIP_DENIED)
    return scene


# Writes.

def next_seq(store, scene_id):
    """The conversation's next position, taken in one step."""
    return _rows(store).claim({'_id': scene_id}, Increase('sequence'))['sequence']


def save(store, scene, **kwargs):
    """The revisioned write of a whole record (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, scene, **kwargs)


def _set(store, scene_id, values):
    _rows(store).update({'_id': scene_id}, Set(values))


def _unset(store, scene_id, *paths, **where):
    _rows(store).update({'_id': scene_id, **where}, Unset(*paths))


def want_condense(store, scene_id, wanted):
    _set(store, scene_id, {'condense_wanted': wanted})


def clear_condense(store, scene_id):
    _unset(store, scene_id, 'condense_wanted')


def set_condense_floor(store, scene_id, floor):
    _set(store, scene_id, {'condense_floor': floor})


def apply_condense(store, scene_id, condensed=None):
    """A condense is done: its marks go; `condensed` (when it compacted) is what it records."""
    change = [Unset('condense_wanted', 'condense_floor', 'condensed_told')]
    if condensed:
        change.append(Set(condensed))
    _rows(store).update({'_id': scene_id}, change)


def told_condensed(store, scene_id, condensed_at, event_id):
    """The turn that tells her of this condense (only while it is still the latest)."""
    _rows(store).update({'_id': scene_id, 'condensed_at': condensed_at}, Set({'condensed_told': event_id}))


def note_size(store, scene_id, size):
    _set(store, scene_id, {'conversation_size': size})


def note_tokens(store, scene_id, tokens):
    _set(store, scene_id, {'conversation_tokens': tokens})


def set_character_context(store, scene_id, context):
    _set(store, scene_id, {'character_context': context})


def set_timezone(store, scene_id, name):
    """The conversation's time zone; None takes it away."""
    if name is None:
        _unset(store, scene_id, 'timezone')
    else:
        _set(store, scene_id, {'timezone': name})


def note_fault(store, scene_id, fault):
    _set(store, scene_id, {'fault': fault})


def clear_fault(store, scene_id, at):
    """The fault mark goes, if it is still the one shown (`fault.at`)."""
    _unset(store, scene_id, 'fault', **{'fault.at': at})


def hold_unsent(store, scene_id, unsent):
    _set(store, scene_id, {'unsent': unsent})


def clear_unsent(store, scene_id, episode_id):
    """The unsent mark goes, if it is still that turn's."""
    _unset(store, scene_id, 'unsent', **{'unsent.episode_id': episode_id})


def asides_shown(store, scene_id, seq):
    """The asides shown so far reach this position (it never moves back)."""
    _rows(store).update({'_id': scene_id}, Larger('asides_shown_seq', seq))
