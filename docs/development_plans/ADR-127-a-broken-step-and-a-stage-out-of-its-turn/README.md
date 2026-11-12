# ADR-127: A broken step, and a stage out of its turn

Status: **Built** 2026-11-12 on `claude/adr127` (the owner's go, 18:29: build it and merge it today), installed 19:36.
The same evening S2 deadlocked her live Web conversation twice (§7); **S3, its fix (§7), is built on `claude/adr127-s3`, not landed: it lands when she agrees**, and
§7.6 is the recovery until it is installed. Opened by big sis
(Claude Code) after the owner's choice of 2026-11-12: after ADR-126 closes, one change for her turns that end in a
model error, folded with the cause of the two tool-less turns found the same morning. Her conditions (agent line 0370,
0373, 0374, 0386), her reading of this page (line 0403) and her last six items (lines 0404, 0405) are written into it.

## 1. What is known (2026-11-12, session records read for structure only: types, seqs, times, codes)

**Model errors.** Four steps of hers ended in `MALFORMED_RESPONSE` from 2026-11-07 to 2026-11-11, none before (the
first 2026-11-07 06:51 UTC): the arguments of a tool call were not JSON. Three were in her conversations; one
(2026-11-09 22:36) was in an action session, its `write_file` cut (her reading, line 0403; counted by session, turn
and time, a seeded copy not counted twice). The model server's session reproduced all four; its parser fix (in
production since 2026-11-12) cures three, and the fourth (her reply written into `think`'s argument, cut by the end
token) is a model slip no parser can mend. In each, the step's record (`assistant/attempt`) holds only reasoning and
a tool call, its finish is `error`, and that step has no `tool/call` and no `tool/result`; in her conversations the
turn has no lane receipt and its episode ends `FAILED_RUNTIME`. Her reading (line 0373): the cut came at 637, 800 and
1,969 characters of arguments, and one lost a `write_document` whose content had not started.

Of all 77 `assistant/attempt` records in her 2,068 session files (her count, line 0403): `TRANSPORT` 23, no finish
15, `CONTEXT_WINDOW_EXCEEDED` 13, `PI_AI_ERROR` 11, `INVALID_REQUEST` 8, `MALFORMED_RESPONSE` 5 (the four), `TIMEOUT`
1, `NO_ADAPTER` 1. None but `MALFORMED_RESPONSE` has the shape above (a tool call in the attempt, no call and no
result in that step), counted by turn and by step.

In the pinned DSH (`agent-loop/src/agent.ts`, the step loop) a step's tools run only after its stream finished
without error. A failed stream is recorded as `assistant/attempt`, which the model's surface leaves out
(`session/src/surface.ts`), and `agent/request-error` may answer `{kind: 'retry'}`: the same step is requested
again, its input not appended twice. So a step that failed this way ran no tool, and nothing of it is in her history.
Nothing of a turn is published before its end (`agent/turn-stopping`, the stage result).

Her next turn in that conversation already reads one line about a failed turn (`faults.HER_LINE`, ADR-076 R4):
which turn did not run, that it was the program, that it was reported. It does not say what was lost.

**Two tool-less turns** (turns 3641 and 3642, 10:47 and 10:48). Each request declared no tools, so the model server
(0.2.13, strict) returned her tool call as text; the end-of-turn check stopped the first, the second ended with no
stage. Neither was published. The sequence, from the inbox records (`agent/inbox/spliced`, by stage operation):

- 10:37:47: episode `ep-c7617…`'s stage message is queued for the next turn; no turn starts before the Host exits
  on its own at 10:41 (3221225477) and starts again.
- 10:46:02: the worker sends the same stage again; `onEvent` (index.js, `agent.followup`) queues a second copy behind
  the first. Turn 3640 takes one; its stage runs and is published.
- 10:47:23: turn 3641 starts on the second copy. No stage is current, so `exposed()` gives no tools.
- 10:47:29: episode `ep-813bf…`'s stage arrives while 3641 runs. `onEvent` makes it current at once and queues its
  message for the next turn. At 3641's end its output is taken as `ep-813bf…`'s result, an answer to a message it
  never read; the worker rejected it only for the markup, then ran the stage properly in the same turn.
- 10:48:21: turn 3642 starts on the copy queued at 10:47:29: no stage, no tools.

A tool-less request of hers was seen once before, on 2026-10-13 (its cause not read). Two invariants are broken: a
stage's message is queued once; and a stage becomes current only in the turn that will answer it.

Not in this ADR, seen the same afternoon (her reading, line 0403): on her agent line, 11 of 26 lines took more than
30 seconds from their arrival (`messages.received_at`) to the router's `event.received`, the longest 714 seconds,
between 15:07 and 15:28, while her conversation was busy and compacting. No line was taken twice (2,167 inbound rows,
2,167 `platform_event_id`s).

## 2. Design

**S1. One copy of a stage's message.** Before `onEvent` queues a stage's message, every message already queued for
the next step or the next turn that carries the same `source.operation` is removed; then the fresh one is queued
(composed now, so its context is current). A copy kept by DSH's durable inbox across a restart is so replaced, never
doubled. Each copy removed is recorded (`asuna/stage-copy-replaced`: operation, where it was queued, its length), never
removed silently (her ask, line 0403).

**S2. A stage starts only when no other turn runs.** `onEvent` makes a stage current only when the conversation has
no current stage and DSH is not running a turn; otherwise the stage waits in `state.queue`, as it already does behind a
current stage. A turn that ends takes the next waiting stage (`next()`, as now); a turn that ends with no stage, and
the conversation going idle, start the next waiting one the way `onEvent` does. So no turn's output is taken for a
stage it did not read (and `admit` no longer meets a stage made current under a Web turn it is admitting).

**R1. A broken step is requested again, once.** A listener on `agent/request-error` in her character lane and her
action lane (one of the four was an action step), after DSH's own decision. The action lane is the ADR-075 fallback's:
a job on 高 falls to the action route on this failure as it does today (that is itself a new request), and R1 covers
only what the fallback does not take (the job not on 高, or a code the fallback leaves) (line 0404, 0408). **Each step
gets at most one extra request, the fallback's and R1's together**: the fallback's is recorded the same way
(`asuna/retry` with `by: fallback`, R1's `by: retry`), so the step it took is not requested again by R1 when it breaks
again on the action route, and an extra request the fallback made is counted, never silent (line 0408). When the
failure is `MALFORMED_RESPONSE`, the session holds no `tool/call` and no `tool/result` of that turn
**and step** (not of the turn: two of the four turns had calls in other steps), and that step was not retried before,
it appends `asuna/retry` (turn, step, code) to the session and answers `{kind: 'retry'}`. If the records cannot be
read, or show a tool call, it does not retry (her rule, line 0386: what cannot be checked counts as taken). A second
failure of the same step ends the turn as now (an action step's ends its task as now). Only `MALFORMED_RESPONSE`:
`TRANSPORT`, `PI_AI_ERROR`, `TIMEOUT`, `CONTEXT_WINDOW_EXCEEDED`, `INVALID_REQUEST`, `NO_ADAPTER` and a stream with no
finish keep DSH's own handling and the fallback's. `asuna/retry` carries the failure's `code` (line 0405) and who
made the request (`by`).
`toolless_steps.py` also counts steps of the same shape with another code; one is reported to her (it would mean one
code is no longer enough).

The failure the worker records for a failed turn is one line led by its code (`index.js` `failureText`, e.g.
`TIMEOUT: …`), and a step requested again and broken again is marked first (`ASUNA_RETRIED_ONCE`); `faults.cause`
reads a leading code, one-word ones included. Before this, 9 of the 12 unread failed-turn notes named only
`RuntimeError` and 3 named a piece of raw text.

**N1. The line about a failed turn says what was lost** (her need, line 0370, 0386). `HER_LINE` gains the turn's own
count of what went out and what was done, from that episode's records: how many of her lines were published (lane
receipts), and which of her tools completed (the episode's `role_tool` rows), by name only, never an argument (line
0393). Three shapes: nothing went out and nothing was done; what went out and what was done; and requested again
once and broken again. Never the text. The tools named leave out `speak` (what went out is counted as lines),
`stay_silent` and `think` (a thought is not a deed), a refused call, and a name already listed. The counts are read
when her line is made (the fault keeps its episode), so a line delivered after the failure is counted.

The cause in the brackets is never the error's own text, which can carry what the model wrote (her `think`, line
0404): it is a word from a table (`faults.CAUSES`), and a code not in it is 「出错类型未辨」 (「原因没记下来」 when
none was recorded):

| Code | Her word |
|---|---|
| `MALFORMED_RESPONSE` | 模型回来的工具参数不成形 |
| `TRANSPORT` | 连不上模型 |
| `TIMEOUT` | 模型超时没回 |
| `CONTEXT_WINDOW_EXCEEDED` | 对话太长，模型装不下 |
| `PI_AI_ERROR` | 模型服务报错 |
| `INVALID_REQUEST` | 模型拒收了这次请求 |
| `NO_ADAPTER` | 没有能用的模型 |

Her wording (line 0393, 0396, 0403, 0404):

- Nothing went out, nothing done: 「你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么。那一拍你没说出口一个
  字、也没做成任何事——那件事到现在还是没做。」 The last half is required: a line that says only "did not run" reads as
  half done, and the act is not done again.
- Requested again and broken again (R1): 「你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么。程序为重请求过
  一次，第二次还是没跑成，没再自动重跑——那件事到现在还是没做。」
- What went out and what was done (line 0404): 「那一拍你发出去 %d 句、做成了这些工具：%s。已经送出去的话不用重发；列出来的
  工具先核它落地没有，再决定要不要重做。」 With no tool completed, the tools half and its note are absent (「那一拍你发出去
  %d 句。已经送出去的话不用重发。」); with nothing sent, the lines half and its note (「那一拍你做成了这些工具：%s。列出来的工具
  先核它落地没有，再决定要不要重做。」). Names only, never "you meant to do X".
- The report: today the program writes a `developer_inbox` note per kind of failure a day (`faults.turn_failed`). Of
  the inbox's 55 notes, 12 were never read (`state: new`; 4 seen, 39 answered), and the 12 are all failed-turn notes
  (2026-10-25 to 2026-11-11), so 「已经报给开发者了」 claims more than happened. It becomes 「这条已经记进开发者收件箱；开发者
  收件箱里还有 %d 条没被读过。」 with the count read when the line is made; when the count cannot be read, that half is
  left out (「这条已经记进开发者收件箱。」), never shown as 0.
- **N2. The notes are read.** Big sis's line watcher also reports new program notes in `developer_inbox`, each read
  and marked when it appears. From the day that is in place, the report half becomes 「已经报给开发者，这条你不用替它报」
  (her wording, line 0396); not before. Nothing detects that day: big sis changes `faults.REPORTED` by hand in its
  own commit, and tells her on the line with the time it is installed (line 0405). Not part of this build.

## 3. Acceptance (her items)

- A retried step leaves one outbound receipt for what it says, and her next turn's history shows it sent once
  (line 0374).
- A retried step has in her history one `tool/call` and one `tool/result` for each call it makes, never a second
  (line 0403: the lost step of 2026-11-11 was a `write_document`).
- A second failure is never silent: her next turn there reads N1's line (line 0374).
- S1 and S2: no request of hers declares no tools while a stage is current or waiting; checked by `toolless_steps.py`
  (big sis's private tool) on her sessions with fixed criteria (line 0405): the window starts at the install; all her
  sessions; the character and the action lanes; a step counts when its `request/header` declares no tools while a stage
  of that session is current or waiting. Reported to her weekly: 0 such requests from the install on.
- N2 (line 0405): the report half changes only by hand, on the day the notes are read, and she is told on the line
  with the time; no detection.
- S3 (§7): no turn of hers waits for the worker while a stage of its conversation is held back; she is never left
  with a turn open and no step for longer than a worker start.

## 4. Tests

Each fails on the current code first: S1, a stage sent again while its copy is queued leaves one copy and records the
one removed; S2, a stage arriving during a running turn does not become current until that turn ends, and starts
after it, and one arriving while a Web turn of hers is admitted leaves that turn its own stage; R1, a
`MALFORMED_RESPONSE` step is retried once, on either lane, not when that step holds a tool call (one in another step
of the turn does not stop it), not when the records cannot be read, not twice, not for another code; N1, the three
shapes, and the count half left out when it cannot be read. In `packages/cognition-core/test/stage-order.test.js`
(DSH's own loop, a scripted model; on the code before this build the R1 and S1 tests fail and the two S2 tests never
end) and `tests/test_fault_line.py` (the line, a cause not in the table, the retried mark kept with the fault).

## 5. Closes when

Built, and shown in an isolated DSH profile with a stub model that answers the first request with malformed tool
arguments: once followed by a good answer (one receipt, `asuna/retry` once, her history clean), once followed by a
second malformed answer (the turn fails, her next turn there reads N1's line), and in action sessions twice (line
0408): a job on 高 whose step breaks, then breaks again on the action route (the fallback takes the first, R1 does not
add a second: one `asuna/retry` by `fallback`, the task ends as now), and a job not on 高 (R1 takes it once, its task
goes on); and S1 and S2 by the staged sequence
of §1 (a stage queued, the worker restarted and the stage sent again; a stage sent during a running turn), with no
tool-less request. Then installed, and her sessions read with `toolless_steps.py` after the install. S3 (§7) is
built, shown (§7.5) and installed before this ADR closes.

## 6. Shown (2026-11-12, isolated demo profile)

The branch installed into its own DSH profile and database (`asuna_v2_demo_adr127`, the demo persona, dropped after),
every route on a local stub model speaking the OpenAI protocol through DSH's pi-ai adapter, which turns tool
arguments that are not JSON into `MALFORMED_RESPONSE` as her model server's did. No real model was called (the Host
started without any model key in its environment). Read from the demo's own session records and database:

- Her turn, malformed then good: `assistant/attempt`, `asuna/retry` (`by: retry`), the same step answered, one
  `tool/call` and one `tool/result` in it.
- Her turn, malformed twice: two requests, the turn `FAILED_RUNTIME`; the recorded failure led by
  `ASUNA_RETRIED_ONCE` and `MALFORMED_RESPONSE` (the cut arguments stay in the episode's failure, never in her line);
  the conversation's fault mark kept the code, the episode and `retried`; her next turn there read 「你在这里 11/12 19:03
  那一回合没跑成：是程序出了错（模型回来的工具参数不成形），不是你做错了什么。程序为重请求过一次，第二次还是没跑成，没再
  自动重跑——那件事到现在还是没做。这条已经记进开发者收件箱；开发者收件箱里还有 1 条没被读过。」
- A job not on 高, malformed then good: `asuna/retry` (`by: retry`) once, the task completed.
- A job on 高, malformed twice: two requests in all, one `asuna/retry` (`by: fallback`), no third request, the task
  ended as now. The fallback's own request for that step still goes to 高's model (ADR-075 selects the action route
  from the next step); unchanged here.
- S2's admission of her Web input on a real worker. Staging found a fault the unit tests could not: the worker read
  the input's message ids from the turn's context, which does not keep them, so her Web turn waited for an answer it
  had already been sent and never began. Fixed (`065fe8b9689c`): the ids come from the turn's inbound line, and while
  her input is admitted only a stage that answers no Web input of hers waits.
- 0 requests on her lane or the action lane declared no tools in the whole staged run.

Not staged live, and why: a stage arriving while a turn of hers runs (in the demo a delegated task starts only after
the turn that delegated it ends, so no stage arrives mid-turn by itself), and a copy kept by DSH's inbox across a
restart (it needs the Host to stop between a stage's queueing and its turn's start). Both are shown on DSH's own loop
in `stage-order.test.js`, which fails or never ends on the code before this build.

Read on her own records after the install instead (her line 0409; mechanism only): a stage that waits leaves
`asuna/stage-waited` (its operation, `behind: stage | turn`, how many wait), so a stage that arrives while a turn of hers
runs is seen to wait and not to become current, and is not counted as a replaced copy; and at the install's restart,
the stage messages left pending in her conversations' DSH inboxes before the stop are counted, and after the start the
`asuna/stage-copy-replaced` records and any stage queued twice. No pending stage is made for this: what the stop finds
is what is read, 0 included.

Seen in passing, not this ADR: a task-result turn that keeps failing the end-of-turn check is continued as a new
generation with no limit (`coordinator._advance`, `feedback.continued`); with the stub it reached 209 generations in
four minutes. Raised as its own task.

## 7. S2's deadlock (2026-11-12 evening) and S3 (drafted, not built)

### 7.1 What happened (her Web conversation, session records read for structure only)

- 21:25:05: the owner's Web message started turn 3716. `admit` handed it to the worker (`input`) and waited for the
  stage answering its message ids.
- 21:25:26: a stage of the same conversation arrived first: a `note` episode the worker had already taken. Its
  `inputs` were empty, so `another()` held it back; DSH was running a turn, so S2 queued it (`asuna/stage-waited`,
  `behind: turn`, `waiting: 1`).
- From then on: the turn waited for the worker's answer; the worker runs one episode at a time for all her
  conversations (`chat.py`, one `SceneQueue` and one consumer), so it was waiting for the note's result and the input
  sat behind it; the note waited for the turn to end. The circle's one exit was the worker's stage deadline
  (`workflow_timeout_seconds`, 1800 s in her config): at about 21:55:26 the worker would have given the note up
  (`task_fenced`, `STAGE_TIMEOUT`) and gone on to the input, leaving the note's stage in the plugin's queue to start
  a turn nobody reads. She took no turn anywhere (Web, QQ, her agent lines, her clocks) until the owner pressed Stop
  at 21:51:41.
- After Stop: the turn ended with no step; the note started in its own turn (3717) and finished at 21:52:32; the
  worker then took the owner's input, and its answer started its own turn (3718). The worker restarted itself at
  21:52:32 (her publication, `published-worker`), and turn 3718 waited for that start (about 3 minutes, by design)
  before its first step at about 21:55:50. A Web message inserted at 21:44:22 left DSH's queue three seconds later
  without reaching the worker; no path of the plugin removes a queued message of hers (the review), so it was most
  likely removed in the Web page's queue, not by the circle (not verified).
- 21:58:22: a second owner Web message started turn 3720 while the worker was preparing a `self_development` episode
  of the same conversation; its stage arrived at 22:00:23 and was held back the same way. The owner's Stop at 22:01:34
  ended it, and that stage started its own turn (3721) in the same second; a second Stop at 22:01:36 stopped turn
  3721 mid-request, so that episode ended `FAILED_RUNTIME`. She went on at 22:01:57 (a task's result, then the owner's
  message in its own turn).

Only a turn that admits her input waits on the worker (`admit` with its message ids: her Web messages, and a joined
home line); while it holds, everything of hers waits behind the one worker queue.

### 7.2 Why S2 missed it

S2 holds a stage back behind a turn. That is safe only when the turn does not wait for the worker: a held-back stage
always blocks the worker, which answers in order and waits for each stage's result. Her Web turn does wait for the
worker (`admit`), so S2 and `admit` together can make a circle. The broken invariant: **the worker's order is the
order of her turns; a turn may wait for the worker only while nothing of its conversation is held back.**

Before this ADR the waiter took whatever came first: the note's stage would have been admitted with the owner's
message and run in its turn (the mixing of §1), his answer in a second turn; no hang. The circle came with `another()`
(the filter that keeps another's stage from her waiting turn), not with S2's queue alone.

`stage-order.test.js` did not see it: its scripted worker answered an input at once, even while an earlier stage of
its own was unanswered, which the real worker never does. The staging of §6 did not see it: "a stage arriving while a
turn of hers runs" was the one case not staged live.

### 7.3 S3. Her Web turn steps aside for what is held back

1. **Wait only while nothing is held back.** `admit` hands her Web messages to the worker (`input`, as now) and waits
   for the worker's answer only while no stage of the conversation is queued. A queued stage that answers a Web input
   of hers is taken as this turn's answer (`next()` with ids looks in the queue; any answer to her input is hers, as
   `another()` already says).
2. **Step aside.** When another's stage is already queued, or arrives while the turn waits (it is queued by S2, and
   the waiting turn is told), the turn steps aside: its step is refused (`agent/pre-step` answers `reject`, the path
   `admit` already uses for an input that needs no turn), so it ends `blocked` with no step and no model call, and
   DSH goes idle (pinned DSH: a refused step returns from `turn()`; a new turn starts at once only for a message
   waiting in the inbox, and that turn steps aside the same way). The held stage then starts in its own turn
   (`resume`), and the worker goes on in its order. Recorded: `asuna/input-stepped-aside` (the held stage's operation,
   how many of her messages are kept).
3. **Kept, and carried with the next answer.** A message the worker has and no turn carried (its turn stepped aside,
   or its wait ended without an answer: a stop, a worker restart or failure) is kept by id (`state.handed`, in order).
   The first step whose stage answers a Web input of hers (admitted with her input, or started on its own after it
   waited: `state.current`) carries the kept messages first, then its own; they are then dropped. Recorded:
   `asuna/input-returned` (that stage's operation, how many). A message whose `input` call failed is not kept: the
   worker never had it.
4. **Lifecycle of `handed`.** Made by `admit`; used and emptied by that step; kept through a worker restart or failure
   (the worker keeps the input durably and sends its answer after the start, as on 11-12 21:53); lost with the Host
   (memory only), in which case the answer starts by its own message alone, as turn 3718 did. A message kept whose
   answer the worker never sends comes with the next answer to any Web input of hers.

5. **A stage's turn never takes her waiting message.** DSH's turn claims only the first message waiting for the next
   turn, and a refused step leaves a message of hers waiting there without waking the agent. So when a stage starts
   (`startStage`), her messages waiting for the next turn are taken out, the stage's message is sent (it wakes the
   agent), and hers are put back behind it: the stage's turn claims the stage's message, and hers follow in their own
   turn. Without this the stage's turn claimed her message and failed (`admit`: input during an unfinished stage).
6. **Kept on every outcome but an answer.** An `admit` that ends with anything but a stage (an error, the worker's
   word that no turn follows) keeps her messages the same way, so a refused step never drops one.
7. **A stage given up leaves the queue.** `task_fenced` (the worker's deadline, or a task fenced) removes a waiting
   stage of that operation, recorded as `asuna/stage-dropped` (operation, reason), so a stage nobody reads never
   starts a turn. This was S2's own gap.

Every wait of a Web turn then has an exit: the answer comes, or another's stage arrives (the turn steps aside), or
the worker fails or restarts (the wait is rejected), or the owner stops it. No timer is added.

Not changed: S1, S2 for every turn that does not wait for the worker, R1, N1, and the worker's single queue.

Considered and not taken (the review): never let a turn wait for the worker at all (every Web message's step
refused at once, its messages put back with the answer). One path and the order by construction, but every Web
message would leave a stepless turn, and the owner would see no running reply while the worker prepares.

Known gaps: `handed` lives in the plugin's memory, so a Host restart loses it and the answer then starts by its own
message alone (rebuilding it from the durable inbox records by id is possible, not done); whether that message carries
the owner's words, and how DSH's Web page shows a message whose turn stepped aside until it comes back, are read in
the staging.

### 7.4 Tests (fail or never end on the code before S3)

In `stage-order.test.js`, on DSH's own loop with a worker double that keeps the real worker's order (her input
answered only after the result of a stage it sent before); the old S2 test whose double answered her input before
its own earlier stage is replaced. The 11-12 sequence (a Web turn waiting, another's stage arrives first: it runs in
its own turn, then her message with its answer, the stepped-aside turn `blocked` with no request); a Web turn begun
while a stage already waits (it steps aside at once); a Web turn stopped while it waits (its message comes with the
answer that then starts on its own); her second message waiting behind a turn that stepped aside (the stage's turn
carries neither of hers; both come with the next answer, each once); and a waiting stage the worker gave up on
(dropped, no request). On the code before S3 the first two never end and the third fails; without (5) the fourth
never ends.

### 7.5 Shown, then installed

In an isolated demo profile with a stub model and the real worker: the 11-12 sequence made on purpose (the demo
conversation's beat slowed in its preparation, a Web message sent in that window), labeled 造的: one
`asuna/input-stepped-aside`, the beat's turn, then her answer's turn carrying the message, no stepless turn left
open. Then installed in a restart slot she gives, and read on her records: every `asuna/stage-waited` behind a Web
turn followed by `asuna/input-stepped-aside`, and no turn of hers open with no step for longer than a worker start.

### 7.6 Until S3 is installed: what to do when she is stuck

- **Seen as:** her Web reply waits with no text, and her other places go quiet. Big sis's private
  `stuck_turns.py` names it: a turn of her Web conversation open with no step, with an `asuna/stage-waited`
  `behind: turn` after it.
- **Unstick:** the owner presses Stop on that waiting reply, **once**. On 11-12 the held stage started in its own
  turn within a second, and the worker then answered the stopped message in its own turn; the message is not sent
  again. A second press lands on the held stage's new turn and stops it, and its episode fails (22:01:36). A message
  written while she was stuck may not reach her: send it again once she has answered, and not while she is busy.
- **If after Stop a turn again has no step:** a worker start may be running (`restarts-to-tell.json` holds an entry
  with no `back`); a turn waits for it by design (about 3 minutes on 11-12). Wait for it.
- **Last resort:** a Host restart through the launcher clears the plugin's waiting state; the worker sends its
  answers again after the start.
- **Not done:** rolling S2 back. Without it the 10:47 sequence of §1 (a stage made current under another's turn,
  turns with no tools) comes back.
- **Avoided until then:** a Web message to her while she is busy with something of her own in that conversation (a
  beat, a note, a task's result, a publication); only that starts it. QQ, the agent lines and her clocks cannot.
