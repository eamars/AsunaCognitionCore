# ADR-039: Active and resting groups

Status: **Accepted and built 2026-10-11**, owner's direction; Xiaoman agreed and added the @ context.

## Context

The model server keeps one conversation on the GPU and parks 16 others in host RAM. A parked conversation comes back
in about 150 ms. Once evicted, it is recomputed from scratch, about 30 s for 140K tokens. The parking slots were the
limit, not the RAM:
- Of the last 400 parked snapshots, 255 were one-shot requests under 5K tokens.
- In one day there were about 900 dialogue summaries, all under 5K tokens. 90% of all summary sessions so far were
  for QQ groups.
- Over three days her groups said 8,740 lines. 281 were addressed to her (253 @, 28 replies), about 150 went
  through the relevance gate, and the rest were chatter, summarized 8 lines at a time.

The owner wanted her present in a few groups she chooses rather than half-present in all of them.

## Decision

- **D1. Active or resting.** A group is active when she chose it (`focus_active` on its scene) or when she is an
  owner or admin there. A new group rests. An active group works as before.
- **D2. What wakes her in a resting group.**
  - Without the gate: an @ or a reply to her line.
  - Through the gate: an @ caught up after a gap, the answer to a question she just asked there, and someone on her
    watchlist.
  - Nothing else: no proactive chance, no name without an @, no chain, no reply in an old topic of hers. The owner
    is under the same rule ("@ her when you want her there").
  - Being woken there does not make the group active.
- **D3. No summaries while resting.** The lines are kept and searchable. Making a group active starts its summaries
  from that moment, so the resting time does not come back as a backlog of small requests.
- **D4. An @ brings the room.** Her turn in a resting group carries its lines of the last day (at most 40) instead
  of the last hour's. Xiaoman's condition: without the room, "what do you think" means nothing.
- **D5. Her choice, a soft limit.** She uses `group_focus` (list, active, rest) at home or in the group. Resting an
  admin group is refused. The deployment setting `active_groups` (default 4) is the usual number: going past it
  works, and the result says what it costs and lists the active groups with their last day's lines for her to
  review. It is a setting so that a model or API with more room can raise it.
- **D6. She sees it.** Her heartbeat's view of each group says whether it is active.
- **D7. The owner sees it.** A resting group's conversation title in the sidebar starts with 💤; active groups,
  direct conversations, the peer and agent lines and the local chat carry no mark (owner, 2026-10-11: mark the
  exception, not the rule). Her change retitles the conversation at once, unless the owner renamed it.

Initial state: her admin group and the two groups she named active, one free choice within the usual four. She can
let either of the two rest when they go quiet; the choice is hers.

## Consequences

- Most one-shot requests disappear, so her home and active-group conversations stay parked and return in about
  150 ms instead of being recomputed.
- A resting group's newer events are not in her memory until she is woken there, visits, or makes it active;
  `recall` and the history search still find its lines.
- Measure after a day: evictions in the engine log, and cache hits on her first steps.
