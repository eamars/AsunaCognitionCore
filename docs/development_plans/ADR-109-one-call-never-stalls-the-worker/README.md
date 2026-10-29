# ADR-109: One tool call never stalls the worker

Status: **Proposed** 2026-10-30. Written by the lead (Claude). Direction decided by the owner the same day: a compute
child for the pure heavy work of both brains (not every tool body), plus timing, overrun records and lease release
for every tool call. Nothing is built. Owner's rule for this ADR: Xiaoman is not told until the root cause is resolved
(installed and checked); her read of the two new wordings (§3, D1) comes after that, not before.

## 1. What happened

On 2026-10-30 at 10:05:45 a task called `digest_authorized_discussion`. Its cursor-fit loop
(`discussion_digest.py`, `carry[:max(len(carry) // 2, 1)]`) never ended when the pending branches alone made the
cursor longer than 1,024 characters. It spun for 27 minutes until a restart at 10:32 (the loop itself is fixed in
`cc8c00627132`, installed 10:32). For those 27 minutes:

- every inbound admission took 8-12 s (8 `host.inbound_slow` records, 10:07-10:18); even the insert (`persist`)
  took 0.73-1.14 s instead of ~15 ms;
- the adapter and the agent line timed out on the channels server and the Host's late replies raised
  `ConnectionResetError` / `ConnectionAbortedError` (`channels.py:958-959`); the owner saw them in host.log;
- the worker process used one full core; the task looked healthy throughout (its lease kept renewing);
- the only way to stop it was restarting the whole worker.

## 2. Root cause: three broken invariants

1. **Isolation.** The worker is one Python process. The front door (inbound admission, the channels HTTP server on
   8766 that serves the adapters and the agent lines, the outbox) and every tool body of both brains run as threads
   in it, under one interpreter lock. One CPU-bound thread makes every other thread wait for the lock after each
   blocking call. Measured offline (local socket pair, switch interval 5 ms): a round trip takes 0.018 ms alone and
   48 ms next to one spinning thread. A database insert is several round trips; that is the 15 ms → 0.9 s above.
   This holds for any CPU-heavy work in the worker, not only for a loop that never ends.
2. **Bounded.** A tool call has no deadline (`native_worker.py:1585`, `worker.js:60-69`: neither side times it), and a
   Python thread cannot be stopped. The executor's stage limit (1,800 s) ends the stage, not a body already running.
3. **Liveness.** The task lease is renewed on a timer (`tasks.py:518`), not on progress, and nothing records a call
   that runs long. A wedged call reads as healthy.

A fourth path of the same class, found by the survey: the effects lock (`TaskService.lock`, a thread lock plus a file
lock) is held across `persona_job_run` (a subprocess job), `list_files` (a walk with no count limit) and `read_file`
(`tasks.py:783-784`). Every outbox claim, her words to QQ and the agent lines included, waits on that lock. The rule
written right above that line already says never to hold it across a wait outside the process.

## 3. Facts the design rests on

Survey: `.runtime/private/tool-isolation/survey-1030.md` (code reading, both brains, file:line). Of the tool bodies,
15 must stay in the worker (Host round trips through the worker's stdio, closures built in the worker, worker
singletons); about 16 more would need a route back. So moving every body does not fit, and it would leave the CPU
work that is not a tool (context ranking, the pilot) in place.

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

Character-brain calls carry no start time today (one audit row at the end), so they are not in this table.
`memory_pilot.rank` (recall surfacing, context building, the pilot thread): 50 ms per call at her 1,243 active items
of 768 dimensions, measured offline on synthetic vectors; linear in the item count.

So in normal running no tool spends minutes of worker CPU. The CPU in the worker is a small set of pure computations:
history, digest, picture decode. Long calls are waits outside the worker, which release the lock.

## 4. Decisions

**D1. Pure heavy computations run in child processes, with a deadline and a kill.**
- *Data child* (new kind `data`, the `media_children.Child` supervisor): `query_authorized_history` and
  `digest_authorized_discussion` run there. The child builds its own Store and Retrieval from the config the job
  carries (the worker's config at the call; it changes at run time, `native_worker.py:1392-1404`) and keeps one
  connection per database. It reads only; validation before and after the call stays in the worker, as today (both
  tools already release the effects lock and re-check `service.valid` after the body).
- *Picture decode* (`animated.seen`, animated pictures up to 1,500 frames, then base64) runs in a *picture child*
  (new kind `picture`: the video child's program and packages, PIL, in its own process). Not the video child itself:
  a picture she opens in a turn would then wait behind an inbound video's split (up to 120 s). Both brains reach it
  through `vision.read_image_for_task`.
- Deadline per try 30 s (history, digest, picture; 10x the measured maxima), budget 60 s (a wait behind one other job
  plus one start). No second try for these jobs (`Child.call` retries once today: a call that timed out is not
  started again in a fresh child; the caller gets the answer at once).
- What she reads (model-facing, in the tool's own language): past the deadline,
  `QUERY_TIMEOUT: 这次查询超过 30 秒被停下了，没有结果；把范围收窄（时间窗、人、话题、limit）再试`; child not
  running, `QUERY_UNAVAILABLE: 做这次查询的后台程序这会儿没起来，这次没有结果；过一会儿再试`. Her read of both
  comes after the install (owner's rule above).
- A kill, a death or a start that fails is a lane fault (`lane_faults`, lanes `data` and `picture`).
- One data child for all tasks: a slow task waits at most the budget behind another task's job; turns never wait on
  it (no character-brain path uses it).

**D2. No body holds the effects lock across work it does not bound.** `persona_job_run`, `list_files` and
`read_file` move to the set that runs without the lock and re-checks `service.valid` after the body (`tasks.py:783-784`),
the pattern every Host-waiting tool already uses. `write_file`, `note_idea` and `report_progress` keep the lock
(writes; measured max 0.93 s). `list_files` gets a count bound in the walk (`LIST_FILES_MOST = 2000` entries, the
result says when it stopped there).

**D3. Every tool call of both brains is timed, and one past its limit is recorded and released.**
- Times: an action artifact gets `started_at` at INTENT (`tasks.py:777`) and `duration_s` at DONE/FAILED
  (`tasks.py:921`, `:929`). A role call gets `duration_s` in the episode's `tool_calls[call_id]` and in its audit row
  (`role_tools.py:1461-1470`), measured around the body alone (`role_tools.py:1350-1446`).
- A worker-wide registry of calls in flight (call id, brain, tool, task or episode, thread, start). A watchdog thread
  looks every 10 s. A call past its limit gets one `host.tool_overrun` evidence record with that thread's stack (the
  `host.inbound_slow` snapshot code, about 60 frames) and a lane fault (lane `tools`). Limit: 600 s (the lease
  extension each call already takes, `tasks.py:776`), or the call's own `timeout` argument plus 60 s where the tool
  takes one (`sandbox_run`, `development_run`, `integration_test`), whichever is larger.
- A task with a call past its limit stops renewing its lease (the keepalive skips it), so the lease expires within
  600 s and `close_orphan` closes the task as interrupted (`tasks.py:655-670`). She gets that honest result instead of
  a task that looks alive. The body's thread may still run, and only a restart stops it; the record names it, so
  it is seen. After D1 and D2 no tool body measured or known spends CPU long in the worker; what remains in the
  worker with data-sized work (credential scrubbing of results, the failure path's file hashing, `rank`) is listed
  with file:line in the survey's §5, and D4's rule applies to each.

**D4. The rule, written where the next feature is designed.** `docs/DEVELOPMENT.md`, present tense: work in the
worker process whose cost grows with stored data or with a call's arguments runs in a child process with a deadline
(the data child, the media children); a worker thread does only work with a stated bound. No body holds the effects
lock across a wait outside the process or a walk without a count bound. `memory_pilot.rank` stays in the worker
(50 ms at 1,243 items); the page records that number and its growth, and the rule applies when it stops holding.

**D5. Static guard.** A test fails when `ToolBroker.call` (or anything in `src/asuna` outside the data child) calls
`query_for_task` or `digest_for_task` directly, or `animated.seen` outside the video child job, or when a tool name
outside the D2 set sits under the effects lock.

## 5. Not chosen

- Every tool body in a child: 15 bodies must stay and ~16 need a route back to the Host; non-tool CPU stays exposed.
- Only the front door in its own process: inbound would be safe, her chat turns would still starve behind her tasks.
- A watchdog alone, or a shorter switch interval: both see or soften the starvation and leave it in place.
- Vectorising `rank` now: 50 ms is bounded and small; written down instead (D4).

## 6. How it is proven

- Unit (in-memory adapter): the job functions of the data child run in process against `asuna.store.memory`; the
  routing in `ToolBroker.call` against a fake child speaking the frames (`Child(command=...)`); D2's lock set; D3's
  registry, limit, record and lease skip; D5's guard.
- Process test (no database): a real data child given a job that spins; the worker side is killed past the deadline,
  answers `QUERY_TIMEOUT`, records a fault, and starts a fresh child; while it spins, socket round trips in the parent
  stay at the alone figure (the 0.018 ms vs 48 ms measurement above becomes the test's assertion, with margin).
- Integration (`integration/`, throwaway database): the data child's Store opens and reads on a real server.
- After install, on the real system: `duration_s` for history and digest against this page's table (the child adds
  frames and JSON: expected milliseconds); `host.inbound_slow` counts against the 10-29 afternoon windows; the first
  `host.tool_overrun` or data-child lane fault, if any, read when it comes.

## 7. Build and install

One build, one review, one install with its own restart (never stacked with ADR-108, which another agent builds; the
lead lands both, in the order they are ready).
