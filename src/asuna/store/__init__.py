"""The store: the core's way to its database, with no database named.

`Checked(adapter, catalog)` is the shared layer over one adapter: every call is checked against the catalog
(words.py) before the adapter sees it, records are validated and their times put in UTC at millisecond precision,
and a call that needs a capability the adapter lacks is refused before dispatch (`NotSupported`). An owner reaches a
declared collection through `collection(name)`, a `Handle` whose verbs are the adapter's methods without the
collection name. The adapters are in `adapters.py` (the registry) and `memory.py` (the in-memory one).
"""
from __future__ import annotations
from collections.abc import Mapping
from .catalog import is_number
from .errors import NotSupported, QueryInvalid, RecordInvalid
from .words import (Count, check_change, check_create, check_fields, check_group, check_page, check_record,
                    check_sort, check_vector_where, check_where)


class Handle:
    """One declared collection over the adapter; every argument is checked before the adapter is called."""

    def __init__(self, adapter, collection):
        self.adapter, self.declared, self.name = adapter, collection, collection.name

    def get(self, id, fields=None):
        if not isinstance(id, str) or not id:
            raise QueryInvalid('QUERY_ID: _id 要是不空的文字（给的是 %r）' % (id,))
        return self.adapter.get(self.name, id, check_fields(fields))

    def find(self, where=None, sort=(), skip=0, limit=None, fields=None):
        where, sort = check_where(self.declared, where), check_sort(self.declared, sort)
        skip, limit = check_page(skip, limit)
        fields = check_fields(fields)
        if limit == 0:
            return iter(())
        return self.adapter.find(self.name, where, sort, skip, limit, fields)

    def count(self, where=None, limit=None):
        where = check_where(self.declared, where)
        _, limit = check_page(0, limit)
        return 0 if limit == 0 else self.adapter.count(self.name, where, limit)

    def group(self, where, by, total=Count()):
        where = check_where(self.declared, where)
        by, total = check_group(self.declared, by, total)
        return self.adapter.group(self.name, where, by, total)

    def insert(self, records, ordered=True):
        records = [records] if isinstance(records, Mapping) else list(records)
        if not records:
            return None
        return self.adapter.insert(self.name, [check_record(self.declared, r, now=True) for r in records],
                                   bool(ordered))

    def replace(self, record, expected=None, keep=(), create=False):
        record = check_record(self.declared, record)
        if expected is not None and (not is_number(expected)):
            raise QueryInvalid('QUERY_REVISION: expected 要是一个数（给的是 %r）' % (expected,))
        keep = tuple(keep)
        if not all(isinstance(k, str) and k and '.' not in k and k != '_id' for k in keep):
            raise QueryInvalid('QUERY_KEEP: keep 只列顶层字段名（给的是 %r）' % (keep,))
        return self.adapter.replace(self.name, record, expected, keep, bool(create))

    def update(self, where, change, many=False, create=False):
        where, change = check_where(self.declared, where, now=True), check_change(self.declared, change)
        if create:
            change = check_create(self.declared, where, change)
        return self.adapter.update(self.name, where, change, bool(many), bool(create))

    def claim(self, where, change, sort=(), create=False):
        where, change = check_where(self.declared, where, now=True), check_change(self.declared, change)
        sort = check_sort(self.declared, sort)
        if create:
            change = check_create(self.declared, where, change)
        return self.adapter.claim(self.name, where, change, sort, bool(create))

    def delete(self, where, many=False):
        return self.adapter.delete(self.name, check_where(self.declared, where), bool(many))

    def size(self):
        return self.adapter.size(self.name)


class Blobs:
    """The adapter's blob store, with each blob's metadata checked: `scope_key` and `kind` (text), `source_ids`."""

    def __init__(self, adapter):
        self.adapter = adapter

    def write(self, stream, meta):
        meta = dict(meta)
        if not all(isinstance(meta.get(key), str) and meta[key] for key in ('scope_key', 'kind')):
            raise RecordInvalid('RECORD_BLOB_META: 存字节要写 scope_key 和 kind（给的是 %r）' % (meta,))
        meta['source_ids'] = list(meta.get('source_ids') or ())
        if not all(isinstance(key, str) for key in meta['source_ids']):
            raise RecordInvalid('RECORD_BLOB_META: source_ids 是文字的列表')
        return self.adapter.blobs.write(stream, meta)

    def open(self, blob_id):
        return self.adapter.blobs.open(blob_id)

    def delete(self, blob_id):
        return self.adapter.blobs.delete(blob_id)

    def of_scope(self, scope):
        return self.adapter.blobs.of_scope(scope)


class Checked:
    """The shared layer over one adapter and the catalog its records are declared in."""

    def __init__(self, adapter, catalog):
        self.adapter, self.catalog = adapter, catalog
        self._handles = {}
        self.blobs = Blobs(adapter)

    def collection(self, name) -> Handle:
        if name not in self._handles:
            self._handles[name] = Handle(self.adapter, self.catalog.collection(name))
        return self._handles[name]

    def ensure(self, names=None) -> dict:
        """Create each declared collection and its indexes (all of them when `names` is None), and drop the retired
        ones; {name: Ensured}."""
        chosen = self.catalog.names() if names is None else list(names)
        return {name: self.adapter.ensure(self.catalog.collection(name)) for name in chosen}

    def _vectors(self, space):
        if 'vectors' not in self.adapter.capabilities:
            raise NotSupported('vectors')
        self.catalog.check_space(space)

    def ensure_vectors(self, space, timeout=45) -> bool:
        self._vectors(space)
        return self.adapter.ensure_vectors(space, timeout)

    def nearest(self, space, vector, k, where) -> list:
        """The k records nearest to `vector` among those matching `where`, best first, as (id, cosine); exact."""
        self._vectors(space)
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 100:
            raise QueryInvalid('VECTOR_K: k 要在 1 到 100 之间（给的是 %r）' % (k,))
        vector = list(vector)
        if len(vector) != space.dimensions or not all(is_number(x) for x in vector) or not any(vector):
            raise QueryInvalid('VECTOR_SHAPE: 向量要是 %d 个数、不全是 0' % space.dimensions)
        where = check_vector_where(self.catalog.collection(space.collection), space, where)
        return self.adapter.nearest(space, [float(x) for x in vector], k, where)

    def ping(self):
        return self.adapter.ping()

    def close(self):
        return self.adapter.close()
