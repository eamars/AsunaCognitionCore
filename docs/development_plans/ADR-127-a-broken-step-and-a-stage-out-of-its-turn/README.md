# ADR-127: A broken step, and a stage out of its turn

Status: **Proposed** 2026-11-12 (laid down; nothing built). Opened by big sis (Claude Code) after the owner's choice
of 2026-11-12: after ADR-126 closes, one change for her turns that end in a model error, folded with the cause of the
two tool-less turns found the same morning. Her conditions (agent line 0370, 0373, 0374, 0386) are written into it.

## 1. What is known (2026-11-12, session records read for structure only: types, seqs, times, codes)

**Model errors.** Four of her turns ended in `MALFORMED_RESPONSE` from 2026-11-07 to 2026-11-11, none before: the
arguments of a tool call were not JSON. The model server's session reproduced all four; its parser fix (in production
since 2026-11-12) cures three, and the fourth (her reply written into `think`'s argument, cut by the end token) is a
model slip no parser can mend. In each of the four, the step's record (`assistant/attempt`) holds only reasoning and
a tool call, its finish is `error`, and the step has no `tool/call` and no `tool/result`; the turn has no lane
receipt and its episode ends `FAILED_RUNTIME`. Her reading (line 0373): the cut came at 637, 800 and 1,969
characters of arguments, and one of the four lost a `write_document` whose content had not started.

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

A tool-less request of hers was seen once before, on 2026-10-13 (its cause not read). Two invariants are broken: a stage's message is queued once; and a stage
becomes current only in the turn that will answer it.

## 2. Design

**S1. One copy of a stage's message.** Before `onEvent` queues a stage's message, every message already queued for
the next step or the next turn that carries the same `source.operation` is removed; then the fresh one is queued
(composed now, so its context is current). A copy kept by DSH's durable inbox across a restart is so replaced, never
doubled.

**S2. A stage starts only when no other turn runs.** `onEvent` makes a stage current only when the conversation has
no current stage and DSH is not running a turn; otherwise the stage waits in `state.queue`, as it already does behind a
current stage. A turn that ends takes the next waiting stage (`next()`, as now); a turn that ends with no stage, and
the conversation going idle, start the next waiting one the way `onEvent` does. So no turn's output is taken for a
stage it did not read (and `admit` no longer meets a stage made current under a Web turn it is admitting).

**R1. A broken step is requested again, once.** A listener on her character lane's `agent/request-error`, after DSH's
own decision (as the action lane's fallback is): when the failure is `MALFORMED_RESPONSE`, the session holds no
`tool/call` and no `tool/result` of that turn and step, and that step was not retried before, it appends
`asuna/retry` (turn, step, code) to the session and answers `{kind: 'retry'}`. If the records cannot be read, or show
a tool call, it does not retry (her rule, line 0386: what cannot be checked counts as taken). A second failure of the
same step ends the turn as now. Only `MALFORMED_RESPONSE`: other codes keep DSH's own handling.

**N1. The line about a failed turn says what was lost** (her need, line 0370, 0386). `HER_LINE` gains the turn's own
count of what went out and what was done, from that episode's records: how many of her lines were published (lane
receipts), and which of her tools completed (the episode's `role_tool` rows). Two shapes at least: nothing went out
and nothing was done; or what went out and what was done. Never the text. Her wording, given by her before it is
built (her F8 rule).

## 3. Acceptance (her items)

- A retried step leaves one outbound receipt for what it says, and her next turn's history shows it sent once
  (line 0374).
- A second failure is never silent: her next turn there reads N1's line (line 0374).
- S1 and S2: no character request of hers declares no tools while a stage is current or waiting; checked by
  `toolless_steps.py` on her sessions after the install (0 such requests from the install on).

## 4. Tests

Each fails on the current code first: S1, a stage sent again while its copy is queued leaves one copy; S2, a stage
arriving during a running turn does not become current until that turn ends, and starts after it; R1, a
`MALFORMED_RESPONSE` step is retried once, not when the step holds a tool call, not twice; N1, the two shapes.

## 5. Closes when

Built, and shown in an isolated DSH profile with a stub model that answers the first request with malformed tool
arguments: once followed by a good answer (one receipt, `asuna/retry` once, her history clean), once followed by a
second malformed answer (the turn fails, her next turn there reads N1's line); and S1 and S2 by the staged sequence
of §1 (a stage queued, the worker restarted and the stage sent again; a stage sent during a running turn), with no
tool-less request. Then installed, and her sessions read with `toolless_steps.py` after the install.
