# ADR-130: A turn of hers waits, open and empty, behind another conversation's turn

Status: **Closed, not built** 2026-11-13 (the owner). Proposed the same evening by big sis (Claude Code), from
ADR-127's after-close reading. Times on this page are local time.

## 1. What was found

ADR-127's S3 reading for her 20:45 clock (2026-11-13, the segment after ADR-129's second install at 20:12:17):

- A turn of her local Web chat opened at 20:26:40 and took its first step at 20:37:54: 674 s open with no step.
- Her agent-line turn 2805 ran from 20:25:26 to 20:37:51 (twelve minutes, over twenty steps, answering the developer's
  messages on that line). The home turn's first step came 3 s after it ended. The agent-line turn progressed the whole
  time; nothing was stuck.
- The worker runs her character turns one at a time. The home turn's DSH turn opened and waited in `admit` for the
  worker's answer. No stage of the local chat was held back, so S3's step-aside (ADR-127 §7.3: a Web turn steps
  aside when a stage of its own conversation is queued) did not apply.
- The owner, watching the home page: the developer's input interrupted her while she was thinking. The page showed a
  turn of hers running with nothing in it for eleven minutes.

ADR-127's S3 promise, "she is never left with a turn open and no step for longer than a worker start", does not hold
when the worker is busy with another conversation. This is a new finding, not ADR-127 reopened: S3 does what §7.3 says.

## 2. The broken invariant

A turn of hers is open only while it can step. A turn that cannot step yet (the worker is running another of her
conversations) is not a turn: it is a message waiting.

## 3. Options (the owner's choice)

- **A. Step aside for a busy worker too (recommended).** S3's rule 1 widened: her Web turn waits for the worker only
  while the worker is free; when the worker is running another conversation's turn, the Web turn steps aside the way
  S3's does (its step refused, it ends `blocked` with no step and no model call), her message is kept (S3's
  `state.handed`), and its own turn starts when the worker reaches it, carrying the kept message (S3's
  `asuna/input-returned`). The same path S3 built and staged; the page shows no empty running turn, only her message
  waiting. Nothing changes in which turn runs first.
- **B. Order.** Her home turns go before turns of other conversations already queued. It does not help while a long
  turn is already running (this case), so it is not enough alone.
- **C. Fewer and batched developer messages.** Already the developer's rule from 11-13 (one batched message, none that
  only acknowledge, non-urgent lines held while she is busy at home). It lowers how often this happens; it does not
  remove the case: a QQ or peer-line turn can do the same.

## 4. Closes when

Chosen by the owner, designed, shown in a demo profile (a long turn of one conversation while a Web message arrives:
the Web turn steps aside with no step, its message carried when its turn starts), installed in her slot, and then a
reading over her use finds no turn of hers open with no step for longer than a worker start.

## 5. Closed (the owner, 2026-11-13)

"The bottleneck is the model server, nothing can be done to help with that, opening new turn aside couldn't really
help." Every turn of hers goes through the one model server, so a Web turn stepping aside (option A) would change what
the page shows, not when her answer comes; B does not help while a turn already runs. What shortens the wait is fewer
and shorter turns: option C, already in effect (the developer sends one batched message, none only to acknowledge;
she keeps work that is not urgent out of a turn that answers him, agent line 0468).

The reading changes with it: ADR-127's S3 reading (`toolless_since.py`, the developer's tool) sorts a wait behind
another conversation's turn into its own class, `behind a turn` (a turn of another of her conversations ran from
before this one opened until at most 15 s before its first step), not judged; only `neither` over 180 s is a failure.
Read so on 2026-11-13: the 674 s wait of §1 is `behind a turn`; every wait over 10 s since 13:01 is too; the longest
`neither` wait is 3 s.
