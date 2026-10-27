# Asuna Runtime API

The interfaces of the Asuna runtime: what a channel adapter, a persona or channel package, an operator and her own action brain can rely on, each with its fields, limits, answers and codes, and a pointer to the code that implements it. It describes interfaces, not how her turns run inside; for that the code is the reference, and each section names where. Installation and operation: [RUN_ASUNA.md](RUN_ASUNA.md), [INSTALL.md](INSTALL.md). The DSH services Asuna relies on: [packages/cognition-core/DSH_API.md](packages/cognition-core/DSH_API.md).

## Contents

- [Process layout](#process-layout)
- [Configuration](#configuration): [plugin settings](#plugin-settings), [model routes](#model-routes), [secrets](#secrets), [deployment settings](#deployment-settings)
- [Channel API](#channel-api): [server and endpoints](#server-and-endpoints), [channels and routes](#channels-and-routes), [admission](#admission), [route keys](#route-keys), [receive an event](#receive-an-event), [platform notices](#platform-notices), [post a notice for her home](#post-a-notice-for-her-home), [claim public output](#claim-public-output), [fetch attachment bytes](#fetch-attachment-bytes), [record a platform receipt](#record-a-platform-receipt), [post a group's member list](#post-a-groups-member-list), [post the current media-link keys](#post-the-current-media-link-keys), [post her own mute in a group](#post-her-own-mute-in-a-group), [post a voice](#post-a-voice), [HTTP outcomes](#http-outcomes)
- [Persona packages](#persona-packages): [persona model](#persona-model), [what she carries](#what-she-carries)
- [Channel packages](#channel-packages): [kind module](#kind-module)
- [Her tools](#her-tools)
- [Action capabilities](#action-capabilities): [tools a task is given](#tools-a-task-is-given), [web search and fetch](#web-search-and-fetch), [skills](#skills), [sandbox](#sandbox), [credentials](#credentials)
- [Media and images](#media-and-images): [inbound media](#inbound-media), [voice messages](#voice-messages), [reading images](#reading-images), [sending pictures](#sending-pictures), [sending files](#sending-files), [received files](#received-files), [erased media](#erased-media)
- [Schedules](#schedules): [rhythms](#rhythms), [what the owner sees](#what-the-owner-sees)
- [Integration and self-development](#integration-and-self-development): [integration profile](#integration-profile), [integration tools](#integration-tools), [drawing and rendering](#drawing-and-rendering), [private words](#private-words), [self-development](#self-development)

## Process layout

Where each part of Asuna runs. For anyone changing the code or writing a package.

| Part | Runs in | Owns | Code |
|---|---|---|---|
| Core plugin `asuna-cognition-core` | the DSH Web Host (Node) | native agents and sessions, presets, the settings card, the memory tab, the Python worker's life | `packages/cognition-core/src/index.js` |
| Publication floor (`asunaFloor`) | the DSH Web Host | the profile's data folder, published candidates and their activation | `packages/cognition-core/src/floor.js` |
| Business worker | a child process: `python -u -m asuna.native_worker` | `RuntimeHost`: the database, input and task queues, memory indexing and summaries, the [Channel API](#channel-api) server, the managed integration | `packages/cognition-core/src/worker.js`, `src/asuna/native_worker.py`, `src/asuna/host.py` |
| Persona packages | registered with the core plugin | a character's seeds, model, skills and preset | `packages/personas/<name>/`; contract in [Persona packages](#persona-packages) |
| Channel packages | registered with the core plugin; the adapter runs in the integration sandbox or in the Host | one platform's kind module and adapter | `packages/channels/<name>/`; contract in [Channel packages](#channel-packages) |

- The worker gets the profile's data folder as `ASUNA_DATA_ROOT` (a checkout's `.runtime` when unset). The folder is the floor's `dataRoot` setting, else `$DSH_HOME/asuna/<profile>/` (`paths.js` `dataRoot`). A deployment's private files are in `<data>/private/`.
- A worker that exits, and a start that fails, are tried again after 5, 15, 45 and 135 seconds and then every 5 minutes, never giving up; a start that succeeds clears the count. Each failed start writes an `Asuna worker could not start (attempt N)` line, and each restart is appended to `<data>/worker-restarts.jsonl` (`index.js` `ready`, `startAgain`, `workerFailed`, `restart`; delays `START_RETRY_SECONDS`).
- While her worker is down and the Host runs on (a start that failed, a worker that exited), the plugin keeps the open span in `<data>/worker-down.json` (`since`, `cause`, `tries`, `inside`), across retries and Host restarts. The worker reads the file at its start and never writes it. A completed start hands the span to the worker (`host.came_back`) without waiting for it, and again every 5 minutes while that worker runs until it is recorded (`HANDOVER_SECONDS`); the worker records one `host_stops` row with `how: worker_down`, and then the file is removed. A worker without that method (an older core candidate) leaves the file for a later one, and the row is written once whenever it is handed over. The plugin never fails a start over this file: a write is whole or not made (a temporary file renamed over it), and a failure is one `Asuna:` line in `restart/host.log`. A cause is a kind and a name only: `start_failed:<name>`, `exited:<code>` (`none` without one), `unknown`. While a span is open, a lease left behind is part of the same outage and writes no `killed` or `crashed` row; a Host stop that was not the worker's own exit is counted in the span's `inside`. Each `host_stops` row other than `planned` is one outage (`outage.js`, `host_stops.worker_down`).
- The plugin and the worker can run different versions: a core publication restarts only the worker, onto the selected core's `python/` (`floor.workerPath`), while the plugin stays the installed package. The worker's `initialize` takes no unknown key (no `**kwargs`), so a new `initialize` argument makes an older worker refuse every start (`TypeError: … unexpected keyword argument`). Anything new between the two goes where an older side passes it by: a file in the data folder, an extra key of an answer, or a new method whose `UNKNOWN_BUSINESS_METHOD` the caller survives.
- `host_from_program` (home turns) lists the outages of the last day and those no committed turn has shown yet, newest first, at most 3, with `count` and, when it lists fewer, `not_listed`; a listed outage whose record cannot be read is counted in `unreadable` instead of said, and the others are still said. An outage stays until a turn that showed it commits (`shown_at`, which says only that it was in that turn's context) and in any case for a day. It can say an outage only afterwards: while the worker is down, none of her turns runs. While it lasts, the settings card shows the worker's state and error. A planned stop keeps who marked it (`by`), and the restart block of the launcher start that followed names it (`host_stops`, `restarts.block`).
- Every inbound input is stored before any retrieval or model call (`src/asuna/ingress.py` `persist_input`).
- The DSH services, hooks, events and file formats the core plugin relies on are listed in `packages/cognition-core/DSH_API.md`.

## Configuration

The settings an operator gives a profile, and what each one does. For operators and for anyone adding a setting. How to install and apply them is in [RUN_ASUNA.md](RUN_ASUNA.md).

### Plugin settings

The core plugin's settings in the DSH profile (`packages/cognition-core/src/index.js` `Config`).

| Key | Default | Effect |
|---|---|---|
| `persona` | — | the persona package that runs (its `id`) |
| `python` | — | the Python that runs the worker |
| `mountSchedule` | `true` | `false`: without DSH's Schedule service her plans and rhythms are off; otherwise the worker waits for that service ([Schedules](#schedules)) |
| `voiceToText` | `true` | `false`: nothing is loaded and every voice reads `没转出文字：语音转写关着` ([Voice messages](#voice-messages)) |
| `videoDecoding` | `true` | `false`: nothing is loaded and `read_image` of a video says decoding is off ([Reading images](#reading-images)) |
| `channelAdmission` | `explicit` | `explicit` or `automatic` ([Admission](#admission)) |
| `deployment` | — | the worker's settings ([Deployment settings](#deployment-settings)) |
| `routes` | — | each brain's model ([Model routes](#model-routes)) |

### Model routes

Each route picks a DSH provider and model from DSH's catalog. Asuna has no model settings of its own: `config/local.json` naming `character` or `executor` is refused (`MODEL_ROUTES_ARE_DSH_PROVIDERS`).

| Route | Used for | When unset |
|---|---|---|
| `character` | every turn of hers, and her relevance gate | DSH's default model (`agentDefaultModel`) |
| `action` | the action brain | DSH's default model |
| `actionHigh` | the action brain's second tier, chosen per task | off |
| `appraiser` | the affect appraiser | off |

| Field | Routes | Meaning |
|---|---|---|
| `provider`, `model` | all | a provider and one of its models in DSH's catalog |
| `reasoningEffort` | all | one of the levels DSH reports for the model; empty: the model's default |
| `maxTokens` | all | output limit; empty: the model's default; must be ≥ 1 and below the context window |
| `attendEffort` | `character` | effort of the relevance gate; empty: the route's own |
| `groupEffort` | `character` | effort of her group turns; empty: the route's own |
| `summaryEffort` | `action` | effort of her background dialogue summaries (one-request sessions); empty: the route's own |
| `idleMinutes` | `action`, `actionHigh` | after this long unused, a task's continuation starts a fresh action context (empty: 30); on `actionHigh` also how long the tier rests after its line fails |

| Refusal | When |
|---|---|
| `MODEL_NOT_CONFIGURED: <route>` | a used route has no provider, or its model is not in the provider's catalog |
| `INVALID_OUTPUT_LIMIT: <route>` | `maxTokens` is not a whole number ≥ 1 below the context window |
| `INVALID_REASONING_EFFORT: <route>` | an effort the model does not offer |

### Secrets

A setting whose key contains `mongo_uri`, `api_key`, `apikey`, `token`, `password` or `secret` (any case) holds a reference, `{"$secret": "ASUNA_MONGO_URI"}`, never a value. The name matches `^[A-Za-z_][A-Za-z0-9_]*$`; the value lives only in DSH's credential store (`packages/cognition-core/src/settings.js` `assertSecretReferences`).

| Refusal | When |
|---|---|
| `USE_NATIVE_SECRET_REFERENCE: <path>` | a secret key holds a value instead of a reference |
| `INVALID_CREDENTIAL_REFERENCE: <path>` | the reference's name is not an environment-variable name |
| `CREDENTIAL_NOT_CONFIGURED: <name>` | the store has no value for a reference |

### Deployment settings

Checked when the worker starts or a proposal is validated (`src/asuna/native_settings.py` `runtime_settings`).

| Key | Default | Effect |
|---|---|---|
| `database` | required | MongoDB database; must be in `allowed_databases` (`DATABASE_NOT_AUTHORIZED`) |
| `mongo_uri` | required | MongoDB address (a secret) |
| `allowed_databases` | `[database]` | databases this profile may open |
| `embedding.base_url` | required | embedding service, an http or https URL with a host (`INVALID_ENDPOINT`) |
| `embedding.model` | required | embedding model (`EMBEDDING_MODEL_REQUIRED`) |
| `chat.scene_id`, `chat.person_id`, `chat.persona` | `local`, `owner`, the selected persona | the local chat: its scene, the owner's person id, the persona |
| `channels` | none | configured channels ([Channel API](#channel-api)) |
| `channel_port` | `8766` | channel server port, 1024–65535 (`INVALID_CHANNEL_PORT`) |
| `active_groups` | `4` | the usual number of active groups, 1–100 (`INVALID_ACTIVE_GROUPS`) |
| `thoughts` | `tool` | where her 心里话 come from: `tool`, her `think` call, first in every turn; `thinking`, the summary of the character model's own first thinking in the turn, recorded by the program, shown cut at 120 characters and marked as another model's summary (`INVALID_THOUGHTS`). `thinking` needs a character route and group effort with a thinking level (`THOUGHTS_NEED_THINKING`); a conversation opened in the other mode continues in a new session at its next turn. In either mode, a turn that does not ask for her thought leaves one audit row once its first stage ends: `thought.taken`, or `thought.none` with its `why` (`no_thinking`, `redacted`, `capture_failed`, or `not_carried` when no call carried the model's thinking); her week's `thoughts` reading shows them whenever there are some, as the program's capture |
| `provider_idle_timeout_seconds` | `1800` | read timeout of a model request, 1–86,400 (`INVALID_TIMEOUT`) |
| `workflow_timeout_seconds` | `1800` | how long one native stage may run before it is fenced, 1–86,400 (`INVALID_TIMEOUT`) |
| `sandbox.backend` | `auto` | `auto` or `none` ([Sandbox](#sandbox)) |
| `home_groups` | none | group scene ids that read as home (owner-private) and are still groups (`visibility.home_group`) |
| `timezone` | UTC | IANA time zone of her rhythms when her policy names none |
| `context_links`, route `read_scenes` | none | read-only links between scenes (`src/asuna/scene_links.py`) |
| `canonical_persons` | none | person id → canonical person (`src/asuna/scene_links.py`) |
| `persona_runtime.<persona>.heartbeat_target` | none (no heartbeat) | the owner-private scene her heartbeat runs in |
| `persona_runtime.<persona>.internal_scene` | the local chat | the owner-private scene her settlement and condensing plans run in |
| `persona_runtime.<persona>.export_dir` | none | where the Web UI's document export writes her documents (`EXPORT_DIR_NOT_CONFIGURED`) |
| `self_development.enabled` | `false` | her self-improvement turns and the development grant ([Self-development](#self-development)) |
| `character_git` | none | `{name, email}` on the commits her commands and publications make |
| `vision` | — | image fetching ([Media and images](#media-and-images)) |
| `search` | — | the web search order ([Action capabilities](#action-capabilities)) |
| `integration` | off | the managed integration ([Integration and self-development](#integration-and-self-development)) |

A route of a channel that names no workspace gets `<data>/channels/<channel>-<route>` (a group member's: `/<sender>` below it).

## Channel API

The HTTP interface a channel adapter uses to hand platform events to her and to send her words out. For adapter and channel-package authors. Server: `src/asuna/channels.py` (`Channels`, `ChannelServer`).

### Server and endpoints

When any channel is configured, the worker serves the channel API on `127.0.0.1` at `channel_port` (default `8766`). It is not reachable through the Web UI's proxy.

| Method and path | Purpose | Body limit |
|---|---|---|
| `POST /v1/channels/{channel_id}/events` | [Receive an event](#receive-an-event) | 256 KiB |
| `POST /v1/channels/{channel_id}/notices` | [Post a notice for her home](#post-a-notice-for-her-home) | 256 KiB |
| `GET /v1/channels/{channel_id}/outbox` | [Claim public output](#claim-public-output) | — |
| `GET /v1/channels/{channel_id}/outbox/{publication_id}/attachment` | [Fetch attachment bytes](#fetch-attachment-bytes) | — |
| `POST /v1/channels/{channel_id}/outbox/{publication_id}/receipt` | [Record a platform receipt](#record-a-platform-receipt) | 256 KiB |
| `POST /v1/channels/{channel_id}/members` | [Post a group's member list](#post-a-groups-member-list) | 4 MiB |
| `POST /v1/channels/{channel_id}/media_keys` | [Post the current media-link keys](#post-the-current-media-link-keys) | 256 KiB |
| `POST /v1/channels/{channel_id}/faults` | [Post the lanes' fault counts](#post-the-lanes-fault-counts) | 256 KiB |
| `POST /v1/channels/{channel_id}/own_mute` | [Post her own mute in a group](#post-her-own-mute-in-a-group) | 256 KiB |
| `POST /v1/channels/{channel_id}/voice` | [Post a voice](#post-a-voice) | 64 MiB of audio bytes |

- Every request carries `Authorization: Bearer <token>`: the channel's token, or a [route key](#route-keys).
- A POST body is one JSON object, except a voice's audio bytes on `voice`. Unknown fields are refused on `events`, `notices`, `own_mute`, `voice`, `faults` and `receipt`; `members` and `media_keys` ignore them.
- A refusal is `{"error": "<CODE>"}`, often followed by `: ` and words for the reader; the status is in [HTTP outcomes](#http-outcomes).

### Channels and routes

A channel is `deployment.channels.<kind>`: its id is the platform kind of an installed [channel package](#channel-packages) (`CHANNEL_KIND_NOT_INSTALLED` otherwise).

| Channel field | Meaning |
|---|---|
| `account_id` | the platform account she uses (required, `CHANNEL_ACCOUNT_REQUIRED`) |
| `token` | bearer token: ASCII, at least 24 characters, unique across channels |
| `routes` | route id → route |
| `blocked_senders`, `blocked_groups` | platform accounts and groups refused at intake and in the outbox (`INVALID_CHANNEL_BLOCK_LIST` when not account ids) |

| Route field | Meaning |
|---|---|
| `scene_id` | her conversation for this target; distinct across routes and from the local chat |
| `target` | `{"type": "dm" | "group", "id": …}`; one route per target |
| `sender_id`, `person_id`, `workspace` | a `dm` route's one speaker, Asuna person and working folder (`target.id` equals `sender_id`) |
| `members` | a `group` route's speakers: `{sender_id: {person_id, workspace, read_only_paths}}` |
| `display_name` | a `dm` route's name for its speaker, 1–40 characters, set on the person's identity at start |
| `read_scenes` | scenes this route's conversation may read ([Deployment settings](#deployment-settings)) |
| `admin_actions` | `false` turns off her admin actions in that group (default on) |
| `proactive` | the group's rules for speaking unprompted (`src/asuna/proactive.py`) |
| `developer` | `true` marks the home line her questions to the developer go to |

A workspace must be an absolute path under `<data>/channels`; overlapping workspaces and conflicting bindings are refused at start (`src/asuna/host.py` `prepare_channels`).

### Admission

| `channelAdmission` | Unknown DM, group or member |
|---|---|
| `explicit` (default) | refused (`CHANNEL_IDENTITY_DENIED`) |
| `automatic` | admitted on its first valid event; the adapter sends the route id `auto-dm-<sender>` or `auto-group-<group>` |

An admission is kept in `artifacts` (kind `channel_admission`) and restored at start. An admitted member gets a workspace under `<data>/channels` and no owner grants; admitting a group member does not change the group's policy epoch. A target that already has a route keeps it (`CHANNEL_TARGET_ALREADY_BOUND` for a second). Admission refusals: `CHANNEL_SENDER_INVALID`, `CHANNEL_BLOCKED`, `CHANNEL_GROUP_DENIED`, `CHANNEL_ROUTE_NOT_AUTHORIZED` (`src/asuna/channel_admission.py`).

### Route keys

A channel kind that declares `ROUTE_KEYS` (the `agent` kind) also accepts a key per route: `route-<route>.<hex>`, the HMAC-SHA256 of `asuna-route-key:<route>` under the channel's token (`channels.route_key`). At start the worker writes each key to `<data>/private/route-keys/<channel>-<route>.json` (`url`, `route_id`, `account_id`, `sender_id`, `key`) and removes files of routes no longer configured.

| Endpoint | With a route key |
|---|---|
| `POST …/events` | only with its own `route_id` (`ROUTE_KEY_OTHER_ROUTE`) |
| `GET …/outbox` | only its own line's messages; admin actions are never handed out |
| `POST …/outbox/{id}/receipt` | only for its own line's messages (`ROUTE_KEY_OTHER_ROUTE`) |
| any other | `ROUTE_KEY_ENDPOINT_DENIED` |

- While she keeps the line closed (`PEER_LINE`), a claim answers `{"items": [], "line": "closed"}` and her words wait.
- On a kind that declares `OWNER_JOINS`, a claim on an open line also returns `owner_lines`: what the owner wrote there from the Web, each once, oldest first, at most 20 a claim, as `{"id", "seq", "text", "at"}` (`seq`: its place in the conversation). Such a claim does not wait.

### Receive an event

`POST /v1/channels/{channel_id}/events` — one platform message or notice.

```json
{"route_id": "authorized-dm", "account_id": "configured-account", "sender_id": "configured-sender",
 "event_id": "platform-event-id", "text": "Message text", "occurred_at": "2026-01-01T00:00:00Z"}
```

| Field | Type | Required | Limit | Meaning |
|---|---|---|---|---|
| `route_id` | string | yes | — | the route (or `auto-…` id) |
| `account_id` | string | yes | — | must be the channel's `account_id` |
| `sender_id` | string | yes | — | the speaker's platform account; must be a member of the route |
| `event_id` | string | yes | 1–200 | the platform's message id |
| `text` | string | yes | 1–16,000 | the message as text |
| `occurred_at` | string | no | — | the platform's send time (ISO 8601); omit when unknown, never the forwarding time |
| `group_id` | string | group routes | — | must be the route's group; refused on a `dm` route |
| `mentioned_account_ids` | string[] | no | ≤ 100 | accounts the message @-mentions; refused on a `dm` route |
| `reply_to` | string | no | 1–200 | platform id of the line it quotes |
| `raw` | object | no | — | the adapter's normalized extras, below; anything else in it is dropped |

| `raw` key | Shape | Meaning |
|---|---|---|
| `asuna_peer` | profile object | the sender's profile, kept only when it matches the authenticated sender and group (`peer_context.snapshot_event`) |
| `asuna_mentioned` | profile objects | profiles of mentioned accounts, at most 10, each in `mentioned_account_ids` and this group (`peer_context.snapshot_mentioned`) |
| `asuna_media` | `{"items": [...]}` | pictures, videos and other media ([Inbound media](#inbound-media)) |
| `asuna_forward` | blocks | a merged forward: at most 3 blocks `{ref: "f" + 8 hex, nodes, source}`, at most 100 nodes `{name, user_id, time, text}` of 500 characters (`forwards.kept`) |
| `group_name` | string | the group's name (kept to 60 characters) |
| `asuna_catchup` | `{reason, fetched_at}` | a line fetched from the platform's history after a gap; `reason` `startup` or `reconnect` |
| `asuna_reply_only` | `true` | the message only quotes another, with no words of its own |
| `asuna_aside` | `true` | a line not addressed to her: stored, wakes no one |
| `asuna_answer` | `{"question": "q-<8 hex>"}` | on a home line: the line answers that question of hers |
| `asuna_self` | `{"role": "owner" | "admin" | "member"}` | her own role in this group (group events only) |
| `asuna_notice` | object | a platform notice ([Platform notices](#platform-notices)) |

| Answer | Meaning |
|---|---|
| `{"status": "accepted", "episode_id", "received_at"}` | stored before any model call, and queued; not a reply |
| `{"status": "duplicate", "episode_id", "received_at"}` | the same event again; nothing new is queued |
| `{"status": "line_closed"}` | a peer line she closed; nothing is kept |
| `{"status": "held"}` | a group notice kept for her next turn there |
| `{"status": "dropped"}` | a notice from someone she blocked |

| Code | Status | When |
|---|---|---|
| `CHANNEL_ENVELOPE_FIELD_DENIED` | 403 | a field outside the table |
| `INVALID_PLATFORM_EVENT_ID`, `INVALID_MESSAGE_TEXT`, `INVALID_OCCURRED_AT`, `INVALID_MENTIONS`, `INVALID_REPLY_ID` | 400 | a field outside its type or limit |
| `DM_GROUP_FIELDS_DENIED` | 403 | `group_id` or `mentioned_account_ids` on a `dm` route |
| `CHANNEL_IDENTITY_DENIED` | 403 | unknown route or member, or the wrong `account_id` |
| `CHANNEL_GROUP_DENIED` | 403 | `group_id` is not the route's group |
| `INPUT_IDENTITY_OR_CONTENT_CONFLICT` | 403 | an event id reused with other content |
| `HOST_RECONFIGURING`, `HOST_STOPPING`, `HOST_DATABASE_UNAVAILABLE` | 503 | the whole Host: settings are being applied, the worker is stopping, or its database is out of reach; ask again later, it is no fault of the request |
| `HOST_REQUEST_FAILED` | 500 | this request failed in the worker; a redacted diagnostic is recorded (`host.channel_error`) |

- **Identity.** An event is the channel, account, route scene and `event_id`, plus `occurred_at` when given: the same id and time again is a redelivery; the same id at another time is a new message.
- **Quotes.** `reply_to` binds, within the conversation and its policy epoch, to the newest received line with that platform id, or her delivered line with that platform message id, no later than `occurred_at`.
- **Addressed to her.** `mentioned_account_ids` containing the channel's `account_id`, or `reply_to` naming her delivered line, addresses her. A caught-up line older than 300 seconds (`caught_up.STALE_SECONDS`) does not wake her by itself. Which lines of a group wake her is decided in `src/asuna/channels.py` (`group_context`), `src/asuna/focus.py` and `src/asuna/attend.py`. An addressed line, like unaddressed talk, is asked at her relevance gate (`attend.GATED`), unless it is from the person she is waiting on or inside her open question's wait (`group_context.answers_her`, set at intake; `attend.gated`), when it runs the full turn at once. A gate verdict of 不理 on an addressed line leaves it in the group for her next turn (`processing_outcome` `ATTEND_QUIET`, the verdict and her reason on the message and in the audit as `attend.verdict`); a gate that fails on one runs the full turn (`attend.fallback` in the audit).
- **People.** An admitted speaker's person id is the kind's `person_id(account)`.
- **Her conversation.** The core plugin writes each accepted line into her native conversation before any turn runs (`packages/cognition-core/src/navigation.js` `recordChannelInput`). The Web composer is view-only in platform conversations, except on a kind that declares `OWNER_JOINS`, where it posts as the owner.

#### Platform notices

A recall, a poke, a reaction and the like come as an event from the person who did it: its `text` is the adapter's words, and `raw.asuna_notice` says what it is.

| `asuna_notice` field | Meaning |
|---|---|
| `kind` | the adapter's name for it, 1–40 characters (required) |
| `gate` | `poked` (someone poked her) or `reacted` (someone reacted to her line): asks her to look |
| `line` | `{"message_id", "mine"}`: the platform id (≤ 40 characters) of the line it is about, `mine` when it is hers |

- `{line}` in `text` is replaced by the host with that line as every pointer names it (`People.pointed`): her line however old, anyone's from the last day, else `一条消息`.
- `reacted` on a line that is not hers loses its gate.
- In a group, a notice with a gate goes to her relevance gate; one without is kept (`artifacts` kind `held_notice`, at most 50 per conversation, kept across restarts) and shown once at her next turn there: the answer is `{"status": "held"}`.
- In a private chat a notice is that chat's input, like a message.

### Post a notice for her home

`POST /v1/channels/{channel_id}/notices` — a notice about her own account, or a request she answers: a friend or group request, a kick, a change of her admin role.

```json
{"kind": "request_friend", "words": "想加你好友，附言「你好」", "actor_name": "name",
 "request": {"flag": "platform-flag", "type": "friend"}}
```

| Field | Type | Required | Limit | Meaning |
|---|---|---|---|---|
| `kind` | string | yes | 1–40 | the adapter's name for it |
| `words` | string | yes | 1–200 | what happened; `{g}` is replaced by the group's name |
| `actor_name` | string | no | 30 | who did it, shown in 「」 before `words` |
| `group_id` | string | no | — | the group, for `{g}` (her conversation's name when routed) |
| `group_name` | string | no | 30 | the group's name when it is not routed |
| `at` | integer | no | > 0 | platform epoch seconds |
| `request` | object | no | — | `{flag (1–200), type: "friend" | "group", sub_type: "add" | "invite" (group)}` |

| Answer or code | Status | Meaning |
|---|---|---|
| `{"status": "held"}` | 200 | kept; within a minute one program event in her local chat lists what came |
| `NOTICE_FIELD_DENIED` | 403 | a field outside the table |
| `NOTICE_INVALID` | 400 | `kind`, `words` or `request` out of shape |

- A request is kept in `artifacts` (kind `platform_request`, one row per `flag`) with a number `请求N` that is never reused, and listed again at each start while open.
- Her answer comes out of the [outbox](#claim-public-output) as an admin action with target `{"type": "request", "id": "friend" | "group"}` and `admin` `{"kind": "accept" | "decline", "flag", "request", "sub_type"}`. Its receipt marks the request `answered` (accepted), `gone` (failed) or `unknown`.
- Accepting admits nobody: who may talk to her is the channel's [admission](#admission).

### Claim public output

`GET /v1/channels/{channel_id}/outbox?wait_seconds=25&supports=image,sticker` — claims the next item to send.

| Query | Meaning |
|---|---|
| `wait_seconds` | long-poll up to this many seconds (0–25; default 0) |
| `lane` | `chat`: every item but files; `bulk`: files only; none named: one lane for everything (an adapter that claims one item at a time). An adapter that declares `file` and claims `chat` and `bulk` sends files on a lane of their own, so an upload holds no message; one that does not declare `file` meets file rows on `chat` and fails them (`CHANNEL_DOES_NOT_DECLARE_FILE`). The answer names the lane it served (`"lane"`) |
| `supports` | comma-separated capabilities the adapter carries now (below); an entry `name:<bytes>` also declares the largest size the platform takes, as `file:4096` (4 KiB) |

| `supports` name | Means the adapter |
|---|---|
| `image` | sends a picture with a message ([attachment](#fetch-attachment-bytes)) |
| `sticker` | sends stickers |
| `file:<bytes>` | sends a file to a group, up to that many bytes ([file pieces](#fetch-attachment-bytes)) |
| `poke`, `react`, `recall` | performs that action (`recall` also: her line can be taken back) |
| `quote` | shows the line she quotes |
| `quote_in`, `react_in` | passes on what others quote, and reactions |
| `voice_in` | settles each voice of a line before posting the line ([post a voice](#post-a-voice)) |

The answer is `{"items": [], "lane": …}` or `{"items": [item], "lane": …}`. Each claim marks the item `SENDING` under a fresh `attempt_id`; claiming is not delivery. An adapter may claim again before the last item settles: on the `chat` lane a conversation with a chat item `SENDING` is held (claimed within the last 300 s, `CHAT_LEASE_SECONDS`; one out longer stays `SENDING` for its receipt but holds nothing), so two chat items of one conversation are never out at once. A file holds nothing while it is on its way: the parts of a reply after it are handed out without waiting for its upload; it waits for the parts before it; one that failed cancels the parts after it that have not gone, as any failed part does. Group admin actions go one at a time per channel, in the order they were chosen.

| Item field | Meaning |
|---|---|
| `publication_id`, `attempt_id` | what to name in the receipt |
| `target` | `{"type": "dm" | "group", "id"}` to send to |
| `text` | her words; her @ of someone reads `@<kind>:<account>` (the kind's `outbound_mention`), `[表情:名字]` is a platform face by name; `""` for a sticker, a file or an action |
| `reply_to` | platform id of the line her words answer, for a platform that needs a reply token; never shown as a quote |
| `quote` | platform id of the line she chose to quote, or `null`; shown only by an adapter that declares `quote` |
| `attachment` | `{artifact_id, media_type, sha256, size}` when `image` is declared and the message carries a picture |
| `sticker` | `{"kind": "custom"}` (send `attachment` as a picture marked as a sticker) or `{"kind": "market", "emoji_id", "emoji_package_id", "key", "summary"}` (a store sticker, no bytes) |
| `file` | `{artifact_id, name, media_type, sha256, size}`: a file sent alone to a group, under `name`; `media_type` is `null` when its type was not recognized |
| `action` | `{"kind": "poke", "account"}`, `{"kind": "react", "message_id", "emoji_id"}` or `{"kind": "recall", "message_id", "line"}` |
| `admin` | an admin action (publication id `ga-…`, no `text`): `{"kind": "mute", "account", "seconds"}`, `unmute` or `kick` with `account`, `recall` with `message_id`, or a request's `accept` / `decline` |

- **Order.** A claim with the channel's token gets queued admin actions first. Conversations take turns by when their oldest queued message was queued (`queued_at`); within a conversation, messages come in its order. A part with `not_before` waits for its time, and a later part of one reply waits until the part before it is delivered (or she cancelled it); either holds only its own conversation. A part whose earlier part ended without arriving is cancelled when it comes up (`CANCELLED_AFTER_FAILURE`).
- **Speaking in parts.** Where a kind declares `REPLY_PARTS`, one reply is several items, each sent as its own platform message and confirmed with its own receipt. A part that ends `failed` or `unknown` cancels the parts after it (`CANCELLED_AFTER_FAILURE`). A `recall` action takes back her own delivered line.
- **Not declared.** An action the claim does not declare fails its row (`CHANNEL_DOES_NOT_DECLARE_POKE`, `…_REACT`, `…_RECALL`); a sticker fails with `CHANNEL_DOES_NOT_DECLARE_STICKER`, a file with `CHANNEL_DOES_NOT_DECLARE_FILE`. A picture without `image` declared: the text goes out and the row records `attachment_skipped`.
- **Files.** A file row fails at claim time, before anything is sent, with `FILE_OVER_CHANNEL_LIMIT` (over the declared `file:<bytes>`; the row keeps `file_limit` `{bytes, limit}`) `FILE_BYTES_EXPIRED` (its bytes were removed; the row keeps `source_present`, whether the task folder still holds the original), or `FILE_ERASED` (a privacy erasure deleted its bytes, [Erased media](#erased-media)). Each row carries `failure_detail` in words.
- **Kept.** The host keeps each channel's last `supports` (`artifacts` kind `channel_capabilities`) across restarts; what she is offered there follows it (`src/asuna/capabilities.py`).
- A row whose route, member, policy epoch or task changed since it was queued is failed at claim time and not handed out (`PUBLICATION_MEMBER_REVOKED`, `PUBLICATION_CONTEXT_STALE`, `PUBLICATION_EPISODE_STALE`, `PUBLICATION_INTENT_STALE`).

### Fetch attachment bytes

`GET /v1/channels/{channel_id}/outbox/{publication_id}/attachment?attempt_id=…&artifact_id=…` — the bytes of the picture a claimed item declared, with the channel's token. For a claimed `file`, one piece of it: `&offset=…&length=…`.

| Query | Required | Meaning |
|---|---|---|
| `attempt_id` | yes | the attempt of the current claim |
| `artifact_id` | no | narrows the request; a different artifact is refused, never substituted |
| `offset`, `length` | for a file | the piece: `length` bytes (1 to 8 MiB) from byte `offset`, fewer only at the file's end |

The answer is the bytes with `Content-Type` from their file signature, re-checked against the row's `sha256`. The adapter checks the digest and signature again; only a platform receipt says the picture arrived.

A file's piece is `application/octet-stream`. The host does not hash a piece: the adapter checks the whole file's `sha256` across its pieces. A piece outside the file, or longer than 8 MiB, is 400 `FILE_PIECE_INVALID`. A file's other refusals (403): `FILE_NOT_DECLARED`, `FILE_ARTIFACT_UNAVAILABLE`, `FILE_BYTES_EXPIRED` (its bytes were removed), `FILE_SHA_MISMATCH` (the stored file is not the declared one). A picture or file a privacy erasure deleted after the claim is 403 `ARTIFACT_ERASED`, followed by its sentence.

| Code (all 403, no partial body) | When |
|---|---|
| `PUBLICATION_NOT_FOUND` | no such publication on this channel |
| `PUBLICATION_ATTEMPT_MISMATCH` | not `SENDING`, or another attempt |
| `ATTACHMENT_NOT_DECLARED` | the claim carried no picture (also after `attachment_skipped`) |
| `ATTACHMENT_ARTIFACT_DENIED` | `artifact_id` is not the declared one |
| `ATTACHMENT_ARTIFACT_UNAVAILABLE` | the stored picture is missing |
| `ATTACHMENT_NOT_HER_OWN` | a picture she did not make, where only her own may go |
| `ATTACHMENT_SCOPE_DENIED` | outside what that conversation may send |
| `ATTACHMENT_HASH_MISMATCH`, `ATTACHMENT_SHA_MISMATCH` | stored bytes differ from their digest |
| `ATTACHMENT_OVER_LIMIT` | over 8 MiB |
| `ATTACHMENT_NOT_AN_IMAGE`, `ATTACHMENT_MEDIA_TYPE_MISMATCH` | not a PNG, JPEG, WebP or GIF, or not the declared type |

Implemented in `src/asuna/outbound_media.py` (`serve`) and `src/asuna/outbound_files.py` (`serve_piece`).

### Record a platform receipt

`POST /v1/channels/{channel_id}/outbox/{publication_id}/receipt` — what the platform did with a claimed item.

```json
{"attempt_id": "claimed-attempt-id", "status": "platform_accepted",
 "platform_message_id": "platform-message-id", "response": {"platform": "response"}}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `attempt_id` | string | yes | the claim's attempt |
| `status` | string | yes | `platform_accepted`, `failed` or `unknown` |
| `platform_message_id` | string | for `platform_accepted` of a message | the platform's id of the sent message; not for a file, an action or an admin action |
| `response` | object | yes | the platform's answer; `failed` with `"reason": "muted"` records her mute ([own mute](#post-her-own-mute-in-a-group)) |

| Answer or code | Status | Meaning |
|---|---|---|
| `{"status": "DELIVERED" | "FAILED" | "UNKNOWN"}` | 200 | the message's state (`delivery_basis` `platform_ack` when delivered) |
| `{"status": "DONE" | "FAILED" | "UNKNOWN"}` | 200 | an admin action's state |
| `RECEIPT_FIELD_DENIED` | 403 | a field outside the table |
| `INVALID_PLATFORM_RECEIPT` | 400 | unknown `status`, or `response` not an object |
| `PLATFORM_MESSAGE_ID_REQUIRED` | 400 | `platform_accepted` of a message without an id |
| `PUBLICATION_NOT_FOUND`, `PUBLICATION_ATTEMPT_MISMATCH` | 403 | unknown publication or attempt |
| `PUBLICATION_RECEIPT_CONFLICT` | 403 | the item already has another final receipt |

- `platform_accepted` means the platform took it, not that anyone read it.
- The same receipt again answers the same state. A receipt may still settle an `UNKNOWN` item.
- Send `unknown` when the result cannot be known. A worker restart turns every `SENDING` item into `UNKNOWN`; the host never claims it again.
- A delivered `recall` action marks her line as taken back.
- A delivered file keeps its bytes 7 days from then ([Sending files](#sending-files)). A file's `failed` receipt names the platform's words in `response.platform`; her record shows them.

### Post a group's member list

`POST /v1/channels/{channel_id}/members` — the whole member list of one admitted group, replacing the last one.

```json
{"group_id": "group-id", "fetched_at": "2026-10-08T00:00:00Z",
 "members": [{"user_id": "10001", "nickname": "name", "card": "group card", "role": "member",
              "last_sent_time": 1791000000, "join_time": 1780000000}]}
```

| Field | Type | Required | Limit | Meaning |
|---|---|---|---|---|
| `group_id` | string | yes | — | a routed group that is not blocked |
| `fetched_at` | string | no | 40 | when the adapter read the list |
| `members` | object[] | yes | 1–5,000 | one per member; one whose `user_id` is not a platform account is dropped |
| `members[].user_id` | string | yes | — | platform account |
| `members[].nickname`, `members[].card` | string | no | 60 | names |
| `members[].role` | string | no | — | `owner`, `admin` or `member` (anything else reads `member`) |
| `members[].last_sent_time`, `members[].join_time` | integer | no | ≥ 0 | platform epoch seconds |

| Answer or code | Status | Meaning |
|---|---|---|
| `{"status": "stored", "count": n}` | 200 | kept in `group_members`, one row per group |
| `MEMBERS_GROUP_NOT_ROUTED` | 403 | no admitted route for the group, or it is blocked |
| `MEMBERS_SCENE_UNKNOWN` | 403 | no conversation for the group yet |
| `MEMBERS_INVALID` | 400 | `members` missing or outside 1–5,000 |

What she reads of it is in `src/asuna/group_members.py` (`block`, `find`).

### Post the current media-link keys

`POST /v1/channels/{channel_id}/media_keys` — the keys a platform signs its media links with (QQ: `rkey`), so a stored link can be signed again before it is fetched.

```json
{"keys": [{"name": "qq-group", "key": "…", "seconds": 3000}, {"name": "qq-private", "key": "…", "seconds": 3000}]}
```

| Field | Type | Limit | Meaning |
|---|---|---|---|
| `keys` | object[] | 1–8 | the current keys |
| `keys[].name` | string | — | a name the channel kind declares in `MEDIA_KEYS` (QQ: `qq-group`, `qq-private`) |
| `keys[].key` | string | 1–1,024 | printable, without `&` |
| `keys[].seconds` | integer | 60–86,400 | how long it still lasts |

| Answer or code | Status | Meaning |
|---|---|---|
| `{"status": "stored", "names": [...]}` | 200 | kept; the answer never repeats a key |
| `MEDIA_KEYS_INVALID`, `MEDIA_KEY_NAME_DENIED`, `MEDIA_KEY_INVALID`, `MEDIA_KEY_SECONDS_INVALID` | 400 | out of shape |

Keys live only in the worker's memory: never in the database, the audit or a log. A key within 30 seconds of its end is not used. A signed link in an inbound event also gives its key for 300 seconds (`media_keys.LINK_KEY_SECONDS`), unless the adapter's key of that name still lasts. Post the keys again after a restart.

### Post the lanes' fault counts

`POST /v1/channels/{channel_id}/faults` — how often each kind of fault happened in the adapter's lanes, by signature and hour; never the line or the item itself.

```json
{"counts": [{"lane": "inbound", "stage": "post", "error": "host_error:500", "hour": "2026-10-23T05", "count": 2}]}
```

| Field | Meaning |
|---|---|
| `lane` | `inbound`, `chat`, `bulk` or `receipts` |
| `stage` | where in the lane (`post`, `spool`, `send`, `replay`) |
| `error` | the class of the fault (a reason, a status and an error code, an exception's class), never words |
| `hour` | the UTC hour it happened in, `YYYY-MM-DDTHH`, within the last 30 days |
| `count` | 1–100000 |

`lane`, `stage` and `error` are names: 1–80 characters of `A–Z a–z 0–9 _ . : -`. At most 200 rows a post, counted all together or not at all. The answer is `{"status": "recorded", "rows": n}`; the counts are added to what the hour already has (`src/asuna/lane_faults.py`), and an hour's counts are kept 30 days. Counts are at least once: a post re-sent after its answer was lost counts again in the same hour.

### Post her own mute in a group

`POST /v1/channels/{channel_id}/own_mute` — whether her account is muted in one admitted group.

```json
{"group_id": "group-id", "source": "notice", "muted": true, "whole_group": false, "operator_id": "10001"}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `group_id` | string | yes | a routed group that is not blocked |
| `source` | string | yes | `notice` (the platform just said so) or `lookup` (the adapter read her state; no mute found clears any) |
| `muted` | boolean | yes | muted or lifted |
| `whole_group` | boolean | no | a whole-group mute (default `false`) |
| `until` | integer | no | when it ends, platform epoch seconds; omit when unknown |
| `at` | integer | no | when it began, platform epoch seconds |
| `operator_id` | string | no | the platform account that did it |

| Answer or code | Status | Meaning |
|---|---|---|
| `{"status": "muted" | "cleared" | "unchanged" | "not_her"}` | 200 | `not_her`: a whole-group mute in a group where she is owner or admin |
| `OWN_MUTE_GROUP_NOT_ROUTED`, `OWN_MUTE_SCENE_UNKNOWN`, `OWN_MUTE_FIELD_DENIED` | 403 | as for members; a field outside the table |
| `OWN_MUTE_INVALID` | 400 | out of shape |

- One row per group in `own_mutes`. A notice that lifts one kind (hers, the whole group's) leaves the other; the row ends by itself when `until` passes.
- A `failed` receipt with `response.reason` `muted` records a mute when none is known; a `platform_accepted` receipt in that group clears it.
- A send is always attempted, muted or not. What she reads of it is in `src/asuna/own_mute.py`.

### Post a voice

`POST /v1/channels/{channel_id}/voice` — one voice segment of a line, before the line is posted: its audio bytes as
the body (`Content-Type` the media type, e.g. `audio/mpeg`) and the line's event in the query:
`…/voice?route_id=g&event_id=5301&index=0&occurred_at=2026-10-23T01%3A00%3A00Z`. The worker transcribes it within
the request and answers with the outcome; the line, posted to `events` next with the same `route_id`, `event_id` and
`occurred_at`, is stored with it. The query and a route key are checked before the audio is read; a refused post's
body is read and dropped, then answered.

| Query | Required | Meaning |
|---|---|---|
| `route_id`, `event_id`, `occurred_at` | `occurred_at` only when the event has it | the line's event, exactly as it will be posted to `events` (a route admitted by that event counts) |
| `index` | yes | which voice of the line, 0–63, in the order of its voice placeholders |

| Answer or code | Status | Meaning |
|---|---|---|
| `{"status": "settled", "state": "…", "seconds": n}` | 200 | transcribed now; `state` is one of [Voice messages](#voice-messages)' |
| `{"status": "duplicate", "state": "…"}` | 200 | this voice was settled already (kept 10 minutes for its line); nothing was done again |
| `VOICE_ROUTE_ID_INVALID`, `VOICE_EVENT_ID_INVALID`, `VOICE_OCCURRED_AT_INVALID`, `VOICE_INDEX_INVALID`, `VOICE_FIELD_DENIED`, `VOICE_BODY_INVALID` | 400 | out of shape |
| `ROUTE_KEY_ENDPOINT_DENIED` | 403 | a route key may not post voices |

A voice the adapter has no outcome for (the platform refused or timed out, or this call failed) is told on the line
instead: its media item carries `voice_refused` (`reason`: `gone`, `refused`, `timeout`, `unreachable`, `no_audio` or
`host`; optional `retcode` and `message`, the platform's own answer, kept on the item for the record), and her line
says why in words.

### HTTP outcomes

| Status | When |
|---|---|
| 200 | the answers above; attachment bytes |
| 400 | malformed JSON, a body size outside its limit, a field out of shape, or a path outside `/v1/channels/{channel_id}/…` |
| 403 | authentication (an unknown channel included), route, identity, capability or receipt refused |
| 404 | an unknown endpoint of an authenticated channel |
| 500 | this request failed in the worker (`HOST_REQUEST_FAILED`); it records a redacted diagnostic (`host.channel_error`) |
| 503 | the whole Host is unavailable for a while (reconfiguring, stopping, its database out of reach); not a fault of the request |

## Persona packages

What a persona package gives the core plugin. For package authors. How to write one step by step: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

A package's `src/index.js` calls `ctx.asuna.registerPersona({...})` (`packages/cognition-core/src/persona.js` `normalizePersona`).

| Field | Required | Rule | Meaning |
|---|---|---|---|
| `id` | yes | `^[a-z0-9][a-z0-9-]{0,62}$`, unique | what the plugin setting `persona` names |
| `resource_root` | yes | a folder | every path below is inside it |
| `model` | no | a JSON file whose `persona.id` is `id` | the persona model (below) |
| `seeds` | yes | `[{slug, kind, path}]`, unique slugs, one of kind `persona` | her documents' starting text |
| `jobs` | no | `[{id, runtime: "python", entry, timeout_s ≥ 1, grants, sources}]`; grants from `persona_data.write`, `probe` | persona jobs |
| `skill_directories` | no | folders | skill folders added to her skill roots |
| `preset` | no | an agent preset name | her role sessions' preset |
| `character_id` | no | — | the author id of her own lines |
| `display_name` | no | — | her name, first in each workspace title |

| Refusal | When |
|---|---|
| `PERSONA_CONTRACT_INVALID: <field>` | a field breaks its rule, or a path leaves `resource_root` |
| `PERSONA_MODEL_UNREADABLE`, `PERSONA_ID_MISMATCH` | the model file cannot be read, or names another persona |
| `Duplicate Asuna persona: <id>` | a second package with the same `id` |

A malformed package never registers; when it is the selected persona the plugin stays inert and says why.

### Persona model

The model is the package's defaults for the core's parameters, checked against `src/asuna/resources/schemas/persona-model.schema.json` (required: `model_version`, `persona`). Effective value: her policy store, then the model, then the core default (`src/asuna/persona_model.py` `CORE_DEFAULTS`).

| Key group | Rule |
|---|---|
| `PRIVATE_KEYS` (`rhythm.timezone`, `rhythm.sleep_window`, `rhythm.public_clock`) | set only on the machine; a package may not default them |
| `CORE_WRITABLE_KEYS` (`heartbeat.*` pace and visits, `heartbeat.dice_*`, `self_development.night_*`) | a package may default them; she sets them with `set_policy` within their ranges |
| `OWNER_KEYS` (`heartbeat.enabled`, `render.identity_tokens`) | a package may default them; only the owner changes them |
| `policy_keys` | keys the package declares for her; may not redeclare core keys |

| Key | Core default | Meaning |
|---|---|---|
| `render.identity_tokens` | 12288 (1,024–65,536) | estimated-token ceiling of what one (place, class) pair carries of her identity every turn: `common.md`, persona, voice, and the `self` and `core` blocks as sent; each pair its own. A package whose own persona and voice seeds render to more than half of it, with a quarter to grow, gets the difference on top |
| `render.max_window_share` | 0.25 | the ceiling never takes more of the character route's window than this |
| `render.action_persona` | `core` | who the action brain is told she is: `core` (her core sentences), `values` (public sections tagged `render.values_tag`), `persona` (the persona's every-turn sections) |
| `render.values_tag` | `values` | the tag `values` reads |
| `people.owner_label` | `本机用户` | the start of the owner's label in her conversations |
| `people.self_names` | `[]` | other names she answers to in groups |
| `people.familiarity` | `{}` | her words and stance for each familiarity level |
| `speak.max_messages` | 1 | her usual lines of `speak` text in one turn: past it the text is sent and the result gives the count; past `role_tools.SPEAK_HARD_LINES` a call is refused |
| `speak.chars_per_second`, `speak.min_gap_s`, `speak.max_gap_s` | 12, 1, 5 | typing pace between her parts |
| `heartbeat.enabled` | `false` | her heartbeat ([Schedules](#schedules)) |
| `self_review.tag` | — | the tag of her own sections her reviews read |
| `self_review.exchanges_note` | neutral text | the note on her exchanges in a self-evaluation |
| `heartbeat.idle_hint` | neutral text | the hint of an idle heartbeat beat |
| `memory.tiers_told` | neutral text | how her memory's places (carried, at hand, put away) are told, once per conversation |

Every other group (`affect`, `memory`, `recall_protocol`, `phrasing`, `rhythm.settle_at`, `self_development.every_min`) is defined in `CORE_DEFAULTS` and the schema.

A persona, voice, `self` or `core` section tagged `place:home`, `place:peer`, `place:group` or `place:dm` is carried only in turns at that place; an untagged one everywhere (`src/asuna/visibility.py` `PLACES`).

### What she carries

`src/asuna/carried.py` `carried` gives, for one (place, class) pair, the sections of persona, voice, `self` and `core` that reach a turn: each where its tier puts it (`memory_tiers.placed`), readable in the class, its `place:` tags honoured. The pairs are the four places, each with its class, and a group read at home when `home_groups` is configured (`carried.pairs`). The system prompt, its re-render from `system_ref` (which records the carried section ids), the identity budget, the relevance gate, the action brain, `doc_refs_from_program`, the persona-data probe, the memory tab and the settings card read it; notes and ledgers go through `carried.note_sections`.

| Rule | Where |
|---|---|
| A write that grows a pair's identity layer while that pair is over `render.budget_limit`, or takes it over, is refused (`PERSONA_RENDER_OVER_BUDGET`): the pair, its gap in `carried()`'s numbers, `let_go` or a shorter text, and the three largest sections it carries now; when the write takes or keeps more than one pair over, one more line names each with its gap. One that shrinks it or keeps it the same applies. `write_document`, `adopt_seed`, `promote_memory` and persona-data imports pass the same gate, measured as the write will carry it (`memory_tiers.Tiers.placement_after`) | `carried.gate`, `carried.over_words` |
| A write to persona, voice, `self` or `core`, and a `let_go`, returns `room`: the section's weight and the room left (or how far over) in each pair that carries it; a section a `let_go` leaves carried nowhere says in how many pairs it was carried and what it freed in each. A section whose `inject` and tier differ says both, with its last move (local time, who, why), on a write and on a `recall` of it (`tier`). The program never writes her `inject` | `carried.room_line`, `carried.tier_line` |
| The pairs in her words, in this order: 家里, 家里那个群 (a group read at home), 外面的群, 线 (a peer line), 私聊 | `carried.PAIR_WORDS` |
| `things_from_program.identity_room`: how full each pair readable in the turn is, in words, only when they change | `carried.room_block`, `carried.ROOM_WORDS` |
| A tier move's `move` row carries `by` (`her` or `program`). A row without `by` was written before it existed; its `reason` says who moved it: `let_go` (her let_go and her own `inject` writes) is hers, every other reason is the program's | `memory_tiers.BY`, `memory_tiers.moved_by` |
| A group's notes over their per-turn limit (2,400 characters) fold the section that surfaced longest ago first (a turn bringing it up, her recall, her rewrite, her writing it); the order is kept and recomputed on her write and at settlement. A folded section brought up by her own items' retrieval is labelled carried and folded. A section with `pin` never folds and still counts; the fold line says when the pins alone are over. The relevance gate reads the notes as the turn shows them | `group_admin.notes_view`, `context_budget.note_view`, `memory_tiers.Tiers.fold_order` |
| Her items at hand come up by themselves when the turn's message has one of their keys, or above the vector floor (0.83); at most two, in fused order. Keys are her tags on any item (two characters or more, not `place:`), and the words of a group note's heading that are rare in the place (in at most 0.5% of its newest 10,000 inbound lines of the last 14 days, at most 5 lines in a quiet place) and not everyday words (jieba dictionary frequency under 500). ASCII letters and digits match as whole runs, without case. An item a key brought carries `why`, the word as the message spells it. `recall` reaches put-away items by the same keys and lists headings by them. Each place's common words are kept (`memory_tiers` rows `rarity`), counted when missing and again at settlement. A write with tags returns `tags_here`: how often the place says each one | `memory_tiers.deliver`, `memory_tiers.headings`, `key_words.keys` |
| `recall` with a query also returns `elsewhere`: at most two lines of her other groups with a word of the query that may cross (outside jieba's dictionary, or a whole ASCII word or number, links and @-mentions stripped) and that the place she is in says at most twice in its recent lines; hers as 「你在别处说过」 first, then a line that explains it (就是 / 指的是 / 意思是), then the newest; others' as 「别人提过」 only from a group set to `all` (`<data>/private/memory-crossing.json`; `own_lines` by default, `never` gives nothing). Each has the day, the group's kind when set, and a `ref`; no place, speaker or mentioned person (an @ reads 「@某人」). A line a later resolved reply corrected is marked 「已被更正·…」 with the correction. `sections` `{doc: elsewhere, section: <ref>}` reads the five lines around one, speakers as 你 or 别人, the group's rule checked again. Only groups are sources, and only spoken lines, never her thoughts. The lines are found through the collection `crossing_words` (one row per word: unit ids, hers or others' (the newest 20), scope; no text), which the program derives and rebuilds: made when missing, rebuilt at settlement, topped up at each recall and cue from the group lines chunked since, with per group the lines of the window that have each word and the latest; place rules are applied when it is read, never stored in it. `before`: at most three past versions of this group's notes or of her running records readable here, one per section, for a word of the same kind its current text no longer has: 「你以前记过：…（改于 日期：原因）」 (「已删」 when the section is gone); none written in the configured excluded dates, none of an item marked 我自己的判断 | `crossing.elsewhere`, `crossing.fetch`, `crossing.before`, `crossing.build` |
| A group turn whose line has such a word, said in at least `seen_elsewhere` (5) lines of her other groups in the last `window_days` (14) days (others' lines counted too, from any group not set to `never`), brings one line into the memories block, in a free own-item slot after her own items: 「X：这个词你在别的群见过 N 次，最近 MM-DD，<kind>；recall 写上它能找到」 (no kind when none is set). With `cue_lines` `new`, its words come from every inbound line new to the turn (after those an earlier turn there delivered, and those claimed into it), and only an earlier turn's delivered lines count as in view; by default (`trigger`) from the turn's own line, with the turn's delivered lines in view. Not on a templated line (an opening the group repeats in 5 lines of 20 characters or more, after a leading @-mention; or three labelled fields), not for a word the turn's delivered lines have, a word her own items this turn have, or one the group says more than `said_here` (2) times; once per word and group in `repeat_minutes` (60). Each cue is a `memory_fires` row (kind `cue`, the group, word, turn, line's `scene_seq`, time), kept 30 days. The numbers are in `<data>/private/memory-crossing.json`. jieba's guessed cuts are made consistent by a learned vocabulary: the Chinese cross words in 3 lines or more at the index build, without glued pieces (one holding a shorter candidate said in at least as many lines), kept with the index and learned by each process; the dictionary test always reads jieba's own dictionary | `crossing.cue`, `key_words.vocabulary`, `key_words.learn` |
| What came back is counted in `memory_fires`, one row per fire with its turn (`episode_id`), the turn's line (`scene_seq`) and its time: `note` (an own item a turn brought up, `by` word or meaning, with the word), `cue`, `elsewhere_hers`, `elsewhere_theirs` and `before` (what a recall returned), `w6` (a recall that returned an item or line the turn's own memories had not, with how many). Rows go after 30 days. Once a local day in each conversation, `things_from_program.came_back` says what came back in the last day, each kind in words (没有 / 一次 / 两三次 / 好几次 / 很多次) and up to three notes readable there by heading; never which place. `tools/memory_fires_report.py` reads the rows per place, with the minutes since each turn's last compaction from DSH's session logs | `crossing.fired`, `crossing.recalled`, `memory_tiers.Tiers.came_back`, `crossing.report` |
| Each turn's episode manifest records `carried`: its pair, the section refs, the group-notes sections shown, the sections its own retrieval brought up (`brought_up`) and the carried ones it would have (`would_surface`) | `carried.manifest` |
| The audit retention thread counts each whole local day once (`carried_days`), back to when the tiers went on, through that day's `turn.output` rows. `carried_counts`, kept 30 days, has per section × pair × day `section`, `pair`, `day`, `turns_carried`, `pair_turns`, `recall_hits` (her recalls of it there), `program_score` (turns whose retrieval scored it above the floor: brought up, or would have been) and `reconstructed` (a day from before manifests recorded it). `carried_sections` keeps each section's `first_carried_at` and `last_carried_at` and is never pruned | `carried.count_days` |
| Her install checks, read only: the latest turn's `system_ref` sections are `carried()`'s, each pair's refusal says `carried()`'s number, a write gets its room line, every tier/`inject` difference is said | `carried.install_checks`, `tools/carried_check.py` |

## Channel packages

What a channel package gives the core plugin. For package authors; the API its adapter speaks is the [Channel API](#channel-api).

A package's `src/index.js` calls `ctx.asuna.registerChannel({...})` (`packages/cognition-core/src/channel.js` `normalizeChannel`).

| Field | Required | Rule | Meaning |
|---|---|---|---|
| `kind` | yes | `^[a-z][a-z0-9_]{0,15}$`, unique | the platform: channel id, and the prefix of its scene and person ids |
| `title` | yes | non-empty | the workspace its conversations live in |
| `project` | yes | `^[a-z][a-z0-9-]{0,50}$` | its development project |
| `resource_root` | yes | a folder | every path below is inside it |
| `python` | yes | a folder | where the kind module is imported from |
| `module` | yes | `^[a-z][a-z0-9_]{0,40}$` | the kind module's name |
| `integration_directory` | no | a folder | the adapter that her integration tools develop and run in the sandbox |
| `skill_directories` | no | folders | skill folders added to her skill roots |

- Refusals: `CHANNEL_CONTRACT_INVALID: <field>`; `Duplicate Asuna channel kind: <kind>`. A configured channel whose package is not registered within 15 seconds stops the start (`CHANNEL_PLUGIN_NOT_INSTALLED`).
- A package without an integration directory runs its own adapter in the Host: `ctx.asuna.channelEndpoint(kind)` gives `{url, channelId, accountId, token, settings}` (the channel's settings with secrets resolved), or `null` when the channel is not configured.

### Kind module

The kind module tells the core one platform's id formats and adapter conventions (`src/asuna/channel_kinds.py`).

| Name | Required | Meaning |
|---|---|---|
| `KIND`, `TITLE` | yes | the kind, and the platform's title |
| `ACCOUNT` | yes | a regular expression for an account id |
| `INBOUND_MENTION` | yes | how the adapter writes a real @ in inbound text |
| `person_id(account)`, `account_of(person)` | yes | `<kind>:<account>` and back |
| `scene_id(bot, kind, target)`, `scene_parts(scene)` | yes | `<kind>:<bot>:<dm|group>:<target>` and back |
| `outbound_mention(account)` | yes | how her @ reaches the adapter (`@<kind>:<account>` in the shipped kinds) |
| `adapter_config(adapter, channel)`, `strip_derived(adapter)` | yes | fill and remove the adapter settings derived from the channel |
| `IMAGE_HOSTS` | no | hosts images may be fetched from by default |
| `FILE_HOSTS` | no | hosts a received file may be fetched from (an entry starting with `.` allows its subdomains); without it its files are offered as not readable |
| `FACES`, `STICKERS` | no | the platform's faces by name → id; whether it sends stickers |
| `HOME` | no | its conversations are home ones (owner-private) |
| `TEXT_ONLY` | no | it carries no pictures |
| `OWNER_JOINS` | no | the owner is a member of each line and writes there from the Web |
| `PEER_LINE` | no | she opens and closes each direct line herself |
| `ROUTE_KEYS` | no | each route has its own key ([Route keys](#route-keys)) |
| `MARKS_ANSWERS`, `answerer(scene)` | no | who on a line marks the lines that answer her questions |
| `REQUESTS` | no | its adapter posts friend and group requests ([notices](#post-a-notice-for-her-home)) |
| `REPLY_PARTS` | no | she speaks there only in these parts (`text`, `sticker`, `picture`, `file`, `poke`, `react`, `recall`); `file` is offered only in groups whose adapter declares `file` |
| `OWN_RECALL_SECONDS` | no | how long after delivery she may take back her line (none where she is a group's owner or admin) |
| `SERVICE_ARGV` | no | the managed adapter's resident command |
| `MEDIA_KEYS`, `media_key_name`, `media_key_in`, `sign_media`, `media_refusal` | no | signed media links ([media keys](#post-the-current-media-link-keys)) |
| `sticker_of(item)`, `sticker_md5(item)` | no | read a stored media item as a sticker, and its file's md5 |

The shipped kinds are in `packages/channels/*/python/`.

## Her tools

The character brain's tools, and where the rest of her turn is implemented. The code is the reference; this section only points to it. For anyone changing or reading them.

Her tools: `src/asuna/role_tools.py` (`TOOLS`; where each is offered: `EVERYWHERE`, `AT_HOME`, `IN_GROUPS`, `_turn_rules`; refusal words: `not_now`, `words`; `block`'s turn rule: `_block`).

| What | Implemented in |
|---|---|
| parameter names she is shown, and old names still taken | `src/asuna/param_names.py` (`RENAMED`, `STILL_TAKEN`) |
| a conversation's tool list and the options it shows (an option no turn there can use is left out, one spec per place and class), fixed when its session starts | `src/asuna/role_tools.py` (`session_specs`, `placed_spec`) |
| the context blocks a turn carries, their limits, and their words; what of her identity each place carries | `src/asuna/context.py` (`ContextBuilder`), `src/asuna/context_budget.py`, `src/asuna/block_guide.py`, `src/asuna/carried.py` |
| the checks on a turn's end, the gate's answer, an appraisal | `src/asuna/answers.py` |
| the relevance gate and group focus | `src/asuna/attend.py`, `src/asuna/focus.py` |
| people, labels and her understanding of them | `src/asuna/people.py`, `src/asuna/understanding.py` |
| memory, recall and her tiered items | `src/asuna/retrieval.py`, `src/asuna/memory_tiers.py`, `src/asuna/memory_pilot.py` |
| history search and summaries | `src/asuna/history_query.py`, `src/asuna/dialogue_summary.py` |
| her documents and group notes | `src/asuna/documents.py`, `src/asuna/group_admin.py` |
| notes, questions and errands between her conversations; a note's limits (length, per turn, hops, unread days) | `src/asuna/notes.py` (the constants at its top), `src/asuna/questions.py`, `src/asuna/errands.py` |
| watches and their limits (how many, how long), switches, condensing | `src/asuna/watches.py` (`WATCH_MAX`, `WATCH_MAX_HOURS`), `src/asuna/switches.py`, `src/asuna/condense.py` |
| stickers | `src/asuna/stickers.py` |
| tasks with the action brain, their hand-back and failures | `src/asuna/tasks.py`, `src/asuna/handover.py`, `src/asuna/faults.py` |
| her restarts | `src/asuna/restarts.py` |

## Action capabilities

What the action brain is given for a task, and the contract its commands run under. For anyone changing a capability, and for her action brain building on them.

### Tools a task is given

A task's tools are fixed when she hands it over (`src/asuna/coordinator.py` `Coordinator._grants`) and recorded with its grant. A tool the task was not given is refused with one sentence: `CAPABILITY_DENIED` (`src/asuna/tasks.py` `GIVEN_TO`, `capability_refusal`).

| Group | Defined in | Given to |
|---|---|---|
| DSH tools `skill`, `todo_write`, `web_search`, `web_fetch` | `tasks.py` `ACTION_DSH_CAPABILITIES` | every task |
| workspace: `list_files`, `read_file`, `write_file`, `offer_file` | `tasks.py` `WORKSPACE_TOOLS` (`offer_file`: `outbound_files.py` `OFFER_FILE_TOOL`) | every task |
| `sandbox_run` | `tasks.py` `SANDBOX_TOOL` | tasks from owner-private conversations, when the Host has a sandbox |
| history search, discussion digest | `history_query.py` `HISTORY_TOOL`, `discussion_digest.py` `DIGEST_TOOL` | every task |
| `ask_character`, `report_progress`, `note_idea` | `tasks.py` `ASK_TOOL`, `PROGRESS_TOOL`, `NOTE_IDEA_TOOL` | every task |
| `read_image` | `vision.py` `READ_IMAGE_TOOL` | when the action route takes images and `vision.image_hosts` is not empty |
| `private_words` | `private_words.py` `PRIVATE_WORDS_TOOL` | every task |
| `render_svg` | `svg_render.py` `RENDER_SVG_TOOL` | every task, when the Host renders SVG |
| `generate_image` | `image_generation.py` `GENERATE_IMAGE_TOOL` | every task, when the integration is enabled, the sandbox is available and an endpoint is named `image` ([Integration](#integration-and-self-development)) |
| integration tools, `import_integration_artifact` | `integration.py` `INTEGRATION_TOOLS`, `integration_import.py` `IMPORT_TOOL` | by integration profile ([Integration](#integration-and-self-development)) |
| development and persona-job tools | `development.py` `DEVELOPMENT_TOOLS`, `PERSONA_JOB_TOOLS` | with the development grant ([Self-development](#self-development)) |

- `ask_character` asks her for a judgment and waits for her answer; `report_progress` leaves her a note without waiting. Neither creates a public reply, a task or a grant.
- A task keeps the grants of the turn that handed it over; her later words never add one.
- A tool call that did not happen is an error, and its tool record is `FAILED` with the same words (`tasks.py`
  `failure_words`): a workspace file operation (`TASK_OPERATION_FAILED: …`), and `generate_image`, `render_svg` or
  `import_integration_artifact` naming a failure code, with its note and the values it names. `IMAGE_JOB_STILL_RUNNING`
  is not a failure: calling again with `job` fetches the picture. A `FAILED` record is not evidence of the task's
  result; the report's tool records show it as its error.

### Web search and fetch

- `web_search` is DSH's tool with 10 sources and a `detail` argument (`titles`: title, link and date only); snippets are cut to `search.snippet_chars` (default 300). Its backend is the core's `asuna-search` provider, which tries `deployment.search.order` (default `searxng`, `gemini`, `exa`, `deepseek-official`) per query (`packages/cognition-core/src/search.js`). Settings: [RUN_ASUNA.md](RUN_ASUNA.md#web-search).
- `web_fetch` is DSH's tool over the core's `asuna-fetch` provider: at most 5,000,000 bytes, 30 seconds and 5 redirects; a Cloudflare challenge page answers `WEB_HUMAN_VERIFICATION` (`packages/cognition-core/src/fetch.js`).

### Skills

A task sees skills by where it came from (`src/asuna/skills.py`): from an owner-private conversation every skill root; otherwise only skills whose `SKILL.md` header lists that place in `scene_kinds` (`home`, `group`, `dm`; absent means `home` only). A header with an unknown key or kind is refused at publication (`python -m asuna.skills`); a valid set passes, and the probe names the skills whose header has no `scene_kinds` (offered at home only).

### Sandbox

Every command the worker does not run itself (`sandbox_run`, `development_run`, persona jobs, integration runs) runs under DSH's sandbox: the Host wraps it with `ctx.sandbox.confine` in `workspace-write` mode (`src/asuna/sandbox_backend.py`).

| Contract | Value |
|---|---|
| may write | only its own folder: the task folder, the candidate, the job's output folder, the integration's data folder |
| reads, network | not restricted |
| run time | 30 s (`development_run` 35 s); a call's `timeout` up to 600 s; a stopped command returns its output so far (`timed_out`) |
| output | 256 KiB; past it `sandbox_run` keeps nothing (`TOOL_OUTPUT_LIMIT`) and `development_run` returns what came (`limited`) |
| `python3`, `python` | the worker's own Python |
| `/task` in an argument | the task folder |
| temporary folder | `TMPDIR` (Python's `tempfile` reads it first) = a new folder inside `.tmp` of its own folder, removed when the command ends; a failed or stopped command's result says what it held (`temp_removed`); `TEMP`, `TMP` = `.tmp` (on Windows DSH's runner gives the command private ones); for `development_run`, only in a core candidate |
| git | nothing prompts (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`; not set for `development_run`); with `character_git` set, a home task's commits carry her name as author and committer |
| home task's commands | also `ASUNA_MONGO_URI`, `ASUNA_DATABASE`, `ASUNA_TIMEZONE` for `asuna.dbread` (`src/asuna/dbread.py`; skill `asuna-database`) |
| working copy | each home place's folder holds `working-copy`, a full clone of the checkout whose `origin` is the checkout's origin; made at start when missing, never changed after (`packages/cognition-core/src/working-copy.js`) |

- `deployment.sandbox.backend` is `auto` (use the Host's sandbox when it has one) or `none`. Without a sandbox, `sandbox_run`, `generate_image`, the managed integration, persona jobs and self-development are off (`SANDBOX_UNAVAILABLE` if called).
- On Windows the Host must be able to change permissions on the data folder.

### Credentials

A credential is a name (`^[a-z][a-z0-9-]{1,31}$`), a note and at most 6 environment variables; its values live only in DSH's credential store, one record `asuna-cognition-core/<name>` (`src/asuna/credentials.py`).

- She files and drops one with her `credential` tool in her local chat; a turn sees names, notes and variable names, never a value.
- Only a task from home may use one: `sandbox_run` with `credentials` sets those variables for that command (`CREDENTIALS_HOME_ONLY` elsewhere).
- Every stored value is replaced by `[凭据已隐藏]` in tool results, briefs, messages and answers to the action brain and reports.

### Local roots

No local root of this computer reaches the character brain; the action brain works with real paths
(`src/asuna/local_roots.py`, `packages/cognition-core/src/roots.js`).

- **The table.** The worker builds it at every start from its settings and the machine and hands it to the Host with
  its `initialize` answer. A known root is written `${ASUNA_<NAME>}` and the rest of the path stays: `WORKSPACE` (the
  Host's repository checkout, else the installed package), `PROJECTS` (the folder that holds it, unless that is a
  filesystem or drive root or the home), `DATA` (the data folder), `DSH_HOME` and `TEMP` (each when
  not under another root), `HOME`, `PROGRAMS` (program folders, their own name kept: `${ASUNA_PROGRAMS}/usr/lib/...`),
  `DRIVE_<X>` (any other path on drive X, WSL's `/mnt/x`; on POSIX each mount by letter or index), `FS` (any other path
  in the machine's own top-level folders on POSIX), `LOCAL_PATH` (a network share, or another account's home beside the user's, nothing
  kept; the shared `Public`, `Default`, `Default User`, `All Users` and `Shared` folders are not accounts) and `USER` (the
  account name, that exact string as a whole word; not a generic account such as `root`). The deepest root wins. Every
  spelling matches: either slash, doubled backslashes, percent-encoded, 8.3 aliases, resolved links, `/mnt/x/...`,
  `/x/...`, after `file:///`, case-insensitive on Windows. `/task/...` is not a root; any other `${...}` is text, and no deployment variable is named like a placeholder. A
  checkout, data folder or DSH home at a filesystem or drive root refuses the table.
- **Toward her.** Every request of her lanes (her persona preset, the relevance gate, the appraiser, the background
  summaries, by the session's preset as it stands now) is rewritten at DSH's `llm/stream`: text, reasoning, the system
  text and earlier tool calls' arguments. The action brain and the recovery session are not rewritten.
  DSH's working-folder line is a required runtime context and is rewritten with the rest. The DSH session, stored
  messages and the Web page keep the real text. Without a table her lanes' requests fail with
  `ASUNA_ROOT_TABLE_MISSING` (a program fault: her next turn there says a turn did not run, the developer inbox gets a
  note, the audit one `roots.refused`) and the settings card says so; the action lane runs. Otherwise the settings card
  shows the table's size and the requests rewritten since the start.
- **Toward the action brain.** The `delegate` brief and title, a message to a task, her answer to a task's question and an `ask`
  to 行动脑 lose every credential value, then each placeholder the place hands over becomes its real path with the
  host's separators (a public place: `WORKSPACE`, `DATA`; home: all but `LOCAL_PATH`); any other stays as written, and the
  tool's result names it (`paths_kept`).
  Refused, in words: a raw root (with the whole text rewritten), an `${ASUNA_...}` name the table does not have where it stands as a path's root (followed by a separator; elsewhere it is text, as the deployment's own `${ASUNA_...}` variables are), a
  `..` segment in a path at a root or placeholder, and in a public place a relative path that climbs.
- **Her writing.** Every other string argument of her tools is stored contracted, except a credential's values and her
  private words.
- **Her speech.** A raw root in a `speak` text or her end-of-turn text is replaced by its placeholder before it is
  queued, each replacement one `roots.speech_replaced` count. Her weekly tool readings (`local_paths`) say that count,
  which should be 0, and her requests rewritten per conversation (`roots.tally`), normally above 0.
- **The image note.** The read-only path DSH's DeepSeek adapter writes beside each image while it builds a request
  comes from DSH's fs service (`processPathFromHostPath`); her lanes' requests run in a scope in which that mapping
  answers contracted, and everywhere else it answers as before.
- **Not covered.** A path inside a picture.

## Media and images

How pictures and other media come in, how she and her action brain read them, and how her pictures go out. For adapter authors and anyone changing image handling. Code: `src/asuna/vision.py`, `src/asuna/outbound_media.py`.

### Inbound media

An adapter puts a message's media in `raw.asuna_media` as `{"items": [...]}`. The host keeps the block as sent; a placeholder is not a seen picture.

| Item field | Meaning |
|---|---|
| `type` | `image` or `video` can be read; any other type stays a placeholder |
| `url` | where to fetch it |
| `file` | the platform's file name (a bare name, read from `vision.image_dirs`) |
| `placeholder` | the text that stands in for it in the line |
| `size` | the size the platform declares, in bytes |
| `summary` | the platform's short description |
| `sticker` | `custom` (a picture sent as a sticker) or `market` (a store sticker, with `emoji_id`, `emoji_package_id`, `key`) |
| `unreadable` | why it cannot be read |

- At most 8 items of a message are listed (`MAX_ITEMS_PER_MESSAGE`), and a conversation's listing offers its newest 8 (`LISTING_ITEMS`). Each gets a reference `att-…`; a reference stays readable for 7 days (`REF_DAYS`).
- A picture the owner attaches in her local chat is stored by the core plugin as an image artifact and recorded on the input as `raw.asuna_media` with `origin: local_upload`. Only the program's own input can carry that origin.

### Voice messages

A voice segment's item has `type` `record` (or `audio`), and the line's text carries `[语音（未解析）]` in its place.
An adapter that can fetch voices declares `voice_in` and [posts each one](#post-a-voice) before its line; the worker
turns it into text on this machine (`src/asuna/voice.py`). Nothing is sent anywhere else. A line from an adapter that
does not declare `voice_in` keeps its placeholder.

- **Never stored.** The audio lives in memory for its request. The line is stored with one entry per voice in its event
  (`event.voice`): state, words, length, sha256, size, first 44 bytes, media type, model and times (`ENTRY_FIELDS`).
  It does not change afterwards.
- **Recognized, then normalized.** The container is told by its first bytes (RIFF/WAVE, ID3 or an MPEG audio frame
  header); anything else is refused before any field is read. av decodes it and resamples it to 16 kHz mono PCM16,
  whatever rate and depth came.
- **Transcribed in a child process.** With `voiceToText` on, a child process of its own (`media_children.py`,
  `media_worker.py`) starts with the worker, loads the model (about 310 MB) and keeps it, and takes one voice at a
  time: av decodes it and SenseVoice int8 with Silero voice detection (speech and silence each at least 0.25 s, a
  piece at most 20 s) through sherpa-onnx transcribes it, language detected, 4 threads. A voice has 180 s in all,
  waiting behind other voices included; a try past 90 s is killed and the voice tried once more in a fresh child; a
  second timeout or crash, or the 180 s spent, fails the voice. Each kill, death, failed
  start or program error in the child is a lane fault (`lane_faults`, lane `transcriber`); a voice the child was
  working on when the worker stops is answered `503 HOST_STOPPING`, so the adapter posts it again. No child outlives the worker. There is no length limit.
- **The model files** are `<data>/models/sensevoice-2024-07-17/` `model.int8.onnx`, `tokens.txt` and `silero_vad.onnx`,
  checked against their sizes and sha256 (`voice.MODEL_FILES`), with the packages (numpy, sherpa_onnx, av), once
  when the worker starts (evidence `voice.model_checked`). A missing or different file or package is one line in the
  Host log, `ASUNA_VOICE_MODEL_UNAVAILABLE`, no child is started, and every voice then reads
  `没转出文字：这台机器上的语音识别没装好`.
- **What her line shows.** The line is stored with each voice's words in its place (`voice.read_text`), so every
  reader shows the same words; the text as it came is kept in `event.received_text`, and a line posted again is the
  same line when that text is the same:

| State | Her line shows |
|---|---|
| `transcribed` | `[语音 33 秒] 文字……`; a piece labelled other than speech is named: `[语音 20 秒，听着像背景音乐] ……` |
| `no_voice` (the detector found no speech) | `[语音 5 秒，里面没有人声]` |
| `no_words` (speech, but no letter or digit in the text) | `[语音 12 秒，有人在说话，但听不出说的什么]` |
| `failed` | `[语音 33 秒，没转出文字：原因]`: bytes that are not WAV or MP3 or do not decode, `识别超时了` (two tries past 90 s, or the voice's 180 s spent, waiting behind other voices included), `识别程序出错了` (the child died twice) or `识别程序出错（类名）` (the child's own code failed), or `交给本机识别时出了错` (the adapter's `voice_refused` `host`) |
| `not_transcribed` (the machine, not the voice) | `[语音，没转出文字：原因]`: `语音转写关着`, `这台机器上的语音识别没装好`, or `这台机器上的语音识别没能启动` (the child would not start; tried again at most once a minute) |
| `not_fetched` | `[语音，没拿到：原因]`, from the adapter's other `voice_refused` reasons, or `这段语音没随消息一起送来` on a `voice_in` channel whose line came with neither an outcome nor a reason |

### Reading images

`read_image` (both brains) takes a reference, a stored image's `artifact_id`, or in an owner-private conversation a file path. It is offered only where the brain's route declares image input and `vision.image_hosts` is not empty.

| `vision` setting | Default | Effect |
|---|---|---|
| `image_hosts` | the hosts the installed kinds declare (`IMAGE_HOSTS`) | hosts a link may be fetched from (an entry starting with `.` allows its subdomains); `[]` refuses every link |
| `max_bytes` | 8 MiB | fetch limit; never above 8 MiB |
| `timeout_seconds` | 15 | fetch timeout |
| `image_dirs` | none | local folders a bare file name is read from |
| `allow_insecure_http` | `false` | allow `http` links |

- Bytes are accepted as PNG, JPEG, WebP or GIF by file signature. A video (at most 32 MB, `VIDEO_MAX_MB`) is read as a contact sheet and not kept, cut in a child process of its own that starts with the worker and stays loaded while `videoDecoding` is on (`media_children.video_snapshot`): a video has 240 s in all, a try past 120 s is killed and the video tried once more in a fresh child, and a second timeout, a crash or a program error in the child (`拆视频的程序出错了`), the decoder not installed (`ASUNA_VIDEO_DECODER_UNAVAILABLE` in the Host log at start), or the setting off each says so in its own words; an animated picture is read as a contact sheet too, in the worker (`src/asuna/animated.py`).
- A link its platform signs is signed again with the current [media key](#post-the-current-media-link-keys) before the fetch.
- Pulled bytes are stored in the scoped blob store; how long each kind of stored picture lives is `src/asuna/media_life.py` (`POLICY`).

| Code | When |
|---|---|
| `IMAGE_NOT_PULLABLE`, `IMAGE_ATTACHMENT_NOT_IN_SCENE` | the reference cannot be read, or is not in this conversation's last 7 days |
| `IMAGE_ARTIFACT_NOT_READABLE` | an `artifact_id` this turn may not read |
| `IMAGE_PATH_HOME_ONLY`, `IMAGE_TASK_DIR_UNAVAILABLE`, `IMAGE_FILE_NAME_DENIED`, `IMAGE_FILE_NOT_AVAILABLE` | a file read refused or missing |
| `IMAGE_URL_MISSING`, `IMAGE_SOURCE_UNAVAILABLE` | no link or file to read from |
| `IMAGE_INSECURE_URL_DENIED`, `IMAGE_REDIRECT_HOST_DENIED` | not https, or a redirect to a host not allowed |
| `IMAGE_FETCH_FAILED`, `IMAGE_EMPTY` | the host refused or could not be reached; nothing came |
| `IMAGE_LINK_EXPIRED` | re-signed and still expired |
| `IMAGE_GONE` | the host says the picture is gone (HTTP 404 or 410) |
| `IMAGE_SIGNATURE_UNAVAILABLE` | no current key is known; worth trying again later |
| `IMAGE_TOO_LARGE`, `IMAGE_TYPE_UNSUPPORTED` | over the limit, or not a supported type |

### Sending pictures

A picture leaves with her words as a message's `attachment` ([Claim public output](#claim-public-output), [Fetch attachment bytes](#fetch-attachment-bytes)).

- Pictures go to a conversation whose route targets a `dm`, or a group, on a kind that is not `TEXT_ONLY` (`outbound_media.target_allowed`).
- In a group and in anyone's private chat but the owner's, only pictures she made go out (`outbound_media.own_only`): source `integration:` (drawn, imported or rendered), and her edits of pictures that came from that conversation. A sticker on her shelf goes wherever stickers go. Anything else is refused with `ATTACHMENT_NOT_HER_OWN`.
- A picture is at most 8 MiB; the registered copy of a PNG has its text chunks removed.

### Sending files

A file goes to a group as its own message: speak's `file` part names a file a task registered ([Claim public output](#claim-public-output), [Fetch attachment bytes](#fetch-attachment-bytes)). Code: `src/asuna/outbound_files.py`.

- **Registration.** The action brain's `offer_file` (`path` inside `/task`, `name` the file name people see, default the file's own) stores the file in the task's own scope as a `file` artifact (source `task-file:<task>:<path>`), streamed into the blob store (`BlobStore.put_stream`). The program computes the sha256, the size and the type from the first bytes (`outbound_files.sniff`); an unrecognized type is recorded as `类型没认出来` and still goes. A name containing a word on her private words list is warned about by category and entry line, never the word, and not refused. The row keeps the task folder and path it came from (`source`).
- **Offer.** A file any of her tasks registered may be sent where the channel declares `file`, as her own pictures go anywhere. `file_artifacts_from_program` lists them, newest first and at most 8, each with `artifact_id`, `name`, a readable `size`, `type` and `registered_at`; it appears in a group whose kind lists `file` in `REPLY_PARTS` and whose adapter declares `file`.
- **Sending.** The part is refused in words when the file is not listed, its bytes are gone, or its size is over the limit the adapter declared; the program has no size or type limit of its own. Her record line is `[文件：名字，大小]`, with `，类型没认出来` when its type was not recognized.
- **Bytes kept.** A file's bytes are removed 7 days after it was last delivered, or 7 days after registration if never delivered, and kept while a message on its way names it (`media_life.sweep`, daily). The artifact row stays, with `storage` `removed` and `bytes_removed_at`. A part or claim naming it then says when the bytes expired and whether the task folder still holds the original unchanged.

### Received files

A file someone sends her is offered by ref and read only when she asks: `received_file`, one tool for both halves (her turn's scene, or the task's binding). Code: `src/asuna/received_files.py`.

- **Offer.** A file on a platform line gets a note under the line: `（文件 ref：att-…，45.0 KB）`, or why it is not read: no link, a platform that declares no `FILE_HOSTS`, a name the first version does not open (archives, PDF, Office, media, programs: `received_files.NOT_OPENED`), a declared size over 1 MiB, a link off the platform's file hosts. A ref is found among the newest 8 files and pictures of the last 50 messages others sent in each conversation in reach, or among all of those of its last 7 days (there the listing's 8 and 50 do not apply, the cap of 8 items in one message still does), the same fence and window as pictures; at home, in any of her conversations.
- **Fetching.** Only on `do=read`, only the item's own `https` link on the hosts its channel kind declares (`FILE_HOSTS`; NapCat: `.ftn.qq.com`), redirects included; at most 1,048,576 bytes counted as they are read, the bytes in memory until judged. A wait of 20 s without data ends a fetch, and after 20 s it ends at the next piece (a host that drips can hold it about 40 s). A fetch is a best attempt: a link the platform no longer serves is said once, in words.
- **Judging.** A BOM decides the encoding; else a program or other binary is refused and never stored (`名字是 .txt，内容却是Windows 程序`); else strict UTF-8; else GB18030 with at most 1 control character per 1,000; else `编码没认出来`. Every answer carries `marks`: caution always (`这个文件是<sender>发来的…`), and runnable for a script's extension or a text starting with `#!`. The text comes after a fixed line saying it is the sender's material.
- **Reading.** One page per call: up to 200 lines and 6,000 characters, counted on the decoded text (a line ends at `\r\n`, `\n` or `\r`); `page` goes to any page, `find` gives the count of matches (Latin letters in either case) and the first 5 pages holding one, with the line. `life` says when the bytes go and how the ref is found.
- **Keeping.** Bytes go 3 days after the last fetch or `let_go` (`media_life`, the `RECEIVED` cycle); a read does not move that. `do=keep` (`why`) keeps a file within 20 MiB or 50 files, `let_go` ends it, `kept` lists what she keeps there and counts the rest. A kept file's ref never ends. Bytes that expired are fetched again onto the same row while the ref is found.
- **Copy (the action brain).** `do=copy` writes the stored bytes to `/task/received/<name>`, the name made safe (no path parts, no `..`, no Windows device name, no trailing dot or space, at most 255 UTF-8 bytes; a clash gets ` (2)`). On Windows the folder gets one inherited deny-execute entry for the worker's account when it is made (files only: a program there cannot be started; it can still be read, so a script runs only when she runs it with its interpreter); on POSIX each copy is `0600`. Where the entry cannot be set the copy is still made and says `这里没法禁止执行`. The program never runs a received file. Each copy's path is kept on the row and the copy is removed with the bytes: by the sweep after they expire, at once by an erasure; a kept file's copies stay.
- **Forwarding.** A file a task registers with `offer_file` whose bytes equal a received file in the task's fence keeps `received_from` (its ref and sender), by content, so a renamed copy keeps it; the offer says `这是<sender>发来的文件；发出去时它的来路跟着`.
- **Erasure.** An erased file answers with the [Erased media](#erased-media) sentence and `从原消息的链接重新拉的那条路也一起关了。`; it is never fetched again.

### Erased media

An operator's privacy erasure (`asuna delete-memory`) deletes every stored byte of the memory's conversation and marks each of its artifact rows `storage` `erased`, with `erased_at` and `deletion_id`; the row keeps its name, size, sources and time. Code: `src/asuna/blobs.py` (`erase_scope`, `refuse_erased`).

- An erased row leaves every offer by itself (`image_artifacts_from_program`, `file_artifacts_from_program`), and the sweep passes it.
- Whatever names one by its id, inside the fence that would let it read or send the row, answers in that same call (`ARTIFACT_ERASED`): `这张图存在过、有内容；字节在<time>被隐私清除删掉了，这一份不会再变回可读。`, or, for a row whose bytes had already expired (`bytes_removed_at`), `这个文件存在过、有内容；字节在<time>到期删掉了；<time>的一次隐私清除之后，这一份不会再变回可读。` (`这张图` for a picture, `这个文件` for a file). That holds for `read_image`, a `picture`, `file` or `sticker` part of `speak`, `attach_image`, keeping her own drawing as a sticker, a claim (`FILE_ERASED`) and the byte endpoint. Outside that fence the row is refused like any unknown id.
- A sticker she drew is stored where she drew it, so an erasure of that conversation covers it. Her shelf lists it with the sentence in its own field, `picture`, and the weekly review lists it first, adding `gone`. It stays on the shelf until she drops it. The stickers she collected and the candidate pool are stored in `global-safe`, which a conversation erasure does not touch.
- A row that still says `gridfs` but has no bytes answers `ARTIFACT_BYTES_MISSING`, in words; running the erasure again marks it.
- The same bytes arriving later are stored as a new row, never matched to the erased one.

## Schedules

Her plans and the program's rhythms, on DSH's Schedule service. For operators and anyone changing timing. Code: `src/asuna/schedule.py`, `src/asuna/schedule_rules.py`.

- Plans and rhythms are records of DSH Web's Schedule service; there is no second timer. The worker waits up to a minute at start for the service, and the start fails saying so when it does not come. With `mountSchedule: false` and no service, plans and rhythms are off.
- A due plan wakes its conversation as a program notice, not a platform input; the plan's person must still be a member of the route, or the owner on a line he joins (`SCHEDULE_ROUTE_REVOKED`). What she says goes out on that conversation's route.
- DSH's `schedule_*` tools are visible to every root agent in the Host; Asuna's presets restrict their own tools.

### Rhythms

The program's own plans (`schedule.RHYTHM_KINDS`): they never appear in her plan list, and her plan tool cannot cancel or retime them.

| Rhythm | Plan id | Runs when |
|---|---|---|
| heartbeat (`presence`) | `plan-asuna-presence` | `heartbeat.enabled` and `persona_runtime.<persona>.heartbeat_target` are set; every `heartbeat.every_min` (15–240) |
| nightly settlement | `plan-asuna-settlement` | her model or policy sets `rhythm.settle_at` and an IANA time zone is known |
| daily self-improvement | `plan-asuna-self-development` | `self_development.enabled` |
| night self-improvement check | `plan-asuna-self-development-night` | `self_development.enabled` and not `self_development.night: false`; a tick that only decides whether a night stage is due (`self_development.night_*`) |
| condensing quiet groups (`condense`) | `plan-asuna-condense` | while she is in any group |

- Her pace keys (`heartbeat.*`, `self_development.night_*`) and their ranges are the persona model's `CORE_WRITABLE_KEYS` ([Persona model](#persona-model)); she sets them with `set_policy`. Only the owner turns the heartbeat on or off.
- How a beat is gated, which roll it makes and what it carries is implemented in `src/asuna/schedule.py`, `src/asuna/dice.py` and `src/asuna/self_review.py`.

### What the owner sees

- DSH's task page (`@deepseek-ai/dsh-client-ui-schedule`, mounted by the core's `cordis.patch.yml`) lists each plan by her own words and each rhythm by its name (`schedule.RHYTHM_TITLES`), in the language of the browser that last opened the Web UI (`packages/cognition-core/src/ui-language.js`; the choice is kept in `<data>/ui-language.json`).
- `/heartbeat` in any session gives her one heartbeat now, skipping its gates, and answers with the next scheduled beat; it creates no model message.

## Integration and self-development

The managed integration (a channel adapter or a LAN device tool run in the sandbox), the tools built on its endpoints, and how her own changes are published. For operators, adapter authors and her action brain.

### Integration profile

`deployment.integration` (from `config/integration.local.json` beside `config/local.json`; example `config/integration.example.json`), checked by `src/asuna/integration.py` `validate_profile`.

| Key | Meaning |
|---|---|
| `enabled` | `true` turns the integration on (it also needs the sandbox) |
| `scene_id`, `person_id` | must be the local chat's (`INTEGRATION_PROFILE_BINDING_MISMATCH`) |
| `endpoints` | at most 8 (`INTEGRATION_ENDPOINT_LIMIT`), below |
| `adapter_config` | the adapter's settings; `adapter_config.host.channel_id` names the channel it serves (`ADAPTER_CHANNEL_NOT_CONFIGURED` when that channel is not configured) |

| Endpoint field | Rule | Meaning |
|---|---|---|
| `name` | `^[a-z][a-z0-9_-]{0,30}$`, unique | the alias tools name it by; `image` is the picture service |
| `host` | a private or loopback IP address | the device |
| `target_port` | 1–65535 | the device's own port |
| `port` | 1024–65535, unique | the local port an adapter's settings may name |
| `tls` | boolean | `import_integration_artifact` uses TLS without verifying the certificate |
| `read_only` | boolean | a description of the device, not enforced |

### Integration tools

| Tool | Owner grant | Agent-line grant | Contract |
|---|---|---|---|
| `integration_test` | yes | no | runs argv against a frozen copy of the development candidate's adapter, up to 60 s, with the real settings: it can act on a platform |
| `integration_start` | yes | yes | runs argv as the managed service from a frozen copy of the published adapter; restored at every start |
| `integration_stop` | yes | no | stops the service and its restoration |
| `integration_status` | yes | yes | process state and bounded logs; never platform delivery |
| `import_integration_artifact` | yes | no | one HTTP/1.1 GET of a path on an endpoint alias, no redirects followed, into the task folder |

- The owner grant comes with work the owner hands over in his local chat, his own platform DM or a home line he joins; the agent-line grant with a home round woken on an `agent` line (`integration.event_profile`).
- In argv, `/app` is the frozen adapter copy, `/data` its writable data folder and `/integration/config.json` its settings (also `$ASUNA_INTEGRATION_CONFIG`, `$ASUNA_INTEGRATION_DATA`). Commands are argument arrays, not shell strings.
- An enabled integration whose adapter serves a channel starts that kind's `SERVICE_ARGV` by itself when it was never started or stopped. After the profile changes outside the settings card, a started service waits for `integration_start` (`PROFILE_CHANGED_RESTART_REQUIRES_EXPLICIT_START` in `integration_status`).
- `import_integration_artifact` writes at most 4 MiB (default 1 MiB), keeps an existing file unless `overwrite`, and registers bytes that are a picture by file signature as her own image artifact (source `integration:`).

### Drawing and rendering

- `generate_image` drives the endpoint aliased `image` through that service's agent API (`project-comfyui-agent/v1`): `POST /project/resolve` (when no `workflow` is named), `POST /project/generate` with `batch_size` 1, `GET /project/jobs/{prompt_id}`, the first `/view` output; for a source picture `POST /upload/image` and `DELETE /project/inputs/{name}` (`src/asuna/integration_image.py`). `width` and `height` are 64–2048 in multiples of 8; `timeout` 30–300 s (default 180); a job still running is collected later with `job`. The picture is registered as hers (source `integration:image:<view path>`); an edit of someone else's picture is not hers and may go only back where it came from.
- `render_svg` turns an SVG in the task folder (at most 2 MiB, no XML entities) into a PNG with resvg in the Host (`packages/cognition-core/src/svg.js`), `width` 16–2048; the PNG is registered as hers (source `integration:svg:<path>`).
- Offline checks: `tests/test_image_generation.py`, `tests/test_svg_render.py`, `python3 tools/integration_import_offline_check.py`, `python3 tools/outbound_image_offline_check.py`.

### Private words

`private_words` (both brains) keeps the deployment's list of words that point at real people and places: `<data>/private/personal-words.txt` (`ASUNA_PRIVATE_WORDS` names another file), one `category|word|why` per line, categories `person`, `group`, `account`, `site`, `host`, `email`, `other` (`src/asuna/private_words.py`). An all-ASCII entry needs at least 3 characters and matches as a whole word; others need 2. Outside owner-private conversations it adds and summarizes but never removes. Nothing prints a listed word. `tests/test_personal_words.py` refuses a committed file that contains one, and is skipped where there is no list.

### Self-development

Her development tools work on persistent candidates of a project (the selected persona package by default; `core` for the cognition core) and publish them through the publication floor (`packages/cognition-core/src/floor.js` `PublicationFloor.publish`).

- The development grant needs `self_development.enabled` and the sandbox, and comes only in owner-private conversations: a turn woken by someone's words there, her self-improvement turn, a plan of hers coming due there, or a trusted note from another home conversation (`src/asuna/grants.py` `development_granted`).
- A publication probes the candidate's boot, packs it and commits its files in the project's source under `character_git` (else the checkout's identity), only those paths; a failed commit is reported as `commit_error`, leaves those paths unstaged and does not undo the publication. A path the source's repository ignores is not the project's: it is neither copied into the source nor committed, and the receipt lists it in `ignored_files`. The receipt's fields are the record built in `PublicationFloor.publish` plus the result of `commitPublished`.
- The publication's reason becomes the commit message. A reason carrying a word from the deployment's private list (`private_words`) or a run of 7–11 digits shaped like a QQ or group number is refused first, with `PUBLISH_REASON_NAMES_PRIVATE` naming the line, the category and the list line (never the word or the number); nothing is published (`packages/cognition-core/src/private-words.js`). The documentation placeholders `900000` and one to three digits (the test fixtures' numbers) are not numbers of anyone.
- The files the candidate changes that the publication commits (not those the repository ignores), and the reason, are checked as main is, before anything is frozen, packed, selected or committed (`tools/publication_scan.py`, run by `PublicationFloor.publicationFindings` on the worker's Python; the checkout's working copy of the scan and of the checks it imports runs at each publication, so a change there applies at once, without a restart): the private list and private addresses in every file and file name (as `tests/test_personal_words.py` and `tests/test_release_scan.py`), and in what the release ships the release's personal-data checks (`tools/check_staged_secrets.py --personal`, with its allow list, marker and placeholders) and the persona names (`tools/release.py persona_names`); the reason gets the private list and the personal-data checks. A hit is refused with `PUBLISH_CONTENT_NAMES_PRIVATE` (or `PUBLISH_REASON_NAMES_PRIVATE`) naming the file, line and category (a file whose name holds the hit is not named; the first 50 and the total), never the word. A scan that is in the checkout but cannot run (no Python, a crash, past 300 s), or cannot read a changed file, is refused with `PUBLISH_CONTENT_CHECK_FAILED`; nothing is published either way. The receipt's `content_check` says what ran: `checked`, checked without a private list (not configured: unchecked for it, not clean), or skipped and why (no checkout, a source outside it, a checkout without the scan); `content_scan` names the checks that ran (the first 12 hex digits of the sha256 of `tools/publication_scan.py` and `tools/check_staged_secrets.py`).

| Publication state | When | Takes effect |
|---|---|---|
| `ACTIVE` | the package is byte for byte the running one | at once; nothing restarts |
| `APPLIED` | any other change | a core publication restarts the worker; a persona or channel publication loads its resources and skills without a restart, and the next `integration_start` runs its adapter |
| `HOST_RESTART_REQUIRED` | a changed JavaScript file, `package.json`, `package-lock.json`, `cordis.patch.yml`, `uv.lock`, `pyproject.toml`, or a package's `python/` | at the next Host start |

While a project waits for a restart, a self-improvement turn cannot publish to it again (`DEVELOPMENT_PUBLISH_WAITING_RESTART`).

Each publication has its own receipt (`sink_receipts`, kind `self_development_publish`, id
`self-publish-<content identity>-<publication time>`), so content published again (a revert) is a receipt of its own;
a newer publication marks a project's earlier receipt still `APPLIED` or `HOST_RESTART_REQUIRED` as `SUPERSEDED`.
Beside the record's fields it says what happened:

| Field | Meaning |
|---|---|
| `activated` | `true` when this publication is what runs now: a persona or channel publication applied in place, or a package byte for byte the running one; otherwise `false` |
| `unchanged` | `true` when the package is byte for byte the running one (state `ACTIVE`): nothing was swapped in |
| `applied` | the worker's own lines for an in-place apply: persona model swapped or unchanged, skills swapped or unchanged, existing self heads preserved |
| `sha256` | the hash of the package archive (`.tgz`), the same value as in `activation.json` |

With Core running, a persona package is also read by the running worker before it is selected, as it would take it
on an in-place apply or at the next start (`persona.check`: its model loaded and its persona id checked, nothing
applied); one it would refuse ends `BOOT_FAILED` with the worker's reason, and nothing is selected or committed.

Each in-place apply writes one `Asuna publication:` line to `restart/host.log` (the project, the archive hash's first
12 characters and the worker's lines). The archive hash is not the persona text's hash: a turn's context manifest
carries `persona_sha256`, the hash of her persona document's text as that turn read it (`src/asuna/context.py`).
