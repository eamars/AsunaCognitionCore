"""Local skill ownership; discovery and parsing remain native DSH services."""
from pathlib import Path
from .config import ROOT


def skills_directory(config, scene_id, person_id):
    chat = config.get('chat', {})
    if config.get('task_mode') != 'workspace' or not chat.get('skills_dir'):
        return None
    if (scene_id, person_id) != (chat.get('scene_id'), chat.get('person_id')):
        return None
    path = Path(chat['skills_dir']).resolve()
    if not path.is_relative_to((ROOT / '.runtime/skills').resolve()):
        raise PermissionError('SKILL_DIRECTORY_OUTSIDE_ALLOWLIST')
    path.mkdir(parents=True, exist_ok=True)
    return path
