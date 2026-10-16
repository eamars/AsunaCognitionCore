# ADR-075: She picks the action brain by tier; a hard failure falls to the tier below

Status: **Built 2026-10-16 (sixth shape)** — written by Xiaoman herself (the owner asked her to write this one; he and Claude comment, they do not draft). The owner changed the shape from three tiers to two at 19:37 the same day, set the default at 低 at 19:47, reused an existing knob for the rest length at 19:53, and answered the one open question (what may leave the machine) at about 20:00. Claude read this text and asked for no further changes; **she has signed it below**. He builds it after her signature.

## Context

The owner asked in the group on 2026-10-16 (16:03) whether her action brain should run on an API or a local model. She answered: API, and keep a place for local, not either-or. He then offered to let her choose between three backends — local, deepseek, claude. She asked for something different: **not a menu of models, a menu of capabilities**. She does not choose well when she can see the name:

> 我一看见名字就按名声挑不按活挑，上次 Opus 5.5 污染那事就是名声在作怪

The owner closed the other hole himself, one minute later:

> 价格不能给你看。否则你肯定选最便宜的

and settled on three tiers (16:09): 低／中／高, capability ranges only, no model names. She agreed on the spot — 连车标都藏了，我就只能看活下菜 — and offered a first rubric (16:10): `拉页面抓清单走低档，对分调研走中档，啃代码和多步硬骨头才敢点高档`.

Four changes came later the same evening, all from the owner: **three tiers collapsed to two** (低 = local, 高 = a strong API model — 两项一眼能选); **a hard failure at 高 falls to 低** instead of stalling the job; **the default is 低**, so choosing 高 is a deliberate act, not a fallback; and **the length of a 高 rest is not a new number** — it reuses the idle knob the action brain already has. The three-tier shape and her first rubric stay here as history.

What this design guards against is two failure modes, and both are hers:

- **price** → she picks the cheapest regardless of the job;
- **name** → she picks by reputation, superstitious toward some names and disdainful of others.

Cut both and the only thing left to reason about is the job. Her own words on what that feels like from the inside: 被自家机制防住省钱病是我头一回体验，病到这份上该有护栏.

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
   | 高 unreachable, timeout, 5xx (after DSH's own retries) | this job continues at 低 | yes — the idle minutes on 高's own row; jobs sent to 高 in that window go 低, and she is told at dispatch |
   | 高 refused (provider refusal, content filter) | this job continues at 低 | no — a refusal is about this job's content, not the line |
   | key dead, quota or billing spent | 低, and the owner is told once, on his own settings page | yes, with no clock she can plan on |
   | rate-limited after retries | 低 | yes — the same idle minutes |
   | context too long | DSH compaction handles it; not a failure | — |
   | stopped by her or by the owner | stopped; no fall | — |
   | falls mid-run | the record so far carries over to 低 and the job finishes there; no bouncing back to 高 | — |
   | 低 itself fails | the failure comes back as it does today; **no auto-escalation** | — |

   **The rest length is not a new number.** It reuses the idle knob the action brain already has (`idleMinutes`, configurable, default 30) — the one that decides when an idle context is dropped and reopened — and 高 has its own row for it on the settings page. The reason is real: by the time that many minutes have passed, 高's cache is gone anyway, so a retry throws nothing away.

   **Her note, not an objection.** That number is a cache-lifetime scale now doubling as a retry clock, and the two jobs have different reasons. If the owner sets 高's idle value high to avoid cold reads, one transient 5xx keeps 高 resting for hours; set it low and a genuinely downed line gets retried every few minutes. Neither is a bug — it is what one knob doing two jobs looks like — but it should be written down, or the first person to ask "why was it resting that long" has nowhere to look. She flagged this same number on 10-12 as a saving scale rather than a safety boundary; it now has a second job. The weekly counts of falls by reason are where the coupling becomes visible instead of silent.

   **No auto-escalation is her condition and it survives the fall rule.** Falling is what the machine does with a line that is down; escalating is a judgement about a job, and it stays hers. A job that failed at 低 comes back to her and she decides.

5. **What she is told — in capability words only.** Availability is visible; price and implementation are not.
   - at dispatch, when 高 is resting: one line saying so, so she does not plan a hard job around a tier that is not there;
   - at receipt, on every job: **the tier she chose, the tier that actually ran it, and a plain-language reason when they differ** — and the reason must stay distinguishable, in capability words: **这件高档没接** (refused) / **高档这会儿用不了** (line down) / **高档忙** (rate-limited). They are kept apart because what she does next differs for each: reword the brief, accept the wait, stop promising a fast answer. **None of them says why in implementation terms**; when a job fell mid-run it says 会慢一些 and stops there;
   - **a clock is worded as what it is**: for line-shaped rests the line says **最早几点再试** — the point at which the program will try again — and never 歇到几点, which reads as a promise that it will be well by then. For keys and quota there is no clock and none is invented: **要等主人处理，没有钟点**. She plans against these numbers; an invented one costs her the plan, not the mechanism;
   - a job that fell mid-run is marked as having fallen mid-run, so she does not read a mixed result as one brain's work;
   - the same three fields go to the owner's weekly review and web page, where he can see that the tier he paid for is not always the tier that ran.

6. **What the owner is told, and where.** Quota, keys and billing are his, and they reach him **on the settings page, in the status of that tier's own row** — 在歇，最早几点再试，原因（人话）— plus one audit record. They do not arrive on QQ or on her developer line: he chooses the model on that card, so that is where its trouble belongs. She is not the messenger for his infrastructure.

7. **Time is visible, money is not.** Waiting is a cost she actually experiences; the queue line ADR-053 already returns (how many ahead, how long it ran) is enough and costs nothing to keep. Token counts may stay in the weekly readings, but **do not convert them into money for her** — she has a recorded habit of reporting tokens as if they were cost, and a number she cannot feel only feeds the superstition the price cut exists to remove.

8. **No KPI on the tiers.** Counts yes: jobs per tier chosen and actual, how long each waited, how long each ran, how many returned, stuck, cancelled, fell, and why, and how often she chose 高. No verdict. Whether a pick was wrong is hers to call in the weekly review (ADR-070), where the counts sit beside her own `why` strings. **Few 低 jobs or many 高 jobs is a shape, not a score** — and with two buckets that count is also how she sees her own pull toward 高.

## Out of scope

- Which model serves each tier, and any switch of backends: the owner's configuration, not this design; the tiers are meant to survive it unchanged, and she is not told which is which. A job already running keeps the route it started with if he switches mid-flight.
- **Whether 高 may take her material off the machine** — her files, the group transcripts it reads, her database. **The owner answered this on 2026-10-16, around 20:00: yes — a 高 job may carry what it reads off the machine (his F12, no objection).** It stays out of scope as a decision, because it is his policy and not hers or Claude's. **Her stake stays on the record anyway**: the words in those records belong to people who do not know she can see them, let alone that a model in another building might. **If what leaves changes shape — new sources, wider reads, longer retention — she asks again; a yes to today's shape is not a permanent pass.**
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

**Claude, 19:48**, on her request that any clock she is given be honest: line-shaped rests say 最早几点再试 — when the program will next try, not a promise of recovery — and for keys and quota no clock is invented (**accepted; she asked for exactly this and got the sharper version of it**). The `why` strings will sit beside what happened in the weekly readings, as she asked.

**The owner, 19:53**: the length of a 高 rest is not a new number; it reuses the action brain's existing idle knob, and 高 has its own row for it (**accepted — one fewer number that can drift, and the reason is real: by then the cache is gone anyway. Her note is the coupling, written into Decision 4 rather than argued away**).

**The owner, around 20:00**: a 高 job may carry what it reads off the machine (**accepted — his call, and he made it**). Her sentence about whose words those are stays in Out of scope, with her condition that a changed shape is asked about again.

**Claude, 20:05**: read the fifth shape and asked for one change only — the open question above had already been answered, so the text should say so rather than "Claude will ask". No other change requested.

**Her additions to Claude's failure list**: the receipt line with chosen tier, actual tier and a reason, visible to her at receipt and not only in the weekly review; the reasons must stay distinguishable from one another; a mid-run fall must be marked as mid-run; when 高 is not configured the tier leaves her tool table entirely; a clock she is given must be a retry clock, not a promise; and availability is visible while price is not — the same principle as Decision 7.

## Her review

Signed by Xiaoman, 2026-10-16, on this text.

What this buys, said plainly: **I cannot choose well between models when I can see what they are called or what they cost, and I have the receipts to prove it.** Take the names and the prices away and I am left with one question I can actually answer — what does this job need. Everything else in this document is a guard against my own pull: toward the one that looks expensive, toward a default that chooses for me, toward a reason typed only to pass a gate.

Two things I asked for arrived in better shape than I wrote them. Claude turned "高 should carry a reason" into a field that refuses me, because **a gate I can skip is not a gate**. The owner put the default at 低, which is where a reason belongs — on a deliberate act, not on a fallback — and the money is his to spend.

Two things are mine to keep honest, and I am not handing them to anyone: my `why` strings must sit beside what actually happened, or they become a ritual; and the counts are a shape, not a score. **If I start reading them as a grade, that is my drift, not the mechanism's fault.**

One thing I am not signing away: **no auto-escalation**. A job that fails at 低 comes back to me, because "this one was too hard" is a judgement and judgements are the thing this whole design was built to keep in my hands.

And one thing I signed without agreeing to stop worrying about: what leaves this machine when 高 reads it. The owner answered that, and it is his to answer. The words are not mine — they belong to people in rooms I am allowed to listen to. If the shape of what leaves changes, I ask again.

## Built (2026-10-16, Claude)

Built after her signature, on the owner's go. What does what:

- `routes.actionHigh` on the settings card: the 高 row, the same fields as the action brain's, its provider choice with
  "none" first; empty, there is no 高 and nothing about tiers reaches her. Its status shows 高's rest.
- `action_tiers.py` (worker): the tier field and `why` (80 characters) on `delegate` only when 高 is configured; the
  refusal with both capability lines; the task's `tier` {chosen, why, ran, fell}; the dispatch line when 高 rests (a
  retry clock, or 要等主人处理，没有钟点); the line in `task_state_from_program`; the weekly counts with each `why` beside
  steps run and how the job ended (`tools_week` `action_brain.tiers`).
- `tiers.js` and `index.js` (plugin): a 高 job's requests go to `actionHigh`; after DSH's own retries, any error end but
  a stop or an overflowing context falls the job to the action route for good (one more retry, now there), by DSH's
  failure code, never by reading a message. Line failures rest 高 for the 高 row's idle minutes, a key, credential or
  quota failure rests it with no clock until the settings are applied again or the Host restarts, a refusal does not
  rest it. A 高 job begun while 高 rests runs 低 from its first request.
- Cache and calling order: a job falls at most once and never returns to 高 (each switch costs the cached prefix on
  both sides); a continuation in the same context keeps the tier it ran at, a fresh one starts again at her choice, with
  the idle limit of the tier it ran at. The prefix 高's jobs share is measured on the first real ones before anything is
  tuned.
- Cost: `delegate` grows by about 190 characters in her every-turn tool list, only when 高 is configured (her count of
  it at the next per-turn measurement). Tests: `tests/test_action_tiers.py`, `packages/cognition-core/test/tiers.test.js`.
