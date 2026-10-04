"""Session class and data visibility (ADR-009 §2).

Every turn is computed to be ``owner_private`` or ``public`` by the program, never
by a model. Owner-private data is readable only in owner-private sessions;
cross-scene links never raise a session's class, and a link that would let a
public scene read an owner-private scene is refused when the host starts.
"""
from __future__ import annotations

import copy

from . import scene_links

OWNER_PRIVATE = 'owner_private'
PUBLIC = 'public'
VISIBILITIES = ('public', OWNER_PRIVATE)
OWNER_PRIVATE_PREFIX = 'owner-private:'


def owner_private_scope(persona: str) -> str:
    return OWNER_PRIVATE_PREFIX + persona


def is_owner_private_scope(scope_key) -> bool:
    return isinstance(scope_key, str) and scope_key.startswith(OWNER_PRIVATE_PREFIX)


def owner_id(config) -> str | None:
    return (config.get('chat') or {}).get('person_id')


def session_class(config, db, scene: dict, person_id: str) -> str:
    """owner_private ⇔ the owner's local scene, or a DM whose canonical person is the owner."""
    local = config.get('chat') or {}
    owner = local.get('person_id')
    if not owner:
        return PUBLIC
    scene_id = scene.get('_id') or scene.get('scene_id')
    if scene_id == local.get('scene_id') and person_id == owner:
        return OWNER_PRIVATE
    if scene.get('kind') == 'dm' and scene_links.canonical_person_id(config, db, person_id) == owner:
        return OWNER_PRIVATE
    return PUBLIC


def readable(visibility: str, cls: str) -> bool:
    return visibility == 'public' or cls == OWNER_PRIVATE


def readable_scope(scope_key: str, cls: str) -> bool:
    """owner-private scopes depend only on the session class, never on links."""
    return not is_owner_private_scope(scope_key) or cls == OWNER_PRIVATE


def owner_private_scenes(config) -> set:
    """Scenes that are owner-private by configuration alone (used before any DB read)."""
    local = config.get('chat') or {}
    owner = local.get('person_id')
    scenes = {local['scene_id']} if local.get('scene_id') else set()
    if not owner:
        return scenes
    mapping = scene_links.canonical_map(config)
    for channel in (config.get('channels') or {}).values():
        for route in (channel.get('routes') or {}).values() if isinstance(channel, dict) else ():
            if not isinstance(route, dict) or (route.get('target') or {}).get('type') != 'dm':
                continue
            person = route.get('person_id')
            if person and mapping.get(person, person) == owner and route.get('scene_id'):
                scenes.add(route['scene_id'])
    return scenes


def without_link_downgrades(config):
    """Return (config, rejected): links from a public reader to an owner-private scene removed.

    Existing monologues, chunks and summaries of owner-private scenes keep their
    ``scene:*`` scope, so refusing these links is what keeps them out of public turns.
    """
    private = owner_private_scenes(config)
    rejected = []
    value = copy.deepcopy(config)
    links = value.get('context_links')
    if isinstance(links, dict):
        for reader, targets in list(links.items()):
            if reader in private or not isinstance(targets, (list, tuple, str)):
                continue
            items = [targets] if isinstance(targets, str) else list(targets)
            kept = [t for t in items if t not in private]
            rejected += [{'reader': reader, 'target': t, 'code': 'LINK_PRIVACY_DOWNGRADE'} for t in items if t in private]
            links[reader] = kept
    for channel in (value.get('channels') or {}).values():
        for route in (channel.get('routes') or {}).values() if isinstance(channel, dict) else ():
            if not isinstance(route, dict) or route.get('read_scenes') is None or route.get('scene_id') in private:
                continue
            items = route['read_scenes'] if isinstance(route['read_scenes'], list) else [route['read_scenes']]
            rejected += [{'reader': route.get('scene_id'), 'target': t, 'code': 'LINK_PRIVACY_DOWNGRADE'}
                         for t in items if t in private]
            route['read_scenes'] = [t for t in items if t not in private]
    return value, rejected
