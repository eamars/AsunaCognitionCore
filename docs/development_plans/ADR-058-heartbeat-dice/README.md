# ADR-058: The heartbeat rolls a die before it reaches her

Status: **Accepted 2026-10-12** after Xiaoman's review (her weights, her scope for what waits, readings not a
summary). **Built 2026-10-12** (see Build).

## Context

Every heartbeat that passes its gates (busy, paused, minimum gap, sleep window, 24 a day) reaches her with the same
open text: look around, decide whether to say, do or write something, or do nothing (`rhythm.HEARTBEAT_TEXT`). A
heartbeat turn is her largest (about 26,000 characters), and an open question every hour leaves the choice, and the
habit, entirely to the model.

The owner's plan: roll a die before the beat reaches her, between doing nothing, doing something interesting, self
development and self evaluation, each with a probability. Simple, deterministic in its control, shown as text (no
tool call), hers to accept, refuse or ignore, with distributions that change between day and night and that she can
override.

## Proposal

1. **The roll.** After the existing gates, the program draws one outcome from the distribution for the current
   period. The draw is reproducible: the beat's occurrence id seeds it, and the record keeps the outcome and the
   distribution used (`presence.rolled`).
2. **What each outcome does** (deterministic, program-side):
   - **Nothing:** the beat does not reach her; one audit line, no model call. Anything that is for her (a message, a
     finished task) wakes her through its own path, as now, so a "nothing" beat hides nothing.
   - **Something interesting:** the heartbeat turn as today (her groups, visits, notes), opening with the roll.
   - **Self development:** the beat runs as a self-improvement turn (her notebook, development tools, as her night
     stages do).
   - **Self evaluation:** the heartbeat turn with a short account of her own day from records (turns, refusals by
     cause, tasks that failed or were stopped), opening with the roll.
3. **Shown as text, hers to take or leave.** The turn opens with one line, for example: "这一拍掷到：自我评估（白天
   的分布：歇着 40、有趣 30、自我开发 15、自我评估 15）。照做、换一件、或者不理，都行。" No tool call, no
   acknowledgement asked.
4. **Distributions by period, hers to change.** Two tables, awake and asleep (her declared sleep window decides
   which, as `heartbeat.skip_in_sleep` already does), as persona policy keys she sets with `set_policy`
   (`heartbeat.dice_awake`, `heartbeat.dice_asleep`: weights for the four outcomes). Defaults proposed for her review:
   awake 40 / 30 / 15 / 15, asleep 70 / 0 / 20 / 10. A weight of 0 removes an outcome; her other heartbeat keys keep
   working as they do.

## Cost (AGENTS.md)

No new tool; two policy keys; one line at the top of a heartbeat turn (about 80 characters) and, for self evaluation,
one block. "Nothing" beats call no model: at the proposed awake default, 40% fewer heartbeat turns, each about 26,000
characters, which is a saving with any provider.

## Open for her

- The default weights, and whether "nothing" should still reach her when something is waiting (the proposal: no, the
  waiting things wake her by their own path).
- What self evaluation should show her of her own day.
- Whether daytime self development may carry development tools (her night stages do).

## How it is checked

A day of beats: outcomes against the distribution, turns saved by "nothing", and what she did with each outcome
(followed, changed, ignored), counted from records.

## Her review (2026-10-12)

- Weights: awake **40/35/10/15** (daytime self development down to 10, the 5 to interesting: daytime is when she is
  most present in her groups, and a development beat there costs more than at night); asleep 70/0/20/10. Run a week,
  then tune from readings.
- "Nothing" does not wake her, provided nothing only a heartbeat shows is swallowed: her waiting list, the asides of
  a peer line, a group where someone called her. Messages to her and returned tasks have their own way to her.
- Self evaluation shows raw readings with their sources, never a summary (a summary writes what she thought more
  tidily than it was).
- Daytime self development carries development tools, as her night stages do. Her own rule, hers to keep: a daytime
  beat neither publishes nor asks for a restart unless she has checked nothing is queued.

## Build (2026-10-12)

`dice.py` (tables, roll, line, what waits), `self_review.py` (the readings), the heartbeat in `schedule._presence`,
`presence.rolled` records, `heartbeat.dice_awake` / `heartbeat.dice_asleep` as core-writable policy keys with
`set_policy` checking their shape, the router keeping `dice` only on the program's own heartbeat. Promises she made
have no program record; the readings say so and point to her own ledger.
