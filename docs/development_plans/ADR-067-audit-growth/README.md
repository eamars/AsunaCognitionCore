# ADR-067: The audit stops copying what is kept elsewhere

Status: **Accepted 2026-10-15** (the owner chose options 1–3 and retention), built the same day.

## What happened

The audit grew about 285 MB a day (measured over 24 hours on 2026-10-15; 2.5 GB in all). Most of it repeated data
that lives elsewhere:

| Record | Per day | What it repeated |
|---|---|---|
| `state.commit` of `memory_units` | ~75 MB | ~66 MB of it the embedding vector the indexer writes into each memory |
| `state.commit` of `messages` | ~60 MB | every revision of a line (delivery and ingress states) in full |
| `context.prepared` | ~55 MB | the turn's whole context, which the episode already holds |
| `state.intent` | ~34 MB | one record before every write; read only by the debug page |

The hash chain is verified only by the `--debug` CLI (`audit.verify`, `replay`); nothing at runtime depends on it.

## Decision

1. A commit leaves out fields computed from the document's own content (`state.DERIVED_FIELDS`: a memory's
   `embedding`) and names them (`derived_left_out`); `audit.verify_documents` and the trace compare the stored
   document without them.
2. `context.prepared` records the manifest (what was selected, the context's hash) and who the turn is with
   (`person_id`, `policy_epoch`, from the episode); the context is the episode's own.
3. No `state.intent`: a single-document write is atomic, and a commit that never got its record is found by the
   document's `_last_op` (`recover_commits`).
4. Retention: daily, and at each worker start, records older than 30 days of the kinds `context.prepared`,
   `retrieval.selected`, `native.context.bound`, `state.intent`, and commits of `messages`, `sink_receipts`,
   `identities`, `sessions`, `lane_receipts` and later revisions of `memory_units`, are deleted. Everything else stays
   whatever its age (persona and relationship revisions, tasks, plans, episodes, artifacts, tool calls, restarts,
   errands, a memory's first commit). Each run that deletes leaves one `audit.pruned` record (cutoff, count);
   `audit.verify` accepts a chain gap only where such a record explains it.

Not chosen: commits of message updates by reference (~49 MB a day more), which would lose the per-revision delivery
history on the debug page.

Expected: ~130 MB a day before retention, and a bounded audit after it. MongoDB reuses the freed space; the files do
not shrink without a compaction, which is the owner's to run.

## Measured (2026-10-16)

The audit's growth in bytes, 24 hours each, the third from the restart that installed this (2026-10-15 00:31 UTC):

| 24 h from | Added | `state.commit` | `context.prepared` | `state.intent` |
|---|---|---|---|---|
| 2026-10-13 00:31 UTC | 233 MB | 154 MB | 36 MB | 28 MB |
| 2026-10-14 00:31 UTC | 273 MB | 166 MB | 53 MB | 33 MB |
| 2026-10-15 00:31 UTC (this built) | 165 MB | 141 MB | 6 MB | 0 |

Down 40%, short of the expected ~130 MB a day. 9 MB of that day was identity commits from a separate bug (every
group member renamed at each start; fixed 16fad5ee, about one identity commit in 3.6 hours after it), so the steady
rate is about 156 MB. What is left is `state.commit` of `messages`: 5,644 messages committed 29,323 times in the day
(about five full copies each as their state moves), 75 MB; `memory_units` 20 MB, `artifacts` and `tasks` 10 MB each.
No `audit.pruned` record yet: the oldest bulky record crosses 30 days around 2026-10-20.

## Side effect

The memory view's "used in the latest context" (`native_cognition`) looks up `context.prepared` by person and epoch;
the full context it used to record carried neither, so that lookup never matched. It now does.

## What it adds to each brain

Nothing.
