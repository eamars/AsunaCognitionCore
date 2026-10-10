# Project map

Read this before the code. It answers how the main things are done, in words, and points to where each one lives.
Below that, every module has one line, by area. Each area page gives a module's description and its public
functions, without code. Open the code once the map has told you where to look.

Names like `visibility.session_class` are a module and a function in `src/asuna`; JavaScript files are named with
their extension. The ADRs in [docs/development_plans](../development_plans/README.md) say why a thing was decided.

## How it is done

### How is home kept apart from public?

Every turn has a **class**, decided by the program from the conversation and the speaker:
`visibility.session_class`.
- **owner_private:** the owner's local chat, his private chats, and the trusted home lines (the agent lines and the
  peer line, whose channel kind declares `HOME`).
- **public:** everything else.

`visibility.place` refines this into four places: home, peer, group and dm.

- **What she reads follows the class.**
  - Memory recall searches only this conversation's scope, the shared `global-safe` scope and, at home, her
    owner-private scope (`retrieval.Retrieval.search`). A linked conversation adds its scope but never raises the
    class (`scene_links`).
  - Documents and persona sections are filtered the same way (`visibility.readable`, `render.readable_sections`), and
    a section tagged with places renders only there.
  - `context.ContextBuilder` adds the home-only blocks only in owner_private turns: her mood's reasons, the developer
    inbox, her places, errands and credentials.
- **What she can do follows the place.** Each conversation lists its tools by place (`role_tools.toolbox`): her
  settings, `restart` and her idea notebook only at home; `errand` only in the owner's own conversations; `visit`,
  `promote_memory` and `credential` only in the local chat.
- **What crosses is always hers and always visible.**
  - A note she writes from one conversation to another (`notes`) arrives marked trusted when it comes from home and
    untrusted from outside. An untrusted one opens a turn that can only read, answer and note ideas.
  - An errand (the owner sends her elsewhere) and a visit (she goes to a group) carry only the words she takes there
    (`places`).
  - Public lines never reach home live. A home heartbeat sees, from outside, only her own delivered words and how
    the groups are going (`places.places_block`, `places.elsewhere`). What others said comes home only through her
    own review: her idea notebook and her night's promotion of a memory
    (`role_tools.RoleTools.tool_promote_memory`).
  - Pictures: in groups and other people's chats she can send only pictures she made (`outbound_media.own_only`).
- **Her words outside** are checked for program talk (`answers.speech_problem`). At home, tool names are a normal
  topic.

Decided in ADR-009 §2, ADR-017 (the home and public boundary), ADR-018 (notes), ADR-032 (places), ADR-038 (tools by
place).

### How is QQ connected to DSH, and how do her words get back?

Two hops, each over a local HTTP API: NapCat ⇄ the QQ adapter ⇄ Asuna's channel server ⇄ her DSH session.

1. **NapCat → adapter.** The adapter is the napcat-qq package's integration
   ([qqadapter](../../packages/channels/napcat-qq/integration/qqadapter)). It runs under the worker as a managed
   service (`integration`, in DSH's sandbox) and keeps a forward WebSocket to NapCat (`onebot.py`: one `/event`
   connection, one `/api` connection).
   - An event is written to a disk spool first (`journal.py`), then checked against the allowlists and the group's
     member snapshot (`inbound.py`).
   - After a gap it reads the missed lines from QQ history (`catchup.py`).
2. **Adapter → Asuna.** It posts each line to the channel server on `127.0.0.1:8766` (`hostapi.py` →
   `POST /v1/channels/qq/events`), authenticated with the channel token and the route's key.
   - The server is `channels.ChannelServer`; `channels.Channels.receive` admits new groups and people
     (`channel_admission.admit`) and hands the line to the queue.
   - `ingress.persist_input` stores it, and the scene's queue takes it in order (`chat.Chat`).
   - In a group, the relevance gate (`attend`) decides whether she joins in. In a group she lets rest, only an @,
     a reply to her, her awaited answers and watched people wake her (`focus.wake`).
3. **Asuna → DSH.** The line becomes input to the conversation's DSH role session.
   - The worker emits `channel_input` (`native_worker`); the Host plugin ([index.js](../../packages/cognition-core/src/index.js))
     puts it into the session's inbox.
   - Her turn runs there (see the next question). The QQ conversation in the Web page is that session, view only.
4. **Back out.** Her words are stored as an outbound message, an outbox row (`publish.PublishService`).
   - The adapter long-polls `GET /v1/channels/qq/outbox` (`channels.Channels.claim`) and sends through NapCat
     (`outbound.py`: `send_group_msg`, `send_private_msg`, with pictures and stickers).
   - It reports the platform's answer with `POST …/receipt` (`channels.Channels.receipt`). Until that receipt her
     words are "not yet confirmed".

The platform's own formats (ids, mentions, faces) are in the kind module
[napcat_qq](../../packages/channels/napcat-qq/python/napcat_qq/__init__.py), loaded by `channel_kinds`; the core names
no platform. Decided in ADR-005 and ADR-016; the adapter's own manual is
[its README](../../packages/channels/napcat-qq/README.md).

### How does one of her turns run?

1. **Episode.** An input becomes an episode (`ingress`), and `coordinator.Coordinator` runs one turn per episode.
2. **Context.** `context.ContextBuilder` assembles what she reads: memories, people, mood, tasks, places, notes, all
   as words. `render.render_system` renders the system prompt (core prompts plus her persona's every-turn sections).
3. **The turn.** It is a native DSH turn in the conversation's role session. She calls `think` first, then any tools
   (`role_tools`), and each text she writes is what she says.
4. **Checks.** Her words pass the end-of-turn checks (`answers.speech_problem`, stickers, labels); a failed check is
   told to her in the same turn.
5. **Publish.** `publish` sends what passes.

Context that has not changed since she last saw it is not sent again (`context-delivery.js`). The tool list is the
same in every turn of a conversation, so the model keeps the conversation cached (ADR-038).

### How does the action brain get a job and hand it back?

1. **Handing over.** `delegate` (`role_tools.RoleTools.tool_delegate`) creates a task (`tasks.TaskService`) with the
   tools its origin grants (`grants`).
2. **Running.** `tasks.Executor` runs it in its own DSH session, a child of her conversation
   ([children.js](../../packages/cognition-core/src/children.js)), and the Web page shows it inline under her turn.
   Every tool call goes through `tasks.ToolBroker` and is checked against the task's grant.
3. **Handing back.** The report comes back to her conversation as a task result. A long report comes as its first
   page, and she turns the rest with `read_report`. She can talk to a running task (`message_action`), stop it
   (`stop_action`), and answer its questions (`answer_action`).

Decided in ADR-011.

### How does she remember and recall?

- **Indexing.** Her conversations are stored as messages and indexed into memory units (`memory_indexer`).
- **Summaries.** Batches are summarized with the speakers attributed by the program (`dialogue_summary`,
  `summary_attribution`).
- **Recall.** A turn recalls by meaning within what the class may read (`retrieval.Retrieval.search`), and she can
  `recall` more herself.
- **Keeping.** At night she promotes what is worth keeping long term (`promote_memory`). Her own documents (persona,
  voice, notes) live in `documents`, and her understanding of people in `understanding`.

### How do her plans, heartbeats and nights happen?

- **Plans.** Her plans are DSH Schedule jobs (`schedule.ScheduleService` on the Host's Schedule service); `plan`
  writes them, and `schedule_rules` checks the timing.
- **Turns.** A plan coming due opens a `scheduled` turn. Her heartbeat (`presence`), her night (`settlement`) and her
  self-improvement time (`self_development`) are rhythm plans the program keeps (`schedule.RHYTHM_KINDS`).

### How does a change to herself go live?

- **Her records** (persona, voice, policies) change at once through her own tools (`write_document`, `update_self`,
  `set_policy`).
- **Capabilities.**
  - Code, skills and adapters change in a candidate through the action brain's development tools (`development`), and
    take effect through `development_publish` (the publication floor,
    [floor.js](../../packages/cognition-core/src/floor.js)).
  - A change the Host must load needs a restart. She asks with `restart` (`restarts`).
- **The states of a publication.** `development_publish` (`PublicationFloor.publish` in
  [floor.js](../../packages/cognition-core/src/floor.js)) checks the candidate, probes that it boots and packs it, then
  selects it in `.runtime/adr008/activation.json`:
  - **HOST_RESTART_REQUIRED:** JavaScript, package or lock files changed. Nothing runs it yet. At the next start the
    launcher installs it (`applySelection` in [asuna-launch.mjs](../../tools/asuna-launch.mjs)), which makes it APPLIED.
    An unattended self-improvement turn cannot publish on top of one still waiting.
  - **APPLIED:** installed. The worker loads it when it next starts.
  - **ACTIVE:** running. `PublicationFloor.workerReady` sets it when the worker has started on it; the Host plugin
    calls it once the worker is ready ([index.js](../../packages/cognition-core/src/index.js), which tells the worker
    `publication.activated`).
  - A selection that has not become ACTIVE after two starts goes back to the last ACTIVE one (`advanceSelection` in
    asuna-launch.mjs; the supervisor does the same when it falls back).
  - So "published" is not "running": running is ACTIVE, after a start.
- **Protected files.** The publication floor cannot be changed by her own publishing: the launcher and start scripts,
  the pack and install tools, floor.js and the modules it imports, and the runtime manifest (`protectedPaths` in
  floor.js). Writing one in a candidate is refused, and so is publishing a candidate that changed one
  (`DEVELOPMENT_FLOOR_PROTECTED`). Only the owner, or his coding agents, change them in the checkout.
- **The launcher.** It prepares each start from the code on disk
  ([asuna-launch.mjs](../../tools/asuna-launch.mjs)), and its supervisor falls back to the previous version when a
  start fails ([asuna-supervisor.mjs](../../tools/asuna-supervisor.mjs)).

Decided in ADR-011 §6 and ADR-034; her skill
[asuna-self-improvement](../../packages/cognition-core/skills/asuna-self-improvement/SKILL.md) says how.

### Where does state live?

- **Mongo.** Messages, episodes, memories, tasks, documents, plans' records and audit (`state.Store`; every write has
  an expected revision and is audited).
- **DSH's home.** Her sessions, settings and credentials (`.runtime/adr008/home`).
- **The data root.** Files she works on, published versions and private lists (`.runtime`).

[DEVELOPMENT.md](../DEVELOPMENT.md#where-state-lives) has the full table.

## Modules by area

<!-- map:modules -->
### [Entry and hosting](hosting.md)

The worker the Host plugin starts, its store, configuration and audit.

- [`native_worker`](../../src/asuna/native_worker.py) — Private business worker for the DSH Host plugin; no model or Web runtime.
- [`host`](../../src/asuna/host.py) — Long-lived owner of Application, queues and adapter listeners; Web is a client.
- [`application`](../../src/asuna/application.py) — Wires the worker's services together: `Application` opens the store, starts retrieval and the action brain's tool broker, then the model lanes, the coordinator, the executor and the router.
- [`cli`](../../src/asuna/cli.py) — The `asuna` command line: `asuna ui` opens the native DSH Web profile; every other command is debug or maintenance only and needs `--debug`.
- [`config`](../../src/asuna/config.py) — Paths and checks every module shares: `ROOT` (the source tree), `DATA` (this profile's data folder), `LOCKS`, the allowed-database and endpoint rules, and credential redaction.
- [`native_settings`](../../src/asuna/native_settings.py) — Native DSH settings migration and model-free runtime validation.
- [`lanes`](../../src/asuna/lanes.py) — The model-lane contract: `LaneResult` is what one turn returns (its text, tool calls and everything she said), and `FakeLane` is the scripted stand-in tests use instead of a model.
- [`queue`](../../src/asuna/queue.py) — Process-wide and cross-process endpoint serialization, without cloud routes.
- [`state`](../../src/asuna/state.py) — The worker's MongoDB store: every write goes through `Store.put` with an expected revision and is recorded in a hash-chained audit stream.
- [`audit`](../../src/asuna/audit.py) — Checks and replays the store's audit trail: `verify` walks each stream's hash chain, `verify_documents` compares stored documents with their last audited commit, and `replay` rebuilds the state in an empty test database.
- [`evidence`](../../src/asuna/evidence.py) — File evidence for runs and probes: `Evidence` writes each event as a hash-chained JSON file in a new folder; `canonical` and `sha` are the stable JSON bytes and digests the store's audit chain also uses.
- [`testing`](../../src/asuna/testing.py) — Explicit teardown for databases owned by isolated tests and probes.
- [`restarts`](../../src/asuna/restarts.py) — Her restarts (ADR-034): the worker side of the Host supervisor (tools/asuna-supervisor.mjs).
- [`host_stops`](../../src/asuna/host_stops.py) — When the Host was taken away from outside (小满's ask, 2026-10-08): she should not have to infer from a gap in the logs whether she was away.
- [`host_lease`](../../src/asuna/host_lease.py) — One running Host per database, across machines (ADR-020 M1).
- [`local_time`](../../src/asuna/local_time.py) — Times a model reads are on the local clock (owner 2026-10-08): stored records keep UTC for the program, and everything handed to a model passes `for_model` first.

### [A turn](turn.md)

From an input to her words: queueing, context, her tools, the checks, publishing.

- [`ingress`](../../src/asuna/ingress.py) — Durable input boundary.
- [`router`](../../src/asuna/router.py) — Trusted host envelopes and debug fixtures share the persisted application route.
- [`coordinator`](../../src/asuna/coordinator.py) — One character turn per episode (ADR-011 §3).
- [`context`](../../src/asuna/context.py) — Builds what her turn shows her: `ContextBuilder.prepare` reads one event's scene, persona, relationship, memories, history, tasks and other state, and returns the system text, the context blocks and a manifest of them.
- [`context_budget`](../../src/asuna/context_budget.py) — What a turn may carry on its own, and how her own notes stay short (owner 2026-10-06, ADR-014).
- [`render`](../../src/asuna/render.py) — Role system prompt rendering (ADR-009 §8.1).
- [`role_tools`](../../src/asuna/role_tools.py) — Her mind's tools: what the character brain may do in one native turn (ADR-011 §3, §5.1).
- [`tool_args`](../../src/asuna/tool_args.py) — What she plainly meant, before a tool checks its arguments (owner 2026-10-06).
- [`answers`](../../src/asuna/answers.py) — Deterministic checks on a model's answer wherever the program needs one to continue (owner 2026-10-05).
- [`publish`](../../src/asuna/publish.py) — Sends her accepted lines: `PublishService.publish` checks the turn is still current, then queues a platform line for its channel route or delivers a local-chat line with an idempotent receipt.
- [`lines`](../../src/asuna/lines.py) — Her own open/close of a peer line (ADR-013 §6).
- [`chat`](../../src/asuna/chat.py) — Shared local controller reused by the native Web host; there is no terminal adapter.
- [`handover`](../../src/asuna/handover.py) — ADR-030: the program's watchdog over handovers between the brains.

### [Groups and people](people.md)

Who is talking, whether she joins in, her places, notes between conversations.

- [`attend`](../../src/asuna/attend.py) — The relevance gate (owner direction 2026-10-04): may she let a group message pass?
- [`proactive`](../../src/asuna/proactive.py) — ADR-005 P5：没被@的时候要不要醒一次——分寸从这个场景已经落库的真实行里算。
- [`rhythm`](../../src/asuna/rhythm.py) — Rhythm block and recent-phrasing hint (ADR-009 §10.1, §11.2).
- [`people`](../../src/asuna/people.py) — Who is who in a scene, as the character reads it.
- [`peer_context`](../../src/asuna/peer_context.py) — Bind and store the verified platform peer snapshot; people.py turns it into what she reads.
- [`familiarity`](../../src/asuna/familiarity.py) — How well she knows a person, in words (AGENTS.md: interpreted state from a versioned table).
- [`group_admin`](../../src/asuna/group_admin.py) — Group administration where she is an admin (owner direction 2026-10-04: on by default).
- [`group_members`](../../src/asuna/group_members.py) — Who is in a group (owner 2026-10-08, her design in member-list-eval): the channel adapter fetches each admitted group's member list when it starts and periodically, and posts it when it changed.
- [`watches`](../../src/asuna/watches.py) — Her watchlist (owner 2026-10-06): people she wants to hear about when they speak, in any conversation.
- [`places`](../../src/asuna/places.py) — Her places (ADR-012 §4.2, §4.4): the groups she can visit from home, and what a visit sees.
- [`focus`](../../src/asuna/focus.py) — Her active and resting groups (ADR-039): she stays present in a few groups and lets the others rest.
- [`notes`](../../src/asuna/notes.py) — Notes between her own conversations (ADR-018, owner 2026-10-07).
- [`scene_links`](../../src/asuna/scene_links.py) — 跨场景只读联动（A2）：一条有向边 + 一个 canonical person，配置是唯一真相。
- [`visibility`](../../src/asuna/visibility.py) — Session class and data visibility (ADR-009 §2).
- [`understanding`](../../src/asuna/understanding.py) — Her understanding of a person, in two layers (owner 2026-10-08, with her wording).
- [`private_words`](../../src/asuna/private_words.py) — Words that point at real people and places, kept per deployment and never committed.

### [Memory](memory.md)

What she remembers, how it is recalled, her documents, mood and blobs.

- [`memory`](../../src/asuna/memory.py) — Her written memory: `commit_understanding` saves the understanding of a person she writes in a turn, `chunk` cuts chat lines into memory units for recall, and `rollback` is the operator's audited undo.
- [`memory_indexer`](../../src/asuna/memory_indexer.py) — Index persisted local dialogue off the generation thread; restart scans pending work.
- [`retrieval`](../../src/asuna/retrieval.py) — Local embeddings and server-side, prefiltered Mongo vector retrieval.
- [`history_query`](../../src/asuna/history_query.py) — 查宿主保存的授权消息（P1-b）：字面检索覆盖完整 messages，原文整条回读。
- [`dialogue_summary`](../../src/asuna/dialogue_summary.py) — Low-priority, source-bound summaries for new dialogue batches (DM and authorized groups).
- [`discussion_digest`](../../src/asuna/discussion_digest.py) — ADR-005 P1-c：按需整理当前授权群里指定时间／主题的讨论（同一来源、同一授权）。
- [`summary_trigger`](../../src/asuna/summary_trigger.py) — ADR-005 P2：自动摘要什么时候该动手——触发点从场景自己真实出现过的节奏里算出来。
- [`summary_attribution`](../../src/asuna/summary_attribution.py) — ADR-005 P2：摘要条目上的说话人归属与更正——由程序从真实行算出来，不让模型自己认领。
- [`documents`](../../src/asuna/documents.py) — Document layer ``doc:<persona>:<slug>`` (ADR-009 ARCHITECTURE §5).
- [`self_state`](../../src/asuna/self_state.py) — Role-owned self descriptions, stored in the existing revision ledger.
- [`affect`](../../src/asuna/affect.py) — Affect ledger and projection (ADR-009 ARCHITECTURE §6).
- [`blobs`](../../src/asuna/blobs.py) — Scoped, hash-verified GridFS storage for bounded-document overflow.
- [`privacy`](../../src/asuna/privacy.py) — Explicit operator erasure, with scope invalidation and auditable redaction roots.

### [Persona](persona.md)

The persona package, its model and policies, her skills and ideas.

- [`persona_model`](../../src/asuna/persona_model.py) — Persona model: validation and effective parameter values (ADR-009 PERSONA_CONTRACT §3).
- [`persona_data`](../../src/asuna/persona_data.py) — Persona data API and probes (ADR-009 PERSONA_CONTRACT §5–§6).
- [`persona_jobs`](../../src/asuna/persona_jobs.py) — Persona jobs: run-to-completion programs a persona package declares (ADR-009 PERSONA_CONTRACT §7).
- [`policy`](../../src/asuna/policy.py) — Policy store ``policy:<persona>`` (ADR-009 PERSONA_CONTRACT §3).
- [`skills`](../../src/asuna/skills.py) — Skill discovery roots; discovery and parsing remain native DSH services.

### [Channels and pictures](channels.md)

The channel API, platform kinds, stickers, seeing and sending pictures.

- [`channels`](../../src/asuna/channels.py) — Authenticated transport-neutral adapter seam.
- [`channel_kinds`](../../src/asuna/channel_kinds.py) — Channel kinds registered by channel plugins (e.g. @asuna/napcat-qq).
- [`channel_admission`](../../src/asuna/channel_admission.py) — Owner-configured channel admission.
- [`caught_up`](../../src/asuna/caught_up.py) — Lines caught up after a gap: a channel adapter fetched them from the platform's history once it was back.
- [`stickers`](../../src/asuna/stickers.py) — Her sticker shelf and the platform's own faces (ADR-016).
- [`vision`](../../src/asuna/vision.py) — 入站图片元数据与行动脑 DSH ``read_image`` 接线。
- [`outbound_media`](../../src/asuna/outbound_media.py) — 出站图片附件：她的 attach_image 工具 → SPEAK 行上的元数据 → 通道字节端点 → 已送达历史。
- [`animated`](../../src/asuna/animated.py) — Animated pictures as something a still-image model can see: one labelled contact sheet plus words.

### [Work and tools](work.md)

The action brain's tasks, grants, schedules, sandbox, development and integrations.

- [`tasks`](../../src/asuna/tasks.py) — The action brain's tasks: `TaskService` claims, leases, cancels and hands each result back to her, `ToolBroker` checks and runs every tool call a task makes, and `Executor` runs one task in its workspace.
- [`grants`](../../src/asuna/grants.py) — Host-owned resource grants, never inferred from a message or model role.
- [`schedule`](../../src/asuna/schedule.py) — Business ownership for native DSH reminders; no host time wheel.
- [`schedule_rules`](../../src/asuna/schedule_rules.py) — ADR-005 P3：把自然语言里的时间换算成 DSH 的那一次钟点——纯换算，不碰网络也不碰 Mongo。
- [`sandbox`](../../src/asuna/sandbox.py) — A task's commands, run under DSH's sandbox (sandbox_backend.py): writes stay in the task folder.
- [`sandbox_backend`](../../src/asuna/sandbox_backend.py) — Where commands the worker does not write itself run: DSH's own sandbox (owner 2026-10-06).
- [`development`](../../src/asuna/development.py) — Schemas for the native Host publication floor; no second publisher.
- [`credentials`](../../src/asuna/credentials.py) — Her credentials (owner 2026-10-07): secrets a home task may use without any brain holding the value.
- [`image_generation`](../../src/asuna/image_generation.py) — Pictures from the configured local image service, for any task (owner 2026-10-06).
- [`svg_render`](../../src/asuna/svg_render.py) — render_svg (ADR-027): an SVG file in the task folder made into a PNG she can look at and send.
- [`integration`](../../src/asuna/integration.py) — Owner-granted (and, narrowly, agent-line) fixed-network integration lifecycle; contains no platform protocol.
- [`integration_fetch`](../../src/asuna/integration_fetch.py) — Trusted one-shot artifact fetcher, run by the managed integration (integration.py) for one configured endpoint.
- [`integration_image`](../../src/asuna/integration_image.py) — Trusted one-shot image generation, run only inside the managed integration namespace.
- [`integration_import`](../../src/asuna/integration_import.py) — Owner-local import of one artifact from an already configured integration endpoint.
- [`developer_inbox`](../../src/asuna/developer_inbox.py) — Her messages to the developer agent (owner 2026-10-08): the agent that changes her program, not the owner.

### [The Web page's data](page.md)

What the Web page reads and changes through the worker.

- [`native_api`](../../src/asuna/native_api.py) — Bounded, read-only projections for native DSH's Asuna memory tab.
- [`native_cognition`](../../src/asuna/native_cognition.py) — Read-only cognitive state coverage for the existing native Memory view.
- [`native_ui`](../../src/asuna/native_ui.py) — Compatibility entry for the installed native DSH profile; stdlib only.

### [The Host plugin](plugin.md)

The DSH plugin (JavaScript): the worker it starts, her sessions, the action brain's children, the publication floor and the Web page contributions.

- [`action.js`](../../packages/cognition-core/src/action.js) — The action brain's preset plugin: each action agent gets the executor's system prompt and only the tools its task was granted (`attachAction` in index.js).
- [`api.js`](../../packages/cognition-core/src/api.js) — The `asunaApi` remote service the Web page calls: worker and model status, the settings card's save and apply, her memory pages, brain context views, session kinds and titles, and persona jobs.
- [`appraiser.js`](../../packages/cognition-core/src/appraiser.js) — The optional affect appraiser's preset plugin: a tool-free session that proposes affect events and never speaks.
- [`attend.js`](../../packages/cognition-core/src/attend.js) — The relevance gate's preset plugin: one small tool-free session per group that decides whether she joins in (attend.py), never speaking itself.
- [`carry.js`](../../packages/cognition-core/src/carry.js) — A conversation that no longer fits the model's window continues in a new session (ADR-028).
- [`channel.js`](../../packages/cognition-core/src/channel.js) — Channel contribution: a platform plugin (e.g. @asuna/napcat-qq) registers its kind with Core.
- [`children.js`](../../packages/cognition-core/src/children.js) — Her action brain's children: tasks (catalogued DSH subagents) and the worker's own hidden stages.
- [`client.js`](../../packages/cognition-core/src/client.js) — The Web page's Asuna parts in DSH's browser client: the memory tab, the settings card, the two brains' thread, her tool rows, conversation marks and turn titles.
- [`collab.js`](../../packages/cognition-core/src/collab.js) — The two brains' collaboration thread in her conversation (ADR-011 §7.1).
- [`compaction.js`](../../packages/cognition-core/src/compaction.js) — Character-brain compaction: DSH's basic engine with a Chinese role-play checkpoint.
- [`context-delivery.js`](../../packages/cognition-core/src/context-delivery.js) — Per-turn context delivery for the character brain: of the whole context the worker prepares every turn, only what her session does not still show is sent.
- [`fetch.js`](../../packages/cognition-core/src/fetch.js) — Her web_fetch, underneath (ADR-026 §6): one fetch provider on DSH's web seam.
- [`floor.js`](../../packages/cognition-core/src/floor.js) — Minimal publication floor, deliberately independent of the business worker.
- [`image-refusal.js`](../../packages/cognition-core/src/image-refusal.js) — A model that refuses a picture must not end her turn, nor leave the conversation resending it (owner 2026-10-06).
- [`index.js`](../../packages/cognition-core/src/index.js) — The Host plugin's core: `CognitionCore` starts the Python worker and runs the turns it prepares in her native DSH sessions, with her role and action tools served by the worker.
- [`navigation.js`](../../packages/cognition-core/src/navigation.js) — Her conversations as DSH sessions: `organizeNativeWorkspaces` creates and titles the workspaces and sessions the worker plans, and `recordChannelInput` writes a received platform line into its conversation without starting a turn.
- [`paths.js`](../../packages/cognition-core/src/paths.js) — Where a profile's files live: `dataRoot` (the profile's data folder, which the worker also gets as ASUNA_DATA_ROOT), the local chat's working folder and the publication floor's state folder.
- [`persistence.js`](../../packages/cognition-core/src/persistence.js) — DSH 0.2.1-alpha.2 compatibility seam for informational plugin event envelopes.
- [`persona.js`](../../packages/cognition-core/src/persona.js) — Persona contribution v2 (ADR-009 PERSONA_CONTRACT §2): shape checks at registration.
- [`preset.js`](../../packages/cognition-core/src/preset.js) — An Asuna agent preset row: DSH's own preset row (@deepseek-ai/dsh-agent-preset) with its name and description declared per language.
- [`python-env.js`](../../packages/cognition-core/src/python-env.js) — Builds the worker's Python environment on first start: a venv in the profile's data folder, installed from the package's `requirements.lock` with uv, or with any Python 3.12+ and pip.
- [`recovery.js`](../../packages/cognition-core/src/recovery.js) — The recovery preset plugin: a repair session limited to the project development tools, which runs through the publication floor even while the cognition worker is down.
- [`role.js`](../../packages/cognition-core/src/role.js) — The character brain's preset plugin: her role session gets the worker-rendered system prompt and her role tools (`attachRole` in index.js).
- [`schedule.js`](../../packages/cognition-core/src/schedule.js) — Business receipt adapter over the single native Host scheduler.
- [`scheduler.js`](../../packages/cognition-core/src/scheduler.js) — The scheduler session's preset plugin: when DSH's scheduler wakes it, it hands the due reminders to the worker (schedule.js) and makes no model request.
- [`search.js`](../../packages/cognition-core/src/search.js) — Her web_search, underneath (ADR-026): one search provider on DSH's web seam (ctx.web) that tries the backends of `deployment.search.order` in turn.
- [`settings.js`](../../packages/cognition-core/src/settings.js) — Business validation around DSH's authoritative revisioned settings store.
- [`spill.js`](../../packages/cognition-core/src/spill.js) — Read only this action's native spill directory; never widen its workspace.
- [`steer.js`](../../packages/cognition-core/src/steer.js) — Steer in her role sessions (owner 2026-10-06).
- [`summary.js`](../../packages/cognition-core/src/summary.js) — The dialogue-summary preset plugin: a tool-free session on the action route that writes low-priority conversation summaries.
- [`svg-worker.js`](../../packages/cognition-core/src/svg-worker.js) — Renders one SVG to PNG with resvg in a worker thread (started by svg.js), so a heavy picture cannot hold up the Host.
- [`svg.js`](../../packages/cognition-core/src/svg.js) — The Host side of render_svg (ADR-027): resvg renders an SVG the worker has already made safe (no links to pictures outside it), in a worker thread with a time and pixel limit.
- [`tool-output.js`](../../packages/cognition-core/src/tool-output.js) — Save images before exposing their durable native attachment references.
- [`ui-language.js`](../../packages/cognition-core/src/ui-language.js) — The language of the names the program gives what DSH shows as plain text: her rhythm tasks in the task page and the scheduler session's title.
- [`worker.js`](../../packages/cognition-core/src/worker.js) — Runs the Python business worker (`asuna.native_worker`) as a child process in the profile's data folder and talks to it in JSON lines: `call` sends a request and waits for its answer; a line without an id is an event for index.js.

### [Channel packages](channel-packages.md)

Each platform plugin: its kind module (ids and formats), its Host plugin and its adapter.

- [`agent-line/python/agent_line/__init__.py`](../../packages/channels/agent-line/python/agent_line/__init__.py) — Coding agents on this machine as an Asuna channel kind (asuna/channel_kinds.py).
- [`agent-line/src/index.js`](../../packages/channels/agent-line/src/index.js) — The agent-line channel plugin: registers the channel kind `agent`, the lines coding agents use to talk with her; agents post and poll through the channel API themselves (tools/agent_line.py).
- [`dsh-peer/python/dsh_peer/__init__.py`](../../packages/channels/dsh-peer/python/dsh_peer/__init__.py) — Another DeepSeek Harness agent as an Asuna channel kind (asuna/channel_kinds.py).
- [`dsh-peer/src/bridge.js`](../../packages/channels/dsh-peer/src/bridge.js) — The bridge between Asuna's channel API and one session of another DSH Web server (ADR-013).
- [`dsh-peer/src/index.js`](../../packages/channels/dsh-peer/src/index.js) — The DSH peer channel plugin: registers the channel kind `dsh` and, when a peer session is configured, runs the bridge (bridge.js) between her and one session of another DSH Web server.
- [`napcat-qq/integration/adapter.py`](../../packages/channels/napcat-qq/integration/adapter.py) — NapCat/OneBot v11 adapter entry point for the managed integration runner.
- [`napcat-qq/integration/qqadapter/__init__.py`](../../packages/channels/napcat-qq/integration/qqadapter/__init__.py) — NapCat / OneBot v11 forward-WebSocket adapter for the Asuna runtime host.
- [`napcat-qq/integration/qqadapter/catchup.py`](../../packages/channels/napcat-qq/integration/qqadapter/catchup.py) — Catch-up after a gap: the messages she missed while this adapter or its event socket was down.
- [`napcat-qq/integration/qqadapter/config.py`](../../packages/channels/napcat-qq/integration/qqadapter/config.py) — Load and validate /integration/config.json.
- [`napcat-qq/integration/qqadapter/faces.py`](../../packages/channels/napcat-qq/integration/qqadapter/faces.py) — QQ's own faces (小黄脸): id <-> name, from faces.json next to this file.
- [`napcat-qq/integration/qqadapter/fixtures.py`](../../packages/channels/napcat-qq/integration/qqadapter/fixtures.py) — Built-in placeholder fixtures for the offline self checks.
- [`napcat-qq/integration/qqadapter/hostapi.py`](../../packages/channels/napcat-qq/integration/qqadapter/hostapi.py) — HTTP client for the runtime host channel API (stdlib only).
- [`napcat-qq/integration/qqadapter/inbound.py`](../../packages/channels/napcat-qq/integration/qqadapter/inbound.py) — OneBot message event -> host envelope, with the authorization gate.
- [`napcat-qq/integration/qqadapter/journal.py`](../../packages/channels/napcat-qq/integration/qqadapter/journal.py) — Disk-backed spool, journals and counters.
- [`napcat-qq/integration/qqadapter/members.py`](../../packages/channels/napcat-qq/integration/qqadapter/members.py) — Group member lists for the host (0.7.1): who is in each admitted group, not only who spoke.
- [`napcat-qq/integration/qqadapter/onebot.py`](../../packages/channels/napcat-qq/integration/qqadapter/onebot.py) — Forward WebSocket client: one read-only /event connection, one /api call connection, with echo correlation and late-ack tolerance.
- [`napcat-qq/integration/qqadapter/outbound.py`](../../packages/channels/napcat-qq/integration/qqadapter/outbound.py) — Host outbox -> OneBot send_private_msg / send_group_msg -> receipt.
- [`napcat-qq/integration/qqadapter/peers.py`](../../packages/channels/napcat-qq/integration/qqadapter/peers.py) — Peer identity: who is speaking, and whether it is still the same person.
- [`napcat-qq/integration/qqadapter/selfrole.py`](../../packages/channels/napcat-qq/integration/qqadapter/selfrole.py) — Her own role in each group (owner / admin / member), so the host knows what she may do there.
- [`napcat-qq/integration/qqadapter/selftest.py`](../../packages/channels/napcat-qq/integration/qqadapter/selftest.py) — Offline + live self checks.
- [`napcat-qq/integration/qqadapter/service.py`](../../packages/channels/napcat-qq/integration/qqadapter/service.py) — Wiring: WS reader -> durable spool -> host submitter, host outbox -> send.
- [`napcat-qq/python/napcat_qq/__init__.py`](../../packages/channels/napcat-qq/python/napcat_qq/__init__.py) — QQ through NapCat, as a channel kind of the Asuna core (asuna/channel_kinds.py).
- [`napcat-qq/skills/qq-napcat-adapter/decode_log.py`](../../packages/channels/napcat-qq/skills/qq-napcat-adapter/decode_log.py) — 把 qq-napcat-adapter 的日志行翻成人话摘要（离线，只读 stdin 或文件）。
- [`napcat-qq/src/index.js`](../../packages/channels/napcat-qq/src/index.js) — The QQ channel plugin: registers the channel kind `qq` with Core, with its kind module (`napcat_qq`), the NapCat adapter her integration tools develop and run, and its skills.

### [Tools](tools.md)

Commands for setup, packing, launching, probes and maintenance.

- [`agent_line.py`](../../tools/agent_line.py) — A coding agent's line to her (ADR-033): post a message, poll her answers.
- [`asuna-launch.mjs`](../../tools/asuna-launch.mjs) — Stable entry: native Web and repair tools boot without importing Python code.
- [`asuna-supervisor.mjs`](../../tools/asuna-supervisor.mjs) — The Host supervisor (ADR-034): the launcher stays as DSH's parent, restarts it when she asks or when it exits on its own, and brings it back down a fallback ladder when a start fails.
- [`build_dsh_inline.mjs`](../../tools/build_dsh_inline.mjs) — Build the reviewed native rendering extension from the pinned commit of the Asuna branch on the DSH fork.
- [`check_dsh_release.py`](../../tools/check_dsh_release.py) — Read the public release tag without changing the project or global runtime.
- [`check_staged_secrets.py`](../../tools/check_staged_secrets.py) — Report paths only; never print configured secret values or matching bytes.
- [`cleanup_test_databases.py`](../../tools/cleanup_test_databases.py) — Inventory or remove only explicitly inventoried Asuna test databases.
- [`import_native_credentials.mjs`](../../tools/import_native_credentials.mjs) — One-time private migration through DSH's credential provider; never logs values.
- [`integration_import_offline_check.py`](../../tools/integration_import_offline_check.py) — 集成产物导入的离线自检：不需要 Mongo、不需要 pytest、不需要 WSL，直接跑同一套用例。
- [`make_demo_config.py`](../../tools/make_demo_config.py) — Create the ignored demo config (ADR-009 §0.3) from config/demo.example.json.
- [`outbound_image_offline_check.py`](../../tools/outbound_image_offline_check.py) — 出站图片附件（QQ 私聊 B 阶段第一步）的离线自检：不需要 Mongo、不需要 pytest、不联网、不发 QQ。
- [`p1c_offline_check.py`](../../tools/p1c_offline_check.py) — ADR-005 P1-c 离线自检：不需要 Mongo、不需要 pytest，直接跑同一套整理用例。
- [`p2_offline_check.py`](../../tools/p2_offline_check.py) — ADR-005 P2 离线自检：不需要 Mongo、不需要 pytest，直接跑摘要闭环那批用例。
- [`p3_offline_check.py`](../../tools/p3_offline_check.py) — ADR-005 P3 交付前自检：零依赖跑法，操作员不必起 Mongo、不必起 DSH、不必联网。
- [`p5_offline_check.py`](../../tools/p5_offline_check.py) — ADR-005 P5 离线自检：不需要 Mongo、不需要 pytest，直接跑话题追踪＋主动参与那批用例。
- [`pack_plugins.py`](../../tools/pack_plugins.py) — Build the core plugin and the persona and channel packages passed with --persona / --channel; no local state or secrets.
- [`probe_blob.py`](../../tools/probe_blob.py) — Probe of large-file storage on a real MongoDB: a synthetic blob over 1 MB goes into GridFS, wrong-scope and non-operator reads are refused, and deleting its memory removes it.
- [`probe_fresh_profile.mjs`](../../tools/probe_fresh_profile.mjs) — Sets up a brand-new DSH profile in an empty home that installs the packed or released tarballs with `dsh plugin add` and takes nothing else from this checkout.
- [`probe_host_seam.py`](../../tools/probe_host_seam.py) — --debug only: isolated host replay, fake cognition, real Mongo and loopback HTTP.
- [`probe_native_atomicity.mjs`](../../tools/probe_native_atomicity.mjs) — Probe of DSH's installed compaction: a cut through a tool call and its result, or a summary that fails, leaves the session's history and its saved log unchanged.
- [`probe_native_image.mjs`](../../tools/probe_native_image.mjs) — Probe of a picture in the action brain's native tool loop: `read_image` returns an image that DSH stores as an attachment, the next model request carries it, and a cold reload of the session replays it unchanged.
- [`probe_native_schedule.mjs`](../../tools/probe_native_schedule.mjs) — Probe of her reminders on DSH's own scheduler: a timer created through the scheduler session fires, reaches the worker boundary once without a model step, and is still recorded once after the session reloads.
- [`probe_plugin_install.mjs`](../../tools/probe_plugin_install.mjs) — Probe of a clean install: the packed tarballs go into a new DSH profile outside this checkout, and every core export and persona package resolves and imports through DSH's public resolver.
- [`probe_qq_admission.py`](../../tools/probe_qq_admission.py) — Offline adapter -> Core -> durable-state simulator.
- [`project_map.py`](../../tools/project_map.py) — Write the project map (docs/map): what each module owns and what it offers, from the code's own docstrings.
- [`release.py`](../../tools/release.py) — Build and check a GitHub Release of the distributable plugins (ADR-010 D10).
- [`setup_native_profile.py`](../../tools/setup_native_profile.py) — Install the core, one persona package and its channel packages into a local-only native Web profile.
<!-- /map:modules -->
