# ADR-104 step 2 and after: the database interface, designed to the end

Design subagent, 2026-10-28 (NZDT), from the survey in [research.md](research.md), reviewed by Claude (the lead) against
[review-list.md](review-list.md) and revised once. Read at main `5a62ebd6a171`. The scripts are in [design/](design/);
what they write and the probe's evidence stay in `<data>/private/adr104-research/` (not tracked):

| file | what it is |
|---|---|
| `design/call_site_map.py` | the census script (AST over every tracked `.py` in `src/asuna`, `tools`, `integration`) |
| `design/owner_ops.py` | owners, their named operations (section 4 in data) and the rules that assign each call |
| `design/hand.py` | the call sites assigned by hand (125 entries covering 127 rows), each with what the code asks |
| `call-site-map.tsv` (private, written by `call_site_map.py`) | its output: 1,607 rows (file, line, function, collection, method, condition shape, change, sort/limit, owner operation, how assigned) |
| `design/fields-per-collection.txt` | the fields each collection's conditions and sorts name today (from the map) |
| `probe_mongo_semantics.py`, `probe-mongo-facts.json` (private, 10,015 and 2,508 bytes) | a probe of MongoDB behaviour on a throwaway database (dropped), and its facts |
| `design/test_census.py` | static count of the unit tests and of those that need a database |

Numbers below say where they were read. "Map" means `call-site-map.tsv` as `call_site_map.py` wrote it at
`5a62ebd6`; "probe" means `probe-mongo-facts.json` (MongoDB 8.2.6, a replica set, run 2026-10-28 on database
`asuna_v2_test_adr104probe_*`, a few hundred synthetic records, dropped).

---

## 1. How it works, in plain words

**What the core asks of a database.** The core keeps everything she is and does as records: lines of
conversation, turns, tasks, memories, files' descriptions, the audit trail. It needs a database to do a small number
of plain things with them: keep a record, give it back by its id, find records whose fields match a description,
count them, change some fields, delete them, take "the next one" so that two workers never take the same one, give
the next number of a counter, and find the memories closest in meaning to a question. It also keeps large files
(pictures, documents) and gives them back as a stream. That is the whole list: nineteen operations, written down
once with their exact meaning.

**How the core is organised around it.** There are three layers.

1. **The rest of the core** asks for things by name, in its own words: "the lines said in this conversation since
   position 40", "the next position of this conversation", "the tasks waiting for feedback". It never describes a
   query itself and never names where records are kept.
2. **One owner per kind of record.** Each kind of record (lines, conversations, tasks, ...) has exactly one module
   that owns it. Only that module knows the record's fields and builds the descriptions ("scene_id is this, direction
   is inbound, position after 40"). There are 31 owners for 43 kinds of record and the store of large files.
3. **The adapter**, the only part written per database. It turns a description into that database's own query. The
   descriptions use a small set of words defined by the core (equals, any of, a range, starts with, contains, ...),
   each with one meaning written in a table, so the same description gives the same records on any database.

**How another user connects a different database.** They install an adapter package for it (the way a channel
package such as QQ is installed) and name it in the settings. The package implements the nineteen operations and
passes one shared test suite, the same one MongoDB passes. Nothing else in the core changes: no owner, no call site.
If the package is missing, the Host refuses to start and says which one is missing; it never runs half-working.
Today's package is MongoDB, and her running system keeps its MongoDB, its database and every record as they are.

**Why this shape.** The owner's concern with the earlier proposal was that every call site would build query
conditions and that the vocabulary was MongoDB's. Here the conditions live in 31 owner modules only, so a call site
reads as what it means, and a check can prove that nobody else builds one. The vocabulary is the core's own, so a
second database reads the same table. The adapter stays small (nineteen operations), so a second database costs
days, not months. Everything a second database cannot do faithfully is refused out loud, never imitated.

**Tests.** Unit tests run on an in-memory database that is the written meaning itself (during the move, on a
temporary in-process stand-in, removed at its end); they can never reach a real server (the test setup takes the address away and refuses to make a connection). Only the adapter's own integration
tests reach a real server, on a throwaway database of made-up records that is deleted at the end.

**How long the move is.** Fifteen batches that change the running system, one at a time, each with its own review,
installed in eleven restarts (four pairs share one; 8.2); besides them, three steps that touch only the tests or add
code nothing runs yet need no restart.

---

## 2. The adapter interface

### 2.1 Where it sits

```
src/asuna/store/                 the shared layer (core, no database named)
    words.py      the condition and change words, their JSON form (her read tool), validation against the catalog
    catalog.py    every collection: fields (path, kind, nullable, required), indexes, vector spaces, owner, flags
    errors.py     the errors below
    memory.py     the in-memory adapter: the reference of the meaning table, and the unit tests' double
    adapters.py   the registry: load(entry) imports a package's adapter module; open() fails loudly
    __init__.py   Checked and Handle: the shared layer's checks over one adapter; Store: the core's facade (put,
                  audit, collection handles for owners, nearest, blobs, maintenance), built on them
src/asuna/records/<name>.py      the 12 leaf owner modules (section 4)
packages/databases/mongodb/      the MongoDB adapter package (after batch B14; until then src/asuna/store/mongodb.py)
```

An owner reaches its collections through `store.collection(name)`, which returns a `Handle` bound to the declared
collection; the handle's verbs are the adapter methods below without the collection name, called after the shared
layer (`Checked`, which `Store` takes over) has validated the words against the catalog. `Store` derives its adapter
from the database it holds (`store.db`), when first used, so a store built over another handle (a test's own
in-process database) writes through that handle.
A repository test (B13) fails when `store.collection('<name>')`, `store.put('<name>', ...)` or any adapter call
appears outside the owner of `<name>` named in the catalog.

### 2.2 Methods

Nineteen methods: fifteen on the adapter, four on its blob store. Each names the core need it serves. "where" and
"change" are trees of section 3's words, already validated; "coll" is a declared collection name; records are
dicts whose `_id` is text.

| # | method | serves (map rows) | result, errors | MongoDB | SQLite | PostgreSQL |
|---|---|---|---|---|---|---|
| 1 | `ensure(collection)` | `Store.migrate` (9 rows) | `Ensured(created, indexes_made, dropped)`; `SchemaConflict(name, why)` when an index of the same name differs | `create_collection` with today's `$jsonSchema` validator for versioned collections; `create_index` by declared name; `drop_index` for `retired` names | `CREATE TABLE IF NOT EXISTS c(id TEXT PRIMARY KEY, doc TEXT NOT NULL)`; one expression index per declared index on `json_extract(doc,'$.f')`, partial `WHERE json_type(...)=...` | same with a `jsonb` column; expression indexes `((doc->>'f') COLLATE "C")` |
| 2 | `ensure_vectors(space, timeout)` | step 1a, as built | `True` once queryable | the search index, as built in 1a | a `vec0` table keyed by id with the space's filter fields as metadata columns (at most 16), written in the record's transaction | a `vector(n)` column of the row; exact search needs no index |
| 3 | `get(coll, id, fields=None)` | 481 `find_one` by `_id` alone (60 more fence an `_id` with other fields and use `find`) | record or `None` | `find_one({'_id': id}, projection)` | `SELECT doc FROM c WHERE id=?` | same |
| 4 | `find(coll, where, sort=(), skip=0, limit=None, fields=None)` | every other read: 296 `find`, 193 `find_one` (a `find` with `limit=1`) | iterator of records, in the sort order of section 3.3 | the where tree as a filter dict; sort as given plus the tie rule (3.3); projection | compiled `WHERE` (3.5); `ORDER BY` with missing first; `LIMIT/OFFSET` | compiled `WHERE`; `ORDER BY ... NULLS FIRST`, `COLLATE "C"`; `LIMIT/OFFSET` |
| 5 | `count(coll, where, limit=None)` | 42 `count_documents` | int (at most `limit`) | `count_documents(filter, limit=)` | `SELECT count(*) FROM (SELECT 1 ... LIMIT ?)` | same |
| 6 | `group(coll, where, by, total=Count())` | 16 `distinct`, audit heads, her `aggregate` | list of `{by fields..., 'total': n}` ordered by the `by` values; `total=None` gives the values only (distinct) | `aggregate([$match, $group, $sort])`; `$sum: 1` or `$max` | `SELECT by, count(*)/max(..) ... GROUP BY ... ORDER BY` | same |
| 7 | `insert(coll, records, ordered=True)` | 9 `insert_one`, 2 `insert_many`, `Store.put` new | `None`; `DuplicateKey(coll, index, at)`; records before `at` stay written | `insert_many(ordered=True)`; E11000 to `DuplicateKey` | one `INSERT` each; `UNIQUE constraint failed` to `DuplicateKey` | one `INSERT` each; SQLSTATE 23505 to `DuplicateKey` |
| 8 | `replace(coll, record, expected=None, keep=(), create=False)` | `Store.put` at a revision (counter fields kept), 11 `replace_one` | `True` written; `False` when no record has that id (and `revision` = `expected`); `DuplicateKey` | `replace_one({_id, revision})`, or with `keep` the update pipeline `$project` of `$literal` values (today's `put`) | `UPDATE c SET doc=json_patch(?, json_object(<kept fields from doc>)) WHERE id=? AND json_extract(doc,'$.revision')=?`; `create` as `INSERT ... ON CONFLICT(id) DO UPDATE` | same with `jsonb` `||` and `jsonb_build_object` |
| 9 | `update(coll, where, change, many=False, create=False)` | 81 `update_one`, 8 `update_many`, 2 `bulk_write` (as a loop) | `Updated(matched, changed, created)`; `DuplicateKey`; `RecordInvalid` | `update_one/many` with `$set $unset $inc $max $min $addToSet:$each $push:$each,$slice $setOnInsert`, `upsert` | one `UPDATE ... SET doc=<json_set/json_remove chain>`; create as `INSERT ... ON CONFLICT DO UPDATE` | `jsonb_set` chain; `INSERT ... ON CONFLICT` |
| 10 | `claim(coll, where, change, sort=(), create=False)` | 5 `find_one_and_update`: the counter and claim-next | the record after the change, or `None` | `find_one_and_update(sort, return_document=AFTER)` (probe: 6 claimers, 60 items, 60 distinct) | `BEGIN IMMEDIATE; UPDATE ... WHERE id=(SELECT id ... ORDER BY ... LIMIT 1) RETURNING doc; COMMIT` | `UPDATE ... WHERE id=(SELECT id ... ORDER BY ... LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING doc` |
| 11 | `delete(coll, where, many=False)` | 12 `delete_one`, 17 `delete_many` | int deleted | `delete_one/many` | `DELETE FROM c WHERE id IN (SELECT id ... [LIMIT 1])` | same |
| 12 | `nearest(space, vector, k, where)` | step 1b, as built | `[(id, cosine)]`, best first, ties by id | `$vectorSearch` with `exact: true`, as built | `vec0` KNN per any-of combination (it has no `IN`), merged exactly | `ORDER BY v <=> ?, id LIMIT k` on a plain scan |
| 13 | `size(coll)` | audit retention cap (`collStats`, 3 calls) | `Size(records, bytes)`: bytes of stored records | `collStats` `count`, `size` | `SELECT count(*), sum(length(doc))` | `count(*)`, `sum(pg_column_size(doc))` |
| 14 | `ping()` | `validate_settings` | `None`; `Unavailable` | `ping` command | `SELECT 1` | `SELECT 1` |
| 15 | `close()` | every `client.close()` | `None` | `client.close()` | close the connection | close the pool |
| 16 | `blobs.write(stream, meta)` | `BlobStore.put*` | `(blob_id, size)`; meta = scope, kind, sources | GridFS `upload_from_stream` (bucket `artifact_blobs`, metadata as today) | a file under the database's folder plus a `_blobs` row, file written and synced before the row | a large object, or a chunk table, plus a row |
| 17 | `blobs.open(blob_id)` | reads, `get_range`, the existence check | a readable, seekable binary stream; `BlobMissing` | `open_download_stream(ObjectId)`; `NoFile` to `BlobMissing` | open the file | `lo_open` or a chunk reader |
| 18 | `blobs.delete(blob_id)` | sweep, failed upload, erasure | `True` deleted, `False` already gone | `bucket.delete`; `NoFile` to `False` | unlink and delete the row | `lo_unlink` and the row |
| 19 | `blobs.of_scope(scope)` | erasure by scope (ADR-105) | list of blob ids | `files.find({'metadata.scope_key': scope})` | `SELECT id FROM _blobs WHERE scope=?` | same |

The package module itself (not counted as methods): `open(settings, database) -> Adapter`; `where(settings) -> str`
(the server's identity without credentials, for the one-Host file lock that `config.database_lock` builds from the
URI today); `databases(settings)` and `drop(settings, database)` (the test harness and
`tools/cleanup_test_databases.py`; the core refuses any name that is not `asuna_v2_test_*`); `SECRETS` (its setting
keys that hold credentials, which the core's redaction and settings page use instead of naming `mongo_uri`); and on
the adapter, `capabilities`.

**Capabilities.** One: `vectors` (methods 2 and 12). An adapter without it raises `NotSupported('vectors')` before
anything reaches the database; retrieval already treats a failed vector search as "lexical recall only" unless the
caller requires vectors (`retrieval.py:237-239`), and the memory indexer does not run. Everything else is required.

**Errors** (`asuna.store.errors`), each with what raises it: `DuplicateKey` (insert, replace, update, claim with create:
a unique key repeated; names the index and, for insert, the position); `StaleRevision` (the shared layer's `put` when
`replace` returned `False` for a record that exists; mapped to today's `Conflict('STALE_REVISION: ...')` and its audit
row); `QueryInvalid` (the shared layer, before dispatch: an undeclared field, a form section 3 refuses, a kind mismatch
in a condition, a naive datetime in a condition, `QUERY_NAIVE_TIME`); `RecordInvalid` (the shared layer on write: a
declared field of the wrong kind, a missing required field, a naive datetime written; the adapter for a change the
record cannot take, as MongoDB codes 28 and 14 in the probe); `RecordTooLarge` (the shared layer: over 1 MiB, today's
`DOCUMENT_TOO_LARGE_USE_ARTIFACT`); `NotSupported` (before dispatch: a capability the adapter lacks); `SchemaConflict`
(ensure); `Unavailable` (the adapter, for a database out of reach; `channels.whole_host_state` maps it to
`HOST_DATABASE_UNAVAILABLE` instead of naming pymongo's `AutoReconnect`); `BlobMissing` (blobs); `AdapterNotInstalled`
(the registry; section 5.15).

### 2.3 What is not in it, and why

No transactions (section 5.14); no change streams (none used); no joins (the one `$lookup` becomes reads, 5.7); no
full-text search (lexical recall is Python, ADR page); no TTL index (the one TTL, `lane_faults`, becomes a delete on
write, 5.6); no raw handle or escape hatch (`store.db`, `dbread._default().db` go); no regular expressions
(decided in the lead's review, 2026-10-28: the core's 12 uses and her 5, `usage_readout.py` lines 734, 735, 791, 821
and `budget_per_place.py` line 55, are all literal prefixes or substrings, which `StartsWith` and `Contains` cover; a
regex subset would be a grammar, a validator and a translation per adapter with no caller; a caller that needs one
adds it with its conformance cases); no database clock outside writes (the lease is the
only user, through `Now`); no bulk write (the two `bulk_write` calls are up to 200 upserts of an adapter post and
become a loop, 5.6); no `list_collection_names` (the catalog is the list).

Expansion: a new collection is a catalog entry and an owner; a new question on an existing collection is a new view
in its owner; neither touches an adapter. A new database is a package implementing 2.2 that passes the contract
suite (section 7.1); nothing else in the core changes.

### 2.4 How this changes decisions 5 and 6

Decision 5 named "get, find, count, update and delete by fields ... named operations only for counters and the few
aggregates". This design keeps its words and adds, per the lead's decisions of 2026-10-28: the owner layer (call
sites call owners' operations, never the words), declared fields, the primitives claim, revisioned replace and `Now`,
and the blob interface. Decision 6 is kept as it stands (her tool speaks the same words, as JSON; `aggregate`
becomes `group`). On the ADR page this is written as a new decision 7, dated 2026-10-28, with its reason (the owner's
concern that call sites would build conditions and that the vocabulary was MongoDB's); 5 and 6 are not rewritten.

---

## 3. The meaning table

The in-memory adapter implements exactly this table and is the reference; MongoDB is tested against it. Each rule
names the conformance case that pins it (section 7.1 lists the classes). "Probe" marks a MongoDB behaviour verified
today.

### 3.1 Records, fields, kinds

- A record is a dict with a text `_id`. Fields not declared in the catalog are stored and returned unchanged but
  cannot be named in a condition, sort, group or index (`QueryInvalid`). `V01`, `V02`.
- A collection whose owner has not moved yet is `pending`: it declares only the fields the store itself names
  (`_last_op`, the audit fields, a vector space's fields, the `only_where_present` fields of its unique indexes), and
  its indexes may name fields not declared yet. The batch that moves its owner declares its fields after its 8.3
  step 5 and ends `pending`; from B13 a guard fails while any collection is `pending`.
- A declared field has a path (dotted for nested objects), a kind and two flags. Kinds: `text`, `number` (int or
  float, compared by value; `1 == 1.0`, probe `eq_1_matches`), `bool` (not a number: `{'g': 1}` does not match
  `True`, probe), `time` (an aware UTC datetime), `list` of one of these or of `object`, `object` (only its declared
  sub-paths are queried), `vector(n)`. `nullable`: null is a value it may hold. `required`: every write has it,
  not null. `V03`-`V06`.
- Writes are validated once, in the shared layer, against the declared fields: a value of another kind, null in a
  non-nullable field, a missing required field: `RecordInvalid`. So no stored record mixes kinds in a declared field,
  and MongoDB's own cross-type ordering never applies. `V07`.
- Time: aware datetimes only (naive refused: `RecordInvalid` in a write, `QueryInvalid` in a condition); stored at
  millisecond precision, truncated by the
  shared layer before the write, so they round-trip equal on every adapter (probe: MongoDB keeps 456 ms of 456789
  µs and returns naive datetimes unless `tz_aware`; the MongoDB adapter opens with `tz_aware=True`). Times the core
  writes as ISO text today (`state.now()`) stay text, compared as text. `T01`-`T03`.
- Size: a record is at most 1,048,576 bytes, checked by the shared layer before the write with the adapter's own
  measure (`measure(record)`) and refused as today, `RecordTooLarge('DOCUMENT_TOO_LARGE_USE_ARTIFACT')`. The MongoDB
  adapter measures BSON bytes, exactly as `state.py:_size` did; the in-memory adapter measures canonical JSON (UTF-8).
  All adapters move to canonical JSON as a change of its own, once a count on her data shows no record on different
  sides of 1 MiB under the two measures. Each adapter states its own hard ceiling, which must be at least that
  (MongoDB 16 MiB). `V08`.

### 3.2 Condition words

A `where` is a mapping `{field: value or word}` (every entry holds) or `And(w, ...)` / `Or(w, ...)`. A plain value
means equality. Nesting depth at most 8. Two-valued logic throughout: a condition on a missing field is false, and
the complements (`Not`, `NoneOf`) are true there.

| word | meaning | refused (`QueryInvalid`) | case |
|---|---|---|---|
| `value` (equality) | the field is present and equals the value (number by value, text by code points exactly, time to the ms) | `None` as the value (MongoDB's `{f: null}` matches null and missing, probe `eq_null_matches`: use `IsNull` or `Exists(False)`); a `list` or `object` field (MongoDB matches an element, probe `eq_on_list_matches_element`: use `Holds`); a value of another kind | `W01`-`W05` |
| `AnyOf(values)` | equals one of them; `AnyOf([])` matches nothing | `None` among the values (MongoDB `$in: [null]` matches missing, probe) | `W06`, `W07` |
| `NoneOf(values)` | missing, null, or equal to none (MongoDB `$nin`, probe `nin_matches`); `NoneOf([])` matches every record | `None` among the values | `W08`, `W09` |
| `Not(value)` | the complement of equality: missing and null match (MongoDB `$ne`, probe `ne_matches`) | as equality | `W10` |
| `Range(gt=, gte=, lt=, lte=)` | present, of the field's kind, within every bound; missing and null never match; text by code point (probe `string_order_is_codepoint`: `'Z' < 'a' < 'é' < '中' < U+FFFF < U+1F600`); a text range never matches a time (probe `string_range_vs_date`) | no bound; a bound of another kind; a list or object field | `W11`-`W15` |
| `Exists(True)` / `Exists(False)` | present with any value, null included (probe `exists_true_matches`) / absent | | `W16`, `W17` |
| `IsNull()` | present and null (MongoDB `$type: 'null'`, probe) | a field not declared nullable | `W18` |
| `StartsWith(*prefixes)` | text that starts with any of the prefixes, literally, case kept | no prefix; an empty prefix | `W19`, `W20` |
| `Contains(text, case=True)` | text that contains `text` literally; `case=False` folds each character one to one (ASCII, Latin, Greek, Cyrillic); `ß` and `İ` are not folded (probe `case_blind`: `straße` does not match `STRASSE`, `istanbul` does not match `İSTANBUL`) | empty `text` | `W21`-`W24` |
| `Holds(value)` / `HoldsAny(values)` | a `list` field with an element equal to the value / to one of them | a non-list field | `W25`, `W26` |
| `NonEmpty()` | a `list` field with at least one element (MongoDB `f.0` exists, probe `list_nonempty_dot0`) | a non-list field | `W27` |
| `Each(where)` | a `list[object]` field with one element that meets every entry of `where` (MongoDB `$elemMatch`); two elements each meeting one entry do not match | a path through a list anywhere else (`sources.scene_id`): use `Each` | `W28`, `W29` |
| `And(...)`, `Or(...)` | all / any; `Or()` with no branch refused | empty `Or` | `W30`, `W31` |
| `Now(seconds=0)` | the database's clock at the moment of the write, plus seconds; allowed as a `Range` bound and in `Set` on `time` fields only, in `update` and `claim` (a change that writes it holds only `Set` and `Unset` and creates nothing), and in `insert`'s values | anywhere else, `Each` included | `T04`, `T05` |

The MongoDB adapter is nearly a passthrough: a validated tree maps onto MongoDB's own operators, whose meaning,
given declared fields and validated writes, equals the table (probe); `NoneOf` and `Not` need nothing added (they
already match missing). It translates three words: `StartsWith` into an anchored `$regex` of the escaped prefix
(probe `plan_prefix_regex`: it uses the index), `Contains` into an unanchored escaped `$regex` (`i` when
case-blind), `Now` into `$$NOW` in an update pipeline or `$expr` (probe `now_in_expr_and_pipeline`).

### 3.3 Order, paging, fields, values

- `sort` is a list of `(field, 1 | -1)` on declared non-list fields. Missing and null sort together before every
  value ascending and after every value descending (probe `sort_asc`, `sort_desc`). `O01`-`O04`.
- **Ties.** Records equal on every sort key come in an order the database chooses: today's behaviour, unchanged.
  The adapter passes the sort as given (MongoDB keeps today's index-backed plans; probe `plan_sort_seq` is `LIMIT,
  FETCH, IXSCAN`, while an added `_id` would make it `SORT, FETCH, IXSCAN`). An owner operation that needs a full
  order puts a unique key last in its sort itself (`_id`, or the fields of a unique index). The in-memory adapter
  returns tied records shuffled, with a seed fixed per test run and printed when a test fails, so no unit test can
  depend on tie order. `O05` (the double shuffles ties and the seed reproduces them). `nearest` keeps step 1b's rule
  as built (5.10).
- `skip` and `limit`: non-negative integers; `limit=None` is all. Paging with `skip` over a sort that is not unique
  can repeat or drop tied records between pages; the owner whose operation pages adds a unique key to its sort.
  Today's code that skips over a non-unique sort key: `attend.py:63` and `notices.py:122` (keep the newest N by
  `received_at`, delete the rest: which of records tied at the N-th time go is the database's, today as after;
  harmless, a held notice or a passed mark of the same second), `audit.py:66` (reads the `occurred_at` at the
  `over`-th position: tied records share that value, so the result does not depend on the order), and her read tools'
  own `skip` (`dbread.find`, `development_database_read`: her sort, so the facade's help says to page with a unique
  key last, as her usage readout already does with `_id`). Every other paging read today already ends its sort with
  `_id` (`native_api.py:461`, `native_cognition.py:36`, `history_query.py:812`). `O06`.
- `fields`: a list of declared or undeclared paths to return; `_id` always comes back; overlapping paths are refused.
  A path through a list returns, as MongoDB does, the list's object elements only, each with that field, or `{}`
  when it lacks it. `O07`.
- `group` returns rows ordered by the `by` values (the sort rule; missing and null form one group, `None`);
  `values` (group with no total) returns the distinct values ascending and, as MongoDB's `distinct`, leaves out the
  records missing a field (null stays, as `None`). `group` on a list field is refused. Totals: `Count()`,
  `Max(field)`. `G01`-`G04`.
- `limit=0` means zero records: the shared layer answers it without calling the adapter.
- `count(limit=n)` stops at n. `G05`.

### 3.4 Change words

| word | meaning | refused | case |
|---|---|---|---|
| `Set({path: value})` | sets each path, creating missing parent objects | a path through a field that is not an object (MongoDB code 28, probe), a value of another kind | `C01`, `C02` |
| `Unset(*paths)` | each path is absent afterwards; an absent path is fine | a required field | `C03` |
| `Increase(path, by=1)` | adds to a number; a missing field starts at 0 (probe `count: 2`) | a field that is not a number (MongoDB code 14, probe) | `C04`, `C05` |
| `Larger(path, value)` / `Smaller(path, value)` | keeps the larger / smaller; a missing field takes the value (probe `high`, `low`); a stored null is below every value (`Larger` takes the value, `Smaller` keeps null), as the sort rule; an undeclared field compares in the sort's order of kinds, as MongoDB does | another kind, for a declared field | `C06` |
| `AddToSet(path, *values)` | adds each value not already in the list; a missing field becomes the list (probe `tags: ['a', 'b']`) | a non-list field | `C07` |
| `Push(path, *values, keep_last=None)` | appends, then keeps the last n (`crossing.py:377`) | a non-list field | `C08` |
| `OnCreate({path: value})` | applied only when the write creates the record | | `C09` |

**Create** (`update(create=True)`, `claim(create=True)`, `replace(create=True)`): allowed only when `where` is plain
equalities, on `_id` or on every field of a declared unique index; the created record holds those equalities, then
`OnCreate`, `Set`, `Increase` from 0, `AddToSet` and `Push` as lists (probe `upsert_record`), and must hold every
required top-level field (`RecordInvalid` otherwise, before dispatch). A create by a unique index gets its `_id` from
the shared layer (`OnCreate`, a uuid4 in hex) unless `OnCreate` gives one. A create that repeats a unique key raises
`DuplicateKey`. `C10`-`C12`.

### 3.5 Unique keys

A unique index applies to the records where all its fields hold a value of their kind. A plain unique index's fields are
`required`, so "only one record may lack the field" (MongoDB's plain unique index indexes missing as null: probe
`plain_unique_two_missing: refused`) can never arise. A partial unique index lists fields in `only_where_present`: a
record missing one of those (or holding null) is outside the index; inside it, its other fields may be missing and are
indexed as null, as today (her outbound messages carry no `adapter_id`). The MongoDB adapter writes `only_where_present`
as `{f: {$type: <the declared kind>}}` for a unique index and as `{f: {$exists: true}}` for a plain one
(`event.visit.intent`), which reproduces today's 53 indexes. MongoDB keeps today's indexes: a plain unique index for
required fields, `partialFilterExpression: {f: {$type: 'string'}}` for `only_where_present` (probe
`partial_unique_refuses_duplicate: 11000`); SQLite and PostgreSQL a partial unique expression index `WHERE
json_type(...) = 'text'`. A repeat raises `DuplicateKey` on insert, replace, update and create. `X05`-`X09`.

### 3.6 Revisions, counters, claims

- `replace(expected=n)` writes only when the stored record's `revision` is n; `keep` names fields whose stored values
  survive the write (today's `COUNTER_FIELDS`). `X10`-`X12`.
- `claim(where, change, sort)` changes the first record by `sort` that matches and returns it after the change, in
  one step; two claimers never get the same record. `X13`, race `R02`.
- The counter is `claim({'_id': id}, Increase(field))`. `X14`, race `R01`.

---

## 4. Owner modules

31 owners, 328 named operations, 43 collections and the blob store (`python owner_ops.py`: `owners 31 operations
328 collections 44`, the blob store counted as one). Twelve owners are new leaf modules in `src/asuna/records/`
(they import only `asuna.store`), for collections read across many domains; nineteen are the domain modules that
already hold a collection's rules. Every collection in `code-facts-collections.md` has one owner; the census found
six more that table did not list (`crossing_words`, `memory_fires`, `carried_counts`, `carried_days`,
`carried_sections`, `host_leases`, reached through module constants or a client of their own), and that `carried.py`
writes rows into `memory_tiers`; all are owned below. The integration test's `units` collection belongs to the test.

**How an owner reads.** A read is a *view*: a named function of the owner that builds the condition and the natural
order, e.g. `messages.said(store, scene, epoch, upto=40)`. A view has the shared verbs `rows(newest_first=False,
limit=None, skip=0, fields=None)`, `first(...)`, `count(limit=None)`, `values(field)`. A call site never sees the
condition. Writes and single-record reads are operations of their own (`scenes.next_seq(store, id)`,
`messages.get(store, id, scene=...)`). `save` is the owner's revisioned write, `Store.put` underneath.

**Why 328** (accepted in the lead's review, 2026-10-28). That call sites never build a condition gives one owner
operation per distinct question the core asks: 1,607 call sites become 328 operations, about 7 per collection, most
of them `get`, `save` and one-field writes. Views with domain parameters keep the count at that; one function per
call site would be over 1,000. No smaller shape keeps conditions out of call sites; it is a cost to know, not a reason
to change the decision.

**What other modules call.** For every collection, every module outside its owner calls the owner's operations
listed here and nothing else; which operation each of the 1,607 call sites becomes is the `owner_op` column of the
map.

| owner | collections | why one owner (where several modules use it today) | operations |
|---|---|---|---|
| `records.messages` | messages | read in 46 modules, written through `put` by channels, ingress, chat, coordinator, publish; no domain module holds all its rules | `get` one line by id, fenced to conversation, epoch, scope, direction, channel; `many` lines by ids, fenced; `said` a conversation as people saw it in an epoch (people's lines and her delivered lines; people only, not yet summarised, seq window, topic, several sources, ids); `pointable` lines one may point at; `lines` live or all lines after/between positions; `inbound` lines people wrote (one or several conversations; author in/not, people only, since, seq window, wake reasons, marks: media, notice, peer, group name, aside, forward ref, peer name; not an outcome); `spoken` her delivered lines (author, since receipt, not in conversations); `outgoing` her lines in delivery states; `turn_parts` the lines of a turn; `at` the line at a position; `by_platform_id` by own, platform event or message id; `replies_to` the digest thread; `answers` answers to her question; `excluded` the digest's left-out counts; `queued` a channel's outbox for a lane and route; `in_flight_scenes`; `sending`; `unsettled`; `claim_unshown` (claim-next); `ingress`; `channel_inbound`; `visits`; `errand_results`; `mark_errands_told`; `artifact_refs`; `mentions`; `authors`; `search` (history_query); `web_page`; `mark_recalled`; `note_failure`; `redact_scope`; `save` |
| `records.scenes` | scenes | read in 52 modules; written by condense, coordinator, faults, places, lines, native_worker, ingress | `get`; `by_scope`; `of_kind`; `many`; `in_scopes`; `all`; `condense_wanted`; `channel_scenes`; `next_seq` (the counter); `authorize` (`Store.authorize`); `want_condense`; `clear_condense`; `set_condense_floor`; `note_size`; `note_tokens`; `set_character_context`; `set_timezone`; `note_fault`; `clear_fault` (if still that fault); `hold_unsent`; `clear_unsent` (if still that turn's); `asides_shown` (Larger); `told_condensed` (if still that condense); `apply_condense`; `save` |
| `records.episodes` | episodes | read in 24 modules; written by coordinator and chat | `get` (fenced); `many`; `of_source`; `of_kind`; `open`; `answered` (familiarity count); `of_scope`; `redact_scope`; `save` |
| `records.tasks` | tasks, task_messages | tasks read in 18 modules, task_messages in 4; `tasks.py` holds the lifecycle but imports most of the core | `get` (fenced); `many`; `in_states`; `by_prefix`; `continuations`; `awaiting_feedback`; `lease_expired`; `paused`; `of_conversations`; `created`; `of_episode`; `finished_since`; `of_scope`; `redact_scope`; `recent_with_inputs` (the `$lookup` aggregate as reads, 5.7); `thread`; `thread_message`; `save`; `save_message` |
| `records.plans` | plans | `schedule.py` reads 37 of 48 but is not a leaf; context, role_tools, condense, night, restarts, reflection_map read | `get` (fenced); `in_status`; `due`; `of_conversation`; `with_outcome`; `count_status`; `save` |
| `records.memories` | memory_units | read in 15 modules; retrieval, memory, dialogue_summary, privacy write | `get` (fenced: readable pairs, scope, epoch, episode, kind, status); `many`; `readable` alive memories of a character in (scope, epoch) pairs; `of_kind`; `summary_of`; `pending_index`; `dependents`; `of_scope`; `alive`; `tombstone`; `set_epoch`; `touch_salience`; `nearest` and `ensure_vectors` (as built); `web_page`; `save` |
| `records.artifacts` | artifacts | read in 17 modules; received_files, notices, capabilities, outbound_files, attend, blobs, media_life write | `get` (kind, state, storage, task revision, scopes); `by_ids`; `of_task`; `of_tasks`; `of_kind`; `of_scene`; `kept`; `with_copies`; `by_content`; `answer`; `admission`; `stored`; `insert`; `replace`; `delete_many`; `delete`; `mark_read`; `mark_sent`; `restore_bytes` (if still removed); `add_copy`; `set_copies`; `set_days_from`; `let_go`; `keep_why`; `unkeep`; `set_received_from`; `bytes_removed`; `erase_scope`; `set_fields`; `count_tool`; `redact_scope`; `save` |
| `blobs` | the blob store (GridFS `artifact_blobs` on MongoDB) | the only user of the blob interface; media_life, outbound_files, the probe call it | `put_stream`; `open`; `delete`; `erase_scope`; `exists`; `stats` |
| `records.sessions` | sessions | native_worker reads 30 of 36 but is not a leaf | `get`; `native`; `successors`; `main`; `titled`; `of_task`; `of_scope`; `invalidate`; `save` |
| `records.receipts` | lane_receipts, sink_receipts | sink receipts read by 7 modules, lane receipts by 5 | `lane_get`; `lane_of_sessions`; `lane_invalidate`; `sink_get`; `sinks`; `sink_of_kind`; `sink_window` (history_query); `redact_scope`; `save_lane`; `save_sink` |
| `audit` | audit_events | `audit.py` holds verify, prune and replay; 18 modules read it; every module appends through `Store.audit`, which calls `audit.append` | `append`; `events`; `last`; `recent`; `of_document`; `commit_of`; `count`; `latest_kept`; `prune`; `size`; `streams`; `redact_streams`; `trace` |
| `records.heads` | state_heads, state_revisions | documents, memory, understanding, self_state, policy, privacy, native_api, reflection_map, familiarity read; `Store.head`, `init_head`, `mutate` move here | `head`; `current`; `init`; `mutate`; `with_prefix`; `heads`; `revision`; `revisions`; `by_mutation`; `history`; `point_to`; `drop_head`; `tombstone_revision`; `stale_revisions`; `save_head`; `save_revision` |
| `documents` | journal_entries, journal_revisions | `DocumentStore` writes both; crossing, memory_pilot, memory_tiers read | `entry`; `slugs`; `entries`; `entry_of`; `last_entry`; `revision`; `revisions`; `revision_of_body`; `last_revision`; `save_entry`; `save_revision` |
| `records.people` | identities, scene_people | identities read in 9 modules, scene_people in 5; `people.py` is not a leaf | `identity`; `by_account`; `all_identities`; `of_person`; `label`; `labels`; `label_of_person`; `first_label`; `save_identity`; `save_label` |
| `affect` | affect_events, affect_amendments, affect_proposals | `AffectLedger` is the insert-only writer; context, native_api, reflection_map read | `insert`; `events`; `event`; `amendments`; `amendment`; `proposals`; `proposal`; `counts` |
| `stickers` | stickers, sticker_pool, sticker_memory | `stickers.py` writes all three; role_tools, media_life read | `shelf`; `sticker`; `shelf_size`; `drop_sticker`; `pool`; `candidate`; `pool_size`; `drop_candidate`; `memory`; `artifact_ids`; `save` |
| `notes` | notes | `notes.py` writes; reflection_map, role_tools read | `get`; `reply_to`; `questions`; `last_seen`; `count`; `seen_in`; `save` |
| `watches` | watches | only `watches.py` | `get`; `active`; `of_person`; `count_active`; `seen` (if `last_seen_at` is still the one read); `save` |
| `questions` | questions | `questions.py` writes; role_tools, reflection_map, tools_week read | `get`; `open_in`; `closed_untold`; `of_persona`; `asked`; `migrated`; `count_open`; `told`; `save` |
| `records.ideas` | ideas | role_tools writes; native_api, night, reflection_map read | `get`; `of_persona` (state, words contained in idea or why); `count`; `save` |
| `developer_inbox` | developer_inbox | faults raises counts, questions reads | `get`; `unread`; `of_persona`; `bump`; `save` |
| `group_members` | group_members | only `group_members.py` | `get`; `save` |
| `host_stops` | host_stops, missed_looks | restarts reads | `get`; `unshown`; `last_back`; `mark_shown` (where still null or missing); `missed`; `note_missed`; `forget_missed`; `save` |
| `switches` | switches | only `switches.py` | `get`; `on`; `changed`; `save` |
| `own_mute` | own_mutes | only `own_mute.py` | `get`; `save` |
| `lane_faults` | lane_faults | only `lane_faults.py` | `count` (each signature's hour, created); `forget_old` (replaces the TTL index) |
| `memory_tiers` | memory_tiers | `Tiers` writes; `carried.py` writes its room rows there today, which become tiers operations; native_api, reflection_map, tools/carried_check read | `get`; `items`; `last_move`; `offered`; `of_doc`; `personas`; `drop`; `drop_scenes`; `told`; `recalled`; `shown`; `surfaced`; `upsert`; `mark`; `use`; `room_told` |
| `memory_pilot` | memory_shadow | only `memory_pilot.py` and its report tool | `rows`; `count`; `forget`; `insert`; `surfaced`; `synced`; `upsert`; `drop_all` |
| `crossing` | crossing_words, memory_fires | `crossing.py` writes both; memory_tiers reads memory_fires once | `word`; `words`; `build`; `raise_generation`; `note_word`; `set_vocabulary`; `fire`; `fires`; `record_fire`; `forget_fires` |
| `carried` | carried_counts, carried_days, carried_sections | only `carried.py` | `count_day`; `days`; `forget_days`; `note_section` |
| `host_lease` | host_leases | only `host_lease.py` | `acquire`; `renew`; `release`; `mark_planned`; `mine`; `holder` |

The full one-line meaning of each operation is in `owner_ops.py` (`python owner_ops.py --markdown` prints this table
with them).

**The shared layer's own surface** (no collection's owner; 21 map rows): `Store.put` and `Store.audit` (stay; owners
call `put` through `save`, every module calls `audit`), `Store.ensure` (replaces `migrate`), `Store.recover_commits`,
`Store.seed` (tests), the **maintenance surface** (`store.maintenance.record(collection, id)`,
`.records(collection)`, `.restore(collection, record)`: store-wide by declared name, used only by `audit.py`'s
verify, trace and replay), `store.collections()`, `store.ping()`, and her read facade (section 6).

**Store methods that go.** `Store.get(collection, key, scope)` has no caller (`git grep` at `5a62ebd6`);
`Store.identity` and `Store.public_messages` are called only by `tests/test_engineering_m1.py`. All three go; the
scope rules of `Store.get` are already applied by each owner's fenced `get`.

---

## 5. The hard cases

**5.1 The counter in one step.** `scenes.next_seq(store, id)` = `claim('scenes', {'_id': id}, Increase('sequence'))`,
returning the new value; `sequence` stays a counter field that `put` keeps (`COUNTER_FIELDS`). Today's four calls
(`coordinator.py:422`, `:451`, `ingress.py:66`, `tools/refusal_probe.py:410`) do exactly this with
`find_one_and_update`. Race `R01`: four processes, 50 increments each, 200 distinct contiguous values.

**5.2 Claiming the next item across processes.** `claim(where, change, sort)`; MongoDB verified (probe, 6 claimers
on 60 items: 60 distinct). Today's one claim-next is `channels.py:279`, the owner's lines shown once on an agent's
route (`messages.claim_unshown`). The outbound queue (`channels._next`) claims by reading the queued lines and
writing each with `put(expected=revision)`: an optimistic claim on one record, which `replace(expected)` serves; it
stays as it is. SQLite serialises writers (`BEGIN IMMEDIATE`); PostgreSQL uses `FOR UPDATE SKIP LOCKED`; the double
uses a lock (one process; cross-process safety is shown in integration, `R02`).

**5.3 The host lease on one clock** (`host_lease.py`, ADR-020).

```python
take = [Set({**holder, 'since': Now(), 'expires_at': Now(LEASE_SECONDS)}), Unset('planned_stop')]
free_or_mine = And({'_id': 'host'}, Or({'expires_at': Range(lt=Now())}, {'instance': me}))
if store.collection('host_leases').update(free_or_mine, take).matched:
    return                                   # expired, or ours
insert({'_id': 'host', **holder, 'since': Now(), 'expires_at': Now(LEASE_SECONDS)})   # DuplicateKey: someone else's
renew:        update({'_id': 'host', 'instance': me}, Set({'expires_at': Now(LEASE_SECONDS)}))
mark_planned: update({'_id': 'host'}, Set({'planned_stop.at': Now(), 'planned_stop.by': by}))
```

`Now` is allowed in this `update` (in a `Range` bound and in `Set`) and in `insert`'s values; the MongoDB adapter writes
an insert holding `Now` as an upsert with an update pipeline using `$$NOW`, under a condition no record meets (`{_never:
{$type: 'minKey'}}`; an upsert's condition may not use `$expr`), so an existing `_id` is a `DuplicateKey`. Which clock:
MongoDB the server's `$$NOW` (as today, probe); PostgreSQL `now()` of the statement; SQLite the host's clock
(`strftime('%Y-%m-%dT%H:%M:%fZ','now')`), shared by every process on that host, which is the only place an SQLite file
is used; the double an injected clock (`MemoryAdapter(clock=...)`), which tests move. `expires_at`, `since` and
`planned_stop.at` are `time` fields. Today's insert path is an upsert filtered on `instance` missing; the design's
insert is the same effect (it fails when any lease exists). Not changed: a paused holder is not fenced after expiry
(today's behaviour; the file lock stops a second Host on one machine). Races `R03`: two holders for an expired lease,
one wins, the other gets `DuplicateKey` or zero matched.

**5.4 Unique keys, including "only where a field exists".** Section 3.5. Today's 18 unique indexes
(`state.py:139-186`) map one to one: five are `$type: string` partial ones (`messages` platform events and
publication key, `memory_units`, `affect_events`, `affect_amendments` source identity) and become
`only_where_present`; the rest make their fields `required`. Before each batch declares a collection, the pre-batch
check (8.3) counts her records that lack a required unique field (expected 0; any other number stops the batch).

**5.5 The revisioned write and `Store.put`'s audit.** In the core, unchanged in meaning: `put` validates, sets
`schema_version`, `revision` (1 or expected + 1), the creation time, `_last_op`, checks size; then `insert` (new) or
`replace(expected, keep=COUNTER_FIELDS unless reset_counters)`; `False` from `replace` writes the
`state.conflict` audit row and raises `Conflict('STALE_REVISION: ...')` as today; `DuplicateKey` gives
`Conflict('DUPLICATE_ID')`; then the `state.commit` audit row. `Store.audit` stays a hash-chained append: read the
stream's newest, insert seq + 1, retry on `DuplicateKey` of `(stream_id, seq)` up to 50 times (`state.py:193-208`).

**5.6 Bulk writes.** `lane_faults.receive` writes up to `MAX_ROWS` 200 upserts per adapter post with
`bulk_write(ordered=False)`; it becomes a loop of `update(create=True)` with `Increase`, `Set`, `OnCreate`
(200 round trips at most, every few minutes). Partial failure behaves as today (unordered bulk writes are partial
too). Its TTL index (`state.py:182`, 30 days) is replaced by `lane_faults.forget_old` on each write
(`delete({'hour_at': Range(lt=cutoff)}, many=True)`); no Python code reads `lane_faults` (map: 2 rows, both writes),
so when old rows go changes nothing anyone sees. Until B2 the catalog declares the TTL index as today's
(`hour_at_1`, `expire_after` 30 days, MongoDB's `expireAfterSeconds`), so `ensure` finds it on her database and
makes it on a new one; B2 declares its replacement and lists the TTL index as retired, and `ensure` drops it.
`insert(records, ordered=True)` serves `insert_many` (`crossing.py:314`, tests).

**5.7 The three aggregates.**
- *Audit heads* (`audit._latest`): `group('audit_events', {'type': AnyOf(LATEST_KEPT)}, by=('type', 'stream_id'),
  total=Max('occurred_at'))`, then the ids of the records at those times (`Or` of the pairs, in pages of 500).
  Difference: two records of one kind in one stream at the same microsecond would both be kept from pruning
  (today one); keeping one more audit record changes nothing she reads.
- *A conversation's tasks with their newest input* (`context.py:598`): read the conversation's tasks (`scene_id`,
  `scope_key`, `policy_epoch`; the fields the projection names plus `raw_input_refs`, `result.text` length computed in
  Python), then their input lines in one `messages.many(ids)` read (pages of 1,000), compute `_active` and the newest
  `received_at`, sort `(_active desc, input time desc, _id)` and keep 16, all in Python. Its cost on her data is
  measured in batch B6's check (tasks per conversation p95, time old against new).
- *The Web memory page* (`native_api.py:461`): lines sort by `occurred_at` directly (one `find`); memories sort by
  "the first of `generated_at`, `occurred_at`, `formed_at`", a computed key, so three reads each limited to
  `skip + page` (records with `generated_at`; without it but with `occurred_at`; with neither but `formed_at`), each
  sorted by its field descending then `_id` descending, merged in Python; the excerpt (`$substrCP` 200) is cut in
  Python. Exact and bounded (offset at most 10,000, `native_api.py:424`).
- *Her `aggregate`* becomes `group` (section 6).

**5.8 Prefix, contains, case-blind.** `StartsWith`, `Contains(case=)` (3.2). The 8 `_id` `$regex` prefixes (some
built as `^relationship:(a|b)\|`, `familiarity.py:34`, `understanding.py:49`) become `StartsWith` of each literal
prefix; the 3 contains (`history_query.py:536`, `native_api.py:449`, `role_tools.py:3258`) become `Contains`. SQLite:
prefix as `substr(x, 1, n) = ?` (never `LIKE`, which folds ASCII case), contains as `instr`, case-blind through a
registered one-to-one fold function; PostgreSQL `left(x, n) = ?`, `strpos`, case-blind fold to be checked against
the cases `W22`-`W24` (unverified, section 10).

**5.9 Nested fields and list items.** Dotted paths into objects; a path through a list is refused; lists use `Holds`,
`HoldsAny`, `NonEmpty`, `Each` (3.2). The two `$elemMatch` (`questions.py:150`, `:209`) become `Each`; `copies.0`,
`rejections.0`, `mentioned_account_ids.0` become `NonEmpty`; `tools_week.py:287`'s `sources.scene_id` becomes
`{'sources': Each({'scene_id': x})}`, which MongoDB answers the same for a one-field condition.

**5.10 Vector search.** As built in 1b: `nearest(space, vector, k, where)`, exact, raw cosine, equal scores in id order;
`where` is the words (equality, `AnyOf`, `And`, `Or`) on the space's filter fields, so the owner turns 1b's pairs into
an `Or` of dicts and answers an empty pair list itself, without a call; which of several records tied at the k-th score
come back is the database's (integration only, never a unit test). The double scores in float64 by brute force; ties in
conformance cases are built from identical vectors, and other cases keep scores at least 1e-6 apart (MongoDB's internal
precision is not verified). The 18 cases of `integration/test_mongo_vectors.py` move into the contract suite's `N`
class. MongoDB's vector filter refuses an empty `$in`, so the adapter drops the branches that can match nothing and
answers `[]` itself when none is left. `memory_units` declares `embedding` as `vector(768)`, the space's dimension.

**5.11 Large binary files and the record size limit.** The blob interface (methods 16-19). `blobs.py` keeps its rules in
the core: it hashes while it streams into `blobs.write`, reads the bytes back through `blobs.open` in `STREAM_PIECE`
pieces and compares hash and size, deletes on mismatch, then writes the `artifacts` row through `put`. The post-write
`metadata.sha256` update on GridFS (`blobs.py:92`) goes: the row's `sha256` is the record of the hash, and nothing reads
the metadata copy (map: one write, no read). Erasure by scope lists `blobs.of_scope(scope)` and deletes each, then marks
the rows (ADR-105, unchanged). Two stored names stay in her data because renaming them is a data migration this ADR does
not do: `storage: 'gridfs'` and the field `gridfs_id`; they live only in `records/artifacts.py` as constants (`STORED`,
`BLOB_FIELD`), documented as stored names. The GridFS file name (today the artifact key) is an optional `name` in the
blob's metadata; B8 decides whether it stays. Records stay at most 1 MiB (3.1); larger content goes to blobs as today.

**5.12 A collection chosen at run time** (46 in the code-facts table; the map's 127 hand rows include them). Three
kinds, each in `hand.py`: an owner choosing among its own collections (`affect._insert`, `memory_tiers`,
`memory_pilot`, `carried`): allowed, they are its own; store-wide maintenance by declared name (`audit` verify, trace,
replay, `recover_commits`, `seed`): the maintenance surface; her facade (`dbread`, `development_database_read`):
section 6. Everything else named a collection at run time only to loop over a fixed list (`privacy.py:92` over five
collections, `crossing.py:481` over two, `state.py:435` over three, `host.py:42` a local helper over two): each loop
becomes calls of the owners' operations.

**5.13 Creating collections, validators and indexes.** `Store.ensure()` calls `adapter.ensure(collection)` for every
declared collection, at the places `migrate` runs today (`application.py:28`, `cli.py`, tests, probes). Index names
are today's MongoDB default names (`scene_id_1_scene_seq_1`), so on her database ensure finds every index and
creates nothing; it never drops an index that is not listed `retired`; an index of the same name with other keys or
options is a `SchemaConflict` that stops the start and names it. MongoDB keeps creating today's `$jsonSchema`
validator (`required: [_id, schema_version]`) for the versioned collections; the shared layer checks the same rule
on every write, so other adapters need no validator. `memory_pilot.py:155`'s own `create_index` becomes a declared
index.

**5.14 No transactions, checked.** The invariants that span two records, and how each stays safe:

| invariant | today | design |
|---|---|---|
| a record and its `state.commit` audit row (`put`) | the record first, then the audit; a crash between is found by the record's `_last_op` and repaired by `recover_commits` at start (ADR-067) | unchanged |
| the audit hash chain (`seq`, `prev_hash`) | unique `(stream_id, seq)`; a racing append retries | unchanged; `DuplicateKey` |
| a head and its new revision (`mutate`, `DocumentStore._commit`) | revision first, head second at its expected revision; a crash between leaves an unreachable revision, and the retry with the same `mutation_id` is refused (`MUTATION_ALREADY_ATTEMPTED`), never doubled | unchanged |
| a journal import (`documents._journal_import`): entries, a revision, then the old head deleted | a crash between leaves both forms; the next import finds the entries | unchanged |
| blob bytes and their `artifacts` row | bytes first, verified, then the row; a failed check deletes the bytes; a crash between leaves bytes without a row, which carry their scope and so go with an erasure; the sweep does not see them (space only) | unchanged, named |
| the conversation counter and the line that takes the number | a crash between leaves a gap in positions | unchanged; ordering only |
| a scope erasure (`privacy._erase`): epoch bump, bytes, memories, five collections redacted, heads, revisions, every touched audit stream re-hashed | the epoch bump fences the scope first; the rest is many single writes; **a crash in the middle leaves a partial erasure, and a crash inside the audit re-hash leaves a stream whose chain no longer verifies** | unchanged and not made worse; it is privacy's own risk (ADR-105's to fix: a resumable erasure with an intent record), named here because no transaction covers it today either |
| a sticker kept from the pool (shelf insert, pool row deleted) | a crash leaves both | harmless; unchanged |

No core invariant needs a multi-record transaction, so the interface has none.

**5.15 The package, and the trap of an empty registry.** The MongoDB adapter becomes `packages/databases/mongodb/`
(`@asuna/database-mongodb`): `package.json`, `src/index.js` calling `registerDatabase({kind: 'mongodb', title,
resource_root, python: 'python', module: 'asuna_mongodb', settings: {...}})` (normalised like `normalizeChannel`,
`packages/cognition-core/src/channel.js`), `python/asuna_mongodb/__init__.py` (the adapter and the module functions of
2.2), `python/requirements.lock` (pymongo 4.16.0 and its closure), README (what a deployment configures: a replica set,
`mongot` for vector search), locale, LICENSE. The Host passes the registered entry to the worker beside `channels`;
`asuna.store.adapters.load(entry)` imports it. `adapters.open(config)` looks the kind up and, when nothing of that kind
was loaded, raises `AdapterNotInstalled('DATABASE_ADAPTER_NOT_INSTALLED: mongodb')`; it never returns a default or an
empty store (the channel registry's trap: `channel_kinds.get` answers `None` and callers carry on; `of_channel` raises,
and the adapter registry has only the raising form). The settings key that selects it is `database_adapter` (`mongodb`
today; when exactly one database package is installed and the key is absent, that one; absent with none installed is
`DATABASE_ADAPTER_NOT_INSTALLED`, absent with several `DATABASE_ADAPTER_NOT_CHOSEN`, both `AdapterNotInstalled`). Its
connection setting stays the key `mongo_uri` her saved settings already use, now declared by the package (`SECRETS`), so
her profile's settings need no change. Outside the Host (checkout tools, `integration/`), `adapters.load_checkout(kind)`
imports `packages/databases/<kind>/python`. The worker's Python environment is built from the union of the core's
`requirements.lock` and each installed package's `python/requirements.lock` (`python-env.js` hashes them all; a change
of any rebuilds), and `pymongo` leaves the core's `WORKER_DEPENDENCIES` (`tools/pack_plugins.py:43`). The places that
name the connection string today take the package's `SECRETS` and `where()` instead: `config.database_lock`,
`config.redact_text`, `config.redacted`, `native_settings.py` (its secret pattern and the deployment keys), the core
plugin's settings page (`packages/cognition-core/src/client.js`, the `mongo_uri` labels and default, which the package's
locale now supplies), and `dbread.environment`, which gives her home task's commands the registered adapter entry and
its resolved settings (`ASUNA_DATABASE_ADAPTER`) in place of `ASUNA_MONGO_URI`. `deploy/docker` keeps naming MongoDB: it
is the stack's own file.

---

## 6. Her read tool

`dbread` (her task scripts and skills) and `development_database_read` (her action brain's tool,
`native_worker.py:1438`, which takes a MongoDB filter today) become one read-only facade over the same words, given
as JSON-like dicts:

```python
from asuna import dbread
when = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00')          # -> {'range': {'gte': ..., 'lt': ...}}
dbread.show(dbread.find('messages', {'scene_id': 'local-dm', 'received_at': when,
                                     'author': {'any_of': ['a', 'b']},
                                     'or': [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]},
                        fields=['text', 'author'], sort=[('scene_seq', -1)]))
dbread.count('tasks', {'tier': {'exists': True}})
dbread.distinct('audit_events', 'payload.code', {'type': 'x'})
dbread.group('tasks', {'tier.fell': {'exists': True}}, by=['tier.fell.reason'])        # replaces aggregate
```

No vector search in her facade (decided in the lead's review, 2026-10-28): none of her scripts or skills searches by
vector, and a vector needs an embedding call her scripts do not make; it is added when she asks.

JSON words: a plain value is equality; `{"any_of": [...]}`, `{"none_of": [...]}`, `{"not": v}`, `{"range": {"gt",
"gte", "lt", "lte"}}`, `{"exists": true|false}`, `{"is_null": true}`, `{"starts_with": [..]}`, `{"contains": "...",
"case": false}`, `{"holds": v}`, `{"holds_any": [...]}`, `{"non_empty": true}`, `{"each": {...}}`; logic as the keys
`"or": [...]` and `"and": [...]` (no field is named `or` or `and`; the catalog refuses such a name). A dict value is
always a word (equality on an object field is not allowed), so the form is unambiguous. A `$`-key gets a coded
refusal that names the new form, e.g. `QUERY_MONGO_SYNTAX: "$exists" 是 MongoDB 的写法；这里写 {"tier": {"exists":
true}}`, in the error form of `docs/DEVELOPMENT.md`.

Bounds: collections are the catalog's (her allowlist: every declared collection, as she reads all today); fields
named in conditions, sorts and groups must be declared (an unknown one is refused with the collection's declared
fields listed, replacing today's `unseen_fields` hint); `limit` at most 500 (`MOST`, 50 by default), and 50 for
`development_database_read` (`tool_args.DATABASE_PAGE`); depth at most 8 and at most 64 words per query; a time limit
of 10 s per query in every adapter (MongoDB `maxTimeMS`, SQLite a progress handler on a read-only connection,
PostgreSQL `SET LOCAL statement_timeout` in a `READ ONLY` transaction). Read-only by construction: the facade holds a
`ReadOnly` wrapper whose only methods are `get`, `find`, `count`, `group`. Its answers keep what they say
today (the database, the collection, the filter as asked, the UTC window a local one became, `found`, `零行`, `more`).
`fields(name)` returns the declared fields; `collections()` the catalog's names; `place`, `history`, `now`, `recent`
stay. The raw handle goes (`dbread._default().db`); a script that needs the core's own functions (her render-budget
script calls `memory_tiers` and `render` with a store) gets `dbread.store()`: a `Store` over the `ReadOnly` adapter.
`Reader` and `Reader.from_host()` stay as the way a checkout tool opens the Host's own database read-only (the
settings the Host wrote for it): `from_host()` returns the facade above, and `.store()` the same read-only `Store`.
`tools/carried_check.py` (her nightly measure of the carried rooms) opens it this way and today reads
`state_heads`, `state_revisions` and `memory_tiers` directly; it moves to `records.heads` and `memory_tiers`
operations through `Reader.from_host().store()` in the batch that moves those collections (B9 for the heads, B11b
for the tiers), and that batch's check runs it before and after: the same five numbers.

**Her files that use the old syntax** (listed, never edited for her; she rewrites them her way; paths inside her
persona package, `packages/personas/<hers>/`):

| file | what in it is old |
|---|---|
| `skills/asuna-usage-readout/usage_readout.py` | `$exists`, `$regex` (a prefix and a literal mark: `starts_with`, `contains`), `$or`, its own `{"$gte", "$lt"}` window (line 166), `$expr` comparing two fields (line 732; no word does that: read both fields and compare in Python), `dbread.aggregate` with `$match`/`$group`/`$sum` (lines 696, 736, 751, 754: `dbread.group`) |
| `skills/asuna-usage-readout/SKILL.md` | the `aggregate` limit advice (line 271), `$exists` wording (147, 762) |
| `skills/asuna-render-budget-per-place/budget_per_place.py` | `dbread._default().db` (line 104), `$regex` on `state_heads._id` (55), raw `find_one` (65, 68), a shell that hands `db` to `memory_tiers` (121): `dbread.store()` |
| `skills/asuna-render-budget-per-place/SKILL.md` | `db = dbread._default().db` (line 40) |
| `skills/asuna-image-generation-and-display/SKILL.md` | reading GridFS bytes "with pymongo / GridFSBucket" (line 466) |
| `skills/asuna-offline-selfchecks/SKILL.md` | line 154 describes equality and substring matches: to be read by her, may need no change |
| `skills/asuna-usage-readout/check_skill.py` | its checks name `asuna.dbread` (line 71) and `development_database_read` (line 199): to be read by her with the readout's rewrite |
| her task scripts outside the repository | not listed here (her workspace is not read); the refusal names the new form; she can list them with `grep -rl dbread` in her workspace |

Core files that the batch itself updates (current references, not hers): `packages/cognition-core/skills/asuna-database/SKILL.md`
(the words, `group`), `packages/cognition-core/skills/asuna-self-improvement/SKILL.md` line 49 ("pymongo can
import"), `src/asuna/development.py`'s tool description of `development_database_read`, `src/asuna/tasks.py:333` (the
`sandbox_run` tool description, which her action brain reads: "read the database with asuna.dbread"; its new words
go to her with B12 like any wording she reads), and the channel skill
`packages/channels/napcat-qq/skills/qq-napcat-adapter/SKILL.md` lines 195-197 (it describes `store.db.messages`).
`RUNTIME_API.md:748` (home task commands get `ASUNA_MONGO_URI` for `asuna.dbread`) changes with B14's
`ASUNA_DATABASE_ADAPTER` (5.15). Order with her own work: she moves her self rules into
`asuna-self-improvement/SKILL.md` on 2026-10-29 at 23:00; B12 comes after that and changes line 49's sentence only,
on top of her version.

---

## 7. Tests

### 7.1 The contract suite

`tests/store_contract.py`: pytest classes on a `store` fixture (`Checked` over the adapter under test, with the
suite's own small catalog of synthetic collections), which the running module provides through an `open_store`
fixture. `tests/test_store_contract.py` runs them on the in-memory adapter (unit);
`integration/test_store_contract.py` runs the same classes on MongoDB on a throwaway `asuna_v2_test_*` database,
dropped at the end and on failure. No marker skips a case outside `capabilities`, except in the stand-in's run, and
there only through `tests/harness_skips.txt` by the case's `[stand-in]` id. Two cases run on the double only, in
`tests/test_store_contract.py`, because a server neither shuffles ties by a seed nor lets a test move its clock:
`O05` and the double's injected clock; the shared `T` cases use times relative to the real clock.

| class | cases | what |
|---|---|---|
| `W` words | 31 | 3.2, each rule above, with records missing the field, null, empty list, list, other kind |
| `O` order | 6 (+ `O05` on the double) | missing/null first and last, multi-key, explicit `_id` direction, a unique key last gives one order on every adapter, skip, limit, fields; `O05`: the double shuffles ties (two seeds give two orders, one seed the same) |
| `G` group | 5 | count, max, two keys, values ascending (missing out, null in), count with limit |
| `C` changes | 12 | 3.4, create rules |
| `X` writes | 15 | insert one and many (position, earlier kept), get missing, delete one and many, unique required and `only_where_present`, duplicate on insert, update and create, replace at a revision, stale, keep counters, claim order, counter, size (records exact, bytes growing) |
| `T` time | 5 (+ the clock case on the double) | aware round trip, naive refused, ms truncation, `Now` in a range and in `Set` and `insert` (on the real clock); the double's injected clock moved past an expiry |
| `V` validation | 8 | undeclared stored and returned but not queryable, kinds, bool not number, nullable, required, size limit |
| `N` nearest | 18 | the 18 cases of `integration/test_mongo_vectors.py` (filters by value, list, pair; k 1, 12, 24; identical vectors; refusals); exact against brute force |
| `B` blobs | 6 | write, open, seek, delete twice, missing, of_scope; a 5 MiB synthetic stream |
| `S` schema | 6 | ensure idempotent, retired index dropped, conflict refused, `NotSupported` before dispatch, unknown adapter kind refused, ping and close |
| `R` races (integration only) | 4 | counter (4 processes x 50), claim (6 x 60), lease expiry (two holders), stale revision (two writers) |
| `D` differential (integration only) | 1 | Hypothesis, `derandomize=True`, at most 200 records and 100 generated where trees per run (missing, null, empty lists, equal sort keys); `find` and `count` on MongoDB equal the double's, order included |

Size, per run (counted at B1b; times as measured, with where):
- the in-memory run: 114 cases, 112 shared (W 31, O 6, G 5, C 12, X 15, T 5, V 8, N 18, B 6, S 6) and 2 its own;
  its 111 `[memory]` cases took 0.25-0.26 s in the B1b worktree (B1a's run of 112 took 0.69-0.72 s in another
  checkout of the same machine);
- the stand-in run: the 112 shared less `S05` (it opens no store, so it runs once): 111 `[stand-in]` cases, of which
  80 pass and 31 are listed in `tests/harness_skips.txt` by their `[stand-in]` ids; 0.09 s in the B1b worktree;
- the integration run on MongoDB: the 112 shared, `R` (4) and `D` (1, 100 generated conditions), 117 cases in 46 s
  from the B1b worktree against the configured server, under the target of 60 s.

Which cases pin each method of 2.2 (a case fails when the in-memory adapter lacks the method; checked at B1b by
deleting each method in turn), and from which batch the core first calls it:

| method | pinned by | first called by the core |
|---|---|---|
| `ensure` | every case (the `store` fixture ensures), `S01`-`S03` | B1b (`Store.ensure`, `migrate`) |
| `ensure_vectors` | `N01`, `N02`, `N17`, `N18` | B1b (`Store.ensure_vectors`, retrieval as built) |
| `get` | `X03` and 25 more (`C`, `O07`, `T`, `V`, `X`) | B2 (the lease's holder) |
| `find` | the `W` cases that match records, `O01`-`O04`, `O06`, `O07`, `C11`, `T03`, `X02`, `X05` | B1b (`Store.audit`'s newest of a stream, `recover_commits`) |
| `count` | `G05`, `X04` | B1b (`recover_commits`) |
| `group` | `G01`-`G04` | B4 (messages' `distinct`, as `values`) |
| `insert` | every case that writes, `X01`, `X02` | B1b (`Store.put` new, `Store.audit`) |
| `replace` | `X09`-`X12` | B1b (`Store.put` at a revision) |
| `update` | `C01`-`C12`, `O07`, `T04`, `T05`, `X08`, `X12` | B2 (the lease, the fault counts) |
| `claim` | `C12`, `T04`, `X13`, `X14` | B3 (the conversation counter) |
| `delete` | `X04`, `X05` | B2 (the lease released, old fault counts) |
| `nearest` | `N01`, `N02`, `N17`, `N18` | B1b (`Store.nearest`, retrieval as built) |
| `size` | `X15` | B10 (audit prune) |
| `ping` | `S06` | no caller until B13 (`native_worker.py:1042`'s ping moves to it) |
| `close` | `S06` | no caller until B13 (the core's `client.close()` calls move to it) |
| `blobs.write` | `B01`-`B03`, `B05`, `B06` | B8 (`blobs.py`) |
| `blobs.open` | `B01`-`B04`, `B06` | B8 |
| `blobs.delete` | `B03` | B8 |
| `blobs.of_scope` | `B05` | B8 (erasure by scope, ADR-105) |

Hypothesis is in the `dev` dependency group (`hypothesis==6.170.12`) for class `D`.

### 7.2 What the contract suite cannot show

How call sites compose (the right view with the right parameters) is shown per batch on her real database, read
only (8.3): the old query against the new owner operation, same ids in the same order.

### 7.3 Unit tests can never reach a server

Enforced by the test setup, from batch B0:

1. Every MongoDB client a unit run makes is the in-process stand-in (`tests/unit_run_site/sitecustomize.py`: a
   mongomock client over one shared in-process store, whatever address it is given; no socket is opened). The test
   process loads it before importing `asuna`, and every Python process the run starts with its environment loads it
   too (that folder on `PYTHONPATH`, `ASUNA_UNIT_RUN=1`).
2. Every configuration the run loads (`asuna.config.load`, which `testing.suite_config` calls) names the address
   `mongodb://unit-run.invalid:27017/` (RFC 6761: it cannot resolve), so a process that does not inherit the
   environment, such as a confined command given the address through `dbread.environment`, has no server to reach
   either. Each lock is enough alone.
3. A guard test (`tests/test_no_server.py`) asserts both, in the test process and in a child process, so a change that
   undoes them fails the run. The stand-in ignores `tz_aware`, so in unit runs only the MongoDB adapter reads naive
   times; a recovery of a record holding a datetime could be refused there, never on a server.
4. After B13, unit runs register only the `memory` adapter; opening any other kind raises `AdapterNotInstalled`, and
   the MongoDB package is never loaded under `tests/`.

`integration/` is its own run (`pytest integration`, outside `testpaths`), the only place a server is reached, on
throwaway databases of synthetic records, dropped at the end and on failure, skipped when the server is not
reachable.

**The interim harness (B0 to B13), the owner's decision of 2026-10-28 evening (section 9).** Until every call
site has left `store.db`, production code still calls pymongo collections, which the in-memory adapter cannot serve.
So from B0 the unit run's `Store` gets an in-process `mongomock` client (no server, no socket) instead of a real one;
from B1b the MongoDB adapter itself runs over that client in unit runs, so old call sites and owners see the same
data. The harness is temporary and never the reference (the research's warning that fakes drift applies to a
reference, which this is not); B13 switches unit runs to the in-memory adapter and removes mongomock, and tests that
then fail relied on MongoDB's or mongomock's own behaviour and are fixed or go (rule R1 below).

**B0 in detail.**
- Baseline: the last full unit run on the server, green at `a00a9aa0eef6` (Python: 1,519 passed).
- B0 runs the unit suite once under the harness with no skip list, without a server. Each failure is read: one that
  is a gap of the harness (a feature mongomock lacks: `$vectorSearch`, `$$NOW` in a pipeline, `collStats`, ...) goes
  into one reviewed file, `tests/harness_skips.txt`, one line per test: `test id | what the harness lacks`; a failure
  that is not a harness gap is fixed, and only one that a tests-only change cannot fix is listed, apart, named as a
  defect with where it is fixed (as built: the clock-tie class below, five tests).
- `tests/conftest.py` reads that file at collection and marks each listed test skipped with the reason `UNCHECKED, not
  passed: the interim harness lacks <what>`. Nothing is caught at run time: a listed id that no longer exists fails the
  collection (found only in a whole run, no `-k` and the paths from `testpaths`, since a part of the suite cannot know
  the whole list; the landing run is the whole suite, so a stale line is caught there), and a test that fails and is not
  listed fails the run. A line skips only the collected test whose id it equals exactly, parameters included (a
  parametrised test is listed once per parameter); a line equal to no collected id fails a whole run's collection. A
  line equal to a case of the store's contract with the adapter parameter `memory` stops the collection
  (`HARNESS_SKIP_HITS_THE_REFERENCE`): a contract case is listed by its `[stand-in]` id only.
- The lead reviews the list; B0 reports pass, skip (by reason) and run time against the baseline.
- B13 deletes the file with the harness.

### 7.4 The suite reset (requirement 6)

Today: 193 test files, 1,285 test functions (parametrised ones count once; pytest collects about 1,500), 868 of
them need a database through the `store` fixture or a fixture of their file that takes it, in 139 files; 5 files use
mongomock, 50 make a client or a `Store` themselves (`test_census.py` at `5a62ebd6`). A run takes 9 to 16 minutes on
this machine (ADR page). The time on the double is measured once it exists (B13), with `pytest --durations=0`
written to a TSV. "Test count and run time on the double" counts the in-memory run only (the contract's `[memory]`
cases and every other test), never the stand-in's `[stand-in]` cases, so B15 compares like with like. B15's before
and after are the landing run's numbers only (a fresh worktree, the whole suite without `-k`, as the landing script
runs it), never a checkout's own run; the baseline is B0's landing run at `1f7bb31bc629`: 1,502 passed, 20 skipped,
2 min 37 s (section 10).

Which tests go, by rule (applied in B15, one rule at a time, each with its count):

- **R1** a test whose subject is the database's behaviour (query meaning, index behaviour, mongomock's fidelity) goes:
  the contract suite owns it.
- **R2** of tests asserting the same invariant through the same code path, one stays: the one closest to what she or
  a person sees.
- **R3** a test of wording goes, unless the words are the contract: error codes (`CODE:`) and `WORDS` stay
  (`tests/test_refusal_words.py`), prompt and message prose goes.
- **R4** a test of the call sequence or internal structure (mocks counting calls, private helpers) goes.
- **R5** a test named for an ADR's history (`test_adrNNN_*`) stays only for the invariants `docs/DEVELOPMENT.md` lists
  (privacy and visibility, authorization and epoch fencing, exactly-once ingest and publication, crash recovery,
  audit integrity, sandbox isolation, visible native behaviour); the rest goes.
- **R6** every remaining test runs under 1 s on the double or is marked `slow` with its reason; the default run's
  target is under 120 s.
- **R7** (from then on) a new test names the invariant it protects in its docstring, and that no other test covers it.

---

## 8. Migration

### 8.1 Every call site mapped

`call-site-map.tsv`: 1,607 rows in 99 files (1,571 in `src/asuna`, 27 in `tools`, 9 in `integration`). Methods:
`find_one` 674, `find` 296, `Store.put` 188, `Store.audit` 144, `update_one` 81, `count_documents` 42,
`Store.authorize` 30, `delete_many` 17, `distinct` 16, `delete_one` 12, `replace_one` 11, `Store.head` 11,
`insert_one` 9, `update_many` 8, `Store.nearest` 7, the rest under 7 each. Assigned: 1,459 by rule (`owner_ops.RULES`:
collection, method, condition shape), 127 by hand (`hand.py`, 125 entries: every condition held in a variable,
merged with `**` or keyed at run time, every collection chosen at run time, each with what the code asks), 21 to the
shared layer; 0 unassigned (the script exits 1 otherwise). Why more than the code-facts table's 1,026: that census
counted `<x>.db.<collection>` only; this one also counts collections reached through a `db` parameter or local
(`visibility`, `privacy`, `familiarity`, `crossing`), handles kept in variables or attributes (`tiers.rows`,
`column = getattr(store.db, 'messages')` in `discussion_digest`, `history_query`, `scene_links`), GridFS bucket calls,
database commands, and the `Store` API (`put`, `audit`, `authorize`, `head`, ...), which also names collections.

A trap of the move: today's pymongo calls pass `limit=0` to mean "all" (`find`, `count_documents`); in the store
`limit=0` means zero records (3.3), so each such call site moves to `limit=None`.

### 8.2 Batches

One batch is one branch in its own worktree, one review by the lead, one merge, and (where it changes the worker)
one install: alone or in one of the four pairs below. Batches run in order; no two edit one file at once (the big owners touch 54 and 60 files). Every batch
after B1b depends only on B1b, so each reverts alone (`git revert -m 1` of its merge restores its call sites; its
owner module has no other caller). B1b reverts alone only before B2 lands.

| batch | what | rows | restart | what proves nothing changes for her |
|---|---|---|---|---|
| B0 | unit runs reach no server (7.3), the interim harness and its reviewed skip list `tests/harness_skips.txt`; reports pass, skip by reason and run time against the baseline (`a00a9aa0eef6`, 1,519 passed) | tests only | no | the guard test; no connection to her server in the run; nothing outside `tests/` changes |
| B1a | `asuna.store`: words, catalog (fields filled per batch), errors, the in-memory adapter, the registry, the shared layer's checks (`Checked`, `Handle`); the contract suite on the double | new code, unused by the worker | no | the contract suite on the double |
| B1b | the MongoDB adapter (`src/asuna/store/mongodb.py`); `Store` over it: `put`, `audit`, `recover_commits`, `ensure` (was `migrate`), `nearest`, `ensure_vectors`, taking over `Checked` and `Handle`; `store.db` kept for old call sites; Hypothesis in the `dev` group and class `D`; `tools/pack_plugins.py` ships `src/asuna/store/` (it copies top-level modules only today) and `tools/project_map.py` maps the package | 38 shared rows | yes | the contract suite on MongoDB (integration, throwaway), class `D` included; the packed worker holds `asuna/store/` and the project map lists it, both checked at landing; `ensure` against her database in dry-run (list indexes only): zero to create or conflict; after the restart, `audit.verify_documents` over the commits since: 0 mismatches |
| B2 | `host_lease`, `lane_faults` (Now, create, the TTL index retired) | 9 | yes | lease taken, renewed and released across the restart (`host_stops` records a planned stop); fault counts keep rising |
| B3 | `records.scenes` | 221 in 60 files | yes | 8.3 on each view and get; the counter: positions contiguous after the restart |
| B4 | `records.messages` | 229 in 54 files | yes | 8.3; her turn context built from the same lines (the `said`, `inbound`, `spoken` views compared) |
| B5 | `records.episodes`, `records.sessions`, `records.receipts` | 166 | yes | 8.3 |
| B6 | `records.tasks`, `records.plans` (the `$lookup` as reads) | 168 | yes | 8.3, and `recent_with_inputs` against the aggregate on 20 conversations: same 16 tasks, same order, time p50/p95 |
| B7 | `records.memories` (retrieval's lexical reads; vector parts as built, 1b's pairs as an `Or` of dicts, an empty pair list answered without a call) | 67 | yes | 8.3; retrieval's whole search old against new on 40 queries (as 1a did): the same six and 24 |
| B8 | `records.artifacts`, `blobs` (the blob interface), `media_life`, `outbound_files` | 126 | yes | 8.3; blob probe on a throwaway database; her stored files open and hash-check (20 sampled ids, read only) |
| B9 | `records.heads`, `documents`, `records.people`, `records.ideas` | 151 | yes | 8.3; `audit.verify_documents` after the restart |
| B10 | `audit` reads, prune and redaction; `privacy` over the owners' `redact_scope`, `tombstone`, `invalidate` | 47 (+ the 146 appends, which stay `store.audit`) | yes | 8.3; prune in dry-run counts equal old against new; the erasure path on a throwaway database (no erasure on hers) |
| B11a | `stickers`, `notes`, `watches`, `questions`, `switches`, `own_mute`, `group_members`, `developer_inbox`, `host_stops` | 120 | yes | 8.3 |
| B11b | `memory_tiers` (with `carried`'s room rows), `carried`, `memory_pilot`, `crossing`, `affect` | 125 | yes | 8.3 |
| B12 | her read facade: `dbread`, `development_database_read` (section 6); she gets the list first | 8 | yes | the facade's answers for the reads her scripts make today, written in the new form by the builder in a scratch file outside her package: same counts and rows as the old form; for `usage_readout`'s comparison of two fields (section 6's list, her `$expr` at `usage_readout.py:732`), also the rows read before the comparison in Python |
| B13 | `store.db` and pymongo leave the core outside the adapter module; repository guards: no `store.db`, no `pymongo`/`bson`/`gridfs` import and no `$`-key literal in `src/asuna` outside the adapter, `store.collection(name)` and `store.put(name, ...)` only in the owner of `name`, no collection `pending` (3.1); unit runs on the in-memory adapter, mongomock goes; the first core callers of `ping` (`native_worker.py:1042`) and `close` (the core's `client.close()` calls) | guards | yes | the guards; the unit run on the double (its time measured, 7.4); the integration contract run |
| B14 | the package split (5.15): `packages/databases/mongodb/`, `registerDatabase`, the registry, the settings keys, the Python locks, `pack_plugins`, `release.py`, the profile's package list | install path | yes | after the restart her `ensure` creates nothing and changes nothing (same MongoDB, same database, same records); `audit.verify_documents` passes; the start fails with `DATABASE_ADAPTER_NOT_INSTALLED` in a demo profile without the package |
| B15 | the suite reset (7.4) | tests only | no | before and after: test count and run time on the double, the landing run's (7.4) |

**The stand-in is checked against the meaning table, not trusted.** From B1b the unit run also runs the shared
contract classes on the MongoDB adapter over the stand-in's client, beside the in-memory adapter: one `open_store`
fixture with the adapter as its parameter, `[memory]` and `[stand-in]`. A case on which the two disagree is a place
where a batch's green would only mean "the same as the stand-in": it goes to `tests/harness_skips.txt` by its exact
`[stand-in]` id, with what the stand-in lacks, so it is never read as checked, and the integration run on MongoDB
(7.1) decides it. The in-memory run, the reference, is never skipped: the collection refuses a line that would reach
it.

**Restarts, two batches to one where they cannot hide each other.** Each batch is still reviewed, checked (8.3)
and merged alone; only the install is shared, and only for adjacent batches over disjoint collections whose
failures show in different places. Installed alone: B1b (every write and audit of hers goes through it), B4 (what her
context is read from), B7 (her recall), B10 (privacy and audit: its check, `audit.verify_documents`, is also B9's),
B12 (her tool), B13 (the unit run switch and the guards), B14 (the install path). Installed in pairs: B2 with B3 (the
lease shows at start, the counter in positions), B5 with B6 (episodes, sessions and receipts against tasks and plans),
B8 with B9 (files and blobs against heads, documents and people), B11a with B11b (disjoint small owners). So eleven
restarts, not fourteen. A pair whose first restart shows a fault is reverted whole, then installed one at a time.

Building: one builder subagent, warm, batch after batch; B11a and B11b touch disjoint files and may be built in
parallel worktrees, landing one at a time. Per batch: the touched modules' tests and the contract suite on the
double while building, one full unit run (no server) at landing; the integration contract run in B1b, B2, B8, B13,
B14. No suite run only to wait. Each batch's worktree is removed when its branch merges; every test and probe
database is dropped at its end and on failure. Current references change with the code in each batch (`docs/DEVELOPMENT.md` "Where
state lives" and "Tests", `RUNTIME_API.md` for the facade, `INSTALL.md`/`RUN_ASUNA.md` and the package README for
the adapter in B14).

### 8.3 The per-batch check on her database (read only, light, numbers only)

`tools/adr104_equivalence.py <batch>` (tracked, generic, no data of hers in it): the lead's check, run for each batch
before its merge, as part of the lead's review of the batch (the owner is informed of its numbers; he is not a gate):

1. **Cases**: one per changed read in the batch (map rows), each a pair: the old pymongo call as the replaced code
   wrote it (kept in the batch's case table) and the new owner operation.
2. **Parameters** sampled from her database through the new owners themselves: at most 20 per case (recent
   conversation ids, task ids, epochs, times), the same for both sides.
3. **Run**: one read-only connection, serial, `maxTimeMS` 2000 per query, at most 1,000 queries per batch; three runs
   per case for timing.
4. **Compare**: old and new are the same query on the same server, so the check requires identical ids in identical
   order, ties included, identical counts and values, and identical plan stages from `explain` (a new `SORT`,
   `COLLSCAN` or another index is a difference). Any difference stops the batch; the owner operation is corrected
   until its query, as the adapter sends it, gives what the old one gave. There is no "tie reorders" bucket: under
   3.3 the adapter passes today's sort unchanged, so MongoDB's own tie order is what both sides see.
5. **Before declaring a collection**: per declared field, counts of records by BSON type and of nulls (`$type` counts),
   of records missing a required unique field, of records whose BSON size and JSON size fall on different sides of 1
   MiB. Rule: the single type present gives the kind (int and double: `number`; string: `text`; date: `time`; bool;
   array: `list`; object: `object`); nulls give `nullable`; two incompatible types, a missing required field or a size
   disagreement stop the batch and are reported. The unit run at a batch's landing is the whole suite without `-k`, the
   only run in which a skip-list line that names no test fails the collection. B1b's check is `ensure` as a dry run (to
   create, make, drop, conflicting; validators) and these counts for the fields it declares; exit 0 clean, 1 something
   differs, 2 not checked. On her data it needs `--max-ms 10000`: at 2000 three large collections stay unchecked.
6. **Output**: numbers only (case name, n, same, differing, p50/p95 old and new, plan stages, type counts), to `<data>/private/adr104-evidence/<batch>/`; ids never leave her machine; the folder goes when the batch
   merges, except a manifest named in the ADR with its path and size.

Writes are not run on her database: the change words are proven by the contract suite on MongoDB, the call sites by
the unit tests, and after each restart by `audit.verify_documents` over the commits written since (each committed
document equals its audit record).

---

## 9. What lands today, and what does not

The order of review: the lead reviews this page and every batch (with its 8.3 check); she receives the design once,
finished; the owner is informed and is not a gate.

**The owner's decision (2026-10-28 evening): the temporary stand-in.** Unit tests run on mongomock, in-process, with
no server, from tonight until B13 removes it (7.3). Its stated cost: a fake leaned on for the length of the move, never
the reference of the meaning table; the tests it cannot carry are skipped in one reviewed list
(`tests/harness_skips.txt`), each with what the stand-in lacks. Not chosen: switching the database tests off until
each module has moved, which would leave the 868 test functions that need a database (139 files, `test_census.py`)
unrun for nearly the whole move, most of them until B13.

**What lands today (2026-10-28): B0.** It is tests only and changes nothing she sees: the guards that keep every unit
run off a server, the stand-in, its reviewed skip list, and its report (pass, skip by reason, run time against the
baseline, 1,519 passed at `a00a9aa0eef6`). From the moment B0 lands, the unit suite never reaches her server again;
until it lands, nobody runs the unit suite.

**What does not land today:** B1a to B15. They land at the pace their checks allow, one at a time, installed in eleven
restarts for the fifteen that change the running worker (B1b, B2, B3, B4, B5, B6, B7, B8, B9, B10, B11a, B11b, B12,
B13, B14: installed alone B1b, B4, B7, B10, B12, B13, B14; in pairs B2+B3, B5+B6, B8+B9, B11a+B11b; seven and four
make eleven restarts; B0, B1a and B15 change nothing that runs and need none); nothing is shortened for a date. From B13 the unit run is on the in-memory adapter; only `integration/` reaches a server, on
throwaway databases.

What she sees: no change of behaviour in any batch (each shown by 8.3); in B12 the new syntax of her read tool and
the list of her files (she rewrites them; until she does, her old calls are refused with the new form named). Her
signature, at the merge blob of each: B1b (put and audit on her data), B4 (what her context is read from), B7 (her
recall), B12 (her tool). B14 (the package split, which restarts her; the owner ruled it is not hers: it has nothing
to do with her cognition core, while the adapter is) and B15 (the suite reset) she is told about; she does not sign
them.

---

## 10. Unverified points the design depends on, and how each is verified

| point | status | how |
|---|---|---|
| MongoDB: `{f: null}`, equality on lists, `$ne`/`$nin` on missing, `$exists` with null, `$in: [null]`, `f.0`, bool not number, sort of missing and null, code-point order, case-blind folding, partial and plain unique, `$inc/$max/$min/$addToSet` on missing, refusals 28 and 14, upsert record, `$$NOW` in `$expr` and pipelines, aware round trip and ms precision, claim-next with six claimers, the `_id` tie-break's `SORT` stage, prefix regex on an index, `collStats` | **verified today** | `probe-mongo-facts.json` (MongoDB 8.2.6, replica set) |
| Greek final sigma under case-blind matching | not verified | conformance case `W24` |
| the clock-tie class (found by B0): this machine's clock moves in 1 ms steps, so two records written within one step carry the same time, and code that decides by the latest or oldest time decides by a hash `_id` | proven for `memory_tiers` (9 of 12 runs failed on the stand-in, 0 of 12 with a strictly increasing clock) and seen directly in the journal; three more tests flaky the same way | its own change (one clock in the core that never repeats a time, a counter where a true order is needed), before the batch that moves the code concerned; an owner operation never relies on time order alone (3.3) |
| MongoDB's internal vector precision | not verified | stated tolerance (5.10); 1b's integration test compares exact results with brute force |
| mongomock carries the 868 database tests | measured in B0 (2026-10-28, `1f7bb31bc629`): 1,502 passed, 20 skipped (14 gaps of the stand-in, 5 of the clock-tie class, 1 skip from before), 2 min 37 s | `tests/harness_skips.txt` |
| her data's kinds per declared field, required unique fields present, BSON and JSON sizes agree at 1 MiB | not verified | 8.3 step 5, per batch, numbers only |
| the reads replacing the `$lookup` and the Web page aggregate cost no more on her data | not verified | B6 and B4/B7 checks, p50/p95 |
| SQLite: `RETURNING` (3.35+), partial and expression indexes, `json_each`, `BEGIN IMMEDIATE`, `LIKE` folding ASCII, no `regexp()` by default | from documentation (research), not run | when a SQLite adapter is written, its contract run |
| PostgreSQL: `SKIP LOCKED`, `NULLS FIRST`, `COLLATE "C"`, SQLSTATE 23505, `lower()` on non-ASCII | from documentation (research), not run | when a PostgreSQL adapter is written, its contract run |
| sqlite-vec has no `IN` in KNN filters (several queries merged) | from the ADR page's survey | its adapter's `N` cases |

---

## 11. Objections to the lead's decisions

None open. The five raised in the first version were settled in the lead's review of 2026-10-28 and are written
where they belong: no regular-expression subset (2.3); `nearest` out of her facade until she asks (section 6); the
tie order of record reads (3.3); the interim harness, the owner's decision (7.3, section 9); the count of named
operations (section 4).

Could not be designed here: nothing of the interface. Two numbers are measured only when built (the contract suite's
run times and the unit run's time on the double), and the per-batch facts of her data (8.3 step 5) are read only
when each batch runs; the rules that turn them into decisions are on this page.
