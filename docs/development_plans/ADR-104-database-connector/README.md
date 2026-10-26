# ADR-104: Database connector

Status: requirements recorded 2026-10-27, before any design. Third in the owner's order (102, 103, 104). The owner
wants to talk it through first. Nothing here is decided.

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

## Open questions (to discuss with the owner first)

1. Which databases are meant ("a different database": another MongoDB, or another kind such as PostgreSQL or SQLite)?
2. What the interface is: the store's operations the core really needs, or a MongoDB-shaped query surface. With 912
   direct collection uses, this decides the size of the work.
3. Retrieval: vector and full-text search are database features today. Are they part of the connector, or their own
   interface?
4. Migration of an existing deployment's data, and what a test double looks like (`mongomock` today).
5. What "similar to the code cleanup" points to (which earlier cleanup is the model).

## Constraints already known

- JS and Python may run different versions (RUNTIME_API).
- Tests and probes drop their own databases (AGENTS.md).
- A deployment's private data stays in its data folder and its own database.
