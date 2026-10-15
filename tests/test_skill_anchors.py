"""A skill points at code as `file:name` (her rule, 2026-10-15): the file is there and the name is in it. A line number
drifts with every edit and still points somewhere, so it is not an anchor."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = re.compile(r'`((?:src|tools|tests|packages|docs|config)/[\w./-]+\.\w+):([\w.$-]+)`')


def test_every_code_anchor_in_a_skill_names_something_in_that_file():
    wrong = []
    for skill in sorted(ROOT.glob('packages/**/skills/*/SKILL.md')):
        for path, name in ANCHOR.findall(skill.read_text(encoding='utf-8')):
            where = '%s: `%s:%s`' % (skill.relative_to(ROOT).as_posix(), path, name)
            target = ROOT / path
            if re.fullmatch(r'\d+(?:-\d+)?', name):
                wrong.append(where + ' is a line number; write the name there instead')
            elif not target.is_file():
                wrong.append(where + ': no such file')
            elif not re.search(r'(?<![\w$])%s(?![\w$])' % re.escape(name.split('.')[-1]),
                               target.read_text(encoding='utf-8', errors='replace')):
                wrong.append(where + ': the name is not in that file')
    assert not wrong, '\n'.join(wrong)
