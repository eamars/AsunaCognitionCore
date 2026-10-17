# ADR-076: A research study of her calling chains, paths and prompts

Status: **Proposed 2026-10-17** — the owner's request; Claude prepared the brief and the first pass after the owner
answered Claude's questions (2026-10-17, about 15:40–16:00 NZDT). A research agent the owner starts runs it as a
one-off case study early in the week of 2026-10-19. Its findings come back as a report and recommendations; Claude
implements what the owner and Xiaoman agree to afterwards.

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
tool calls); tasks with tiers; notes. Two known blind spots: action-brain tool errors are only in the session logs,
not the audit; a tier rest at dispatch has no audit record of its own.

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
  - One-shot sessions (summary, gate, errand, reflection) leave DSH's session store a day after their last write, at
    each Host start, and stay in `.runtime/adr008/archive/sessions/` for 14 days (`tools/asuna-launch.mjs`,
    `retireOneShotSessions`). Read both places.
  - Every scheduler-woken turn spent 18-61 s preparing its context until 2026-10-18 08:33. The cause was a missing
    `messages.episode_id` index: 0.58 s per lookup, once per past visit. Context-preparation times before that are
    not representative.

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
