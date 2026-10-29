# ADR-109: One tool call never stalls the worker

Status: **Proposed** 2026-10-30. Written by the lead (Claude). Direction decided by the owner the same day: a child
process for the pure heavy work (not every tool body), and every tool call timed and recorded when it runs long; a
wedged character-brain call is recorded and alerted, never released and never restarted automatically (owner, the
same day). Two cold reviews of earlier drafts (13 findings, then 10) showed that releasing a wedged in-worker call
adds hang paths of its own and still cannot stop a spinning thread; this version keeps what removes the class and
drops the rest (§5). Nothing is built. Owner's rule for this ADR: Xiaoman is not told until the root cause is resolved
(installed and checked); her read of the new wordings (§4) comes after that, not before.

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
3. **Visible.** Nothing records a call that runs long. The lease is renewed by the claim (`tasks.py:466`), the
   keepalive (`tasks.py:508-522`) and each call's INTENT (`tasks.py:776`), and the orphan sweep skips the task the
   executor is running (`chat.py:562-563`, `handover.py:51-55`). A wedged call reads as healthy until the stage limit.

Two more paths of the same class:

- The effects lock (`TaskService.lock`, a thread lock plus a file lock, `queue.py:57-80`) is held across
  `persona_job_run` (a job whose `timeout_s` her own job definitions set; core caps none) and `list_files` (a walk with
  no count limit), among others (`tasks.py:783-784`). Every outbox claim, her words to QQ and the agent lines
  included, waits on that lock, and so do several of her own tools (`speak` through `publish.py:38`,
  `understand_person`, `plan`, `delegate`, task message and stop). The rule written right above that line already says
  never to hold it across a wait outside the process; `persona_job_run` does.
- A character-brain tool body runs on the turn thread, which holds `Coordinator.lock` for the whole turn
  (`coordinator.py:553`); the stage deadline is checked only between calls (`native_worker.py:337-341`). A role body
  that wedges, on its own work or on the effects lock above, stops every later turn of hers, in every conversation
  (`ingest` takes the same lock, `coordinator.py:99-100`). Inbound admission is not behind this lock
  (`router.receive` runs on the chat thread, `chat.py:464`).

## 3. Facts the design rests on

Survey: `.runtime/private/tool-isolation/survey-1030.md` (code reading, both brains, file:line). Of the tool bodies,
15 must stay in the worker (Host round trips through the worker's stdio, closures built in the worker, worker
singletons); about 16 more would need a route back. So moving every body does not fit.

Measured durations, action brain, 7 days to 2026-10-30 10:50 NZDT (audit `state.commit` of artifacts, INTENT to
DONE/FAILED, 14,669 calls):

| Tool | n | p50 s | p99 s | max s | Where the time goes |
|---|---|---|---|---|---|
| sandbox_run | 7,320 | 0.20 | 25.2 | 508 | the Host's sandbox (a wait, not worker CPU) |
| development_run | 1,045 | 1.50 | 22.2 | 273 | the Host (a wait) |
| generate_image | 293 | 18.4 | 157 | 176 | the image model (a wait) |
| ask_character | 52 | 26.1 | 91.8 | 91.8 | her character brain (a wait) |
| read_image | 339 | 0.08 | 4.75 | 6.93 | the download (a wait); a still picture is only base64-encoded (`animated.py:275-278`) |
| query_authorized_history | 173 | 0.96 | 3.26 | 3.38 | store reads plus Python over up to 200 rows a page |
| digest_authorized_discussion | 10 | 1.20 | 2.34 | 2.34 | the same, plus thread expansion (today's call never ended) |
| all others | ≤ 0.93 s max | | | | |

Calls that raised are not in this table (they leave only the INTENT row), and character-brain calls carry no start
time today. `memory_pilot.rank` (recall surfacing, context building, the pilot thread): 50 ms per call at her 1,243
active items of 768 dimensions, measured offline on synthetic vectors; linear in the item count.

So in normal running no tool spends minutes of worker CPU. The long calls are waits outside the worker, which release
the interpreter lock. The data-sized Python work inside tool bodies is history and the digest; the one call that ever
spun is the digest.

## 4. Decisions

**D1. History and the digest run in a child process, with a deadline and a kill.**

A new child kind `data`, supervised by `media_children.Child`, runs `query_authorized_history` and
`digest_authorized_discussion` (`HistoryQueryService.query_for_task`, `DiscussionDigestService.digest_for_task`).
Validation before and after the body stays in the worker, as today (both tools run without the effects lock and
re-check `service.valid` after the body, `tasks.py:820-832`).

- *The job carries* the task row, the tool's args, a copy of the worker's config, and the channel packages the worker
  was initialized with (`native_worker.py:452`). The copy is `dict(config)`: run-time writers only replace top-level
  keys (`native_worker.py:71-74`, `:1396`, `:1400`), so a shallow copy taken in one call is a consistent snapshot. The
  child loads the channel packages with `channel_kinds.load`; without them `person_ids` finds nothing and
  `verify_peer` answers `no_platform` (`peer_context.py:73-75`).
- *The child holds* one Store per database, its `config` replaced by each job's copy (`Store.config` is fixed at
  construction, `state.py:114`), and one Retrieval, rebuilt when the copy's embedding settings differ from the ones it
  was built with. Its Retrieval embeds the query with the memory indexer's timeouts (10 s, 5 s to connect,
  `memory_indexer.py:25`), not the 180 s default (`evidence.py:68`), so a slow embedding endpoint falls back to
  lexical search inside the deadline, as it does today (`retrieval.py:59-66`). Retrieval's per-process state starts
  empty in each new child; the pilot does not read this instance.
- *It writes what these tools write today*: label rows (`people.py:492-500`, unique per scene and handle,
  `catalog.py:404`) and Retrieval's audit (`retrieval.py:92`, `:321-322`). Audit appends from two processes are safe
  (`state.py:165-176` retries on a duplicate key). Evidence is not written by the child: its records come back in the
  answer and the worker records them. A kill in the middle of a `put` leaves a document whose commit is missing;
  `recover_commits` reconciles it at the next start (`state.py:209`, run by `coordinator.py:599`).
- *What comes back*: the result passed through the worker's JSON conversion (`tasks.py:913-915`, `default=str`)
  inside the child's try, so an answer that cannot be written becomes a `program` error, never a dead child. A refusal
  of a known class (`Denied`, `ValueError`, `PermissionError`, `Conflict`, `state.py:104`) comes back as its class and
  words and is raised again in the worker with the same words, so `error_text` (`native_worker.py:1537-1548`) says what
  it says today. Any other exception is a `program` error and a lane fault.
- *Times*: deadline 30 s per job (10x the measured maxima); one job at a time; a job waits at most 30 s for the
  child's lock (a limit of its own, not the whole budget as `Child.call` acquires today, `media_children.py:337`); a
  start at most 30 s; one try. The concurrency is parallel calls inside one task (one executor thread, `chat.py:94`;
  one thread per call, `native_worker.py:1585-1587`). After a kill or a death the next job starts a fresh child within
  its own budget (no background start, which would queue on the same lock).
- *Changes to `media_children.Child`*: a `tries` setting (1 for `data`; voice and video keep 2), a lock-wait limit
  separate from the budget, `Busy` for a job that waited out the lock-wait limit (distinct from `Timeout`), and `data`
  and `tools` in `lane_faults.LANES` (`lane_faults.py:22`) and `FAULT_LANES` (`media_children.py:39`), without which
  their faults are refused and lost.
- *What she reads*: the three outcomes come back as a result carrying `error`, the form `failure_words` closes FAILED
  (`tasks.py:918-922`), so her next call is a new call and never `TOOL_DELIVERY_UNKNOWN` (`tasks.py:772-774`).

  | Case | Words |
  |---|---|
  | past the deadline | `QUERY_TIMEOUT: 这次查询超过 30 秒被停下了，没有结果；把范围收窄（时间窗、人、话题、limit）再试` |
  | the child busy or starting past its wait | `QUERY_BUSY: 做查询的后台程序这会儿腾不出来，这次没有结果；过一会儿再试` |
  | the child will not start | `QUERY_UNAVAILABLE: 做这次查询的后台程序这会儿没起来，这次没有结果；过一会儿再试` |

**D2. No body holds the effects lock across a wait outside the process or an unbounded walk.**
- `persona_job_run` joins the set that runs without the lock and re-checks `service.valid` after the body
  (`tasks.py:783-784`), as every Host-waiting tool already does (`persona.job_run` from the plugin already runs that
  way, `native_worker.py:1368-1372`). The lock never protected the task folder: `sandbox_run` and the development
  tools write there without it.
- `list_files` keeps the lock and gets a count bound: it walks iteratively and stops at `LIST_FILES_MOST = 2000`
  entries (replacing `sorted(rglob)` at `tasks.py:260-261`, which walks everything before it sorts), sorts what it has,
  and says when it stopped there.
- `read_file`, `write_file`, `note_idea` and `report_progress` are unchanged (measured max 0.93 s). `report_progress`
  emits to the Host under the lock (`tasks.py:818`); that pipe is the worker's own output, which every thread needs
  anyway, so it is named here and not moved.

**D3. Every tool call of both brains is timed, and one that runs long is recorded and alerted.**
- *Registry.* The worker keeps the calls in flight: call id, brain, tool, task or episode, thread, start. Every call
  leaves it in a `finally`, which appends one audit event `tool.time` (stream: the task id or the episode id; call id,
  tool, `duration_s`, outcome `done` / `failed` / `raised`). One mechanism for both brains, and calls that raise are
  counted too. There is no audit kind registry; `payload.outcome` is declared text (`catalog.py:350`). Volume: about
  2,100 action calls a day plus her role calls, against ~72,000 commits a day.
- *Watchdog.* A thread looks every 10 s. A call running longer than 600 s, or than its own `timeout` argument plus
  120 s where it takes one (`sandbox_run`, `development_run`), gets one `host.tool_overrun` evidence record (call,
  tool, seconds, the thread's stack: 60 innermost frames, not the 12 of `host.inbound_slow`, `channels.py:30`), a lane
  fault (lane `tools`) and one warning line in host.log. One threshold, not a table per tool: it only records, so a
  late record costs nothing and a false one costs a line; 600 s is above every measured call but `sandbox_run`'s, which
  carries its own timeout.
- *No release.* A wedged action call ends its task at the stage limit (`STOPPED_AT_LIMIT`, `tasks.py:1017-1018`), as
  today. Releasing it earlier would mean failing the stage Future and cancelling the action session while the body may
  hold the effects lock (`tasks.py:1013` would then wait on it) and while the plugin's cancel of a pending `execute`
  is unsettled (`index.js:1474-1482`); and it still could not stop the thread. After D1 the work that can spin runs in
  the child, where the deadline kills it; what remains in the worker waits on I/O and harms only its own task.
- *Character brain* (owner's decision): an overrun is recorded and alerted as above, never released; recovery is a
  restart by us, never automatic. A role body can wait on the effects lock with no timeout (§2), so the record's stack
  says which: its own work, or a lock holder. D2 removes the one long holder known (`persona_job_run`).

**D4. The rule, written where the next feature is designed.** `docs/DEVELOPMENT.md`, present tense: work in the
worker process whose cost grows with stored data or with a call's arguments runs in a child process with a deadline
(the data child, the media children); a worker thread does only work with a stated bound. No body holds the effects
lock across a wait outside the process or a walk without a count bound. Data-sized work that stays in the worker, each
with its stated bound and the reading that would move it, all timed by D3's `tool.time` from the first day:
`memory_pilot.rank` (50 ms at 1,243 items, linear); picture handling in `read_image` (a still is base64 only; an
animated picture's frame walk in Pillow, `animated.py:121-130`, bounded by the 8 MiB cap); `task page` and the task
feedback's observations (`tasks.py:157-179`: every artifact result of the task, `records_pages` quadratic in the record
count); credential scrubbing of results (bounded by the result's size); the persona job data API (bounded by the job's
`timeout_s`); the failure path's file hashing (`tasks.py:938`, at most 20 files).

**D5. Static guard.** A test fails when anything in `src/asuna` outside the data child's job calls `query_for_task` or
`digest_for_task`, or when `persona_job_run` runs its body under the effects lock in `ToolBroker.call`.

## 5. Not chosen

- Every tool body in a child: 15 bodies must stay and ~16 need a route back to the Host.
- Only the front door in its own process: inbound would be safe, her chat turns would still starve behind her tasks.
- A watchdog alone, or a shorter switch interval: both see or soften the starvation and leave it in place.
- Releasing a wedged in-worker call (failing its stage Future, a per-tool limit table): it adds two hang paths (the
  effects lock in the failure branch; a pending `execute` the plugin may not cancel) and cannot stop the thread (§4 D3).
- A picture child: nothing measured needs it (a still is not decoded; the 6.93 s maximum includes the download); its
  cost is timed under D4 instead.
- An atomic `write_file` (temporary file and replace): it loses `overwrite=False`'s exclusivity, can fail on Windows
  when another process holds the file open, and leaves temporary files for `list_files` and `files_left`; the reads
  that would need it keep the lock (D2).
- Releasing a wedged role call (running role bodies off the turn thread): a deep coordinator change (the turn's state
  is written under the same lock); not now (owner).
- An automatic restart on a role overrun: her Host would restart on its own, mid-conversation, on a bug (owner: no).
- Vectorising `rank` now: 50 ms is bounded and small; written down instead (D4).

## 6. How it is proven

- Unit (in-memory adapter): the data child's job functions run in process against `asuna.store.memory`, with the
  channel kinds loaded; refusals of each known class come back with the same class and words; a result holding a
  non-JSON value comes back converted; the routing in `ToolBroker.call` against a fake child speaking the frames
  (`Child(command=...)`): timeout, busy and unavailable each close FAILED with their words; `Child`'s `tries`,
  lock-wait limit and `Busy`; D2 (`persona_job_run` outside the lock and re-checked after; the `list_files` bound);
  D3's registry (`tool.time` on done, failed and raised, both brains) and the watchdog's record at the threshold; D5's
  guard; the new lanes accepted by `lane_faults.record`.
- Process test (no database): a real data child given a job that spins: killed past the deadline, `QUERY_TIMEOUT`, a
  lane fault, the next job served by a fresh child; while it spins, socket round trips in the parent stay near the
  alone figure (the 0.018 ms vs 48 ms measurement becomes the assertion, with margin).
- Integration (`integration/`, throwaway database): the data child's Store opens, reads and writes a label row on a
  real server.
- After install, on the real system: `tool.time` for history and digest against §3's table (the child adds frames and
  JSON: expected milliseconds); `host.inbound_slow` counts against the 10-29 afternoon windows; the first
  `host.tool_overrun` or new-lane fault, if any, read when it comes; the first week of `tool.time` for the D4 items.

## 7. Build and install

One build, one review, one install with its own restart (never stacked with ADR-108, which another agent builds; the
lead lands both, in the order they are ready).
