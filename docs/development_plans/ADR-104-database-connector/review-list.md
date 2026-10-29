# ADR-104 review list (Claude, 2026-10-28 evening, written before any design exists)

What "ADR-104 satisfied" means. I hold the design to every line; a line it cannot meet is named on its page, with the
reason, never passed silently. Sources: the owner's requirements on the ADR-104 page (1-6), his words today, AGENTS.md.
The design subagent gets this list as its acceptance criteria.

## A. The owner's requirements

1. **Own package.** The MongoDB adapter is a package beside the core, loaded by configuration like the channel
   packages. After the build the core imports no database driver and names no database: `src/asuna` has no `pymongo`,
   `bson`, `$`-operator or `mongo` outside the configuration key that selects an adapter. A missing or unknown adapter
   fails at start with one clear error (as `CHANNEL_KIND_NOT_INSTALLED` does), never with a half-working store.
2. **Another database can be connected.** For every operation in the interface, the page states how SQLite and
   PostgreSQL would do it (one line each), or marks it "not available there" with what the core does then. The double
   alone does not prove this: it is Python, it can do anything.
3. **Expansion.** Adding a collection, or a new query on an existing one, needs no adapter change. Adding a database
   means implementing the stated methods and passing the contract suite, nothing else. A capability one database lacks
   is declared and refused explicitly, never approximated quietly.
4. **Unit tests stop at the interface.** No unit test can reach a database server: enforced by the test setup (for
   example no server address in the unit run, a guard that fails any connection), not by convention. Only
   `integration/` reaches a server: a throwaway `asuna_v2_test_*` database of synthetic records, small, dropped at the
   end and on failure.
5. **The suite reset.** Which tests go, which stay, and why, by rule (duplicated coverage, wording, MongoDB-behaviour
   tests the contract suite now owns). A measured run time before and a target after.
6. **Today.** The page says plainly what lands today and what does not, and when unit tests stop touching her server.
   No step is shortened to make today.

## B. The level of abstraction (the owner's concern)

7. **Call sites name no collection and build no condition.** Outside the module that owns a collection, code calls
   named operations of that owner ("readable memories for these pairs"), never `where` words. Checkable by a search
   once migrated.
8. **One owner per collection.** All collections are listed, each with one owner module. A collection used by several
   modules today has its decision written (which owns it; what the others call).
9. **The adapter interface carries no database's vocabulary**: no `$` names, no MongoDB method names as concepts, no
   database handle or escape hatch (today's `store.db`, `dbread._default().db` go).
10. **Small and justified.** The adapter's method count is stated; each method names the core need it serves. Nothing
    is there "for later".
11. **Meaning written once.** Every operation and every condition word has its meaning in prose: missing versus null,
    list fields, string order and case, mixed types, where missing sorts, limits, ids, time values (aware datetimes
    round-trip unchanged). The errors are named (duplicate, stale revision, not supported) and what raises them.
12. **The hard cases, each designed**, not deferred: the counter in one step; claiming the next item safely across
    processes; the host lease on one clock (which clock in each adapter; the double takes an injected clock); unique
    keys including "only where a field exists"; the revisioned write and `Store.put`'s audit (in the core, not the
    adapter); bulk writes; the three aggregates; prefix, contains and case-blind matching; nested fields and list items;
    vector search with filters and the tie rule from step 1b; large binary files (today GridFS: streamed in and out,
    hash-checked, erased by scope) and the record size limit; a collection chosen at run time (46 such uses today);
    creating collections, their validators and indexes.
13. **No transactions, checked.** The design states that no core invariant spans two records, or names each one that
    does and how it stays safe.
14. **Her read tool.** `dbread` works on every database, read only and bounded, in the interface's terms. Her files
    that use the old syntax are listed; she rewrites them herself; nothing of hers is edited for her.

## C. The double stays faithful

15. **One contract suite**, the same cases on the double (unit run) and on MongoDB (integration). Its cases are listed
    per word and per operation (including races on the counter and the claim, duplicates on update and upsert, stale
    revisions, lease expiry), with a size and a run time.
16. **What the contract suite cannot show** (how call sites compose) is covered by the per-module check: the old query
    against the new on her real database, read only, light, numbers only, same rows in the same order.
17. **The double is exact** where production is exact; a tie at the k-th place belongs to the integration test, never
    to a unit test (step 1b).

## D. Execution

18. **Every call site is mapped.** The census (about 968 calls) maps each call to an owner operation; the dynamic and
    merged filters (about 70) are each assigned, none left as "handle later".
19. **Batches.** Module order, each batch's size, the proof that nothing changes for her at the layer she sees, which
    batches need a restart (one change per restart), and that each batch reverts alone.
20. **Who builds.** Subagents in separate worktrees for independent modules; my review of each batch before it lands;
    no two batches editing one file at once.
21. **Tests while building.** Targeted tests per batch on the double; one full suite per landing; no suite run just to
    wait on it.
22. **The package split.** The install path (plugin, floor, release) changes once; her running system's data needs no
    migration (same MongoDB, same records), stated and checked.

## E. Xiaoman

23. What she sees: her behaviour unchanged (shown per batch); `dbread`'s new syntax; the list of her files. Which
    points need her signature, at which blob. She receives it once, finished.

## F. Project rules

24. The core stays persona-agnostic; no personal data in tracked files; the current references (RUNTIME_API,
    DEVELOPMENT.md, package READMEs) show the present only; evidence kept is named with path and size; worktrees and
    test databases removed when their job ends.
25. The decisions on the page made earlier (5 and 6: the "small query vocabulary" and `dbread` speaking it) are not
    rewritten. Where the design changes them, the change is written as a new decision with its date and reason.

## G. For a person reading it

26. The owner can read the page and understand, without code: how another user connects a database, what the core
    asks of a database, and why this shape. Every number says where it was read; nothing unverified is stated as fact.
