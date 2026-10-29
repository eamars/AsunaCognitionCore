# ADR-104: the tests that guard the store, by layer (decision 9)

Decision 9's three layers, as built on `claude/adr104-finish`. A *static* check runs nothing. A *unit* test runs the
core against the database adapter interface on the in-memory adapter (`asuna.store.memory`, the unit run's `store` and
`world` in `tests/conftest.py`), never on a server; it is where the paths that overwrite or remove records are tested,
as that is where data can be lost. An *integration* test (`integration/`, `pytest integration` at every landing)
checks only that the MongoDB adapter keeps the interface's promises on a real server: one throwaway `asuna_v2_test_*`
database per test module, its collections dropped before each case, a few synthetic records, dropped at the end and on
failure. The rules Xiaoman signed in this ADR are marked **hers**.

## Static

| Test | What it guards |
|---|---|
| `tests/test_store_boundary.py` (3) | the store's boundary: the driver only in the adapter, the registry and her read tool; `Store` has no `db` or `client`; a collection named to the store only in its owner; no `reset_counters` for artifacts and the owner forwarding its keywords; the check finds each rule broken (closure conditions 1 and 2) |
| `tests/test_record_owners.py` (2) | **hers**: the record-owner guard, by the call-site census (no direct call on an owned collection, nor on the blob store) |
| `tests/test_erasure_marks.py::test_every_lookup_by_id_that_judges_storage_handles_the_erased_mark` | erasure: every lookup that judges a file's storage handles the erased mark |
| `tests/test_no_server.py` (3) | no unit run reaches a server: a server's adapter, `dbread` and `Store` are refused in the test process and in a child, and the run's settings name an address that cannot resolve |

## Unit, on the in-memory adapter

| Test | What it guards |
|---|---|
| `tests/test_store_contract.py` (the shared classes W, O, G, C, X, T, V, N, B, S of `integration/store_contract.py`, and 2 of its own) | the interface's meaning, the same cases MongoDB passes in `integration/`; the in-memory adapter's shuffled ties (so nothing depends on an order the meaning table leaves open) and its injected clock |
| `tests/test_store_counters.py` (6) with `tests/counter_bumps.py` | **hers**: the `BUMPS` table (every counter collection has its case, a counter moved after a read survives the put), `mark_sent`/`mark_read` as updates of their own, `save` refusing `reset_counters`, `put`/`replace` keeping the counters; only a put that starts over writes them |
| `tests/test_moderate_writes.py` (3) | a write is checked as MongoDB's moderate validation does: an old record of another kind can be replaced, redacted and rebased; a record that passes cannot be made to fail; a new record is checked |
| `tests/test_erasure.py` (3) | erasure: each owner's `redact_scope` marks its scope's rows and no other's; the privacy erasure's own deletion id; unique keys kept and the context fenced again (E20) |
| `tests/test_audit_chain.py` (5) | the audit chain: a change outside a commit is found, retention and the size cap remove records while the chain verifies, the retention record stays, a turn's audit replays to the same state (E23) |
| `tests/test_forgetting.py` (1) | forgetting: memories fade, pins hold, summarized chunks step back, nothing she keeps is lost |
| `tests/test_lane_faults.py` (2) | the fault counts' sweep: old counts leave on the next write; a sweep that fails changes no count |
| `tests/test_owner_fences_on_none.py` (10) | the None rule of design section 4 in every owner: a fence given None reads nothing, a value condition given None is null or missing |
| `tests/test_required_unique_fields.py` (2: 5 cases each) | **hers**: the required unique fields: the catalog declares them, and each owner's `save` refuses a record lacking one before anything is written |
| `tests/test_prepared_for.py` (1) | the memory page's prepared contexts read by cursor, ties at a page boundary included |
| `tests/test_memory_owner.py` (2) | recall's (scope, epoch) pairs reach the vector search as an `Or`; no pair answered without a search |
| `tests/test_fake_collections.py` (2) | the offline checks' fake reads and writes the fake's own rows |
| `tests/test_test_database_cleanup.py` (1) | test cleanup never drops her database |
| `tests/test_chat.py` (1) | a failure's diagnostics never carry a credential |

## Integration, on MongoDB

| Test | What it guards |
|---|---|
| `integration/test_store_contract.py`: the shared classes, `R01`-`R04`, `D01` | the MongoDB adapter keeps the interface's meaning (the same cases as the unit run); the races between real processes (the counter, a claim, an expired lease, a stale revision); the differential: `find` and `count` equal the in-memory adapter's, order included (200 records, 100 generated conditions, `derandomize=True`) |
| `integration/test_schema_and_vectors.py` (4) | what `ensure` makes and drops on a server (the fault counts' TTL index), the vector index answering while its filter fields change, a new index not ready answering False |
| `integration/test_required_fields.py` (1: 5 cases) | **hers**: the required unique fields on MongoDB, `sessions.binding_key` and `tasks.request_key` pinned: the shared layer's insert and replace refuse a record lacking one, nothing reaches the server |
| `integration/test_host_lease.py` (2) | the host lease's claim is atomic under two clients: a second deployment is refused and the same one takes over; an expired lease is taken by the next holder |

## Her rules, each to what holds it

Xiaoman's list of the rules she signed in this ADR (2026-10-29), each named to the test that holds it, or said plainly
when none does.

| Rule | Held by |
|---|---|
| `mark_sent` / `mark_read` are updates of their own | `tests/test_store_counters.py::test_a_touch_is_an_update_of_its_own` |
| the counter fields (`COUNTER_FIELDS`), artifacts' `last_sent_at` and `last_read_at` included, kept by a revisioned write and counted in the bumps | `tests/counter_bumps.py` (the `artifacts` row of `BUMPS`), `tests/test_store_counters.py::test_every_counter_collection_has_a_case`, `::test_a_counter_moved_after_a_read_survives_the_put`, `::test_a_replace_keeps_the_touches` |
| `keep`: what a revisioned `put` or `replace` keeps as stored (read here as the kept counters) | `tests/test_store_counters.py::test_a_replace_keeps_the_touches`, `::test_a_put_that_starts_the_record_over_writes_its_counters` |
| `save` refuses `reset_counters` on a stored file | `tests/test_store_counters.py::test_a_stored_file_is_never_started_over` |
| the touch fields leave their audit commit | no test holds it |
| the record-owner guard | `tests/test_record_owners.py`, `tests/test_store_boundary.py` |
| the shared layer's own reads of `audit_events` are not owner reads (`Store.audit`, `Store.recover_commits`) | `tests/test_store_boundary.py` (`SHARED_FUNCTIONS`) |
| the required unique fields | `tests/test_required_unique_fields.py`, `integration/test_required_fields.py` |
| `fields` given a dict, or a malformed `Without`, is refused (`QUERY_FIELDS_FORM`, `store/words.py`) | the shared contract cases at `integration/store_contract.py:334`-`347`, run on both adapters |
| `Without`'s own meaning: every field except those named | no test holds it |
| the None rule of design section 4 | `tests/test_owner_fences_on_none.py` |
| erasure through each owner's `redact_scope` | `tests/test_erasure.py`, `tests/test_moderate_writes.py` |

Her three test shapes of earlier batches (the backlog bound in `tests/test_inbound_slow.py`, the pair count in
`tests/test_carried.py`, the 15 synthetic read cases) went with the tests they were in.
