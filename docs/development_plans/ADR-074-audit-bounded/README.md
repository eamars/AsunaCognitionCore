# ADR-074: The audit is bounded by time and by size

Status: **Built 2026-10-16** (the owner's decision: the audit rotates by size or time; his yes to the numbers below the
same evening). Installed with her next restart.

## Context

ADR-067 deleted the bulky diagnostic records after 30 days and kept everything else whatever its age. Measured
2026-10-16 18:30 NZDT over the last 24 hours (read-only, `$bsonSize` per record): the audit grows about 159 MB a day;
about 120 MB of it went at 30 days, about 39 MB a day stayed for ever (commits of tasks, artifacts, new memories and
episodes, received events, her tool calls). At that reading it held 2.7 GB of data (1.46 GB on disk), oldest record
2026-09-20.

What reads old records: every reader of `audit_events` looks back 30 days or less, except two. `reasons.then` reads
her tool calls (`role_tool`) of the turn a recalled thought came from, whatever its age, to say what she did next; and
each review counts from the record of its last showing (`review.tools_week`, `review.tools_week.started`,
`review.exchanges`, `review.map`, `sticker.review_offered`).

## Decision

`audit.prune`, at worker start and daily (as before):

1. **Time.** Every audit record older than 30 days goes, except her tool calls, kept a year, and the newest record of
   each review's last showing in each stream, kept whatever its age.
2. **Size.** When the audit's data (`collStats` size, before compression) is over 6 GB, the oldest records go first,
   whatever their kind, as many as the excess holds at the average record size; the newest showing of each review
   stays.
3. One `audit.pruned` record per run that deleted: up to when, how many, `by` (`time`, `size`), and the limits.
   `audit.verify` accepts a chain gap only where such a record explains it (unchanged).
4. An index on `occurred_at` serves both deletes.

Expected: about 30 days at ~159 MB a day plus a year of her tool calls (~1.8 MB a day): roughly 5–5.5 GB of data,
about 3 GB on disk at the compression read above, then flat. MongoDB reuses the freed space; the files stop growing
but do not shrink without a compaction, which is the owner's to run.

Commits of persona and relationship revisions, tasks, plans and episodes now go at 30 days too: each collection holds
its own documents (and `state_revisions` every revision); the audit was a second copy.

Not changed: `Store.recover_commits` treats a document whose last operation has no commit as a lost commit; after
retention that is normal. No live path calls it (only `Coordinator.recover`, used by tests); a caller added later needs
to account for it.

## Cost (AGENTS.md)

Neither brain: no tool, option or line. Program: `audit.prune`, its tests, one index.
