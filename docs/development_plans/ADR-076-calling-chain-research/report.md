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

### 2.6 The window holds two designs

The 30-day window spans design changes that moved prompt text between positions, so the matrix reads records from
**2026-10-14 onward** as the current design and keeps the older ones only for counts:

| Change | First commit (NZDT) | What moved |
| --- | --- | --- |
| ADR-056: turn instruction and block guide into the system prompt | 2026-10-12 20:16 (`block_guide.py` 20:54) | the `# 这一回合` text left the notice tail (2,315 older notices carry it; 1,978 current ones end with `THINK_FIRST` alone) |
| ADR-060: wording audit, new tool names | 2026-10-13 01:57 | tool descriptions |
| ADR-064 phase 2: `reply` → `speak` on platform conversations | 2026-10-13 12:39; renamed 2026-10-14 | the speaking tool and the unsent-body rule |
| ADR-067: `context.prepared` manifest | 2026-10-15 | the audit, not the prompt |
| ADR-069: one `note` tool | 2026-10-16 | tool list |
| ADR-075: action-brain tiers | 2026-10-16 19:26 | `delegate` `tier`, `why` |
| ADR-079: per-session `speak` definitions, pointers | 2026-10-18 13:49 | tool definitions fixed per session (`session.tools`, 32 rows) |
| ADR-080: refusal probe, Claude off the character route | 2026-10-18 19:07 | — |

### 2.7 The action brain and the side sessions

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

One row per class of §2 (kind × place/channel × step × state, plus each failure branch), with: how it was covered
(replayed local / API, traced in code, unreachable), evidence (record ids, replay ids, `file:name` anchors), the
prompt shown there (block, size, cached prefix or per-turn tail, how often it changes, whether the model is seen to
use it), and every failure branch's message (what happened, what to do next, whether its values can be copied,
whether its wording agrees with the same situation elsewhere).

### 4.1 Character-brain turns: what the first request carries (records 2026-10-14 → 2026-10-19, local route)

Generated from the session logs by the agent's script; sizes are characters of the JSON sent. "Prefix" is the
system prompt (fixed per conversation: `common.md`, the persona render for the place, `turn.md` and the block guide,
`render.role_text`) plus the session's tool definitions (`role_tools.session_specs`); everything else is the per-turn
tail. A block "in N of M" notices is sent only when it changed since the session last showed it
(`context-delivery.composeContext`); `unchanged_from_program` names the ones held back.

<!-- matrix:begin -->
Block names end in `_from_program` where written `*`. Sizes are median characters of the block when sent. "Every notice" = sent in ≥ 90% of this cell's first notices (it changes every turn or is always sent); "often" = 30–90%; "rarely" = under 30% (the block is usually unchanged, so held back by the delivery, or absent in that state). Steps and cache hit are the lane's 30-day medians; the prefix is the system prompt median for the place (tool definitions, about 20,000 characters, come on top of it).

| Kind | Where (scene, class) | Turns | First notice chars / blocks | Every notice | Often | Rarely (count) | Prefix chars | Steps | Cache hit | Made in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `external` | QQ (napcat-qq) (group, public) | 985 | 2658 / 13 | `unchanged*` 603, `memories` 505, `group_continuity*` 295, `event` 150, `repeated*` 55, `ref_index` 42, `scene` 19, `speaker` 13, `session_class` 8, `delivered_history` 2 | `pace*` 157, `clock*` 101 | 36 | 5664 | 3 | 93.3% | `chat.py` (a message or line) |
| `external` | agent line (dm, owner_private) | 330 | 5191 / 12 | `memories` 2751, `unchanged*` 635, `event` 456, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 19, `session_class` 15, `delivered_history` 2 | `task_state*` 277, `elsewhere*` 202, `recent_phrasing*` 103 | 24 | 11679 | 3 | 92.1% | `chat.py` (a message or line) |
| `external` | local chat (dm, owner_private) | 157 | 4027 / 12 | `memories` 2272, `unchanged*` 643, `delivered_history` 181, `event` 111, `clock*` 104, `rhythm*` 98, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7 |  | 24 | 6959 | 3 | 87.5% | `chat.py` (a message or line) |
| `external` | DSH peer line (dm, owner_private) | 29 | 4511 / 12 | `memories` 1957, `unchanged*` 613, `event` 362, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 17, `session_class` 15, `speaker` 12, `delivered_history` 2 | `elsewhere*` 344, `task_state*` 267, `recent_phrasing*` 109 | 14 | 6670 | 2 | 83.2% | `chat.py` (a message or line) |
| `external` | QQ (napcat-qq) (dm, owner_private) | 13 | 2784 / 12 | `memories` 717, `unchanged*` 673, `event` 137, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 18, `session_class` 15, `speaker` 13, `delivered_history` 2 | `restart*` 1095, `affect*` 549, `elsewhere*` 412, `things*` 332, `task_state*` 242 | 18 | 5664 | 3 | 93.3% | `chat.py` (a message or line) |
| `external` | QQ (napcat-qq) (group, owner_private) | 2 | 8567 / 23 | `unchanged*` 542, `things*` 417, `notes*` 326, `group_continuity*` 272, `pace*` 155, `event` 136, `clock*` 104, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 13, `scene` 9, `memories` 2, `delivered_history` 2 | `lines*` 2680, `affect*` 1373, `errand_places*` 1348, `group_notes*` 1177, `restart*` 1136, `action_capabilities*` 965, `self_state*` 591, `elsewhere*` 567, `errands*` 560, `note_places*` 536 | 0 | 5664 | 3 | 93.3% | `chat.py` (a message or line) |
| `task_feedback` | agent line (dm, owner_private) | 93 | 13457 / 12 | `event` 10181, `memories` 1354, `unchanged*` 571, `task_state*` 337, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 19, `session_class` 15, `delivered_history` 2 | `elsewhere*` 187, `recent_phrasing*` 103 | 17 | 11679 | 3 | 92.1% | `tasks.py:feedback`, `handover.py` |
| `task_feedback` | QQ (napcat-qq) (group, public) | 85 | 8614 / 14 | `event` 5295, `unchanged*` 566, `group_continuity*` 534, `memories` 401, `task_state*` 311, `pace*` 158, `repeated*` 55, `ref_index` 42, `scene` 19, `speaker` 13, `session_class` 8, `delivered_history` 2 | `image_artifacts*` 604, `clock*` 101 | 17 | 5664 | 3 | 93.3% | `tasks.py:feedback`, `handover.py` |
| `task_feedback` | local chat (dm, owner_private) | 45 | 12618 / 13 | `event` 9613, `memories` 920, `unchanged*` 553, `task_state*` 325, `clock*` 104, `rhythm*` 98, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7, `delivered_history` 2 | `elsewhere*` 255 | 11 | 6959 | 3 | 87.5% | `tasks.py:feedback`, `handover.py` |
| `task_feedback` | DSH peer line (dm, owner_private) | 8 | 13353 / 13 | `event` 9585, `memories` 1856, `unchanged*` 558, `task_state*` 281, `clock*` 107, `repeated*` 55, `ref_index` 42, `scene` 17, `session_class` 15, `speaker` 12, `delivered_history` 2 | `questions*` 2124, `elsewhere*` 229 | 5 | 6670 | 2 | 83.2% | `tasks.py:feedback`, `handover.py` |
| `task_feedback` | QQ (napcat-qq) (dm, owner_private) | 2 | 7786 / 12 | `event` 5295, `image_artifacts*` 991, `unchanged*` 616, `task_state*` 294, `memories` 245, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 18, `session_class` 15, `speaker` 13, `delivered_history` 2 |  | 0 | 5664 | 3 | 93.3% | `tasks.py:feedback`, `handover.py` |
| `consult` | QQ (napcat-qq) (group, public) | 37 | 2598 / 10 | `event` 949, `unchanged*` 673, `memories` 284, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 13, `session_class` 8, `delivered_history` 2 | `clock*` 101 | 9 | 5664 | 3 | 93.3% | `coordinator.py` (consult) |
| `consult` | agent line (dm, owner_private) | 10 | 11145 / 13 | `memories` 4203, `event` 2780, `unchanged*` 497, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 19, `session_class` 15, `delivered_history` 2 | `action_capabilities*` 823, `task_state*` 273, `elsewhere*` 196, `recent_phrasing*` 98 | 7 | 11679 | 3 | 92.1% | `coordinator.py` (consult) |
| `consult` | local chat (dm, owner_private) | 4 | 10034 / 13 | `memories` 4018, `event` 3143, `unchanged*` 482, `delivered_history` 224, `clock*` 104, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7 | `action_capabilities*` 823, `task_state*` 279, `elsewhere*` 409, `recent_phrasing*` 74 | 2 | 6959 | 3 | 87.5% | `coordinator.py` (consult) |
| `self_development` | local chat (dm, owner_private) | 77 | 4671 / 13 | `unchanged*` 591, `event` 197, `clock*` 104, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7, `memories` 2, `delivered_history` 2 | `recent_experience*` 1905, `ideas*` 1998, `affect*` 483, `notes*` 475 | 20 | 6959 | 3 | 87.5% | `chat.py`, `schedule.py` |
| `presence` | local chat (dm, owner_private) | 42 | 16949 / 17 | `places*` 5654, `recent_experience*` 4473, `memories` 2028, `unchanged*` 534, `event` 455, `delivered_history` 178, `clock*` 104, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7 | `lines*` 1953, `night*` 1491, `peer_asides*` 602, `affect*` 446, `last_visits*` 230, `notes_sent*` 212, `notes*` 228 | 21 | 6959 | 3 | 87.5% | heartbeat (`rhythm`) |
| `settlement` | local chat (dm, owner_private) | 5 | 10560 / 16 | `memories` 3466, `sticker_candidates*` 1097, `unchanged*` 538, `settlement*` 188, `event` 182, `clock*` 104, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7, `delivered_history` 2 | `night_list*` 3890, `stickers_review*` 588, `affect*` 759, `elsewhere*` 168 | 7 | 6959 | 3 | 87.5% | `context_budget.py` |
| `scheduled` | agent line (dm, owner_private) | 22 | 14093 / 17 | `places*` 5491, `memories` 3559, `scheduled_plan*` 1236, `event` 790, `unchanged*` 564, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 19, `session_class` 15, `delivered_history` 2 | `peer_asides*` 552, `questions*` 692, `affect*` 496, `last_visits*` 318, `elsewhere*` 219, `plans*` 119, `rhythm*` 98 | 16 | 11679 | 3 | 92.1% | `schedule.py` |
| `scheduled` | local chat (dm, owner_private) | 14 | 15483 / 18 | `places*` 5020, `memories` 4631, `scheduled_plan*` 1128, `event` 785, `unchanged*` 536, `delivered_history` 170, `clock*` 104, `rhythm*` 98, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7 | `peer_asides*` 582, `elsewhere*` 468, `affect*` 501, `plans*` 341, `questions*` 273, `notes*` 223 | 13 | 6959 | 3 | 87.5% | `schedule.py` |
| `scheduled` | QQ (napcat-qq) (group, public) | 11 | 6062 / 17 | `memories` 2431, `scheduled_plan*` 516, `unchanged*` 473, `event` 288, `pace*` 155, `clock*` 101, `repeated*` 55, `ref_index` 42, `scene` 17, `speaker` 14, `session_class` 8, `delivered_history` 2 | `self_state*` 1538, `image_artifacts*` 1423, `members*` 707, `note_places*` 410, `stickers*` 397, `things*` 155, `pictures*` 169, `faces*` 123, `affect*` 130, `plans*` 81 | 20 | 5664 | 3 | 93.3% | `schedule.py` |
| `scheduled` | DSH peer line (dm, owner_private) | 6 | 15787 / 21 | `places*` 6359, `memories` 3693, `scheduled_plan*` 1065, `event` 748, `unchanged*` 466, `peer_asides*` 398, `elsewhere*` 349, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 17, `session_class` 15, `speaker` 12, `delivered_history` 2 | `affect*` 1374, `lines*` 1362, `restart*` 1039, `doc_refs*` 510, `stickers*` 727, `last_visits*` 323, `your_pictures*` 406, `notes_sent*` 462, `things*` 314, `task_state*` 302 | 5 | 6670 | 2 | 83.2% | `schedule.py` |
| `visit` | QQ (napcat-qq) (group, public) | 51 | 5125 / 16 | `memories` 1286, `visit*` 672, `event` 263, `clock*` 101, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 18, `session_class` 8, `delivered_history` 2 | `group_notes*` 1224, `members*` 1111, `image_artifacts*` 1429, `unchanged*` 461, `sticker_candidates*` 544, `pace*` 157, `things*` 216, `pictures*` 169, `faces*` 136 | 23 | 5664 | 3 | 93.3% | `places.py` |
| `note` | local chat (dm, owner_private) | 56 | 4083 / 15 | `note*` 589, `elsewhere*` 472, `unchanged*` 451, `event` 152, `clock*` 104, `repeated*` 55, `ref_index` 42, `session_class` 15, `speaker` 14, `scene` 7, `memories` 2, `delivered_history` 2 | `affect*` 506, `questions*` 531, `notes*` 228, `notes_sent*` 214, `note_places*` 192 | 16 | 6959 | 3 | 87.5% | `role_tools.py` (`note`) |
| `note` | agent line (dm, owner_private) | 17 | 7568 / 16 | `memories` 3050, `note*` 666, `unchanged*` 476, `event` 169, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 24, `speaker` 19, `session_class` 15, `delivered_history` 2 | `action_capabilities*` 965, `questions*` 873, `affect*` 652, `elsewhere*` 295, `rhythm*` 98, `recent_phrasing*` 98 | 14 | 11679 | 3 | 92.1% | `role_tools.py` (`note`) |
| `note` | DSH peer line (dm, owner_private) | 7 | 6080 / 16 | `note*` 469, `unchanged*` 457, `event` 168, `clock*` 104, `repeated*` 55, `ref_index` 42, `scene` 17, `session_class` 15, `speaker` 12, `memories` 2, `delivered_history` 2 | `lines*` 2757, `affect*` 824, `restart*` 1028, `elsewhere*` 344, `notes_sent*` 196, `things*` 253, `rhythm*` 98 | 11 | 6670 | 2 | 83.2% | `role_tools.py` (`note`) |
| `note` | QQ (napcat-qq) (dm, owner_private) | 5 | 11709 / 23 | `lines*` 2996, `self_state*` 1591, `affect*` 1327, `restart*` 1081, `questions*` 754, `elsewhere*` 734, `note*` 372, `unchanged*` 319, `event` 170, `clock*` 104, `rhythm*` 98, `repeated*` 55, `ref_index` 42, `scene` 18, `session_class` 15, `speaker` 13, `memories` 2, `delivered_history` 2 | `note_places*` 452, `action_capabilities*` 894, `things*` 399, `doc_refs*` 508, `stickers*` 304, `errands*` 237, `notes*` 201, `notes_sent*` 182 | 5 | 5664 | 3 | 93.3% | `role_tools.py` (`note`) |

**Block index** (all cells above): how many cells carry the block, in what share of their first notices it was sent (its change rate, since an unchanged block is held back), and its median size. Whether the model is seen to use a block is marked only where a tool consumes it (`[ ]` elsewhere: not measurable from the records without reading her words).

| Block | Cells | Sent in | Median chars | Consumed by |
| --- | --- | --- | --- | --- |
| `memories` | 26 | 100% | 1856 | `recall` |
| `event` | 26 | 100% | 455 | the turn itself |
| `scene` | 26 | 100% | 17 | `[ ]` |
| `speaker` | 26 | 100% | 14 | `[ ]` |
| `session_class` | 26 | 100% | 15 | `[ ]` |
| `delivered_history` | 26 | 100% | 2 | `speak` quote/line numbers |
| `repeated_from_program` | 26 | 100% | 55 | `[ ]` |
| `ref_index` | 26 | 100% | 42 | `feel` event_id |
| `unchanged_from_program` | 26 | 98% | 553 | `[ ]` |
| `clock_from_program` | 26 | 88% | 104 | `[ ]` |
| `group_continuity_from_program` | 4 | 96% | 295 | `[ ]` |
| `pace_from_program` | 6 | 87% | 157 | `[ ]` |
| `task_state_from_program` | 24 | 28% | 277 | `task` |
| `recent_phrasing_from_program` | 22 | 18% | 98 | `[ ]` |
| `questions_from_program` | 23 | 17% | 396 | `speak` wait, `await_answer` |
| `elsewhere_from_program` | 18 | 42% | 344 | `[ ]` |
| `rhythm_from_program` | 17 | 31% | 98 | `[ ]` |
| `affect_from_program` | 21 | 14% | 503 | `feel` |
| `sticker_candidates_from_program` | 6 | 19% | 544 | `sticker` keep/remember |
| `pictures_from_program` | 4 | 19% | 169 | `[ ]` |
| `notes_from_program` | 22 | 10% | 223 | `note` reply |
| `things_from_program` | 21 | 9% | 216 | `[ ]` |
| `plans_from_program` | 18 | 9% | 936 | `plan` update/cancel |
| `notes_sent_from_program` | 21 | 9% | 213 | `[ ]` |
| `attend_from_program` | 2 | 14% | 39 | `[ ]` |
| `sender_identity` | 1 | 14% | 47 | `[ ]` |
| `group_notes_from_program` | 5 | 12% | 1177 | `[ ]` |
| `members_from_program` | 4 | 12% | 707 | `find_member`, `@` labels |
| `faces_from_program` | 4 | 12% | 130 | `[ ]` |
| `image_artifacts_from_program` | 7 | 10% | 1423 | `attach_image`, `speak` picture part |
| `stickers_from_program` | 18 | 6% | 328 | `speak` sticker part |
| `relationship` | 10 | 6% | 4163 | `[ ]` |
| `unsent_from_program` | 4 | 10% | 36 | `[ ]` |
| `self_state_from_program` | 18 | 5% | 933 | `[ ]` |
| `action_capabilities_from_program` | 17 | 6% | 965 | `[ ]` |
| `note_places_from_program` | 16 | 6% | 452 | `note` |
| `restart_from_program` | 17 | 11% | 1081 | `restart` |
| `recent_experience_from_program` | 2 | 82% | 4473 | `[ ]` |
| `recent_thoughts_from_program` | 8 | 7% | 423 | `[ ]` |
| `undelivered_outbound_not_public` | 12 | 5% | 629 | `[ ]` |
| `note_from_program` | 5 | 65% | 469 | `[ ]` |
| `places_from_program` | 4 | 100% | 5654 | `visit` |
| `lines_from_program` | 13 | 10% | 2191 | `peer_line`, `plan` line |
| `notices_from_program` | 6 | 5% | 96 | `[ ]` |
| `peer_asides_from_program` | 4 | 68% | 582 | `[ ]` |
| `doc_refs_from_program` | 13 | 3% | 485 | `[ ]` |
| `scheduled_plan_from_program` | 4 | 100% | 1128 | `[ ]` |
| `speak_from_program` | 7 | 4% | 185 | `[ ]` |
| `visit_from_program` | 1 | 100% | 672 | `[ ]` |
| `your_pictures_from_program` | 11 | 6% | 406 | `[ ]` |
| `ideas_from_program` | 1 | 61% | 1998 | `ideas` review |
| `understanding_update_from_program` | 10 | 2% | 285 | `understand_person` |
| `errands_from_program` | 12 | 6% | 243 | `[ ]` |
| `errand_places_from_program` | 11 | 6% | 1189 | `errand` |
| `media_from_program` | 2 | 3% | 478 | `[ ]` |
| `last_visits_from_program` | 4 | 45% | 318 | `[ ]` |
| `your_place_from_program` | 3 | 3% | 22 | `[ ]` |
| `how_to_record_from_program` | 3 | 3% | 215 | `[ ]` |
| `condensed_from_program` | 3 | 3% | 79 | `[ ]` |
| `host_from_program` | 13 | 3% | 110 | `[ ]` |
| `credentials_from_program` | 7 | 3% | 162 | `credential` |
| `night_from_program` | 1 | 43% | 1491 | `[ ]` |
| `ongoing_development_task_id_from_program` | 1 | 18% | 39 | `[ ]` |
| `waiting_from_program` | 2 | 0% | 206 | `[ ]` |
| `settlement_from_program` | 1 | 100% | 188 | `promote_memory` |
| `schedule_control_from_program` | 1 | 0% | 719 | `[ ]` |
| `night_list_from_program` | 1 | 80% | 3890 | `[ ]` |
| `muted_here_from_program` | 1 | 8% | 42 | `[ ]` |
| `errand_from_program` | 3 | 0% | 227 | `[ ]` |
| `self_review_from_program` | 1 | 7% | 723 | `[ ]` |
| `stickers_review_from_program` | 1 | 60% | 588 | `[ ]` |
| `coverage_from_program` | 1 | 0% | 31 | `[ ]` |
| `task_continuation_from_program` | 2 | 0% | 127 | `[ ]` |
| `dice_review_from_program` | 1 | 5% | 3811 | `[ ]` |
| `relationship_shared_from_program` | 1 | 8% | 108 | `[ ]` |
| `memory_week_from_program` | 1 | 2% | 1430 | `[ ]` |
| `notes_review_from_program` | 1 | 20% | 11197 | `[ ]` |
| `trimmed_from_program` | 1 | 20% | 126 | `[ ]` |
<!-- matrix:end -->

### 4.2 Failure branches: the message each one shows

`[ ]`

### 4.3 Side sessions and the action brain

`[ ]`

## 5. Findings

`[ ]` Each finding points to the turn records it rests on; a guess about her state of mind is marked as the agent's
guess.

Verified against the records (counts from the audit and session logs; episode ids in the private appendix):

1. **"Think first" is enforced three times, and each layer works; the cost is one wasted call in 3.5% of turns.**
   The rule is said in `turn.md` step 1 and in the `THINK_FIRST` tail line, enforced by the handlers (a call before
   `think` is refused with `先用 think 写下这回合的心里话，再做别的。`) and by the end-of-turn check (`no_thought`).
   Since 2026-10-14: 69 of 1,968 turns met the handler refusal; in 66 the very next call was `think` and the refused
   call was then repeated; 3 turns needed it twice. 13 turns reached the end-of-turn `no_thought` rejection; all 13
   recovered on the first repair and committed. No turn failed on this rule. The refusal text names the fix and the
   fix works, so this is robustness by design, not a defect; its price is one extra model step per affected turn.
2. **`self_development` turns fail at runtime every day: `NATIVE_BINDING_IDENTITY_CHANGED`** (`asuna.state.Denied`),
   33 of 179 such turns since 2026-10-05 (2–7 a day from 2026-10-10 on), plus 1 `scheduled`. The same code appears
   34 times in `chat.error`. The turn fails before any `think` (0 tool calls in 25 of the 33). She never sees it: the
   failure has no prompt and no message to her. A program fault in the binding of the self-development turn to its
   native session, to be traced in `native_worker.py` (`[ ]` anchor).
3. **Silent failures around her:** the embedding step failed 4,595 times (`HTTPStatusError`) over 2026-10-06 →
   2026-10-09 and the summary lane retried 149 times on `Connection error`; `chat.error` holds 18 `KeyError:
   'scope_key'` (2026-10-04) and 26 `STALE_REVISION` conflicts; 10 requests were refused by the local server with
   `prompt + max tokens exceeds the context` (the `maxTokens` 32,768 reserve meets a full window) and 3 timed out in
   its queue (`LOCAL_ENDPOINT_QUEUE_TIMEOUT`). None of these reach her as a message; whether each should is a design
   question for §6.
4. **`write_document` op `correction` was refused all 29 times** (`DOC_OP_NOT_ALLOWED: 这份文档不能这样改`, 17 of
   them adding `「work_log」是流水记录…`): an option she is shown and never once allowed to use in 30 days. Either
   the option's description does not say where it applies, or the refusal should name the op to use instead (`[ ]`
   read the description).
5. **DSH's own schema validation speaks English and runs before every rule of the house.** About 60 calls in 30
   days were returned as `invalid arguments: missing required property "op"` and the like (`feel` 13, `write_document`
   12, `plan` 6, `private_words` 4, `sticker` 4, `ideas` 3, `stay_silent` 3, `think` 3, …). The message names the
   field, so she can correct it, but it is not in the `CODE: 原因；怎么办` form, not in Chinese, and carries no
   "what to do next". Fixing the wording needs the DSH fork (**marked**); the record shows the next call usually
   corrects it (`[ ]` measure).
6. **Hallucinated tool names hit the DSH guard 6 times** (`read_image` where the conversation has none, `ask`,
   `set_tags`, `lines_from_program` and `catchup` as tools): the guard's text lists the usable tools and says to go
   on without one; an adequate message.
7. **The relevance gate failed 27 times, all `Native turn stopped before stage completion`** (26) or a session
   handle clash (1), never on the model's answer shape (613 verdicts: quiet 384, join 228, 1 failed answer). The gate
   itself is reliable; its failures are the Host's.
8. **Publication is nearly failure-free:** of 4,596 outbound `SPEAK` rows from 30-day turns, 4,584 delivered, 5
   `FAILED`, 4 `UNKNOWN`, 2 `QUEUED_EXTERNAL`, 1 `CANCELLED_AFTER_FAILURE`. The failure branches of §2.5 F11 exist in
   the code and are almost never taken; their messages are checked in §4.2 by code reading.
9. **The summary lane is the largest silent spender of the one local slot.** 6,817 one-step summary sessions in 30
   days (about 227 a day) produced 7.2M output tokens, as many as all her turns together (7.0M), at a 1–3% cache hit
   rate by construction; a summary emits a median of about 2,400–3,400 output tokens (reasoning included) for a
   230-character system prompt and a 1,200-character input. Sizing and trigger in §4.3 (`[ ]`).

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
