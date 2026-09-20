"""Private discovery and the real persistent mount share the same ownership."""
import uuid
from asuna.config import ROOT
from asuna.context import ContextBuilder
from asuna.sandbox import Sandbox
from asuna.skills import skills_directory


def test_private_skill_catalog_and_mount_do_not_follow_user_into_other_scene(store):
    key = 'skill-scope-' + uuid.uuid4().hex
    root = ROOT / '.runtime/skills' / key
    work = ROOT / '.runtime/work' / key
    store.config.update(task_mode='workspace', chat={
        **store.config['chat'], 'person_id': 'A', 'scene_id': 'dm-a',
        'skills_dir': str(root), 'workspace': str(work), 'read_only_paths': []})
    calls = []
    def catalog():
        calls.append(True)
        return {'complete': True, 'skills': [{'name': 'private-note', 'description': 'A 的私聊技能'}]}
    builder = ContextBuilder(store, skill_catalog=catalog)
    _, own, _ = builder.prepare({'event_id': 'own', 'scene_id': 'dm-a', 'person_id': 'A', 'text': '你好'})
    _, foreign, _ = builder.prepare({'event_id': 'foreign', 'scene_id': 'dm-b', 'person_id': 'B', 'text': '你好'})
    assert own['available_skills_from_native_dsh']['skills'][0]['name'] == 'private-note'
    assert 'available_skills_from_native_dsh' not in foreign
    assert len(calls) == 1
    assert skills_directory(store.config, 'dm-b', 'A') is None
    assert skills_directory(store.config, 'dm-a', 'B') is None
    mounted = Sandbox(work, skills_dir=skills_directory(store.config, 'dm-a', 'A'))
    written = mounted.run(['python3', '-c', "from pathlib import Path; Path('/skills/probe.txt').write_text('persisted')"])
    assert written['exit_code'] == 0
    assert (root / 'probe.txt').read_text() == 'persisted'
    hidden = Sandbox(work).run(['python3', '-c', "from pathlib import Path; assert not Path('/skills').exists()"])
    assert hidden['exit_code'] == 0
