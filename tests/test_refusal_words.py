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
    assert problem.startswith('intent 太长了：1200 字，过了 1000 字的线 200 字（要求 800 字以内）')
    # The scheduler's own guard carries a code that names the cause; role_tools shows words() of it.
    text = role_tools.words(ValueError('PLAN_INTENT_INVALID: ' + problem))
    assert 'PLAN_INTENT_INVALID' not in text and text.startswith('intent 太长了：1200 字')


def test_every_refusal_names_its_code_and_her_words_start_with_none():
    """Each `Refused` and each problem a handler finds (`_found`) names its codes (ADR-108 D4b), which the record keeps,
    so every refusal can be counted by code; a message written out never starts with a code, which is not her words."""
    import ast
    problems = []
    for path in sorted(SRC.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        other = any(isinstance(node, ast.ClassDef) and node.name == 'Refused' for node in ast.walk(tree)) \
            or any(isinstance(node, ast.ImportFrom) and node.module == 'vision' and any(a.name == 'Refused' for a in node.names)
                   for node in ast.walk(tree))
        if other and path.name != 'role_tools.py':
            continue                                  # a module's own Refused (vision.py: a fetch refused)
        for node in ast.walk(tree):
            name = isinstance(node, ast.Call) and (getattr(node.func, 'id', None) or getattr(node.func, 'attr', None))
            if name not in ('Refused', '_found'):
                continue
            where = '%s:%d' % (path.name, node.lineno)
            codes = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg in ('codes', 'code')), None)
            empty = codes is None or (isinstance(codes, ast.Constant) and not codes.value) or (
                isinstance(codes, (ast.List, ast.Tuple))
                and (not codes.elts or any(isinstance(e, ast.Constant) and not e.value for e in codes.elts)))
            if empty:
                problems.append(where + ' names no code')
            head = node.args[0] if node.args else None
            while isinstance(head, ast.BinOp):
                head = head.left
            if isinstance(head, ast.Constant) and isinstance(head.value, str) and re.match(r'[A-Z][A-Z0-9_]+:', head.value):
                problems.append(where + ' starts her words with a code')
    assert not problems, problems
