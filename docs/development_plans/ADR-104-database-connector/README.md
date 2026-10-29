# ADR-104: Database connector

Status: decided with the owner 2026-10-28 (below). Third in the owner's order (102, 103, 104). The vector interface
is designed (section "Vector search", Claude on the owner's delegation); step 1a (the interface, her search
unchanged) is built and installed 2026-10-28; step 1b (exact search) is built on it, on main (see "Build order" and
"Built"). Everything after step 1 is designed to the end in [design.md](design.md) (2026-10-28 evening, decisions 7
and 8 below), from an independent survey ([research.md](research.md)), checked against
[review-list.md](review-list.md). Its batch B0 (the unit run reaches no server) is built and landed (see "Built").

## The owner's ask (2026-10-27, verbatim)

> The next task will be similar to the code cleanup, that I want to breakout the database connector from the Asuna
> package, similar to QQBot and Napcap adapter, that I want the capability for other users to connect to different
> database. The database connector interface should be designed to accommodate future expansion. I would like to
> discuss more about this when your current job is done.

## What exists today (counted in the code on 2026-10-27)

- The Python worker reaches MongoDB through `Store` (`src/asuna/state.py`: `put`, `audit`, `authorize`, and its
  `db`), but most code goes to the collections directly: `store.db.<collection>` appears 915 times in 77 files of
  `src/asuna/` (`git grep -o 'store\.db\.' c6e837c947bf -- src/asuna`, occurrences, not lines; first written as 912
  without its method, which Xiaoman could not reproduce; 931 in 78 files at `3e1e95f2c120`).
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
   are the only ones that reach a database. The owner, 2026-10-28, on Claude's question of a second server: "Can you
   test on the production server? As you are using unit test to stress that server already." and then "Yes, but
   after today the unit test needed never stress the production server anymore. This is one off test requirement."
   Refined the same night: "most unit test stops at the DB adapter interface, only integration test reaches at real
   server to ensure the interface compatibility, but not stressing the server." So: unit tests run on the double;
   integration tests (`integration/`, outside the default run) reach her server only to show the adapter meets the
   interface, on a throwaway `asuna_v2_test_*` database of synthetic records dropped at the end. From 2026-10-29 no
   unit test reaches her server (AGENTS.md); until the double carries them, a unit test that needs a database is not
   run, and what it would show is checked read-only on her database.
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

7. **Step 2 onward as [design.md](design.md)** (2026-10-28 evening). The owner then judged decision 5's proposal not
   robust enough in its level of abstraction: "This is the DB adapter's job. WHY the adapter even need to expose the
   raw operator vocabulary?", and asked that the design be finished before the build, from a survey of how projects
   that serve several databases do it ("I'm not intended to re-invent the wheel"). He set the direction as product
   manager; the technical decisions are Claude's. The survey ran from requirements only, without reading this code
   ([research.md](research.md)); a design agent wrote the design from it; Claude reviewed it against a list written
   before the design existed ([review-list.md](review-list.md)) and had it revised once. What it adds to decision 5:
   one owner module per collection, so no other module builds a condition or names a collection; declared fields
   per collection, writes validated once; a meaning table that the in-memory adapter implements and MongoDB is tested
   against; named primitives for what generic calls cannot make atomic (claim, revisioned replace, the database's
   clock in a write, the counter); a blob interface for large files; nineteen adapter methods; eighteen batches
   (B0 to B15), each its own review; B1b to B14 installed in eleven restarts (four adjacent pairs share one). The words stay the core's own, not MongoDB's subset
   the survey suggested (decision 2). Decisions 5 and 6 stand as written; this one adds to them.
8. **The unit run's stand-in until B13** (the owner, 2026-10-28 evening, in the question tool, Claude's
   recommendation): from B0 the unit run uses an in-process MongoDB stand-in (mongomock), never a server, until B13
   moves it onto the in-memory adapter. Its cost, as put to him: a fake leaned on for the length of the move, never
   the reference of what a query means; the tests it cannot carry are skipped with what it lacks in one reviewed list.
   Not chosen: switching the database tests off until each module has moved.

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

- **`nearest`** returns k records best first, the score raw cosine in [-1, 1] (MongoDB's (1 + cos) / 2 becomes
  2s - 1). Step 1a keeps her search as it is: approximate (MongoDB looks at 8 candidates per result, retrieval's 96
  and 192 before); among equal scores the order is not defined (MongoDB gives none without a sort, Xiaoman's point),
  as before. Exact search, the design's contract, is step 1b, its own change
  (the owner, 2026-10-28: "Having different result from interface change is real concerning"; split, Claude's
  recommendation). Under exact search, equal scores come in id order, and which of several records tied at the k-th
  score are returned is the database's (found by the integration test); nothing in the core depends on which of
  identical memories it gets. `where` maps a declared field to a value or a list (any of them), or a tuple of
  declared fields to a list of value tuples (any of those combinations); every entry holds; an empty any-of matches
  nothing. It refuses an undeclared field, a wrong dimension or a zero vector, and `k` outside 1 to 100.
- **Written with the record.** The adapter keeps a record's vector and filter fields in the record's own write:
  MongoDB on the document (as today), PostgreSQL a `vector` column of the row, SQLite its `vec0` table in the same
  transaction. A status change or an erasure needs no second call.
- **Left out of the first design:** `put` and `remove` (the record's write does it); the model in the space (the core
  already keeps models apart with its filter field `embedding_revision`); the combined field `scope_epoch` (a tuple
  key instead, so 134,016 records need no new field).
- **Kept:** exact search as the contract (from step 1b), raw cosine, any-of, eventual visibility, and the list of what is not in the
  interface.
- **The core's own scale.** Her `memory.coverage_floor` is a persona setting from 0 to 1 that read MongoDB's score; so
  that it keeps its meaning, retrieval compares it with (1 + cosine) / 2.
- **The double and the contract suite** come with the record interface (step 2): the double is the in-memory store,
  and the one contract suite runs against it, and as an integration test against the MongoDB adapter on a throwaway
  database of her server.

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

What she gets (Xiaoman's ask, 2026-10-28: the final six, not the candidates, and what drops out). 40 queries, ten in
each of her four largest conversations, each a stored memory of hers (not her thoughts) as the query's text and its
stored vector as the query's vector; `Retrieval.search` run whole (vector and lexical fused, the six selected) with
the old code (approximate) and the new (exact), read only (its audit and evidence writes turned off):

| conversation | queries | the same six | memories that dropped out | most in one query |
|---|---|---|---|---|
| the largest | 10 | 5 | 8 | 2 |
| the second | 10 | 10 | 0 | 0 |
| the third | 10 | 5 | 8 | 3 |
| the fourth | 10 | 7 | 4 | 2 |

20 of the 240 selected memories change by id; the vector candidates changed for 29 of the 40 queries. Split as she
asked (she found it in the sample), by where each dropped out and whether an identical twin (another record with the
same `content_sha256`, so the same score) took its place:

| | a twin took its place | a real change |
|---|---|---|
| out of the vector candidates (not in the new 24) | 2 | 4 |
| out at the fusion that picks six (still in the new 24) | 7 | 7 |

So 11 of 240 (4.6%) really change: 4 lost by recall, 7 at the fusion. A twin swap happens because exact search orders
equal scores by id; in one sample the query's own memory gave way to its twin. Whether the 11 should have dropped out
is hers to judge on their content: ten samples, each with what came in, went to her by id (Claude does not read them);
seven of the ten turned out to be twin swaps. Her queries are mostly short phrases, not whole memories; a second
reading with real phrases of hers is open (it needs their embeddings).

## Step 2: the record interface (proposed by Claude 2026-10-28, for the owner's review)

Superseded the same evening by decision 7 and [design.md](design.md); kept below as it was proposed.

Decisions 5 and 6 give its shape: a small vocabulary the core defines, which the core and her read tool both speak.

### What it has to carry (counted in `src/asuna/` on 2026-10-28)

- Calls: `find_one` 624, `find` 254, `update_one` 38, `count_documents` 32, `delete_many` 13, `distinct` 8,
  `insert_one` 7, `update_many` 5, `replace_one` 5, `delete_one` 5, `find_one_and_update` 4, `aggregate` 3 (plus
  `dbread`'s), `bulk_write` 2. Writes of records mostly go through `Store.put` (a revision checked, an audit row).
- Filter words, counted as written (an operator inside an aggregate counts too): any of (`$in`) 129, ranges 128,
  `$or` 44, exists 42, not (`$ne`) 23, none of (`$nin`) 16, a regular expression 12 (9 "starts with", two of them
  any of several prefixes; 3 "contains" at two places, one case-blind), `$elemMatch` 2, `$type` 1 (beside a prefix).
- Change words: set 66, unset 13, add to a set 11, increase 9, set when created 7, keep the larger 4, keep the
  smaller 1, push and keep the last few 1.
- Database features beyond reads and writes: unique keys, some only over rows that have a field (inbound messages are
  dropped as duplicates by one); a counter taken and increased in one step (a conversation's sequence); the host
  lease taken on the server's clock (`$$NOW`, ADR-020); three aggregates (the audit stream's heads, a conversation's
  tasks joined to their messages with `$lookup`, the Web's message listing).
- Her side: seven files of her skills name `dbread`, and the code of four calls it ten times (`find`, `count`,
  `distinct`, one `aggregate` that groups and counts), and one script takes MongoDB's own handle (`dbread._default().db`). Her task scripts outside the
  repository use it too.
- Tests: 49 test files make a store or name a test database (an `asuna_v2_test_*` database on her server), 5 use
  `mongomock`.

### The interface

```python
class Records(Protocol):                       # the core's store; `Store` keeps its audit and revision rules on top
    def declare(self, collection, *, unique=(), indexes=()) -> None   # unique: (fields, only where these exist)
    def get(self, collection, id, fields=None) -> dict | None
    def find(self, collection, where, *, sort=(), skip=0, limit=None, fields=None) -> Iterator[dict]
    def count(self, collection, where) -> int
    def distinct(self, collection, field, where) -> list
    def group(self, collection, where, by, *, total=None) -> list[tuple]     # count, or a field's sum, per value
    def insert(self, collection, record) -> None                            # Duplicate when a unique key repeats
    def replace(self, collection, record, *, revision=None) -> bool         # only if its revision is still that one
    def update(self, collection, where, change, *, many=False, create=False) -> int
    def delete(self, collection, where) -> int
    def next(self, collection, id, field) -> int                            # the counter increased, in one step
    # and step 1's ensure_vectors and nearest
```

- **Where**, in plain Python with the core's own words, never a database's: `{'field': value}` (equals; on a list
  field, the list holds it), `AnyOf([...])`, `NoneOf([...])`, `Not(value)` (also true where the field is missing),
  `Range(gte=, gt=, lt=, lte=)`, `Exists(True/False)`, `StartsWith('...', ...)` (any of the prefixes), `Contains('...', case=False)`,
  `Or(where, ...)`, `Each(field, where)` (one list item meets all of `where`). Dotted names reach nested fields.
- **Change**: `Set({...})`, `Unset([...])`, `Add(field, *values)` (to a set), `Increase(field, by)`,
  `Larger(field, value)`, `Smaller(field, value)`, `OnCreate({...})`, `Push(field, value, keep_last=n)`.
- **Semantics written down once**, the way MongoDB behaves today where the core relies on it: a missing field is not
  null; `Not` and `NoneOf` match a missing field; equals on a list means "holds"; strings compare by code point; a
  sort puts missing first. The in-memory double implements exactly these, and the contract suite pins each.
- **Named operations stay few:** `next` (the sequence), the lease (its own small interface, the adapter's clock), and
  `group`. The three aggregates become reads plus Python: the audit heads read each stream's newest row; a
  conversation's tasks are read, then their messages by id (16 tasks at most); the Web listing reads and cuts its
  excerpt in Python.
- **Not in it:** transactions (every write today is one record, made safe by its revision), change streams, joins,
  full-text search, the database's clock outside the lease.

### Her read tool

`dbread` keeps its names and its answers (what it asked, how many rows, 零行) and takes the same `where` words, so a
script of hers reads the same on any database. `aggregate` becomes `group`; the raw handle goes. She rewrites her own
skills and scripts; the change reaches her when this step is built, with the list of her files that use the old
syntax (four files of code in her package today), never edited for her.

### Tests (requirement 5)

- The double is the in-memory `Records`; `mongomock` goes.
- One contract suite runs the same cases against the double (with the unit tests) and the MongoDB adapter (as an
  integration test, requirement 5: a throwaway database of her server, a few hundred synthetic records, dropped at
  the end).
- Unit tests then run on the double: no database server, no shared load on hers. From 2026-10-29 this comes first:
  the double and the test setup on it are step 2's first part, before any call site moves, so the suite can run
  again. Which tests stay is requirement 6, step 4.

### How the call sites move

Module by module, largest first, nothing changing for her between steps: each module's reads are checked on her real
database read-only, the old query against the new one, as step 1 was (same rows, same order), before its commit. A
module is done when it names no collection method.

### Build order

1. Vector search through the store, in two changes: 1a the interface with her search unchanged (built); 1b exact
   search (built), landed apart from 1a, after a reading on real phrases of hers and her judgement of what
   changes.
2. The record interface from the core's own operations, the in-memory double and the contract suite; the call sites
   move to it module by module behind the MongoDB adapter, nothing changing for her between steps.
3. The MongoDB adapter leaves the core into its own package, loaded by configuration as the channel packages are.
4. The suite: unit tests on the double (the double itself first, in step 2), and the reset
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

- Step 1a (2026-10-28, installed the same day): `Space`, `Store.ensure_vectors` and `Store.nearest` (`src/asuna/state.py`);
  `retrieval.py` asks the store for both of its searches (`MEMORY`, 24 for `search` and 12 for `own_thoughts` as
  before) and imports nothing of MongoDB. Its search stayed what it was: approximate, `CANDIDATES_PER_RESULT` 8 (the constant left with 1b; 96
  and 192 as before), no defined order among equal scores. Checked on her real memory, read only, against two references (Xiaoman asked that each
  be named): (a) for 30 queries of both kinds `nearest` returned the same records in the same order at the same
  scores as the `$vectorSearch` stage retrieval built, rebuilt in the check script (`check_nearest_1a.py`); (b) for
  40 queries the whole search (vector and lexical fused, six selected), run with main's own `retrieval.py` before
  and after 1a's, gave the same six and the same 24 vector candidates every time (her memory did not drift between),
  and the same coverage score to the bit, so the same verdict for any `coverage_floor`. The one visible change is the
  scale of the scores the evidence records: raw cosine, 2s - 1 of MongoDB's (her finding); a comparison of scores
  across 1a converts first. They land in her audit stream (`retrieval.selected`, `vector_ranks`), so rows from
  before 1a's install carry the old scale; no code reads that field (`vector_ranks`, and `numCandidates`, which 1b
  replaces with `exact`, have no reader anywhere in the tree: `src`, `tools`, `integration`, `packages` with the JS
  and her persona's skills, searched by her and by Claude), and `nearest`'s callers are only retrieval's
  two searches (`own_thoughts` uses ids alone; `search` uses the score for coverage, converted back to 0..1).
  Its integration test, `integration/test_mongo_vectors.py` (18 cases, 7 s, a throwaway database of 301 synthetic
  records): the index made and brought up to the space's fields; `nearest` gives k records, each matching the filter
  and scored with its own cosine, best first, for value, list, pair and combined filters at k 1, 12 and 24; identical
  vectors; the refusals. Built first as exact (commits up to `774550b2d849`), then turned back to today's search
  for the split; the measurements above are of that exact version, the reading for step 1b.
  On her database `ensure_vectors` runs where `ensure_index` ran before (the worker's memory indexer, `asuna`'s index
  command): her index already has the space's six filter fields, so it only lists the index; it changes an index only
  when a space's fields differ from it. Before a change of the filter fields reaches her database, she is told
  (her ask, 2026-10-28).

- Step 1b (2026-10-28): `nearest` exact (MongoDB's exact mode), equal scores in id order; retrieval's
  evidence records `exact`; the integration test checks exact results against a brute-force cosine. Its reading on
  her real searches, the one she asked for (her rule: ids and scores, not positions; three columns): 73 of the 182
  `recall.read` rows with a query in her `audit_events` (60 drawn, plus all 13 id-like ones, a class apart), each in the conversation she
  asked it in, embedded once through her embedding service (the owner's yes) and run whole (vector and lexical fused,
  six selected), the old code before and after 1b so her memory's drift shows (none did). The final six: the same
  set in 73 of 73, the same order in 72. The 24 candidates (1,752): 7 displaced (0.4%); 53 one place lower by score,
  each because a closer record came in above it; 8 tie reorders. The id-like class the same. Her query text and its
  vectors were deleted after the run. The earlier 8% (whole memories as queries) came from placeholder duplicates,
  not from how she searches. What this shows (her boundary): old and new code are equivalent on today's memory, not
  that those queries find what they found the day she asked them; her memory grows by the minute.
  Its cost, a whole `search` (vector and lexical, six selected) on 40 queries, three runs each, the old code run
  before and after (read only, the embedding call left out, the same in both): p50 383 / 387 ms old, 371 ms 1b;
  p95 566 / 563 old, 596 1b; the vector part alone p50 28 / 26 old, 24 1b, p95 35 / 33 old, 37 1b. A recall's time
  is mostly the lexical read of up to 4,096 records; exact adds at most 4 ms to the vector part; the whole search's
  p95 went from 566 to 596 ms, 30 ms slower (+5.3%), more than the vector part explains, so it is reported as it is,
  not as zero. Evidence, ids and scores only (her memory ids carry conversation keys, so it is not in git):
  `<data>/private/adr104-evidence/`, 27 files, 1,472,997 bytes; `README.txt` there maps each reading to its file and
  its code (by blob); kept until after her 10-30 check.
  **Why 1b at all (the reason, so it can be judged).** Not her recall: on her real searches it changes nothing she
  sees (above). The reason is the interface and its tests. (1) The in-memory double the unit tests run on is exact (an
  approximate double would be a second approximate search to keep in step with MongoDB's); with exact production, a
  unit test on the double shows what production returns, except at a tie on the k-th score: which of the tied
  records come back stays the database's, and the double decides it its own way, so ties at that boundary belong to
  the integration test, never to a unit test (her point: "unit test = production" must not become a free pass).
  With approximate production the two differ wherever approximate search misses: 0.4% of candidates on her real
  searches (the reading above); larger on stored memories used as queries (the first measurement: document vectors
  as queries, in a memory full of identical placeholder records; 1 to 4% of the best-scored on average, up to 83% on
  one query, counted by score so tie swaps do not count), a shape of the worst case, not how she searches. (2) Every engine surveyed searches exactly, while the approximate
  settings differ per engine (MongoDB's `numCandidates`, other engines' list and probe counts) and pgvector can return
  fewer than k after a filter, so exact is the one behaviour a second adapter can promise. (3) It costs within the
  noise (above). If these do not weigh enough for her, 1b waits: 1a works without it, and the double then has to be
  read as exact where production is not.

- B0 (2026-10-28, landed at `8bf815818995` and `1f7bb31bc629`, tests only, no restart): the unit run reaches no
  database server (design.md 7.3; decision 8). Every MongoDB client it makes is the in-process stand-in
  (`tests/unit_run_site/sitecustomize.py`), in the test process and in every Python process it starts, and every
  configuration it loads names `mongodb://unit-run.invalid:27017/`; `tests/test_no_server.py` checks both. Run on
  `1f7bb31bc629`: Python 1,502 passed, 20 skipped, 2 min 37 s (the last run on her server, `a00a9aa0eef6`: 1,519
  passed in 9 to 16 min); JS 260 passed. `tests/harness_skips.txt` lists 14 tests of what the stand-in lacks (the
  lease's update pipeline on the server's clock, `collStats`, one store across processes, MongoDB's own refusal
  text) and, apart, 5 of one defect class the stand-in's speed shows (design.md section 10, the clock-tie class).
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
