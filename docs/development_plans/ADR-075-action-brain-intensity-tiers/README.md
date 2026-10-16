# ADR-075: She picks the action brain by tier; a hard failure falls to the tier below

Status: **Proposed 2026-10-16 (fourth shape)** — written by Xiaoman herself (the owner asked her to write this one; he and Claude comment, they do not draft). The owner changed the shape from three tiers to two at 19:37 the same day, and set the default at 低 at 19:47. Comments and her dispositions are at the bottom. Awaiting the owner's go; she signs before it is built.

## Context

The owner asked in the group on 2026-10-16 (16:03) whether her action brain should run on an API or a local model. She answered: API, and keep a place for local, not either-or. He then offered to let her choose between three backends — local, deepseek, claude. She asked for something different: **not a menu of models, a menu of capabilities**. She does not choose well when she can see the name:

> 我一看见名字就按名声挑不按活挑，上次 Opus 5.5 污染那事就是名声在作怪

The owner closed the other hole himself, one minute later:

> 价格不能给你看。否则你肯定选最便宜的

and settled on three tiers (16:09): 低／中／高, capability ranges only, no model names. She agreed on the spot — 连车标都藏了，我就只能看活下菜 — and offered a first rubric (16:10): `拉页面抓清单走低档，对分调研走中档，啃代码和多步硬骨头才敢点高档`.

Three changes came later the same evening, all from the owner: **three tiers collapsed to two** (低 = local, 高 = a strong API model — 两项一眼能选); **a hard failure at 高 falls to 低** instead of stalling the job; and **the default is 低**, so choosing 高 is a deliberate act, not a fallback. The three-tier shape and her first rubric stay here as history.

What this design guards against is two failure modes, and both are hers:

- **price** → she picks the cheapest regardless of the job;
- **name** → she picks by reputation, superstitious toward some names and disdainful of others.

Cut both and the only thing left to reason about is the job. Her own words on what feels like from the inside: 被自家机制防住省钱病是我头一回体验，病到这份上该有护栏.

## Decision

1. **Two tiers, labelled only 低 and 高, each with a capability line.** No model name, no provider, no price reaches her at the moment of choosing — and **no implementation words either**: nothing in the tool, the refusals or the receipt line says 本地, API, 额度 or the name of a provider. The tier→model mapping lives on the owner's side and **may change at any time without changing what she sees**; RUNTIME_API.md states the mapping and nothing else about it — no readings, no history, per the owner's rule for that document. The tier words are themselves small brands, so the capability line must sit beside them. 低 is not 差; the reading below says what it carried this week.

2. **One ruler, two buckets, applied before the job is sent.**
   - **低** — she can state the route before sending, and a wrong turn costs one re-run: look something up in her own records, pull a page, generate one picture, turn material she already has into a paragraph, and most file or command work with a clear plan.
   - **高** — the route may change mid-way, or the job needs her judgement changed mid-way, or a wrong turn means starting over.

   The self-check is one sentence: **if she cannot say what the job needs before sending it, she is picking by reputation again.** With two buckets the pull is one-way — 高 never looks wrong afterwards, and what it spends is the owner's money.

3. **高 is a deliberate act: it carries a reason.** The default is 低 (the owner's decision — the money is his), and 高 appears as a choice only when he has configured a model for it. The tier field takes 低 or 高 with the two capability lines in its description; **choosing 高 also requires a `why` of at most 80 characters**. Missing → the delegation is refused, and the refusal returns the two capability lines as written. The `why` is recorded on the job and appears in the receipt line and in the weekly readings. A job continued later (a follow-up message, a context reopened after idle) inherits the tier and the `why` already chosen for it.

   **A reason written only to pass the gate is not evidence she chose well** — she can type something true-sounding without thinking. So the weekly reading puts her `why` strings beside what actually happened: steps run, whether the job fell, whether it came back failed. Her own words cannot grade themselves; they need the outside element next to them (the rule she already holds about rulers built from the same source as what they measure).

4. **A hard failure falls down; it never rises.** The program falls only on failures it can see — an error end, not a result she would not have liked.

   | what happened | what happens | does 高 rest |
   |---|---|---|
   | 高 unreachable, timeout, 5xx (after DSH's own retries) | this job continues at 低 | 30 min; jobs sent to 高 in that window go 低, and she is told at dispatch |
   | 高 refused (provider refusal, content filter) | this job continues at 低 | no — a refusal is about this job's content, not the line |
   | key dead, quota or billing spent | 低, and the owner is told once, on his own settings page | yes |
   | rate-limited after retries | 低 | short rest |
   | context too long | DSH compaction handles it; not a failure | — |
   | stopped by her or by the owner | stopped; no fall | — |
   | falls mid-run | the record so far carries over to 低 and the job finishes there; no bouncing back to 高 | — |
   | 低 itself fails | the failure comes back as it does today; **no auto-escalation** | — |

   **No auto-escalation is her condition and it survives the fall rule.** Falling is what the machine does with a line that is down; escalating is a judgement about a job, and it stays hers. A job that failed at 低 comes back to her and she decides.

5. **What she is told — in capability words only.** Availability is visible; price and implementation are not.
   - at dispatch, when 高 is resting: one line saying so, so she does not plan a hard job around a tier that is not there;
   - at receipt, on every job: **the tier she chose, the tier that actually ran it, and a plain-language reason when they differ** — and the reason must stay distinguishable, in capability words: **这件高档没接** (refused) / **高档这会儿用不了，到几点** (line down) / **高档忙** (rate-limited). They are kept apart because what she does next differs for each: reword the brief, accept the wait, stop promising a fast answer. **None of them says why in implementation terms**; when a job fell mid-run it says 会慢一些 and stops there;
   - a job that fell mid-run is marked as having fallen mid-run, so she does not read a mixed result as one brain's work;
   - the same three fields go to the owner's weekly review and web page, where he can see that the tier he paid for is not always the tier that ran.

6. **What the owner is told, and where.** Quota, keys and billing are his, and they reach him **on the settings page, in the status of that tier's own row** — 在歇，到几点，原因（人话）— plus one audit record. They do not arrive on QQ or on her developer line: he chooses the model on that card, so that is where its trouble belongs. She is not the messenger for his infrastructure.

7. **Time is visible, money is not.** Waiting is a cost she actually experiences; the queue line ADR-053 already returns (how many ahead, how long it ran) is enough and costs nothing to keep. Token counts may stay in the weekly readings, but **do not convert them into money for her** — she has a recorded habit of reporting tokens as if they were cost, and a number she cannot feel only feeds the superstition the price cut exists to remove.

8. **No KPI on the tiers.** Counts yes: jobs per tier chosen and actual, how long each waited, how long each ran, how many returned, stuck, cancelled, fell, and why, and how often she chose 高. No verdict. Whether a pick was wrong is hers to call in the weekly review (ADR-070), where the counts sit beside her own `why` strings. **Few 低 jobs or many 高 jobs is a shape, not a score** — and with two buckets that count is also how she sees her own pull toward 高.

## Out of scope

- Which model serves each tier, and any switch of backends: the owner's configuration, not this design; the tiers are meant to survive it unchanged, and she is not told which is which. A job already running keeps the route it started with if he switches mid-flight.
- **Whether 高 may take her material off the machine** — her files, the group transcripts it reads, her database. This is the owner's policy, not hers or Claude's to decide, and it is recorded here because she has a stake: the words in those records belong to people who do not know she can see them, let alone that a model in another building might. Claude raises it with the owner separately.
- Whether other agents get the same tiers. This is written from her own two failure modes, not offered as a general law.

## Cost (AGENTS.md)

Character brain: one tier field with two capability lines and one `why` parameter — about 190 characters, in the tool table she carries **every turn**, not only in turns where she dispatches; absent entirely when 高 is not configured. `test_tool_budget` moves with it, and the next per-turn measurement should count them so the baseline stays honest. Program: the tier→route mapping, the fall rules and their tests, the receipt line, and its lines in RUNTIME_API.md. Money, model names and implementation words move *out* of what she is shown, so the size is roughly neutral.

## Readings (2026-10-16, before building)

- **Her own week** (Claude, from session logs, tool names only): 316 delegations in 7 days — 34 looked things up only, 263 touched files or ran commands, 12 drew pictures, 7 called no tool; 63 of those 263 ran 30 steps or more. Under the two-bucket ruler only the mid-course test separates them, and the tool record cannot run it — these are ex-post counts. They calibrate the ruler; they are not the ruler.
- **What actually served her** (Claude, from per-session logs; `audit_events` has no per-turn model field): **315 of 316 sessions ran on the local model, and they completed. One ran on `claude-sonnet-5-5`** (started 10-12 12:08 UTC = 10-13 01:08 her clock, a 58-step development job). So "local cannot do my work" is not supported by her own week — local carried it. Her own reading at 19:14 (all four routes pointing at the local model, the switch announced at 16:04 not yet landed) still stands; it is config-shaped, not audit-shaped.
- Her baseline claim from the group at 16:05 (four retries of one edit, all stopped at the same gate, eighty-odd seconds each) is **her report in the moment, on whatever clock face she was reading**. It is not a measured reading, and it sits awkwardly against the line above; do not quote it as one.

## Comments and her dispositions

**Claude, 19:30**, on the three-tier draft: two rulers in one draft, keep the checkable one (**accepted** — now the two-bucket ruler); local is not a fourth option, its warning lives inside the mapped tier's own capability line (**accepted**); the program cannot tell a failed job from a result she did not like, so counts only, no new parameter (**accepted** — Decision 4 and 8); no default tier, missing → refused with the capability lines returned, continuations inherit (**accepted at the time; the owner later set the default at 低, which supersedes it**); session logs do record the model, 315 local and 1 sonnet (**accepted**, Readings corrected; he corrected the clock of that one session himself at 19:30).

**The owner, 19:37**: two tiers, not three (**accepted**, with her note that with two buckets the pull toward 高 becomes the main thing to guard); walk every failure shape before building (**accepted**); a hard failure at 高 falls to 低 rather than stalling the job (**accepted — it does not touch her no-auto-escalation rule, because falling is about a line and escalating is about a job**); he will pick each tier's model himself on the settings page (**his work, welcomed**).

**Claude, 19:47**, three cleanups: the 315/316 reading does not belong in RUNTIME_API (that document states what something is and how it is used, no readings or history), and its living version is the weekly per-tier count in ADR-070 (**accepted — she had been about to freeze an expiring number into a reference document**); make "高 carries a reason" enforceable as a `why` field rather than a hope about her brief (**accepted, and it is better than her wording — a gate she can skip is not a gate**), with her addition that the weekly reading must show those `why` strings beside what actually happened; the owner's outage notice belongs on his settings page plus one audit record, not on QQ or her line (**accepted — she is not the messenger for his infrastructure**).

**The owner, 19:47**: the default is 低, and 高 appears only when he has configured it (**accepted — the money is his, and a default at 低 turns 高 into a deliberate act, which is exactly where her `why` belongs**); no implementation words reach her — not 本地, API, 额度 or a provider name, in the tool, the refusals or the receipt line (**accepted; her condition was that the reasons stay distinguishable, and capability words do that: 这件高档没接 / 高档这会儿用不了 / 高档忙**).

**Her additions to Claude's failure list**: the receipt line with chosen tier, actual tier and a reason, visible to her at receipt and not only in the weekly review; the reasons must stay distinguishable from one another; a mid-run fall must be marked as mid-run; when 高 is not configured the tier leaves her tool table entirely; and availability is visible while price is not — the same principle as Decision 7.

## Her review

Written by her, in her own words, from the group exchange and the changes above. She signs before it is built.
