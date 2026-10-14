"""ADR-060: the words she reads (tool texts, notes, refusals) name a parameter only by the name she is shown. The old
names still run for a while (param_names), but no sentence of the program's teaches them again."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r'[一-鿿]')
# Old parameter names a sentence of hers could only mean as a parameter; generic English words are left out.
OLD = re.compile(r'(?<![A-Za-z_.])(op|inject|sid|mode|body|reason|workflows)(?![A-Za-z_])')
# Strings that hold an old name on purpose: the rename note itself, and where the old name is the subject.
KEPT = {('param_names.py', 'NOTE')}
NOT_HERS = {'audit.py'}                      # the owner's audit page, not a model's


def sentences():
    for path in sorted((ROOT / 'src' / 'asuna').glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        docs = {id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        names = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and node.col_offset == 0:
                for sub in ast.walk(node.value):
                    names[id(sub)] = ','.join(getattr(t, 'id', '?') for t in node.targets)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value)
                    and id(node) not in docs and (path.name, names.get(id(node))) not in KEPT and path.name not in NOT_HERS):
                yield path.name, node.lineno, node.value


def test_no_sentence_of_hers_names_a_parameter_by_its_old_name():
    found = ['%s:%d %s' % (name, line, text[:60]) for name, line, text in sentences() if OLD.search(text)]
    assert found == [], 'say the name she is shown (param_names.RENAMED):\n' + '\n'.join(found)
