"""The store's boundary, read from the code (ADR-104 decision 9): the core reaches its records only through their
owner modules, and MongoDB only through its adapter. A static check by AST over `src/asuna` and `tools`, no database;
each finding names its file, line and rule. Imports are resolved (relative ones included), never matched as text.

- drivers: `pymongo`, `bson`, `gridfs`, `asuna.store.mongodb` and the name `MongoClient` are imported in `src/asuna`
  only by the adapter, the registry and her read tool (`ADAPTER_MODULES`), and in `tools` only by `TOOL_CLIENTS`.
- store-surface: `Store` defines no `db` or `client`. On a store (a receiver named `store`, or ending in `.store` or
  `_store`) no module reads `db` or `client`, by attribute or by `getattr`/`hasattr`; `adapter` and `checked` only in
  `store/` and `state.py`; `maintenance` (on any receiver) only in `audit.py`.
- owner: `<store>.collection(x)` and `<store>.put(x, ...)` name a collection the module owns (the catalog's `owner`).
  `x` is resolved through literals, the module's own constants, imported names and `module.CONST`; a name that cannot
  be resolved passes only as a parameter of the function or one of the module's own constants, and only in a module
  that chooses among its own collections (`CHOOSERS`) or in the shared layer (`SHARED`).
- artifact-touches: no call passes `reset_counters` (or a `**` splat that could carry it) to the stored files'
  owner (`records.artifacts.save`) or to a put of `artifacts`; and that owner forwards its keyword arguments, so its
  refusal sees every one.
"""
import ast
from pathlib import Path

from asuna import repo_files
from asuna.store.catalog import CATALOG

ROOT = Path(__file__).resolve().parents[1]
DRIVERS = ('pymongo', 'bson', 'gridfs', 'asuna.store.mongodb')
# Who may import a driver in src/asuna: the MongoDB adapter itself, the registry (it imports the adapter by name when
# the built-in kind is first asked for), and dbread, her MongoDB read tool with its own client (decision 9).
ADAPTER_MODULES = {'src/asuna/store/mongodb.py', 'src/asuna/store/adapters.py', 'src/asuna/dbread.py'}
# Tools that keep a client of their own, each for a verb the store has no word for.
TOOL_CLIENTS = {
    'tools/cleanup_test_databases.py': "lists the server's leftover asuna_v2_test_* databases and drops the "
                                       'inventoried ones; no store is opened on them',
    'tools/memory_pilot_report.py': "--drop removes the pilot's whole collection, which the store has no verb for",
}
# Modules that choose among their own collections at run time (design 5.12).
CHOOSERS = {'affect', 'carried', 'memory_tiers', 'memory_pilot'}
# The shared layer, which names collections it is given: the store package (the checked layer and the adapters),
# Store's own put, audit, commit recovery, ensure and seed, a View's reads (records/view.py: each owner's View names
# its own collection), and the audit's maintenance surface (verify, trace, replay read any collection by its name).
SHARED_MODULES = {'store', 'store.__init__', 'store.words', 'store.catalog', 'store.memory', 'store.mongodb',
                  'store.adapters', 'store.errors', 'records.view'}
SHARED_FUNCTIONS = {('state', 'Store.put'), ('state', 'Store.audit'), ('state', 'Store.recover_commits'),
                    ('state', 'Store.ensure'), ('state', 'Store.seed'),
                    ('audit', 'verify_documents'), ('audit', 'trace_contents'), ('audit', 'replay'),
                    ('audit', 'projection')}
SURFACE_HOMES = ('src/asuna/store/', 'src/asuna/state.py')
UNRESOLVED = object()


def sources():
    out = {}
    for path in repo_files.files(ROOT, 'src/asuna', 'tools'):
        if path.endswith('.py'):
            out[path] = ast.parse((ROOT / path).read_text(encoding='utf-8'), filename=path)
    return out


def module_name(path):
    """'src/asuna/records/scenes.py' -> 'records.scenes'; a tool -> 'tools.<name>'."""
    parts = Path(path).with_suffix('').parts
    if parts[:2] == ('src', 'asuna'):
        return '.'.join(parts[2:])
    return '.'.join(parts)


def dotted(path):
    """The importable name of a module of the core: 'src/asuna/records/scenes.py' -> 'asuna.records.scenes'."""
    name = module_name(path)
    return 'asuna' + ('' if name == '__init__' else '.' + name.removesuffix('.__init__'))


def is_package(path):
    return path.endswith('__init__.py')


def absolute(path, node):
    """The absolute module an ImportFrom names, resolving its dots against the importing module."""
    if not node.level:
        return node.module or ''
    if not path.startswith('src/asuna/'):
        return node.module or ''
    base = dotted(path).split('.')
    if not is_package(path):
        base = base[:-1]
    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
    return '.'.join(base + ([node.module] if node.module else []))


def imported(path, tree):
    """[(line, the absolute module or name imported)] for every import in the file, wherever it is."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = absolute(path, node)
            found.append((node.lineno, module))
            found.extend((node.lineno, module + '.' + alias.name) for alias in node.names)
            found.extend((node.lineno, alias.name) for alias in node.names if alias.name == 'MongoClient')
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and ast.unparse(node.func) in ('importlib.import_module', 'import_module', '__import__')):
            found.append((node.lineno, node.args[0].value))
    return found


def is_driver(name):
    return name == 'MongoClient' or any(name == d or name.startswith(d + '.') for d in DRIVERS)


def is_store(node):
    if isinstance(node, ast.Name):
        return node.id == 'store' or node.id.endswith('_store')
    if isinstance(node, ast.Attribute):
        return node.attr == 'store' or node.attr.endswith('_store')
    return False


class Module:
    """One module's top-level bindings, for resolving a collection's name."""

    def __init__(self, path, tree, modules):
        self.path, self.tree, self.modules = path, tree, modules
        self.name = module_name(path)
        self.constants, self.unresolved, self.imports, self.aliases = {}, set(), {}, {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._bind(target, node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self._bind(node.target, node.value)
            elif isinstance(node, ast.ImportFrom):
                module = absolute(path, node)
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (module, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split('.')[0]
                    self.aliases[local] = alias.name if alias.asname else local

    def _bind(self, target, value):
        if isinstance(target, ast.Name):
            self.constants[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)) \
                and len(target.elts) == len(value.elts):
            for one, its in zip(target.elts, value.elts):
                self._bind(one, its)
        elif isinstance(target, (ast.Tuple, ast.List)):
            self.unresolved.update(t.id for t in target.elts if isinstance(t, ast.Name))

    def module_of(self, local):
        """The module a local name stands for: an `import x` alias, or `from pkg import module`."""
        if local in self.aliases:
            return self.aliases[local]
        if local in self.imports:
            module, name = self.imports[local]
            return module + '.' + name
        return None

    def resolve(self, node, seen=()):
        """The collection name an expression holds, or UNRESOLVED."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.constants and node.id not in seen:
                return self.resolve(self.constants[node.id], seen + (node.id,))
            if node.id in self.imports:
                module, name = self.imports[node.id]
                other = self.modules.get(module)
                if other is not None:
                    return other.resolve(ast.Name(id=name), ())
            return UNRESOLVED
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            other = self.modules.get(self.module_of(node.value.id) or '')
            if other is not None:
                return other.resolve(ast.Name(id=node.attr), ())
        return UNRESOLVED

    def own_constant(self, node):
        """Whether an unresolved name is one of this module's own top-level names."""
        return isinstance(node, ast.Name) and (node.id in self.constants or node.id in self.unresolved)


def functions(tree):
    """{node id of each call: (qualified function name, its parameters)} for every call inside a function."""
    where = {}

    def visit(node, qualname, params):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                name = getattr(child, 'name', '<lambda>')
                args = child.args
                own = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
                own |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
                visit(child, (qualname + '.' if qualname else '') + name, params | own)
            elif isinstance(child, ast.ClassDef):
                visit(child, (qualname + '.' if qualname else '') + child.name, params)
            else:
                if isinstance(child, ast.Call):
                    where[id(child)] = (qualname, params)
                visit(child, qualname, params)
    visit(tree, '', frozenset())
    return where


def findings(trees=None):
    trees = sources() if trees is None else trees
    modules = {}
    for path, tree in trees.items():
        if path.startswith('src/asuna/'):
            modules[dotted(path)] = Module(path, tree, modules)
    found = []

    said = set()

    def fail(path, line, rule, what):
        if (path, line, rule) not in said:            # one finding a line and rule (an import names its module twice)
            said.add((path, line, rule))
            found.append('%s:%d %s: %s' % (path, line, rule, what))

    for path, tree in trees.items():
        # drivers
        allowed = path in ADAPTER_MODULES if path.startswith('src/asuna/') else path in TOOL_CLIENTS
        for line, name in imported(path, tree):
            if is_driver(name) and not allowed:
                fail(path, line, 'drivers', 'imports %s' % name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == 'MongoClient' and not allowed:
                fail(path, node.lineno, 'drivers', 'names MongoClient')
        # store-surface
        home = path.startswith(SURFACE_HOMES)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and is_store(node.value):
                if node.attr in ('db', 'client'):
                    fail(path, node.lineno, 'store-surface', 'reads %s.%s' % (ast.unparse(node.value), node.attr))
                elif node.attr in ('adapter', 'checked') and not home:
                    fail(path, node.lineno, 'store-surface', 'reads %s.%s' % (ast.unparse(node.value), node.attr))
            if isinstance(node, ast.Attribute) and node.attr == 'maintenance' and not (
                    home or path == 'src/asuna/audit.py'):
                fail(path, node.lineno, 'store-surface', 'reads %s.maintenance' % ast.unparse(node.value))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('getattr', 'hasattr')
                    and len(node.args) >= 2 and is_store(node.args[0]) and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in ('db', 'client')):
                fail(path, node.lineno, 'store-surface', '%s(%s, %r)' % (node.func.id, ast.unparse(node.args[0]),
                                                                          node.args[1].value))
        if path == 'src/asuna/state.py':
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == 'Store':
                    for sub in ast.walk(node):
                        named = (sub.name if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) else
                                 sub.attr if isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Store) else
                                 None)
                        if named in ('db', 'client'):
                            fail(path, sub.lineno, 'store-surface', 'Store defines %s' % named)
        # owner and artifact-touches
        module = modules.get(dotted(path)) if path.startswith('src/asuna/') else None
        name = module_name(path)
        calls = functions(tree)
        artifact_saves = artifact_save_names(module, tree, path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr in ('collection', 'put') and is_store(func.value)
                    and node.args):
                qualname, params = calls.get(id(node), ('', frozenset()))
                shared = name in SHARED_MODULES or (name, qualname) in SHARED_FUNCTIONS
                arg = node.args[0]
                value = module.resolve(arg) if module is not None else (
                    arg.value if isinstance(arg, ast.Constant) else UNRESOLVED)
                if value is UNRESOLVED:
                    chooser = name in CHOOSERS or shared
                    kind = ('a parameter' if isinstance(arg, ast.Name) and arg.id in params else
                            'its own constant' if module is not None and module.own_constant(arg) else
                            'a parameter its instance keeps' if kept_parameter(tree, qualname, arg) else None)
                    if not (chooser and kind):
                        fail(path, node.lineno, 'owner', '%s(%s) names a collection that cannot be resolved%s'
                             % (func.attr, ast.unparse(arg), '' if chooser else ' (and the module chooses none)'))
                else:
                    owner = owner_of(value)
                    if owner is None:
                        fail(path, node.lineno, 'owner', '%s(%r): no such declared collection' % (func.attr, value))
                    elif owner != name and not shared:
                        fail(path, node.lineno, 'owner', '%s(%r) belongs to %s' % (func.attr, value, owner))
                    if func.attr == 'put' and value == 'artifacts' and not (
                            name == 'records.artifacts' and qualname == 'save'):    # the owner's own, after its refusal
                        check_touches(node, path, fail)
            elif artifact_saves and ast.unparse(func) in artifact_saves:
                check_touches(node, path, fail)
    return found


def kept_parameter(tree, qualname, node):
    """Whether `self.<name>` in a method is a parameter of its class's `__init__`, kept as is (`self.x = x`)."""
    if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'self'
            and '.' in qualname):
        return False
    owner = qualname.rsplit('.', 1)[0]
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == owner.rsplit('.', 1)[-1]:
            for init in cls.body:
                if isinstance(init, ast.FunctionDef) and init.name == '__init__':
                    params = {a.arg for a in init.args.args}
                    for assign in ast.walk(init):
                        if isinstance(assign, ast.Assign):
                            for target, value in pairs(assign.targets[0], assign.value):
                                if (isinstance(target, ast.Attribute) and target.attr == node.attr
                                        and isinstance(value, ast.Name) and value.id in params):
                                    return True
    return False


def pairs(target, value):
    """The (target, value) pairs of one assignment, tuples unpacked."""
    if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
        return list(zip(target.elts, value.elts))
    return [(target, value)]


def owner_of(collection):
    try:
        return CATALOG.collection(collection).owner
    except Exception:
        return None


def artifact_save_names(module, tree, path):
    """How this file names the stored files' owner's save: `alias.save` for its module, or a `save` imported."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = absolute(path, node)
            for alias in node.names:
                if source == 'asuna.records' and alias.name == 'artifacts':
                    names.add((alias.asname or alias.name) + '.save')
                if source == 'asuna.records.artifacts' and alias.name == 'save':
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'asuna.records.artifacts':
                    names.add((alias.asname or alias.name) + '.save')
    return names


def check_touches(call, path, fail):
    for keyword in call.keywords:
        if keyword.arg == 'reset_counters':
            fail(path, call.lineno, 'artifact-touches', 'passes reset_counters for artifacts')
        elif keyword.arg is None:
            fail(path, call.lineno, 'artifact-touches', 'passes **%s, which could carry reset_counters, for artifacts'
                 % ast.unparse(keyword.value))


def test_the_store_boundary_holds():
    found = findings()
    assert found == [], '\n'.join(found)


def test_the_stored_files_owner_forwards_its_keywords_to_its_refusal_and_its_put():
    """A pass-through cannot hide a `reset_counters`: `records.artifacts.save` takes every keyword, refuses it, and
    passes the rest on to the put."""
    tree = ast.parse((ROOT / 'src/asuna/records/artifacts.py').read_text(encoding='utf-8'))
    [save] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'save']
    assert save.args.kwarg is not None, 'save takes **kwargs'
    kwargs = save.args.kwarg.arg
    body = ast.unparse(save)
    assert "%s.get('reset_counters')" % kwargs in body, 'save looks for reset_counters in its keywords'
    puts = [node for node in ast.walk(save) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'put']
    assert puts and all(any(k.arg is None and ast.unparse(k.value) == kwargs for k in put.keywords) for put in puts), \
        'save passes its keywords on to the put'


def test_the_check_finds_each_rule_broken_once():
    """The check sees what it says it sees, on synthetic files beside the real owner of `scenes`: a relative driver
    import, a store's raw handle read by attribute and by getattr, another owner's collection named through an
    imported constant and through `module.CONST`, a name a non-choosing module cannot resolve, and a reset of a
    stored file's touches."""
    real = 'src/asuna/records/scenes.py'
    trees = {real: ast.parse((ROOT / real).read_text(encoding='utf-8'))}
    trees['src/asuna/records/example.py'] = ast.parse(EXAMPLE)
    found = sorted((line.split()[1].rstrip(':'), int(line.split()[0].rsplit(':', 1)[1])) for line in findings(trees))
    assert found == [('artifact-touches', 10), ('drivers', 1), ('owner', 5), ('owner', 6), ('owner', 7),
                     ('store-surface', 8), ('store-surface', 9)], findings(trees)


EXAMPLE = """from ..store.mongodb import MongoAdapter
from .scenes import COLLECTION
from . import scenes, artifacts as artifact_records
def f(store, name):
    store.collection(COLLECTION)
    store.put(scenes.COLLECTION, {})
    store.collection(name)
    store.db
    getattr(store, 'client', None)
    artifact_records.save(store, {}, reset_counters=True)
"""
