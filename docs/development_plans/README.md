# Development plans

This folder holds Asuna's architecture decision records (ADRs): what was decided, why, and plans not yet built. It is not the authority for current behaviour; that lives in [RUNTIME_API.md](../../RUNTIME_API.md), [docs/DEVELOPMENT.md](../DEVELOPMENT.md) and the source.

Large built ADRs keep only their decisions still in force, with the full text named by a git hash. Archived ADRs are removed from the tree; `git show <hash>:docs/development_plans/<folder>/<file>` (or `git log --all -- docs/development_plans/<folder>`) brings any of them back.

## Order of work (owner, 2026-10-13)

Kept current by the master agent (Claude); each plan has one builder at a time.

| # | Plan | Where it stands | Waits on |
|---|---|---|---|
| 1 | ADR-066 an errand carries home | Built 2026-10-15; first real errand checked 2026-10-16 (fork, title, archive as designed; first step cold after an idle hour) | nothing |
| 2 | ADR-067 audit growth | Built 2026-10-15 | 24 h of growth measured from the restart that installed it (2026-10-15 00:31 UTC; expected ~130 MB a day); the first daily prune around 2026-10-20 |
| 3 | ADR-050 hand-back clean-up | Built 2026-10-16 (`machine_words.py`) | her restart; then the same count a week later, expecting zero. Gate asks merged per group and a fair task queue: measured first |
| 4 | ADR-069 her tools, kept by what only they do | Built 2026-10-16 (id matching held on the data) | installed with her next restart; the old names leave 2026-10-23 |
| 5 | ADR-070 her weekly tooling review | Built 2026-10-16 (3,200 characters, measured on her week) | installed with her next restart; she checks the first reading |
| 6 | ADR-071 her exchanges, read back beside the thought she wrote | Built 2026-10-16 (3,200 characters, measured on her days) | her `self_review.tag` in her persona model; installed with her next restart |
| 7 | ADR-072 her reflection in a session of its own | Built 2026-10-16 (owner's decision: an empty session) | installed with her next restart; whether night self-development moves too: measured first |
| 8 | ADR-073 a map of what she has, in her reflection | Built 2026-10-16 (her review in) | installed with her next restart |
| 9 | ADR-074 the audit bounded by time and by size | Built 2026-10-16 (owner's numbers: 30 days, her tool calls a year, 6 GB) | live since her 19:26 publication; the first deletions around 2026-10-20 |
| 10 | ADR-075 her action brain by tier | Built 2026-10-16 (written and signed by her; owner's go) | the owner picks 高's model on the settings card; installed with the next Host restart; she checks the tier line and the weekly `why` beside what happened on real jobs |

Rules (owner): tooling changes go in when built and tested, and the next plan starts without waiting; changes to her
memory or her prompt get observation time on real turns before the next step builds on them. Her per-turn input is
profiled after each install (ADR-062 §7); anything sent twice is a defect fixed before the next step.

Status: **Active** (an ongoing routine or plan), **Open** (built, with a named part still pending), **Built**, **Decided** (accepted, not built), **On hold**, **Archived**.

| ADR | Title | Status | Decision | Where |
|---|---|---|---|---|
| 001 | V1 architecture and Codex package | Archived | First V1 design and eval package; superseded by the later plans | archived, git f652bb64 |
| 002 | Core-first reset: local entry and autonomous QQ access | Archived | Local entry first, QQ built by her; carried out through ADR-003/005/008 | archived, git 9146d705 |
| 003 | V2.2 NapCat native flow and growth | Archived | NapCat native flow on DSH timers; superseded by ADR-005 and ADR-008 | archived, git 47a7434e |
| 003.1 | DSH extension correction | Archived | Asuna extends DSH and never cuts its tools; the principle lives on in ADR-005 and AGENTS.md | archived, git 120bc68e |
| 004 | UI elements V1 kit | Archived | Custom workbench UI kit; superseded by ADR-006, then ADR-008 | archived, git cf7c21ce |
| 005 | QQ functional: memory and daily interaction | Built | QQ profiles, history query, group digest, summaries, timed plans, topic-aware proactive turns, read-only scene links; built by her | [folder](ADR-005-asuna_qq_functional/README.md) |
| 006 | Native UI reuse | Archived | Native DSH components plus Asuna composition; superseded by ADR-008 | archived, git 040c24e6 |
| 007 | Autonomous self-development foundation | Built | Experience → reflect → develop → verify → forward-only publish, with boot survivability the one protected floor | [folder](ADR-007-asuna_autonomous_self_development/README.md) |
| 008 | DSH native plugin | Built | One DSH Host: native sessions and UI, Asuna as core plugin plus persona packages; paused work waits for an explicit go-ahead after restart | [folder](ADR-008-dsh-plugin/README.md) |
| 009 | Persona residency | Built | Persona-agnostic primitives (documents, affect ledger, rhythm, persona jobs), Mongo the one state truth, owner-private visibility | [folder](ADR-009-persona_residency/README.md) |
| 010 | DSH distributable plugin | On hold | GitHub Release .tgz, uv, MongoDB, local inline patch, GPLv3; M0–M5 built, the upstream DSH PR (D7-A) on hold | [folder](ADR-010-dsh-distributable-plugin/README.md) |
| 011 | Both brains on native tools | Built | `think` then tools then the reply as the last text; tools between the brains; one publish path | [folder](ADR-011-brain-tools/README.md) |
| 012 | Heartbeat and places | Built | Home is her main loop; the program owns the heartbeat, she sets its pace and goes out to groups | [folder](ADR-012-heartbeat-places/README.md) |
| 013 | DSH peer channel | Built | Two agents in different DSH Hosts talk over `@asuna/dsh-peer` | [folder](ADR-013-dsh-peer/README.md) |
| 014 | Context budget | Built | Per-turn limits table; she tidies her own notes at night | [folder](ADR-014-context-budget/README.md) |
| 015 | DSH sandbox replaces WSL | Archived | Commands run under DSH's write-only sandbox; `sandbox_run` only in the owner's scenes; the rule lives in `src/asuna/sandbox_backend.py` | archived, git 50af104b |
| 016 | QQ faces and her sticker shelf | Built | Platform faces plus a sticker shelf she keeps herself | [folder](ADR-016-stickers/README.md) |
| 017 | Home and public boundary | Built | Public words reach home only through her own reviewed, audited paths | [folder](ADR-017-home-public-boundary/README.md) |
| 018 | Notes between her conversations | Open | Notes trusted from home, cautioned and tool-limited from public; live Web review pending | [folder](ADR-018/README.md) |
| 019 | Linux deployment and Docker | Built | The plugin inherits DSH's platform layer; Docker is a deployment layer on top | [folder](ADR-019/README.md) |
| 020 | Several characters at once | Open | One Host and page per character, a database per profile; M1, M2, M4, M5 built, Web review pending | [folder](ADR-020-several-characters/README.md) |
| 021 | Night self-development in stages | Built | Night stages one at a time; a change needing a Host restart is hers to request (ADR-034) | [folder](ADR-021-night-self-development/README.md) |
| 022 | Catching up missed QQ messages | Open | History fetched by the adapter, old lines marked and gated; off until the owner names routes | [folder](ADR-022-qq-catchup/README.md) |
| 023 | Chatbot security by design | Archived | Not adopted (owner: no extra burden on her), nor the lighter measures | archived, git d90d7866 |
| 024 | What she sees in a group | Built | Member lists by the adapter, a slice per turn; trigger and recent pictures; animated pictures as a contact sheet | [folder](ADR-024-what-she-sees-in-a-group/README.md) |
| 025 | Understanding in two layers | Built | The person wherever she meets them, and how they are in each conversation | [folder](ADR-025-understanding-in-two-layers/README.md) |
| 026 | Ordered web search | Built | SearXNG first, then Exa, then DSH's DeepSeek search, behind the same tool | [folder](ADR-026-ordered-web-search/README.md) |
| 027 | render_svg | Built | An SVG she writes becomes her own picture (resvg on the Host) | [folder](ADR-027-render-svg/README.md) |
| 028 | Carried-summary recovery | Built | An overflowing conversation continues in a new session with its last summary | [folder](ADR-028-carried-summary-recovery/README.md) |
| 029 | Group history archive | Built | Old human group lines kept as archived messages, read only by explicit history; a platform id names a message only with its time | [folder](ADR-029-group-history-archive/README.md) |
| 030 | Handover watchdog | Open | A program watchdog hands back a failed handover by cause; slowness is not a failure; live check pending | [folder](ADR-030-handover-watchdog/README.md) |
| 031 | Persona recall evaluation | Archived | Retrieval by the incoming turn rejected for persona sections; concluded in ADR-032 (option A) | archived, git 8aecc148 |
| 032 | Section places | Built | A persona section renders only in the places it serves (`place:` tags) | [folder](ADR-032-section-places/README.md) |
| 033 | Agent line | Built | A trusted `agent` channel kind, one route and key per coding agent, `tools/agent_line.py` | [folder](ADR-033-agent-line/README.md) |
| 034 | Host supervisor | Built | The launcher restarts DSH on her request or a crash, down a fallback ladder; her `restart` tool | [folder](ADR-034-host-supervisor/README.md) |
| 035 | QQ picture links | Built | Picture links re-signed with the current key when fetched | [folder](ADR-035-qq-picture-links/README.md) |
| 036 | Models are DSH providers | Built | The brains' models are DSH providers; no model routes or keys in Asuna's config | [folder](ADR-036-models-are-dsh-providers/README.md) |
| 037 | Following DSH | Active | Every DSH alpha after 7 days; patches as commits on the owner's fork; the upgrade routine | [folder](ADR-037-following-dsh/README.md) |
| 038 | Fixed tool lists | Built | One tool list per conversation for cache hits; turn rules as refusals; `pin_memory` removed | [folder](ADR-038-fixed-tool-lists/README.md) |
| 039 | Active groups | Built | Resting groups wake her only when meant for her; she chooses with `group_focus` | [folder](ADR-039-active-groups/README.md) |
| 040 | Merged forwards | Built | Forwards read and previewed; the full text pulled by ref | [folder](ADR-040-merged-forwards/README.md) |
| 041 | Who she waits for | Built | Lines of the last hour still awaiting someone, shown at home and in that group | [folder](ADR-041-who-she-waits-for/README.md) |
| 042 | What the night changed | Built | The first home heartbeat after night turns lists what they changed, with her reasons | [folder](ADR-042-what-the-night-changed/README.md) |
| 043 | Reasons behind actions | Built | Each action keeps its thought and the reason comes back; batches 1 and 2 built, later batches planned | [folder](ADR-043-reasons-behind-actions/README.md) |
| 044 | Persona embodiment | Built | Identity and biography from the persona; history, perception and actions from evidence | [folder](ADR-044-persona-embodiment/README.md) |
| 045 | Sister heartbeat wakes | Built | Her sister's asides wait in her home heartbeat until she answers | [folder](ADR-045-sister-heartbeat-wakes/README.md) |
| 046 | QQ Bot channel | Open | Official QQ Bot platform beside NapCat (kind `qqbot`); first step built | [folder](ADR-046-qq-bot-channel/README.md) |
| 047 | Bot or person | Decided | Telling bots from people inside her skill, no new tools; the skill is hers | [folder](ADR-047-bot-or-person/README.md) |
| 048 | Effort by action | On hold | Thinking effort by what she does; waits for the full benchmark | [folder](ADR-048-effort-by-action/README.md) |
| 049 | Quiet-time upkeep | Built | Slang and habits learned on note-writing visits; early condensing once a group is quiet | [folder](ADR-049-quiet-time-upkeep/README.md) |
| 050 | Lessons from exploited bots | Open | Nobody's text passes for the program's lines; private-words answers the same either way; first batch built | [folder](ADR-050-lessons-from-exploited-bots/README.md) |
| 051 | Owner on agent lines | Built | The owner can speak on an agent line, labelled as his | [folder](ADR-051-owner-on-agent-lines/README.md) |
| 052 | Switches at home | Built | Mute, block, tools off for a while; every switch ends by itself or says where it is on | [folder](ADR-052-switches-at-home/README.md) |
| 053 | Action brains | Built | A context per task, an idle limit, and she is told at hand-over | [folder](ADR-053-one-action-brain/README.md) |
| 054 | Tool wording from her mistakes | Built | Each confusable tool says when to use it rather than its sibling | [folder](ADR-054-tool-wording-from-her-mistakes/README.md) |
| 055 | Fewer tools, same abilities | Built | `task` and `ideas` merge the follow-up and notebook tools | [folder](ADR-055-fewer-tools-same-abilities/README.md) |
| 056 | Per-turn characters | Built | Fixed text once in the system prompt; clock times in blocks; only what changed | [folder](ADR-056-per-turn-characters/README.md) |
| 057 | Group labels | Built | Nothing typed can pass for a label; the number authenticates nothing, so the plan is closed; random ids parked | [folder](ADR-057-group-labels/README.md) |
| 058 | Heartbeat dice | Built | The heartbeat rolls a die (rest, interesting, self development, self evaluation, review, reach out) with tables she sets | [folder](ADR-058-heartbeat-dice/README.md) |
| 059 | Reading the database, git and ssh from her home tasks | Built | Owner's keys and logins, her own name on commits; no read-only database user; `asuna.dbread` reads only and repeats its query, 零行 when empty; skill asuna-database | [folder](ADR-059-home-reach/README.md) |
| 060 | Plain parameter names | Built | One name per idea, words a reader understands (`op`, place/line/to, why/reason, yes/no as words); old names keep working a while; her review | [folder](ADR-060-plain-parameter-names/README.md) |
| 061 | Asking for help | Built (closed 2026-10-16: 88 group questions, 85 answered) | One question to many sources (Claude, a group, the owner, the action brain), each with a patience; answers labelled by source, never judged; per-turn cost kept to counts and arrivals; she remembers how each ask went | [folder](ADR-061-asking-for-help/README.md) |
| 062 | Tiered memory | Built, on since 2026-10-14 | One item per idea in three places (随身 / 手边 / 收着) by confirmation and use, not refusal; details fade into her gist with the verbatim kept; night consolidation and graduation into character_core; phase 0 (work_log as rows) built | [folder](ADR-062-tiered-memory/README.md) |
| 063 | Context growth defects | Built (D1–D12) | Her conversations grew 6–9× faster than her sister's: D1 group lines and failing compaction, D2–D11 duplicates and non-folding blocks; fixed in order before ADR-062 | [folder](ADR-063-context-growth-defects/README.md) |
| 064 | QQ notices | Built (phase 1, and phase 2 with ADR-061, live since 2026-10-14) | Phase 1: NapCat notices projected to one-off text lines, never stored; through the relevance gate like text (poke at her, reaction to her line); recall shown as a quoted line, no DB work; requests answered by her home session; cards kept for the action brain, not read by default; voice/video parked. Phase 2: a reply tool (text, sticker, poke, reaction in any combination), like ADR-061 | [folder](ADR-064-qq-notices/README.md) |
| 065 | Sandbox temporary folders | Accepted, built | A confined command's temporary folder is inside its own folder, and its Pythons make 0o700 folders with inherited permissions (`sandbox_site`), so `tempfile` works in her scripts; on Windows its git uses OpenSSL (Schannel has no credentials under the restricted token) and logs in through an askpass that asks the credential manager; she has her own working copy, made by the Host (owner 2026-10-13) | [folder](ADR-065-sandbox-temp-folders/README.md) |
| 066 | An errand carries home | Accepted and built 2026-10-15 (delegate does not carry home; pictures follow the conversation's rules) | The turn an `errand` opens gets home's full permission for that turn only, in a DSH fork of the destination's session that keeps its prompt and tools (warm cache) and appends home at the end; only what she says goes back, with one `errand_from_program` block; home-only tools stay home; forks retired like one-shot sessions | [folder](ADR-066-errand-carries-home/README.md) |
| 067 | The audit stops copying what is kept elsewhere | Accepted and built 2026-10-15 | Commits leave out a memory's embedding; context.prepared keeps the manifest; no state.intent; bulky diagnostic records past 30 days deleted daily (retention now ADR-074) | [folder](ADR-067-audit-growth/README.md) |
| 068 | Editing a picture with generate_image | Built 2026-10-15, checked live 2026-10-16 | `source_image` read with read_image's fence; an edit of someone else's picture goes back only where it came from; uploads deleted after the job; the service owns size and frames | [folder](ADR-068-image-edit/README.md) |
| 069 | Her tools, kept by what only they do | Built | A tool or parameter is kept by whether it does something nothing else can; `update_self` retired; `pass_note` and `leave_note` merged keeping `deliver=wake` and limits; old names retired by use; long text and inexact ids answered with what to send | [folder](ADR-069-tools-by-what-only-they-do/README.md) |
| 070 | Her weekly tooling review | Built | Once a week her own review of her tools: the program's readings (calls, refusals and what they cost, unused parameters, lengths, turn shape, her action brain, the list she carries, last week's proposals) in a self-evaluation turn; her proposals to add, remove or reshape go to the developer's line, the developer answers each within a day |
| 071 | Her exchanges, read back beside the thought she wrote | Built | Her daily self-review reads back a sample of her lines with what she meant then and what followed (facts only, no tone or sentiment label, others' words as 60-character cautioned excerpts); never a score; her lessons go by next-time notes, her voice document and her ideas |
| 072 | Her reflection runs in a session of its own | Built | A turn carrying review readings runs in its own empty session, archived after: more tokens for reflection, none in her regular turns (owner 2026-10-16) |
| 073 | A map of what she has, in her reflection | Built | In reflection turns only: one line per store (size, what changed, how to open it), what she changed in her own words, and attention as counts |
| 074 | The audit is bounded by time and by size | Built | Audit records go after 30 days (her tool calls after a year, the latest showing of each review kept); over 6 GB of data the oldest go first | [folder](ADR-074-audit-bounded/README.md) |
| 075 | She picks the action brain by tier; a hard failure falls to the tier below | Built | Two tiers told by capability only (no model, provider, price or implementation word); 低 is the default and 高 exists only when the owner configured it; 高 needs a `why`; a hard failure at 高 falls to 低 for the rest of the job and never rises; a line failure rests 高 for its idle minutes, a key or quota failure with no clock; she is told the tier she chose, the tier that ran and why; counts, never a score | [folder](ADR-075-action-brain-intensity-tiers/README.md) |
| 076 | A research study of her calling chains, paths and prompts | Proposed | One-off study by a separate research agent early in the week of 2026-10-19: every calling chain normal and failure, every prompt per scenario class, the optimal path balancing long-term robustness and economics for the 262K local model and a 1M API model; local replays in her free mornings, API for comparison; a coverage matrix and labelled recommendations; Claude implements after the owner and Xiaoman agree | [folder](ADR-076-calling-chain-research/README.md) |
| 077 | The current references, analysed and reshaped as interface control documents | Proposed | After ADR-076: Claude analyses every current reference (who reads it for which question, every fact checked against the code), then a generated ICD for interface facts with an agreement test and short prose for behaviour; Xiaoman reviews; sign-off by real lookups answered correctly with fewer characters read | [folder](ADR-077-documents-as-interface-control/README.md) |
| 078 | A skill may say it can be used outside home | Built | Action-brain jobs from groups and others' chats get no skills (home-only rule of 2026-10-05); each skill opts in by a header field, diagnostic and development skills stay home; character brain unchanged | [folder](ADR-078-skills-outside-home/README.md) |
| 079 | Lines that point at other lines (quote, reply, reaction, recall) | Accepted | One handle on every line (its number), one rendering of "this points at that" whoever made it, one way to choose a line in every tool, three fields to the adapter, and capabilities the running adapter declares with what it cannot carry hidden; chosen by a 720-run experiment on the local model and DeepSeek; step 1 (what she reads) first | [folder](ADR-079-choosing-what-to-quote/README.md) |
| 080 | Can a model run her character brain without being refused (refusal probe) | Built; Sonnet 5.5 FAIL | Synthetic SFW group conversations and a made-up persona run through the real character-brain design in a throwaway database; only the model call goes to the provider; PASS, FAIL (stopped, declined in its own words, or a moment that missed what it needs) or no result; no model words kept | [folder](ADR-080-refusal-probe/README.md) |
| 081 | Videos as contact sheets, and a life cycle for stored pictures | Built | A video is read like an animated picture: downloaded into memory (32 MB cap), cut into the same 9-moment contact sheet with words that say it has no sound, and dropped; every stored picture has an owner or an expiry (pulled copies 7 days, pool candidates while listed, her records kept), swept daily | [folder](ADR-081-videos-and-media-life/README.md) |
