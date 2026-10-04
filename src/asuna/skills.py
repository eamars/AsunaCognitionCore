"""Local skill ownership; discovery and parsing remain native DSH services."""
from pathlib import Path
from .config import ROOT


def skills_directory(config, scene_id, person_id):
    chat = config.get('chat', {})
    if config.get('task_mode') != 'workspace' or not chat.get('skills_dir'):
        return None
    if (scene_id, person_id) != (chat.get('scene_id'), chat.get('person_id')):
        return None
    if config.get('_skill_workspace'):
        path = Path(config['_skill_workspace']).resolve()
        # Any profile's floor keeps candidates in a self-development folder under .runtime.
        if not (path.is_relative_to((ROOT / '.runtime').resolve()) and 'self-development' in path.parts):
            raise PermissionError('SKILL_PROJECT_OUTSIDE_ALLOWLIST')
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = Path(chat['skills_dir']).resolve()
    if not path.is_relative_to((ROOT / '.runtime/skills').resolve()):
        raise PermissionError('SKILL_DIRECTORY_OUTSIDE_ALLOWLIST')
    path.mkdir(parents=True, exist_ok=True)
    return path


def skill_directories(config, scene_id, person_id):
    """Explicit persona artifacts supplement the existing owner's skill grant."""
    legacy = skills_directory(config, scene_id, person_id)
    chat = config.get('chat', {})
    if (scene_id, person_id) != (chat.get('scene_id'), chat.get('person_id')):
        return []
    roots = [legacy] if legacy and not config.get('_skill_workspace') else []
    for value in config.get('_skill_directories', []):
        path = Path(value).resolve()
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots
