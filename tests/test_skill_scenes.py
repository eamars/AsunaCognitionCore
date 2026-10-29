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


@pytest.mark.parametrize('path', TRACKED, ids=lambda path: path.parent.name)
def test_every_shipped_skill_header_is_one_the_program_takes(path):
    skills.scene_kinds(path.read_text(encoding='utf-8'))


def _private_list():
    named = os.environ.get('ASUNA_PRIVATE_WORDS')
    return Path(named) if named else ROOT / '.runtime' / 'private' / 'personal-words.txt'


def _leaves_home(path):
    """Whether a shipped skill lists more than home; a header that cannot be read fails its own test above, not the
    collection of this file."""
    try:
        return bool(set(skills.scene_kinds(path.read_text(encoding='utf-8'))) - {'home'})
    except skills.SkillHeaderError:
        return False


@pytest.mark.parametrize('path', [path for path in TRACKED if _leaves_home(path)], ids=lambda path: path.parent.name)
def test_a_skill_that_leaves_home_passes_its_own_private_words_scan(path):
    """Her condition: a skill may go outside home only with a self-check whose leak scan is green. With no private
    list on this machine it fails: unchecked is not clean."""
    check = path.parent / 'check_skill.py'
    assert check.exists() and 'leak_scan_ran' in check.read_text(encoding='utf-8'), \
        '%s lists scenes besides home but has no self-check with a private-words leak criterion' % path.parent.name
    words = _private_list()
    if not words.exists():
        pytest.skip('UNCHECKED, not passed: no private-words list at %s on this machine' % words.name)
    run = subprocess.run([sys.executable, str(check)], capture_output=True, text=True, encoding='utf-8',
                         env={**os.environ, 'ASUNA_PRIVATE_WORDS': str(words), 'PYTHONUTF8': '1'})
    assert run.returncode == 0, (run.stdout + run.stderr)[-600:]
