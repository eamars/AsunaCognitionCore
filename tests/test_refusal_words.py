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
    plain = '「x」不是本地钟点：写成 2026-10-12 21:00 或 2026-10-12（整天）'
    assert role_tools.words(ValueError(plain)) == plain, 'a colon in words is no code'


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


def test_echoed_keeps_a_name_or_an_id_whole_and_cuts_prose():
    from asuna.config import echoed
    task_id = 'task-' + '0' * 32
    prose = '我想问问他最近是不是有点不开心，因为昨天他说话很少'
    assert echoed('[名字 #4]') == '[名字 #4]' and echoed(task_id) == task_id
    assert echoed(prose) == prose[:16] + '…'
    assert role_tools._given({'layer': prose}, 'layer') == '（给的是「%s」）' % echoed(prose)


_CALL = {'args', 'item', 'part'}             # what holds her call's arguments


def _from_call(node, names):
    """A value read from her call in this function: args/item/part .get() or ['field'], self._text(args, ...), a copy
    of one (str(), a strip, a slice, `or ''`), or a name assigned from one here."""
    import ast
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.BoolOp):
        return any(_from_call(v, names) for v in node.values)
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name) and node.value.id in _CALL:
            return isinstance(node.slice, ast.Constant)            # args['field'], not a slice of a list of hers
        return _from_call(node.value, names)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ('get', '_text'):
            held = func.value if func.attr == 'get' else (node.args[0] if node.args else None)
            return isinstance(held, ast.Name) and held.id in _CALL
        if isinstance(func, ast.Name) and func.id == 'str':
            return bool(node.args) and _from_call(node.args[0], names)
        if isinstance(func, ast.Attribute) and func.attr in ('strip', 'lstrip', 'rstrip', 'lower', 'upper'):
            return _from_call(func.value, names)
    return False


def test_a_refusal_shows_a_value_of_the_call_only_through_echoed():
    """Within one function: a value read from args, item or part that a refusal's words format (%, an f-string or +)
    goes through config.echoed, so a long value never comes back in full."""
    import ast
    problems = []
    for path in sorted(SRC.glob('*.py')):
        for func in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {t.id for node in ast.walk(func) if isinstance(node, ast.Assign) and _from_call(node.value, set())
                     for t in node.targets if isinstance(t, ast.Name)}
            raised = {id(node.exc) for node in ast.walk(func) if isinstance(node, ast.Raise)}
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                kept = name == 'append' and node.args and isinstance(node.args[0], ast.Tuple) and node.args[0].elts \
                    and isinstance(node.args[0].elts[0], ast.Constant) \
                    and re.fullmatch(r'[A-Z][A-Z0-9_]+', str(node.args[0].elts[0].value))
                if name not in ('Refused', '_found', 'problem') and id(node) not in raised and not kept:
                    continue                          # a refusal: raised, a problem found, or a (CODE, words) kept
                for sub in ast.walk(node):
                    if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mod):
                        shown = sub.right.elts if isinstance(sub.right, ast.Tuple) else [sub.right]
                    elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Add):
                        shown = [sub.left, sub.right]
                    elif isinstance(sub, ast.JoinedStr):
                        shown = [v.value for v in sub.values if isinstance(v, ast.FormattedValue)]
                    else:
                        continue
                    problems += ['%s:%d %s' % (path.name, node.lineno, ast.unparse(v)[:40])
                                 for v in shown if _from_call(v, names)]
    assert not problems, 'show these through config.echoed: %s' % sorted(set(problems))
