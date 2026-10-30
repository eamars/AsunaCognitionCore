# ADR-112: A working task cut at the stage limit, and the restart loop that followed

Status: **Open**. Two fixes are installed (§6). The root causes are identified (§5). What is still open (§7) is not
designed here.

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
| 2. A task paused by a restart does not hold the night stage (`night_stage_busy` reads `READY`, `RUNNING`) | `868c26e6` | 00:21:03 | Regression test `test_a_self_development_task_paused_by_a_restart_does_not_hold_the_night` fails without it. The night of 10-31: the night plan's check at 01:07:16 returned `ENQUEUED` (`audit_events`, `schedule.dispatched`; `plans.last_stage_at` 01:07:16), the first since 10-25 05:37, and that night turn (`ep-543d9466…`) ran to `COMMITTED`. `task-d55513ac` was still `PAUSED` after it: hers to decide. |

Both landed through the usual landing: suite, integration, start check, push gate, her slot asked first, the restart,
the loaded commit and all 166 installed files checked. She confirmed both installs on her side (her messages 0336,
0337).

## 7. Still open

Not designed here:

- **C1, the limit itself.** The owner's decision, open since ADR-084 §10.
- **C2.** A publish that went through while her task records a failure. The Host's selection already carries the
  publishing task (`origin.task_id`), which a start could use to give that task its true result. Proposed, not
  designed.
- **C4.** Evidence retention that a restart loop cannot erase.
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
