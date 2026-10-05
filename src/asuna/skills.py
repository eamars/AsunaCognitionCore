"""Skill discovery roots; discovery and parsing remain native DSH services.

Skills are published resources (persona and channel packages). Changing one goes through the
development tools and `development_publish` only (ADR-011 §5.3); no sandbox mounts them writable.
"""
from pathlib import Path


def skill_directories(config, scene_id, person_id, db=None):
    """The published core, persona and channel skill roots, for the owner's private chats (local or DM)."""
    chat = config.get('chat', {})
    if (scene_id, person_id) != (chat.get('scene_id'), chat.get('person_id')):
        from . import visibility
        scene = (db.scenes.find_one({'_id': scene_id}) if db is not None else None) or {'_id': scene_id}
        if db is None or visibility.session_class(config, db, scene, person_id) != visibility.OWNER_PRIVATE:
            return []
    roots = []
    for value in config.get('_skill_directories', []):
        path = Path(value).resolve()
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots
