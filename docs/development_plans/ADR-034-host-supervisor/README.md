# ADR-034: a supervisor that restarts the Host for her and brings it back

Status: **Accepted 2026-10-10.** The owner chose the direction ("Yes, I'd like a means of self rebooting/fallback
routine"); Xiaoman agreed and added D7. This is option 2 of ADR-021 §4.

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
