# ADR-076 report: her calling chains, paths and prompts

Status: **draft in progress**. Research agent session 1, started 2026-10-19 00:13 NZDT on Fable 5.1 (`claude-fable-5-1`;
the session ran on Opus 5.5 until the brief arrived). Branch `research/adr076`. Read-only on the live records; no
contact with Xiaoman; no replay has run yet. Every judgement about one of her turns points to that turn's record id;
quoted evidence lives only in the private appendix (`.runtime/private/adr076/`, never committed). Times are NZDT.

Sections 1–3 are checkpoint 1 (the owner approves §3 before any API replay runs). Sections 4–7 fill in as the study
proceeds; a row or item marked `[ ]` is not yet covered.

## 1. How the records were read

- **Session logs** `.runtime/adr008/home/sessions/<project>/<session>/session.v4.jsonl.zstd` and the one-shot
  archive under `.runtime/adr008/archive/sessions/`: 7,760 files written in the last 30 days (8,290 sessions in all,
  322 MB). Kinds by directory prefix: `asuna-role` 34, `asuna-action` 549, `asuna-attend` 336, `asuna-summary` 6,813,
  `asuna-reflect` 4, `asuna-errand` 2, `asuna-scheduler` 1, Web `session-*` 21. Rows used: `system/message`
  (the rendered system prompt), `user/message` with `source.kind: asuna` (the notice: context JSON, `source.carried`),
  `request/header` (route config), `request/context` (`contextWindow` 262144 on the local route), `tool/call`,
  `tool/result` (`isError`), `assistant/message` (`usage`), `compaction/*`, `llm/retry`, `asuna/stage`,
  `asuna/stage-result`. Deduplicated globally by `data.message.id` (an errand session starts with a copy of its
  parent's history).
- **The database**, through `asuna.dbread` (read-only): `audit_events` (`type`, `occurred_at` as ISO text,
  `stream_id` = the episode id for turn events), `episodes` (`episode_kind`, `manifest.session_class`,
  `system_ref.place`, `turn_tools`, `tool_calls`, `context`), `tasks` (`tier`, `feedback_state`), `notes`, `messages`.
- Scripts print summaries only (counts, codes, sizes); no record is dumped into the agent's context. They stay in the
  agent's scratch folder, not in the repository.

## 2. Scenario classes enumerated from the code

A scenario class is one cell of **turn kind × place/channel × step × state**, with each failure branch reachable
there as its own row (ADR-076 §4). The dimensions below are read from the code; the 30-day counts beside them are
from `episodes` joined on `turn.started` (4,857 distinct turns) and say which cells the records cover.

### 2.1 Turn kinds (`role_tools.turn_kind`, set as `episode_kind` where the turn is made)

| Kind | Made in | What its words say it is for | 30-day turns (class) |
| --- | --- | --- | --- |
| `external` | `chat.py` (a message, a line) | someone spoke to her | 3,415 (public 1,817; owner_private 1,598) |
| `task_feedback` | `tasks.py`, `handover.py`, `chat.py` | the action brain's result came back | 564 |
| `consult` | `coordinator.py` | the action brain asked her a question (`turn_consult.md`) | 66 |
| `self_development` | `chat.py`, `schedule.py` | her self-improvement turn | 179 (35 `FAILED_RUNTIME`) |
| `presence` | `rhythm` / heartbeat | a heartbeat at home | 167 |
| `settlement` | `context_budget.py` | the night settlement | 13 |
| `scheduled` | `schedule.py` | a plan of hers came due | 138 |
| `visit` | `places.py` | she went to see a group from home | 139 |
| `note` | `role_tools.py` (`note`) | a note from another conversation woke her | 167 |

### 2.2 Places and channel kinds

- Place (`visibility.PLACES`): `home` (the local chat; the owner's platform DM; a `home_groups` group reads as home
  with a group's tools), `peer` (the agent line, the DSH peer line), `group`, `dm`. Class: `owner_private` for home
  and peer, `public` for group and dm (`visibility.PLACE_CLASS`).
- Channel kind (`channel_kinds`, one package each): none (the local chat), `napcat-qq` (`REPLY_PARTS` text, sticker,
  picture, poke, react, recall; faces; images), `qq-bot` (`REPLY_PARTS` text, picture), `agent-line` (`ROUTE_KEYS`,
  `OWNER_JOINS`, home), `dsh-peer` (`PEER_LINE`). Only Xiaoman's live profile is studied; the QQ Bot deployment is
  not running.
- Observed 30-day requests by lane and place (session logs, deduplicated): role on the QQ channel 6,925 requests
  (cache hit 93.3%, median 3 steps a turn); role in the local chat 4,785 (87.5%, 3 steps); role on the agent line
  2,797 (92.1%); role on the DSH peer line 1,394 (83.2%); action brain 12,289 across home, peer, group and
  auto-admitted conversations (89.7–95.4%, median 9–19 steps a task); the gate 587 (34.5%: one step, cold each
  time, as ADR-076 §8 predicts); summaries 6,817 (0.9–2.8%); reflection 14; errands 7; Web sessions 318.

### 2.3 Steps within a turn

| Step | What the model receives | Where |
| --- | --- | --- |
| S0 gate (group lines not addressed to her) | `stage_attend.md` + her `core` + words only, one request | `attend` phase, `asuna-attend-*` session |
| S1 first request | system prompt (`common.md` + persona render + `turn.md`), the notice (context JSON, only what the session does not still show, folded lists, `THINK_FIRST` tail), the session's fixed tool list | `coordinator._deliver`, `context-delivery.composeContext`, `role_tools.session_specs` |
| S2 after a tool result | the result (or refusal text) appended; lines that arrived join at the step boundary; after a compaction, `restored_from_program` follow-up | DSH loop, `navigation.js`, `context-delivery.restoreContext` |
| S3 after a refused call | the refusal as a tool error, in her words (`WORDS[code] （CODE: detail）`, `NOT_NOW`, `CONSULT_ONLY`, `NOTE_ONLY`) | `role_tools.not_now`, handlers |
| S4 repair | a program note in the same turn: `REPLY_THINK_NOTE`, `UNSENT_NOTE`, `answers.turn_note(issue)`; at most 2 | `coordinator` (REPAIRS = 2) |
| S5 end of turn | nothing more: the output is checked and published, held as unsent, or the turn is silent; lines in view are absorbed | `coordinator`, `_publish`, `_absorb` |

### 2.4 States that change what a step shows or allows

Resting group (`focus.py`), waiting task (`WAITING_TASK`), open question (`questions.py`), tier resting (`tiers.js`),
night and quiet hours (`night_*` blocks, presence), muted here, unsent words pending (`unsent_from_program`), a watch
active, held notices, requests open at home, tools switched off (`switches`), tiered memory on or off, a channel's
capability change (`speak_from_program.leg`), caught-up lines, pictures attached to the turn (`turn_pictures`),
compaction committed since the last notice, the context ceiling reached (`context.trimmed`), one-shot session (errand,
reflection: no delegating).

### 2.5 Failure branches, by where they are raised

| Branch | What she or the action brain reads | 30-day count |
| --- | --- | --- |
| F1 DSH tool guard: a tool not in the conversation's list | `这个对话里没有 X 这个工具；有的是：…` (`index.js attachPreset`) | in session logs only (`[ ]` to count) |
| F2 DSH schema validation before the worker | DSH's own validation error | in session logs only (`[ ]`) |
| F3 listed but not this turn | `NOT_NOW[name]`, `CONSULT_ONLY`, `NOTE_ONLY`, `ERRAND_NOTE`, `NO_DELEGATE`, switched-off text | part of 1,406 refused `role_tool` rows |
| F4 handler refusal | `Refused` codes (`WORDS` table), the first-think gate `先用 think 写下这回合的心里话，再做别的。`, length refusals with a cut offer, old parameter names (`GONE`), the per-turn call cap (12), `TOOL_FAULT` | the first-think gate alone ≈ 190 rows across 20 tools |
| F5 end-of-turn check | `no_thought` 99, `unsent` 5, program words in speech 13, a `#n` label 4, a sticker or face she lacks 3, a think end-mark leak 1 (`turn.rejected`); after 2 repairs `INVALID_TURN_OUTPUT` → `FAILED_PROTOCOL`; `TURN_NOT_FINISHED` for transport failures | 130 `turn.rejected` |
| F6 worker exception in a turn | `FAILED_RUNTIME` (a traceback in the episode) | 57 (35 `self_development`, 18 `external`, 3 `task_feedback`, 1 `scheduled`) |
| F7 context pressure | `context.trimmed` (memories 144 cases alone, history + memories 148, shortened texts 126), `render.over_budget` 7, `system.render_drift` 3, `SessionCarried` (ADR-028), compaction (127 in one home session) | 457 trims |
| F8 gate | `ATTEND_FAILED` (passes quietly; `missed_looks`) | 27 of 614 looks (quiet 384, join 228) |
| F9 action brain | guard `CAPABILITY_DENIED`, `ASUNA_ACTION_STAGE_SUPPRESSED`, `tool.failed` codes (`INVALID_INTEGRATION_ARGV` 10, `STALE_TASK_FENCE` 8, `DEVELOPMENT_PATH_DENIED` 8, `INVALID_COMMAND` 7, `DEVELOPMENT_FLOOR_PROTECTED` 5, `CAPABILITY_DENIED` 3, `IMAGE_*` 6, `TOOL_TIMEOUT` 2, a raw `[Errno 17]` 2), `execution.rejected` 2, `BLOCKED` 7 (`TimeoutError` 4, `RuntimeError` 3), `UNDELIVERABLE` 1, tier fall-back 0 (6 高 tasks ran 高) | 573 tasks |
| F10 side sessions | appraisal `phase.rejected` 9 (8 `不是有效的 JSON`), `phase.failed` 35, summary `llm/retry` 149 `Connection error`, `embedding.failed` 4,595 | — |
| F11 publication | outbox and part failures (`CANCELLED_AFTER_FAILURE`, `CHANNEL_DOES_NOT_DECLARE_*`), `not_landed`, recall refused | `[ ]` |
| F12 notes | `NOTE_TOO_LONG` 75, `NOTE_HOP_LIMIT` 18, `NOTE_MODE_NOT_ALLOWED` 16, `NOTE_VISIT_NOT_NOW` 14, `NOTE_NOT_OWN_WORDS` 6, `NOTE_HOME_LIMIT` 6, `NOTE_DAY_LIMIT` 4, `NOTE_TARGET_UNKNOWN` 4 | 143 |

### 2.6 The action brain and the side sessions

- Action brain: `delegate` (tier 低/高 when `actionHigh` exists) → `tasks.py` → executor session (`executor.md` + her
  `core` sentences readable in the task's class) with the granted tools (`tool_args.normalize` first) → `ask_character`
  (a `consult` turn) / `report_progress` / her `task.message` injected → the report checked (`execution.rejected`) →
  hand-back in pages of 6,000 characters, `machine_words` rewrite outside home → `task_feedback` turn; the handover
  watchdog's short version; `fresh_context` continuations after `idleMinutes`.
- Side sessions, each its own class: the gate (`stage_attend.md`), the appraisal (`stage_appraise.md`, `DECIDE`
  767 phases), dialogue summaries (6,813 one-step sessions, median system prompt 2,866–2,987 characters), compaction
  (`compaction.js`, `condense.py`: `floor` 75, `mark` 1 of 99 results), the scheduler (1 session), errands (2),
  reflection (4 sessions, 13 `REFLECT` phases).

## 3. Replay plan and cost (checkpoint 1: needs the owner's approval before any API replay)

**Method.** Isolated, synthetic probes through the real design, the way `tools/refusal_probe.py` does it (its own
profile, its own throwaway database, no channels), one probe per scenario class that the records do not already
cover or whose failure branch needs a model's reaction (what the model does after reading the refusal). Each probe is
one turn of two to five steps. Recorded real turns are **not** replayed against any API model: the probes carry
synthetic words only, so no conversation's or person's words leave the machine (the list her consent asks for will
then be empty, and the report says so). Where a class can only be judged on a real turn, it is judged from the record
and, on the local model only, from a replay of that recorded request against the local endpoint.

**Local model (first, the reference).** Up to 40 probes, one at a time, in her free mornings (NZ), each preceded by
the idle check (no `turn.started` without its `turn.output` in the last minutes, no inbound line queued); the series
stops when she becomes busy; nothing at night and nothing on 2026-10-18 09:00–12:00 (past). Cost: her model slot for
about one to two minutes a probe (a cold prefill of about 130k tokens).

**API comparison: DeepSeek, not Claude.** ADR-080 and `docs/MODELS.md` record that Anthropic's safety system stops
every character-brain request (`reasoning_extraction`) before any output, so a Claude comparison would measure the
stop, not the harness. DeepSeek's API is OpenAI-compatible like the local route (`reasoning_content`), its models
have a **1M context** (the future-model projection the owner asked for), and its prices make the comparison nearly
free. Prices read on 2026-10-19 from DeepSeek's pricing page, per 1M tokens, off-peak / peak (peak is 01:00–04:00 and
06:00–10:00 UTC Monday–Friday = 14:00–17:00 and 19:00–23:00 NZDT; her free mornings are off-peak):

| Model | Cache hit | Cache miss | Output |
| --- | --- | --- | --- |
| `deepseek-flash` | $0.003 / $0.006 | $0.15 / $0.30 | $0.60 / $1.20 |
| `deepseek-v4-pro` | $0.022 / $0.044 | $0.66 / $1.32 | $1.98 / $3.96 |

Request sizes come from the 30-day session logs: a home turn's request averages about 19k uncached + 134k cached
tokens on the local route (4,785 requests), a QQ turn's about 8k + 109k (6,925 requests). Plan: 24 probes (8 scenario
classes × 3 variants) on `deepseek-flash`, the same 24 on `deepseek-v4-pro`, each turn 3 requests: one cold request
of about 130k tokens, two warm ones of about 130k hit + 2k miss, 3k output a turn.

| | Per turn | 24 turns | With a 2× margin for repairs and retries |
| --- | --- | --- | --- |
| `deepseek-flash` (off-peak) | ≈ $0.023 | ≈ $0.55 | **≈ $1.10** |
| `deepseek-v4-pro` (off-peak) | ≈ $0.10 | ≈ $2.40 | **≈ $4.80** |

**Asked of the owner:** approval of up to **US$6** on DeepSeek's API (both models), or **US$1.50** for `deepseek-flash`
alone, and a DeepSeek key placed where `tools/refusal_probe.py` reads one (`--key-env`). No API replay runs before
that approval is in writing. The gate and the summary lanes are replayed on the API too (one request each; cost
negligible) to show the cross-request prefix caching the local server cannot do (ADR-076 §8).

## 4. Coverage matrix

`[ ]` One row per class of §2 (kind × place/channel × step × state, plus each failure branch), with: how it was
covered (replayed local / API, traced in code, unreachable), evidence (record ids, replay ids, `file:name` anchors),
the prompt shown there (block, size, cached prefix or per-turn tail, how often it changes, whether the model is seen
to use it), and every failure branch's message (what happened, what to do next, whether its values can be copied,
whether its wording agrees with the same situation elsewhere).

## 5. Findings

`[ ]` Each finding points to the turn records it rests on; a guess about her state of mind is marked as the agent's
guess.

Candidates noted so far (to verify against records before they count):

1. The "think first" rule is enforced in three places at once: the `THINK_FIRST` tail line, a per-tool refusal in the
   handlers (≈190 refusals across 20 tools in 30 days), and the end-of-turn `no_thought` rejection (99 of 130
   `turn.rejected`). Whether the three agree in wording and whether the model's next step after each is the right one
   is to be read from the records (`[ ]`).
2. `self_development` turns fail at runtime more than every other kind together (35 of 57 `FAILED_RUNTIME`): a
   program fault, not hers; its traceback class is to be read (`[ ]`).
3. The summary lane retried 149 times on `Connection error` and the embedding step failed 4,595 times in 30 days,
   silently to her: a cost without a prompt, to be sized (`[ ]`).
4. `write_document` op `correction` was refused every one of 29 times (`DOC_OP_NOT_ALLOWED`): either an option she
   is shown but can never use here, or one whose refusal does not teach the right op (`[ ]`).

## 6. Recommendations

`[ ]` Ranked; each labelled **robustness by design** or **model-specific tuning**, projected for the 262K local model
and a 1M-window API model, with its cost to each brain (tools, description characters, program lines per turn, in
characters, per `tests/test_tool_budget.py`: character 30 tools / 20,400 characters, 20,696 with tiered memory;
action 25 + DSH's own / 15,700; prompt files `common.md` 418, `turn.md` 639, `turn_consult.md` 187, `executor.md` 586,
`stage_attend.md` 422, `stage_appraise.md` 416) and its evidence. A recommendation needing a change to the DSH fork
is marked.

## 7. Not covered, and why

`[ ]`

## 8. Differences between the reference docs and the code

`[ ]` `RUNTIME_API.md` and `NATIVE_PLUGIN.md` against the code, listed as found.
