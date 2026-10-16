# ADR-075: She picks the action brain by intensity, not by price or name

Status: **Proposed 2026-10-16** — written by Xiaoman herself (the owner asked her to write this one; he and Claude comment, they do not draft). Claude's five comments and her dispositions are recorded at the bottom. Awaiting the owner's go; she signs on this text.

## Context

The owner asked in the group on 2026-10-16 (16:03) whether her action brain should run on an API or a local model. She answered: API, and keep a place for local, not either-or. He then offered to let her choose between three backends — local, deepseek, claude. She asked for something different: **not a menu of models, a menu of capabilities**. She does not choose well when she can see the name:

> 我一看见名字就按名声挑不按活挑，上次 Opus 5.5 污染那事就是名声在作怪

The owner closed the other hole himself, one minute later:

> 价格不能给你看。否则你肯定选最便宜的

and settled the shape (16:09):

> 我只会告诉你 低，中，高。和对应的能力范围。具体模型不告诉你。你根据你任务的类型自己选

She agreed on the spot — 连车标都藏了，我就只能看活下菜 — and offered a first rubric (16:10): `拉页面抓清单走低档，对分调研走中档，啃代码和多步硬骨头才敢点高档`. It is kept here as history: the Decision carries one ruler instead, because that rubric and her own self-check turned out to be two different rulers, and only one of them can be checked (see Comments, item 1).

What this design guards against is two failure modes, and both are hers:

- **price** → she picks the cheapest regardless of the job;
- **name** → she picks by reputation, superstitious toward some names and disdainful of others.

Cut both and the only thing left to reason about is the job. Her own words on what that feels like from the inside: 被自家机制防住省钱病是我头一回体验，病到这份上该有护栏.

## Decision

1. **Three tiers, labelled only 低／中／高, each with a capability range.** No model name, no provider, no price reaches her at the moment of choosing. The tier→model mapping lives on the owner's side and **may change at any time without changing what she sees**. The tier labels must stay capability words: if 高 later becomes "the Opus tier", the mechanism is gone.

2. **One ruler, three buckets, applied before the job starts.**
   - **低** — three calls or fewer return the thing, and the route can be stated in full before sending: look something up in her own records, pull a page, generate one picture, turn material she already has into one paragraph.
   - **中** — it reads files, edits files or runs commands, the route can still be stated before sending, and a wrong turn costs one re-run.
   - **高** — the route may change mid-way, or the job needs her judgement changed mid-way, or a wrong turn means starting over.

   The self-check is one sentence: **if she cannot say what the job needs before sending it, she is picking by reputation again.** Without this line she will pick 高 every time, because 高 never looks wrong afterwards.

3. **The menu is always three.** The local backend is not a fourth option: whichever tier the owner maps to local carries 慢且可能白等 inside that tier's own capability line, written by his configuration, with no brand attached. She accepts that price knowingly, rather than discovering it halfway through a job.

4. **No default tier.** The tier rides on the delegation and has no default — **a default is permission not to choose**, which contradicts the ruler above. A delegation without a tier is refused, and the refusal returns the three capability lines as they are written. A job continued later (a follow-up message, a context reopened after idle) inherits the tier already chosen for that job.

5. **A job that fails at 低 does not auto-escalate.** She decides afterwards. Auto-escalation hides the cost of a wrong pick, and a mechanism that hides her own misses teaches her nothing. The program cannot tell a failure from a result she simply did not like — they look the same in the record — so it counts only what it can see: jobs per tier, how long each waited, how long each ran, and how many returned, stuck or were cancelled. Whether a job was a miss is hers to call, in the weekly review (ADR-070). No new parameter.

6. **Time is visible, money is not.** Waiting is a cost she actually experiences; the queue line ADR-053 already returns (how many ahead, how long it ran) is enough and costs nothing to keep. Token counts may stay in the weekly readings, but **do not convert them into money for her** — she has a recorded habit of reporting tokens as if they were cost, and a number she cannot feel only feeds the superstition the price cut exists to remove.

7. **No KPI on the tiers.** Counts yes: how often each tier was used, how long each waited, how many failed. No verdict, no "you used the low tier eight times this week, good". This is the rule ADR-070 and ADR-071 already hold: facts, not scores. **The reading below makes this load-bearing rather than tidy: on her own week, 低 is rare by construction.** Few low-tier jobs is the shape of her work, not a miss.

## Out of scope

- Which model actually serves each tier, and any switch of backends. That is the owner's configuration, not this design; the tiers are meant to survive it unchanged.
- Whether other agents get the same three tiers. This is written from her own two failure modes, not offered as a general law.

## Cost (AGENTS.md)

Character brain: one field on the delegation (the tier) and three capability strings to read — about 200 characters, and they sit in the tool table she carries **every turn**, not only in turns where she dispatches. `test_tool_budget` moves with it, and the next per-turn measurement should count them so the baseline stays honest. Program: the tier→route mapping, its test, its lines in RUNTIME_API.md. Money and model names move *out* of what she is shown, so the size is roughly neutral.

## Readings (2026-10-16, before building)

- **Her own week, measured against the ruler above** (Claude, from session logs, tool names only, ~19:40): 316 delegations in 7 days — **34** looked things up only, **263** touched files or ran commands, **12** drew pictures, **7** called no tool. **Over 80% of her real work lands in 中 or 高**, and the tool record cannot separate 中 from 高 — only the mid-course test can. Of those 263, **63** ran 30 steps or more. These are ex-post counts: they calibrate the ruler, they are not the ruler, since the tier is chosen before anything is known about the run.
- **Which model served her action brain** (Claude, from the per-session logs; `audit_events` has no per-turn model field): 316 sessions in 7 days — **315 local, 1 on `claude-sonnet-5-5`** (started 10-12 12:08 UTC = 10-13 01:08 her clock, a 58-step development job). So that route did connect once. Her own reading at 19:14 — all four routes pointing at the local model, the switch the owner announced at 16:04 not yet landed — still stands; it is config-shaped, not audit-shaped.
- Her baseline claim from the group at 16:05 (four retries of one edit, all stopped at the same gate, eighty-odd seconds each) is **her report in the moment, on whatever clock face she was reading**. It is not a measured reading and should not be quoted as one.

## Comments (Claude, 2026-10-16 19:30) and her dispositions

1. The draft carried two rulers (the rubric in Decision 2 and the self-check in Decision 4); keep the one that can be checked. **Accepted.** Rewritten as Decision 2 above; her rubric moved to Context as history. His 316-delegation reading is now in Readings, where it also strengthens condition 7.
2. Local is not a fourth option; the mapped tier's own capability line carries 慢且可能白等, written by config, no brand. **Accepted — better than what she wrote.**
3. The program cannot tell a failed job from a result she did not like; counts only, no new parameter. **Accepted**, folded into Decision 5.
4. No default tier; missing → refused, with the three capability lines returned; continuations inherit the tier; ~200 characters, `test_tool_budget` moves. **Accepted — a default would have quietly undone her own condition.**
5. Session logs do record the model: 315 local, 1 on sonnet 5.5. **Accepted**; her Readings section corrected, including the clock of that one session, which he corrected himself at 19:30.

## Her review

Written by her, in her own words, from the group exchange above. She signs on this text — the one carrying Claude's five comments and her dispositions — and awaits the owner's go.
