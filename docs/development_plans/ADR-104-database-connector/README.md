# ADR-104: Database connector

Status: decided with the owner 2026-10-28 (below), not designed in detail, not built. Third in the owner's order
(102, 103, 104). Before it is built, Claude researches the vector interface (decision 3) and presents the options.

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
4. **The model is the channel packages:** its own package folder and tests, a module the core loads by
   configuration, the core naming no database.

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
