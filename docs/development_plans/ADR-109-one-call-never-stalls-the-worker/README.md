# ADR-109: One tool call never stalls the worker

Status: **Proposed** 2026-10-30. Written by the lead (Claude). Direction decided by the owner the same day: child
processes for the pure heavy work of both brains (not every tool body), plus timing, overrun records and release for
every tool call; a wedged character-brain call is bounded and alerted, never restarted automatically (owner, the same
day). Revised after a cold review of the first draft (13 findings; the release in D3 did not reach any closing path).
Nothing is built. Owner's rule for this ADR: Xiaoman is not told until the root cause is resolved (installed and
checked); her read of the new wordings (§4) comes after that, not before.

## 1. What happened

On 2026-10-30 at 10:05:45 a task called `digest_authorized_discussion`. Its cursor-fit loop
(`discussion_digest.py`, `carry[:max(len(carry) // 2, 1)]`) never ended when the pending branches alone made the
cursor longer than 1,024 characters. It spun for 27 minutes until a restart at 10:32 (the loop itself is fixed in
`cc8c00627132`, installed 10:32). For those 27 minutes:

- every inbound admission took 8-12 s (8 `host.inbound_slow` records, 10:07-10:18); even the insert (`persist`)
  took 0.73-1.14 s instead of ~15 ms;
- the adapter and the agent line timed out on the channels server and the Host's late replies raised
  `ConnectionResetError` / `ConnectionAbortedError` (`channels.py:958-959`); the owner saw them in host.log;
- the worker process used one full core; the task looked healthy throughout;
- the only way to stop it was restarting the whole worker.

## 2. Root cause: three broken invariants

1. **Isolation.** The worker is one Python process. The front door (inbound admission, the channels HTTP server on
   8766 that serves the adapters and the agent lines, the outbox) and every tool body of both brains run as threads
   in it, under one interpreter lock. One CPU-bound thread makes every other thread wait for the lock after each
   blocking call. Measured offline (local socket pair, switch interval 5 ms): a round trip takes 0.018 ms alone and
   48 ms next to one spinning thread. A database insert is several round trips; that is the 15 ms → 0.9 s above.
   This holds for any CPU-heavy work in the worker, not only for a loop that never ends.
2. **Bounded.** A tool call has no deadline (`native_worker.py:1585`, `worker.js:60-69`: neither side times it), and a
   Python thread cannot be stopped. The executor's stage limit (`workflow_timeout_seconds`, 1,800 s,
   `native_worker.py:294`) ends the stage, not a body already running.
3. **Liveness.** Nothing records a call that runs long, and nothing releases its task. The lease is renewed by the
   claim (`tasks.py:466`), the keepalive (`tasks.py:508-522`) and each call's INTENT (`tasks.py:776`); and lease
   expiry could not close it anyway, because the orphan sweep skips the task the executor is running
   (`chat.py:562-563`, `handover.py:51-55`). A wedged call reads as healthy until the stage limit.

Two more paths of the same class:

- The effects lock (`TaskService.lock`, a thread lock plus a file lock) is held across `persona_job_run` (a job whose
  `timeout_s` her own job definitions set; core caps none), `list_files` (a walk with no count limit) and `read_file`
  (`tasks.py:783-784`). Every outbox claim, her words to QQ and the agent lines included, waits on that lock. The rule
  written right above that line already says never to hold it across a wait outside the process.
- A character-brain tool body runs on the turn thread, which holds `Coordinator.lock` for the whole turn
  (`coordinator.py:553`); the stage deadline is checked only between calls (`native_worker.py:337-341`). A wedged role
  body stops every later turn of hers, in every conversation (`ingest` takes the same lock, `coordinator.py:99-100`).
  Inbound admission is not behind this lock (`router.receive` runs on the chat thread, `chat.py:464`).

## 3. Facts the design rests on

Survey: `.runtime/private/tool-isolation/survey-1030.md` (code reading, both brains, file:line). Of the tool bodies,
15 must stay in the worker (Host round trips through the worker's stdio, closures built in the worker, worker
singletons); about 16 more would need a route back. So moving every body does not fit, and it would leave the CPU
work that is not a tool in place.

Measured durations, action brain, 7 days to 2026-10-30 10:50 NZDT (audit `state.commit` of artifacts, INTENT to
DONE/FAILED, 14,669 calls):

| Tool | n | p50 s | p99 s | max s | Where the time goes |
|---|---|---|---|---|---|
| sandbox_run | 7,320 | 0.20 | 25.2 | 508 | the Host's sandbox (a wait, not worker CPU) |
| development_run | 1,045 | 1.50 | 22.2 | 273 | the Host (a wait) |
| generate_image | 293 | 18.4 | 157 | 176 | the image model (a wait) |
| ask_character | 52 | 26.1 | 91.8 | 91.8 | her character brain (a wait) |
| read_image | 339 | 0.08 | 4.75 | 6.93 | download (a wait) plus decode and base64 in the worker |
| query_authorized_history | 173 | 0.96 | 3.26 | 3.38 | store reads plus Python over up to 200 rows a page |
| digest_authorized_discussion | 10 | 1.20 | 2.34 | 2.34 | the same, plus thread expansion (today's call never ended) |
| all others | ≤ 0.93 s max | | | | |

Calls that raised are not in this table (they leave only the INTENT row), and character-brain calls carry no start
time today. `memory_pilot.rank` (recall surfacing, context building, the pilot thread): 50 ms per call at her 1,243
active items of 768 dimensions, measured offline on synthetic vectors; linear in the item count.

So in normal running no tool spends minutes of worker CPU. The CPU in the worker is a small set of pure computations:
history, digest, animated-picture decode. Long calls are waits outside the worker, which release the lock.

## 4. Decisions

**D1. Pure heavy computations run in child processes, with a deadline and a kill.**

*The data child* (new kind `data`, supervised by `media_children.Child`) runs `query_authorized_history` and
`digest_authorized_discussion`.
- What the job carries: the task row, the tool's args, and a snapshot of the worker's config (deep-copied under the
  lock `persona.resources` takes when it changes it, `native_worker.py:1392-1404`), plus the channel packages the
  worker was initialized with (`native_worker.py:452`). The child loads those packages with `channel_kinds.load`
  (without them `person_ids` finds nothing and `verify_peer` answers `no_platform`, `peer_context.py:73-75`).
- What the child holds: one Store per database (its `config` replaced by each job's snapshot, since `Store.config` is
  fixed at construction, `state.py:114`) and one Retrieval, rebuilt when the snapshot's embedding settings differ from
  the ones it was built with. Its Retrieval embeds the query with the memory indexer's timeouts (10 s, 5 s to connect,
  `memory_indexer.py:25`), not the 180 s default (`evidence.py:68`), so a slow embedding endpoint falls back to
  lexical search inside the deadline, as it does today (`retrieval.py:59-66`). Retrieval's per-process state (the
  weight check, `resting_until`, its cache) starts empty in each new child; the pilot does not read this instance.
- It writes, as these tools do today: label rows (`people.py:492-500`, unique per scene and handle,
  `catalog.py:404`) and Retrieval's audit and evidence (`retrieval.py:92`, `:321-322`). Audit appends from two
  processes are safe (`state.py:165-176` retries on a duplicate key). Evidence is not written by the child: its
  records come back in the answer and the worker records them, so one process writes the evidence folder. A kill in
  the middle of a `put` leaves a document whose commit is missing; `recover_commits` reconciles it at the next start
  (`state.py:209`, run by `coordinator.py:599`).
- What comes back: the result passed through the same JSON conversion the worker applies today
  (`tasks.py:913-915`, `default=str`) before the frame is written, inside the child's try (an answer that cannot be
  written becomes a `program` error, never a dead child). A coded refusal (`Denied`, `ValueError`, `PermissionError`)
  comes back as its class and words and is raised again in the worker with the same words, so `error_text`
  (`native_worker.py:1537-1548`) says what it says today. Validation before and after the body stays in the worker,
  as today (both tools re-check `service.valid` after the body, without the effects lock).
- Times: deadline 30 s per job (10x the measured maxima); one job at a time; a job waits at most 30 s behind another
  (the concurrency is parallel calls inside one task: one executor thread, `chat.py:94`, one thread per call,
  `native_worker.py:1585-1587`); start at most 30 s. Budget 90 s. One try only.

*The picture child* (new kind `picture`: the video child's program and packages, PIL, in its own process) decodes
animated pictures (`animated.seen` of a picture with more than one frame, up to 1,500 frames, then base64) at the
three call sites `vision.py:678`, `:715`, `:747`. A still picture decodes in the worker as today (one frame, bounded by
the 8 MiB cap and PIL's pixel limit), so a picture child that will not start costs only animated pictures. Not the
video child itself: a picture she opens in a turn would then wait behind an inbound video's split (up to 120 s). With
no Host running (tools, tests), decode runs in process, as `video_snapshot` does (`media_children.py:394-396`). Times:
deadline 20 s, wait behind another 20 s, budget 45 s, one try. Her group turns open at most two pictures
(`TURN_PICTURES`, `role_tools.py:1092`), so a turn waits on this child at most 90 s.

*Changes to `media_children.Child`*: a `tries` setting (1 for both new kinds; voice and video keep 2); after a kill or a
death, a fresh child starts in the background at once, not on the next call; waiting out the budget behind another job
raises `Busy`, not `Timeout`, so each says what happened; `data`, `picture` and `tools` join `lane_faults.LANES`
(`lane_faults.py:22`) and `FAULT_LANES` (`media_children.py:39`), without which their faults are refused and lost.

*What she reads* (model-facing; the tool's own language):

| Case | Words |
|---|---|
| data job past its deadline | `QUERY_TIMEOUT: 这次查询超过 30 秒被停下了，没有结果；把范围收窄（时间窗、人、话题、limit）再试` |
| data job waited out behind another | `QUERY_BUSY: 前面还有一个查询在跑，这次没排上，没有结果；过一会儿再试` |
| data child not running | `QUERY_UNAVAILABLE: 做这次查询的后台程序这会儿没起来，这次没有结果；过一会儿再试` |
| animated picture past its deadline | `PICTURE_NOT_READ: 拆这张动图超时了，没有截图可看` |
| picture child busy or not running | `PICTURE_NOT_READ: 拆动图的程序这会儿用不了，这张动图没有截图可看；过一会儿再试` |

All are raised as `Denied`, so the call's artifact closes FAILED with these words (`tasks.py:921`).

**D2. No body holds the effects lock across work it does not bound.** `persona_job_run`, `list_files` and
`read_file` move to the set that runs without the lock and re-checks `service.valid` after the body (`tasks.py:783-784`),
the pattern every Host-waiting tool already uses (`persona.job_run` from the plugin already runs that way,
`native_worker.py:1368-1372`). The lock never protected the task folder: `sandbox_run` and the development tools write
there without it. `write_file`, `note_idea` and `report_progress` keep the lock (writes; measured max 0.93 s).
- `list_files` walks iteratively and stops at `LIST_FILES_MOST = 2000` entries (replacing `sorted(rglob)` at
  `tasks.py:260-261`, which walks everything before it sorts); it sorts what it has and says when it stopped there.
- `write_file` writes to a temporary file in the same folder and replaces the target (`tasks.py:273-275`), so a
  `read_file` or `list_files` running beside it never sees half a file.

**D3. Every tool call of both brains is timed; one past its limit is recorded, and an action call is released.**
- *Registry.* The worker keeps the calls in flight: call id, brain, tool, task or episode, thread, start, limit. Every
  call leaves it in a `finally`, which appends one audit event `tool.time` (stream: the task id or the episode id;
  call id, tool, `duration_s`, outcome `done` / `failed` / `raised`). One mechanism for both brains, and calls that
  raise are counted too. Volume: about 2,100 action calls a day plus her role calls, against ~72,000 commits a day.
- *Limit*: the call's longest stated wait plus 60 s.

  | Calls | Longest stated wait | Limit |
  |---|---|---|
  | `sandbox_run`, `development_run` | the call's `timeout` (≤ 600 s, `sandbox.py:16-17`) | timeout + 60 s |
  | `integration_test` | 60 s (`tool_args.py:16`) | 120 s |
  | `generate_image` | 330 s (`image_generation.py:36`, `integration.py:555`) | 390 s |
  | `persona_job_run` | the job's `timeout_s` | timeout_s + 60 s |
  | `ask_character` | a turn of hers (no own bound) | 600 s |
  | history, digest | the data child's budget, 90 s | 150 s |
  | `read_image`, `received_file` (both brains) | the vision pull timeout plus the picture budget | that + 60 s |
  | `recall` | two query embeddings at 180 s (`context.prepare` from `role_tools.py:1647`, then `memory_tiers.py:1062`) | 420 s |
  | role calls that reach the Host (`credential`, `set_policy`, `plan`, `group_focus`, ...) | `host_call`, 120 s (`native_worker.py:419`) | 180 s |
  | every other call | none (store work, measured ≤ 0.93 s) | 120 s |

- *Watchdog.* A thread looks every 10 s. A call past its limit gets one `host.tool_overrun` evidence record (call,
  tool, seconds, the thread's stack: 60 innermost frames, not the 12 of `host.inbound_slow`, `channels.py:30`), a
  lane fault (lane `tools`) and one warning line in host.log.
- *Release, action brain.* The worker fails that task's pending stage Future with
  `Denied('TOOL_OVERRUN: ...')` and emits `task_fenced` with reason `tool_overrun`, the route `task_fenced` already
  takes (`native_worker.py:918-927`); the plugin cancels the action session on it (`index.js:897-901`). The executor's
  failure branch (`tasks.py:1011-1022`) closes the task BLOCKED with failure type `TOOL_OVERRUN` and its own words
  (beside `STOPPED_AT_LIMIT`): `行动脑调的 %s 跑了 %d 秒还没结束，任务停在这里；它可能还在后台跑完，但结果不会再交回。已发起而没有回执的操作须先核实，不可盲目重做。`
  The body's thread may still finish; its result is refused by the post-check (`service.valid` after the body).
- *Character brain* (owner's decision): an overrun is recorded and alerted as above, never released; recovery is a
  restart by us, never automatic. This is safe to accept because every wait inside a role body already has a timeout
  (the table's rows; survey §1b) and D1 moves its CPU work out, so a wedge there can only be a code bug, and the record
  names it with its stack.

**D4. The rule, written where the next feature is designed.** `docs/DEVELOPMENT.md`, present tense: work in the
worker process whose cost grows with stored data or with a call's arguments runs in a child process with a deadline
(the data child, the picture child, the media children); a worker thread does only work with a stated bound. No body
holds the effects lock across a wait outside the process or a walk without a count bound. Data-sized work that stays in
the worker, each with its stated bound and the reading that would move it: `memory_pilot.rank` (50 ms at 1,243 items);
`task page` and the task feedback's observations (`tasks.py:157-179`: every artifact result of the task, and
`records_pages` quadratic in the record count), timed from the first day by D3's `tool.time`; credential scrubbing of
results (bounded by the result's size); the persona job data API (bounded by the job's `timeout_s`); the failure path's
file hashing (`tasks.py:938`, at most 20 files).

**D5. Static guard.** A test fails when anything in `src/asuna` outside the data child calls `query_for_task` or
`digest_for_task`; when `animated.seen` is called on a multi-frame picture outside the picture child's job (the three
`vision.py` sites go through `media_children`); or when a tool outside `write_file`, `note_idea` and
`report_progress` runs its body under the effects lock in `ToolBroker.call`.

## 5. Not chosen

- Every tool body in a child: 15 bodies must stay and ~16 need a route back to the Host; non-tool CPU stays exposed.
- Only the front door in its own process: inbound would be safe, her chat turns would still starve behind her tasks.
- A watchdog alone, or a shorter switch interval: both see or soften the starvation and leave it in place.
- Releasing a wedged role call (running role bodies off the turn thread): a deep coordinator change (the turn's state
  is written under the same lock); not now (owner).
- An automatic restart on a role overrun: her Host would restart on its own, mid-conversation, on a bug (owner: no).
- Vectorising `rank` now: 50 ms is bounded and small; written down instead (D4).

## 6. How it is proven

- Unit (in-memory adapter): the data child's job functions run in process against `asuna.store.memory`, with the
  channel kinds loaded; refusals come back with the same class and words; a result holding a non-JSON value comes back
  converted; the routing in `ToolBroker.call` against a fake child speaking the frames (`Child(command=...)`): timeout,
  busy, unavailable each give their words; `Child`'s `tries`, `Busy` and background restart; D2's lock set, the
  `list_files` bound and the atomic `write_file`; D3's registry (`tool.time` on done, failed and raised), each row of
  the limit table, the overrun record, the action release (the stage Future fails, `task_fenced` is emitted, the task
  closes BLOCKED `TOOL_OVERRUN`, the late result is refused) and the role record without release; D5's guard; the new
  lanes accepted by `lane_faults.record`.
- Process tests (no database): a real data child given a job that spins: killed past the deadline, `QUERY_TIMEOUT`, a
  lane fault, a fresh child started in the background; while it spins, socket round trips in the parent stay near the
  alone figure (the 0.018 ms vs 48 ms measurement becomes the assertion, with margin). The same for the picture child
  with an animated picture.
- Integration (`integration/`, throwaway database): the data child's Store opens, reads and writes a label row on a
  real server.
- After install, on the real system: `tool.time` for history and digest against §3's table (the child adds frames and
  JSON: expected milliseconds); `host.inbound_slow` counts against the 10-29 afternoon windows; the first
  `host.tool_overrun` or new-lane fault, if any, read when it comes; the first week of `tool.time` for `task page`.

## 7. Build and install

One build, one review, one install with its own restart (never stacked with ADR-108, which another agent builds; the
lead lands both, in the order they are ready).
