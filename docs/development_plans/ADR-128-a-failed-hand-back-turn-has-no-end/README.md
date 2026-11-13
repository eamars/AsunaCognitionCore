# ADR-128: A turn that fails its check: a hand-back with no end, and no one told

Status: **Designed** 2026-11-13; proposed 2026-11-12 by big sis (Claude Code). Nothing built. Designed against
`main` at `c287d051eaba` (ADR-127 installed); read again 2026-11-14 against `main` at `8fd48818d844` (ADR-129 installed
2026-11-13 20:12 as `816e825ea84f`, and closed), and every line number and count on this page is from that reading.
The owner's decisions of 2026-11-12, relayed by the ADR-127 session: the whole class is in scope (D3), and this is a
plan only. Read by her on 2026-11-13 after ADR-127 closed (agent line 0433, 0435, 0436): D1 and D3 agreed, D2's words
hers (§3). The owner, 2026-11-13: write it now; built only after ADR-129 is fully deployed. The owner, 2026-11-14: go
(§7). Times on this page are local time.

## The ask

The task brief (2026-11-12, raised from ADR-127's staging, ADR-127 §6 last paragraph):

> In the Asuna repo (its local path left out here), the worker's coordinator resumes a `task_feedback` episode
> that ended `FAILED_PROTOCOL` as a new generation (`src/asuna/coordinator.py`, `_advance`: `if
> ep['state']=='FAILED_PROTOCOL' and ep.get('episode_kind')=='task_feedback'` → `feedback.continued`, and `_run_turn`
> bumps `turn_generation`, operation `ep-…:TURN:resume:N`). Observed 2026-11-12 while staging ADR-127 in an isolated
> demo profile with a stub model that never satisfied the end-of-turn check (no `think` first): one task_feedback
> episode reached `resume:209` within about four minutes, and once its 24-call tool limit (role tool hard line) was
> spent, every continuation ended immediately, failed the check again and was continued again, so the loop could not
> end by itself. Nothing bounds the number of generations. Find what re-advances the episode (which caller, how
> often), name the broken invariant (a failed turn is continued without a limit or a backoff), and propose the
> smallest design that ends it (for example a fixed number of continuations, after which the episode fails as
> FAILED_RUNTIME and her failed-turn line says so). This is design work for an ADR page: follow
> `.agents/skills/big-sis/SKILL.md`, write the proposal, do not build or land anything, and use no real model endpoint
> (stage only with a stub model in an isolated profile).

The owner's decision on reading the first proposal (relayed 2026-11-12): "A FAILED_PROTOCOL turn of any kind (not
only a hand-back) must reach the developer note and her failed-turn line. … Close the class, not just the one
instance." Plan only: no build, no push, no merge.

The owner, 2026-11-13: "Yes please write the ADR for 128, and don't build until the 129 is fully deployed".

In scope: the loop that hands a failed task-result turn back to itself (D1), her line's words for the failures it
names (D2), and every turn of hers that fails its check reaching the developer note and her line (D3).

## 1. What is known (code at `8fd48818d844`; her database read 2026-11-14 12:1x)

**Who re-advances a failed hand-back, and how often.** One caller, in one cycle of four steps:

1. The worker's queue loop takes a hand-back event (`_feedback_task`) and calls `TaskService.feedback`
   (`src/asuna/chat.py:419`).
2. `feedback` finds the task's earlier episode (`continuing`, `tasks.py:632`), and because its state is
   `FAILED_PROTOCOL` it calls `coordinator.advance` on it (`src/asuna/tasks.py:664-665`).
3. `_advance` sees `FAILED_PROTOCOL` on a `task_feedback` episode, sets `resume_diagnostic`, writes
   `feedback.continued` (`src/asuna/coordinator.py:599-604`) and runs the turn; `_run_turn` adds one to
   `turn_generation` for a `FAILED_PROTOCOL` episode (`coordinator.py:300`). The turn gets its usual three deliveries
   (the first and `answers.REPAIRS` = 2 repair notes); when all three fail the check, `ProtocolFailure` sets the
   episode back to `FAILED_PROTOCOL` (`coordinator.py:624-626`, with a `phase.failed` row), and `feedback` records
   the task's `feedback_state` as `READY` again (`tasks.py:671`).
4. The queue loop sees `FAILED_PROTOCOL` and puts the same event straight back on the queue
   (`chat.py:425-429`), with no count and no delay; its `finally` keeps the task in `handbacks`
   (`chat.py:543`), so the watchdog leaves it alone as "on its way".

How often: as soon as the queue reaches it again. The queue is fair across conversations (`SceneQueue`), so other
conversations still get their turns, but the loop takes a slot in every round while it lasts. ADR-127's staging
measured it: 209 generations in about four minutes with a stub model (ADR-127 §6), each generation three deliveries.

**What ends it: only a generation that passes the check.** Nothing bounds the number of generations. In ADR-127's
staging the loop also could not end once the turn's tool calls were spent: they are counted per episode, not per
generation (`role_tools.py:1607`, `made = len(ep['tool_calls']) + 1`), so every later generation's first call ended
the turn without running (`role_tools.py:1611-1612`) and the check failed again for want of her thought. Since
ADR-129 such a generation passes (a turn ended by a call finishes `stop`, and with nothing said it commits silent), so
the spent budget no longer feeds the loop. What still does is a generation that fails the check every time, which
since ADR-129 is the cases below.

**Which turns fail the check since ADR-129.** The check is the end of `_run_turn` (`coordinator.py:324-372`):
- A conversation turn where QQ's rules apply: never. A turn with no thought is handed back twice and then ends as it
  is (`coordinator.py:350`, `issue!='length'` at the last attempt).
- A local conversation turn (the Web chat, an agent line, a peer line): only when all three deliveries were cut at the
  length limit with no `speak` and nothing written (`issue='length'`, `answers.CUT_SPEAK`). A turn with no `speak`
  that was not cut is her silence and commits.
- A consult (the action brain asked her): when none of the three answered with `task answer`
  (`answers.consult_problem`: not answered, or cut). Then `consult` raises `CONSULT_NOT_ANSWERED` to the action
  brain (`coordinator.py:167-168`).
- A task_time turn (a stage at its limit): never; it always commits (`coordinator.py:330-332`).
- `TURN_NOT_FINISHED` (a finish that is neither `stop` nor `length`, `coordinator.py:324-327`): the native plugin
  never gives it. A stage's `finish_reason` is `length` only for a `max-tokens` finish and `stop` otherwise
  (`packages/cognition-core/src/index.js:1507`), and a model error or a stopped turn comes back as an `error`, which
  the worker raises as a `RuntimeError`: a `FAILED_RUNTIME`, reported, and for a hand-back already on ADR-030's
  ladder. A model outage or a Host stop does not feed this loop; a failed check does.

So the loop of steps 1-4 needs a local hand-back turn cut three times in every generation: rare with a real model
(a result too long to answer within the length limit), certain with a stub that is always cut. The tool-call hard
line now matters for a consult: a consult whose 25 calls are spent before it answered cannot answer at all, since
every later call ends the turn (§3 D2's second word).

**A restart does not end it either.** The queue is in memory, so a restart drops the event, but the task's
`feedback_state` stays `READY`. The watchdog (ADR-030) finds it lost, and `handover.next_step` counts
`FAILED_PROTOCOL` with the resumable states (`handover.py:64, 69, 82`), so it hands back the full result again
(`FULL`), which reaches step 2 above. The ladder ADR-030 built for exactly this (full, then the short version, then
give up with the developer told) is never reached by a `FAILED_PROTOCOL` turn.

**A turn that fails its check is told to no one.** `faults.turn_failed` (the developer inbox note and her
conversation's fault mark, which her next turn there reads) runs only from the queue loop's exception path
(`chat.py:506, 523, 529`), so only on `FAILED_RUNTIME` (and never while the Host is stopping). Every turn of hers
reaches `_turn` by one of two paths, and neither reports a `ProtocolFailure`:

| Path | Kinds | On a `ProtocolFailure` today |
|---|---|---|
| `_advance` (`coordinator.py:586-626`), from the queue loop, `recover()` and `feedback` | external, presence, settlement, visit, note, scheduled, self_development, task_feedback | `FAILED_PROTOCOL` and a `phase.failed` row; no note, no line |
| `_task_turn` (`coordinator.py:193-241`), from `consult` and `time_up` | consult, task_time | the exception leaves `_turn` and the episode stays `TURN`; `consult` hands the error to the action brain, `time_up` audits `task.time_up_failed`; no note, no line, and the episode never says it failed |

**On her real data** (read-only counts, no content, 2026-11-14): 0 `feedback.continued` rows ever; 1,987
`task_feedback` episodes, of which 1,963 `COMMITTED`, 20 `WAITING_TASK`, 3 `FAILED_RUNTIME`, 1 `FAILED_PROTOCOL`. The
one `FAILED_PROTOCOL` carries a code from before ADR-011 (`INVALID_STAGE_OUTPUT`) and its task is `CANCELLED` with
`feedback_state: SUPPRESSED`: nothing is in flight. All 18 `FAILED_PROTOCOL` episodes (16 external, 1
self_development, 1 task_feedback) are the same as on 2026-11-12; one `phase.failed` row exists at all (2026-10-30, a
`self_development` turn, `INVALID_TURN_OUTPUT`), and that turn was told to no one. No `turn.rejected` row has ever
named `length`: since ADR-129 nothing of hers has failed the check. The design closes a class that is quiet on her
data and loud the first time it happens.

## 2. The broken invariants

- **Every automatic retry of a failed turn ends by a rule read from durable state.** A failed hand-back is retried by
  two mechanisms. ADR-030's watchdog retries a lost result by its cause, counted in durable state (full, short, give
  up). The older continuation (ADR-003's "the same durable feedback episode remains eligible", `chat.py:426`)
  retries the same episode with no count, and the watchdog classes its state as resumable, so the bounded ladder
  never sees it. Census of the class (`grep` of every `pending.put`, `task_queue.put`, `.advance(` and `feedback(`
  caller in `src/asuna`, 2026-11-12, checked again 2026-11-14): the other re-queues are the restart wait
  (`chat.py:414`), a new or recovered input, a hand-back and task scheduling, none of which re-runs a failed turn;
  the queue loop advances only `RESUMABLE` states (`chat.py:467`) and `recover()` only `PREPARED`, `TURN` and
  `SPEAK_ACCEPTED`; `SessionCarried` runs a turn again once (`coordinator.py:278-283`). The continuation is the only
  unbounded one.
- **Every turn of hers that fails is told to the developer and to her** (ADR-076 R4, `faults.py`'s own docstring:
  "nobody may be left not knowing"). It holds for a turn that raises; it fails for every turn that fails its check,
  on both paths of §1, because the report is written by one caller's exception path and not where a turn ends.

## 3. Design

**D3 first, because D1 rests on it. D3: a failed turn is ended, and told, where every turn ends.**

Site: `coordinator._turn` (`coordinator.py:273-288`), the one method both paths call and the only place a turn's
`ProtocolFailure` passes. Inside its outer `try` (so its `finally`, the plugin's `turn_done`, still runs), a
`ProtocolFailure` from `_run_turn` (the first run or the `SessionCarried` rerun) is caught and the turn is ended once:
the `phase.failed` row, the episode set `FAILED_PROTOCOL` with its `failure` (both moved here from `_advance`,
`coordinator.py:624-626`), then `faults.turn_failed(store, ep, failure)`, and `_turn` returns the failed episode
instead of raising. A failed report never becomes the next failure: `turn_failed` is wrapped like the queue loop's
`_report_fault` (`chat.py:168-175`), its error audited on the episode (`turn.fault_unreported`, as a plan's is
`schedule.fault_unreported`, `faults.py:99`) and the episode still ended.

What each caller then sees:
- `_advance`: gets the failed episode back. Its `except ProtocolFailure` (`coordinator.py:624-626`) is deleted: no
  other `ProtocolFailure` reaches it (the only other raise, `CONSULT_NOT_ANSWERED`, is in `consult`, after `_turn`;
  `_attend` only re-raises). Anything else that raises still reaches the queue loop's exception path, `FAILED_RUNTIME`
  and reported, as today.
- `_task_turn`: gets the failed episode back, and runs `_turn` only for an episode still `PREPARED` or `TURN` (today
  any state but `COMMITTED`, `coordinator.py:239`), so a failed one is never run again under the same key.
  - `consult` then raises `CONSULT_NOT_ANSWERED: <the failure>` to the action brain (`coordinator.py:167-168`,
    unchanged code, reached now): the action brain's error is today's `INVALID_TURN_OUTPUT: …` with that prefix.
  - `time_up` returns the failed episode; its thread ignores the value (`native_worker.py:413`). A task_time turn
    cannot fail the check today (§1); were one to, `task.time_up_failed` would not be written for it (the failure is
    on her episode, with the note); it stays for the stage already over and for anything that raises.
- The queue loop (`chat.py:464-486`): a `FAILED_PROTOCOL` result is marked `COMPLETE` with that state. Its notice
  (`chat.py:485`, written to the evidence log as `host.notice` by the Host's `emit`, `host.py:326`) says today
  本轮没有公开发言, which reads like a silence she chose. For a `FAILED_PROTOCOL` result it says
  她这一回合没跑成，状态：FAILED_PROTOCOL (her words 这一回合没跑成, line 0433); the turn itself is told by D3. The notice is the
  operator's only: it is an evidence row, never shown on her Web page and never in her context (her line 0435). One
  change in its exception path: anything that raises after `_turn` returned (the task save in `feedback`,
  `tasks.py:671`; the scene check, `chat.py:473`; the proactive and sticker steps) must not relabel and report the
  turn again, so the two state checks there (`chat.py:502, 525`, "not `COMMITTED` or `WAITING_TASK`") also leave a
  `FAILED_PROTOCOL` turn alone; the hand-back's `missed` record (`chat.py:509`) still runs.

The developer note is one per kind and cause a day, counted (`faults.turn_failed`'s key), so a burst of failed checks
is one note with a count. That throttle is the developer note's only: her conversation's fault mark is written for
every failed turn (`scene_records.note_fault` on each call), so a second or third failure in a day still reaches her
next turn there (her line 0433). The note names the kind (`faults.KINDS` has `consult` and `task_time`); the line goes
to the conversation the turn belongs to (`ep['scene_id']`; for a turn about a task, the task's), and her next turn
there reads it (`context.py:1447-1452`).

**D1. A failed hand-back is not continued; ADR-030's ladder takes it.** With D3 the turn is already ended and told
when `feedback` gets it back. What remains is to stop the continuation and let the watchdog see the result as lost:

- Deleted: the queue loop's re-queue (`chat.py:425-429`) and the `FAILED_PROTOCOL` condition in its `finally`
  (`chat.py:543`): the task leaves `handbacks` like any other hand-back.
- Deleted: `_advance`'s `FAILED_PROTOCOL` branch and its `feedback.continued` audit (`coordinator.py:599-604`), and
  `FAILED_PROTOCOL` in the states `_advance` runs a turn from (`coordinator.py:617`).
- Deleted: `ep['state']=='FAILED_PROTOCOL' or` in `_run_turn`'s generation rule (`coordinator.py:300`): a generation
  still advances for a turn resumed after a restart or an interruption, unchanged.
- Deleted: the `continuing` clause that advances a `FAILED_PROTOCOL` episode (`tasks.py:664`). Kept: `feedback_state`
  `READY` for a `FAILED_PROTOCOL` turn (`tasks.py:671`), which now means what the watchdog reads it as: not taken.
- Added, one call: `feedback` records the hand-back as missed by its turn (`self.handback(task, 'missed', 'turn',
  faults.cause(ep['failure']), short=short)`), what the queue loop's exception path records for a raised one
  (`chat.py:509`), so the thread's card says the result did not reach her.
- Deleted: `'FAILED_PROTOCOL'` in `handover.next_step` and `handover.cause` (`handover.py:64, 69, 82`): a failed
  hand-back episode is a failed turn there. Those lookups are all `kind='task_feedback'`, so nothing else changes.

The watchdog's next sweep (at most `SWEEP_SECONDS` = 60 later) finds the result lost and `next_step` gives the short
version, a new episode with its own tool budget, whose context holds D3's line about the failed one. If that turn
fails too, the next sweep gives up (`give_up_handback`: `UNDELIVERABLE`, the developer told, her task list says the
result could not reach her). The episode stays `FAILED_PROTOCOL`, not relabelled `FAILED_RUNTIME` as the ask's example
had it: after D1 and D3 the state is terminal everywhere and reported, and keeps which failure it was (`places.FAILED`
and `questions.ENDED` already read it as failed). The short version is also the one most likely to pass the one check
a hand-back can still fail since ADR-129 (cut at the length limit): its input is smaller.

The alternative, a fixed number of continuations (the ask's example), and its cost: one continuation, counted on the
episode, then D1. It keeps two retry mechanisms for one failure, adds a counter with its own lifecycle, and its extra
try is the weaker one: the same episode, its input the full result that was already cut three times. The short
version ADR-030 gives next is a fresh episode with a fresh budget and a smaller input. Worst case per result: today
unbounded; recommended, 2 episodes × 3 deliveries = 6; the alternative, 9. No backoff is needed: after D1 no retry runs
in a hot loop, and the one left waits for the sweep.

**D2. Her line names these failures, in ADR-127's line as built.** Checked against `src/asuna/faults.py` at
`8fd48818d844`: the line is `TURN_HEAD` (「你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么。」, the
stamp and a word from `CAUSES`), then `lost()`, then `reported()`.
- The cause: D3 stores the failure as `str(exc)`, which starts `INVALID_TURN_OUTPUT: `, so `cause()` takes it from
  its leading code (`LEAD`, `faults.py:19`). It is not in `CAUSES` today, so without D2 the line says 「出错类型未辨」.
  D2 adds one row. `TURN_NOT_FINISHED` gets none: the native plugin never gives it (§1); were it to come, the line
  would say 「出错类型未辨」, which is true.
- `lost()` reads the failed episode's delivered lines and completed tools (the fault keeps `episode_id`, which
  `turn_failed` writes): a failed check with nothing done reads `NOTHING_DONE`; one that ran tools before failing
  lists them, which is what the continuation's notice used to say (「这一回合中断前已经生效的工具调用（不用再做一遍）」).
  `RETRIED` is not involved: its mark, `ASUNA_RETRIED_ONCE`, is written only into an `error` (`index.js:78`), never
  into a `ProtocolFailure`.
- `reported()`: 「这条已经记进开发者收件箱」 is true, because D3 writes the note before the mark.

Her words (agent line 0433):

| Code | Her word in `CAUSES` |
|---|---|
| `INVALID_TURN_OUTPUT` | 收尾的检查三次没过 |
| `INVALID_TURN_OUTPUT`, when the turn's tool calls had reached the hard line | 工具次数已经用完，收尾过不去 |

`TURN_HEAD` holds for a failed check (her word: the check is the program's rule, and in the staged loop the program
made passing impossible), so her line reads 「是程序出了错（收尾的检查三次没过），不是你做错了什么」. The second word is hers
for the case where the hard line on tool calls made the ending impossible: with the first word she would read that one
more tool call could save it, when every call there ends the turn at once. Since ADR-129 that case is a consult (§1):
a conversation turn whose calls are spent ends and commits. Told apart by durable state, not by text: `turn_failed`
reads the failed episode's own tool calls (`len(ep['tool_calls'])` against `role_tools.CALLS_HARD`) and writes
`capped: true` on the fault mark; `her_line` picks the word by the code and that flag.

With D2's change to `faults.py`, one word elsewhere moves to the table it belongs to (her yes, agent line 0283): the
unknown reason in `vision.py`'s `IMAGE_NOT_PULLABLE` (`vision.py:655`, 「原因不明」) becomes `faults.NO_CAUSE`
(「原因没记下来」), the one word for a cause with no record.

## 4. Failure modes, I/O, lifecycle

| Case | Who waits, how long | What recovers |
|---|---|---|
| Any turn fails its check (D3) | Nothing waits on it | The note (one per kind, cause and day, counted) and her line in her next turn there |
| A full hand-back fails its check | Only that result; at most 60 s to the next sweep | The short version, with her line in its context |
| The short one fails too | Nothing more is tried | `give_up_handback`: `UNDELIVERABLE`, developer told, her task list says so (as for `FAILED_RUNTIME` today) |
| Her model server is down, or the Host stops | Unchanged: these come back as an `error`, `FAILED_RUNTIME` (or `INTERRUPTED` while stopping), outside this design | As today |
| The report itself fails (the inbox or the scene write) | Nothing | `turn.fault_unreported` on the episode; the turn is still ended `FAILED_PROTOCOL`, the hand-back still goes down the ladder. This is the one case where a turn did not run and she is told nothing (her line 0435): the row is what a reader of the audit finds, and big sis's line watcher reports `turn.fault_unreported` and `schedule.fault_unreported` rows by day with a count (her line 0436) |
| Something raises after a turn ended `FAILED_PROTOCOL` | Nothing | The exception path leaves the turn as it is (no second note); a hand-back's `missed` record is written; the watchdog gives the short version |
| A consult fails its check | The action brain's call, as today | The action brain gets `CONSULT_NOT_ANSWERED` with the failure; her episode now says `FAILED_PROTOCOL`, and she is told |

State: nothing new is stored. Deleted: the `feedback.continued` audit type, and a task-path turn left in `TURN` after
it failed. A restart in the middle loses only the queue's in-memory event, which the watchdog restores from the
database as today. No stored data is wrong after the change (§1: nothing in flight), so nothing is converted; the 18
old `FAILED_PROTOCOL` episodes stay as they are and are told to no one now (they are weeks old; a line about them
would be news of nothing she can act on).

Two sides at different versions: the change is in the Python worker only; the plugin is not touched. `turn_done`
still runs from `_turn`'s `finally` and reads nothing of the state.

## 5. Acceptance

- D1: a local hand-back turn that is cut every time ends after one full and one short episode, at most six deliveries
  in all; no `resume:` operation and no `feedback.continued` row; the task ends `UNDELIVERABLE`; the thread's card
  shows the hand-back missed by its turn, then given up.
- D2: her line about such a turn names the cause by her word for `INVALID_TURN_OUTPUT`, never 「出错类型未辨」, under
  `TURN_HEAD`; a consult whose tool calls had reached the hard line gets her second word.
- D3: a turn of each path that fails its check (a local external one, a task_feedback one, a consult) leaves its
  episode `FAILED_PROTOCOL`, one `phase.failed` row, one developer-inbox note per kind and cause that day (never a
  second for the same turn), and her line in her next turn in that conversation; a consult's action brain gets
  `CONSULT_NOT_ANSWERED`.

## 6. Tests

Each fails on the current code first; each guards a failure that is silent and costly (an unbounded request loop; a
failed turn nobody hears of). Today one test reaches `FAILED_PROTOCOL` (`tests/test_adr129_one_rule.py`, a consult
with no answer), and none checks that anyone is told.
- In `tests/test_fault_line.py` (ADR-127's, in-memory store): a turn whose stub character fails the check three times,
  run through `_advance` (a local turn cut each time) and through `_task_turn` (a consult with no answer), ends
  `FAILED_PROTOCOL` with one developer note and the scene's fault mark holding its episode; her line names the cause
  by `CAUSES`, and a consult whose calls were spent gets the second word. Today: no note, and the consult episode
  stays `TURN`.
- One test of the ladder: `feedback` on a hand-back whose turn ends `FAILED_PROTOCOL` returns it without queueing or
  advancing it again on a second call, and `handover.next_step` gives `SHORT` for the failed full episode and
  `GIVE_UP` for a failed short one. Today: the second call advances it, and `next_step` gives `FULL`.

Nothing for wording.

## 7. Landing

ADR-129 was installed 2026-11-13 20:12 and closed the same evening; this page was read again against the code of
2026-11-14 (the header), and the owner said go that day. Her reading first: what changed in her part since 0433 (her
second word now names a consult; the operator-only notice and the unreported case said on the page, 0435, 0436),
once. Then built on a branch, staged (§8), landed, and installed in its own worker restart at a slot she gives; no
plugin change. Then her check by content: her words in `CAUSES`, read in the installed `faults.py`.

## 8. Closes when

Built, and shown in an isolated demo profile with a stub model (no real model; the Host started without any model
key), labeled 造的: §5's D1 case end to end with the stub's answer that is always cut at the length limit (the
stub that made ADR-127's 209 generations wrote no thought, which since ADR-129 fails no local check; the deliveries
counted from the stub's own request log), and D3's local external and consult cases (the notes and the line read
from the demo's database and the next turn's context). Her line is shown to her word for word as the demo's next turn
read it, both words of D2, not "the line is there" (her ask, line 0433: ADR-127 taught that a word not seen landed is
not landed). Then installed, and checked by content: the running worker's `faults.CAUSES` holds her word for
`INVALID_TURN_OUTPUT`, and its `_turn` ends a failed check (the installed files read, not a date waited for).
