"""Skills are published resources: discovery follows the owner, and no sandbox mounts them writable."""
from asuna.sandbox import Sandbox
from asuna.skills import skill_directories


def test_skill_discovery_follows_owner_and_sandbox_has_no_skill_mount(store, runtime_work):
    root = runtime_work('skill-scope')
    published = root / 'published-skills'
    published.mkdir(parents=True)
    work = root / 'task'
    store.config.update(task_mode='workspace', _skill_directories=[str(published)], chat={
        **store.config['chat'], 'person_id': 'A', 'scene_id': 'dm-a', 'workspace': str(work), 'read_only_paths': []})
    # Discovery is native DSH's (the skill tool in the bound session); the core names the published roots.
    assert skill_directories(store.config, 'dm-a', 'A') == [published.resolve()]
    assert skill_directories(store.config, 'dm-b', 'A') == []
    assert skill_directories(store.config, 'dm-a', 'B') == []
    # Changing a skill goes through the development tools and development_publish only (ADR-011 §5.3).
