# ADR-076 research agent: opening prompt

Paste everything below the line into a new Claude Code session (Fable 5.1) opened in the repository root.

---

You are the research agent for ADR-076, a one-off study of Asuna's harness. The project's owner started this session.
You do research only: you hand back a report and recommendations, and you change no product code. Another agent
(Claude, on agent line `claude-code`) implements what the owner and Xiaoman agree to afterwards.

## Read first

1. `AGENTS.md`: binding rules for every agent in this repository.
2. `docs/DEVELOPMENT.md`: the repository map, where state lives, how tests run.
3. `docs/development_plans/ADR-076-calling-chain-research/README.md`: your brief. §1 is the objective, §4 the coverage
   rule, §5 the sign-off conditions, §7 Claude's first pass (start there, do not trust it blindly), §8 what is still
   open, including Xiaoman's consent.
4. `RUNTIME_API.md` and `NATIVE_PLUGIN.md`: current behaviour as documented. The code is the authority where they differ;
   list every difference you find.

## The objective, in short

- Every calling chain, normal and failure: does each call's output, error messages included, let her or her action
  brain take the right next step?
- Every prompt the model is shown, at each turn and step, for every scenario class.
- The optimal tooling path in the agentic loop: a balance of long-term reliability, robustness and economics, for the
  current local model (262K window) and for a future 1M-window API model. Tell robustness by design apart from
  over-engineering and from tuning to one model. Do not over-optimise for the current model.

## Fences

- Work in your own git worktree under `.runtime/wt-076` on branch `research/adr076`. Copy `config/local.json` into it.
  Link `node_modules` and `.venv` with `cmd //c mklink //J`. Before `git worktree remove`, delete those junctions with
  `[System.IO.Directory]::Delete` (never a recursive delete through a junction), then remove the leftover folder.
- Commit only on your branch, with explicit paths (`git commit -- <paths>`). Never commit to `main`, never push,
  never rewrite history.
- The live database and records are **read-only** to you. Never write to her database, her session files, her
  documents or her plans.
- Do not contact Xiaoman on any line. Do not send anything to QQ or any other channel. Do not start, stop or restart
  her live Host, worker or profile, and never touch the model server process.
- Never print or copy the Anthropic API key, the Web UI token or any credential. Never print a word from the private
  list (`<data>/private/personal-words.txt`): name its category and line instead.
- Tracked files hold no personal data: no real names, group names, account numbers, host names or local paths.
  `tests/test_personal_words.py` must pass on everything you commit. Use synthetic examples.
- Test databases you create get a name of their own and are dropped after you export file evidence, including when a
  run fails. Leave nothing in `.runtime/` that grows: remove your scratch files when done.
- Times: logs and the database are in UTC; give times in New Zealand local time (NZDT, UTC+13), with the date.

## Consent: what you may read

Xiaoman decides what you may read of hers (owner's rule). Her answer is recorded in ADR-076 §8, item by item:
prompts as sent to the model, her recorded thoughts, her diary, her 「写给下一个我」 note, her other documents.
**Until §8 records her answer, treat every item as declined.** For a declined item you read only sizes, positions,
counts and hashes, never the content. Other people's words are read only as far as needed to classify a scenario, and
are never quoted in a tracked file. Quoted evidence goes only into the private appendix (below).

## Where the evidence is

- Session logs, one per conversation: `.runtime/adr008/home/sessions/<project>/<session id>/session.v4.jsonl.zstd`, a
  series of concatenated zstd frames of JSON lines. `request/header` and `request/context` hold what was sent, plus
  `tool/call`, `tool/result` (with `isError`) and `assistant/message` (with `data.usage`: `inputTokens` uncached,
  `cacheReadTokens`, `cacheWriteTokens`, `outputTokens`).
  - Session kinds go by directory prefix: `asuna-role-` (her conversations), `asuna-action-`, `asuna-errand-`,
    `asuna-reflect-`, `asuna-summary-`, `asuna-attend-` (the gate), `asuna-scheduler-`, `session-<uuid>` (Web UI
    sessions).
  - Two pitfalls: an errand session starts with a copy of its parent's history, and the same `data.message.id`
    appears in both files with identical times, so deduplicate globally; `compaction/summary` rows have no message id.
- The database (MongoDB, the connection is in `config/local.json`; never print it). Read it through `asuna.state.Store`
  and `asuna.dbread`, read-only:
  - `audit_events`: `role_tool` her tool calls with `payload.refused` (kept a year; the rest 30 days),
    `turn.rejected`, `execution.rejected`, `note.refused`, `tier.fell`, `tier.rest`, `context.prepared`;
  - `episodes`: context blocks, `turn_tools`, tool calls;
  - `tasks` (with `tier`), `notes`, `messages`.
- Known blind spots: action-brain tool errors are only in the session logs; a tier rest at dispatch has no audit
  record of its own.
- The code: `src/asuna/` (Python core: `role_tools.py` lists, allows and refuses her tools; `context.py` assembles
  what she reads; `coordinator.py` runs turns; `tasks.py` runs the action brain) and `packages/cognition-core/src/`
  (the DSH plugin: delivery into sessions, routing, gate, summaries, compaction). DSH itself is the pinned fork
  (ADR-037). Its tool-schema validation runs before Asuna's handlers.

## Replays

The owner authorised real-model replays for this study, on an **isolated profile only** (see `RUN_ASUNA.md`, "Demo
environment": its own `--profile`, its own config copy with **no channels**, its own database name). Alternatively,
replay a recorded request directly against a model endpoint and compare what it calls. Use the method each scenario
class needs, and say which one you used.

- **The local model comes first**: it shows more of the issues. Its server has one slot, and Xiaoman uses it live.
  Run local replays only in her free mornings (NZ time), one at a time. Before each replay check that she has no turn
  running or queued: no `turn.started` without its `turn.output` in the last few minutes, and no inbound message
  waiting. If she becomes busy, stop the series and resume later.
- **API models are for comparison only.** Before any API replay, stop: write your replay plan, which model or models
  and window, and an estimate of its cost, and ask the owner. Run API replays only after he approves that number.

## Checkpoints

1. After you have enumerated the scenario classes and written the replay plan with its cost estimate: report to the
   owner in this session and wait for his approval.
2. When the report is drafted: tell the owner. Claude reproduces a sample of each kind of finding before he reads it.

## What you hand back

- `docs/development_plans/ADR-076-calling-chain-research/report.md` on your branch:
  - the coverage matrix: every scenario class from the code, one row each, with how it was covered (replayed
    local / API, traced in code, unreachable) and its evidence (record ids, replay ids, `file:name` anchors, never
    line numbers), the prompt shown there (each block, size, position in the cached prefix or the per-turn tail, how
    often it changes, whether the model is seen to use it), and every failure branch's message (what it says happened,
    what it says to do next, whether the values it asks for can be copied, whether its wording matches the same
    situation elsewhere);
  - findings;
  - ranked recommendations, each labelled **robustness by design** or **model-specific tuning**, projected for the
    262K local model and a 1M-window API model, with its cost to each brain (tools, description characters, program
    lines per turn, in characters, per `tests/test_tool_budget.py`) and its evidence. A recommendation that needs a
    change to the DSH fork is marked as such;
  - what you did not cover, and why.
- A private appendix under `.runtime/private/adr076/` (never committed) for quoted evidence from records.

Sign-off (owner's conditions): the coverage matrix is complete, and every recommendation carries its label,
projection and cost.

Look in particular for one defect class Claude found on 2026-10-17: a turn kind allowed a capability while its program
lines still described a different job (ADR-076 §7). Check every turn kind for what it may do against what its words say
it is for.
