"""ADR-105: an operator erasure deletes a conversation's stored bytes and marks each of its rows `erased`; whatever
looks one up by its id answers with the one sentence, never "not found", and a sending tool says it in the very call
that names the erased file or picture. A row outside the caller's fence is refused as before, so the sentence never
tells anyone that a row they may not see exists."""
import ast
from pathlib import Path


from asuna.config import ROOT


# ── every lookup by id ──────────────────────────────────────────────
def _stored_mark(side):
    """'gridfs', or the owner's name for it (records.artifacts.STORED)."""
    return (isinstance(side, ast.Constant) and side.value == 'gridfs') or (
        isinstance(side, ast.Attribute) and side.attr == 'STORED')


def _judges_storage(fn):
    """Whether a function compares a value with 'gridfs' (or the owner's STORED), or looks an artifacts row up by
    `_id` filtered on storage (the owner's `get` with a storage, or a direct read)."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and any(_stored_mark(side) for side in (node.left, *node.comparators)):
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get'
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'artifact_records'
                and any(keyword.arg == 'storage' for keyword in node.keywords)):
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'find_one'
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'artifacts'
                and node.args and isinstance(node.args[0], ast.Dict)):
            keys = {key.value for key in node.args[0].keys if isinstance(key, ast.Constant)}
            if {'_id', 'storage'} <= keys:
                return True
    return False


def lookups_without_the_mark(sources):
    """(path, function) for each function that judges a row's storage by its id but never names the erased mark.
    A list of everything (offers, the sweep) reads `gridfs` with `find` and is not a lookup by id."""
    marks = {'erased', 'refuse_erased', 'erased_words', 'refuse_erased_named'}
    missing = []
    for path, text in sources:
        for fn in ast.walk(ast.parse(text)):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _judges_storage(fn):
                names = {getattr(node, 'id', None) or getattr(node, 'attr', None) for node in ast.walk(fn)}
                if not names & marks:
                    missing.append((path, fn.name))
    return missing


def test_every_lookup_by_id_that_judges_storage_handles_the_erased_mark():
    sources = [(path.relative_to(ROOT).as_posix(), path.read_text(encoding='utf-8'))
               for path in sorted((ROOT / 'src' / 'asuna').rglob('*.py'))]
    assert len(sources) > 50
    assert lookups_without_the_mark(sources) == []
    forgot = ("def look(store, key):\n"
              "    row = store.db.artifacts.find_one({'_id': key})\n"
              "    if row.get('storage') != 'gridfs':\n"
              "        raise ValueError('gone')\n")
    filtered = "def look(store, key):\n    return store.db.artifacts.find_one({'_id': key, 'storage': 'gridfs'})\n"
    owned = ("def look(store, key):\n"
             "    row = artifact_records.get(store, key)\n"
             "    if row.get('storage') != artifact_records.STORED:\n"
             "        raise ValueError('gone')\n")
    asked = "def look(store, key):\n    return artifact_records.get(store, key, storage=artifact_records.STORED)\n"
    assert lookups_without_the_mark([('a.py', forgot), ('b.py', filtered), ('c.py', owned), ('d.py', asked)]) == [
        ('a.py', 'look'), ('b.py', 'look'), ('c.py', 'look'), ('d.py', 'look')], 'the test itself bites'


