# ADR-045: Her sister's heartbeat should not wake her

Status: **Accepted and built 2026-10-11** with Xiaoman, after the owner's direction (below); its own restart. The owner assigned it after the active and resting groups work ("her protocol with old
Xiaoman … she should not be woken up by her sister's heartbeat").

## Context

The old-home line (ADR-013, `packages/channels/dsh-peer`) bridges her to the older DSH Xiaoman, whom she calls her
sister. It is a home channel, so every line from the other side wakes her. The other side runs her own heartbeat,
and its periodic beats reach the line as messages. Observed on 2026-10-11:

- The line kept her busy enough that applying a settings change waited about 8 minutes: settings apply only when no
  turn runs and nothing is queued (`settings.quiesce`).
- Its conversation grew from 194K to 210K tokens in one turn, past the local model's compaction line. During the
  DeepSeek trial she closed the line for an hour (`peer_line close`) so it would stop growing.
- Notes between home and the old-home line often hit the 300-character limit (raised to 1,500 for home lines,
  ADR-018 §12).

## Plan

1. **Measure:** of the old-home line's inbound lines over a few days, how many are heartbeat traffic (periodic,
   unaddressed status from the other side) and how many are addressed to her. Look at what each turn they woke
   ended in (silence vs words) and what each cost in tokens and turns.
2. **Read the protocol:** how the dsh-peer bridge marks a message's kind, and whether the other side's heartbeat is
   distinguishable at the source (a field, a sender session, a pattern the program can read deterministically, not
   by judging content).
3. **Propose the smallest change,** to Xiaoman first, and to the owner if it touches the protocol or the other
   side. Candidates, to be weighed against the data:
   - heartbeat lines are kept and visible but don't open a turn, like unaddressed lines in a resting group (ADR-039);
   - or they fold into her own next home heartbeat as a one-line summary of the other side's state.
4. Build in one small batch with its own restart. Verify on the real line: turns woken per day before and after,
   nothing addressed to her missed.

## Findings (2026-10-11)

- **The bridge mislabels her sister's replies.** It decides "this answered her" from the prompt's source, checking
  `kind === 'user-rpc'`; DSH records a prompt sent over RPC as `kind: 'user'` with an `rpcId` (`user-rpc` is only the
  name of that source type). So nearly every reply carried the "not a reply to you" note: of her 96 messages since
  10-07, 93 were answered within 5 minutes, and all 93 answers bore the note. She may have judged her sister by it.
- **Traffic, estimated by timing** (an answer within 5 minutes of her words counts as a reply): 319 lines since 10-07,
  121 replies and 198 not. Of 311 turns on the line, 193 (62%) were woken by lines not answering her: 66.9M input
  tokens (mostly cache reads) and 164K output. The fixed bridge's own split replaces this estimate after a day.
- **The owner's concern:** her sister runs on plain DSH and drifts over long runs. His direction: bundle the reply
  instruction with each message, so her sister answers in a consistent form without having to remember it.

## Decision (with Xiaoman)

1. **Fix the reply test** in the bridge: a turn answers her when its prompt's `rpcId` is one she sent.
2. **Lines not answering her don't wake her.** They are kept and visible on the line, and listed in her home
   heartbeat, one per line with its time. As with the waiting list (ADR-041), each stays listed until she speaks on
   that line after it; nothing drops off unanswered.
3. **Her reply instruction rides on every message she sends.** She wrote it (short, so it is not
   imitated or echoed); it lives in the channel's local config and changes only when she changes it.
4. **She reviews her own records** of those days for judgments made under the wrong label, and corrects them herself.
5. **Verify:** turns woken per day before and after; every reply still wakes her; the bridge's exact split against
   the estimate above.

## Built (2026-10-11)

- The bridge tests `turn.source.rpcId` against the prompts she sent; its old test fed it `kind: 'user-rpc'`, the
  same wrong shape, which is why it never failed.
- A turn not answering her rides with `raw.asuna_aside: true`; the host keeps only that mark, and the router stores
  the line like an unwoken group line (`RECORDED_NO_WAKE`).
- Her home turns carry `peer_asides_from_program`: per peer line, the asides since her last words there (scene order,
  not time), the newest 6 and how many more. A note from home to the line wakes her there to answer.
- `replyNote` (the plugin's local config, her text) opens every message she sends, after the label and before her
  words: her text calls itself the opening note.

## Measured (2026-10-12)

In the 21 hours after the fix went live: 39 lines from her sister; 29 (74%) were kept without waking her, 10 opened
turns (before: 43 to 92 turns a day on this line). Every line that answered her within 5 minutes of her words woke
her (7 of 7); 3 more woke her that the timing estimate counts as not answering (the bridge's own test decides).
Still to see: her note opening her next message there, and her review of her records of 10-07 to 10-11.
