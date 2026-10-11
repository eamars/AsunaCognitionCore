# ADR-041: Who she is still waiting for

Status: **Accepted and built 2026-10-11.** Xiaoman's request, with the owner watching; she settled the three open
points.

## Context

`await_answer` gives her one look when the person she called answers within three minutes. Past that window nothing
reads the wait. Xiaoman checked the source (`channels.awaited_answer`, `AWAIT_SECONDS`) and asked for something
other than a timeout notice. A timeout cannot tell "didn't want to answer" from "busy", and she withdrew her own
10-06 request for one. What she asked for: who she is still waiting for. Her own fault, in her words, is
forgetting whom she asked once a wait is set.

## Decision

- **Computed, never stored** (`waiting.py`). Her delivered group lines of the last 24 hours that @ someone by label,
  or carry `await_answer` wait=yes (then anyone there), minus those she set wait=no, whose people have not spoken
  in that group since. A line @-ing two people waits for both. Nothing accumulates: a person drops off when they
  speak, and a line drops off after a day ("a reminder, not a debt").
- **A plain reply does not count** (Xiaoman: "answering someone is not a debt"). Only an @ and wait=yes count, the
  same strict basis as her own waits.
- **Shown at home, and in the group.** A heartbeat or a plan due at home lists every group's, at most 5, because
  home is where she thinks things over. A group turn lists that group's. Each entry is about 60 characters, and
  the block is absent when nobody is waited for.
