# Development plans

This folder holds Asuna's architecture decision records (ADRs): what was decided, why, and plans not yet built. It is not the authority for current behaviour; that lives in [RUNTIME_API.md](../../RUNTIME_API.md), [docs/DEVELOPMENT.md](../DEVELOPMENT.md) and the source.

Large built ADRs keep only their decisions still in force, with the full text named by a git hash. Archived ADRs are removed from the tree; `git show <hash>:docs/development_plans/<folder>/<file>` (or `git log --all -- docs/development_plans/<folder>`) brings any of them back.

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
| 021 | Night self-development in stages | Built | Night stages one at a time; a change needing a Host restart waits for the owner | [folder](ADR-021-night-self-development/README.md) |
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
| 043 | Reasons behind actions | Open | Each action keeps its thought and the reason comes back; batches 1 and 2 built, later batches planned | [folder](ADR-043-reasons-behind-actions/README.md) |
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
| 057 | Group labels | Open | Nothing typed can pass for a label; the number authenticates nothing; random ids parked | [folder](ADR-057-group-labels/README.md) |
| 058 | Heartbeat dice | Built | The heartbeat rolls a die (rest, interesting, self development, self evaluation, review, reach out) with tables she sets | [folder](ADR-058-heartbeat-dice/README.md) |
