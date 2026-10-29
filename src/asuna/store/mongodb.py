"""The MongoDB adapter: the store's words as MongoDB queries, the catalog's collections, validators and indexes, blobs
in the GridFS bucket `artifact_blobs`, and exact vector search.

A validated condition maps onto MongoDB's own operators, whose meaning on validated records is the meaning table's;
`StartsWith` (with `$type: 'string'`) and `Contains` become escaped regular expressions (`i` when case-blind),
`NonEmpty` the list's first element, and `Now` the server's `$$NOW` (in `$expr`, in an update pipeline, and as an
upsert pipeline for an insert that holds it). Times come back aware, in UTC. Index names are MongoDB's defaults; a
unique index's `only_where_present` fields become a `$type` filter of their declared kind, a plain index's an
`$exists` one.
"""
from __future__ import annotations
import re
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from bson import BSON
from bson.codec_options import CodecOptions
from bson.objectid import ObjectId
from bson.regex import Regex
from gridfs import GridFSBucket
from gridfs.errors import NoFile
from pymongo import MongoClient, ReturnDocument, WriteConcern
from pymongo.errors import (BulkWriteError, CollectionInvalid, ConnectionFailure, DuplicateKeyError,
                            OperationFailure, WriteError)
from pymongo.operations import SearchIndexModel
from .adapters import Ensured, Size, Updated
from .catalog import ID
from .errors import BlobMissing, DuplicateKey, RecordInvalid, SchemaConflict, Unavailable
from .words import (AddToSet, And, AnyOf, Contains, Count, Each, Exists, Holds, HoldsAny, HoldsNone, Increase, IsNull,
                    Larger, Max, NonEmpty, NoneOf, Not, Now, OnCreate, Or, Push, Range, Set, Smaller, StartsWith, Unset,
                    Without)

KIND = 'mongodb'
SECRETS = ('mongo_uri',)
BUCKET = 'artifact_blobs'
VALIDATOR = {'$jsonSchema': {'bsonType': 'object', 'required': ['_id', 'schema_version'],
                             'properties': {'schema_version': {'enum': [1]}}}}
BSON_TYPES = {'text': 'string', 'number': 'number', 'bool': 'bool', 'time': 'date'}
# MongoDB's refusals of a change the stored record cannot take.
REFUSED_CHANGES = {14: 'RECORD_NOT_A_NUMBER', 28: 'RECORD_PATH_NOT_OBJECT', 2: 'RECORD_NOT_A_LIST'}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_BOUNDS = {'gt': '$gt', 'gte': '$gte', 'lt': '$lt', 'lte': '$lte'}
# A condition no record meets and an upsert does not copy (an upsert's condition may not use $expr).
_NEVER = {'_never': {'$type': 'minKey'}}


def _client(settings):
    return MongoClient(settings['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, timeoutMS=20000)


def open(settings, database):
    """The adapter on `database`, with a client of its own."""
    return MongoAdapter(_client(settings), database, owns_client=True)


def where(settings):
    """The server's identity, without credentials: its first host and port."""
    parts = urlsplit(settings['mongo_uri'])
    return '%s:%d' % (parts.hostname or '', parts.port or 27017)


def databases(settings):
    client = _client(settings)
    try:
        return client.list_database_names()
    finally:
        client.close()


def drop(settings, database):
    client = _client(settings)
    try:
        client.drop_database(database)
    finally:
        client.close()


# Conditions.

def _now(seconds):
    return '$$NOW' if not seconds else {'$add': ['$$NOW', seconds * 1000]}


def _prefix(prefix):
    return Regex('^' + re.escape(prefix))


def projection(fields):
    """A read's checked `fields` as a MongoDB projection: the paths to return, or those to leave out (`Without`)."""
    if not fields:
        return None
    if isinstance(fields, Without):
        return {path: 0 for path in fields.paths}
    return {path: 1 for path in fields}


def query(where):
    """A validated condition as a MongoDB filter."""
    if isinstance(where, And):
        return {'$and': [query(branch) for branch in where.wheres]} if where.wheres else {}
    if isinstance(where, Or):
        return {'$or': [query(branch) for branch in where.wheres]}
    found, clock = {}, []
    for path, test in where.items():
        key, condition = _condition(path, test, clock)
        found[key] = condition
    if clock:
        found['$expr'] = clock[0] if len(clock) == 1 else {'$and': clock}
    return found


def _condition(path, test, clock):
    if isinstance(test, AnyOf):
        return path, {'$in': list(test.values)}
    if isinstance(test, NoneOf):
        return path, {'$nin': list(test.values)}
    if isinstance(test, Not):
        return path, {'$ne': test.value}
    if isinstance(test, Range):
        condition = {}
        for bound, value in test.bounds().items():
            if isinstance(value, Now):
                condition['$type'] = 'date'
                clock.append({_BOUNDS[bound]: ['$' + path, _now(value.seconds)]})
            else:
                condition[_BOUNDS[bound]] = value
        return path, condition
    if isinstance(test, Exists):
        return path, {'$exists': test.present}
    if isinstance(test, IsNull):
        return path, {'$type': 'null'}
    if isinstance(test, StartsWith):
        # `$type` states what the prefix already implies (text), so a partial index on text (`$type: 'string'`)
        # serves the read as it served the regex written with it.
        if len(test.prefixes) == 1:
            return path, {'$regex': _prefix(test.prefixes[0]), '$type': 'string'}
        return path, {'$in': [_prefix(p) for p in test.prefixes], '$type': 'string'}
    if isinstance(test, Contains):
        return path, {'$regex': re.escape(test.text), **({} if test.case else {'$options': 'i'})}
    if isinstance(test, Holds):
        return path, test.value
    if isinstance(test, HoldsAny):
        return path, {'$in': list(test.values)}
    if isinstance(test, HoldsNone):
        # On a list MongoDB's $ne and $nin compare each element: no element equal, a missing list included.
        return path, {'$ne': test.values[0]} if len(test.values) == 1 else {'$nin': list(test.values)}
    if isinstance(test, NonEmpty):
        return path + '.0', {'$exists': True}
    if isinstance(test, Each):
        return path, {'$elemMatch': query(test.where)}
    return path, test


# Changes.

def _has_now(value):
    if isinstance(value, Now):
        return True
    if isinstance(value, dict):
        return any(_has_now(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_now(v) for v in value)
    return False


def _expression(value):
    """A written value as an aggregation expression: `Now` as `$$NOW`, everything else literal."""
    if isinstance(value, Now):
        return _now(value.seconds)
    if isinstance(value, dict) and _has_now(value):
        return {k: _expression(v) for k, v in value.items()}
    if isinstance(value, list) and _has_now(value):
        return [_expression(v) for v in value]
    return {'$literal': value}


def _measured(value):
    if isinstance(value, Now):
        return _EPOCH
    if isinstance(value, dict):
        return {k: _measured(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_measured(v) for v in value]
    return value


def _clocked(change):
    return any(isinstance(w, (Set, OnCreate)) and _has_now(w.values) for w in change)


def update_of(change):
    """A validated change as MongoDB update operators, or as an update pipeline when it holds `Now` (then it holds
    only `Set` and `Unset`, which the shared layer checks)."""
    if _clocked(change):
        stages = []
        for word in change:
            if isinstance(word, Set):
                stages.append({'$set': {path: _expression(v) for path, v in word.values.items()}})
            elif isinstance(word, Unset):
                stages.append({'$unset': list(word.paths)})
        return stages
    ops = {}
    for word in change:
        if isinstance(word, Set):
            ops.setdefault('$set', {}).update(word.values)
        elif isinstance(word, OnCreate):
            ops.setdefault('$setOnInsert', {}).update(word.values)
        elif isinstance(word, Unset):
            ops.setdefault('$unset', {}).update({path: '' for path in word.paths})
        elif isinstance(word, Increase):
            ops.setdefault('$inc', {})[word.path] = word.by
        elif isinstance(word, (Larger, Smaller)):
            ops.setdefault('$max' if isinstance(word, Larger) else '$min', {})[word.path] = word.value
        elif isinstance(word, AddToSet):
            ops.setdefault('$addToSet', {})[word.path] = {'$each': list(word.values)}
        elif isinstance(word, Push):
            each = {'$each': list(word.values)}
            if word.keep_last is not None:
                each['$slice'] = -word.keep_last if word.keep_last else 0
            ops.setdefault('$push', {})[word.path] = each
    return ops


# Errors.

def _index_of(error):
    found = re.search(r'index: (\S+) dup key', str(getattr(error, 'details', None) or error))
    return found.group(1) if found else None


class _Guard:
    """MongoDB's errors as the store's: a repeated key, a change the record cannot take, a server out of reach."""

    def __init__(self, coll, at=None):
        self.coll, self.at = coll, at

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        if error is None:
            return False
        if isinstance(error, DuplicateKeyError):
            raise DuplicateKey(self.coll, _index_of(error), self.at) from error
        if isinstance(error, BulkWriteError):
            first = (error.details.get('writeErrors') or [{}])[0]
            if first.get('code') == 11000:
                raise DuplicateKey(self.coll, _index_of(first.get('errmsg', '')), first.get('index')) from error
        if isinstance(error, (WriteError, OperationFailure)) and getattr(error, 'code', None) in REFUSED_CHANGES:
            raise RecordInvalid('%s: %s 里这条记录接不住这次改动（MongoDB %s）'
                                % (REFUSED_CHANGES[error.code], self.coll, error.code)) from error
        if isinstance(error, ConnectionFailure):
            raise Unavailable('DATABASE_UNAVAILABLE: 连不上数据库（%s）；不是参数的问题，稍后再试'
                              % type(error).__name__) from error
        return False


class Blobs:
    """Blobs in the GridFS bucket `artifact_blobs`, their metadata (scope_key, kind, source_ids) as GridFS
    metadata; an optional `name` in the metadata is the file's name."""

    def __init__(self, db):
        self.db, self.bucket = db, GridFSBucket(db, bucket_name=BUCKET)

    def write(self, stream, meta):
        meta = dict(meta)
        name = meta.pop('name', '') or ''
        with _Guard(BUCKET):
            blob_id = self.bucket.upload_from_stream(name, stream, metadata=meta)
            return str(blob_id), self.db[BUCKET + '.files'].find_one({'_id': blob_id}, {'length': 1})['length']

    def open(self, blob_id):
        try:
            return self.bucket.open_download_stream(ObjectId(blob_id))
        except (NoFile, TypeError, ValueError) as error:
            raise BlobMissing(blob_id) from error

    def delete(self, blob_id):
        try:
            self.bucket.delete(ObjectId(blob_id))
            return True
        except (NoFile, TypeError, ValueError):
            return False

    def of_scope(self, scope):
        return [str(row['_id']) for row in self.db[BUCKET + '.files'].find({'metadata.scope_key': scope}, {'_id': 1})]


def _possible(where):
    """A vector filter (equality, AnyOf, And, Or) without its branches that match nothing, or None when nothing is
    left: MongoDB's vector filter refuses an empty $in."""
    if isinstance(where, (And, Or)):
        branches = [_possible(branch) for branch in where.wheres]
        if isinstance(where, And):
            return None if any(b is None for b in branches) else And(*branches)
        branches = [b for b in branches if b is not None]
        return Or(*branches) if branches else None
    return None if any(isinstance(t, AnyOf) and not t.values for t in where.values()) else where


class MongoAdapter:
    """The adapter over one database of a client; `owns_client`: closing the adapter closes the client."""
    capabilities = frozenset({'vectors'})

    def __init__(self, client, database, *, owns_client=False, handle=None):
        self.client, self.owns_client, self.name = client, owns_client, database
        self.db = handle if handle is not None else client.get_database(
            database, codec_options=CodecOptions(tz_aware=True), write_concern=WriteConcern(w='majority', j=True))
        self._blobs = None

    @classmethod
    def over(cls, db):
        """The adapter on a database handle already held: through its client (times read aware) when it has one,
        else the handle as it is."""
        client = getattr(db, 'client', None)
        if hasattr(client, 'get_database'):
            return cls(client, db.name)
        return cls(None, getattr(db, 'name', None), handle=db)

    @property
    def blobs(self):
        if self._blobs is None:
            self._blobs = Blobs(self.db)
        return self._blobs

    def measure(self, record):
        """A record's size against the store's limit: its BSON bytes (a `Now` counted as the time it becomes)."""
        return len(BSON.encode(_measured(record)))

    # Schema.

    def _wanted(self, collection, declared):
        options = {}
        if declared.unique:
            options['unique'] = True
        if declared.expire_after is not None:
            options['expireAfterSeconds'] = declared.expire_after
        if declared.only_where_present:
            options['partialFilterExpression'] = {
                path: ({'$type': BSON_TYPES[collection.field(path).kind]} if declared.unique else {'$exists': True})
                for path in declared.only_where_present}
        return [(path, int(direction)) for path, direction in declared.keys], options

    def plan(self, collection):
        """What `ensure` would do, read only: {'create': bool, 'make': [index names], 'drop': [index names],
        'conflicts': [(index name, why)]}."""
        name = collection.name
        with _Guard(name):
            listed = bool(self.db.list_collection_names(filter={'name': name}))
            existing = self.db[name].index_information() if listed else {}
        wanted = {declared.name: self._wanted(collection, declared) for declared in collection.indexes}
        conflicts = []
        for index, (keys, options) in wanted.items():
            if index in existing:
                info = existing[index]
                have = ([(path, int(direction)) for path, direction in info['key']],
                        {k: info[k] for k in ('unique', 'partialFilterExpression', 'expireAfterSeconds')
                         if info.get(k) is not None and info.get(k) is not False})
                if have != (keys, options):
                    conflicts.append((index, 'declared %s %s, the database has %s %s'
                                      % (keys, options, have[0], have[1])))
        return {'create': not listed, 'make': [index for index in wanted if index not in existing],
                'drop': [index for index in collection.retired if index in existing], 'conflicts': conflicts}

    def validator(self, collection):
        """Whether the stored collection has the validator `ensure` creates: 'same', 'other', 'none', 'absent' (no
        collection) or 'not declared' (the collection is not versioned)."""
        if not collection.versioned:
            return 'not declared'
        with _Guard(collection.name):
            listed = list(self.db.list_collections(filter={'name': collection.name}))
        if not listed:
            return 'absent'
        found = (listed[0].get('options') or {}).get('validator')
        return 'none' if found is None else 'same' if found == VALIDATOR else 'other'

    def ensure(self, collection):
        plan, name = self.plan(collection), collection.name
        if plan['conflicts']:
            raise SchemaConflict(*plan['conflicts'][0])
        wanted = {declared.name: self._wanted(collection, declared) for declared in collection.indexes}
        with _Guard(name):
            created = plan['create']
            if created:
                try:
                    self.db.create_collection(name, **({'validator': VALIDATOR} if collection.versioned else {}))
                except CollectionInvalid:
                    created = False
            for index in plan['make']:
                keys, options = wanted[index]
                self.db[name].create_index(keys, name=index, **options)
            for index in plan['drop']:
                self.db[name].drop_index(index)
        return Ensured(created, tuple(plan['make']), tuple(plan['drop']))

    def ensure_vectors(self, space, timeout=45):
        collection = self.db[space.collection]
        definition = {'fields': [{'type': 'vector', 'path': space.path, 'numDimensions': space.dimensions,
                                  'similarity': 'cosine'}, *[{'type': 'filter', 'path': key} for key in space.fields]]}
        with _Guard(space.collection):
            current = list(collection.list_search_indexes(space.name))
            if not current:
                collection.create_search_index(SearchIndexModel(name=space.name, type='vectorSearch',
                                                                definition=definition))
            elif ({f.get('path') for f in (current[0].get('latestDefinition') or {}).get('fields') or []
                   if f.get('type') == 'filter'} != set(space.fields)):
                collection.update_search_index(space.name, definition)
            until = time.monotonic() + timeout
            while True:
                rows = list(collection.list_search_indexes(space.name))
                if rows and rows[0].get('status') == 'READY' and rows[0].get('queryable'):
                    return True
                if time.monotonic() > until:
                    return False
                time.sleep(.5)

    # Reads.

    def get(self, coll, id, fields=None):
        with _Guard(coll):
            return self.db[coll].find_one({ID.path: id}, projection(fields))

    def find(self, coll, where, sort=(), skip=0, limit=None, fields=None):
        cursor = self.db[coll].find(query(where), projection(fields),
                                    sort=list(sort) or None, skip=skip, limit=limit or 0)
        with _Guard(coll):
            yield from cursor

    def count(self, coll, where, limit=None):
        with _Guard(coll):
            return self.db[coll].count_documents(query(where), **({'limit': limit} if limit is not None else {}))

    def group(self, coll, where, by, total=Count()):
        keys = {'k%d' % n: {'$ifNull': ['$' + path, None]} for n, path in enumerate(by)}
        present = {}
        if total is None:
            # Values leave out a record missing a field (null stays), as a distinct does: grouped by presence and
            # dropped after, never an `$exists` in the match: that would offer the planner an index on the field
            # which the caller's filter never asked for (one conversation's authors read through an index on
            # `author` scan every line that has one).
            present = {'p%d' % n: {'$ne': [{'$type': '$' + path}, 'missing']} for n, path in enumerate(by)}
        stage = {'_id': {**keys, **present}}
        if isinstance(total, Max):
            stage['total'] = {'$max': '$' + total.field}
        elif total is not None:
            stage['total'] = {'$sum': 1}
        with _Guard(coll):
            rows = list(self.db[coll].aggregate([{'$match': query(where)}, {'$group': stage},
                                                 {'$sort': {'_id.' + key: 1 for key in keys}}]))
        rows = [row for row in rows if all(row['_id'].get(key) for key in present)]
        values = [tuple(row['_id'].get(key) for key in keys) for row in rows]
        if total is None:
            return [v[0] if len(by) == 1 else v for v in values]
        return [{**dict(zip(by, v)), 'total': row.get('total')} for v, row in zip(values, rows)]

    # Writes.

    def insert(self, coll, records, ordered=True):
        if not any(_has_now(record) for record in records):
            with _Guard(coll):
                self.db[coll].insert_many(records, ordered=ordered)
            return
        first = None
        for at, record in enumerate(records):
            try:
                with _Guard(coll, at):
                    if _has_now(record):
                        # An upsert that never matches inserts once, or meets the same _id: a duplicate, as an insert.
                        self.db[coll].update_one({ID.path: record[ID.path], **_NEVER},
                                                 [{'$set': {k: _expression(v) for k, v in record.items()
                                                            if k != ID.path}}], upsert=True)
                    else:
                        self.db[coll].insert_one(record)
            except DuplicateKey as error:
                if ordered:
                    raise
                first = first or error
        if first:
            raise first

    def replace(self, coll, record, expected=None, keep=(), create=False):
        match = {ID.path: record[ID.path], **({'revision': expected} if expected is not None else {})}
        try:
            with _Guard(coll):
                if keep:
                    fields = {k: {'$literal': v} for k, v in record.items() if k not in keep and k != ID.path}
                    result = self.db[coll].update_one(match, [{'$project': {**fields, **{k: 1 for k in keep}}}],
                                                      upsert=create)
                else:
                    result = self.db[coll].replace_one(match, record, upsert=create)
        except DuplicateKey as error:
            if create and expected is not None and error.index == '_id_':
                return False                 # the record is there, at another revision
            raise
        return result.matched_count == 1 or result.upserted_id is not None

    def update(self, coll, where, change, many=False, create=False):
        with _Guard(coll):
            write = self.db[coll].update_many if many else self.db[coll].update_one
            result = write(query(where), update_of(change), upsert=create)
        return Updated(result.matched_count, result.modified_count, result.upserted_id is not None)

    def claim(self, coll, where, change, sort=(), create=False):
        with _Guard(coll):
            return self.db[coll].find_one_and_update(query(where), update_of(change), sort=list(sort) or None,
                                                     upsert=create, return_document=ReturnDocument.AFTER)

    def delete(self, coll, where, many=False):
        with _Guard(coll):
            write = self.db[coll].delete_many if many else self.db[coll].delete_one
            return write(query(where)).deleted_count

    # Vectors.

    def nearest(self, space, vector, k, where):
        where = _possible(where)
        if where is None:
            return []
        stage = {'index': space.name, 'path': space.path, 'queryVector': list(vector), 'exact': True, 'limit': k}
        found = query(where)
        if found:
            stage['filter'] = found
        with _Guard(space.collection):
            rows = self.db[space.collection].aggregate([
                {'$vectorSearch': stage}, {'$project': {'_id': 1, 'score': {'$meta': 'vectorSearchScore'}}}])
            # MongoDB scores cosine as (1 + cosine) / 2.
            return sorted(((row['_id'], 2 * row['score'] - 1) for row in rows), key=lambda hit: (-hit[1], hit[0]))

    # Maintenance.

    def size(self, coll):
        try:
            with _Guard(coll):
                stats = self.db.command('collStats', coll)
        except OperationFailure as error:
            if 'not found' in str(error).lower():
                return Size(0, 0)
            raise
        return Size(stats.get('count', 0), stats.get('size', 0))

    def ping(self):
        with _Guard('admin'):
            self.client.admin.command('ping')

    def close(self):
        if self.owns_client:
            self.client.close()
