# ADR-127: A broken step, and a stage out of its turn

Status: **Proposed** 2026-11-12 (laid down; nothing built). Opened by big sis (Claude Code) after the owner's choice
of 2026-11-12: after ADR-126 closes, one change for her turns that end in a model error, folded with the cause of the
two tool-less turns found the same morning. Her conditions (agent line 0370, 0373, 0374, 0386) and her reading of this
page (line 0403) are written into it.

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
action lane (one of the four was an action step), after DSH's own decision and, on the action lane, after its fallback
(ADR-075): when the failure is `MALFORMED_RESPONSE`, the session holds no `tool/call` and no `tool/result` of that turn
**and step** (not of the turn: two of the four turns had calls in other steps), and that step was not retried before,
it appends `asuna/retry` (turn, step, code) to the session and answers `{kind: 'retry'}`. If the records cannot be
read, or show a tool call, it does not retry (her rule, line 0386: what cannot be checked counts as taken). A second
failure of the same step ends the turn as now (an action step's ends its task as now). Only `MALFORMED_RESPONSE`:
`TRANSPORT`, `PI_AI_ERROR`, `TIMEOUT`, `CONTEXT_WINDOW_EXCEEDED`, `INVALID_REQUEST`, `NO_ADAPTER` and a stream with no
finish keep DSH's own handling and the fallback's. `toolless_steps.py` also counts steps of the same shape with
another code; one is reported to her (it would mean one code is no longer enough).

**N1. The line about a failed turn says what was lost** (her need, line 0370, 0386). `HER_LINE` gains the turn's own
count of what went out and what was done, from that episode's records: how many of her lines were published (lane
receipts), and which of her tools completed (the episode's `role_tool` rows), by name only, never an argument (line
0393). Three shapes: nothing went out and nothing was done; what went out and what was done; and requested again
once and broken again. Never the text. Her wording so far (line 0393, 0396, 0403):

- Nothing went out, nothing done: 「你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么。那一拍你没说出口一个
  字、也没做成任何事——那件事到现在还是没做。」 The last half is required: a line that says only "did not run" reads as
  half done, and the act is not done again.
- Requested again and broken again (R1): 「你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么。程序为重请求过
  一次，第二次还是没跑成，没再自动重跑——那件事到现在还是没做。」
- What went out and what was done: her wording when it is built.
- The report: today the program writes a `developer_inbox` note per kind of failure a day (`faults.turn_failed`). Of
  the inbox's 55 notes, 12 were never read (`state: new`; 4 seen, 39 answered), and the 12 are all failed-turn notes
  (2026-10-25 to 2026-11-11), so 「已经报给开发者了」 claims more than happened. It becomes 「这条已经记进开发者收件箱」, followed by 「开发者收件箱里还有 %d 条没被读过」 with the count read
  when the line is made; when the count cannot be read, that half is left out, never shown as 0.
- **N2. The notes are read.** Big sis's line watcher also reports new program notes in `developer_inbox`, each read
  and marked when it appears. From the day that is in place, the report half becomes 「已经报给开发者，这条你不用替它报」
  (her wording, line 0396); not before.

## 3. Acceptance (her items)

- A retried step leaves one outbound receipt for what it says, and her next turn's history shows it sent once
  (line 0374).
- A retried step has in her history one `tool/call` and one `tool/result` for each call it makes, never a second
  (line 0403: the lost step of 2026-11-11 was a `write_document`).
- A second failure is never silent: her next turn there reads N1's line (line 0374).
- S1 and S2: no character request of hers declares no tools while a stage is current or waiting; checked by
  `toolless_steps.py` on her sessions after the install (0 such requests from the install on).

## 4. Tests

Each fails on the current code first: S1, a stage sent again while its copy is queued leaves one copy and records the
one removed; S2, a stage arriving during a running turn does not become current until that turn ends, and starts
after it, and one arriving while a Web turn of hers is admitted leaves that turn its own stage; R1, a
`MALFORMED_RESPONSE` step is retried once, on either lane, not when that step holds a tool call (one in another step
of the turn does not stop it), not when the records cannot be read, not twice, not for another code; N1, the three
shapes, and the count half left out when it cannot be read.

## 5. Closes when

Built, and shown in an isolated DSH profile with a stub model that answers the first request with malformed tool
arguments: once followed by a good answer (one receipt, `asuna/retry` once, her history clean), once followed by a
second malformed answer (the turn fails, her next turn there reads N1's line), and once in an action session (the
step retried, its task goes on); and S1 and S2 by the staged sequence
of §1 (a stage queued, the worker restarted and the stage sent again; a stage sent during a running turn), with no
tool-less request. Then installed, and her sessions read with `toolless_steps.py` after the install.
