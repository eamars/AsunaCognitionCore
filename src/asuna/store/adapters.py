"""The registry of database adapters, and the results adapters return.

An adapter module (the built-in MongoDB one, a database package's, or the in-memory one) has `KIND`, `SECRETS` (its
setting keys that hold credentials), `open(settings, database)`, `where(settings)` (the server's identity without
credentials), `databases(settings)` and `drop(settings, database)`. `open(settings, database)` opens the kind the
settings name (`database_adapter`), `mongodb` when they name none; the built-in `mongodb` kind is imported here, when it
is first asked for, and this is the one place that names its module. `load(entry)` imports a package's module as the
Host registered it, `register(module)` makes a module's kind known; a kind asked for and not known raises
`AdapterNotInstalled`.
"""
from __future__ import annotations
from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
from .errors import AdapterNotInstalled

SETTING = 'database_adapter'
TIMEOUT = 'database_timeout_ms'       # an operation's time limit, for a caller that needs its own (the host lease)
DEFAULT = 'mongodb'
BUILT_IN = {'mongodb': 'asuna.store.mongodb'}
TEST_PREFIX = 'asuna_v2_test_'
_LOADED = {}


@dataclass(frozen=True)
class Ensured:
    """What `ensure` did: whether it created the collection, the index names it made and those it dropped."""
    created: bool
    indexes_made: tuple
    dropped: tuple


@dataclass(frozen=True)
class Updated:
    """What `update` did: records matched, records changed, whether it created one."""
    matched: int
    changed: int
    created: bool


@dataclass(frozen=True)
class Size:
    """A collection's records and the bytes they take."""
    records: int
    bytes: int


def register(module):
    """Make an adapter module's kind available to `open`."""
    _LOADED[module.KIND] = module
    return module


def load(entry):
    """Import a database package's adapter module: {'kind': ..., 'python': <directory>, 'module': <name>}."""
    directory = str(Path(entry['python']).resolve())
    if directory not in sys.path:
        sys.path.insert(0, directory)
    module = importlib.import_module(entry['module'])
    if getattr(module, 'KIND', None) != entry['kind']:
        raise ValueError('DATABASE_ADAPTER_KIND: %s 的 KIND 是 %r，登记的是 %r'
                         % (entry['module'], getattr(module, 'KIND', None), entry['kind']))
    return register(module)


def loaded() -> list[str]:
    return list(_LOADED)


def module(settings):
    """The adapter module the settings select (`mongodb` when they name none)."""
    kind = settings.get(SETTING) or DEFAULT
    if kind not in _LOADED and kind in BUILT_IN:
        register(importlib.import_module(BUILT_IN[kind]))
    if kind not in _LOADED:
        raise AdapterNotInstalled('DATABASE_ADAPTER_NOT_INSTALLED: %s' % kind)
    return _LOADED[kind]


def open(settings, database):
    """An open adapter of the selected kind on `database`."""
    return module(settings).open(settings, database)


def over(db):
    """The built-in MongoDB adapter over a database handle already held (a store's own, while it holds one)."""
    return module({}).MongoAdapter.over(db)


def drop(settings, database):
    """Drop a test database; any name outside `asuna_v2_test_*` is refused."""
    if not str(database).startswith(TEST_PREFIX):
        raise ValueError('DATABASE_NOT_A_TEST: 只删 %s* 的测试库（给的是 %s）' % (TEST_PREFIX, database))
    module(settings).drop(settings, database)
