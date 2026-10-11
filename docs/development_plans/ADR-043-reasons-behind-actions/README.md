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

## Status (2026-10-11)

- **Batch 1 built and live:** commit 66ad7006, installed by her restart at 19:30 NZDT, together with the one-hour
  waiting list (ADR-041) and the plan-time fix (94d50bb0).
  - Checked: the panel's "然后" section renders; in her first three notices 4 visible thoughts were left out, and
    the one recalled thought delivered carried `then`.
  - Xiaoman's own check (19:45): the afternoon thought came back dated, and both "then" lines read like her memory;
    no thought she could still see came back as a recall.
- **Recall readability, from her recall test the same evening** (the owner asked her to recall the day's
  conversation on the agent line and judge what came back):
  - Of 12 records, 2 were noise from the day before, 2 were her own lines from four hours earlier that she still
    saw, and the day's main decision was missing. It had been indexed; it was held back because it was in the
    lines she had in front of her, and the result said nothing, so she concluded "not indexed until compaction".
  - Change (agreed with her): every recalled record carries `when`, the clock stamp her history lines use plus how
    long ago (a chunk dated by its line, a summary by its last line); a recall says how many related records it
    held back for being in view and that they are in the conversation in front of her, from the earliest one's
    time; with nothing else found it no longer says she remembers nothing. Her last three thoughts count as in
    view too, since they reach every turn; older ones that may be compacted away do not.
  - Kept: lines beyond the delivered history come back even when her session still shows them, because
    compaction may drop them. She agreed: better given twice than lost.
- **Baseline to compare against** (10-10 → 10-11, before batch 1):
  - Notices averaged 15,121 characters; `memories` about 2,000 of that, `recent_thoughts_from_program` about 590
    in every notice, `unchanged_from_program` about 530.
  - 91 of 205 recalled thoughts had their `think` call still visible; memories re-sent while visible were 8%.
  - Measure again after a day of traffic: notice size, thoughts left out, how often the last-3 block still goes
    out, and the share of thoughts among recalled memories.

## Batch 2: binding and returning (built 2026-10-11, its own restart)

Built as designed, with three simplifications found while building:

- **One place binds.** `reason_ref` is stored where every call is recorded (`RoleTools._record`: the episode's
  `tool_calls` and the `role_tool` audit), not copied onto plans, tasks, notes and revisions. A plan and a task
  already name the turn that made them, so their thought is read from that turn's call whose result names them
  (`reasons.for_call`); a delivered line's is the last of its turn's `monologue_refs` (`reasons.for_message`).
- **One table.** `reasons._action` decides what has consequences; the night block counts by it too, so it now also
  lists hand-offs, notes, visits and the rest, with the thought where she wrote no reason.
- **The reply return rides on the line itself.** In a native session the replying line enters her conversation as
  text, so her thought is a `> （你说那句时心里想的：…）` line under the `> 回复` line, not a context field.

The original design, for reference:

Each action records the thought it came from, and the reason comes back with the thing, in her words (rule 1).

- **Bind.** When a call with consequences is recorded (`RoleTools._record`, `role_tools.py`), store `reason_ref`:
  the id of her newest thought in the turn at that moment. Store the same on what the call produced and what comes
  back later:
  - delivered messages (they already carry `monologue_refs`; `reason_ref` names the one thought);
  - tasks, plans, notes, ideas, and self or document revisions.
  - "With consequences" is one shared table. `reasons._action` already names those tools; `night.COUNTED` is a
    smaller copy, so merge the two rather than keep both.
- **Return,** each at the tail of the turn it comes back in, as her original thought text, shortened only with
  the excerpt mark, never summarised (rule 1):
  - a plan firing (the `scheduled` turn's `scheduled_plan_from_program`): "你当时为什么定它";
  - a task result (`task_feedback` notice);
  - an inbound line that replies to or quotes her delivered line (`context.py` already resolves the parent row
    for the reply): what she thought when she wrote it;
  - the night block (ADR-042), for tools without a `why` argument (`group_focus`, notes, `delegate`, `peer_line`,
    `errand`).
- **No new tool and no `why` argument on tools:** the bound thought is the why.
- **Measure:** returned reasons per day by kind, and any "ownership unknown" incident per week (the goal is zero).
  Real-page test: the owner picks five actions from the audit (two plans, a task, a self edit, a group change) and
  asks her for the reason behind each, before and after.

## Later, only if measurement asks

- **One-step turns.** A step carrying `think` and her words ends the turn, saving the second request. The
  think-only first step is a median 12 s of a 24 s turn and 56% of its output tokens. Two DSH behaviours need
  checking first: whether several calls in one step run in order, and whether the step's text can be read while its
  tools run.
- **A post-compaction "what I did and why" block** (ADR-042 generalised), only if reasons are still lost inside a
  compacted span that batches 1 and 2 don't cover.
- **Not pursued:** Kazusa's residue; a `why` on every tool; forcing the first call with tool choice (DSH's LLM layer
  has no tool-choice option, so it would need a fork patch; reconsider only if a route that skips `think` often,
  such as DeepSeek V4.1 Flash at 6 of 12, goes live).

