# Several databases behind one abstraction: survey and recommendation

Date: 2026-10-28 (NZDT). Written by Claude Code (Opus 5.5) as an independent researcher.
Input: the brief's requirements only. I did not read this repository's code, docs, ADRs or plans.
Method: primary sources (project docs and source files on GitHub), read on 2026-10-28. Claims I checked
today cite a source. Claims from memory that I did not re-check today are marked **[unverified]**.

---

## 0. Verdict

Build a **small document-store port**. Application code calls it with a **declarative query
vocabulary**: a strict subset of MongoDB's filter and update syntax, parsed into a typed tree. The
**meaning** of that vocabulary is defined once, in a one-page semantics table and in an **in-memory
reference backend**. Each real backend (MongoDB, SQLite, later PostgreSQL) translates the tree. The
hard cases are not built from generic pieces. They are **four named primitives**: claim-next,
compare-and-set by revision, server-clock `Now`, and vector search. Every query names only **declared
fields** of a per-collection field schema, and that rule is what makes one meaning possible across
backends. Faithfulness is proven by **one shared conformance suite**: the in-memory backend in unit
runs, every real backend in the hand-run integration suite. A seeded **differential test** compares
each real backend with the reference on generated data.

The backend-facing interface is about **13 methods plus about 20 operators**. That is the size of
Kinto's storage interface (13 abstract methods) and well below any ORM dialect. The strongest
alternative is SQLAlchemy Core on SQLite/PostgreSQL with MongoDB retired. It loses here because it
cannot keep MongoDB live during the move, its "in-memory" test backend is SQLite, which is faithful
only to SQLite, and it leaves null, missing-field and array semantics undefined for JSON data (§5.7).

---

## 1. Projects surveyed, and where each draws the boundary

### 1.1 Summary table

| Project (version read) | Boundary | Backend-facing size | Gaps handled by | Faithfulness | In-memory backend |
|---|---|---|---|---|---|
| Django ORM + django-mongodb-backend (docs 6.1) | Full ORM; backend = compiler + operations + features + schema editor | Very large; `BaseDatabaseFeatures` alone has ~160 flags | Feature flags; a long "limitations" page for MongoDB | Django's own test suite, gated by flags | No (SQLite `:memory:` is used instead) |
| SQLAlchemy (main) | SQL expression language / ORM; backend = dialect | Very large (dialect, compiler, types) | `SuiteRequirements` exclusions per dialect | **Dialect compliance suite** `sqlalchemy.testing.suite` | No |
| Spring Data (Core API 4.1.0, KeyValue 4.1.2) | Repository interfaces; derived queries from method names (`PartTree`, 27 `Part.Type`s); store templates | Per store: a query creator per `Part.Type` plus a template | Store throws on unsupported part types; store-specific `@Query` escape | Per-store test suites **[unverified]** | Yes: KeyValue map repositories evaluate derived queries in memory (details **[unverified]**) |
| Doctrine ORM 3.7 / ODM / Collections 3.1 | Separate ORM and ODM; shared `ObjectRepository` (`find`, `findBy`, ...) **[unverified list]** and a shared `Criteria` language | Criteria: 12 comparison and 3 composite operators | Criteria is deliberately "limited" | Not seen | **Yes**: `Criteria` runs on in-memory `ArrayCollection` and in SQL |
| Ecto 3.14.2 | Query DSL compiled by the adapter | ~10 callbacks (`prepare`, `execute`, `stream`, `insert`, `insert_all`, `update`, `delete`, ...), but the adapter receives the **whole query AST** | Adapter raises on unsupported query parts **[unverified]** | Per-adapter **[unverified]** | No |
| Prisma (6.19 for MongoDB; 7.x) | Generated client over one schema; engine per connector | Inside Prisma (not user-implementable) | MongoDB: no Migrate, no v7 yet, `isSet` filter for unset vs null | Prisma's own | No |
| MikroORM 7.2 | Unit of work + **Mongo-style operator filters** over SQL and MongoDB drivers | Driver + platform classes | Operators marked "postgres only"; per-driver full-text | Own suite | No |
| TypeORM | ORM; MongoDB via separate `MongoEntityManager` / `MongoRepository` | n/a | MongoDB gets a **different API**; `query` and `transaction` unavailable | n/a | No |
| Temporal (main) | **Named store interfaces** (`ShardStore`, `TaskStore`, `ExecutionStore`, `QueueV2`, ... 9 in total) + a `sqlplugin` layer for MySQL/PostgreSQL/SQLite | Large: dozens of methods, each per backend family | Optional capability interfaces (`RunAlreadyExistsChecker`) | Shared `persistence-tests` package | No (SQLite in-memory for dev) **[unverified]** |
| Keycloak map storage (2022–23) | Generic map store with criteria, JPA and Hot Rod layers | Large | n/a | n/a | Yes (CHM) |
| Matrix Synapse | Hand-written SQL in storage classes; `BaseDatabaseEngine` for SQLite/PostgreSQL | Engine: ~4 properties + ~11 methods; SQL itself is shared | Engine properties (`supports_using_any_list`, ...) | Tests run on SQLite by default, PostgreSQL in CI **[unverified]** | No |
| Mattermost (v11) | Named `store.Store` interfaces (per entity) | Large | n/a | `StoreTest()` loops every store type | Mock store only |
| Airflow 3.3.2 | SQLAlchemy ORM | n/a | Docs exclude databases without row locks from HA | n/a | No |
| Jaeger v2 (main) | `tracestore.Reader` / `Writer` with typed query params + `Filter` | Reader: 8 methods incl. `SearchCapabilities` | **Declared capabilities checked before dispatch**; per-backend skip list | **`StorageIntegration`** shared suite | **Yes** (`memory`, `memory_v2`) |
| Kinto (master) | **Generic storage**: CRUD + `list_all(filters, sorting, pagination)` | **13 abstract methods** | Fixed operator enum | **`StorageTest`** shared suite | **Yes** (`memory.py`) |
| Haystack (docs 3.4) | **`DocumentStore` protocol** + a JSON filter language | **4 core methods** (+ optional by-filter methods) | Per-store operator support "may vary" | **`haystack.testing.document_store`** test classes | **Yes** (`InMemoryDocumentStore`) |
| LlamaIndex (core) | `BasePydanticVectorStore` + `MetadataFilters` | 3 abstract methods | Stores ignore or reject operators **[unverified per store]** | Not seen | Yes (`SimpleVectorStore`) **[unverified name]** |
| LangChain (core) | `VectorStore`; filters per store; `StructuredQuery` IR + per-store `Visitor` | Visitor: 3 methods | `allowed_comparators` / `allowed_operators` → `ValueError` | `VectorStoreIntegrationTests` (filters **not** tested) | Yes (`InMemoryVectorStore`) **[unverified]** |
| FerretDB (v1 → v2) | MongoDB wire protocol over an SQL engine | n/a | v2 dropped SQLite; requires PostgreSQL + DocumentDB | Compatibility tests **[unverified]** | No |
| mongomock | In-memory fake of pymongo | n/a | **Raise `NotImplementedError` rather than diverge** | Tests compared with a real MongoDB | It is one |

Skipped: Gitea, Grafana and Home Assistant. All three follow the SQL-only ORM pattern
(xorm / SQLAlchemy) that Synapse, Mattermost and Airflow already cover. They would not change the
conclusion (my judgement; not checked in detail).

### 1.2 Four shapes of boundary

**A. Full ORM with a dialect/adapter layer** (Django, SQLAlchemy, Ecto, Prisma, MikroORM, TypeORM,
Doctrine ORM). The backend translates a large language. This works well inside one family (SQL to
SQL). Every project that crosses into MongoDB ships a limitations page, and the gaps fall exactly on
this application's hard cases:
- django-mongodb-backend does not support `select_for_update()`.
- Its `JSONField` "cannot distinguish JSON null from SQL null", and filtering for `None` can return
  documents where the field is missing.
- Its `DateTimeField` has no microsecond granularity, and savepoints are unsupported.
- TypeORM gives MongoDB a different API altogether.
- Prisma has no Migrate for MongoDB and no v7 MongoDB support yet. It needs `isSet` to tell unset
  from null.
- MikroORM marks `$ilike`, `$overlap`, `$contains`, `$hasKey`... as PostgreSQL-only.

**B. Named repository methods per use case** (Temporal, Mattermost, Synapse, Keycloak's classic SPI,
Spring Data derived queries). Each new query is a method that every backend implements. This lets a
backend use native strengths (Temporal on Cassandra versus SQL), but the cost is (app queries) ×
(backends). Temporal can pay for that; one owner with agents and about 1000 call sites cannot.

**C. Generic store plus a small declarative filter vocabulary** (Kinto, Haystack, Jaeger's
`TraceQueryParams` + `Filter`, Doctrine `Criteria`, Spring Query-by-Example, LlamaIndex, LangChain).
The backend surface is small, a single meaning is possible, and a shared test suite is natural.
Expressiveness is limited and needs an explicit escape hatch.

**D. Wire-compatible reimplementation** (FerretDB, mongomock, MongoDB-API-on-SQLite libraries). The
application API stays and the engine changes. Fidelity is the whole problem, and both FerretDB (v2)
and the fakes show how hard that is.

This application's profile points to **C**, with B's named methods kept for the few operations whose
atomicity a generic vocabulary cannot express faithfully. That profile is about 1000 call sites,
three backends of two families (document and SQL), a small team, nested JSON data and a need for
concurrency primitives.

---

## 2. Per-project notes (only what bears on the decision)

Sources for each project are listed in §7.

**Django + django-mongodb-backend.** Capabilities are feature flags in
`django/db/backends/base/features.py`: about 160, for example `has_select_for_update_skip_locked`
(default False), `supports_partial_indexes` (True), `supports_json_field` (True) and
`supports_nullable_unique_constraints` (True). That is how flags grow once a large language is
shared. The MongoDB backend (docs v6.1) does not support `extra()`, `prefetch_related()`, `raw()` or
`select_for_update()`. `$expr`-based lookups "often trigger collection scans", pattern lookups work on
string fields only, transactions need a replica set, and nested `atomic` blocks have no effect. The
escape hatch for missing MongoDB features is `Model.objects.raw_aggregate(pipeline)`.

**SQLAlchemy.** The relevant idea is the **dialect compliance suite**. A third-party dialect imports
`sqlalchemy.testing.suite` in a stub `test/test_suite.py` and declares support in a
`Requirements(SuiteRequirements)` class, where each property is `exclusions.open()` or `.closed()`.
The suite is "the primary target for new dialects". Its stated limits: not every test is
dialect-neutral, and maintainers must track it as it grows.

**Spring Data.** Cross-store repositories (`CrudRepository`) with queries derived from method names
(`PartTree`). `Part.Type` has 27 constants, including `BETWEEN`, `IS_NULL`, `IN`, `STARTING_WITH`,
`REGEX`, `EXISTS` and `NEAR`. Query-by-Example documents no nested or grouped constraints and
store-specific string matching. Real work goes through store templates (`MongoTemplate`, JDBC): a
leak by design.

**Doctrine.** ORM (SQL) and ODM (MongoDB) are **separate projects**. They share `doctrine/persistence`
interfaces (`ObjectRepository` with `find`/`findBy`/`findOneBy` **[unverified exact list]**) and
Doctrine Collections' `Criteria`: comparisons `EQ, NEQ, LT, LTE, GT, GTE, IS, IN, NIN, CONTAINS,
MEMBER_OF, STARTS_WITH, ENDS_WITH`, composites `AND, OR, NOT`. The ORM 3.7 docs call Criteria a
limited language that "works both on the SQL and on the PHP collection level". That is the clearest
precedent for one small filter language evaluated both in memory and by the database.

**Ecto 3.14.2.** Few callbacks, large meaning. `Ecto.Adapter.Queryable` has `prepare/2`, `execute/5`
and `stream/5`; `Ecto.Adapter.Schema` has `insert`, `insert_all`, `update`, `delete` and
`autogenerate`. `prepare/2` receives the whole `Ecto.Query`, so each adapter compiles the whole
language. Optimistic concurrency is built in: `update`/`delete` return `{:error, :stale}` when no row
matches. `on_conflict` covers upserts.

**Prisma.** MongoDB support for v7 is "coming"; use v6.19. There is no Migrate for MongoDB ("no
plans"), transactions need a replica set, and a MongoDB-only `isSet` filter separates unset from
null.

**MikroORM 7.2.** MongoDB-style operators (`$eq, $in, $gt, $like, $re, $and, $or, $not`, ...) for SQL
and MongoDB drivers alike. It is the precedent for **MongoDB syntax as the cross-backend filter
language**, and it also shows the risk: some operators are PostgreSQL-only, and the page contradicts
itself on `$contains`.

**Temporal.** `common/persistence/persistence_interface.go` defines 9 store interfaces. Correctness
rests on **fencing values in every write**: `RangeID`/`PreviousRangeID` (shards, task queues),
`Version` (queue metadata, user data) and `Condition`/`DBRecordVersion` (executions). That is
optimistic concurrency used as a lease. SQL backends share `common/persistence/sql/sqlplugin/`
(`mysql/`, `postgresql/`, `sqlite/`, `interfaces.go`). The visibility **List Filter** is a
restricted SQL-like language (`= != > >= < <=`, `AND OR ()`, `BETWEEN`, `IN`, `STARTS_WITH`,
`IS [NOT] NULL`, `ORDER BY`). Each store converts it (`sqlplugin/visibility_query_converter.go` for
SQL), and differences are documented (1 ns on Elasticsearch, 1 µs on SQL). It is a working
user-facing, read-only, cross-backend query language.

**Keycloak.** The generic "map storage" (JPA and Hot Rod layers) was **discontinued in October
2023**, with removal from Keycloak 23. The stated reasons: large remaining work (only
PostgreSQL/CockroachDB, no cache layer, no tree store, no migration strategy, incomplete tests),
uncertainty, and the cost of keeping two storage implementations.

**Matrix Synapse.** Hand-written SQL plus `synapse/storage/engines/_base.py`. `BaseDatabaseEngine` has
the abstract properties `single_threaded`, `supports_using_any_list`, `server_version` and
`row_id_name`, and abstract methods such as `convert_param_style`, `is_deadlock`, `lock_table` and
`executescript`. The docs say SQLite "trades performance for convenience" and "should not be used in
a production server". Leaving it needs the two-phase `synapse_port_db`: snapshot, then a final sync
while stopped.

**Mattermost.** `server/channels/store/sqlstore/store_test.go` has `StoreTest`,
`StoreTestWithSqlStore` and `StoreTestWithSearchTestEngine`, each running one test function for
**every configured store type**: the conformance pattern. Since v11 the only type is PostgreSQL,
because **MySQL support was removed**.

**Airflow 3.3.2.** Multiple schedulers rely on row locks (`SELECT ... FOR UPDATE`, NOWAIT/SKIP LOCKED).
HA is supported only on PostgreSQL 12+ and MySQL 8.0+. MariaDB before 10.6 lacked those clauses and
"deadlock" errors were reported. With `use_row_level_locking = False`, run only one scheduler. The
critical feature is **refused** where it cannot work, not approximated.

**Jaeger v2.** The `Reader` in `internal/storage/v2/api/tracestore/reader.go` has `GetTraces`,
`GetServices`, `GetOperations`, `FindSpans`, `FindTraces`, `FindTraceIDs`, `FindTraceSummaries` and
`SearchCapabilities`. A reader that cannot tell its capabilities returns `errors.ErrUnsupported`. The
query service **refuses** undeclared span queries and page tokens before dispatch, and a reader only
receives a `Filter` whose operators it declared. `internal/storage/integration/integration.go`
(`StorageIntegration`) runs one corpus and fixture set with `Capabilities.SkipList()` across
`memory`, `memory_v2`, `badger`, `cassandra`, `elasticsearch`, `opensearch`, `clickhouse`, `grpc` and
others. Its weak spot is documented too: whether filters must match the same span is
"implementation-dependent".

**Kinto** (Python; the closest precedent). `StorageBase` in `kinto/core/storage/__init__.py` has 13
abstract methods (`initialize_schema`, `create`, `get`, `update`, `delete`, `delete_all`, `list_all`,
`count_all`, `purge_deleted`, `trim_objects`, `resource_timestamp`, ...). Queries use
`Filter(field, value, operator)` and `Sort(field, direction)`, and errors are `UnicityError` and
`ObjectNotFoundError`. The backends are `memory.py` and `postgresql/`. `kinto/core/storage/testing.py`
defines `StorageTest` ("Compound of all storage tests"), which **pins down meaning**:
- `EQ None` matches only explicit `None`, and `HAS False` only missing fields.
- No implicit casting (`test_list_all_does_not_implicitly_cast`).
- Sort order and range filters partition the same order, missing included.
- An empty `IN` returns nothing.

**Haystack.** The `DocumentStore` protocol (`haystack/document_stores/types/protocol.py`) has
`count_documents`, `filter_documents(filters)`, `write_documents(documents, policy)` and
`delete_documents(ids)`. `DuplicatePolicy` is `NONE/SKIP/OVERWRITE/FAIL`, where `FAIL` raises
`DuplicateError`. Filters are JSON dicts with `== != > >= < <= in not in` and `AND OR NOT`.
`haystack/testing/document_store.py` provides `CountDocumentsTest`, `WriteDocumentsTest`,
`DeleteDocumentsTest` and `FilterDocumentsTest`, which each integration subclasses with its own
`document_store` fixture. Tested edge cases: ordering comparisons with `None` give no results, with a
string or list they raise `FilterError`, and malformed filters raise. `InMemoryDocumentStore` filters
through `haystack.utils.filters.document_matches_filter`, and its embedding ties keep **storage
iteration order** (a stable `sorted`): an accident of the fake. The docs still say operators "may
vary" per store.

**LlamaIndex / LangChain.** LlamaIndex `MetadataFilters` has 14 operators (`EQ, GT, LT, NE, GTE, LTE,
IN, NIN, ANY, ALL, TEXT_MATCH, TEXT_MATCH_INSENSITIVE, CONTAINS, IS_EMPTY`) and `AND/OR/NOT`.
LangChain's `StructuredQuery` IR has 10 comparators and 3 operators. Each store's `Visitor` lists
`allowed_comparators`, and anything else raises `ValueError`: explicit, not approximate. But
`VectorStoreIntegrationTests` **does not test filters**, so the shared syntax has no shared meaning.

**FerretDB.** v1 offered PostgreSQL and SQLite. v2 "requires a PostgreSQL with DocumentDB extension".

**mongomock.** It aims at "a reasonably complete mock ... not a perfect replica". Behaving differently
from pymongo is "unacceptable": unsupported features raise `NotImplementedError`. Tests are compared
against a real MongoDB through docker-compose.

---

## 3. Failure modes and lessons

1. **Every extra backend is a permanent tax, and projects shed backends.** Mattermost removed MySQL
   (v11), FerretDB dropped SQLite (v2), Keycloak abandoned a second storage implementation because
   keeping two complicated maintenance, and Synapse calls SQLite unfit for production. *Lesson:* keep
   the backend-facing surface small enough that a backend costs days, not months. Be ready to drop
   one.
2. **SQL-first ORMs leak exactly where this application is hard.** Over MongoDB the gaps cluster on
   row locking (no `select_for_update` in django-mongodb-backend), transactions (replica set needed,
   no savepoints), null versus missing (Django's `JSONField`, Prisma's `isSet`), time precision (Django
   loses microseconds) and migrations (no Prisma Migrate). *Lesson:* do not inherit an SQL ORM's
   meaning and patch MongoDB under it.
3. **A common syntax is not a common meaning.** Haystack and LlamaIndex share operator names but
   support "may vary" per store. Jaeger leaves same-span matching "implementation-dependent", and
   LangChain's standard tests skip filters. *Lesson:* write the semantics once (table plus reference
   evaluator) and make every backend pass the same tests, as Kinto's `StorageTest` does.
4. **Fakes drift.** *Software Engineering at Google*, ch. 13 (Test Doubles), says a fake needs
   fidelity "from the perspective of the test", needs its own contract tests run against both the
   fake and the real implementation, and is best owned by whoever owns the real one. mongomock's rule
   is to raise, never diverge. Haystack's in-memory tie order shows a fake quietly defining behaviour
   that no real store shares. *Lesson:* the in-memory backend must be the **reference** that real
   backends are tested against, not a mock written after them.
5. **Capability flags multiply.** Django has about 160. Jaeger shows the better form: few
   capabilities, declared by the backend, and **enforced before dispatch**, so an unsupported request
   fails loudly. Ibis tags each backend test as `notimpl` (work to do), `notyet` (the engine may add
   it) or `never` (the engine cannot), per its PyCon 2024 talk "Test 20 databases on every commit".
   *Lesson:* keep flags to a handful. Anything else is required of every backend.
6. **A larger language means a larger backend.** Ecto adapters and Django backends compile an entire
   query language. Temporal keeps one converter per store for a deliberately small language.
   *Lesson:* choose the smallest vocabulary that covers the call sites, plus explicit escape
   hatches.
7. **Database-specific traps that silently change results.** Each must be pinned by a conformance
   test.

   | Trap | Detail | Checked |
   |---|---|---|
   | MongoDB `{f: null}` | Matches null *and* missing (`$type: 10` for null only, `$exists: false` for missing) | [query-for-null-fields](https://www.mongodb.com/docs/manual/tutorial/query-for-null-fields/) |
   | MongoDB equality on an array | Matches any element (implicit traversal) | **[unverified today]** |
   | Unique index, missing field | MongoDB indexes missing as null, so only one record may lack the field; SQL allows many NULLs; a partial filter changes this (§4.3) | **[unverified today]** |
   | SQL three-valued logic | `NOT (x > 5)` drops NULL rows; MongoDB `$not`/`$ne` match missing | **[unverified today]** |
   | String collation | MongoDB and SQLite compare code points; PostgreSQL uses the database collation unless `COLLATE "C"` | **[unverified today]** |
   | SQLite `LIKE` | Case-insensitive for ASCII by default (use `GLOB` or ranges) | **[unverified today]** |
   | SQLite `REGEXP` | No `regexp()` function by default; needs a user function | **[unverified today]** |
   | NULL sort order | SQLite: NULL smallest; PostgreSQL: NULLs last ascending unless `NULLS FIRST` | **[unverified today]** |
   | SQLite `RETURNING` | Row order arbitrary, not controlled by `ORDER BY` | [lang_returning](https://www.sqlite.org/lang_returning.html) |
   | Time precision | BSON ms, PostgreSQL µs; Temporal documents 1 µs against 1 ns between its stores | docs above |
8. **Migrating a large code base.** Synapse's `synapse_port_db` is two-phase (snapshot copy while
   running, final sync while stopped), and Mattermost publishes a guide for leaving MySQL. *Lesson:*
   move collection by collection while the old backend stays live, and move data with a resumable
   copy tool built on the same port.

---

## 4. The hard cases

### 4.1 Atomic claim of the next work item (several processes)

| Backend | Established method |
|---|---|
| PostgreSQL | `UPDATE q SET ... WHERE id = (SELECT id FROM q WHERE state='pending' ORDER BY ... LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *`. PostgreSQL 18 docs: SKIP LOCKED "can be used to avoid lock contention with multiple consumers accessing a queue-like table" (and gives an inconsistent view, which a queue accepts). https://www.postgresql.org/docs/current/sql-select.html |
| MongoDB | `findOneAndUpdate(filter, update, sort, returnDocument=after)`. It is atomic on the single document **[unverified today]**. That each concurrent claimer gets a *different* document is what the integration test must show. |
| SQLite | One writer at a time: `BEGIN IMMEDIATE; UPDATE ... WHERE id = (SELECT id ... ORDER BY ... LIMIT 1) RETURNING *; COMMIT;` with a busy timeout. `RETURNING` needs SQLite ≥ 3.35.0 and not virtual tables. https://www.sqlite.org/lang_returning.html |
| In-memory | A lock around select-then-update. It is single-process by nature, so cross-process safety is proven only in integration. |

Airflow shows the policy for a backend that cannot do this safely: **refuse** (no multi-scheduler on
old MariaDB), do not approximate. In the port this is one named primitive, `find_one_and_update` with
a sort, because "find then update" assembled from generic calls is not atomic on any backend.

### 4.2 Leases with expiry on one shared clock

**The clock must be read inside the write.** MongoDB: `$$NOW` in `$expr` filters and pipeline-style
updates (4.2+) **[unverified today]**. PostgreSQL: `now()` or `clock_timestamp()`. SQLite:
`strftime('%Y-%m-%dT%H:%M:%fZ','now')`; with SQLite "the server clock" is the host's OS clock, shared
by every process on that host. In-memory: an injectable clock that tests control. In the port this is
a value placeholder `Now()` (optionally `Now() + duration`), allowed in filter and update values and
evaluated by the backend in the same statement; `store.now()` reads it for display.

**Leases need fencing.** Expiry alone cannot stop a paused holder from writing after its lease
expired (Kleppmann, "How to do distributed locking", 2016 **[not re-read today]**). Temporal makes
every write carry `RangeID` or `Version`, and the store rejects stale ones. The port gets this for free
when a lease holder makes later writes with `expected_rev` (§4.4).

### 4.3 Unique constraints, including partial ones

PostgreSQL: `CREATE UNIQUE INDEX ... WHERE <predicate>`. SQLite: partial indexes (since 3.8.0
**[unverified today]**). MongoDB (manual 9.0): `partialFilterExpression` supports only equality,
`$exists: true` (**not** `false`), `$gt/$gte/$lt/$lte`, `$type`, `$and`, `$or`, `$in` and geo
operators. `$ne` and `$exists: false` are unsupported, and uniqueness applies only to documents that
match the filter.

**Definition for the port.** A unique index applies only to records where every indexed field is
present **with a value of its declared type**, intersected with an optional partial predicate. The
predicate is limited to the subset all three backends support (the MongoDB list above). On MongoDB the
backend adds `{f: {$type: <declared>}}` per field to `partialFilterExpression`. That removes the "one
missing allowed" difference, because records without the field are outside the index. On SQL it adds
the matching `json_type(...)`/`jsonb_typeof(...)` predicate. A duplicate raises one
`DuplicateKey(collection, index, key)`, mapped from MongoDB E11000, `sqlite3.IntegrityError` ("UNIQUE
constraint failed") and PostgreSQL SQLSTATE 23505 **[codes from memory]**.

### 4.4 Optimistic concurrency

All mature designs carry a version in the write's condition:
- Ecto: `{:error, :stale}`.
- Temporal: `PrevRangeID`, `Version`, `DBRecordVersion`.
- Kinto: `last_modified` timestamps.
- Spring Data: `@Version` with an optimistic-locking exception **[unverified today]**.

Port: every record carries a store-managed integer `_rev`, incremented by every write the port
performs. `replace`/`update`/`delete` accept `expected_rev`. The backend adds `_rev == n` to the
filter, and zero matches with the record present raises `StaleRevision`. This works identically on
all backends: it is just a filter and an `$inc`.

### 4.5 Vector similarity search with filters and ties

| Backend | Exact | Approximate | Filter | Ties |
|---|---|---|---|---|
| MongoDB `$vectorSearch` | `exact: true` (ENN) | HNSW; `numCandidates` (docs: about 20× `limit`; recall typically about 90–95% of ENN) | Pre-filter `filter` (`$eq`, `$in`, `$and` shown; full list and the "filter-type index field" rule **[unverified]**) | Not defined. Score is normalized: cosine `(1+cos)/2` in [0,1]. Self-managed: Community/Enterprise 8.2+ through the separate `mongot` binary, public preview in Sept 2025, **Linux only (not Windows/macOS) at preview**; current status **[unverified]** |
| PostgreSQL + pgvector 0.8.7 | No index = exact, "perfect recall" | HNSW / IVFFlat | Post-filter, so it can return **fewer than k**; `hnsw.iterative_scan = strict_order / relaxed_order` (0.8.0+) | Not defined; strict order regained by re-ordering in a materialized CTE |
| SQLite + sqlite-vec (docs v0.1.10-alpha.4) | `vec0` KNN (`MATCH ... AND k = ?`), or a manual brute force with `vec_distance_cosine()` ... `ORDER BY distance` | Not offered | `vec0` metadata columns: only `= != > >= < <=` (no `IN`; booleans only `= !=`), at most 16 columns; partition keys | Not defined |
| Haystack in-memory | Exact | n/a | Shared filter function | Storage iteration order (accidental) |

Sources: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/,
https://www.mongodb.com/products/updates/mongodb-8-2-is-now-available/ (8.2 announcement via search),
https://github.com/pgvector/pgvector, https://alexgarcia.xyz/sqlite-vec/features/knn.html,
https://alexgarcia.xyz/sqlite-vec/features/vec0.html

No surveyed system defines ties. Definition for the port:

- **Score** is raw cosine similarity in [-1, 1]. The MongoDB backend converts `2*s - 1`.
- **Exact mode** returns the top k by `(score desc, _id asc)` among records that match the filter and
  have the vector field.
  - On SQL that is literally `ORDER BY distance, id LIMIT k` over a plain scan, which is deterministic.
  - On MongoDB, ask for `k + m` with `exact: true`, re-sort by `(score, _id)` in the port, and widen
    while the last fetched score equals the k-th. The tie window is then complete.
- **Approximate mode** promises less:
  - Every returned record matches the filter.
  - Results are ordered by `(score desc, _id asc)`.
  - It **may return fewer than k and may miss true neighbours**.
  - Exact results are valid approximate results, so in-memory and SQLite may answer approximate
    queries exactly.
- **Floating point**: real stores score in float32 (pgvector `vector` and sqlite-vec `float[]`;
  MongoDB's internal precision **[unverified]**), and Python may score in float64. Scores within about
  1e-6 may order differently across backends. This is stated as a documented tolerance, not left
  silent. Conformance tests use identical vectors to build real ties (equal on every backend) and
  well-separated vectors otherwise. Approximate mode is tested by ordering, filter correctness and a
  recall floor on a fixed corpus.
- **Filters**: allow only the subset every vector backend can pre-filter (`= != < <= > >=`, `$in`
  expanded to `$or` for sqlite-vec). Anything else raises `NotSupported`. Do not post-filter
  silently, because that is pgvector's "fewer than k" trap.

### 4.6 A safe ad-hoc read path for an AI agent

Precedents: **Temporal's List Filter** (a parsed, restricted language, translated per store,
read-only by construction); **Haystack's JSON filters** (validated, `FilterError` on malformed input);
**Datasette's arbitrary SQL on SQLite** (read-only/immutable connections, a 1 s default time limit
enforced with `set_progress_handler`, `max_returned_rows` default 1000, `PRAGMA` blocked; settings
docs plus Simon Willison's SQLite forum post, found via search). Python's `sqlite3` documents both
pieces: a non-zero return from the progress handler "will terminate the currently executing query",
and `file:...?mode=ro` with `uri=True` opens read-only.

Raw SQL or MongoDB pipelines are not portable, so the agent speaks **the port's own JSON query form**
through a separate **read-only facade**:
- Only `find`, `count`, `aggregate` and `vector_search` exist there, so writes are absent by
  construction.
- Collections are allowlisted, only declared fields may be named, and `limit` (for example ≤ 200),
  tree depth and size are capped.
- Each backend enforces a time limit: MongoDB `maxTimeMS`; PostgreSQL `SET LOCAL statement_timeout`
  in a `READ ONLY` transaction; SQLite a progress handler on a `mode=ro` connection. Read-only
  credentials are used where the backend has accounts.

The same tree and conformance suite back it, so the agent's query means the same on every backend.

### 4.7 Index and schema setup, migrations, time values

- **Schema.** Each collection declares its *queryable* fields (path; kind
  `str|int|float|bool|datetime|list[...]|object|vector(n)`; nullable), its indexes (fields, unique,
  partial predicate) and its vector index. Undeclared fields are stored and returned but cannot be
  queried, sorted or indexed. `ensure_schema()` is idempotent: MongoDB `createIndex`; SQL
  `CREATE TABLE coll(id TEXT PRIMARY KEY, rev INTEGER, doc JSON)` plus expression indexes on declared
  fields. Writes are validated against declared kinds **once, in the shared layer**. That is what lets
  MongoDB's native equality and comparison semantics coincide with the definition (§5.3).
- **Migrations.** An ordered list of migration functions written *against the port*, so they are
  backend-agnostic, with applied ones recorded in a `_migrations` collection (as in Django/Alembic).
  Copying data between backends is one resumable tool on the port: iterate by `_id`, write to the
  target, re-run for a final sync (the Synapse pattern).
- **Time.** Timezone-aware UTC only (naive datetimes rejected) at **millisecond** precision, which is
  BSON's resolution; the port truncates. SQLite stores a fixed-width ISO-8601 string
  (`YYYY-MM-DDTHH:MM:SS.mmmZ`), whose lexical order equals time order; PostgreSQL uses `timestamptz`
  or the same string in jsonb; the in-memory backend uses `datetime`.

---

## 5. Recommendation

### 5.1 Boundary

Two layers:

1. **Backend-facing port** (implemented three times, plus in-memory): a generic document store.
   It knows collections, records, the query and update trees, and four named primitives. It knows
   nothing about the application's domain.
2. **Application-facing collection modules** (written once, backend-independent): thin named
   functions per collection (`claim_next_job()`, `memories_for(person)`). They are built on the port
   wherever call sites cluster, so application code reads well. These cost nothing per backend. This
   is Spring Data's split: repositories above, store template below.

Not an ORM: no unit of work, identity map or relations. Not raw passthrough: no backend query objects
cross the port. Not one interface per use case: Temporal's way costs (queries × backends).

### 5.2 The backend-facing interface (about 13 methods)

```
get(coll, id) -> Record | None
find(coll, filter, *, sort=(), skip=0, limit=None, fields=None) -> list[Record]
count(coll, filter) -> int
aggregate(coll, filter, *, group_by: list[field], metrics: {name: Count|Sum|Min|Max|Avg(field)},
          sort=(), limit=None) -> list[dict]
insert(coll, record) -> Record                        # DuplicateKey
replace(coll, record, *, expected_rev=None, upsert=False) -> Record   # StaleRevision, DuplicateKey
update(coll, filter, update, *, many=False, upsert=False, expected_rev=None) -> UpdateResult
find_one_and_update(coll, filter, update, *, sort=(), upsert=False, return_new=True) -> Record | None
delete(coll, filter, *, many=False, expected_rev=None) -> int
bulk(coll, ops, *, ordered=True) -> BulkResult        # independent ops, not atomic
vector_search(coll, field, vector, k, *, filter=None, mode=EXACT|APPROX) -> list[(Record, score)]
ensure_schema(spec) / now() -> datetime / capabilities -> frozenset[str]
```

Defined once:
- `sort` always ends with `_id asc`, so pagination and ties are deterministic.
- Upsert is allowed only when the filter is equality on `_id` or on the fields of a declared unique
  index. Otherwise it raises: this avoids MongoDB's documented duplicate-upsert race and SQL's need
  for an `ON CONFLICT` target.
- `bulk` runs ops in order. On the first failure, earlier ops stay applied and later ones are not
  run, and the result names the failing index. This is MongoDB's "ordered" behaviour, which SQL
  backends reproduce instead of being silently stronger.
- **No general multi-record transactions** in the port. The requirements do not need them, and
  MongoDB transactions need a replica set (django-mongodb-backend and Prisma both say so). If a need
  appears, add a named primitive for it.
- `capabilities` holds at most a handful of flags (for example `vector.approx`,
  `vector.filter.ne`). Anything not listed is **required** of every backend. An unsupported request
  raises `NotSupported` before touching the database (the Jaeger model).

### 5.3 The query vocabulary

- **Filter operators**: `$eq $ne $gt $gte $lt $lte $in $nin $exists $type:null`, prefix (an anchored
  literal `^...`), restricted `$regex`, list `$all`/element equality on list fields, `$and $or $not
  $nor`.
- **Update operators**: `$set $unset $inc $push $setOnInsert`.
- **"Matches any of these (a, b) pairs"** is `$or` of `$and` pairs, built by a helper. SQL backends may
  compile it to `(a,b) IN (VALUES ...)` (row values: SQLite ≥ 3.15 **[unverified today]**).

Why this syntax: it is MongoDB's, so existing pymongo call sites move mechanically. Agents and LLMs
already know it, and MikroORM uses the same idea over SQL. Why this is safe: a **strict parser**
accepts only forms whose MongoDB meaning equals the port's definition, given declared fields and
validated writes.
- **Equality with `null`** (MongoDB: null *or* missing) is rejected. Write `{"$type":"null"}` for
  null or `{"$exists":false}` for missing.
- **`null` inside `$in`** is rejected.
- **`$eq` on a field declared as a list** is rejected; use `$all`/element match. On scalar-declared
  fields arrays cannot exist, so MongoDB's implicit array traversal never applies.
- **Ordering comparisons** require a literal of the field's declared kind (the Haystack `FilterError`
  rule). Stored values are validated on write, so there is no cross-type comparison (Kinto's "does not
  implicitly cast").
- **Logic is two-valued**: a missing field makes a comparison false, and `$not`/`$ne`/`$nin` are set
  complements, so they match missing. That is MongoDB's behaviour. SQL backends must compile `NOT`
  and `<>` as `COALESCE(<cond>, FALSE)` complements, never bare three-valued `NOT`.
- **Sort**: missing and null sort together before all values ascending (after them descending), then
  `_id`. PostgreSQL needs explicit `NULLS FIRST/LAST`.
- **Strings**: compare by code point; PostgreSQL expressions need `COLLATE "C"`. Prefix uses ranges or
  `GLOB` on SQLite, never `LIKE`.
- **`$regex`**: a validated subset (literals, `. [] * + ? ^ $ |` and groups, flag `i`; no
  backreferences, lookaround or `\d\w\s`). Python `re`, PCRE and PostgreSQL's AREs agree on that
  subset. SQLite registers Python `re` as `regexp()`.

Consequences:
- The **MongoDB backend is almost a passthrough** of the validated dict, plus `$type` guards for
  partial unique indexes, `Now` and `_rev`. That is the lowest translation risk on the backend that
  is live today.
- The **SQLite backend is the real compiler**: JSON path extraction, typed expression indexes and
  complement logic.
- The **in-memory backend is a direct evaluator** of the semantics table.

Escape hatch: no backend-native queries in application code. A need the vocabulary cannot express
becomes an app-facing function written with port calls plus Python-side processing (data here is
small). If that is too slow, it becomes a new named port method that all backends implement and the
conformance suite covers.

### 5.4 Proving faithfulness

1. **Semantics table** (one page) plus the **in-memory backend as reference**. Each rule in the table
   names the conformance test that pins it.
2. **One conformance suite**: pytest classes parameterized by a `store` fixture, the Kinto
   `StorageTest`, Haystack `FilterDocumentsTest`, SQLAlchemy `testing.suite`, Jaeger
   `StorageIntegration` and Mattermost `StoreTest` pattern.
   - Unit runs use only the in-memory backend.
   - The hand-run integration suite runs the **same classes** against each real backend on a
     throwaway database of synthetic records, dropped afterwards.
   - Per-backend gaps are explicit markers with a reason (Ibis's `notimpl`/`notyet`/`never`), and the
     target is zero markers outside `capabilities`.
3. **Differential test** in the integration suite. Hypothesis generates small record sets, including
   missing, null, empty lists, mixed kinds within declared rules, equal sort keys and equal vectors,
   plus random valid filter trees. Each real backend's result must equal the reference's, with a
   fixed seed and a bounded size so the server sees no load. This is my addition. The technique is
   established (Hypothesis; SQLancer's differential testing of database engines **[not re-read
   today]**), but none of the surveyed projects ships it for their storage abstraction, so treat it as
   a proposal.
4. **Concurrency tests** (integration only): N processes claim from one queue (no item claimed twice,
   none lost); two holders race for an expired lease (one wins, the loser's later `expected_rev`
   write fails).
5. **mongomock's rule** is project law: a backend that cannot do something raises `NotSupported`,
   never approximates.

### 5.5 Migrating about 1000 call sites

Work collection by collection while MongoDB stays the production backend (strangler pattern):
declare the collection's fields and indexes, move its call sites (pymongo dicts mostly carry over
unchanged), and run its tests on the in-memory backend. Every place the strict parser rejects is a
place that silently relied on MongoDB-only meaning; fix it explicitly. Once a collection is migrated,
a static check (an AST or grep test) forbids importing `pymongo` outside the MongoDB backend.
Aggregation pipelines in application code are inventoried: most become `aggregate(group_by,
metrics)`, the rest app-facing functions. SQLite becomes usable when all 36 collections are on the
port, and the data moves with the resumable copy tool. Rough size, **an estimate, not a measurement**:
in-memory reference 600–900 lines, MongoDB backend 400–600, SQLite compiler 1000–1500, conformance
suite 1500–2500.

### 5.6 What you pay for this choice

- **A home-made IR.** Its syntax is borrowed (the MongoDB subset), and its test pattern is
  established (Kinto, Haystack, SQLAlchemy). The semantics table is the invented part, and it must
  stay short.
- **SQLite performance** depends on expression indexes over JSON paths. Regex and approximate
  vectors are scans; that is acceptable at personal-assistant scale but should be measured in the
  integration suite.
- **Friction at migration**: the strict parser will reject code that works today. That friction is
  the point.
- **MongoDB self-managed vector search** runs through `mongot`, Linux-only at its 2025 preview. If
  production is Windows, exact search on MongoDB may need a brute-force fallback in the backend.
  Check current status before relying on it.

### 5.7 The strongest alternative, and why it loses here

**SQLAlchemy Core (with Alembic) on SQLite and PostgreSQL, retiring MongoDB as part of the move.**

Its strengths: it is mature (transactions, `FOR UPDATE SKIP LOCKED` on PostgreSQL, partial indexes,
migrations), SQLite `:memory:` is a real engine in tests, and the agent could get read-only SQL the
Datasette way. Why it loses for this application:
- **No MongoDB dialect.** Nothing is gained until a big-bang data move, or the code carries two
  storage paths during the transition. The port keeps MongoDB live and moves one collection at a
  time.
- **It defines SQL, not meaning.** The 36 collections of nested, optional and list-valued data end up
  in JSON columns, where missing versus null, array membership, type mixing, sort order of NULLs and
  collation are again the application's problem. SQLAlchemy's JSON type does not settle them, and
  SQLite and PostgreSQL disagree on several (§3.7).
- **Its test double is SQLite.** That is faithful to SQLite, not to PostgreSQL. Synapse and Airflow
  both treat SQLite as development-only.
- **The agent's raw SQL would be dialect-specific**, not "the same on every backend".

It would win if the owner decided MongoDB goes away now and PostgreSQL never comes. With a single SQL
backend, the cheapest design is SQLAlchemy Core and no port at all. Under the stated goals (MongoDB
now, SQLite next, PostgreSQL perhaps) the port is cheaper overall.

Also rejected:
- **Django ORM + django-mongodb-backend**: a heavy framework for a worker. Its MongoDB gaps sit on
  this application's hard cases (no `select_for_update`, JSON null ambiguity, no savepoints), and it
  has no cross-backend vector search.
- **FerretDB** (keep pymongo, swap the server): v2 needs PostgreSQL + DocumentDB, has no SQLite, and
  gives no in-memory unit tests.
- **MongoDB-API-on-SQLite libraries** (for example montydb or mongita): small projects of unknown
  fidelity **[not examined]**.

---

## 6. Not verified (collected)

- MongoDB: array-equality traversal, unique index treatment of missing fields, `$not`/`$ne` matching
  missing fields, `$$NOW` in `$expr` and in pipeline updates (and their index use),
  `findOneAndUpdate` handing distinct documents to concurrent claimers, `$vectorSearch` filter
  operator list and the filter-type index requirement, internal vector precision, whether
  self-managed search has left preview and supports Windows.
- SQLite: no `regexp()` by default, case-insensitive ASCII `LIKE`, NULLs smallest in sort, partial
  index version 3.8.0, row values 3.15.
- PostgreSQL: NULLS LAST default for ascending, default collation for string comparison inside
  expressions, SQLSTATE 23505.
- Doctrine `ObjectRepository` method list; Spring Data KeyValue's in-memory query internals and
  `@Version` exception name; Ecto adapters' behaviour on unsupported query parts; Temporal's
  per-backend test runner layout; LlamaIndex and LangChain in-memory class names.
- Kleppmann (2016, https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) and
  SQLancer were cited from memory, not re-read.
- The code-size estimates in §5.5 are estimates.

## 7. Sources (read 2026-10-28)

- django-mongodb-backend limitations (docs 6.1): https://www.mongodb.com/docs/languages/python/django-mongodb/current/limitations-upcoming/
- Django `BaseDatabaseFeatures`: https://github.com/django/django/blob/main/django/db/backends/base/features.py
- SQLAlchemy dialect suite: https://github.com/sqlalchemy/sqlalchemy/blob/main/README.dialects.rst
- Spring Data `Part.Type` (Core API 4.1.0): https://docs.spring.io/spring-data/commons/docs/current/api/org/springframework/data/repository/query/parser/Part.Type.html
- Spring Data Query by Example: https://docs.spring.io/spring-data/data-commons/reference/4.1-SNAPSHOT/query-by-example.html
- Spring Data KeyValue 4.1.2: https://docs.spring.io/spring-data/keyvalue/reference/
- Doctrine Collections 3.1 expressions: https://www.doctrine-project.org/projects/doctrine-collections/en/stable/expressions.html
- Doctrine ORM 3.7 filtering collections: https://www.doctrine-project.org/projects/doctrine-orm/en/current/reference/working-with-associations.html
- Ecto 3.14.2: https://ecto.hexdocs.pm/Ecto.Adapter.html, https://ecto.hexdocs.pm/Ecto.Adapter.Queryable.html, https://ecto.hexdocs.pm/Ecto.Adapter.Schema.html
- Prisma MongoDB: https://www.prisma.io/docs/orm/overview/databases/mongodb
- MikroORM 7.2 query conditions: https://mikro-orm.io/docs/query-conditions
- TypeORM MongoDB: https://typeorm.io/docs/drivers/mongodb/
- Temporal: https://github.com/temporalio/temporal/blob/main/common/persistence/persistence_interface.go, https://github.com/temporalio/temporal/tree/main/common/persistence/sql/sqlplugin, https://github.com/temporalio/temporal/tree/main/common/persistence/persistence-tests, https://docs.temporal.io/list-filter, https://docs.temporal.io/self-hosted-guide/visibility
- Keycloak map store removal: https://www.keycloak.org/2023/10/map-store-removal
- Synapse: https://github.com/element-hq/synapse/blob/develop/synapse/storage/engines/_base.py, https://element-hq.github.io/synapse/latest/setup/installation.html, https://element-hq.github.io/synapse/latest/postgres.html
- Mattermost: https://github.com/mattermost/mattermost/blob/master/server/channels/store/sqlstore/store_test.go, https://docs.mattermost.com/product-overview/mattermost-v11-changelog.html
- Airflow 3.3.2 scheduler: https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/scheduler.html
- Jaeger: https://github.com/jaegertracing/jaeger/blob/main/internal/storage/v2/api/tracestore/reader.go, https://github.com/jaegertracing/jaeger/blob/main/internal/storage/integration/integration.go
- Kinto: https://github.com/Kinto/kinto/blob/master/kinto/core/storage/__init__.py, https://github.com/Kinto/kinto/blob/master/kinto/core/storage/testing.py
- Haystack: https://docs.haystack.deepset.ai/docs/metadata-filtering, https://github.com/deepset-ai/haystack/blob/main/haystack/document_stores/types/protocol.py, https://github.com/deepset-ai/haystack/blob/main/haystack/testing/document_store.py, https://github.com/deepset-ai/haystack/blob/main/haystack/document_stores/in_memory/document_store.py
- LlamaIndex: https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/vector_stores/types.py
- LangChain: https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/structured_query.py, https://github.com/langchain-ai/langchain/blob/master/libs/standard-tests/langchain_tests/integration_tests/vectorstores.py
- Ibis test markers (PyCon 2024): https://ibis-project.org/presentations/pycon2024/maintainers
- FerretDB v1→v2: https://docs.ferretdb.io/migration/migrating-from-v1
- mongomock: https://github.com/mongomock/mongomock
- Software Engineering at Google, ch. 13: https://abseil.io/resources/swe-book/html/ch13.html
- MongoDB: https://www.mongodb.com/docs/manual/core/index-partial/, https://www.mongodb.com/docs/manual/tutorial/query-for-null-fields/, https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/, https://www.mongodb.com/products/updates/mongodb-8-2-is-now-available/
- pgvector 0.8.7: https://github.com/pgvector/pgvector
- sqlite-vec: https://alexgarcia.xyz/sqlite-vec/features/knn.html, https://alexgarcia.xyz/sqlite-vec/features/vec0.html
- SQLite RETURNING: https://www.sqlite.org/lang_returning.html
- PostgreSQL 18 SELECT (SKIP LOCKED): https://www.postgresql.org/docs/current/sql-select.html
- Python sqlite3: https://docs.python.org/3/library/sqlite3.html
- Datasette settings: https://docs.datasette.io/en/stable/settings.html
