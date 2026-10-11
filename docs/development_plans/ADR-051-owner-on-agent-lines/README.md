# ADR-051: The owner speaks on an agent line

Status: **Approved by the owner 2026-10-12** (direction and Web change); details pending Xiaoman's review, then built.

## Context

Development work on her runs in two of her conversations at once: her home chat, where the owner asks, and an agent
line (ADR-033), where a coding agent builds. Measured over 24 hours to 2026-10-12:

- Tasks handed over for development-type work: 22 from the home chat (561 tool steps), 18 from agent lines (244).
  No two titles were near duplicates: the waste is not one task done twice but one subject held in two
  conversations, each with half of it, each checking what the other did (both re-verified the same commit; the
  ADR-047 rulings went through the developer inbox while her line self wrote the skill).
- Her home conversations ran at 150k–190k tokens, much of it development traffic. A larger home conversation is
  read again from scratch more often (ADR-049's measurements: about 25 s cold against 3 s warm).

Today the Web composer is read-only in every conversation but the home chat ("This conversation is read-only"), and
the agent-line README says what a line opens is "one agent's voice in her home, never the owner's".

The owner's ruling: let him write on an agent line, so a development request goes where the development happens.
No prompt rule narrowing what she does where: he wants her to do more development herself, not less.

## Decision

1. **The Web composer is open in an agent-line conversation.** What the owner types there joins that line's
   conversation as the owner's line, next to the agent's. Nothing new in the UI: DSH's own composer, which the
   input policy no longer blocks for the `agent` kind. Pictures attach as in the home chat.
2. **Who said what stays plain.** The owner's line carries his person (`chat.person_id`) and is labelled with her
   word for him, as in any conversation he is in; the agent's lines stay `agent:<route>` with the route's display
   name. Neither can pass for the other: the line's key still posts only as its agent, and the Web composer only as
   the owner.
3. **Same rights as before.** An agent line is already a trusted home conversation (ADR-050, owner's trust rule);
   the owner's line there carries the owner's grants as in his home chat (integration and development profile), so
   a task handed over from it is his request, and its result comes back to that line.
4. **The agent sees the whole conversation.** Its poll shows the owner's lines on its line as well as her answers,
   marked as the owner's, so it never answers a reply to words it never saw. It still cannot post as him.
5. **Her answers go to the line as now.** One answer reaches everyone on the line: the agent by its poll, the owner
   in the Web conversation.

No change to the home chat, the developer inbox, or what she may do where.

## For her

A line is no longer one agent's alone: the owner may join it. Her answer there is read by both. A line she closed
stays closed to the agent; whether a closed line also refuses the owner is her call in review.

## Not in this ADR

Which conversations get which rights, tools, or an action brain (the owner's open question of a master switch at
home) is discussed with her separately.
