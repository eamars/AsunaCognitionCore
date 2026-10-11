# ADR-042: What her night turns changed, at the first heartbeat after them

Status: **Accepted and built 2026-10-11.** The owner's suggestion after a night decision went unrecognised; Xiaoman
wanted it and set what counts and where the night ends.

## Context

At 03:07 a self-improvement turn of hers made a fourth group active and wrote the reason in her work log. The same
afternoon her daytime self did not recognise the change and marked it "ownership unknown". It was traced back only
by searching the audit. The decision itself was sound; what failed was the hand-over from her night self to her
day self.

## Decision

- **The first home heartbeat after her night turns lists what they changed** (`night.py`, `night_from_program`):
  when, what in words, and the reason she wrote then. It is absent after a night with no changes, and a later
  heartbeat starts after the earlier one, so it shows once.
- **Night is decided by turn kind, not by the clock** (Xiaoman): self-improvement and settlement turns. Otherwise
  what she did in the evening would be labelled as her night self's.
- **What counts:** group focus, settings, self, restart requests, plans (Xiaoman: alarms set or cancelled at night
  are the ones most easily forgotten), her peer line, idea decisions, watches and document sections. Lookups and
  refused calls don't count.
- **Her work log by section name only** (Xiaoman): it is a running record, and listing every entry would turn the
  block into one she learns to skip.
- Computed from the audit, nothing stored. The audit gains an index on type and time, which this lookup needs.
