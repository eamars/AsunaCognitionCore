"""ADR-078: a skill is offered outside home only when its header lists that kind of scene; a wrong header is refused,
never read as home only; a skill that leaves home carries a self-check whose private-words scan is green."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from asuna import skills

ROOT = Path(__file__).resolve().parents[1]
TRACKED = sorted(ROOT.glob('packages/**/skills/*/SKILL.md'))


def skill(root, name, header=''):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text('---\nname: %s\ndescription: 用来测的技能\n%s---\n\n正文\n' % (name, header),
                                     encoding='utf-8')
    return folder


def test_the_header_lists_scene_kinds_from_a_closed_set_and_a_wrong_one_is_refused():
    text = lambda extra: '---\nname: x\ndescription: y\n%s---\nbody\n' % extra
    assert skills.scene_kinds(text('')) == ('home',)
    assert skills.scene_kinds(text('scene_kinds: [home, group]\n')) == ('home', 'group')
    assert skills.scene_kinds(text('scene_kinds: [group,dm]\n')) == ('group', 'dm')
    assert skills.scene_kinds(text('metadata:\n  owner: someone\n')) == ('home',)      # a nested value is not a key
    for wrong, words in (('scene_kind: [group]\n', '不认识的键'),               # a misspelt key never reads as home only
                         ('places: [group]\n', '不认识的键'),
                         ('scene_kinds: [everywhere]\n', '不在'),               # no catch-all
                         ('scene_kinds: [home, groups]\n', '不在'),
                         ('scene_kinds: group\n', '写成列表'),
                         ('scene_kinds: []\n', '写成列表'),
                         ('scene_kinds:\n- group\n', '读不出')):
        with pytest.raises(skills.SkillHeaderError, match=words):
            skills.scene_kinds(text(wrong))
    with pytest.raises(skills.SkillHeaderError, match='没有用 --- 收尾'):
        skills.scene_kinds('---\nname: x\n')


def test_home_gets_every_root_and_elsewhere_only_the_skills_that_list_that_kind(store, tmp_path):
    root = tmp_path / 'skills'
    home_only = skill(root, 'home-only')
    groups = skill(root, 'in-groups', 'scene_kinds: [home, group]\n')
    chats = skill(root, 'in-chats', 'scene_kinds: [dm]\n')
    skill(root, 'broken', 'scene_kinds: [everywhere]\n')
    config = store.config
    config['_skill_directories'] = [str(root)]
    local = config['chat']
    assert skills.skill_directories(config, local['scene_id'], local['person_id'], store.db) == [root.resolve()]
    store.db.scenes.insert_one({'_id': 'g-skills', 'schema_version': 1, 'scene_id': 'g-skills', 'kind': 'group',
                                'scope_key': 'scene:g-skills', 'policy_epoch': 1, 'sequence': 0})
    store.db.scenes.insert_one({'_id': 'dm-skills', 'schema_version': 1, 'scene_id': 'dm-skills', 'kind': 'dm',
                                'scope_key': 'scene:dm-skills', 'policy_epoch': 1, 'sequence': 0})
    assert skills.skill_directories(config, 'g-skills', 'someone', store.db) == [groups.resolve()]
    assert skills.skill_directories(config, 'dm-skills', 'someone', store.db) == [chats.resolve()]
    assert home_only.resolve() not in skills.skill_directories(config, 'g-skills', 'someone', store.db)
    # The publication probe names the broken one and what to fix.
    run = subprocess.run([sys.executable, '-m', 'asuna.skills', str(root)], capture_output=True, text=True,
                         encoding='utf-8', env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONUTF8': '1'})
    assert run.returncode != 0 and 'broken' in run.stderr and 'everywhere' in run.stderr


@pytest.mark.parametrize('path', TRACKED, ids=lambda path: path.parent.name)
def test_every_shipped_skill_header_is_one_the_program_takes(path):
    skills.scene_kinds(path.read_text(encoding='utf-8'))


def _private_list():
    named = os.environ.get('ASUNA_PRIVATE_WORDS')
    return Path(named) if named else ROOT / '.runtime' / 'private' / 'personal-words.txt'


@pytest.mark.parametrize('path', [path for path in TRACKED
                                  if set(skills.scene_kinds(path.read_text(encoding='utf-8'))) - {'home'}],
                         ids=lambda path: path.parent.name)
def test_a_skill_that_leaves_home_passes_its_own_private_words_scan(path):
    """Her condition: a skill may go outside home only with a self-check whose leak scan is green. With no private
    list on this machine it fails: unchecked is not clean."""
    check = path.parent / 'check_skill.py'
    assert check.exists() and 'leak_scan_ran' in check.read_text(encoding='utf-8'), \
        '%s lists scenes besides home but has no self-check with a private-words leak criterion' % path.parent.name
    words = _private_list()
    assert words.exists(), 'no private-words list at %s: a skill that leaves home cannot be checked' % words.name
    run = subprocess.run([sys.executable, str(check)], capture_output=True, text=True, encoding='utf-8',
                         env={**os.environ, 'ASUNA_PRIVATE_WORDS': str(words), 'PYTHONUTF8': '1'})
    assert run.returncode == 0, (run.stdout + run.stderr)[-600:]
