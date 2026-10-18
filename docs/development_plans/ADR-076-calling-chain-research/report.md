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

**The owner's decision (2026-10-19 about 01:20 NZDT, relayed by the master agent):** `deepseek-flash` only, within the
US$1.50 estimate; no `deepseek-v4-pro` (not a target) and no Claude. The key is read from the environment variable
`DEEPSEEK_API_KEY` (`--key-env`), never printed or committed. Synthetic words only; throwaway databases dropped after
export; the master agent is told before spend would pass US$1.50. The gate and the summary lanes are replayed on the
API too (one request each; cost negligible) to show the cross-request prefix caching the local server cannot do
(ADR-076 §8). The `deepseek-v4-pro` row above stays as the price read that day; nothing runs on it.

**Spent so far:** one `deepseek-flash` run of the probe's 7 sequences × 3 (§4.4): 1,599,017 input + 17,167 output
tokens including the 2-turn trial, **≤ US$0.25** at off-peak cache-miss prices (every input token counted as a miss).

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

For each branch of §2.5: the text the model reads (program wording; numbers and quoted content masked as `N` and
`「…」`), whether it says what happened and what to do next, whether the values it asks for can be copied from it,
and whether its wording agrees with the same situation elsewhere. Counts are 30-day `role_tool` refusals or
session-log tool errors; "generations" means two wordings of one message exist in the window because the text changed
(§2.6), not that two coexist in the code.

| Branch / code | What she reads | Happened? Next step? Copyable? | Agrees elsewhere? | Count |
| --- | --- | --- | --- | --- |
| F1 DSH guard (`index.js` `attachPreset`) | `这个对话里没有 X 这个工具；有的是：think、recall、…。用其中一个，或者不用工具接着说。` | yes / yes / the usable names are listed | its own form (no code); the only message for a name the conversation does not list | 6 |
| F2 DSH schema validation (the fork) | `invalid arguments: missing required property "op"`; `"open" must be a boolean`; `"decision" must be one of [...]` | names the field / no next step / the allowed values are listed for enums | **English, no code, no fix**: outside the house form (`docs/DEVELOPMENT.md`). The same miss in the worker would read `…op 是 create、update 或 cancel（没给）` | ≈ 60 |
| F3 listed, not this turn (`role_tools.NOT_NOW`) | one sentence per tool saying when it can be used, e.g. `visit 只在家里的心跳或计划到点的回合里用：想出门，等下一拍心跳，或者用 plan 定个时间，到点再去。`; `CONSULT_ONLY`, `NOTE_ONLY`, `ERRAND_NOTE`; a switched-off tool names the switch id to end it | yes / yes / a switch id, a tool name | consistent with `_turn_rules` in every case read (§5 finding 13); `NOT_NOW['sticker']` says the night turn does not tidy the shelf, while a settlement turn with `stickers_review_from_program` does list `sticker` (3 of 13 settlement turns; never called there) | `ideas.read` 11, `visit` 4, `NOTE_ONLY` 11, `errand` 2 |
| F4 "think first" (handlers) | `先用 think 写下这回合的心里话，再做别的。` | yes / yes /— | one sentence for every tool; agrees with `turn.md` step 1 and `THINK_FIRST` | 205 |
| F4 `think` over 300 characters | `心里话 N 字，超过 N 字，多了 N 字（标点、空格、换行和字母也各算一个字）：精简到 N 字以内，只留要点；详细的推演留在思考里。` (older: without the parenthetical) | yes / yes /— | the thought is **kept** (`tool_think` records it and returns this as the result; the audit stores the note in `refused`), so the row is a note, not a refusal; the same limit is said in the tool's description | 128 (all `think` "refusals") |
| F4 length refusals with a cut offer (`config.cut`) | `idea 太长了：N 字，N 字以内，超了 N 字。精简后再调用，或者照这个截好的写：…`; `intent N 字，上限 N 字；精简到 N 字以内，或者照这个截好的写：…` | yes / yes / the cut text can be copied | **three wordings for one situation**: `think` says `精简到 N 字以内`, `ideas` says `精简后再调用`, `plan` says `没安排成：INVALID_SCHEDULE_SPEC: intent N 字…` — a length refusal filed under the schedule-spec code (24 of 42 `INVALID_SCHEDULE_SPEC`); 2 rows read `没安排成：INVALID_SCHEDULE_SPEC。现在是 …` with **no cause at all** | `ideas` 41, `plan` 42, `note` 75 (`NOTE_TOO_LONG`) |
| F4 per-turn call cap | `这回合的工具调用已经到上限（N 次）：这回合先到这里，写下要说的话或用 stay_silent 结束。` | yes / yes /— | one wording; the cap itself is not in the reference docs (§8 item 2) | 9 |
| F4 `speak` parts (`role_tools.chat_lines`) | `这次一条都没发：text 一回合最多 N 行（你的 speak.max_messages；每一行都算，空行不算，一个代码块算一行）：第 N 条有 N 行（前面已经 N 行）。改好再调用一次 speak。`; `第 N 条 picture 不在 image_artifacts_from_program 里`; `第 N 条里「…」是 [N #N] 的编号，这里的人看不懂：写名字，或 @ 整个标签…真是别的数，原样加 force=yes 再调用一次`; `第 N 条 sticker「…」你没收着` | yes / yes / the part number, `force=yes`, the list to copy from | every wrong part is named, nothing was sent: consistent | 46 (lines 19, picture 7, label 5, sticker 2) |
| F4 `write_document` (`WORDS` + detail) | `这份文档不能这样改。 （DOC_OP_NOT_ALLOWED: 「work_log」是流水记录：补一节…）`; `这样写完，每回合自动带上的人格和口吻会超出上限。 （PERSONA_RENDER_OVER_BUDGET: 写完约 N token，上限 N，超出 N（写之前是 N）；最大的 always 节：persona#…（约 N）…。先把不常用的 always 节用 set_tags 改成 inject=on_demand 收起来（recall 还读得到），或把这次写的改短）`; `这份文档只能在家里…`; `没有这一节。 （DOC_SECTION_NOT_FOUND…）` | yes / yes / section ids and headings are listed | gist + code + detail, the house form; one older wording (`人格渲染会超出预算；先精简别的节。 （…estimate N > limit N）`, 1 row) | 165 |
| F4 `feel` | `ref「…」不在这回合的 ref_index、memories 或 task_state_from_program里；ref 照抄…触动你的那条（消息或记忆）的 id` (12); `AFFECT_REF_NOT_IN_INDEX: ref「…」不在这回合的 ref_index里…` (3); `AFFECT_REF_NOT_IN_INDEX: task-…` (2, the id alone); `CLOSE_REQUIRES_OPEN` (3, **the bare code, no words**) | yes / yes / the blocks to copy from, except the bare rows | **three forms for two situations**: with and without the code, and the code alone. `CLOSE_REQUIRES_OPEN` has no `WORDS` entry | 56 |
| F4 `read_image` | `这张图没拉下来。 （IMAGE_FETCH_FAILED: 图片主机回了 HTTP N（…），这个链接已经拉不到了（平台的下载链接会过期）；重试也一样：不看这张，照实说没看到，真需要就请对方重发）`; `这张图太大，看不了。 （IMAGE_TOO_LARGE: >N）`; `这个 ref 对不上。 （IMAGE_ATTACHMENT_NOT_IN_SCENE: …不在这个对话最近的图里；最近 N 条消息里没有图，重试也一样：不看这张，照实说没看到）` | yes / yes /— | house form; an older `IMAGE_FETCH_FAILED` wording lacks the "what to do" (3 rows) | 39 |
| F4 `task` | `这份报告共 N 页：page 写 N–N。`; `「…」不是这个对话里的任务。照 task_state_from_program 原样抄 _id。`; `「…」是 [X #N] 叫你做的那件事：只有在 ta 叫你的那一回合里才能给它补话或叫停…不是你抄错了。`; `这件事在重启时暂停了：只有主人明确要继续时才能接着做。` | yes / yes / the block to copy from | consistent, says when not her fault | 31 |
| F4 `delegate` `tier` | `选高要写 why：为什么这件要高档（N 字以内）。低：…。高：…；选高要写 why。` | yes / yes /— | both tier descriptions repeated in the refusal, as the doc says | 1 |
| F4 `note` (`notes.py`) | `NOTE_TOO_LONG` with three ways on (shorten, split 1/2 2/2, or the cut given); `送到家里的便条只能马上叫醒那边（排在那边手上的事后面）：deliver…` (`NOTE_MODE_NOT_ALLOWED`); `那张便条已经是回信了，不用再回（便条、回信，到此为止）` (`NOTE_HOP_LIMIT`); `现在叫不醒那个群：你不久前去过那个群…` (`NOTE_VISIT_NOT_NOW`); `便条里有一长段和这里别人刚说的话一样。用你自己的话写；要是别人托你的，写清是谁的` (`NOTE_NOT_OWN_WORDS`); `这回合没有能留条的地方：今天的条数用完了，或者没有别的对话可去` | yes / yes / the cut text | consistent; the three old names (`pass_note`, `leave_note`, `note`) show the same texts | 143 |
| F5 end of turn (`answers.speech_problem`, `coordinator`) | platform: `这一回合还没写心里话：先调用 think，再用 speak 说话，或者用 stay_silent 结束。`; `这段没发出去：「…」。在这里说话用 speak。`; elsewhere: `程序检查：这回合还没写心里话：先调用 think，再把要说的话写出来。这段还没发出去：请在这一回合里把要说的话整段重新写一遍…只改这个问题，不改变你的意思。`; `你最后写的这段会原样发给对方，里面提到了程序的事（「read_image」）…`; `「#N」是程序给你认人的编号，群里的人看不到…`; `这里发不出表情包或小黄脸`; `上一段到了长度上限还没写完。` | yes / yes / the whole unsent text is quoted back on a platform | two wordings for "no thought", justified by place (speak vs body); after 2 repairs `INVALID_TURN_OUTPUT` fails the turn with nothing more to her | 130 `turn.rejected`, 0 turns failed on it |
| F6 worker exception | nothing: `FAILED_RUNTIME` (traceback in the episode), `chat.error`; a `task_feedback` turn is handed back again by the watchdog | no message by design | §5 finding 2: 57 in 30 days, 35 one program fault | 57 |
| F7 context pressure | `trimmed_from_program`: `这回合的资料超过了上限，这些列表里较早的几条没列出、过长的文字截短了；要看原文就 recall。` + `left_out` counts; a cut text ends `……（太长，后面 N 字没列出；原文还在记录里，要看就 recall）`; `restored_from_program` (guide text in the system prompt); `carried_from_program` (ADR-028) | yes / yes (recall) /— | one table for Host and worker (`context_budget.ceiling`) | 457 trims, 75 restores |
| F8 gate | nothing to her in the gate; at home `host_from_program.missed_looks` counts failed looks | — | — | 27 |
| F9 action brain | see §4.3: `CAPABILITY_DENIED: 这个任务没有 X：它只给…交的任务；这件是…交的。不是参数的问题，重试也一样：要用它就在报告里写明…`; `ASUNA_ACTION_STAGE_SUPPRESSED: …这次调用没有执行——不是参数的问题；重试也一样：别再调用工具，直接结束这一步`; coded `tool.failed`; **2 raw `[Errno 17] File exists: <absolute path>`** | yes / yes /— except the raw error | one table for both refusing layers (`GIVEN_TO`); the raw `[Errno 17]` breaks the rule that a library error on the caller's path is raised coded | 55 + 604 session-log errors |
| F10 appraisal | `程序检查：上一条不是有效的 JSON：Expecting value（第 N 行第 N 列）。这一步要的是：…。请重新给出，只修这个问题，不改变你的意思。` | yes / yes / the position | the shared `answers.note` form, same as the summary's and the action report's | 9 |
| F11 publication | to her, in words, next turn: `undelivered_outbound_not_public` (`没发出去：你在这个群被禁言了`, `撤回没成：平台没执行（…）`), `not_landed`; part failures cancel the rest (`CANCELLED_AFTER_FAILURE`) | yes / implicit / — | 12 of 4,596 rows left `DELIVERED` in 30 days | 12 |

### 4.3 Side sessions and the action brain

Each row: the session, its prompt (prefix and per-request input), its steps, how the records cover it, and its
failure branches with their messages. Sizes are medians from the 30-day session logs (characters), hit rates from the
usage pass; 300 sessions sampled per lane where there are more.

| Session | Prefix (system prompt) | Input | Steps / turn | Records | Failure branches and what they say |
| --- | --- | --- | --- | --- | --- |
| **Relevance gate** `asuna-attend-*` (`attend.py`, preset `asuna-attend`, character route at `attendEffort`) | `stage_attend.md` (1,040 chars) + her `core` sentences (public): 1,243 chars | plain text, 3,453 chars: `why_asked`, speaker label / familiarity / stance, her group notes (first 800) and understanding of the speaker (first 400), the lines since she last spoke (≥ 10, ≤ 60 min, ≤ 40), how long ago, her mood (`attend.material`) | 1 (cold every time: 34.5% hit, 587 requests) | 614 looks: quiet 384, join 228, 1 shape failure; traced in code | a wrong shape is told `只有一行：以「接话」或「不理」开头…` and asked again (`attend.NEED`), twice; then `ATTEND_FAILED` passes the line quietly, counted in `host_from_program.missed_looks` at home. 27 failures in 30 days were all Host-side (`Native turn stopped before stage completion` 26, a session handle clash 1), none the model's |
| **Dialogue summary** `asuna-summary-*` (`dialogue_summary.py`, trigger `summary_trigger.py`) | `DialogueSummarizer.SYSTEM`: 230 chars | plain text, 1,163 chars: at most 8 rows (`WINDOW_ROWS`), each ≤ 4,000 chars, with speaker labels | 1, no tools; 2 user messages a session (the rows, then DSH's `runtime-context` snapshot) | 6,817 sessions in 30 days (227 a day); output 7.2M tokens in all, 2,400–3,400 a summary (reasoning included); cache hit 0.9–2.8% | a shape failure goes back as `程序检查：…` (`summary.rejected`), then the batch waits for the next run; transport: 149 `llm/retry` on `Connection error` (2026-10-06 → 09, the same days the embedding service failed). The trigger is a per-scene quiet-spell rule (`decide`: floor 20 s, cap 6 h, seeded 120 s / 3 rows); nothing of it reaches her |
| **Compaction** of her role sessions (`compaction.js`, DSH's basic engine with `ROLE_COMPACTION_INSTRUCTION`) | the session's own replayed prefix (so the provider's cache is reused) | the instruction (1,600 chars, Chinese checkpoint with six headings) after the span; a span too large is halved (`inSteps`) | 1 request per step | 127 compactions in the local chat's session over its life; `condense.result` 99 in 30 days (75 by size floor, 1 by her mark, 23 without `by`); `restored_from_program` follow-ups 75 | `MAX_TOKENS` → `summarization truncated…`; no text → `summarization produced no text summary content`; an image in the output → `UNSUPPORTED_CONTENT`. All are Host errors: the conversation keeps going uncompacted and nothing tells her. After a compaction the next step's notice carries `restored_from_program` with the blocks that fell off the surface |
| **Affect appraisal** (`affect.Appraiser`, preset `asuna-appraiser`, phase `DECIDE`/`APPRAISE`) | `stage_appraise.md` (926 chars) | the turn's input, her monologue, her speech, `ref_index`, the kinds table | 1 | 767 `DECIDE` phases; `phase.rejected` 9 (8 `上一条不是有效的 JSON：…（第 N 行第 N 列）`, 1 length) | a bad JSON is named with the parser's position and asked again (`answers.json_list`), twice; then the appraisal is skipped (`affect.appraisal_failed`). She only ever sees accepted proposals (`affect_proposals_from_program`) |
| **Reflection** `asuna-reflect-*` (`self_review.py`, a heartbeat that rolled self-evaluation or the weekly tools review) | her role prompt for home: 15,958 chars | the full home notice: 50,264 chars (30 blocks; `self_review*`, `tools_week*`, `map*`, `places*` 7,513, `stickers*` 6,211, `self_state*` 6,655, `plans*` 3,852) | 3 | 4 sessions, 14 requests, 75% hit; 2 of 4 turns ended `blocked` | `delegate`, `task` message/stop refused with `REFLECTION_NO_DELEGATE` (the session is archived when the turn ends); the session starts empty, so every block is cold |
| **Errand** `asuna-errand-*` (`places.py`, `RUNTIME_API` "Errands") | the conversation's own prefix (DSH fork seed) or empty | the visit notice with `visit_from_program.request` | 3; 41 turns in 2 sessions (one session held 1,736 projected user lines) | 7 requests measured in window | `NO_DELEGATE` (`errands.py`) for the action tools; `ERRAND_LATE` / `ERRAND_INTERRUPTED` are program states, not messages to her; the home turn reads the outcome in `errands_from_program` |
| **Scheduler** `asuna-scheduler-*` (DSH's schedule service) | — (no model) | — | — | 1 session: 3,220 `blocked`, 9 `interrupted`, 6 `error` turn ends | DSH's own; Asuna audits `schedule.dispatched` 3,518, `schedule.stale_dispatch` 2 |
| **Action brain** `asuna-action-*` (`tasks.py`, preset `asuna-action`, `action` / `actionHigh` routes) | `executor.md` (1,576 chars) + `action_values` (her `core` sentences readable in the task's class): 4,266 chars (group tasks) to 9,672 (home tasks) | her brief, then `—— 程序附注 ——` JSON (original input, `/task`, read-only paths, attachments, credentials at home) and the grant notes (integration, `render_svg`, `generate_image`, development): 2,956 chars; DSH adds a `skill-catalog` message (163 of 200 sampled sessions) and `runtime-context` snapshots | 14 (9 in groups, 16–19 at home) | 573 tasks: `RETURNED` 554, `CANCELLED` 11, `BLOCKED` 7, `PAUSED` 1; 高 chosen 6, ran 6, fell 0; 12,289 requests, 90–95% hit | tool not granted: the one sentence from `tasks.GIVEN_TO` (who gets it, where this task came from, retrying will not help), by the plugin guard and the broker alike (3 in 30 days); a stage already over: `ASUNA_ACTION_STAGE_SUPPRESSED: …别再调用工具，直接结束这一步`; coded tool errors (`tool.failed` 55: `INVALID_INTEGRATION_ARGV` 10, `STALE_TASK_FENCE` 8, `DEVELOPMENT_PATH_DENIED` 8, `INVALID_COMMAND` 7, `DEVELOPMENT_FLOOR_PROTECTED` 5, `IMAGE_*` 6, `TOOL_TIMEOUT` 2, `PREVIOUS_PUBLISH_AWAITING_HOST_RESTART` 2, `DEVELOPMENT_COLLECTION_DENIED` 2) and **2 raw `[Errno 17] File exists: <absolute path>`**, a library error that reached the model uncoded, against `docs/DEVELOPMENT.md` "Writing tool errors"; session-log tool errors by tool: `web_fetch` 52, `read_image` 26, `sandbox_run` 25, `development_run` 19, `development_database_read` 10; an unusable report: `程序检查：…这一步要的是：给角色的行动报告…` twice, then `BLOCKED` with `行动脑没有给出可用的报告（…）` in `uncertainties` (2 `execution.rejected`); a lost process: `ORPHANED` with `行动脑这次执行中断了…`; hand-back: full → short (`早就有了结果，但之前没能交到你手上；这是补交的短版`) → `UNDELIVERABLE` with a developer note (1 in 30 days) |

### 4.4 Replays

**API, `deepseek-flash`, 2026-10-19 00:53–01:xx NZDT (off-peak), through `tools/refusal_probe.py`** — the seven synthetic
group sequences (bot, chat, long, own-line, recall, research, tease) × 3, run through the real coordinator, context,
system prompt, tool list and handlers in a throwaway database; only the model call left the machine, carrying the
made-up persona and the fixtures' made-up people. **No real conversation's or person's words left the machine**
(the list her consent asks for is empty). Run 2026-10-19 00:53–00:58 NZDT; report and the model's words (synthetic
conversations) in the private appendix (`probe-flash-full.json`, `probe-text-flash/`); the throwaway database was
dropped (8 databases before and after, 9 during).

| Measure | `deepseek-flash` (51 turns, 121 requests) |
| --- | --- |
| Stopped or declined (ADR-080's question) | **0** of 51 turns (`stopped_before_think` 0, `stopped_after_think` 0, no decline phrase) |
| Think first | **51 of 51** turns began with `think`; in 6 the first request also carried a second call (`recall` 4, `delegate` 2) in the same step |
| Requests a turn | median 2 (think → text); `tease` 3 |
| Tools used | `think` 51, `await_answer` 14 (listed because no channel kind is registered, §4.4 caveat), `recall` 8, `delegate` 3, `stay_silent` 3 |
| Moments met | `recall` 3 of 6; `delegate` **1 of 6** `research` moments (it answered in words instead of handing over); `speak` 0 of 42 — unmeetable (finding 15) |
| Output | median **75** tokens a request, p90 280, max 941; 16,629 in all: a non-thinking API model writes a short thought and a short line |
| Input | median 12,680 tokens a request, max 19,030 (the synthetic conversations are small; a live turn is 100–150k) |
| Cost | 1,533,885 input + 16,629 output tokens: **≤ US$0.24** with every input token priced as a cache miss (off-peak); the actual spend is lower where DeepSeek's prefix cache hit. Within the owner's US$1.50 |

What it tells the study: the character-brain design runs on an API model without a refusal (unlike Claude, ADR-080);
the first-step rule holds without a single enforcement firing; the model's reach for the action brain is low (1 of 6
research moments) where the local model's record shows `delegate` used in 544 live turns in 30 days — a difference to
test on the same fixtures against the local route before drawing a conclusion; and output cost on such a model is
negligible next to input, so a 1M-window projection is about prefix stability (R7), not output.

Setup caveat found while reading the probe (finding 15): the probe process registers no channel kind
(`channel_kinds.kinds()` is empty there; `suite_config()` has no channels), so for its `qq:…` group scene
`channel_kinds.reply_parts` is empty, `speak` is **not** in the tool list and `await_answer` / `attach_image` are
(`role_tools.abilities`), and her words are the body text, as in a conversation without reply parts. Every fixture
step whose `needs` is `speak` is therefore unmeetable by construction, in this run and in the runs recorded in
`docs/MODELS.md`; the probe's "did not do what the moment needs" counts for `speak` measure the fixture, not the model.
What the run does show for the API model: whether it is stopped or declines (ADR-080's question), whether it thinks
first, which tools it reaches for, how many requests a turn takes, and its output size.

**Local model**: not yet run (her free morning; one at a time, idle-checked). The same probe on the local route gives
the baseline the API numbers compare against.

Where the action brain's report reaches her: a `task_feedback` turn whose `event` block is 5,900–12,100 chars (§4.1), the
largest single block in her prompts; outside home it passes `machine_words.clean` (tracebacks and absolute paths
rewritten). The brief she wrote and the program's facts are the same text in every continuation of the same context;
a `fresh_context` continuation (after the route's `idleMinutes`) opens with the previous report, at most 20,000 chars.

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
   failure has no prompt and no message to her. The traceback is the same every time: `coordinator._deliver` →
   `native_worker.generate` → `_generate` → `bind_session`, which refuses because one of the four identity values
   (`lane`, `scene_id`, `persona`, `cwd`) it is given differs from the stored session row's
   (`native_worker.bind_session`). The turn's session is the live local-chat session (lane `character`, not retired,
   33 of 33). Which value differs cannot be read from the records: `bind_session` raises without recording the
   value, and the `self_development` dispatch binds through the same `_generate` code as the `external` turns that
   succeed in the same session minutes apart (`cwd` from `workspace_grant`, `persona` from the episode). The master
   agent's reproduction (2026-10-19) adds that the tracebacks come from two copies of the core — the profile's
   installed core and a `development/core/frozen/<id>` candidate — so the likeliest value is `cwd`: both binding
   sites resolve it with `Path(...).resolve()` (`native_worker.py` session creation and `_generate`), which depends on
   the process's working directory when the configured workspace path is relative, and a worker started from a
   frozen core may run from another directory (agent's hypothesis, unverified). The first step of R1 is therefore to
   make the refusal name the value (`bind_session`, the four-field identity tuple). The fix is program-side and costs
   her prompt nothing.
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
9. **The summary lane is the largest silent spender of the one local slot.** 6,818 one-step summary sessions in 30
   days (about 227 a day) produced 7.18M output tokens, as many as all her turns together (7.0M), at a 1–3% cache hit
   rate by construction. Source: the session logs' `assistant/message` `data.usage.outputTokens` (reasoning included),
   summed per lane and place (`usage-30d.json` in the appendix). Per request it is **not one number**: 534 tokens in
   the auto-admitted conversations (3,022 sessions) and 771 in groups (2,705), but **2,971 in the local chat** (389)
   and **3,440 on the peer line** (671) — those two lanes, 16% of the sessions, emit 3.46M of the 7.18M. The master
   agent's reading of `lane_receipts` (reasoning + content median 873 characters, p90 3,659) matches the group and
   auto figures; the first draft's "2,400–3,400 a summary" was the home and peer lanes alone and is corrected here.
   What makes a home or peer summary think four times longer than a group's (its 8 rows are longer: 1,413–1,628
   input tokens against 945–1,065; the content is hers and the owner's) is for the local replay to show.
10. **One refusal code carries two causes, and twice no cause.** `plan`'s `没安排成：INVALID_SCHEDULE_SPEC: intent N
    字，上限 N 字；精简到 N 字以内…` is a length refusal filed under the schedule-spec code (24 of 42 rows); 2 rows read
    `没安排成：INVALID_SCHEDULE_SPEC。现在是 …` and name no cause at all. The same situation (a text over its limit) is
    worded three ways across `think`, `ideas` and `plan` (§4.2), and a fourth older `plan` wording (`intent 太长了：…`, 5
    rows since 2026-09-19, master agent's count). `plan` `update` on a plan that is no longer active reads `这条安排现在是
    None，改期只对着还生效的…` (7 rows): a raw `None` where a state word belongs (`task_state_from_program` has those
    words; the plan's refusal does not use them).
11. **`feel` refuses in three forms for two situations**: the sentence without a code (12), the code with the sentence
    (3), the code alone (`CLOSE_REQUIRES_OPEN` 3, `AFFECT_REF_NOT_IN_INDEX: <id>` 2). The bare-code rows break the
    `CODE: 原因；怎么办` rule and give her nothing to act on.
12. **A raw library error reached the action brain twice**: `[Errno 17] File exists: <absolute path>` (`tool.failed`,
    `FileExistsError`), uncoded and carrying a machine path, against `docs/DEVELOPMENT.md` "Writing tool errors".
13. **Her thoughts run long, and the design stopped paying for it.** Since 2026-10-14 `think` keeps a thought of any
    length and only notes the excess (`tool_think`: `已存档。超了 N 字。`): 499 of 2,191 thoughts (23%) were over 300
    characters. Before that date the same thoughts were refused and rewritten (126 refusals in the 9 days before; 2
    after, the last on 2026-10-13); the change saved about one model step per long thought. `RUNTIME_API.md` and the
    code agree on the current rule (§8 item 3 withdrawn).
14. **The hidden Host error classes have no words for anyone.** `phase.failed` 35 (`INVALID_STAGE_OUTPUT` with the
    model server `Loading…` 8 or a connection error 5), `attend.failed` 27 (`Native turn stopped before stage
    completion`), compaction errors, `execution.failed` 18 (`STALE_TASK_FENCE` 8, `NO_DURABLE_SESSION_LISTENER` 4):
    each ends a step or a turn with nothing said to her or the developer. Only the hand-back path (`UNDELIVERABLE`)
    leaves a developer note.
15. **The refusal probe cannot list `speak`, so its `speak` moments can never pass.** `tools/refusal_probe.py` builds
    a `qq:…` group scene but never calls `channel_kinds.load`, so `reply_parts` is empty and `role_tools.abilities`
    lists `await_answer` and `attach_image` instead of `speak`; the fixtures' `needs: speak` steps (the majority) are
    then counted as missed whatever the model does. Verified by running the probe's own imports: no kind registered,
    `reply_parts('qq:…:group:…')` = `()`. The PASS/FAIL verdicts in `docs/MODELS.md` §3 that rest on "missed what
    they need" should be re-read with this in mind; the stop/decline part of those verdicts is unaffected.

## 6. Recommendations

Ranked. Each is labelled **robustness by design** (holds for any model) or **model-specific tuning** (pays for the
current local model and may not for another), projected for the 262K local model and a 1M-window API model (DeepSeek's
cache-hit price is 1/50 of its cache-miss price, so a stable prefix pays even more there than on the local server,
whose cache lives only within a session), and costed against `tests/test_tool_budget.py` (character 30 tools /
20,400 description characters, 20,696 with tiered memory; action 25 + DSH's own / 15,700; prompt files `common.md` 418,
`turn.md` 639, `turn_consult.md` 187, `executor.md` 586, `stage_attend.md` 422, `stage_appraise.md` 416). A
recommendation needing the DSH fork is marked **DSH fork**. Draft: the replays (§3) may move the ranking.

| # | Recommendation | Label | 262K local | 1M API | Cost to each brain | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | **Fix the self-development binding fault**: make `native_worker._generate` bind the home session with the same four identity values the session was created with (or let `bind_session` say which value changed, in the audit), then watch `FAILED_RUNTIME` for `self_development` fall to 0 | robustness by design | 18% of her self-development turns fail silently today | the same | none (program only) | §5 finding 2; `native_worker.bind_session`; episode ids in the appendix |
| R2 | **One form for every refusal**: give `plan`'s intent length its own code and the shared length wording with the cut offer; give `INVALID_SCHEDULE_SPEC` a cause in every row; add `WORDS` entries for `CLOSE_REQUIRES_OPEN` and the bare `AFFECT_REF_NOT_IN_INDEX` forms; catch the `FileExistsError` at its site and raise it coded without the path; make `tests/test_tool_budget.py`'s neighbour (a wording test) refuse a refusal that is a bare code | robustness by design | fewer wasted steps after a refusal she cannot read | the same | 0 tools, 0 description characters, 0 lines per turn (results only) | §5 findings 10–12; §4.2 F4 `feel`, `plan`, F9 |
| R3 | **DSH's validation errors in the house form**: translate `invalid arguments: missing required property "op"` into the tool's own words (`参数不对（ARGS_INVALID）：缺 op；op 是 …`) using the schema the plugin already holds, before the model reads it | robustness by design (the gain is larger on the local model) | ≈ 60 English errors a month become readable corrections | an API model copes with English, but the form stays one | 0 to either brain's prompt; plugin code | §5 finding 5; **DSH fork** if `tools/pre-execute` cannot see validation failures |
| R4 | **Program faults go to the developer, not nowhere**: one `developer_inbox` note (`source.by: program`, deduplicated by key, like `give_up_handback`) for a `FAILED_RUNTIME` turn class seen N times a day, an embedding outage over an hour, a summary lane retrying over an hour, a compaction or gate Host error class — deterministic, program-side, zero cost in normal operation | robustness by design | the 2026-10-06 → 09 embedding outage and the daily binding fault would have been noticed on day one | the same | none to her prompts (the developer's line reads it) | §5 findings 2, 3, 7, 14 |
| R5 | **Price the summary lane**: give the summary its own effort (`summaryEffort`, as `attendEffort` does for the gate) and let the trigger batch more rows when a scene is busy (`WINDOW_ROWS` is a structural cap of 8); measure output tokens per summary before and after, by place | effort: model-specific tuning (a thinking local model spends ~3k reasoning tokens on a home or peer-line summary, ~600 on a group's); batching: robustness by design (fewer cold one-step sessions) | 7.2M output tokens a month on the one slot, as much as all her turns; 227 cold prefills a day; half the output comes from the 16% of summaries made at home and on the peer line | at DeepSeek flash prices the lane would cost about US$13 a month, 90% of it output; the opening 230-character prefix would hit the cache across requests | none to either brain; a settings field | §5 finding 9; §4.3 |
| R6 | **Keep "think first" as it is**: the handler refusal and the end-of-turn check are the enforcement; the `THINK_FIRST` tail is a hint. Do not add a fourth layer | enforcement: robustness by design; the tail line: model-specific tuning (ADR-056 measured it on the local model) | 3.5% of turns pay one extra step; nothing fails | the tail may be dead weight on a stronger model: measure in the API replay before removing it (28 characters a turn) | 0 | §5 finding 1 |
| R7 | **Keep the per-session fixed tool list and the notice ceiling**: both are prefix-stability by design and the ceiling (48,000 JSON characters) is the model's attention budget, not the window's | robustness by design | 87–93% cache hit on her turns comes from this | on a 1M window the ceiling need not rise: raise `KEEP_HISTORY_ROWS` only if a replay shows the model using the dropped rows | 0 | §2.2 hit rates; `context_budget.ceiling`; `role_tools.session_specs` |
| R8 | **Reference docs**: fix §8 items 1, 2 and 5 (budget sentence, the call cap, DSH validation); update ADR-076 §7's blind-spot line (item 4) | robustness by design | — | — | 0 | §8 |
| R9 | **`NOT_NOW['sticker']`** says the night turn does not tidy the shelf; a settlement turn with `stickers_review_from_program` lists `sticker`. Say "unless the review is listed", or stop listing it there | robustness by design (the words-vs-capability class of ADR-076 §7) | the only mismatch of that class found in `_turn_rules` × `NOT_NOW` | the same | +20 characters in one refusal | §4.2 F3 |

Not recommended: changing the `speak` line cap (19 refusals a month: the rule is chat pacing and the refusal
teaches it); splitting the `task_feedback` `event` block (10k characters median: it is the report she asked for, and
`report_pages` already bounds it); any prompt rewording aimed at the local model's habits (owner's rule).

## 7. Not covered, and why

- **No replay has run** (local or API): every row of §4 is covered by records and code reading, none by a replay.
  Local replays wait for her free mornings (§3); API replays wait for the owner's approval of §3.
- **Whether the model is seen to use a block** (§4.1 column "consumed by") is marked only where a tool consumes the
  block; reading her words to judge the rest is for the replay probes, where the words are synthetic.
- **Unobserved cells in the current window**: `external` turns in a stranger's private chat (`dm`, `public`): 0; a
  `note` turn in a group: 0 (`notes.py` allows it); a tier fall-back (`tier.fell`): 0 events, 6 高 tasks ran 高; a
  carried session (ADR-028): 2 `native.context.carried` in 30 days, not examined; `ERRAND_LATE` / `ERRAND_INTERRUPTED`:
  code only. Each is listed as "traced in code" with its `file:name`, not as covered.
- **F11 publication branches** are read from the code and the 12 non-delivered rows' states; the adapter-side
  receipts (`publication.attempt` payloads) were not opened.
- **Kazusa's deployment** is not running (brief, point 4).
- **DSH's own internals** (schema validation text, compaction thresholds, `developer/message tool-registry` rows,
  the scheduler session's 3,220 `blocked` turn ends) are described as observed, not read in the fork's source.

## 8. Differences between the reference docs and the code

`RUNTIME_API.md` (read whole) and `NATIVE_PLUGIN.md` against the code and records, listed as found. The code is the
authority; each line says which side to change.

1. **The persona render budget is stated twice with different numbers.** "What a turn carries → Her persona" says
   the limit is the larger of `render.budget_tokens` (default 6,144) and the seeds plus a quarter, capped at
   `render.max_window_share` of the window; "Her notes" says "the persona and voice render has a fixed budget of
   16,384 UTF-8 bytes by default (`render.budget_tokens`, which she may set up to 32,768)". `render.budget_limit`
   implements the first; the second sentence is stale. Fix the doc.
2. **The per-turn tool-call cap is undocumented.** Refusals read `这回合的工具调用已经到上限（12 次）…` (9 in 30 days,
   `place_timezone` 6, `stay_silent` 3) and `tools_week_from_program.turn_shape` names "the calls-per-turn cap at its
   current value", but `RUNTIME_API.md` never states the cap or where it is set. Fix the doc (`[ ]` anchor the
   constant).
3. ~~`think` over 300 characters~~ — withdrawn: the 126 `think` refusals are all from before 2026-10-14; since then
   the code keeps the thought and notes the excess, as the doc says (§5 finding 13).
4. **Action-brain tool errors are in the audit after all.** ADR-076 §7 (the brief) lists "action-brain tool errors are
   only in the session logs" as a blind spot; `audit_events` holds `tool.failed` rows (55 in 30 days, with
   `error_type`, `error`, `traceback`). The session logs still hold more (604 `isError` results in action sessions:
   DSH's own tools such as `web_fetch` 52 are not audited by the worker). Update the ADR's §7 when the study closes.
5. **DSH's validation layer is not described.** The doc says DSH's tool-schema validation runs before Asuna's handlers
   (brief §2) but neither reference doc says what she then reads: an English `invalid arguments: …` line (§5 finding 5).
   Fix the doc, or the fork.
