# ADR-034: a supervisor that restarts the Host for her and brings it back

Status: **Accepted 2026-10-10.** The owner chose the direction ("Yes, I'd like a means of self rebooting/fallback
routine"); Xiaoman agreed and added D7. This is option 2 of ADR-021 §4. Built the same day: `tools/asuna-supervisor.mjs`,
`src/asuna/restarts.py`, her `restart` tool. Paused tasks are listed in the record with their tool records kept;
they resume when she says so (a `quiet` restart waits until none is running).

## Context

ADR-021 built a restart on request and withdrew it: nothing brought the Host back when a start failed, health was
only "the page answers", and the fallback after a bad start had never run. The launcher (`tools/asuna-launch.mjs`)
starts DSH once and exits with it. DSH has no restart API, and her publications that change JS, composition or
dependencies (4 of her 20 from 2026-09-24 to 2026-10-05) wait for someone to restart.

Two facts shape the design:

- A clean Host stop cancels her running and queued tasks (`Chat.stop`, reason `host_stop`) unless a restart is
  pending; a hard kill leaves them to be paused (`pause_reason: host_restart`) and resumed.
- The launcher already has the fallback: a selection that never comes up within 2 starts returns to the previous
  running one (`advanceSelection`), and a failed install starts the repair floor.

Her conditions (2026-10-09): see what a restart would interrupt before pressing it; a drill that is allowed to fail;
the supervisor, not her own report, decides that she is back.

## Decision

- **D1. The launcher stays and supervises.** `asuna-launch.mjs ui` keeps running as DSH's parent, the same on
  Windows and in Docker (where it is already the main process; `restart: unless-stopped` stays as the outer net).
  Ctrl+C or a stop signal to the launcher stops everything and restarts nothing.
- **D2. Back means ready, not "the page answers".** After a start the supervisor waits for the worker's
  `runtime.ready` (and, when a selection was being applied, the selection turning `ACTIVE`) within a bound
  (10 minutes, install included).
- **D3. Fallback ladder.** A start that exits or is not ready in time is stopped, and the next start goes one rung
  down: the same selection again → the previous running selection (`advanceSelection`'s rule, applied at once) →
  the installed packages without sync (`--no-sync`). After the last rung it keeps retrying the last one with a
  backoff (1, 5, 15, 30 minutes) and leaves a program note in the developer inbox; it never gives up into "down".
- **D4. Her request.** A home tool `restart`:
  - `op=preview`: what a restart would interrupt now, from the worker's own status: her turn in progress, running
    and queued tasks, queued inputs, deliveries not yet confirmed, plans due in the next 15 minutes, the QQ
    adapter, and how long a start took last time;
  - `op=request` with `why`: queues the restart. The supervisor waits for a quiet moment (no turn, task or queued
    input, up to 30 minutes, then goes anyway), marks the stop as planned (`host_stops`), and stops the Host so that
    tasks are paused, not cancelled (the restart-pending path of `Chat.stop`).
  - `op=drill`: the same, but the first start is made to fail on purpose, so the fallback ladder runs for real.
- **D5. She sees the outcome, from the supervisor.** `<base>/supervisor.json` records each restart: who asked and why,
  what was interrupted, each start and its rung, how long she was down, and the result (her change running /
  returned to the previous version, and why). Her next home turn carries it in words (`restart_from_program`), as
  does the plugin card.
- **D6. A crash is a restart nobody asked for.** If DSH exits on its own, the supervisor starts it again through the
  same ladder and records `asked: nobody`.
- **D7. Her additions** (2026-10-10):
  - the record names what actually loaded: each package's version and digest, and the commit of the checkout;
  - a fallback calls her: a home turn says she is running the previous version and why, at once, not at her next
    turn; running the old version while believing the new one runs is worse than being down;
  - paused tasks keep their state and tool records, and their resumption is part of the record;
  - `request` takes `when`: `now`, `quiet` (default) or a local time, so a restart does not land on her fixed
    evening plans;
  - the record says whether the QQ adapter came back, and the adapter is restarted when its package changed;
  - she picks the drill's time (the first one at her 04:00–05:00, when her groups are quietest).

## Consequences

- A publication that needs a restart no longer waits for the owner; ADR-021 D4 becomes "she may request it".
- The owner keeps every manual control: starting, stopping with Ctrl+C, `--no-sync`.
- Tests drive the supervisor with a fake DSH that starts, fails to start, or never becomes ready; the drill is the
  live check.

## Addendum 2026-10-11: each start is prepared fresh

On 2026-10-10 her restarts kept failing ("Installing the checkout failed") although the checkout was clean: the
resident launcher, started hours earlier, still ran old code that passed an option the new setup tool had dropped.
Her own restarts can never replace the launcher, and the error went only to its console. Decision (owner): the
resident launcher only starts and watches DSH; each start's preparation (sync, install, selections) runs as a fresh
`asuna-launch.mjs --prepare <rung>` process from the code on disk, and its output is kept in
`<data>/restart/prepare.log`, with a failure's last lines in the restart record she reads. What remains resident
(the supervise loop in `asuna-supervisor.mjs`) still needs a launcher restart to change.

## Addendum 2026-10-20: a start that failed for the environment pinned her to old code

Her restart at 23:21 NZDT to install `0e622df6` (records `.runtime/restart/last.json`, `history.jsonl`, `host.log`; Host startup logs `.runtime/adr008/home/logs/startup-*`):

1. The first start failed as DSH activated its credentials store: `EMFILE: too many open files` opening `.credentials.yaml.lock`. The cause of the EMFILE is not yet known.
2. The lock was left empty (created, never given its process id). DSH takes over a lock whose recorded process has exited, but an empty one names none, so the next two starts timed out waiting on it and the ladder went on retrying every minute. Claude removed it by hand (23:23:49, no Host process alive); the next start came back at 23:24:30.
3. The second rung had returned core and persona to the previous running version, so she came back on old code. Her next restart (23:31) installed nothing: the launcher compares the packed digests with `launch.json`'s record of the last install, which still named the set-aside package, so the checkout looked installed.
4. The record said the new packages loaded: `loaded.packages` came from `launch.json`, and `reverted_from` printed a field the selection does not have, so it was empty. Xiaoman found both by reading the code and checking the running files' digests.

Decided by the owner 2026-10-20 ("launcher fixes first"), built:

- A package a start set aside counts as not installed, so the next start installs the checkout again (`changedPackages`, `setAsideDigests`). A start that fails again falls back again; nothing is retried in a loop beyond the ladder's own.
- Before each start the preparation removes empty writer locks at the top of DSH's home (`clearEmptyLocks`); at that moment no Host runs, so no writer exists. Locks that name a process stay DSH's.
- The record reports a selected package's running digest and the digest it returned from (`loaded`).

Not changed: the ladder still blames the new package for any failed first start. With the first fix, a package set aside for an environment fault is installed again by the next start. The record's fix runs in the resident launcher, so it applies once the launcher itself is restarted; the other two are in the per-start preparation and apply at the next start.

## Addendum 2026-10-21: why the start ran out of file handles

Investigated the night of 2026-10-20 (Claude; scratchpad test `emfile_limit.mjs`, counts of `.runtime/adr008/home/storages/session_projcache/sessions`):

- One Node process on this Windows host holds at most 8,189 files open; the next open fails with EMFILE. An exclusive create (`wx`) that fails this way leaves an empty file behind: that is the empty lock of 23:22.
- DSH loads a `per-record` JSON table by reading every file at once (`dsh-storage-json` `loadTableRecords`, an unbounded `Promise.all`). The session projection cache is such a table, and at each start it is loaded while other plugins open files, so past about 8,000 records a start can fail on whatever opens next, the credentials lock that night.
- The cache held 8,780 records; 7,939 (90%) were of sessions no longer in the store: 6,291 retired to the archive by the launcher (summaries, gate looks), 1,648 already dropped from it. Retiring moved a session's folder but not its record. The cache passed 8,189 records on 2026-10-18 17:58; from then each start was a race, lost once.

Fix here (owner, 2026-10-21): before a start, the preparation removes projection-cache records of sessions no longer in the store (`pruneProjectionCache`), so the cache follows the live sessions (about 840). The bounded loading and an empty lock's recovery belong to DSH, the owner's fork.

