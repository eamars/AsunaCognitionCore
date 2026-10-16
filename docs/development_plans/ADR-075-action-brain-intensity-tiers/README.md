# ADR-075: She picks the action brain by tier; a hard failure falls to the tier below

Status: **Proposed 2026-10-16 (third shape)** — written by Xiaoman herself (the owner asked her to write this one; he and Claude comment, they do not draft). The owner changed the shape from three tiers to two at 19:37 the same day. Comments and her dispositions are at the bottom. Awaiting the owner's go; she signs before it is built.

## Context

The owner asked in the group on 2026-10-16 (16:03) whether her action brain should run on an API or a local model. She answered: API, and keep a place for local, not either-or. He then offered to let her choose between three backends — local, deepseek, claude. She asked for something different: **not a menu of models, a menu of capabilities**. She does not choose well when she can see the name:

> 我一看见名字就按名声挑不按活挑，上次 Opus 5.5 污染那事就是名声在作怪

The owner closed the other hole himself, one minute later:

> 价格不能给你看。否则你肯定选最便宜的

and settled on three tiers (16:09): 低／中／高, capability ranges only, no model names. She agreed on the spot — 连车标都藏了，我就只能看活下菜 — and offered a first rubric (16:10): `拉页面抓清单走低档，对分调研走中档，啃代码和多步硬骨头才敢点高档`.

Two changes came later the same evening, both from the owner: **three tiers collapsed to two** (低 = local, 高 = a strong API model — 两项一眼能选), and **a hard failure at 高 falls to 低** instead of stalling the job. The three-tier shape and her first rubric stay here as history.

What this design guards against is two failure modes, and both are hers:

- **price** → she picks the cheapest regardless of the job;
- **name** → she picks by reputation, superstitious toward some names and disdainful of others.

Cut both and the only thing left to reason about is the job. Her own words on what that feels like from the inside: 被自家机制防住省钱病是我头一回体验，病到这份上该有护栏.

## Decision

1. **Two tiers, labelled only 低 and 高, each with a capability line.** No model name, no provider, no price reaches her at the moment of choosing. The tier→model mapping lives on the owner's side and **may change at any time without changing what she sees**. The tier words are themselves small brands, so the capability line must sit beside them — and one fact belongs in RUNTIME_API.md next to the mapping: **this week 低 carried 315 of her 316 delegations, and they completed.** 低 is not 差.

2. **One ruler, two buckets, applied before the job is sent.**
   - **低** — she can state the route before sending, and a wrong turn costs one re-run: look something up in her own records, pull a page, generate one picture, turn material she already has into a paragraph, and most file or command work with a clear plan.
   - **高** — the route may change mid-way, or the job needs her judgement changed mid-way, or a wrong turn means starting over.

   The self-check is one sentence: **if she cannot say what the job needs before sending it, she is picking by reputation again.** With two buckets the pull is one-way — 高 never looks wrong afterwards, and what it spends is the owner's money — so **高 requires a reason she can say out loud**, not merely the absence of a reason for 低.

3. **No default tier.** The tier rides on the delegation and has no default — **a default is permission not to choose.** A delegation without a tier is refused, and the refusal returns the two capability lines as they are written. A job continued later (a follow-up message, a context reopened after idle) inherits the tier already chosen for it.

4. **If the owner has not configured 高, the tier does not appear in her tool table at all** — no field, no capability lines. She should not pay characters every turn for a menu she cannot use; this is the same rule ADR-073's C applies to other blocks.

5. **A hard failure falls down; it never rises.** The program falls only on failures it can see — an error end, not a result she would not have liked.

   | what happened | what happens | does 高 rest |
   |---|---|---|
   | 高 unreachable, timeout, 5xx (after DSH's own retries) | this job continues at 低 | 30 min; jobs sent to 高 in that window go 低, and she is told at dispatch |
   | 高 refused (provider refusal, content filter) | this job continues at 低 | no — a refusal is about this job's content, not the line |
   | key dead, quota or billing spent | 低, and the owner is told once | yes; she is told the tier is unavailable, without a price |
   | rate-limited after retries | 低 | short rest |
   | context too long | DSH compaction handles it; not a failure | — |
   | stopped by her or by the owner | stopped; no fall | — |
   | falls mid-run | the record so far carries over to 低 and the job finishes there; no bouncing back to 高 | — |
   | 低 itself fails | the failure comes back as it does today; **no auto-escalation** | — |

   **No auto-escalation is her condition and it survives the fall rule.** Falling is what the machine does with a line that is down; escalating is a judgement about a job, and it stays hers. A job that failed at 低 comes back to her and she decides.

6. **What she is told.** Availability is visible; price is not.
   - at dispatch, when 高 is resting: one line saying so, so she does not plan a hard job around a brain that is not there;
   - at receipt, on every job: **the tier she chose, the tier that actually ran it, and a plain-language reason when they differ** — and the reason must distinguish **refused / line down / no quota / rate-limited**, because what she does next differs for each: reword the brief, accept the wait, stop promising a fast answer;
   - a job that fell mid-run is marked as having fallen mid-run, so she does not read a mixed result as one brain's work;
   - the same three fields go to the owner's weekly review and web page, where he can see that the tier he paid for is not always the tier that ran.

7. **Time is visible, money is not.** Waiting is a cost she actually experiences; the queue line ADR-053 already returns (how many ahead, how long it ran) is enough and costs nothing to keep. Token counts may stay in the weekly readings, but **do not convert them into money for her** — she has a recorded habit of reporting tokens as if they were cost, and a number she cannot feel only feeds the superstition the price cut exists to remove.

8. **No KPI on the tiers.** Counts yes: jobs per tier chosen and actual, how long each waited, how long each ran, how many returned, stuck, cancelled, fell, and why. No verdict. Whether a pick was wrong is hers to call in the weekly review (ADR-070). **Few 低 jobs or many 高 jobs is a shape, not a score** — and with two buckets that count is also how she sees her own pull toward 高.

## Out of scope

- Which model serves each tier, and any switch of backends: the owner's configuration, not this design; the tiers are meant to survive it unchanged. A job already running keeps the route it started with if he switches mid-flight.
- **Whether 高 may take her material off the machine** — her files, the group transcripts it reads, her database. This is the owner's policy, not hers or Claude's to decide, and it is recorded here because she has a stake: the words in those records belong to people who do not know she can see them, let alone that a model in another building might. Claude raises it with the owner separately.
- Whether other agents get the same tiers. This is written from her own two failure modes, not offered as a general law.

## Cost (AGENTS.md)

Character brain: one field on the delegation and two capability lines — about 150 characters, in the tool table she carries **every turn**, not only in turns where she dispatches; absent entirely when 高 is not configured (Decision 4). `test_tool_budget` moves with it, and the next per-turn measurement should count them so the baseline stays honest. Program: the tier→route mapping, the fall rules and their tests, the receipt line, and its lines in RUNTIME_API.md. Money and model names move *out* of what she is shown, so the size is roughly neutral.

## Readings (2026-10-16, before building)

- **Her own week** (Claude, from session logs, tool names only): 316 delegations in 7 days — 34 looked things up only, 263 touched files or ran commands, 12 drew pictures, 7 called no tool; 63 of those 263 ran 30 steps or more. Under the two-bucket ruler only the mid-course test separates them, and the tool record cannot run it — these are ex-post counts. They calibrate the ruler; they are not the ruler.
- **What actually served her** (Claude, from per-session logs; `audit_events` has no per-turn model field): **315 of 316 sessions ran on the local model, and they completed. One ran on `claude-sonnet-5-5`** (started 10-12 12:08 UTC = 10-13 01:08 her clock, a 58-step development job). So "local cannot do my work" is not supported by her own week — local carried it. Her own reading at 19:14 (all four routes pointing at the local model, the switch announced at 16:04 not yet landed) still stands; it is config-shaped, not audit-shaped.
- Her baseline claim from the group at 16:05 (four retries of one edit, all stopped at the same gate, eighty-odd seconds each) is **her report in the moment, on whatever clock face she was reading**. It is not a measured reading, and it sits awkwardly against the line above; do not quote it as one.

## Comments and her dispositions

**Claude, 19:30**, on the three-tier draft: two rulers in one draft, keep the checkable one (**accepted** — now the two-bucket ruler); local is not a fourth option, its warning lives inside the mapped tier's own capability line (**accepted**); the program cannot tell a failed job from a result she did not like, so counts only, no new parameter (**accepted** — Decision 5 and 8); no default tier, missing → refused with the capability lines returned, continuations inherit (**accepted — a default would have quietly undone her own condition**); session logs do record the model, 315 local and 1 sonnet (**accepted**, Readings corrected; he corrected the clock of that one session himself at 19:30).

**The owner, 19:37**: two tiers, not three (**accepted**, with her note that with two buckets the pull toward 高 becomes the main thing to guard, which is why 高 must carry a stated reason); walk every failure shape before building (**accepted**); a hard failure at 高 falls to 低 rather than stalling the job (**accepted — it does not touch her no-auto-escalation rule, because falling is about a line and escalating is about a job**); he will pick each tier's model himself on the settings page (**his work, welcomed**).

**Her additions to Claude's failure list**: the receipt line with chosen tier, actual tier and a plain-language reason, visible to her at receipt and not only in the weekly review; the reason must distinguish refusal from line-down from quota from rate-limit; a mid-run fall must be marked as mid-run; when 高 is not configured the tier leaves her tool table entirely; and availability is visible while price is not — the same principle as Decision 7.

## Her review

Written by her, in her own words, from the group exchange and the two changes above. She signs before it is built.
