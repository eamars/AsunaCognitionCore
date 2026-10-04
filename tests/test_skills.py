"""Private discovery and the real persistent mount share the same ownership."""
import uuid
from asuna.config import ROOT
from asuna.sandbox import Sandbox
from asuna.skills import skills_directory


def test_private_skill_catalog_and_mount_do_not_follow_user_into_other_scene(store):
    key = 'skill-scope-' + uuid.uuid4().hex
    root = ROOT / '.runtime/skills' / key
    work = ROOT / '.runtime/work' / key
    store.config.update(task_mode='workspace', chat={
        **store.config['chat'], 'person_id': 'A', 'scene_id': 'dm-a',
        'skills_dir': str(root), 'workspace': str(work), 'read_only_paths': []})
    # Skill discovery is native DSH's (the skill tool in the bound session); the core owns only the mount.
    assert skills_directory(store.config, 'dm-b', 'A') is None
    assert skills_directory(store.config, 'dm-a', 'B') is None
    mounted = Sandbox(work, skills_dir=skills_directory(store.config, 'dm-a', 'A'))
    written = mounted.run(['python3', '-c', "from pathlib import Path; Path('/skills/probe.txt').write_text('persisted')"])
    assert written['exit_code'] == 0
    assert (root / 'probe.txt').read_text() == 'persisted'
    hidden = Sandbox(work).run(['python3', '-c', "from pathlib import Path; assert not Path('/skills').exists()"])
    assert hidden['exit_code'] == 0
