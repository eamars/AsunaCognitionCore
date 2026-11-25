"""A conversation's own files (ADR-120 §4), the one answer every read, list and send fence asks.

- **What they are** (`scopes`, `holds`): the stored rows (`artifacts`: pictures, files, received files) made or received
  there (`scope_key`), and those sent or carried there (`shared_scopes`, added by `share`); an edit of a picture that
  came from there, which goes back there; and those of the conversations the owner linked to it (`context_links`,
  `scene_links.read_scope`). Stickers (`global-safe`) are everyone's. Its messages' attachments are found by the same
  links (vision.readable_image_scenes), and a task's folder is its working folder inside them.
- **Who reads what** (`reach`): work whose origin may use `all_files` reads any conversation's file by id while its bytes
  exist; work that may use only `own_files` reads its own conversation's; a file of another conversation answers as one
  that does not exist.
- **Who sends what** (`send_refused`): into a home conversation, whatever the work may read; into another, any file
  (`send_any`), any file into the conversation the work is for (`send_to_asker`), or that conversation's own
  (`send_own`). A refusal is `access.SEND_REFUSED`.
- **When a row gains a conversation** (`share`): when a message carrying it is written there (coordinator.queue_reply),
  and when a going-out picks it for that place (`carry`: a visit's or an errand's picture). One set-add, never a copy
  of the bytes; an erasure of a conversation takes its scope out of every other row (blobs.erase_scope).
"""
from __future__ import annotations

from . import access, visibility
from .records import artifacts as artifact_records

STICKERS = 'global-safe'          # the scope of the stickers she collects: every conversation's


def scopes(config, place):
    """The scope keys whose rows are this conversation's own: its own first, then those the owner linked to it.
    `place` is a scene row or a turn's or a task's binding (`_id` or `scene_id`, and `scope_key`)."""
    from .scene_links import read_scope
    own = (place or {}).get('scope_key')
    linked = read_scope(config, place or {})['linked_scope_keys']
    return list(dict.fromkeys(scope for scope in (own, *linked) if scope))


def holds(row, own):
    """Whether a stored row is one of the conversation's own whose scopes are `own`."""
    from .outbound_media import returns_to
    own, row = set(own or ()), row or {}
    return (row.get('scope_key') == STICKERS or row.get('scope_key') in own
            or bool(own & set(row.get('shared_scopes') or ())) or (returns_to(row) or None) in own)


def share(store, artifact_id, scope):
    """The row is `scope`'s own from now on; a row already its own, or a sticker, is left as it is."""
    return artifact_records.share(store, artifact_id, scope, besides=(STICKERS,))


def reach(config, origin):
    """How far work of this origin reads stored files: 'all' (any conversation's), 'own' (its own conversation's) or
    None (none)."""
    if access.allowed(config, origin, 'all_files'):
        return 'all'
    return 'own' if access.allowed(config, origin, 'own_files') else None


def readable(config, origin, row, own):
    """Whether work of this origin, whose own conversation's scopes are `own`, may read this stored row."""
    found = reach(config, origin)
    return found == 'all' or (found == 'own' and holds(row, own))


def at_home(store, scene):
    """Whether a conversation is a home one: her local chat, a chat of the owner's, a home line or a home group."""
    from . import channel_kinds
    from .outbound_media import _route_person
    config, scene = store.config, scene or {}
    scene_id = scene.get('_id') or scene.get('scene_id')
    if not scene_id:
        return False
    if scene_id == (config.get('chat') or {}).get('scene_id') or channel_kinds.home(scene_id) \
            or visibility.home_group(config, scene_id):
        return True
    person = _route_person(config, scene)
    return scene.get('kind') == 'dm' and bool(person) and \
        visibility.session_class(config, store, scene, person) == visibility.OWNER_PRIVATE


def send_refused(store, origin, row, place, own, asker=None):
    """The row of the table that bars work of `origin` (whose own conversation's scopes are `own`) from sending a stored
    `row` into `place` (a scene row), or None when it may. `asker`: the conversation the work is for
    (`whose.scene_id`)."""
    config = store.config
    if not readable(config, origin, row, own):
        return 'all_files' if reach(config, origin) else 'own_files'
    if at_home(store, place) or access.allowed(config, origin, 'send_any'):
        return None
    place_id = (place or {}).get('_id') or (place or {}).get('scene_id')
    if asker and asker == place_id and access.allowed(config, origin, 'send_to_asker'):
        return None
    if holds(row, scopes(config, place)) and access.allowed(config, origin, 'send_own'):
        return None
    return 'send_own' if holds(row, scopes(config, place)) else 'send_to_asker' if asker == place_id else 'send_any'


def refuse_send(store, by, origin, resource, tool):
    """The send refusal, recorded: one sentence whatever row refused it (§9, her 0668)."""
    from .state import Denied
    access.record(store, by, origin, resource, tool, send=True)
    return Denied(access.SEND_REFUSED)


def carry(store, ep, artifact_id, place, tool, kinds=('image',)):
    """A going-out's picture or file (a visit's or an errand's `artifact_id`; `kinds` it may be), checked and shared
    with the place it goes to: a stored one the picking turn may read and may send there (`send_refused`), which is
    that place's own from now on, so the turn there lists it and sends it as its own. Raises the refusal (ValueError
    for one that does not exist, Denied for one this turn may not send there, ADR-105's sentence for an erased one)."""
    from . import whose as whose_of
    from .blobs import refuse_erased
    row = artifact_records.get(store, artifact_id, state='DONE')
    if not row or row.get('kind') not in kinds:
        raise ValueError(NOT_FOUND)
    origin = access.origin_of_turn(store, ep)
    asker = (whose_of.of(store, ep) or {}).get('scene_id')
    refused = send_refused(store, origin, row, place, scopes(store.config, ep), asker)
    if refused:
        raise refuse_send(store, {'turn': ep['_id'], 'scope': ep.get('scope_key')}, origin, refused, tool)
    refuse_erased(store, row, place.get('_id'))
    if row.get('storage') != artifact_records.STORED:
        raise ValueError(NOT_FOUND)
    share(store, artifact_id, place['scope_key'])
    return row


NOT_FOUND = 'ARTIFACT_NOT_FOUND: 没有这个（或它的字节已经不在了）；artifact_id 照抄你能发的图、文件或你自己的图里的，或不带'
