"""ADR-104 call-site census: every direct database call in the core, one row each, with the owner operation it becomes.

Run from the checkout:  PYTHONUTF8=1 .venv/Scripts/python.exe docs/development_plans/ADR-104-database-connector/design/call_site_map.py
Writes <data>/private/adr104-research/call-site-map.tsv (not tracked: it names lines, which move) and prints counts. Reads only tracked Python files (git ls-files); touches
no database.

A call is counted when its receiver resolves to a collection or a GridFS bucket:
  <x>.db.<name>, <x>.db[<key>], db.<name> / db[<key>] for a name `db` (a parameter or a local bound to `<x>.db`),
  a name or `self.<attr>` bound to one of those, a client subscript (`client[db][name]`), GridFSBucket(...).
The key of a subscript is resolved through module constants; anything else is `<dynamic>`.

Each row gets an owner operation: by rule (collection, method, condition shape) from RULES in owner_ops.py, or by
hand (HAND, keyed by file:line) for the dynamic and merged conditions. A row no rule or hand entry assigns is written
with `UNASSIGNED` and makes the script exit 1 (a census with unassigned rows is not done).
"""
from __future__ import annotations

import ast
import collections
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import owner_ops  # noqa: E402

AREAS = ('src/asuna', 'tools', 'integration')
METHODS = {'find_one', 'find', 'update_one', 'update_many', 'count_documents', 'delete_many', 'delete_one',
           'distinct', 'insert_one', 'insert_many', 'replace_one', 'find_one_and_update', 'find_one_and_replace',
           'find_one_and_delete', 'aggregate', 'bulk_write', 'create_index', 'create_indexes', 'drop',
           'list_search_indexes', 'create_search_index', 'update_search_index', 'index_information',
           'estimated_document_count', 'list_collection_names', 'create_collection', 'drop_collection',
           'list_collections', 'get_collection', 'drop_database'}
BUCKET_METHODS = {'upload_from_stream', 'open_download_stream', 'delete', 'find', 'open_upload_stream',
                  'download_to_stream', 'rename'}
DB_NAMES = {'db', 'database'}
GLOBAL_ATTRS = {}   # <obj>.<attr> bound to a collection in some class (self.<attr> = ...), filled by census()
CURSOR = {'sort', 'limit', 'skip'}
STORE_API = {'put', 'get', 'head', 'init_head', 'mutate', 'authorize', 'identity', 'public_messages', 'nearest',
             'ensure_vectors', 'recover_commits', 'migrate', 'seed', 'audit'}


def files():
    out = subprocess.run(['git', 'ls-files', '--', *AREAS], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.endswith('.py')]


def constants(tree):
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value.value
    return found


class Scope:
    """Name bindings: module level, then per function (a later binding in the same function wins: good enough)."""

    def __init__(self, consts):
        self.consts = consts
        self.bound = {}          # name -> ('db',) | ('coll', name) | ('bucket', name)
        self.attrs = {}          # self.<attr> -> same


def classify(node, scope, local):
    """('db',) for a database handle, ('coll', name) for a collection, ('bucket', name), or None."""
    if isinstance(node, ast.Name):
        if node.id in local:
            return local[node.id]
        if node.id in scope.bound:
            return scope.bound[node.id]
        if node.id in DB_NAMES:
            return ('db',)
        return None
    if isinstance(node, ast.Attribute):
        if node.attr == 'db' or (node.attr == 'admin' and isinstance(node.value, ast.Attribute)
                                 and node.value.attr == 'client'):
            return ('db',)
        if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr in scope.attrs:
            return scope.attrs[node.attr]
        if not (isinstance(node.value, ast.Name) and node.value.id == 'self') and node.attr in GLOBAL_ATTRS:
            return GLOBAL_ATTRS[node.attr]
        base = classify(node.value, scope, local)
        if base == ('db',):
            if node.attr in METHODS:
                return None
            return ('coll', node.attr)
        if base and base[0] == 'coll' and node.attr in ('files', 'chunks'):
            return ('coll', base[1] + '.' + node.attr)
        return None
    if isinstance(node, ast.Subscript):
        base = classify(node.value, scope, local)
        key = node.slice
        if base == ('db',) or base == ('client',):
            name = None
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                name = key.value
            elif isinstance(key, ast.Name) and key.id in scope.consts:
                name = scope.consts[key.id]
            elif isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name) and key.attr.isupper():
                name = '%s.%s' % (key.value.id, key.attr)    # another module's constant, resolved below
            if base == ('client',):
                return ('db',)
            return ('coll', name or '<dynamic>')
        if isinstance(node.value, ast.Attribute) and node.value.attr == 'client':
            return ('db',)
        if isinstance(node.value, ast.Name) and node.value.id == 'client':
            return ('db',)
        return None
    if isinstance(node, ast.IfExp):
        a, b = classify(node.body, scope, local), classify(node.orelse, scope, local)
        if a and b and a[0] == b[0] == 'coll':
            return a if a == b else ('coll', a[1] + '|' + b[1])
        return a or b
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == 'getattr' and len(node.args) >= 2:
            base = classify(node.args[0], scope, local)
            key = node.args[1]
            name = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None
            if name is None and isinstance(key, ast.Name) and key.id in scope.consts:
                name = scope.consts[key.id]
            if name == 'db':
                return ('db',)
            if base == ('db',):
                return ('coll', name or '<dynamic>')
            if base and base[0] == 'coll' and name in METHODS:
                return ('method', base[1], name)
            return None
        if isinstance(func, ast.Name) and func.id == 'GridFSBucket':
            name = 'fs'
            for kw in node.keywords:
                if kw.arg == 'bucket_name' and isinstance(kw.value, ast.Constant):
                    name = kw.value.value
            return ('bucket', name)
        if isinstance(func, ast.Attribute) and func.attr == 'get_database':
            return ('db',)
        if isinstance(func, ast.Attribute) and func.attr == 'collection':
            # dbread.Reader.collection(name) returns a collection chosen by her script
            return ('coll', '<dynamic>')
    return None


def bind(target, value, scope, local, top):
    if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
        for t, v in zip(target.elts, value.elts):
            bind(t, v, scope, local, top)
        return
    kind = classify(value, scope, local)
    if not kind:
        return
    if isinstance(target, ast.Name):
        (scope.bound if top else local)[target.id] = kind
    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
        scope.attrs[target.attr] = kind


def shape_of_value(value):
    if isinstance(value, ast.Constant):
        if value.value is None:
            return 'eqnull'
        if isinstance(value.value, (str, bool, int)) and len(str(value.value)) <= 28:
            return 'eq=' + str(value.value)
        return 'eq'
    if isinstance(value, ast.Dict) and len(value.keys) == 1 and isinstance(value.keys[0], ast.Constant)             and value.keys[0].value in ('$in', '$nin', '$ne') and isinstance(value.values[0], (ast.List, ast.Tuple))             and all(isinstance(e, ast.Constant) for e in value.values[0].elts):
        return value.keys[0].value[1:] + '=' + '/'.join(str(e.value) for e in value.values[0].elts)
    if isinstance(value, ast.Dict) and len(value.keys) == 1 and isinstance(value.keys[0], ast.Constant)             and value.keys[0].value in ('$ne', '$exists') and isinstance(value.values[0], ast.Constant):
        return value.keys[0].value[1:] + '=' + str(value.values[0].value)
    if isinstance(value, ast.Dict):
        ops = []
        for key in value.keys:
            if key is None:
                ops.append('**')
            elif isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.startswith('$'):
                ops.append(key.value[1:])
            else:
                return 'eqdict'
        return '+'.join(sorted(ops)) if ops else 'eqdict'
    if isinstance(value, (ast.List, ast.Tuple)):
        return 'eqlist'
    return 'val'


def shape_of(node):
    """A condition's shape: sorted field:op entries; nested $or/$and shown inline; merged parts as **."""
    if node is None:
        return '{}'
    if not isinstance(node, ast.Dict):
        return '<var>'
    parts = []
    for key, value in zip(node.keys, node.values):
        if key is None:
            parts.append('**')
            continue
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            name = key.value
            if name in ('$or', '$and', '$nor'):
                if isinstance(value, (ast.List, ast.Tuple)):
                    inner = '|'.join(shape_of(item) for item in value.elts)
                else:
                    inner = '<var>'
                parts.append('%s(%s)' % (name[1:], inner))
            elif name == '$expr':
                parts.append('expr')
            elif name.startswith('$'):
                parts.append(name[1:])
            else:
                parts.append('%s:%s' % (name, shape_of_value(value)))
        else:
            parts.append('<key>')
    return '{%s}' % ','.join(sorted(parts))


def change_of(node):
    if node is None:
        return ''
    if isinstance(node, ast.List):
        return 'pipeline'
    if not isinstance(node, ast.Dict):
        return '<var>'
    parts = []
    for key, value in zip(node.keys, node.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.startswith('$'):
            fields = ''
            if isinstance(value, ast.Dict):
                fields = '(%s)' % ','.join(sorted(k.value for k in value.keys
                                                  if isinstance(k, ast.Constant) and isinstance(k.value, str)))
            parts.append(key.value[1:] + fields)
        elif key is None:
            parts.append('**')
        else:
            return 'replace'
    return ' '.join(parts)


def arg(call, index, name):
    if len(call.args) > index:
        return call.args[index]
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def describe(call, method):
    """(condition shape, change shape, modifiers) of a call."""
    mods = []
    for kw in call.keywords:
        if kw.arg in ('sort', 'upsert', 'limit', 'skip', 'projection', 'return_document', 'array_filters'):
            if kw.arg == 'sort':
                mods.append('sort[%s]' % '>'.join(map(str, sort_keys(kw.value))))
            else:
                mods.append(kw.arg + ('=True' if kw.arg == 'upsert' and isinstance(kw.value, ast.Constant) and kw.value.value else ''))
    if method in ('find_one', 'find', 'count_documents', 'delete_many', 'delete_one', 'find_one_and_delete'):
        cond = shape_of(arg(call, 0, 'filter'))
        if method in ('find', 'find_one') and (len(call.args) > 1 or any(k.arg == 'projection' for k in call.keywords)):
            mods.append('fields')
        return cond, '', mods
    if method in ('update_one', 'update_many', 'find_one_and_update'):
        return shape_of(arg(call, 0, 'filter')), change_of(arg(call, 1, 'update')), mods
    if method in ('replace_one', 'find_one_and_replace'):
        return shape_of(arg(call, 0, 'filter')), 'replace', mods
    if method == 'distinct':
        key = arg(call, 0, 'key')
        field = key.value if isinstance(key, ast.Constant) else '<var>'
        return shape_of(arg(call, 1, 'filter')), 'field=' + str(field), mods
    if method == 'insert_one':
        return '', 'insert', mods
    if method == 'insert_many':
        return '', 'insert_many', mods
    if method == 'aggregate':
        node = arg(call, 0, 'pipeline')
        stages = []
        if isinstance(node, ast.List):
            for item in node.elts:
                if isinstance(item, ast.Dict) and item.keys and isinstance(item.keys[0], ast.Constant):
                    stages.append(item.keys[0].value)
                else:
                    stages.append('<var>')
        return '', 'pipeline[%s]' % ' '.join(stages) if stages else 'pipeline<var>', mods
    return '', '', mods


def sort_keys(node):
    """The field names of a sort argument: 'f', [('f', -1), ...] or {'f': -1}; '?' where computed."""
    if node is None:
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        if node.elts and all(isinstance(e, ast.Tuple) for e in node.elts):
            return [e.elts[0].value if isinstance(e.elts[0], ast.Constant) else '?' for e in node.elts]
        if node.elts and isinstance(node.elts[0], ast.Constant):
            return [node.elts[0].value]
    if isinstance(node, ast.Dict):
        return [k.value if isinstance(k, ast.Constant) else '?' for k in node.keys]
    return ['?']


def chained(parents, call):
    """sort/limit/skip applied on a find's cursor; a sort carries its keys: sort[a>b]."""
    out = []
    node = call
    while True:
        parent = parents.get(id(node))
        if isinstance(parent, ast.Attribute) and parent.attr in CURSOR:
            grand = parents.get(id(parent))
            if isinstance(grand, ast.Call):
                if parent.attr == 'sort':
                    out.append('sort[%s]' % '>'.join(map(str, sort_keys(grand.args[0] if grand.args else None))))
                else:
                    out.append(parent.attr)
                node = grand
                continue
        break
    return out


def census():
    rows = []
    module_consts = {}
    trees = {}
    for path in files():
        source = (ROOT / path).read_text(encoding='utf-8')
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        trees[path] = tree
        module_consts[Path(path).stem] = constants(tree)
    for path, tree in trees.items():
        scope = Scope(module_consts[Path(path).stem])
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        bind(target, node.value, scope, {}, True)
        for attr, kind in scope.attrs.items():
            if attr not in ('db', 'client', 'store'):
                GLOBAL_ATTRS.setdefault(attr, kind)
    for path, tree in trees.items():
        scope = Scope(dict(module_consts[Path(path).stem]))
        for node in ast.walk(tree):          # names imported from another module's constants (function imports too)
            if isinstance(node, ast.ImportFrom) and node.module:
                source = module_consts.get(node.module.split('.')[-1], {})
                for alias in node.names:
                    if alias.name in source and (alias.asname or alias.name) not in scope.consts:
                        scope.consts[alias.asname or alias.name] = source[alias.name]
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        # module-level and class-level (self.x = ...) bindings first
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        bind(target, node.value, scope, {}, True)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    bind(target, node.value, scope, {}, True)

        def visit(func_node, name):
            local = {}
            for node in ast.walk(func_node):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        bind(target, node.value, scope, local, False)
                elif isinstance(node, (ast.With,)):
                    for item in node.items:
                        if item.optional_vars is not None:
                            bind(item.optional_vars, item.context_expr, scope, local, False)
            for node in ast.walk(func_node):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    handle = local.get(node.func.id) or scope.bound.get(node.func.id)
                    if not (handle and handle[0] == 'method'):
                        continue
                    method, kind = handle[2], ('coll', handle[1])
                elif isinstance(node.func, ast.Attribute):
                    method = node.func.attr
                    kind = classify(node.func.value, scope, local)
                    receiver = ast.unparse(node.func.value)
                    if (not kind and method in STORE_API and (receiver == 'store' or receiver.endswith('.store')
                            or receiver in ('self.app.store',) or (receiver == 'self' and path.endswith('state.py')))):
                        coll = '<store>'
                        first = node.args[0] if node.args else None
                        if method in ('put', 'get') and isinstance(first, ast.Constant) and isinstance(first.value, str):
                            coll = first.value
                        elif method in ('put', 'get'):
                            coll = '<dynamic>'
                        elif method == 'audit':
                            coll = 'audit_events'
                        elif method in ('head', 'init_head', 'mutate'):
                            coll = 'state_heads'
                        elif method in ('authorize',):
                            coll = 'scenes'
                        elif method in ('identity',):
                            coll = 'identities'
                        elif method in ('public_messages',):
                            coll = 'messages'
                        elif method in ('nearest', 'ensure_vectors'):
                            coll = 'memory_units'
                        shape = ''
                        if method == 'put':
                            shape = 'expected' if any(k.arg == 'expected' for k in node.keywords) else 'new'
                        rows.append({'file': path, 'line': node.lineno, 'col': node.col_offset, 'function': name,
                                     'collection': coll, 'method': 'Store.' + method, 'shape': shape, 'change': '',
                                     'mods': ''})
                        continue
                else:
                    continue
                if not kind:
                    continue
                if kind[0] == 'coll' and method in METHODS:
                    coll = kind[1]
                elif kind[0] == 'bucket' and method in BUCKET_METHODS:
                    coll = 'gridfs:' + kind[1]
                elif kind == ('db',) and method in ('list_collection_names', 'create_collection', 'drop_collection',
                                                    'list_collections', 'drop_database'):
                    coll = '<database>'
                elif kind == ('db',) and method == 'command':
                    second = node.args[1] if len(node.args) > 1 else None
                    coll = second.value if isinstance(second, ast.Constant) else 'command:' + (
                        node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else '?')
                else:
                    continue
                if '.' in coll and coll.split('.')[0][:1].islower() and coll.split('.')[1].isupper():
                    mod, const = coll.split('.')
                    coll = module_consts.get(mod, {}).get(const, coll)
                cond, change, mods = describe(node, method)
                mods = mods + chained(parents, node)
                rows.append({'file': path, 'line': node.lineno, 'col': node.col_offset, 'function': name, 'collection': coll,
                             'method': method, 'shape': cond, 'change': change, 'mods': ','.join(mods)})

        # Each function is visited with its own local bindings; a call seen by several visits (an outer function's
        # walk reaches its nested functions) keeps the last view, the innermost function's.
        collected = []
        for node in [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            before = len(rows)
            visit(node, getattr(node, 'name', '<module>'))
            new = rows[before:]
            del rows[before:]
            for row in new:
                key = (row['file'], row['line'], row['col'], row['method'])
                collected.append((key, row))
        # keep one row per call: the innermost function's view (the last visit that saw it)
        final = {}
        for key, row in collected:
            final[key] = row
        # attribute to the innermost function by line range
        funcs = [(n.lineno, n.end_lineno, n.name) for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for row in final.values():
            inner = [f for f in funcs if f[0] <= row['line'] <= f[1]]
            row['function'] = min(inner, key=lambda f: f[1] - f[0])[2] if inner else '<module>'
            rows.append(row)
    rows.sort(key=lambda r: (r['file'], r['line'], r['method']))
    return rows


def main():
    rows = census()
    unassigned = 0
    for row in rows:
        op, how = owner_ops.assign(row)
        row['owner_op'], row['how'] = op, how
        if op == 'UNASSIGNED':
            unassigned += 1
    out = ROOT / '.runtime' / 'private' / 'adr104-research' / 'call-site-map.tsv'
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = ['file', 'line', 'function', 'collection', 'method', 'shape', 'change', 'mods', 'owner_op', 'how']
    with out.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write('\t'.join(cols) + '\n')
        for row in rows:
            handle.write('\t'.join(str(row[c]) for c in cols) + '\n')
    by_area = collections.Counter(r['file'].split('/')[0] if not r['file'].startswith('src/') else 'src/asuna' for r in rows)
    by_how = collections.Counter(r['how'] for r in rows)
    by_method = collections.Counter(r['method'] for r in rows)
    ops = collections.Counter(r['owner_op'] for r in rows)
    print('rows', len(rows), dict(by_area))
    print('how', dict(by_how))
    print('methods', dict(by_method.most_common()))
    print('distinct owner_op labels (a label may name several operations; shared-layer ones included)',
          len([o for o in ops if o not in ('UNASSIGNED',)]))
    print('unassigned', unassigned)
    if '--verbose' in sys.argv:
        for row in rows:
            if row['owner_op'] == 'UNASSIGNED':
                print('\t'.join(str(row[c]) for c in cols[:8]))
    return 1 if unassigned else 0


if __name__ == '__main__':
    sys.exit(main())
