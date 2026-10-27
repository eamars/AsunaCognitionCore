# ADR-104: Database connector

Status: decided with the owner 2026-10-28 (below), not designed in detail, not built. Third in the owner's order
(102, 103, 104). The vector interface is designed (section "Vector search", Claude on the owner's delegation).

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

### The interface

```python
@dataclass(frozen=True)
class Space:                       # one per embedding model and revision; fixed for its whole life
    name: str
    dimensions: int
    model: str                     # the embedding model and revision: a mismatch is refused, never mixed
    fields: dict[str, type]        # the filterable fields, declared with the index (str, int, bool)

class VectorStore(Protocol):
    def ensure(self, space: Space) -> None: ...
        # create, or check that the existing index matches; return only once it can be queried; refuse a mismatch
    def put(self, id: str, vector: Sequence[float], fields: Mapping[str, object]) -> None: ...
        # upsert; refuse a wrong dimension, a zero vector, an undeclared or mistyped field
    def remove(self, id: str) -> None: ...          # nothing there is not an error
    def nearest(self, vector: Sequence[float], k: int,
                where: Mapping[str, object | Sequence[object]] = {}) -> list[tuple[str, float]]: ...
        # exact top k among the records matching `where` (each field: one value, or any of a few values; the
        # fields AND-ed), best first; score = cosine similarity in [-1, 1]; ties broken by id; 1 <= k <= 100
```

- **Exact search is the contract.** Every engine above can do it, and at a companion's scale (10^4 to 10^5 memories)
  it is affordable. It removes the approximate-search knobs, the filter-recall trap (pgvector can return fewer than
  k after a filter), and lets the test double be exactly what the engines are. An adapter that one day needs
  approximate search may switch internally; the shared contract tests then show what recall it lost.
- **The score is raw cosine** in every adapter (MongoDB and Elasticsearch: 2s - 1; pgvector, sqlite-vec, Redis:
  1 - d). A threshold set on one database then means the same on another. A minimum score is applied by the caller.
- **"Any of a few values" stays,** because the core needs it (the scope and epoch pairs, written as one field
  `scope_epoch`). An engine without `IN` (sqlite-vec) runs one exact query per value and merges the top k: under exact
  search the result is the same.
- **The model is part of the space.** Vectors from two embedding models compared by cosine mean nothing and nothing
  would warn; a new model is a new space and a re-embedding (the core's `embedding_revision` today).
- **Not in the interface:** metric choice, quantization, approximate-search knobs, ranges and negations, nested paths,
  hybrid or full-text search, server-side embedding, returning stored vectors or documents. The adapter hides vector
  normalization (and refuses a zero vector), the conversion to cosine, the encoding of vectors and ids, waiting for an
  index, and turning off default quantization where an engine has it (Elasticsearch).
- **Writes become visible eventually** (MongoDB's search follows the oplog; Elasticsearch refreshes every second);
  PostgreSQL and SQLite are immediate. No caller may depend on reading its own write at once; the double has a
  delayed-visibility mode so a caller that does fails in a unit test.
- **One copy of the filter fields per adapter.** Outside MongoDB the vector entry holds its own copy of the filter
  fields, so every change of a record's status and every erasure (ADR-105) updates or removes its vector entry in the
  same step, or search returns stale or erased records. The contract tests pin it.
- **The test double** is an exact cosine search in memory (float32, normalized), with the adapters' refusals,
  upsert and idempotent remove, the same `k` bounds and tie order. One contract test suite runs against the double and
  against each real adapter (a throwaway database or file, dropped after); with it, unit tests stop at the interface
  (requirement 5).

### Risks to check when it is built

1. Switching MongoDB from approximate (`numCandidates` 96 and 192 today) to exact changes her retrieval: recall can
   only rise, latency must be measured on her real memory first.
2. MongoDB's self-managed vector search needs a replica set and `mongot`; this deployment has both today (its
   retrieval works). A new deployment's install says so.
3. The dimension ceiling: pgvector indexes at most 2,000 dimensions (4,000 as `halfvec`), exact search has no such
   limit. Today's embedding model is well under it.
4. sqlite-vec is before v1 (upsert only in alphas): its adapter pins the version and upserts as delete then insert.

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
