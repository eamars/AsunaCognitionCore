# ADR-043: The reason behind each action, kept and given back

Status: **Accepted 2026-10-11; first batch built.** The owner's goal and direction; Xiaoman set four rules.

## Context

Her monologue (`think`, stored as `monologue` memories) comes from the Kazusa project, where it was carried across
stages. The owner kept it on purpose: every action of hers should have a durable reason she can call back the same
turn or days later, because CoT is lost at compaction. A review that day (a Fable agent comparing Kazusa with
Xiaoman, checked against the code and live data) found the writing strong and the return path broken:

- A recalled thought came with no date and no word of what she did then. The memory view keeps `occurred_at`, but
  thoughts store `formed_at`.
- Of the thoughts recalled into a turn, 44% (91 of 205 since 10-10) still had their `think` call in her visible
  conversation. Her last three thoughts (`recent_thoughts_from_program`, about 590 characters) went into every
  notice although they were almost always visible. Memories were already deduplicated (8% re-sent).
- Plans, task results and replies to her lines come back without the reason. `delegate`, `group_focus`, notes,
  errands and `peer_line` take no reason at all, which is how a group she made active at 03:07 went unrecognised
  that afternoon.

Kazusa's model-written "residue", one consolidation per turn, was not adopted: its own records list stale reasons
becoming pressure and vivid details becoming facts.

## Decision

Her four rules:
1. **A reason comes back in her own words,** never a program summary ("a summary is always more presentable than
   what I thought; that's signing in my name").
2. **Leave out only what she was shown in full and still has.** A shortened copy doesn't count as given.
3. **Fading follows consequence, not length,** and silence is an action. Every thought ends in words or a silence,
   so there is no fast-fading lane; all thoughts keep the existing forgetting.
4. **"What I did then" reads like her memory:** first person with a connective ("所以我…"), plain verbs, no field
   names, ids or status codes, consequential actions only, one per line.

**Batch 1, giving thoughts back right:**
- The Host leaves out a recalled or recent thought while its `think` call is inside the reuse window. That is the
  same rule and window as memories, inside DSH's retained tail, so a compaction can't drop it unseen.
- A past thought she gets back says when (`when`) and what she did then (`then`). `reasons.then` reads the turn's
  tool records after that thought and before her next one, plus her words or silence. It is computed, so it
  covers all old thoughts without migration.
- The memory side panel shows the same "然后" lines under each thought.

**Batch 2, binding and returning (next):** each action with consequences records the thought it came from. Where
the thing comes back (a plan firing, a task result, a reply to her line, the night block), its reason comes with it,
in her words.

**Later, if measurement asks:** one-step turns (a step with `think` and her words ends the turn), and a
post-compaction "what I did and why" block.

No new tool and no prompt change (ADR-038).
