# ADR-045: Her sister's heartbeat should not wake her

Status: **Proposed 2026-10-11, investigation not started.** The owner assigned it after the active and resting groups
work ("her protocol with old Xiaoman … she should not be woken up by her sister's heartbeat").

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
