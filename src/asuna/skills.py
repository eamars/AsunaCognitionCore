"""Skill discovery roots; discovery and parsing remain native DSH services.

Skills are published resources (persona and channel packages). Changing one goes through the
development tools and `development_publish` only (ADR-011 §5.3); no sandbox mounts them writable.
"""
from pathlib import Path


def skill_directories(config, scene_id, person_id):
    """The published persona and channel skill roots, for the local owner's tasks."""
    chat = config.get('chat', {})
    if (scene_id, person_id) != (chat.get('scene_id'), chat.get('person_id')):
        return []
    roots = []
    for value in config.get('_skill_directories', []):
        path = Path(value).resolve()
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots
