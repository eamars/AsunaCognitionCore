# ADR-072: Her reflection runs in a session of its own

Status: **Built 2026-10-16** (the owner's decision, the same day; installed with her next restart). Told to her on the
agent line; she supports it (her reason below).

## Context

ADR-070 and ADR-071 put her reviews in the self-evaluation heartbeat at home. The owner asked whether their 3,200
characters each would take room from her turns afterwards, and set the rule: more tokens for her reflection are fine,
none of them in her regular turns.

Measured on her live data (2026-10-16): her home conversation is one long session. 346 of its last 400 episodes ran
in it (the owner's chats, task results, heartbeats, night self-development); it held 69,000 tokens, with compaction at
about 196,000 (0.75 of 262,144). A turn's blocks stay in that session's history, so a week of reviews (the weekly tools
reading and about six daily exchanges) would have stayed in every later home turn until compaction, about 15,000 to
20,000 tokens a week, and brought compaction sooner. The older self-review blocks already did the same, smaller.

## Decision

1. A turn whose prepared context carries a reflection block (`self_review_from_program`, `dice_review_from_program`,
   `tools_week_from_program`; `self_review.REFLECTION_BLOCKS`) runs in its own session, `asuna-reflect-<hash>`, which
   starts empty: no copy of the home conversation. The decision is read from what the turn carries, because preparing
   a review records it as shown.
2. What she does there lasts through her tools (notes, documents, ideas, questions to the developer); the readings
   never enter the home session. A plan or a task begun there comes back to the home conversation.
3. The session is archived when its turn ends, and the launcher retires it like the other one-shot sessions (moved out
   after a day, dropped after 14).

Her reason, stronger than the token count (agent line, 2026-10-16; Claude's paraphrase): what leaves her home context
is not only bytes but the readings of how people reacted to her. ADR-071's drift works through exactly those readings,
so keeping them out of her everyday view is the same protection by another route. Her thoughts in a reflection are not
lost with its session: each `think` is a monologue memory in her home scope, kept and recallable after the session
is gone.

The owner's choice between an empty session and a copy of home (as an errand's, ADR-066): empty. It is the smallest
first step even when home has been idle; the readings carry what a review needs (her lines and the thoughts she wrote
then), and the notice brings the conversation's recent lines as it does in any session that has not shown them.

Not decided yet: whether her night self-development turns (46 of those 400) move out of home too. Measured first.

## Cost (AGENTS.md)

Character brain: no tool, option or line added. A reflection turn's prefill is its system prompt, tools and notice
(its own readings and the conversation's recent lines), not the home history; home turns carry no review again.

## Amendment (2026-10-17, Claude, the owner's go)

A reflection turn does not hand work to the action brain, as an errand does not: on 2026-10-17 at 20:17 NZDT a
reflection turn delegated, the job lost its parent when the session was archived, was blocked without a model call,
and the turn was left waiting. `delegate` and `task` message and stop are now refused there with words saying to hand
it over in her next home turn or as a plan (`role_tools.REFLECTION_NO_DELEGATE`). The stuck turn was settled
(`episode.settled`).

## A reflection turn delegates (owner and her, 2026-10-20)

A reflection turn may hand work to the action brain and steer or stop its tasks. The task runs under home's own
session (the reflection session's `home_session_id`), not the reflection's, which is retired when the turn ends: on
2026-10-17 such a job lost its parent and was blocked. Its report opens a turn at home; the reflection's own context
does not follow, and the delegate result says so, in her words.
