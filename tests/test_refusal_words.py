"""Every refusal she reads is words, never a bare code (ADR-060; ADR-076 R2). A coded error raised without its detail
reaches her as the code alone unless `role_tools.WORDS` knows it, so each such raise site must have an entry; and
`words()` itself never returns an empty or code-only text."""
import re
from pathlib import Path

from asuna import role_tools
from asuna.affect import AffectError
from asuna.documents import DocumentError

SRC = Path(role_tools.__file__).parent
# The error classes whose message reaches the character brain through role_tools.words().
BARE = re.compile(r"raise (?:AffectError|DocumentError)\('([A-Z_]+)'\)")


def test_a_coded_error_raised_without_detail_has_words():
    missing = []
    for path in sorted(SRC.glob('*.py')):
        for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for code in BARE.findall(line):
                if code not in role_tools.WORDS:
                    missing.append('%s:%d %s' % (path.name, line_no, code))
    assert not missing, 'add a WORDS entry (role_tools.py) or a detail in words to: ' + ', '.join(missing)


def test_words_never_hands_her_a_bare_code():
    for exc in (AffectError('CLOSE_REQUIRES_OPEN'), DocumentError('DOC_OP_NOT_ALLOWED'), ValueError('SOME_CODE'),
                ValueError('SOME_CODE: machine detail id-1234')):
        text = role_tools.words(exc)
        assert text and text != role_tools.code_of(exc) and re.search(r'[一-鿿]', text), text


def test_a_plan_length_refusal_names_its_cause_not_the_schedule_code():
    from asuna import schedule
    problem = schedule.intent_problem('x' * 1200)
    assert problem.startswith('intent 1200 字，上限 1000 字')
    # The scheduler's own guard carries a code that names the cause; role_tools shows words() of it.
    text = role_tools.words(ValueError('PLAN_INTENT_INVALID: ' + problem))
    assert 'PLAN_INTENT_INVALID' not in text and text.startswith('intent 1200 字')
