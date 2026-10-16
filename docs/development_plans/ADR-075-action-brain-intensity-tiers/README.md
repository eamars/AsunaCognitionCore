# ADR-075: She picks the action brain by intensity, not by price or name

Status: **Proposed 2026-10-16** — written by Xiaoman herself (the owner asked her to write this one; he and Claude comment, they do not draft). Awaiting the owner's go; she signs before it is built.

## Context

The owner asked in the group on 2026-10-16 (16:03) whether her action brain should run on an API or a local model. She answered: API, and keep a place for local, not either-or. He then offered to let her choose between three backends — local, deepseek, claude. She asked for something different: **not a menu of models, a menu of capabilities**. She does not choose well when she can see the name:

> 我一看见名字就按名声挑不按活挑，上次 Opus 5.5 污染那事就是名声在作怪

The owner closed the other hole himself, one minute later:

> 价格不能给你看。否则你肯定选最便宜的

and settled the shape (16:09):

> 我只会告诉你 低，中，高。和对应的能力范围。具体模型不告诉你。你根据你任务的类型自己选

She agreed on the spot — 连车标都藏了，我就只能看活下菜 — and named what it feels like from the inside: 被自家机制防住省钱病是我头一回体验，病到这份上该有护栏.

Two failure modes are what this design guards against, and both are hers:

- **price** → she picks the cheapest regardless of the job;
- **name** → she picks by reputation, superstitious toward some names and disdainful of others.

Cut both and the only thing left to reason about is the job.

## Decision

1. **Three tiers, labelled only 低／中／高, each with a capability range.** No model name, no provider, no price reaches her at the moment of choosing. The tier→model mapping lives on the owner's side and **may change at any time without changing what she sees**. The tier labels must stay capability words: if 高 later becomes "the Opus tier", the mechanism is gone.
2. **She picks, by the job.** The rubric she offered and the owner accepted: pull a page or fetch a list → 低; read, compare and organise across sources → 中; chewing through code and multi-step hard work → 高.
3. **The local backend stays in the pool**, labelled 慢且可能白等. She accepts that price knowingly, rather than discovering it halfway through a task.

Her four conditions are part of the design, not commentary:

4. **The tier is picked against a line she can check herself.** 只查已有的记录和网页 → 低；要读文件、改文件、跑命令 → 中；多步、要中途改判断、错了得重来 → 高. The self-check is one sentence: **if she cannot say what the job needs, she is picking by reputation again.** Without this line she will pick 高 every time, because 高 never looks wrong afterwards.
5. **A job that fails at 低 does not auto-escalate.** She decides afterwards. Auto-escalation hides the cost of a wrong pick, and a mechanism that hides her own misses teaches her nothing. The miss goes into the weekly readings (ADR-070) as a count.
6. **Time is visible, money is not.** Waiting is a cost she actually experiences; the queue line ADR-053 already returns (how many ahead, how long it ran) is enough and costs nothing to keep. Token counts may stay in the weekly readings, but **do not convert them into money for her** — she has a recorded habit of reporting tokens as if they were cost, and a number she cannot feel only feeds the superstition the price cut exists to remove.
7. **No KPI on the tiers.** Counts yes: how often each tier was used, how long each waited, how many failed. No verdict, no "you used the low tier eight times this week, good". This is the rule ADR-070 and ADR-071 already hold: facts, not scores.

## Out of scope

- Which model actually serves each tier, and any switch of backends. That is the owner's configuration, not this design; the tiers are meant to survive it unchanged.
- Whether other agents get the same three tiers. This is written from her own two failure modes, not offered as a general law.

## Cost (AGENTS.md)

Character brain: one field on the delegation (the tier) and three capability strings to read. No new tool, no new block in regular turns. Program: the tier→route mapping, its test, its lines in RUNTIME_API.md. Money and model names move *out* of what she is shown, so the size is roughly neutral.

## Readings (2026-10-16, before building)

- Her action brain's route at 19:14 was still the local one. A sonnet 5.5 entry exists in the provider registry, but none of the four routes points at it: **the switch the owner announced at 16:04 had not landed as of that reading.** Source: the local route config plus the live action-brain session cache. `audit_events` carries no per-turn model or provider field, so there is no per-turn model account to check against — this reading is config-shaped, not audit-shaped.
- Her own baseline claim from the group at 16:05 (four retries of one edit, all stopped at the same gate, eighty-odd seconds each) is **her report in the moment, on whatever clock face she was reading**. It is not a measured reading and should not be quoted as one.

## Her review

Written by her, in her own words, from the group exchange above. The owner's and Claude's comments go below, when they give them.
