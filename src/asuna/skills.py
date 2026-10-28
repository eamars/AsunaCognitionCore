"""Skill discovery roots; discovery and parsing remain native DSH services.

Skills are published resources (persona and channel packages). Changing one goes through the
development tools and `development_publish` only (ADR-011 §5.3); no sandbox mounts them writable.

Where a skill is offered (ADR-078): every skill in the owner's private conversations; elsewhere only a skill whose
`SKILL.md` header lists that kind of scene in `scene_kinds` (`home`, `group`, `dm`; absent means home only). DSH
discovers a root's own `.md` files as skills, so an allowed skill's folder is passed as a root of its own.
"""
import re
import sys
from pathlib import Path
from .records import scenes as scene_records
from . import records

SCENE_KINDS = ('home', 'group', 'dm')
FIELD = 'scene_kinds'
# The header keys DSH reads (dsh-skill-filesystem), and ours: any other top-level key is refused, so a misspelt
# `scene_kinds` is never silently home-only.
KEYS = ('name', 'description', 'whenToUse', 'disable-model-invocation', 'user-invocable', 'metadata', FIELD)
_KEY = re.compile(r'^([A-Za-z][A-Za-z0-9_-]*)\s*:(.*)$')
_LIST = re.compile(r'^\[\s*([a-z]+(?:\s*,\s*[a-z]+)*)?\s*\]$')


class SkillHeaderError(ValueError):
    pass


def header(text):
    """The top-level keys of a SKILL.md header, as {key: raw value}; raises SkillHeaderError when there is none."""
    lines = text.replace('\r\n', '\n').split('\n')
    if not lines or lines[0].strip() != '---':
        raise SkillHeaderError('SKILL.md 开头没有 --- 包着的头')
    found = {}
    for line in lines[1:]:
        if line.strip() == '---':
            return found
        if not line.strip() or line[0] in ' \t#':
            continue                                 # a nested value (metadata), a blank line or a comment
        match = _KEY.match(line)
        if not match:
            raise SkillHeaderError('头里这行读不出是哪个键：%s' % line[:60])
        found[match.group(1)] = match.group(2).strip()
    raise SkillHeaderError('SKILL.md 的头没有用 --- 收尾')


def scene_kinds(text):
    """The scene kinds a SKILL.md allows, as a tuple; raises SkillHeaderError on an unknown key or a wrong value."""
    keys = header(text)
    unknown = sorted(set(keys) - set(KEYS))
    if unknown:
        raise SkillHeaderError('头里有不认识的键 %s；能写的是 %s' % ('、'.join(unknown), '、'.join(KEYS)))
    if FIELD not in keys:
        return ('home',)
    match = _LIST.match(keys[FIELD])
    if not match or not match.group(1):
        raise SkillHeaderError('%s 写成列表，比如 [home, group]；现在是 %s' % (FIELD, keys[FIELD][:40] or '空的'))
    kinds = tuple(dict.fromkeys(part.strip() for part in match.group(1).split(',')))
    wrong = [kind for kind in kinds if kind not in SCENE_KINDS]
    if wrong:
        raise SkillHeaderError('%s 里的 %s 不在 %s 里' % (FIELD, '、'.join(wrong), '、'.join(SCENE_KINDS)))
    return kinds


def problems(root):
    """[(skill folder, words)] for every SKILL.md under a skills root whose header the program would refuse."""
    found = []
    for skill in sorted(Path(root).glob('*/SKILL.md')):
        try:
            scene_kinds(skill.read_text(encoding='utf-8'))
        except SkillHeaderError as exc:
            found.append((skill.parent.name, str(exc)))
    return found


def home_only(root):
    """The skill folders under a skills root whose header names no scene kinds: offered at home only."""
    return [skill.parent.name for skill in sorted(Path(root).glob('*/SKILL.md'))
            if FIELD not in header(skill.read_text(encoding='utf-8'))]


def _roots(config):
    roots = []
    for value in config.get('_skill_directories', []):
        path = Path(value).resolve()
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def skill_directories(config, scene_id, person_id, db=None):
    """Skill roots for a session: every root in the owner's private conversations; elsewhere one root per skill that
    lists this kind of scene (ADR-078)."""
    from . import visibility
    chat = config.get('chat', {})
    if (scene_id, person_id) == (chat.get('scene_id'), chat.get('person_id')):
        return _roots(config)
    scene = (scene_records.get(records.on(db), scene_id) if db is not None else None) or {'_id': scene_id}
    if db is not None and visibility.session_class(config, db, scene, person_id) == visibility.OWNER_PRIVATE:
        return _roots(config)
    kind = 'group' if scene.get('kind') == 'group' else 'dm'
    allowed = []
    for root in _roots(config):
        for skill in sorted(root.glob('*/SKILL.md')):
            try:
                kinds = scene_kinds(skill.read_text(encoding='utf-8'))
            except (OSError, SkillHeaderError) as exc:
                # Publication refuses such a header; one that got here anyway is said, not silently dropped.
                print('ASUNA_SKILL_HEADER_REFUSED %s: %s' % (skill.parent.name, exc), file=sys.stderr)
                continue
            if kind in kinds:
                allowed.append(skill.parent.resolve())
    return allowed


if __name__ == '__main__':
    # The publication probe: every skill header under the given skills roots, or exit with what to fix. A skill with
    # no scene kinds is valid and offered at home only; the receipt names it (her ask, 2026-10-22: a report, not a
    # refusal), so a skill left out of groups is never left out by accident.
    failed = [(name, words) for root in sys.argv[1:] for name, words in problems(root)]
    if failed:
        sys.exit('；'.join('技能 %s：%s' % item for item in failed) + '。照这个改 SKILL.md 的头再发布')
    home = [name for root in sys.argv[1:] for name in home_only(root)]
    print('Skill headers valid.' + ('\n只在家里可用（头里没写 %s）：%s' % (FIELD, '、'.join(home)) if home else ''))
