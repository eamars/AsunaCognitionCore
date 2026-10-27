# ADR-104: Database connector

Status: decided with the owner 2026-10-28 (below). Third in the owner's order (102, 103, 104). The vector interface
is designed (section "Vector search", Claude on the owner's delegation) and built as step 1 of 4 (see "Build order"
and "Built"), not installed. The record interface (step 2) is not designed yet.

## The owner's ask (2026-10-27, verbatim)

> The next task will be similar to the code cleanup, that I want to breakout the database connector from the Asuna
> package, similar to QQBot and Napcap adapter, that I want the capability for other users to connect to different
> database. The database connector interface should be designed to accommodate future expansion. I would like to
> discuss more about this when your current job is done.

## What exists today (counted in the code on 2026-10-27)

- The Python worker reaches MongoDB through `Store` (`src/asuna/state.py`: `put`, `audit`, `authorize`, and its
  `db`), but most code goes to the collections directly: `store.db.<collection>` appears 912 times in 77 files of
  `src/asuna/`.
- Its own clients besides the store: `src/asuna/dbread.py`, `host_lease.py`, `testing.py`, and in `tools/`
  `cleanup_test_databases.py` and `probe_qq_admission.py`.
- MongoDB features in use: `aggregate` (7 uses); vector search in `retrieval.py` (`$vectorSearch` over a
  `vectorSearch` search index it creates on `memory_units` with `SearchIndexModel`; the server log shows
  `__mdb_internal_search`); `$jsonSchema` validators (`state.py`); update pipelines with `$expr` and `$$NOW` (the
  lease, ADR-020). The server runs as a replica set (it keeps an oplog). No change streams, no multi-document
  transactions.
- The JS plugin never talks to MongoDB.
- Pinned: `pymongo==4.16.0`; tests use `mongomock==4.3.0`.

## Requirements as asked

1. The database connector is its own package, beside the core, as the QQ Bot and NapCat adapters are.
2. Another user can connect a different database.
3. The connector interface accommodates future expansion.
4. "Similar to the code cleanup".
5. **Unit tests stop at the adapter** (the owner, 2026-10-27, on hearing that the suite runs about 1,500 tests
   against the MongoDB server her live data is on): "I object the idea of using the real DB test from its root.
   Perhaps add 'stop using real db for unit test' ... when the DB adapter interface is built, and the unit test stop
   at the DB adapter." Unit tests use a double of the interface, never a database server; the adapter's own tests
   are the only ones that reach a database, and never the server a live deployment uses.
6. **The suite is cleaned up with it** (the owner, 2026-10-27): "Fundamentally having unit tests to run for 10
   minutes is absurd, and that needed to be fixed. ... Perhaps with ADR-104 we need to start cleaning up, and
   removing unit tests serving no purposes as well. Adding unit test is NOT a good habit." Today: about 1,500 Python
   tests, 9 to 16 minutes a run on this machine. Which tests earn their place, and how the slow ones are found, is
   part of the design.
   Later the same night: "at some stage we need a total reset, that old test must gone, and tests with duplicated
   coverage should be gone. I understand the unit test is to protect you from writing the good code so I won't ask
   you to remote all unit. But this isn't the excuse of adding more and more unit test without considering 'do i need
   them?'."

## Decided with the owner (2026-10-28)

1. **MongoDB and a test double.** The first version builds the interface, the MongoDB adapter (today's behaviour)
   and an in-memory double the unit tests use (requirement 5). A second real database is written when a user needs
   one; the double shows the interface is not MongoDB-only.
2. **The core's own operations.** The interface is defined from what the core does (store a record, read by id, find
   by fields, update, count, append to a log, ...), not as a MongoDB-shaped subset; every call site moves to it,
   module by module, behind the MongoDB adapter, with nothing changing for her between steps.
3. **Retrieval is to be researched first.** The owner: "I need you to research and define the common vector
   interface for commonly used databases. You don't need to do it now, but later before running the ADR, and present
   the option to me."
   Later the same night: "If ADR-104 is trivial, or the interface is deterministic then you should design the
   interface yourself. ... I'd expect you don't need complicated interface, as the embedding and cosine similarity
   can be hidden behind the abstracted interface." Designed in section "Vector search" below.
4. **The model is the channel packages:** its own package folder and tests, a module the core loads by
   configuration, the core naming no database.

5. **Step 2's record interface is a small query vocabulary the core defines** (the owner, 2026-10-28, in the question
   tool, Claude's recommendation): get, find, count, update and delete by fields (equals, any of, not, ranges, exists,
   starts with, contains, and/or, nested fields; sort, limit, the fields returned); named operations only for counters
   and the few aggregates. Each adapter translates it. Not chosen: a named operation per use (hundreds of methods).
   Counted for it on 2026-10-28: about 1,000 direct collection calls in 81 files of `src/asuna/` (`find_one` 624,
   `find` 254, `update_one` 38, `count_documents` 32, the rest under 15 each).
6. **Her read tool speaks that vocabulary** (the owner, 2026-10-28, Claude's recommendation): `dbread`, which her task
   scripts and skills use with MongoDB's query syntax today, takes the core's vocabulary and so works on any database;
   she rewrites her own scripts and skills, her way. Not chosen: translating MongoDB syntax in every adapter (the
   MongoDB-shaped surface decision 2 ruled out), or the tool on MongoDB only.

## Vector search (designed by Claude, 2026-10-28, on the owner's delegation)

### What the core asks of it today (`src/asuna/retrieval.py`)

One cosine index on the `embedding` of `memory_units`, with filter fields `scope_key`, `character_id`, `status`,
`policy_epoch`, `embedding_revision` and `kind`. Two queries (`own_thoughts`: 96 candidates, 12 results; `search`:
192, 24) return ids and a score; the filter is equality on those fields plus "any of these (scope, epoch) pairs".
Lexical recall is computed in Python on rows the program reads itself, so it needs nothing of the database beyond
reading records.

### What the common databases offer (a survey, sources checked 2026-10-28)

| | storage, dimension | metrics | filter with k-nearest | exact search | score returned |
|---|---|---|---|---|---|
| MongoDB `$vectorSearch` | array on the document; fixed in the index | cosine, dotProduct, euclidean | pre-filter on fields declared in the index; `$eq $in $or` and ranges | `exact: true` or `flat` | 0..1, cosine as (1 + cos) / 2 |
| PostgreSQL + pgvector | `vector(n)` column | cosine `<=>`, inner product, L2, L1 | any `WHERE`; with an ANN index applied after the scan (fewer than k can return) | no index | cosine distance 0..2 |
| SQLite + sqlite-vec | `vec0` table, `float[n]` | cosine, L2, L1 | inside the k-nearest, on up to 16 metadata columns; `= != < <= > >=`, no `IN` | the stable release is brute force | distance, lower is closer |
| Redis | float32 blob, `DIM` | cosine, IP, L2 | schema fields (tag, numeric) | FLAT | 1 - cos |
| Elasticsearch / OpenSearch | `dense_vector`, `dims` | cosine, dot, l2 | a filter inside `knn` is a pre-filter | `script_score` | (1 + cos) / 2 |
| Qdrant | collection size | Cosine, Dot, Euclid | the search runs among matching points | `exact: true` | cosine as is |

Sources: the MongoDB Vector Search pages (index type, the `$vectorSearch` stage, self-managed search), pgvector's README
(v0.8.7), sqlite-vec's docs and releases (stable v0.1.9), Redis vector search docs, Elastic's `dense_vector` and
filtered kNN pages, OpenSearch's filtered k-NN page, Qdrant's collections and search pages. Not verified: MongoDB's
dotProduct and euclidean score formulas, Redis's dimension limit, sqlite-vec's exact cosine formula.

### The interface (as built; revised from the first design during the build, 2026-10-28)

The first design (commit `d6c35bf3e876`) had a vector store of its own, with `put` and `remove`. Building it showed
what that costs: outside MongoDB its entries hold their own copy of the filter fields, so every change of a record's
status and every erasure (ADR-105) would need a second call that each caller must remember, a sync rule spread over
the call sites. Revised: vector search is an operation of the store that holds the records, and a record's vector is
written with the record.

```python
@dataclass(frozen=True)
class Space:                       # src/asuna/state.py
    name: str                      # its index
    collection: str                # the records that hold the vectors
    path: str                      # the field with a record's vector, written with the record by `put`
    dimensions: int
    fields: tuple[str, ...]        # the record fields a search may filter on, declared with the index

store.ensure_vectors(space, timeout=45) -> bool          # create, or bring the filter fields up to the space's;
                                                         # True once it can be queried
store.nearest(space, vector, k, where) -> list[tuple[str, float]]
```

- **`nearest`** is exact, best first, equal scores in id order, the score raw cosine in [-1, 1] (MongoDB's
  (1 + cos) / 2 becomes 2s - 1). `where` maps a declared field to a value or a list (any of them), or a tuple of
  declared fields to a list of value tuples (any of those combinations); every entry holds; an empty any-of matches
  nothing. It refuses an undeclared field, a wrong dimension or a zero vector, and `k` outside 1 to 100.
- **Written with the record.** The adapter keeps a record's vector and filter fields in the record's own write:
  MongoDB on the document (as today), PostgreSQL a `vector` column of the row, SQLite its `vec0` table in the same
  transaction. A status change or an erasure needs no second call.
- **Left out of the first design:** `put` and `remove` (the record's write does it); the model in the space (the core
  already keeps models apart with its filter field `embedding_revision`); the combined field `scope_epoch` (a tuple
  key instead, so 134,016 records need no new field).
- **Kept:** exact search as the contract, raw cosine, any-of, eventual visibility, and the list of what is not in the
  interface.
- **The core's own scale.** Her `memory.coverage_floor` is a persona setting from 0 to 1 that read MongoDB's score; so
  that it keeps its meaning, retrieval compares it with (1 + cosine) / 2.
- **The double and the contract suite** come with the record interface (step 2): the double is the in-memory store,
  and the one contract suite runs against it and against the MongoDB adapter (a server that no deployment uses).

### Measured on her memory (2026-10-28 02:04, read only, numbers only)

134,016 records, 28 conversation and epoch pairs (the largest 33,372). Twenty queries a row, each a stored vector of
one of her memories (no embedding call), today's approximate search (`numCandidates` 96 and 192) against exact.
Recall counts the approximate results whose score reaches the exact 24th (12th) score, because up to 24 identical
memories share one top score.

| query (as retrieval makes it) | records in the filter | approximate, ms median / p95 | exact, ms median / p95 | approximate recall, mean / worst |
|---|---|---|---|---|
| `search`, the largest conversation | 33,372 | 28 / 35 | 36 / 38 | 0.979 / 0.875 |
| `search`, the second | 19,222 | 34 / 38 | 30 / 33 | 0.963 / 0.875 |
| `search`, the third | 10,978 | 31 / 36 | 23 / 27 | 0.973 / 0.708 |
| `search`, the fourth | 7,929 | 26 / 30 | 18 / 23 | 0.990 / 0.833 |
| `own_thoughts`, six conversations | 3,719 | 18 / 22 | 14 / 18 | 0.946 / 0.167 |
| no conversation filter (no query does this) | 133,835 | 31 / 33 | 94 / 101 | 0.892 / 0.625 |

Verdict: exact passes. On every query retrieval makes it costs at most 8 ms and is mostly faster; it finds what
approximate missed (up to five of six of one query's best). Noted, not this ADR's: identical memories (up to 24 at
one score) can fill a whole result.

### Build order

1. Vector search through the store (built).
2. The record interface from the core's own operations, the in-memory double and the contract suite; the call sites
   move to it module by module behind the MongoDB adapter, nothing changing for her between steps.
3. The MongoDB adapter leaves the core into its own package, loaded by configuration as the channel packages are.
4. The suite: unit tests on the double, the adapter's tests on a server no deployment uses, and the reset
   (requirement 6).

The package is the last step, not the first: until the core reaches the database only through the interface, there is
nothing to lift out, and the install path (the plugin, the floor, releases) changes once.

### Risks to check when it is built

1. Resolved by the measurement above: exact on her memory.
2. MongoDB's self-managed vector search needs a replica set and `mongot`; this deployment has both today (its
   retrieval works). A new deployment's install says so.
3. The dimension ceiling: pgvector indexes at most 2,000 dimensions (4,000 as `halfvec`), exact search has no such
   limit. Today's embedding model is well under it.
4. sqlite-vec is before v1 (upsert only in alphas): its adapter pins the version and upserts as delete then insert.

## Built

- Step 1 (2026-10-28, not installed): `Space`, `Store.ensure_vectors` and `Store.nearest` (`src/asuna/state.py`);
  `retrieval.py` asks the store for both of its searches (`MEMORY`, exact, 24 for `search` and 12 for
  `own_thoughts` as before) and imports nothing of MongoDB. Its evidence records `exact` instead of `numCandidates`.
  Checked on her real memory, read only: for 30 queries of both kinds `nearest` returned the same records at the same
  scores as the pipeline retrieval ran before, made exact; its refusals and its empty any-of hold. No unit test: no
  test server has vector search, and the contract suite comes with the double (step 2).

## Open questions (to discuss with the owner first) (as recorded before the decisions)

1. Which databases are meant ("a different database": another MongoDB, or another kind such as PostgreSQL or SQLite)?
2. What the interface is: the store's operations the core really needs, or a MongoDB-shaped query surface. With 912
   direct collection uses, this decides the size of the work.
3. Retrieval: vector and full-text search are database features today. Are they part of the connector, or their own
   interface?
4. Migration of an existing deployment's data, and what a test double looks like (`mongomock` today).
5. What "similar to the code cleanup" points to (which earlier cleanup is the model).

## Constraints already known

- JS and Python may run different versions (RUNTIME_API).
- Tests and probes drop their own databases (AGENTS.md). Today the suite's databases live on the same server as the live data (`config/local.json`
  `mongo_uri`, one `asuna_v2_test_*` database per test; drops refuse any other name, `tests/conftest.py`): separate
  data, shared load. Requirement 5 ends that; the AGENTS.md rule changes with it.
- A deployment's private data stays in its data folder and its own database.
