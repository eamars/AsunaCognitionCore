"""The catalog: every collection the core keeps, declared once, and the vector spaces searched in them.

A collection declares its fields (path, kind, nullable, required), its indexes, the index names `ensure` drops
(`retired`), its owner module and its flags. Only declared fields can be named in a condition, sort, group or index;
other fields are stored and returned unchanged. A dotted path is a field inside a declared `object`, or inside the
objects of a declared `list` of `object` (queried only through `Each`). A nested required field is required wherever
its parent is present. `CATALOG` holds the core's collections; each is declared when its owner moves onto the store.
"""
from __future__ import annotations
from dataclasses import dataclass, field as _field
from datetime import datetime
from .errors import QueryInvalid

KINDS = ('text', 'number', 'bool', 'time', 'list', 'object', 'vector')
ELEMENTS = ('text', 'number', 'bool', 'time', 'object')
# Words of the JSON form of a condition (words.from_json): no field may be named one of them.
RESERVED = ('or', 'and')


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def kind_of(value) -> str:
    """The kind a value is: null, bool, number, text, time, list, object, bytes or other."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if is_number(value):
        return 'number'
    if isinstance(value, str):
        return 'text'
    if isinstance(value, datetime):
        return 'time'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, bytes):
        return 'bytes'
    return 'other'


def _invalid(why):
    return ValueError('CATALOG_INVALID: ' + why)


@dataclass(frozen=True)
class Field:
    """A declared field: `of` is a list's element kind, `dimensions` a vector's length."""
    path: str
    kind: str
    of: str | None = None
    dimensions: int | None = None
    nullable: bool = False
    required: bool = False

    def holds(self, value) -> bool:
        """Whether a value other than null is of this field's kind."""
        if self.kind == 'vector':
            return (isinstance(value, list) and len(value) == self.dimensions
                    and all(is_number(x) for x in value))
        if self.kind == 'list':
            return isinstance(value, list) and all(self.holds_element(x) for x in value)
        return kind_of(value) == self.kind

    def holds_element(self, value) -> bool:
        return kind_of(value) == self.of


ID = Field('_id', 'text', required=True)


@dataclass(frozen=True)
class Index:
    """An index: `keys` are (path, 1 | -1); a unique index's fields are required unless listed in
    `only_where_present`, and a record missing one of those (or holding null) is outside the index."""
    name: str
    keys: tuple
    unique: bool = False
    only_where_present: tuple = ()


@dataclass(frozen=True)
class Space:
    """Vectors searched by cosine similarity: each record of `collection` holds its vector in `path`, and a search
    may filter on `fields`. A change of dimensions or fields is a new space."""
    name: str
    collection: str
    path: str
    dimensions: int
    fields: tuple


@dataclass(frozen=True)
class Collection:
    """A declared collection. Flags: `versioned` (every record carries `schema_version`), `insert_only` (a ledger),
    `counters` (fields a revisioned write keeps at their stored values), `derived` (fields computed from the record's
    own content, left out of its audit)."""
    name: str
    owner: str
    fields: tuple = ()
    indexes: tuple = ()
    retired: tuple = ()
    versioned: bool = False
    insert_only: bool = False
    counters: tuple = ()
    derived: tuple = ()
    _paths: dict = _field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        paths = {'_id': ID}
        for declared in self.fields:
            path = declared.path
            if path in paths:
                raise _invalid('%s declares %s twice' % (self.name, path))
            parts = path.split('.')
            if not all(parts) or any(p.startswith('$') or p in RESERVED for p in parts):
                raise _invalid('%s: %r is not a field name' % (self.name, path))
            if declared.kind not in KINDS:
                raise _invalid('%s.%s: kind %r' % (self.name, path, declared.kind))
            if (declared.kind == 'list') != (declared.of in ELEMENTS):
                raise _invalid('%s.%s: a list names its element kind, and only a list' % (self.name, path))
            if (declared.kind == 'vector') != isinstance(declared.dimensions, int):
                raise _invalid('%s.%s: a vector names its dimensions, and only a vector' % (self.name, path))
            if declared.required and declared.nullable:
                raise _invalid('%s.%s: a required field is never null' % (self.name, path))
            if len(parts) > 1:
                parent = paths.get('.'.join(parts[:-1]))
                if parent is None or not (parent.kind == 'object' or parent.of == 'object'):
                    raise _invalid('%s.%s: declare its parent first, as an object or a list of objects'
                                   % (self.name, path))
            paths[path] = declared
        names = set()
        for index in self.indexes:
            if index.name in names or index.name in self.retired:
                raise _invalid('%s: index %s declared twice or also retired' % (self.name, index.name))
            names.add(index.name)
            for path, direction in index.keys:
                if path not in paths or direction not in (1, -1):
                    raise _invalid('%s: index %s names %r' % (self.name, index.name, path))
                if index.unique:
                    if paths[path].kind in ('list', 'object', 'vector'):
                        raise _invalid('%s: unique index %s on %s' % (self.name, index.name, path))
                    if not paths[path].required and path not in index.only_where_present:
                        raise _invalid('%s: unique index %s: %s is neither required nor only_where_present'
                                       % (self.name, index.name, path))
            if not set(index.only_where_present) <= {path for path, _ in index.keys}:
                raise _invalid('%s: index %s: only_where_present names a field it does not index'
                               % (self.name, index.name))
        object.__setattr__(self, '_paths', paths)

    def field(self, path) -> Field | None:
        return self._paths.get(path)

    def paths(self) -> list[str]:
        return list(self._paths)

    def unique(self) -> list[Index]:
        return [index for index in self.indexes if index.unique]


class Catalog:
    """The declared collections and vector spaces, by name."""

    def __init__(self, collections=(), spaces=()):
        self._collections, self._spaces = {}, {}
        for declared in collections:
            if declared.name in self._collections:
                raise _invalid('collection %s declared twice' % declared.name)
            self._collections[declared.name] = declared
        for space in spaces:
            self.check_space(space)
            if space.name in self._spaces:
                raise _invalid('space %s declared twice' % space.name)
            self._spaces[space.name] = space

    def collection(self, name) -> Collection:
        declared = self._collections.get(name)
        if declared is None:
            raise QueryInvalid('QUERY_COLLECTION_NOT_DECLARED: 没有声明叫 "%s" 的集合；声明了的：%s'
                               % (name, '、'.join(self._collections) or '（没有）'))
        return declared

    def collections(self) -> list[Collection]:
        return list(self._collections.values())

    def names(self) -> list[str]:
        return list(self._collections)

    def spaces(self) -> list[Space]:
        return list(self._spaces.values())

    def check_space(self, space):
        """Refuse a space whose collection, vector path or filter fields are not declared."""
        declared = self._collections.get(space.collection)
        vector = declared and declared.field(space.path)
        if not vector or vector.kind != 'vector' or vector.dimensions != space.dimensions:
            raise _invalid('space %s: %s.%s is not a declared vector of %s dimensions'
                           % (space.name, space.collection, space.path, space.dimensions))
        for path in space.fields:
            if declared.field(path) is None or declared.field(path).kind in ('list', 'object', 'vector'):
                raise _invalid('space %s filters on %s, not a declared value field' % (space.name, path))


CATALOG = Catalog()
