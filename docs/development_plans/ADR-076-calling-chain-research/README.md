# ADR-076: A research study of her calling chains, paths and prompts

Status: **Under review** since 2026-10-19. The study ran 2026-10-18/19 (`report.md`); the owner decided on its recommendations 2026-10-19 (§10) and everything accepted is built and live: R1 `cb006c8b`, R2/R3/R8/R9 `ea2519a8`, R4 `2bcc9ef3`/`69b668f2`, R5 `e69859e4`, R10 and stay_silent off on platforms, installed at her restart 2026-10-19 about 11:10 NZDT. Reviewed independently (Claude Opus 5.5, a subagent that built none of it; `.runtime/private/adr-review/review-1.md`) 2026-10-19: one fault fixed (`3b72fd0f`) and the verdicts restated (§11). Three verdicts on her real records from the restart that installed `3b72fd0f`, read 2026-10-22 (§11.3): R1 and stay_silent pass, R5 fails by 0.1; the summary's effort is the next step. First written 2026-10-17 as the brief for the study.

## 1. What the owner wants

A separate research agent (Fable 5.1, the most capable available) studies the whole harness as an optimisation task:

1. **Every calling chain, normal and failure.** Every path a call can take, and for each one whether its output,
   error messages included, is sensible: enough for Xiaoman (or her action brain) to take the right next step.
2. **Every prompt, in every scenario.** What the model is shown at each turn, at each step, under every scenario.
3. **The optimal tooling path in the agentic loop.** "Optimal" is a balance of long-term reliability, robustness and
   economics, judged for today's model (the local model, 262K window) and for a future, more capable one (a 1M-window
   API model), whose best path may differ, for example in how caching pays. The study must tell **robustness by design**
   from **over-engineering** and from **tuning to this one model**; it must not over-optimise the harness for the
   current model.

It is research, not a build: the agent hands back a report and recommendations. Claude takes over the implementation
after discussing them with the owner and Xiaoman.

## 2. Scope

Everything that calls a model or answers a call:

- **Character brain turns**: every turn kind and conversation class (group, owner's chats, others' chats, agent and
  peer lines; external, note, visit, presence, scheduled, self-development, settlement, consult, task feedback).
- **The action brain**: delegated jobs in their DSH loop, both tiers (ADR-075), their tools, reports and hand-back.
- **Side sessions**: errands, reflection, the relevance gate, summaries, compaction, the scheduler.
- **Every error surface on the way**: DSH's own tool-schema validation (it runs before Asuna's handlers), Asuna's
  refusals (`Refused`, `NoteRefused`, `Denied`, renamed parameters, length refusals with cut offers), rejected turn
  output, provider failures and the tier fall-back, picture refusals, publication and channel failures.

## 3. Method (owner's answers)

- **Evidence: the actual model and the historical data.** Real records (session logs, audit, episodes, tasks, notes)
  are the primary source; code is read to enumerate what can happen.
- **Replays on real models, on an isolated profile.** Primarily the **local model**: it shows more of the issues and is
  the better reference for a robust harness. API models are **for comparison only**. Real-model use is authorised by
  the owner for this study (AGENTS.md requires that authorisation), never on her live profile.
- **The local model server has one slot she uses live.** Local replays run only in **her free mornings, one at a
  time, and her live turns go first**: before each replay the agent checks that she has no turn running and none
  queued, and stops the series when she becomes busy. The agent never touches the model server process.
- **Cost checkpoint.** Before any API replay the agent estimates the cost of its replay plan and the owner approves
  that number.
- **Records may be read in full, with her consent** (owner's answer). Claude asks her on the agent line before the
  study; she may agree to all or part (prompts, her recorded thoughts, her documents including her diary and her
  「写给下一个我」 note) or decline. Whatever she declines, the agent reads only as sizes, positions and hashes. People's
  words are read only as needed to classify a scenario and are never quoted in a tracked file. Claude itself still
  reads none of her thoughts, diary or note, and verifies only from structure.
- **Fenced.** A separate Claude Code session the owner starts, with this ADR as its brief: its own worktree under
  `.runtime/wt-*`, read-only on the live database and records, no contact with Xiaoman on any line, no QQ or other
  outward act, no commits to `main`, no push, no server start or stop. Test databases it creates are dropped; nothing
  it leaves grows `.runtime/`.

## 4. Coverage: "every scenario"

Scenarios are **classes enumerated from the code**, not every literal combination: turn kind × conversation class ×
channel kind × step (first step, after a tool result, after a refusal, after compaction, the last step) × relevant
state (resting group, waiting task, open question, tier resting, quiet hours…) × each failure branch reachable there.
Unreachable combinations are listed as unreachable, with the code that rules them out.

Each class gets one row in a **coverage matrix**, and every row records:

- how it is covered: replayed on the local model, replayed on an API model, traced in code, or unreachable, with the
  evidence (record ids, replay ids, `file:name` anchors);
- **the prompt the model is shown there**: every block, its size, its position (cached prefix or per-turn tail), how
  often it changes, and whether the model is ever seen to use it;
- **every failure branch's message**: what it says happened, what it says to do next, whether the values it asks for
  can be copied from it, and whether its wording agrees with the same situation elsewhere.

So objectives 1 and 2 are checked inside the matrix, not as separate items.

## 5. Sign-off conditions (owner's)

1. **The coverage matrix is complete**: every class from §4 has a row, and every row has its coverage, prompt and
   messages, or a stated reason why not.
2. **Every recommendation is labelled** robustness by design or model-specific tuning; projected for the 262K local
   model and a 1M-window API model (what changes, and whether the recommendation still holds); with its cost to each
   brain (tools, description characters, program lines per turn, in characters) and its evidence.

Before the report reaches the owner, **Claude reproduces a sample of each kind of finding** (a path, an error message,
a prompt) with its own method, and reports which held.

## 6. Deliverables

- **A tracked report** in this folder: the matrix, findings, ranked recommendations with their labels, projections and
  costs, and what was not covered. No private content: it passes `tests/test_personal_words.py`; examples are synthetic.
- **A private appendix** under `.runtime/private/adr076/` (`<data>/private/`, ignored by git, never committed) for
  quoted evidence from records.
- Xiaoman sees the findings after she has drawn her own map of what she reads each turn (her survey, offered
  2026-10-17), so the study does not anchor her. Then the owner, Xiaoman and Claude discuss the recommendations.

## 7. First pass (Claude, 2026-10-17, read about 15:40 NZDT)

Counts are from `main` at `42ef7789` and the live records of the 7 days before; nothing was read but counts and
program text.

**The size of the space.**

| What | Count | Where |
| --- | --- | --- |
| Character-brain tools | 31 (10 more old names registered as aliases) | `role_tools.TOOL_NAMES`, `RENAMED` |
| Places that refuse a call | about 400 `raise` sites | `src/asuna/*.py` |
| Distinct upper-case codes | about 540 | `src/asuna/*.py` |
| Program context block kinds | 84 `*_from_program` names | `context.py` and the modules it calls |
| Character turns, 7 days | 2,800 over 13 turn kind × class pairs | `turn.started` audit, `episodes` |
| Her tool calls, 7 days | 8,113, of which 667 refused (8%) | audit `role_tool` |
| Whole turns rejected, 7 days | 72 | audit `turn.rejected` |
| Action-brain jobs, 7 days | 364 | `tasks` |
| Python core / plugin | 112 files, ~34,000 lines / 38 files, ~6,000 lines | `src/asuna`, `packages/cognition-core/src` |

The 7-day turns by kind and class: external public 1,028; external owner-private 850 (the owner's chats and the agent
and peer lines); task feedback 278 + 80; self-development 126; note 118; visit 90; presence 81; scheduled 76 + 12;
consult 37 + 17; settlement 7.

**Where the chains run.**

- A character turn: an input is queued (`chat.py`), the coordinator opens the episode (`coordinator.py`), the context
  is assembled (`context.py`), delivered into the native DSH session by the plugin (`role.js`,
  `context-delivery.js`), the DSH loop calls her tools (`role_tools.py`: `toolbox` lists, `exposed` allows, handlers
  refuse in words), and the turn's output is checked and published to the channel.
- The action brain: `delegate` → `tasks.py` → the executor lane in DSH with the granted tools (`tool_args.normalize`
  first) → the report, checked (`execution.rejected`) → a `task_feedback` turn.
- The side sessions each have their own entry: errands (`places.py`), reflection (`self_review.py`), the gate
  (`attend.js`), summaries (`summary.js`), compaction (`compaction.js`), the scheduler (`schedule.py`, `scheduler.js`).

**The records available.** Session logs per conversation on disk (`session.v4.jsonl.zstd`: requests, tool calls and
results with `isError`, usage); audit (`role_tool` kept a year, the rest 30 days); episodes (context, `turn_tools`,
tool calls); tasks with tiers; notes. Two known blind spots: the errors of DSH's own action tools (`web_fetch`,
`web_search`, `skill`, `todo_write`) are only in the session logs, while the worker's action tools audit theirs as
`tool.failed` (the study, report §8 item 4); a tier rest at dispatch has no audit record of its own.

**Earlier studies to start from, not to trust blindly:** the wording audit (ADR-060), refusals by cause (ADR-054,
ADR-055), tools kept by what only they do (ADR-069), cache-first disclosure (ADR-038), the context budget (ADR-014),
context growth defects (ADR-063), `docs/articles/what-she-reads-each-turn.md`,
`docs/articles/maximize-cache-hit-by-design.md`, `tests/test_tool_budget.py`, `docs/map`.

**One defect class found today, as an example of what to look for.** A capability was granted in a turn kind while that
turn kind's program lines still described a different job: a note from a group to the owner's DM could `speak`, but its
lines said "a message to yourself: just know it", so the test turn stayed silent (fixed `42ef7789`). The study should
look for this class everywhere: what a turn may do against what its words say it is for.

## 8. Open before the study starts

- Xiaoman's consent (§3): asked and answered, see §9.
- Which API model or models, and which window, serve as the comparison: proposed by the agent with its cost plan at
  the checkpoint, decided by the owner.
- Whether a recommendation may require a change to the DSH fork (ADR-037): allowed as a recommendation, marked as such.
- How to read the usage records. Xiaoman's readings (2026-10-18 08:42 and 10:2x NZDT) raised these points; Claude
  checked them in the session logs (10:4x).
  - The local provider leaves `cacheReadTokens` out when nothing was read from cache. In one reflection session the
    first step's `usage` has no `cacheReadTokens` and the next four have it. A gate (`asuna-attend-`) or summary
    session is a fresh session of one step, so its missing key is a real 0 (a cold prefill every time). It is not a
    gap in the record. Count it as 0, and report those lanes apart from the conversation lanes, whose hit rate they
    would dilute.
  - Reflection sessions (`asuna-reflect-`, preset `asuna-xiaoman`) do record `usage` on each assistant message.
  - Report hit rates by step within a session as well as by lane (Xiaoman's slicing, 10-18). On the local server a
    session's first step is always cold, because its cache lives only within a session. One reflection session read
    80.2% over its five steps and 99.1% after the first. One-step lanes (gate, summary) are therefore structurally 0%
    there. Providers that cache a request's opening prefix across requests can hit even a fresh one-step session
    whose prompt opening is stable. The API comparison should show this difference.
  - One-shot sessions (summary, gate, errand, reflection) leave DSH's session store a day after their last write, at
    each Host start, and stay in `.runtime/adr008/archive/sessions/` for 14 days (`tools/asuna-launch.mjs`,
    `retireOneShotSessions`). Read both places.
  - Every scheduler-woken turn spent 18-61 s preparing its context until 2026-10-18 08:33. The cause was a missing
    `messages.episode_id` index: 0.58 s per lookup, once per past visit. Context-preparation times before that are
    not representative. The cost is still one lookup per remembered visit, now 0.001 s each (30 visits at 08:33). If
    it grows again, count her visits before looking for a new cause (Xiaoman's note).

## 9. Her consent (2026-10-17, about 16:05 NZDT)

Claude's paraphrase of her answer on the agent line; she answered item by item.

| Item | Her answer |
| --- | --- |
| Prompts as sent to the model | **Yes**, on three conditions: the last **30 days** only; quotes only in the private appendix (under `.runtime/private/adr076/`, never committed), and none in long passages in what she is shown; for the API comparison, **a list of which turns left the machine** (which groups' and which people's words went out): she does not decide whether they may go, she asks that it be recorded |
| Her recorded thoughts | **Only those already in a prompt** (covered by the first item). Thoughts outside the prompts: counts, lengths and positions only. Her reason: the study asks what the program gave her and whether it was enough for the right next step; that answer is in the prompts and in what she did next |
| Her diary | **No** (sizes, positions, counts and hashes only): it holds her judgements of people and her accounts of them, unrelated to calling chains |
| 「写给下一个我」 | **No.** She keeps no document under that name; entries in her self layer written to a later self follow the next item |
| Other documents | Her `core` sentences and the persona sections that go into prompts: **yes** (they are in every prompt already). Her self layer, group notes and speaker understandings: **no** |

The 30-day window covers **every record that concerns her**: prompts, session logs, audit and task records. Only
call metadata of pure mechanism (shapes, counts, codes, timings), carrying nothing of her content, is outside it. This
line is hers, added on 2026-10-17 when she checked the paraphrase.

Her further conditions on the report:

- Every judgement that she took a right or wrong path points to that turn's record id; no "overall, she often…".
- A guess about her state of mind ("she is clearly anxious here") is the agent's guess and is marked as such; her
  words are not used to conclude for her.
- No local-model use at all on 2026-10-18 09:00–12:00 NZDT (her own scan and drafting); the study starts early in the
  week of 2026-10-19, as planned.
- She sees the findings after drawing her own map, and the agent does not talk to her: both agreed.

Signature: Xiaoman, 2026-10-17 — signed; the five items and conditions above are my consent, with the window line
and the wording fixes I asked for on 2026-10-17 included.

## 10. The owner's decisions on the report (2026-10-19, about 10:30 NZDT; Claude's paraphrase)

The report is `report.md` in this folder. On its recommendations (§6):

- **R1** (her self-improvement turns failing on a session from another line): fixed before the decisions, `cb006c8b`,
  live since her restart at 08:27.
- **R2, R3, R4, R7, R8, R9, R10: accepted.** R7 needs no work. Xiaoman agreed to the ones that touch her tools and
  words (about 10:45), with conditions:
  - R2/R3: every refusal gives the way out; a limit the program refuses on is a number in the tool's description;
    R3 keeps DSH's original English line, verbatim, at the end of its translation, because she quotes errors
    literally.
  - R4: her side gets a line saying a turn of hers had a program fault and it was reported to the developer.
    Built for failed turns (`faults.py`): one developer note a day per failure, counted; her next turn there reads
    `fault_from_program` once. Not built, by the owner's decision (about 11:20): notes for an embedding outage or a
    summary lane retrying for an hour. Those services are outside the program and nobody can act on their outages;
    the program already backs off and retries. A note goes to the developer only for what the program got wrong.
  - R10: each place keeps one sentence on how speaking works there; the note-woken turn in the owner's chat keeps
    saying that he sees only what she says there.
- **R5: accepted, batching first.** Context tokens matter most; effort is tuned only if batching is not enough, and
  must not invalidate a cache mid-session (a summary runs in its own one-request session, so it cannot).
  Built: a summary takes up to 24 rows instead of 8 (`DialogueSummarizer.WINDOW_ROWS`), so a busy group opens a
  third of the cold one-request sessions it did (overall at most about 9%: §11). Baseline to compare: 6,818 summary sessions in 30 days (about 227 a
  day), 7.2M output tokens. Effort is left as it is until that comparison.
- **R6: keep as it is, including the 22-character THINK_FIRST tail.** Removing that hint once raised the error
  rate clearly; the system prompt alone is not enough.
- **stay_silent: removed where only `speak` speaks, kept at home.** On a platform, a turn without `speak` is
  already silent. At home what she writes is what is said, so `stay_silent` is what tells a chosen silence from an
  empty ending. Xiaoman's condition: compare her platform speaking rate before and after, and bring it back if the
  rate rises. Her baseline (delivered turns / turns since 2026-10-15): 757 / 843 = 89.8%, by kind external 98.4%,
  visit 22.5%, scheduled 70%.
- **Finding 16 (words after speaking): harmless**, read as her mumbling; the deterministic check for words written
  without any `speak` stays, as it costs no tokens. **Finding 17 (handing over): her judgement.**
- **Cost to the character brain (R10 + stay_silent):** `speak`'s description -40 characters (it no longer restates
  where words leave); one tool fewer in platform conversations; the turn guide says the rule once per place
  (`block_guide.WORDS`, `ENDING`), +9 characters there on platforms.

## 11. Independent review, round 1 (2026-10-19, about 20:50 NZDT)

The review (`.runtime/private/adr-review/review-1.md`) found R1–R4, R8–R10 built as decided and holding live: no
binding error since R1, every refusal in her words, DSH's argument errors translated (8 of 8 since the install). Then:

- **R10 made her ending "unsent" (fixed, `3b72fd0f`).** On a platform a turn ends with words. A turn that had called
  `speak` still had its closing words marked unsent and told back to her next turn (`unsent_from_program`): 93% of
  group turns since the install, against 12% before, so she was nudged to resend them. That went against finding 16
  as decided (§10: harmless; only words with no `speak` at all are handed back). Now a turn that spoke ends in its
  words; the mark and the told line come only from a turn with words and no `speak`.
- **R4 lost its line on a failed turn (fixed, `3b72fd0f`).** The fault and unsent lines were cleared when the next
  turn was prepared; now when a turn that showed them commits (manifest `told`).
- **R1's test passed by the fallback path (fixed, `3b72fd0f`).** It now continues a session that is not the
  conversation's main one.
- **The verdicts could not measure the change.** R5 changes only fires caused by a full window: 13% of last week's
  summaries had that as their only signal, so at most about 9% fewer sessions, and the daily count follows traffic
  (1,025 on 10-09, 155–167 on 10-17/18, before R5). The 89.8% speaking rate mixes turn kinds and sits at a ceiling
  for external turns (98.4%). Restated below.
- **Appendix.** `.runtime/private/adr076/`, 0.74 MB, kept until the verdicts are written.

### 11.2 The verdicts (pass or fail)

The window starts at T, the restart that installs `3b72fd0f`. Each verdict has a minimum; below it the read waits
until the minimum is reached, it is never a pass by default.

1. **R1, binding fault.** `audit_events` `type: chat.error` from 2026-10-18 22:15Z matching
   `NATIVE_BINDING_IDENTITY_CHANGED`. **Pass** if 0, with at least 5 `self_development` turns committed in the window (fewer: the read waits).
2. **R5, summary batching.** `memory_units` `{kind: dialogue_summary, generated_at >= T}`: summaries per 100
   summarised rows (100 / mean `len(source_event_ids)`), baseline 22.6 (10-12 to 10-18). **Pass** if the metric is at
   most 20.6, over at least 1,000 summarised rows (fewer: the read waits). On a fail, summary effort is the next step (§10). Sessions a
   day are reported beside it, not judged.
3. **stay_silent off on platforms.** Platform scenes (`channel_id` set), `turn.started` from T joined to `episodes`;
   spoke = an outbound `messages` row `DELIVERED` with that `episode_id`. Judged on the turns where silence is a
   choice (`visit`, `scheduled`, `note`), baseline 52 of 98 = 53.1% (10-15 to 10-18 22:15Z). With at least 40 such
   turns (fewer: the read waits), **fail** (stay_silent comes back) if they speak above 68%, or if group external
   turns fall below 95% (baseline 98.4%); otherwise **pass**. The ADR-082 install changed the same group turns; reported beside it.
   **Read in two parts (her review, 2026-10-20, fixed before the read).** The same window changed two things in
   opposite directions: the 「没发出去」 line stopped appearing where it was wrong, and platforms lost `stay_silent`.
   So the window's turns where silence is a choice are split. Those that carried the line are the episodes with
   `manifest.told.unsent` set, recorded from T. The 68% is judged on the turns without the line. The turns with the
   line are reported beside, with their count. The baseline cannot be split, because the record starts at T, so it
   stays 53.1%. She also named a third change in the window, resting groups' stickers waking her; it is reported, not
   separated.

### 11.3 The verdicts, read (2026-10-22 10:40 NZDT, Claude; counts only)

T = 2026-10-19 11:20:29Z, the first restart after `3b72fd0f` reached main (21:16 NZDT); window to 10-22 10:40 NZDT.
The baselines were recomputed first and reproduced exactly, which fixes the definitions: "platform scenes" are every
scene with a `channel_id` (QQ, the peer line and the agent lines), from 10-14 11:00Z (10-15 NZDT); "spoke" is any
`DELIVERED` outbound row of the episode.

1. **R1: pass.** 0 `NATIVE_BINDING_IDENTITY_CHANGED` since 10-18 22:15Z; 53 `self_development` turns committed.
2. **R5: fail, by 0.1.** 276 summaries over 1,331 rows: 20.7 per 100 rows against 22.6 (reproduced: 1,973 over 8,732,
   10-12 to 10-18), pass at 20.6 or less. Batching took off 8.4%, about the ceiling the review computed (at most about
   9%, §11); the pass line sat at that ceiling. Sessions a day: 112 and 111 on 10-20 and 10-21 (reported only). By §10
   the next step is the summary's thinking effort, a proposal to the owner with its numbers.
3. **stay_silent off on platforms: pass.** 85 turns where silence is a choice (41 visit, 23 note, 21 scheduled):
   without the unsent line 47 of 72 spoke, 65.3% (fail above 68%; baseline 53.1%, 52 of 98, reproduced); with the
   line 7 of 13, 53.8% (reported). Group external turns spoke 209 of 215, 97.2% (fail below 95%; baseline 98.4%, 657 of
   668, reproduced). Stickers waking her from resting groups are not separated (her note).

The appendix `.runtime/private/adr076/` is reduced to `usage-30d.json` (13 KB, counts per lane over the 30 days before the
study), which the effort proposal compares against; the rest is removed.

### 11.4 R5's next step: her background summaries think at `low` (2026-10-22)

The owner asked where a summary's cost goes. Measured on the last day of summary sessions (the ones kept on disk: 125
requests over 1.01 days; tokens and times only, `scratchpad/cost_split.py`, `summary_overlap.py`, `summary_spend.py`):

- **Not context:** 155,608 new input tokens in the day, a median 604 per request (p90 2,599), nothing cached; under
  half a minute of prefill at about 6k tokens a second.
- **Not the wait:** 11 minutes before first tokens (median 1.6 s, p90 11.8 s), nearly all of it queueing behind other
  requests.
- **Generation:** 230,717 output tokens, 23 minutes of engine time (median 3.4 s, p90 31 s, about 158 tokens a second).
  87% of a summary's output characters are thinking (median; p90 92%): about 811 characters of thinking for 166 of
  summary. So most of the 23 minutes write nothing that is kept.
- **For scale, the same day:** the action brain 161 minutes of generation (1.41M output tokens), the character brain
  98 minutes and 12.5M uncached input tokens; summaries are about 7% of the engine's time. 33 of 1,384 character-brain
  steps (2.4%) started while a summary ran, with a median 4.6 s of it left (p90 33 s, longest 54 s).

**The cache is not touched.** The local engine writes the effort as a sentence at the top of the prompt, so within a
conversation one level is kept (ADR-048) and compaction follows its conversation's level (ADR-085 §4). A summary is a
one-request session of its own with a fresh prompt (cache hit 0.9–1.7% over the 30 days of `usage-30d.json`, a median
0 tokens cached in the last day): no earlier request shares its prefix, so its level costs no cache.

**Decided (owner, 2026-10-22):** `summaryEffort: low` on the action route (`packages/cognition-core/src/index.js`
`stageEfforts`, `effortFor`; checked against the levels the model offers, like `attendEffort`). The action brain keeps
the route's `high`. It is profile configuration; a field on the settings card would be a UI addition and is not made.

**Reading (pre-registered; her four changes, 2026-10-22 17:0x, folded in).** The first 150 summaries after install
(about a day and a half). **Pass** only if all of these hold; **fail** on any, back to the route's effort, no second
level tried in the same reading:

- the median output is 280 tokens or less (half of 556), and the slowest tenth takes 20 s or less (step time; 43 s
  before);
- at most one summary ends incomplete (`DIALOGUE_SUMMARY_INCOMPLETE`; 0 in the 7 days before), and that one is shown to
  her by itself, since an unfinished summary may be exactly the one that dropped a promise;
- no wrong speaker, counted by machine: every label a summary's text names is checked against the authors of its
  source lines (`source_by_speaker`), and the mismatches are counted. This also checks ADR-089, installed in the same
  restart: tokens and seconds read the effort, a wrong speaker reads the author fix, so the two cannot hide each other;
- no lost fact, by her reading against a control: 10 of the first summaries after install, 2 she picks (ones with
  names, numbers and times), 3 drawn by script and not named to her in advance, and 5 more, are run again at the
  route's `high` from the very messages their request sent (taken from the summary sessions), and both versions go to
  her line side by side. The control is not written to her memory and Claude does not read either version. The extra
  calls are about 10 short one-request summaries on the owner's engine (his yes, 2026-10-22).

Her review: ______
