"""The in-memory adapter: the meaning table of the store's words written as code, its reference, and the unit tests'
database.

It is given words the shared layer has validated (words.py) and answers them as every adapter must. Databases live in
this process by name, so `open` twice reaches the same records. Records equal on every sort key (and every record of
a read with no sort) come back shuffled by a generator seeded per adapter (`seed`, chosen at random when not given),
so nothing can depend on an order the meaning table leaves to the database. `Now` reads the injected `clock`.
Unique indexes hold once `ensure` has made them, as on a server. One lock serialises every call.
"""
from __future__ import annotations
import copy
from datetime import datetime, timedelta, timezone
import io
import math
import random
import threading
import uuid
from .adapters import Ensured, Size, Updated
from .catalog import is_number, kind_of
from .errors import BlobMissing, DuplicateKey, RecordInvalid, SchemaConflict
from .words import (AddToSet, And, AnyOf, Contains, Count, Each, Exists, Holds, HoldsAny, Increase, IsNull, Larger,
                    Max, NonEmpty, NoneOf, Not, Now, OnCreate, Or, Push, Range, Set, Smaller, StartsWith, Unset,
                    record_bytes, to_utc_ms)

KIND = 'memory'
SECRETS = ()
PIECE = 1024 * 1024
_DATABASES = {}
_DATABASES_LOCK = threading.Lock()
# Kinds in the order a sort puts them when a field holds several (never after validated writes; kept total so a sort
# cannot fail).
_RANK = {'number': 1, 'text': 2, 'object': 3, 'list': 4, 'bytes': 5, 'bool': 6, 'time': 7}


class Database:
    """One in-memory database: records by collection and id (in write order), the indexes `ensure` made, blobs."""

    def __init__(self, name=None):
        self.name = name
        self.records, self.indexes, self.existing, self.blobs = {}, {}, set(), {}


def open(settings, database):
    """The adapter on the named in-memory database; `settings` may give `seed`."""
    with _DATABASES_LOCK:
        data = _DATABASES.setdefault(database, Database(database))
    return MemoryAdapter(data, seed=settings.get('seed'))


def where(settings):
    return 'memory'


def databases(settings):
    with _DATABASES_LOCK:
        return sorted(_DATABASES)


def drop(settings, database):
    with _DATABASES_LOCK:
        _DATABASES.pop(database, None)


# Values.

def same(a, b) -> bool:
    """Equality as the meaning table defines it: numbers by value, a bool never a number, objects field by field in
    order, lists element by element."""
    kind = kind_of(a)
    if kind != kind_of(b):
        return False
    if kind == 'list':
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if kind == 'object':
        return list(a) == list(b) and all(same(a[key], b[key]) for key in a)
    return a == b


def _key(value):
    """A hashable key that is equal exactly when values are `same` (for unique keys and groups)."""
    kind = kind_of(value)
    if kind == 'list':
        return kind, tuple(_key(x) for x in value)
    if kind == 'object':
        return kind, tuple((k, _key(v)) for k, v in value.items())
    return kind, value


def _order(value):
    """The sort key: missing and null before every value, then values of one kind in their own order."""
    if value is None:
        return (0,)
    kind = kind_of(value)
    if kind in ('list', 'object'):
        return 1, _RANK[kind], repr(_key(value))
    return 1, _RANK.get(kind, 8), value


def _at(doc, path):
    """(present, value) at a dotted path through objects."""
    value = doc
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _fold(text):
    return ''.join(c.casefold() if len(c.casefold()) == 1 else c for c in text)


def _instant(clock, now):
    """The write's one moment, for every `Now` in it."""
    if now is None:
        moment = clock()
        if not isinstance(moment, datetime) or moment.tzinfo is None:
            raise ValueError('the clock gives aware datetimes')
        now = to_utc_ms(moment)
    return now


def _fill(value, now):
    """A written value with each `Now` replaced by the write's moment."""
    if isinstance(value, Now):
        return to_utc_ms(now + timedelta(seconds=value.seconds))
    if isinstance(value, dict):
        return {k: _fill(v, now) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, now) for v in value]
    return copy.deepcopy(value)


# Conditions.

def matches(doc, where, now=None) -> bool:
    """Whether a record meets a validated condition; `now` is the moment a `Now` bound reads."""
    if isinstance(where, And):
        return all(matches(doc, branch, now) for branch in where.wheres)
    if isinstance(where, Or):
        return any(matches(doc, branch, now) for branch in where.wheres)
    return all(_holds(doc, path, test, now) for path, test in where.items())


def _holds(doc, path, test, now):
    present, value = _at(doc, path)
    if isinstance(test, AnyOf):
        return present and any(same(value, v) for v in test.values)
    if isinstance(test, NoneOf):
        return not (present and any(same(value, v) for v in test.values))
    if isinstance(test, Not):
        return not (present and same(value, test.value))
    if isinstance(test, Range):
        if not present or value is None:
            return False
        for bound, limit in test.bounds().items():
            if isinstance(limit, Now):
                limit = _fill(limit, now)
            if kind_of(value) != kind_of(limit):
                return False
            if not {'gt': value > limit, 'gte': value >= limit, 'lt': value < limit, 'lte': value <= limit}[bound]:
                return False
        return True
    if isinstance(test, Exists):
        return present == test.present
    if isinstance(test, IsNull):
        return present and value is None
    if isinstance(test, StartsWith):
        return isinstance(value, str) and value.startswith(test.prefixes)
    if isinstance(test, Contains):
        return isinstance(value, str) and (test.text in value if test.case else _fold(test.text) in _fold(value))
    if isinstance(test, Holds):
        return isinstance(value, list) and any(same(x, test.value) for x in value)
    if isinstance(test, HoldsAny):
        return isinstance(value, list) and any(same(x, v) for x in value for v in test.values)
    if isinstance(test, NonEmpty):
        return isinstance(value, list) and bool(value)
    if isinstance(test, Each):
        return isinstance(value, list) and any(isinstance(x, dict) and matches(x, test.where, now) for x in value)
    return present and same(value, test)


# Changes.

def _put(doc, path, value):
    parts = path.split('.')
    for n, part in enumerate(parts[:-1]):
        child = doc.setdefault(part, {})
        if not isinstance(child, dict):
            raise RecordInvalid('RECORD_PATH_NOT_OBJECT: "%s" 是 %s，不能往里面写 "%s"'
                                % ('.'.join(parts[:n + 1]), kind_of(child), path))
        doc = child
    doc[parts[-1]] = value


def _drop(doc, path):
    parts = path.split('.')
    for part in parts[:-1]:
        doc = doc.get(part) if isinstance(doc, dict) else None
    if isinstance(doc, dict):
        doc.pop(parts[-1], None)


def _listed(doc, path):
    present, value = _at(doc, path)
    if not present:
        return []
    if not isinstance(value, list):
        raise RecordInvalid('RECORD_NOT_A_LIST: "%s" 存的是 %s，不是列表' % (path, kind_of(value)))
    return value


def apply(doc, change, now, creating=False):
    """The record after a validated change (`doc` is changed in place)."""
    for word in change:
        if isinstance(word, (Set, OnCreate)):
            if creating or isinstance(word, Set):
                for path, value in word.values.items():
                    _put(doc, path, _fill(value, now))
        elif isinstance(word, Unset):
            for path in word.paths:
                _drop(doc, path)
        elif isinstance(word, Increase):
            present, value = _at(doc, word.path)
            if present and not is_number(value):
                raise RecordInvalid('RECORD_NOT_A_NUMBER: "%s" 存的是 %s，加不了' % (word.path, kind_of(value)))
            _put(doc, word.path, (value if present else 0) + word.by)
        elif isinstance(word, (Larger, Smaller)):
            present, value = _at(doc, word.path)
            if not present or (value is None and isinstance(word, Larger)):
                _put(doc, word.path, copy.deepcopy(word.value))
            elif value is not None:
                # A declared field holds one kind; an undeclared one is compared in the sort's order of kinds.
                new, old = _order(word.value), _order(value)
                if (new > old) if isinstance(word, Larger) else (new < old):
                    _put(doc, word.path, copy.deepcopy(word.value))
        elif isinstance(word, AddToSet):
            items = list(_listed(doc, word.path))
            for value in word.values:
                if not any(same(value, item) for item in items):
                    items.append(copy.deepcopy(value))
            _put(doc, word.path, items)
        elif isinstance(word, Push):
            items = list(_listed(doc, word.path)) + copy.deepcopy(list(word.values))
            if word.keep_last is not None:
                items = items[len(items) - word.keep_last:] if word.keep_last else []
            _put(doc, word.path, items)
    return doc


def created(where, change, now):
    """The record a create writes: the condition's equalities, then `OnCreate`, then the change."""
    doc = {}
    for path, value in where.items():
        _put(doc, path, copy.deepcopy(value))
    return apply(doc, change, now, creating=True)


# Results.

def _pick(value, parts):
    """(found, the part of value at the path), through lists as a projection does."""
    if not parts:
        return True, copy.deepcopy(value)
    if isinstance(value, dict):
        if parts[0] not in value:
            return False, None
        found, part = _pick(value[parts[0]], parts[1:])
        return found, {parts[0]: part} if found else None
    if isinstance(value, list):
        return True, [_pick(item, parts)[1] or {} for item in value if isinstance(item, dict)]
    return False, None


def _merge(into, part):
    for key, value in part.items():
        if key in into and isinstance(into[key], dict) and isinstance(value, dict):
            _merge(into[key], value)
        elif key in into and isinstance(into[key], list) and isinstance(value, list):
            for mine, theirs in zip(into[key], value):
                _merge(mine, theirs)
        else:
            into[key] = value


def project(doc, fields):
    if fields is None:
        return copy.deepcopy(doc)
    shown = {'_id': doc['_id']}
    for path in fields:
        found, part = _pick(doc, path.split('.'))
        if found:
            _merge(shown, part)
    return shown


class Blobs:
    """Blobs of one in-memory database: bytes with their metadata (scope_key, kind, source_ids)."""

    def __init__(self, data, lock):
        self.data, self.lock = data, lock

    def write(self, stream, meta):
        pieces = []
        while True:
            piece = stream.read(PIECE)
            if not piece:
                break
            pieces.append(bytes(piece))
        content, blob_id = b''.join(pieces), uuid.uuid4().hex
        with self.lock:
            self.data.blobs[blob_id] = (content, copy.deepcopy(dict(meta)))
        return blob_id, len(content)

    def open(self, blob_id):
        with self.lock:
            if blob_id not in self.data.blobs:
                raise BlobMissing(blob_id)
            return io.BytesIO(self.data.blobs[blob_id][0])

    def delete(self, blob_id):
        with self.lock:
            return self.data.blobs.pop(blob_id, None) is not None

    def of_scope(self, scope):
        with self.lock:
            return [key for key, (_, meta) in self.data.blobs.items() if meta.get('scope_key') == scope]


class MemoryAdapter:
    """The adapter over one in-memory database (a new private one when none is given)."""
    capabilities = frozenset({'vectors'})

    def __init__(self, data=None, *, clock=None, seed=None):
        self.data = data if data is not None else Database()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.seed = random.SystemRandom().randrange(2 ** 32) if seed is None else seed
        self.random = random.Random(self.seed)
        self.lock = threading.RLock()
        self.blobs = Blobs(self.data, self.lock)

    # Schema.

    def ensure(self, collection):
        with self.lock:
            name = collection.name
            made = self.data.indexes.setdefault(name, {})
            for index in collection.indexes:
                have = made.get(index.name)
                if have is not None and have != index:
                    raise SchemaConflict(index.name, 'declared %s, the database has %s' % (index, have))
            new = []
            for index in collection.indexes:
                if index.name not in made:
                    keys = [key for key in (_index_key(doc, index) for doc in self._records(name).values())
                            if key is not None]
                    if index.unique and len(keys) != len(set(keys)):
                        raise SchemaConflict(index.name, 'the stored records repeat its key')
                    made[index.name] = index
                    new.append(index.name)
            dropped = tuple(old for old in collection.retired if made.pop(old, None) is not None)
            created_now = name not in self.data.existing
            self.data.existing.add(name)
            self.data.records.setdefault(name, {})
            return Ensured(created_now, tuple(new), dropped)

    def ensure_vectors(self, space, timeout=45):
        return True

    def measure(self, record):
        """A record's size against the store's limit: its canonical JSON."""
        return record_bytes(record)

    # Reads.

    def _records(self, coll):
        return self.data.records.get(coll, {})

    def _matching(self, coll, where, sort=(), now=None):
        """Matching records in the order of `sort`, ties shuffled."""
        found = [doc for doc in self._records(coll).values() if matches(doc, where, now)]
        self.random.shuffle(found)
        for path, direction in reversed(sort):
            found.sort(key=lambda doc: _order(_at(doc, path)[1]), reverse=direction == -1)
        return found

    def get(self, coll, id, fields=None):
        with self.lock:
            doc = self._records(coll).get(id)
            return None if doc is None else project(doc, fields)

    def find(self, coll, where, sort=(), skip=0, limit=None, fields=None):
        with self.lock:
            found = self._matching(coll, where, sort)[skip:]
            if limit is not None:
                found = found[:limit]
            return iter([project(doc, fields) for doc in found])

    def count(self, coll, where, limit=None):
        with self.lock:
            n = sum(1 for doc in self._records(coll).values() if matches(doc, where))
            return n if limit is None else min(n, limit)

    def group(self, coll, where, by, total=Count()):
        with self.lock:
            groups = {}
            for doc in self._records(coll).values():
                # Values only (total None) leave out a record missing a field, as a distinct does; null stays.
                if matches(doc, where) and (total is not None or all(_at(doc, path)[0] for path in by)):
                    values = tuple(_at(doc, path)[1] for path in by)
                    groups.setdefault(tuple(_key(v) for v in values), (values, []))[1].append(doc)
            rows = sorted(groups.values(), key=lambda item: tuple(_order(v) for v in item[0]))
            if total is None:
                return [values[0] if len(by) == 1 else values for values, _ in rows]
            result = []
            for values, docs in rows:
                if isinstance(total, Max):
                    seen = [v for v in (_at(doc, total.field)[1] for doc in docs) if v is not None]
                    amount = max(seen, key=_order) if seen else None
                else:
                    amount = len(docs)
                result.append({**dict(zip(by, copy.deepcopy(values))), 'total': amount})
            return result

    # Writes.

    def _clash(self, coll, doc, skip=None):
        """The unique index the record would repeat, or None."""
        others = [other for key, other in self._records(coll).items() if key != skip]
        for index in self.data.indexes.get(coll, {}).values():
            if index.unique:
                mine = _index_key(doc, index)
                if mine is not None and any(_index_key(other, index) == mine for other in others):
                    return index.name
        return None

    def _write(self, coll, doc, replacing=None):
        if replacing is None and doc['_id'] in self._records(coll):
            return '_id_'
        clash = self._clash(coll, doc, skip=doc['_id'])
        if clash:
            return clash
        self.data.existing.add(coll)
        self.data.records.setdefault(coll, {})[doc['_id']] = doc
        return None

    def insert(self, coll, records, ordered=True):
        with self.lock:
            now, first = _instant(self.clock, None), None
            for at, record in enumerate(records):
                clash = self._write(coll, _fill(record, now))
                if clash and ordered:
                    raise DuplicateKey(coll, clash, at)
                if clash and first is None:
                    first = DuplicateKey(coll, clash, at)
            if first:
                raise first

    def replace(self, coll, record, expected=None, keep=(), create=False):
        with self.lock:
            stored = self._records(coll).get(record['_id'])
            if stored is None:
                if not create:
                    return False
                clash = self._write(coll, copy.deepcopy(record))
                if clash:
                    raise DuplicateKey(coll, clash)
                return True
            if expected is not None and not same(stored.get('revision'), expected):
                return False
            doc = {k: copy.deepcopy(v) for k, v in record.items() if k not in keep}
            doc.update({k: copy.deepcopy(stored[k]) for k in keep if k in stored})
            clash = self._write(coll, doc, replacing=stored)
            if clash:
                raise DuplicateKey(coll, clash)
            return True

    def _change(self, coll, doc, change, now):
        new = apply(copy.deepcopy(doc), change, now)
        if same(new, doc):
            return False
        clash = self._write(coll, new, replacing=doc)
        if clash:
            raise DuplicateKey(coll, clash)
        return True

    def _create(self, coll, where, change, now):
        doc = created(where, change, now)
        if '_id' not in doc:
            raise RecordInvalid('RECORD_ID: 新建的记录没有 _id')
        clash = self._write(coll, doc)
        if clash:
            raise DuplicateKey(coll, clash)
        return doc

    def update(self, coll, where, change, many=False, create=False):
        with self.lock:
            now = _instant(self.clock, None)
            found = self._matching(coll, where, now=now)
            if not many:
                found = found[:1]
            if not found and create:
                self._create(coll, where, change, now)
                return Updated(0, 0, True)
            return Updated(len(found), sum(self._change(coll, doc, change, now) for doc in found), False)

    def claim(self, coll, where, change, sort=(), create=False):
        with self.lock:
            now = _instant(self.clock, None)
            found = self._matching(coll, where, sort, now)
            if found:
                self._change(coll, found[0], change, now)
                return copy.deepcopy(self._records(coll)[found[0]['_id']])
            return copy.deepcopy(self._create(coll, where, change, now)) if create else None

    def delete(self, coll, where, many=False):
        with self.lock:
            found = self._matching(coll, where)
            if not many:
                found = found[:1]
            for doc in found:
                del self.data.records[coll][doc['_id']]
            return len(found)

    # Vectors.

    def nearest(self, space, vector, k, where):
        with self.lock:
            q = math.sqrt(sum(x * x for x in vector))
            scored = []
            for doc in self._records(space.collection).values():
                present, v = _at(doc, space.path)
                if not present or not isinstance(v, list) or len(v) != len(vector) or not matches(doc, where):
                    continue
                n = math.sqrt(sum(x * x for x in v))
                if n:
                    scored.append((doc['_id'], sum(a * b for a, b in zip(vector, v)) / (q * n)))
            return sorted(scored, key=lambda hit: (-hit[1], hit[0]))[:k]

    # Maintenance.

    def size(self, coll):
        with self.lock:
            records = self._records(coll).values()
            return Size(len(records), sum(record_bytes(doc) for doc in records))

    def ping(self):
        return None

    def close(self):
        return None


def _index_key(doc, index):
    """A record's key in a unique index, or None when it is outside the index."""
    key = []
    for path, _ in index.keys:
        present, value = _at(doc, path)
        if (not present or value is None) and path in index.only_where_present:
            return None
        key.append(_key(value))
    return tuple(key)
