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


# A value of the call: the parameters that hold her arguments, what is read from them, and copies of it.
_CALL = {'args', 'item', 'part'}
_KEEPS = {'str', 'strip', 'lstrip', 'rstrip', 'lower', 'upper', 'join', 'split', 'replace', 'list', 'tuple', 'sorted',
          'items', 'values', 'keys', 'enumerate'}


def _hers(node, names):
    import ast
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Subscript):
        return _hers(node.value, names)
    if isinstance(node, ast.Call):
        func, name = node.func, getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
        if name == '_text' or name == 'get' and isinstance(func, ast.Attribute) and _hers(func.value, names):
            return True
        inside = [func.value] if isinstance(func, ast.Attribute) and name != 'join' else []
        return name in _KEEPS and any(_hers(a, names) for a in [*inside, *node.args])
    if isinstance(node, ast.BoolOp):                 # `a and b` is b; `a or b` may be either
        return _hers(node.values[-1], names) if isinstance(node.op, ast.And) else any(_hers(v, names) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _hers(node.body, names) or _hers(node.orelse, names)
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
        inner = names | {n for g in node.generators if _hers(g.iter, names) for n in _bound(g.target, g.iter)}
        return any(_hers(e, inner) for e in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)))
    return False


def _bound(target, source):
    """The names a loop binds to her values: `for i, x in enumerate(...)` binds x, not i."""
    import ast
    if isinstance(source, ast.Call) and getattr(source.func, 'id', None) == 'enumerate' and isinstance(target, ast.Tuple):
        target = ast.Tuple(elts=target.elts[1:])
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def test_every_value_a_refusal_shows_back_from_the_call_is_bounded():
    """A refusal that shows a value of her call shows `config.echoed(value)`: a name, a choice or an id whole, never
    more than a few characters of her prose. Followed through assignments, loops and the functions a value is handed to
    (by name, in its module or one it imports); not through an object's method or a regex match."""
    import ast
    from asuna.config import echoed
    assert echoed('task-' + '0' * 32) == 'task-' + '0' * 32 and echoed('[名字 #4]') == '[名字 #4]'
    assert echoed('我想问问他最近是不是有点不开心，因为昨天') == '我想问问他最近是不是有点不开心，…'
    trees = {p.stem: ast.parse(p.read_text(encoding='utf-8')) for p in sorted(SRC.glob('*.py')) if p.name != 'vision.py'}
    functions, aliases = {}, {}
    for mod, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.setdefault((mod, node.name), node)
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                for a in node.names:
                    aliases[(mod, a.asname or a.name)] = (a.name, None) if node.module is None else (node.module, a.name)

    def callee(mod, call):
        f = call.func
        if isinstance(f, ast.Name):
            got = aliases.get((mod, f.id))
            return got if got and got[1] else (mod, f.id)
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            got = aliases.get((mod, f.value.id))
            return (mod, f.attr) if f.value.id == 'self' else (got[0], f.attr) if got and got[1] is None else None
        return None

    def parameters(func):
        return [a.arg for a in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs] if a.arg != 'self']

    handed, names = {key: set() for key in functions}, {}
    for _ in range(4):
        for key, func in functions.items():
            known = {p for p in parameters(func) if p in _CALL} | handed[key]
            for _ in range(2):
                for node in ast.walk(func):
                    if isinstance(node, ast.Assign) and _hers(node.value, known):
                        known |= {n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
                    if isinstance(node, ast.For) and _hers(node.iter, known):
                        known |= _bound(node.target, node.iter)
            names[key] = known
            wide = known | {n for c in ast.walk(func) if isinstance(c, ast.comprehension) and _hers(c.iter, known)
                            for n in _bound(c.target, c.iter)}
            for node in ast.walk(func):
                to = isinstance(node, ast.Call) and callee(key[0], node)
                if to in functions and to != key:
                    own = parameters(functions[to])
                    handed[to] |= {own[i] for i, a in enumerate(node.args) if i < len(own) and _hers(a, wide)}
                    handed[to] |= {k.arg for k in node.keywords if k.arg in own and _hers(k.value, wide)}
    problems = []
    for key, func in functions.items():
        raised = {id(n.exc) for n in ast.walk(func) if isinstance(n, ast.Raise)}
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            coded = name == 'append' and node.args and isinstance(node.args[0], ast.Tuple) and node.args[0].elts \
                and isinstance(node.args[0].elts[0], ast.Constant) and re.fullmatch(r'[A-Z][A-Z0-9_]+', str(node.args[0].elts[0].value))
            if name not in ('Refused', '_found', 'problem') and id(node) not in raised and not coded:
                continue                              # a refusal: raised, a problem found, or a (CODE, words) kept
            for sub in ast.walk(node):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mod):
                    shown = sub.right.elts if isinstance(sub.right, ast.Tuple) else [sub.right]
                elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Add):
                    shown = [sub.left, sub.right]
                elif isinstance(sub, ast.JoinedStr):
                    shown = [v.value for v in sub.values if isinstance(v, ast.FormattedValue)]
                else:
                    continue
                problems += ['%s.py:%d %s' % (key[0], node.lineno, ast.unparse(v)[:40]) for v in shown if _hers(v, names[key])]
    assert not problems, 'show these through config.echoed: %s' % sorted(set(problems))
