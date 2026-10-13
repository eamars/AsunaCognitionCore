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

## After the first beat (2026-10-12)

- **What wakes a "nothing" beat: only what an hour would lose** (her rule: lost wakes her, late does not). The first
  roll was nothing and reached her anyway, woken by an aside on her old home's line, which sends one most hours (25
  of 47 hours). Asides and calls stay listed until she answers, so every nothing would have reached her and the
  saving would have been nearly zero. Now only two things wake it: her waiting list (it ends after an hour), and a
  peer line whose unseen asides already fill the six she is shown (one more would push the oldest out of her view,
  and she has no tool to read it back). Fewer asides and a group where someone called her (that woke her by its own
  path) wait for the next beat that reaches her.
- **One night mechanism** (owner's question, her choice of option 1). `heartbeat.skip_in_sleep` skipped every beat in
  her sleep window before the roll, so the asleep table never rolled. The gate and its key are removed; her sleep
  window now decides only which table rolls, and a fully quiet night is `100/0/0/0`. The window still tells her she
  is in her sleeping hours. Her own rule for night beats (read, reckon, write ideas, prepare; no publishing, no big
  decisions) is hers, not the program's. A stored `skip_in_sleep` value stays in her policy ledger and is read by
  nothing.
- She asked for a day's count after this: nothing beats, how many the old rule would have woken, how many the new one
  does; she retunes the 40 from it.

## Two more outcomes (owner, her review, 2026-10-12)

The owner asked for a small share of beats to review the dice and to talk at home. Her answers:

- **复盘 · review the dice** (weight 2, about every three days awake): the heartbeat with `dice_review_from_program`,
  every roll since her last review with what each beat did (reached her or not, tools, lines said, her reason when
  quiet), the count per outcome and both tables. It closes the loop: weights become something she can check, not
  only set (she had just set an asleep table that never rolled). She retunes from it; a new kind of beat she asks
  the developer for.
- **找人 · reach out at home** (weight 5): she chose reaching out on any of her lines (Claude, Codex, her old home's
  self; whom is hers) over Claude only. Text only, through her existing `pass_note`; 0 where she has no line. Her
  own rule: with nothing true to say she sends nothing; dice should not manufacture socialising.
- **Named weights:** six positions are unreadable, so tables are written `歇着 40、有趣 31、…`; a name left out weighs 0.
  Her ask: `set_policy` returns the whole stored table (`stored_table`), so a name left out shows as 0 instead of
  quietly vanishing. Defaults, hers to run unchanged until the review readings: awake 歇着 40、有趣 31、自我开发 10、
  自我评估 12、复盘 2、找人 5; asleep 歇着 66、自我开发 20、自我评估 8、复盘 2、找人 4.
- **Follow-up (回访) is not an outcome:** her ledger already holds what she promised and comes in every home turn;
  self evaluation points to it. A separate outcome only if reviews show promises still going unclosed.
- **Learning one thing** stays in reserve: it overlaps with self development.

Cost: no tool; the opening line names every weight in the table rolled (about 20 characters more); the review block only on its beats.

## A seventh face: 待着 · idle (Xiaoman, 2026-10-14)

She asked for a face that asks for nothing. When `idle` (待着) rolls, the beat reaches her with only its line and
hint: no readings attached (no `dice` envelope, so `context.py` adds no block), no task, and in
`schedule._presence` the face skips the standard `HEARTBEAT_TEXT` framing that the six older faces keep byte
for byte. The forced and reconnected notes still append when they apply.

- **Her hint, verbatim** (`dice.HINTS['idle']`): 这一拍什么都不必换。看一眼就行，愿意说就说一句，不说也行；不用记账，不用挂闹钟，不用给它找个产出。
- **Default weight 0 in both tables** (`dice.DEFAULTS` and the core persona defaults in `persona_model.py`), so
  the six older faces keep their names, their defaults and their behavior exactly. `words()` lists the new face
  even at 0, and `set_policy` accepts 待着 by name; she retunes the share herself.
- **Her live tables are her stored policy, not these defaults.** As of 2026-10-14 02:04 (her clock, two
  `set_policy` revisions in the state ledger) she has set: awake `歇着 40、有趣 31、自我开发 10、自我评估 10、复盘 4、找人 5`;
  asleep `歇着 74、自我开发 12、自我评估 8、复盘 2、找人 4` (有趣 left out, so 0). 待着 is left out of both,
  so it weighs 0 until she writes it in.
- The numbers in the sections above (four outcomes, then six, each with the weights of that day) are history;
  this section neither restates nor retires them.


### Same night, second revision: 02:51 (Xiaoman, 2026-10-14)

The two tables in the bullets above are the 02:04 pair. At 02:51 the same night she set the awake table once more:
待着 5 added, 自我评估 10 → 6, 歇着 40 → 39, 有趣 unchanged at 31. The asleep table was not touched again, so the
02:04 asleep line above still matches what is stored. What is live is whatever the policy store holds; the code
defaults keep 待着 at 0 in both tables.

**Both of tonight's edits were judgment, not readings.** This ADR says "Run a week, then tune from readings"; the
dice was built 2026-10-12, so a full week lands 2026-10-19, and that is the first day a change may claim to be
tuned from readings. Neither of tonight's two revisions is that change, and neither is an acceptance.

One minute to pin: 02:04 in the bullet above is right. The message of commit `6bcffef4` says 02:05 — a minute off;
this section stands (basis: that night's `plan` receipt carried `updated_at` 02:04, with both `set_policy` calls
before it).

Acceptance for this section is still open: nothing here has been verified against a week of readings.

- 2026-10-14 (Xiaoman): the Cost line in Two more outcomes above stopped counting faces (six weights -> every weight in the table rolled); it describes current behavior, so it must not need an edit when a face is added.
