# ADR-112: A working task cut at the stage limit, and the restart loop that followed

Status: **Open**. Two fixes are installed (§6). The root causes are identified (§5). C2 (§9) and C4 (§10) are
designed, built and reviewed (§11) on branch `claude/focused-hamilton-wy3xp7`, not yet installed. C1 and the paused
tasks without an end are the owner's decisions (§7); the 12:39 crash is not explained.

All times are New Zealand local time (NZDT, UTC+13), 2026-10-30 evening to 2026-10-31 early morning, unless marked UTC.

## 1. The ask

The owner, 2026-10-30 23:4x:

> Check her home line, and check if her DSH crashed recently? And it seems her development tasks were all messed up.
> I rebooted once but not recovering.

The owner, 2026-10-31 00:3x:

> Let's don't rush, and write the ADR of symptom first.
>
> Noted I want root cause to be evaluated, identified.

In scope: what went wrong on the live system on the night of 10-30, and why. The two fixes already installed that
night are recorded as facts. Designs for what is still open are separate work.

## 2. Symptoms

What the owner and she saw, and what the records show.

| # | Symptom | Source |
|---|---|---|
| S1 | Her worker restarted 11 times in 31 minutes, 23:37:06 to 00:08:09, every time `worker asked: published-worker` (one at 00:01:37: `a restart requested during the last one`). DSH itself did not crash. | `.runtime/worker-restarts.jsonl` |
| S2 | The owner's launcher restart at 23:42 (`restart-20261030104200`) did not stop it: the loop went on from the new start. | `.runtime/restart/history.jsonl`, S1 |
| S3 | Each new task of hers was paused by the next restart 14 to 29 s after it was created, before it ran (`pause_reason: host_restart`, `paused_state: READY`). She cancelled two of them herself and sent them again (23:39 `task-1728e6ba`, 23:45 `task-2fc77a67`, `cancel_reason: character_stop`); two are still paused (23:51 `task-5afc50d4`, the daily self-review; 23:57 `task-abba75af`, the check that the faces change took effect). | `tasks` |
| S4 | Her 23:07 task (`task-8b579a2a`, the faces change the owner decided that evening, from her QQ DM with the owner) ended `BLOCKED` with `NATIVE_STAGE_TIMEOUT`; its last publish call ended `raised`. Yet that publication (`c22436ec`) was installed and has been running since. Her record of the task says the opposite of what happened. | `tasks`, `audit_events` (`tool.time`), `.runtime/adr008/activation.json` |
| S5 | The agent line refused connections 23:37 to 23:48 (`WinError 10061/10054`). | the line watcher's log |
| S6 | She saw only one stop (23:42) on her side: her start records are Host level, and the worker restarts of S1 are not. | her message 0335, 00:08 |
| S7 | Her night stage has not run since 10-25 05:37. The night plan's check was refused `STAGE_BUSY` 150 times: every 10 minutes, 01:07 to 05:57, on each of the nights of 10-26, 10-27, 10-28, 10-29 and 10-30, 30 a night. | `audit_events`: `stream_id = plan-asuna-self-development-night`, `type = schedule.dispatched`, `payload.outcome = STAGE_BUSY`; `plans.last_stage_at` |
| S8 | The Host reports of the first runs of the loop were gone within minutes: the worker keeps the reports of its last 5 starts, and the loop started a new one every 2 to 6 minutes. | `KEPT_HOST_REPORTS = 5` (`src/asuna/native_worker.py`), `.runtime/reports/` |

## 3. Timeline

| Time | What happened | Source |
|---|---|---|
| 23:07:05 | Her faces task `task-8b579a2a` starts its action stage. | `audit_events` |
| 23:25:31 | Its first core publication (`ff05bb0e`, receipt `self-publish-569c3b54…`), state `APPLIED`. The Host marks a restart pending; it waits, because a turn is active. | `sink_receipts`, Host reports |
| 23:33:06 | Its napcat-qq publication, applied in place, `ACTIVE`. | `sink_receipts` |
| 23:36:51.8 | It calls `development_publish` a second time (the 424 rename, `c22436ec`). | `tool.time` (ended 23:37:06.296 after 14.453 s) |
| 23:37:05.9 | Its stage reaches 1,800 s since 23:07:05. | `workflow_timeout_seconds` |
| 23:37:06.062 | The task is written `BLOCKED`, `NATIVE_STAGE_TIMEOUT`, feedback `READY`. | `audit_events` seq 717 of the task's stream |
| 23:37:06.295 | The worker asks for the pending restart. | `worker-restarts.jsonl` |
| 23:37:06.296 | The publish call in flight ends `raised` in the stopping worker. | `tool.time` |
| 23:37:08.069 | The Host completes that publish and selects it (`self-publish-78492805…`). No worker records it. | `activation.json` |
| 23:37:30 | The new worker reports what it loaded: `78492805` is written as `native_recovery_publish` (no record of it existed). `569c3b54` stays `APPLIED`. | `sink_receipts` |
| 23:39 to 00:08 | After each turn ends, the Host finds `569c3b54` `APPLIED` and asks for a restart: S1, S3. | `worker-restarts.jsonl`, Host reports `restart.pending/blocked/requested` with that receipt id |
| 23:42 | The owner's launcher restart, commit `c22436ec`. The loop goes on (S2). | `restart/history.jsonl` |
| 00:08:34 | Fix 1 (`f144c650`) installed at her slot (her message 0335). Back 00:09:10. | `land_1031_000919.txt` |
| 00:09:10 | The first start with it marks `569c3b54` `SUPERSEDED`. No restart is requested after it. | `sink_receipts`, `worker-restarts.jsonl` |
| 00:20:29 | Fix 2 (`868c26e6`) installed at her slot (her message 0336). Back 00:21:03. | `land_1031_002109.txt` |

## 4. Earlier, separately

- **The paused self-development task.** `task-d55513ac` (fetching back her words from the late-night TTS work of 10-24)
  was created 10-25 08:48 by a self-development turn and paused by a restart at 08:51. It is still paused. It is the
  cause of S7 (§5, C5).
- **One worker crash.** 10-30 12:39 the worker exited `3221225477` (`0xC0000005`, an access violation in native code),
  with no Python traceback. It is the only `exited (…)` in `host.log`. It is not part of this incident and is not
  explained.

## 5. Root causes

Each link says how it is known. "Verified" means read from the records named; "from the code" means read from the code
at the installed commit, with no record of the moment itself.

### C1. The stage limit cuts working tasks

`workflow_timeout_seconds` (1,800 s) is a deadline set once when an action stage starts (`NativeLane.wait`: `deadline =
time.monotonic() + timeout`), whatever the stage is doing when it arrives.

- Verified: 8 of her 14 `BLOCKED` tasks ended this way (10-10, 10-12, 10-13, 10-17, 10-22 twice, 10-28, 10-30). Every
  one was cut 1,800 s (one 1,801 s) after its first record, and every one was still working: its last tool record came
  2 to 156 s before the cut (`audit_events`, the task's `state.commit` of `artifacts` before the `BLOCKED` commit).
  They had 81 to 164 tool steps.
- Known before: ADR-084 §10 (2026-10-22) counted seven of these and made the stop say so in words. It left the limit
  itself open as the owner's decision. Tonight shows a consequence that section did not have: the cut can fall in the
  middle of a tool call that changes something.

**Broken invariant:** a limit meant to catch a stuck stage also ends a stage that is making progress.

### C2. A tool call outlives its task, and the restart gate cannot see it

- From the code: when the stage times out, `wait` raises, the task is closed, the controller clears `active_task`
  and calls `on_turn_finished`, which runs the publish restart check at once. The executor's tool call already in
  flight is not waited for: it runs on a dispatcher thread (`Dispatcher`, `asuna-dispatch`) as a `host_call` to the
  Host.
- From the code: the publish restart gate (`RuntimeHost._maybe_restart_after_publish`) stops the worker once neither a
  turn (`controller.active`) nor a task (`controller.active_task`) is active. An in-flight tool call is neither.
- Verified by the timeline: the restart was asked 233 ms after the task was closed and while its publish call was in
  flight; the call ended `raised` 1 ms later, and the Host completed the publish 2 s later.
- Result, verified: the publish went through but her task records it as a failure (S4). She had to send a separate
  task to check whether her change took effect.
- Not verified: that no other kind of in-flight call was cut the same way on other nights. Before ADR-109 (10-30)
  there were no `tool.time` records to show it.

**Broken invariant:** "nothing is active" is read as "nothing is in flight", but a call of a closed task still is.

### C3. A publication's state is kept twice, and one copy can miss an update

- From the code: what is selected and loaded lives in the Host's selection (`activation.json`, `floor.js`). The
  worker keeps its own receipt in `sink_receipts`, written when the publish answer reaches it. The restart decision
  reads only the worker's copy: any core receipt still `APPLIED` means "restart to load it".
- From the code: an older receipt was closed (`SUPERSEDED`) at one moment only: when the worker recorded a newer
  publication's answer.
- Verified: the 23:37 answer never reached a worker (C2). So `569c3b54`, overtaken by `78492805` before any start
  loaded it, stayed `APPLIED`, and every start asked for a restart that could never load it: S1, S2, S3.

**Broken invariant:** a receipt that will never be activated reaches a final state on every path.
Fixed (§6, fix 1). The class is closed at the one moment that always happens: each start reconciles the worker's
copy with what the Host loaded.

### C4. The evidence went before it could be read

- Verified: the worker keeps the Host reports of its last 5 starts (`KEPT_HOST_REPORTS`). With a start every 2 to 6
  minutes, the reports of the 23:37 run were gone before anyone looked. The evaluation above rests on the database's
  `audit_events` instead, which survived.

**Broken invariant:** the evidence of an incident survives the incident. A count-based retention is erased by the very
failure (repeated starts) it would be needed for.

### C5. A paused task counted as work in progress

- From the code: `schedule.night_stage_busy` held the night stage while a self-development task was `READY`, `RUNNING`
  or `PAUSED`.
- From the code: a task paused by a restart never resumes by itself. She can stop it (`task.stop`); only the owner can
  have it continued (`coordinator`: 「这件事在重启时暂停了：只有主人明确要继续时才能接着做。」).
- Verified: `task-d55513ac` paused 10-25 08:51 → S7, five nights. A deadlock: the paused task waited for her decision,
  and the night stage, where she would have seen it and decided, waited for the task.

**Broken invariant:** a state that has no exit of its own was counted as live work.
Fixed (§6, fix 2).

### The class

C2, C3 and C5 have the same shape: a stored state says one thing ("blocked", "applied", "at work") while the system
is in another (the publish succeeded, it will never load, nobody is working). C1 is what set this night off; C2 and C3
turned one cut-off stage into a loop.

## 6. Installed on the night

| Fix | Commit | Installed | Verified |
|---|---|---|---|
| 1. A started worker supersedes a publication it did not load (`native_worker.supersede_waiting`, called by `publication.activated` too) | `237dc1c4` + map `f144c650` | 00:09:10 | `569c3b54` `SUPERSEDED` at 00:09:10 by `native-install-8f68748d…`; no `APPLIED` receipt left; no restart requested since. Regression test `test_a_started_worker_supersedes_a_publication_it_did_not_load` fails without the fix. |
| 2. A task paused by a restart does not hold the night stage (`night_stage_busy` reads `READY`, `RUNNING`) | `868c26e6` | 00:21:03 | Regression test `test_a_self_development_task_paused_by_a_restart_does_not_hold_the_night` fails without it. Tonight's first night stage (01:07) is still to be read. |

Both landed through the usual landing: suite, integration, start check, push gate, her slot asked first, the restart,
the loaded commit and all 166 installed files checked. She confirmed both installs on her side (her messages 0336,
0337).

## 7. Still open

Not designed here:

- **C1, the limit itself.** The owner's decision, open since ADR-084 §10.
- **C2.** Designed and built in §9.
- **C4.** Designed and built in §10.
- **Paused tasks have no end** but her stop or the owner's "continue". Open on 10-31 00:40: `task-b141054d` (10-16,
  agent home line), `task-d55513ac` (10-25), `task-5afc50d4` and `task-abba75af` (23:51 and 23:57). The owner's
  restart policy; left as it is unless he decides otherwise.
- **The 12:39 crash** (§4). One occurrence, not explained.

## 8. My own errors that night

- I first edited the fix in the main checkout, where her publications commit. I moved it to a worktree before any
  commit.
- I pushed her three unpushed commits (`ff05bb0e`, `26168725`, `c22436ec`) through the push gate with the wrong base,
  so the first run scanned nothing. A rescan of the real range (12 message lines, 215 added lines) found 0 hits.
- I first wrote "10-25 to 10-29" to her for the blocked nights. Those were UTC dates; the local nights are 10-26 to
  10-30. I corrected it to her the same hour.

## 9. C2: a call in flight holds the restart, and a start gives a lost publication to its task

Written from the code at `9b2fe32` and the records quoted in §2 to §5; the live data was not read for this section.

### 9.1 What the code does, end to end

1. Her action brain's tool call reaches the worker as a `tool` request, which the dispatcher runs on a thread of its
   own (`DETACHED`). The call checks its stage once, at its start (`pending[operation]`), then runs:
   `ToolBroker.call` → `NativeDevelopmentBridge.call` → `host_call('development')` waits up to 120 s for the Host.
2. The stage's deadline passes in `NativeLane.wait`: `TimeoutError`, `task_fenced` to the plugin, the operation
   leaves `pending`. The executor closes the task `BLOCKED`. The task thread's `finally` clears `active_task` and
   calls `on_turn_finished` → `RuntimeHost._after_turn` → `_maybe_restart_after_publish`.
3. The gate saw `569c3b54` `APPLIED`, `active` and `active_task` both empty, and asked for the restart. The plugin
   restarted the worker; `BusinessWorker.close` failed every waiting `host_call` with `DSH_HOST_DISCONNECTED` (the
   `raised` 1 ms later); the Host's publish went on in the plugin and finished 2 s later with no worker to answer.
4. The started worker got the selection in `publication.activated`, found no receipt for `78492805`, and wrote a
   `native_recovery_publish` row. `_complete_activations` offers her only `self_development_publish` receipts, so
   her task was never told.

The worker already knows every call in flight: `tool_watch.Calls.flight`, with each call's limit. Nothing that
decides a restart read it. Four checks decide one, each reading "at work" its own way, and none counted a call:

| Check | Stops the worker when | File |
|---|---|---|
| the publication restart | a core receipt is `APPLIED` and no turn or task is active | `host.py` `_maybe_restart_after_publish` |
| her quiet restart | no turn, task or queued work (or after `QUIET_MINUTES`) | `restarts.py` `Desk.quiet` |
| a settings apply | no turn, task, stage or queued work | `native_worker.py` `settings.quiesce` |
| a recovery activation | the worker's `status` shows no turn, task or queued work | `index.js` `activateRecovery` |

### 9.2 Design

**D1. A call in flight within its limit holds every restart that waits for quiet.** `Calls.holding()` counts the
calls in flight not yet past their limit (600 s, or a timed tool's own timeout + 120 s; a development call ends
sooner, at its `host_call` wait of 120 s), and `tool_watch.holding()` sums it over every `Calls` of the process (the
worker has one). The controller reads it itself (`Chat.calls_in_flight`), so no wiring at start can leave a check
blind, and all four checks read it; `status` reports it as `calls_in_flight`, which an older plugin ignores and a
newer plugin reads as 0 from an older worker. The publication restart's watch loop also looks while a restart is
pending, because no turn ends when the last call does; a core publication recorded `APPLIED` asks the gate at once,
from the call that recorded it, because a task already closed has no turn left to end. `restart.blocked` is recorded
at each change of what holds the restart (`held_by`: turn, task, calls), not once per worker: at 23:25 the restart
was already held by the task, and the hold by the call after the cut would otherwise leave no record. A restart
pending when no core publication is `APPLIED` any more (overtaken by one byte for byte the running one, or by one that
needs the Host restarted) is withdrawn, `restart.withdrawn`: before, it held her queues until a restart from outside,
and the watch loop would have polled for it for ever.

- Slow call: the restart waits for it, and so do her turns and tasks, which hold while a restart is pending: up to
  the call's limit, 600 s for most tools. The usual call held at a cut is a publish answered within seconds.
- Failing call: it ends, and the restart follows within 0.5 s.
- Hung call: it holds the restart until its limit, where the watchdog has already recorded it (`host.tool_overrun`);
  the restart then goes ahead and is its recovery. Nothing waits without a bound.

**D2. A started worker gives a publication no worker recorded to its task.** In `publication.activated`, a
publication with no receipt whose Host record names its task (`origin.task_id`, a task that exists, in the
`origin.scope_key` it was published from) is recorded as that task's `self_development_publish` receipt, as the
publish path records it. `_complete_activations` then offers her its result as it does every other's. A selection
with no task (an install by the launcher, `native-install-*`) stays `native_recovery_publish`.

D1 removes the cause seen that night. D2 closes the class for every other way a worker stops between the Host's
publish and the answer: a crash (§4), a restart from outside, a `host_call` past its 120 s wait. It is the same
choice as fix 1: settle the record at the one moment that always comes, a start.

### 9.3 Review: does it reach the root cause?

- **Replay of 23:37 with D1.** 23:25 the restart goes pending, `restart.blocked` held by the task. 06.062 the task
  closes; the gate finds `569c3b54` `APPLIED` and is held by the publish call (started 23:36:51.8, well within its
  limit): `restart.blocked` again, `held_by: calls`, `calls_in_flight: 1`. About 08.07 the Host answers; the worker records `78492805` for task `8b579a2a` and marks
  `569c3b54` `SUPERSEDED` (fix 1's helper); the call then ends `raised` at the broker's closing fence (its task is
  closed: by design a call's answer never revives a closed task) but the receipt is already written. The watch loop
  sees no call and asks for one restart. The started worker activates `78492805` and offers her its result for that
  task. No loop, no lost publication, one restart.
- **Without fix 1**, D1 alone would also have prevented the loop, because the newer receipt would have been recorded.
  With both, each covers the other's failure.
- **C1 is not touched.** The stage still ends at 1,800 s; D1 only stops the restart cutting what the cut left
  running. Draining a task's calls before closing it would lengthen the stage past its limit, which is the owner's
  decision (§7).
- **Not a bandage for one tool.** D1 holds for any call of either brain on the four restarts that wait for quiet.
  Restarts that do not wait (her `when: now`, her quiet request's fallback after `QUIET_MINUTES`, a restart after the
  worker fails, the launcher's, the supervisor's, a recovery activation from an older plugin) still cut a call in
  flight; for a publication, D2 settles its record at the next start whatever stopped the worker.
- **Her task's own record stays `BLOCKED`** with the stage cut at its limit, which is true. The publication's
  result reaches her the way every core publication's does, after the restart, naming the task.
- **Existing rows.** The recovery row written for `78492805` that night is left as it is (D2 acts only where no
  receipt exists). Whether that task should still be told is the owner's choice; it needs no code.

### 9.4 Tests that earn their place

| Test | Guards | Fails without |
|---|---|---|
| `test_host.py` `test_a_publication_restart_waits_for_a_call_its_closed_task_left_in_flight` | the 23:25 to 23:37 sequence: held by the task, then by the call, each recorded; asked once the call ends | D1's gate, the record per change, the watch loop |
| `test_host.py` `test_a_pending_restart_with_nothing_left_to_load_lets_the_queues_go_on` | her queues held for ever by a restart with nothing to load | the withdrawal |
| `test_tool_watch.py` `test_a_call_in_flight_holds_every_restart_that_waits_for_quiet` | the checks read the process's calls through a real `Chat`: her quiet restart, a settings apply | `Chat.calls_in_flight` |
| `test_tool_watch.py` overrun test, `holding` at 149 / 151 / 601 s | a hung call cannot hold a restart for ever | `holding`'s limit |
| `test_native_worker.py` `test_a_started_worker_gives_her_task_the_publication_no_worker_recorded` | S4: the task is told; an install, and a task in another scope, stay a recovery | D2 |

Each was run with its fix reverted (the whole change; the watch-loop line alone; `Chat.calls_in_flight` returning 0;
the record once per worker; no withdrawal) and failed. Suite figures are in §11.

### 9.5 Landing

One core landing: the suite, `pytest integration`, the node tests (`npm run test:native`: one line in `index.js`,
not run in the cloud session that built this), the push gate, the restart, the loaded commit checked. Then read on
the live system: the next `restart.blocked` record carries `held_by` and `calls_in_flight`, and a stage cut at its
limit during a publication leaves a `self_development_publish` receipt for its task.

Before the restart, compare the receipt ids in `activation.json` (`projects` and `active`, and each one's `previous`)
with `sink_receipts`: the first start with D2 records, and offers her, any selected publication with no receipt whose
task still exists in the same scope. None is expected (every selection has had a receipt or a recovery row since its
first start); one found is an old result she would be told about, and the owner decides before the restart.

### 9.6 Not in this change

- **C4**, evidence retention: §10.
- **C1**, **paused tasks without an end**, **the 12:39 crash**: as in §7.

## 10. C4: the evidence of a start outlives a loop of starts

Written from the code at `83e1493`; the sizes of the live reports were not read for this section (§10.5 reads them).

### 10.1 What the code does

- Each worker start writes its Host report to a new folder, `<data>/reports/native-host-<10 hex>`, one JSON file per
  record (`Evidence`). Within a start only its newest 3,000 records stay (`KEPT_HOST_RECORDS`), besides the pinned
  kinds `runtime.ready` (the supervisor's proof that the start came up, `readySince`) and `clock.zone`.
- At each start, right after its own folder is made, `prune_host_reports` sorts the `native-host-*` folders by their
  last write and removes all but the newest 5 (`KEPT_HOST_REPORTS`).
- What reads the folders: the supervisor (`asuna-supervisor.mjs` `readySince`, one stat per folder while it waits for
  a start), people and agents after an incident. Nothing else.
- What only they hold: the restart trail (`restart.pending`, `restart.blocked` with what held it, `restart.requested`
  with the receipt), `host.task_paused`, `chat.task_error` tracebacks, `host.tool_overrun` stacks, the recovery
  timings. The database's `audit_events` hold neither these nor the process's view of a start.

So the unit of retention is the start, and the bound is a count. A start costs what it writes, not one unit: a
start that lives 2 to 6 minutes writes far fewer records than one that lives a day. The count bound erased eleven
small reports and kept five, sized for five full ones.

### 10.2 How retention is usually bounded

Log stores bound by age and by size together and never by count of files alone: journald (`MaxRetentionSec` with
`SystemMaxUse` and `SystemMaxFiles`), logrotate (`maxage` with `size`), Windows event logs (a size, then overwrite).
The age says what must survive; the size is the disk's safety bound; reaching the size bound is itself reported.

### 10.3 Design

**D3. Kept by time, bounded by size; an erasure the bound forces is recorded.**

- **Kept:** the newest 5 starts (as now: the start before a quiet week explains why it ended), and every start that
  wrote in the last 48 hours (`KEPT_HOST_REPORT_HOURS`), however many starts that is. Age is from the folder's last
  write, read against `asuna.clock`.
- **Bounded:** at most 60,000 records (`HOST_REPORTS_MOST_RECORDS`, twenty full starts) and 1,000 starts
  (`HOST_REPORTS_MOST`) in all. The unit is a record, the same unit as the per-start bound, so no file-system
  accounting is needed; a record is one small file (about 0.4 to 1 KB, a stack or traceback a few KB). The start
  bound keeps the supervisor's stat per folder bounded when starts write almost nothing (a crash at start).
- **Order:** newest first. The current start always stays. When a wanted start does not fit, it and every older one
  go, so what is kept has no gap.
- **Said:** when the bound removes a start the rule wanted, the new start records `host.reports_pruned` (how many
  starts it removed, how many of them it wanted, the starts and records kept, and the age of the oldest kept), a
  pinned kind. Nothing is recorded on the normal path.

What it costs: the old bound was at most 15,000 records; the new one is at most 60,000, about 25 to 60 MB in file
bytes. A start's prune lists each kept folder once (`os.scandir`: on Windows the listing carries what is needed
without a stat per file).

**Considered and left out.** Pinning the restart trail within a long start: a busy hour writes about a thousand
records, so a restart held for 30 minutes keeps its trail well within 3,000; nothing shows it was ever lost. Copying
the trail into the database: the audit has a retention of its own (ADR-074), and the files are enough once they
are kept.

### 10.4 Review: does it reach the root cause?

- **Replay of 10-30.** The loop's starts (23:37 to 00:08, eleven, each a few minutes) and the start that ran the cut
  task are all within 48 hours of anyone reading them on 10-31; together they are far below 60,000 records. All
  kept. The same night under the old rule kept five.
- **A loop left running.** A loop of light starts (a hundred or so records each) reaches the 1,000-start bound after
  about 33 hours at one start every 2 minutes, which a person notices well before: each restart pauses her tasks.
  When it does reach it, the erasure is recorded, so the report says the evidence is incomplete rather than looking
  complete.
- **A quiet system** keeps what it kept before: its newest 5 starts, plus anything of the last two days.
- **Two sides at different versions.** Only the worker prunes; the supervisor's reading of the folders is unchanged.
  One gap: when the supervisor falls back to the core that ran before this change (`previous`, after starts that do
  not come up), that older worker prunes back to five reports, erasing the evidence of that very fallback. It lasts
  until the core that falls back is one with D3.
- **The broken invariant** was "a count-based retention is erased by the very failure it is needed for". The kept set
  no longer depends on the number of starts within 48 hours, and a bound reached is visible.

### 10.5 Tests and landing

| Test | Guards | Fails without |
|---|---|---|
| `test_native_worker.py` `test_host_reports_of_a_restart_loop_outlive_the_loop` | a dozen short starts in an hour all kept; old starts beyond the newest 5 removed | D3 (the old rule keeps 5) |
| `test_native_worker.py` `test_host_reports_past_their_bound_go_oldest_first_and_say_so` | the bound on disk, no gap, `host.reports_pruned` recorded | D3's bound |

At landing, before the restart, read the size of `<data>/reports/native-host-*` (records and bytes per start) and
check that a full start is near 3,000 records and a few MB. After the restart: the reports of the previous starts of
the last two days are still there.

## 11. Review

A fresh reviewer read §9 and §10 against the code at `3fb3d2e` and the working tree, told to judge the code and not
the prose: whether C2 and C4 are closed, other paths that stop the worker, waits that could last for ever, the new
code's edge cases, the two sides at different versions, whether the tests fail without their fixes, and the
references. Its verdict: D1 closes C2 on the path of that night (the receipt is written before the call ends, so one
restart follows), D2 settles every other stop, D3 closes C4 up to its bound. Its findings, each checked against the
code, and what was done:

| # | Finding | Done |
|---|---|---|
| 1 | The hook carrying D1 was one assignment at start, guarded by no test: deleting it would bring C2 back with every test green. | The hook is gone: `Chat.calls_in_flight` reads the process's calls (`tool_watch.holding`). Test through a real `Chat`, her quiet restart and a settings apply (§9.4). |
| 2 | `restart.blocked` was written once per worker; at 23:25 it was already written, so the hold by the call after the cut would leave no record, and §9.3's replay and §9.5's check would read a stale one. | Recorded at each change of what holds it, with `held_by` (§9.2). |
| 3 | A restart pending when nothing core is `APPLIED` any more held her queues until a restart from outside (older than this change), and D1's watch loop would poll for it every 0.5 s for ever. | Withdrawn, `restart.withdrawn` (§9.2), with its test. |
| 4 | Her turns and tasks wait while a call holds the restart, up to its limit; §9.2 said only that the restart waits. | Said in §9.2 and RUNTIME_API. Left at the call's limit: holding a closed task's call only for its own wait would need a second limit per tool, and the usual held call is answered within seconds. |
| 5 | A cut task's first core publication, recorded after the task closed with no restart pending, would wait for some later turn to end. | The publish path asks the gate as it records an `APPLIED` receipt (§9.2). |
| 6 | A supervisor fallback to the core before D3 prunes back to five reports. | Stated in §10.4; it ends once the fallback core has D3. |
| 7 | D2's first start could offer her an old result for a selection with no receipt. | A check before the landing's restart (§9.5). |
| 8 | D2's test covered neither a task in another scope nor a missing one. | Another scope added to the test (a missing task takes the same branch). `host.reports_pruned` being written at start is not tested: `initialize` needs the whole Host; the prune's result it records is. |
| 9 | §9.3 said D1 holds on every restart path; restarts that do not wait for quiet still cut a call. `Desk.preview` told her nothing was running while a call was. The references carried reasons, and omitted the recovery activation. | §9.3 corrected; `Desk.preview` names the calls still out; RUNTIME_API and DEVELOPMENT corrected. |

Checked and fine by the reviewer: `Calls.holding` (no lock order against the controller's), no new call can join a
stage once it is cut, the character brain's calls covered by its turn, `prune_host_reports` (kept starts are a prefix
of the newest-first order, the current start always kept, mtime is the last record written on Linux and NTFS), the
supervisor's `readySince`, and the version skew of `calls_in_flight` in `status`.

Suite after the fixes (`tests/`, in the cloud session, no `config/local.json` and no node): 845 passed, 30 skipped,
3 failed, the same 3 that fail at `9b2fe32` there (`test_no_server`, two in `test_refusal_probe`). Not run there:
`pytest integration` and `npm run test:native` (§9.5).

