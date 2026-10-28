"""ADR-104: how many test functions the unit suite has and how many need a database (static, nothing is run).

    PYTHONUTF8=1 .venv/Scripts/python.exe docs/development_plans/ADR-104-database-connector/design/test_census.py
A test needs a database when it takes the `store` fixture, or a fixture of its own file that takes `store`.
Parametrized cases count once (pytest collects more items than this counts).
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
tests = ROOT / 'tests'
total = with_store = 0
files_with_store = files = mongomock = clients = 0
for path in sorted(tests.glob('test_*.py')):
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    fixtures = {'store'}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any('fixture' in ast.unparse(d) for d in node.decorator_list):
            if {a.arg for a in node.args.args} & fixtures:
                fixtures.add(node.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any('fixture' in ast.unparse(d) for d in node.decorator_list):
            if {a.arg for a in node.args.args} & fixtures:
                fixtures.add(node.name)
    n = s = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test'):
            n += 1
            if {a.arg for a in node.args.args} & fixtures:
                s += 1
    files += 1
    total += n
    with_store += s
    files_with_store += bool(s)
    mongomock += 'mongomock' in source
    clients += bool(re.search(r'MongoClient\(|Store\(', source))
print({'test_files': files, 'test_functions': total, 'need_a_database': with_store, 'files_needing_one': files_with_store,
       'files_using_mongomock': mongomock, 'files_making_a_client_or_store': clients})
