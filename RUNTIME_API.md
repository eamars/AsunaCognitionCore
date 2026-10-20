# Asuna Runtime API

The interfaces of the Asuna runtime: what a channel adapter, a persona or channel package, an operator and her own action brain can rely on, each with its fields, limits, answers and codes, and a pointer to the code that implements it. It describes interfaces, not how her turns run inside; for that the code is the reference, and each section names where. Installation and operation: [RUN_ASUNA.md](RUN_ASUNA.md), [INSTALL.md](INSTALL.md). The DSH services Asuna relies on: [packages/cognition-core/DSH_API.md](packages/cognition-core/DSH_API.md).

## Contents

- [Process layout](#process-layout)
- [Configuration](#configuration): [plugin settings](#plugin-settings), [model routes](#model-routes), [secrets](#secrets), [deployment settings](#deployment-settings)
- [Channel API](#channel-api): [server and endpoints](#server-and-endpoints), [channels and routes](#channels-and-routes), [admission](#admission), [route keys](#route-keys), [receive an event](#receive-an-event), [platform notices](#platform-notices), [post a notice for her home](#post-a-notice-for-her-home), [claim public output](#claim-public-output), [fetch attachment bytes](#fetch-attachment-bytes), [record a platform receipt](#record-a-platform-receipt), [post a group's member list](#post-a-groups-member-list), [post the current media-link keys](#post-the-current-media-link-keys), [post her own mute in a group](#post-her-own-mute-in-a-group), [HTTP outcomes](#http-outcomes)
- [Persona packages](#persona-packages): [persona model](#persona-model)
- [Channel packages](#channel-packages): [kind module](#kind-module)
- [Her tools](#her-tools)
- [Action capabilities](#action-capabilities): [tools a task is given](#tools-a-task-is-given), [web search and fetch](#web-search-and-fetch), [skills](#skills), [sandbox](#sandbox), [credentials](#credentials)
- [Media and images](#media-and-images): [inbound media](#inbound-media), [reading images](#reading-images), [sending pictures](#sending-pictures)
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
- A failed worker is restarted after 1 second, at most 3 times; each restart is appended to `<data>/worker-restarts.jsonl` (`index.js` `workerFailed`, `restart`).
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
| `POST /v1/channels/{channel_id}/own_mute` | [Post her own mute in a group](#post-her-own-mute-in-a-group) | 256 KiB |

- Every request carries `Authorization: Bearer <token>`: the channel's token, or a [route key](#route-keys).
- A POST body is one JSON object. Unknown fields are refused on `events`, `notices`, `own_mute` and `receipt`; `members` and `media_keys` ignore them.
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
| `HOST_RECONFIGURING`, `HOST_STOPPING` | 503 | settings are being applied, or the worker is stopping |

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
| `supports` | comma-separated capabilities the adapter carries now (below) |

| `supports` name | Means the adapter |
|---|---|
| `image` | sends a picture with a message ([attachment](#fetch-attachment-bytes)) |
| `sticker` | sends stickers |
| `poke`, `react`, `recall` | performs that action (`recall` also: her line can be taken back) |
| `quote` | shows the line she quotes |
| `quote_in`, `react_in` | passes on what others quote, and reactions |

The answer is `{"items": []}` or `{"items": [item]}`. Each claim marks the item `SENDING` under a fresh `attempt_id`; claiming is not delivery.

| Item field | Meaning |
|---|---|
| `publication_id`, `attempt_id` | what to name in the receipt |
| `target` | `{"type": "dm" | "group", "id"}` to send to |
| `text` | her words; her @ of someone reads `@<kind>:<account>` (the kind's `outbound_mention`), `[表情:名字]` is a platform face by name; `""` for a sticker or an action |
| `reply_to` | platform id of the line her words answer, for a platform that needs a reply token; never shown as a quote |
| `quote` | platform id of the line she chose to quote, or `null`; shown only by an adapter that declares `quote` |
| `attachment` | `{artifact_id, media_type, sha256, size}` when `image` is declared and the message carries a picture |
| `sticker` | `{"kind": "custom"}` (send `attachment` as a picture marked as a sticker) or `{"kind": "market", "emoji_id", "emoji_package_id", "key", "summary"}` (a store sticker, no bytes) |
| `action` | `{"kind": "poke", "account"}`, `{"kind": "react", "message_id", "emoji_id"}` or `{"kind": "recall", "message_id", "line"}` |
| `admin` | an admin action (publication id `ga-…`, no `text`): `{"kind": "mute", "account", "seconds"}`, `unmute` or `kick` with `account`, `recall` with `message_id`, or a request's `accept` / `decline` |

- **Order.** A claim with the channel's token gets queued admin actions first. Messages come in conversation order; a part with `not_before` waits for its time, and a later part of one reply waits until the part before it is delivered (or she cancelled it).
- **Speaking in parts.** Where a kind declares `REPLY_PARTS`, one reply is several items, each sent as its own platform message and confirmed with its own receipt. A part that ends `failed` or `unknown` cancels the parts after it (`CANCELLED_AFTER_FAILURE`). A `recall` action takes back her own delivered line.
- **Not declared.** An action the claim does not declare fails its row (`CHANNEL_DOES_NOT_DECLARE_POKE`, `…_REACT`, `…_RECALL`); a sticker fails with `CHANNEL_DOES_NOT_DECLARE_STICKER`. A picture without `image` declared: the text goes out and the row records `attachment_skipped`.
- **Kept.** The host keeps each channel's last `supports` (`artifacts` kind `channel_capabilities`) across restarts; what she is offered there follows it (`src/asuna/capabilities.py`).
- A row whose route, member, policy epoch or task changed since it was queued is failed at claim time and not handed out (`PUBLICATION_MEMBER_REVOKED`, `PUBLICATION_CONTEXT_STALE`, `PUBLICATION_EPISODE_STALE`, `PUBLICATION_INTENT_STALE`).

### Fetch attachment bytes

`GET /v1/channels/{channel_id}/outbox/{publication_id}/attachment?attempt_id=…&artifact_id=…` — the bytes of the picture a claimed item declared, with the channel's token.

| Query | Required | Meaning |
|---|---|---|
| `attempt_id` | yes | the attempt of the current claim |
| `artifact_id` | no | narrows the request; a different artifact is refused, never substituted |

The answer is the bytes with `Content-Type` from their file signature, re-checked against the row's `sha256`. The adapter checks the digest and signature again; only a platform receipt says the picture arrived.

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

Implemented in `src/asuna/outbound_media.py` (`serve`).

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
| `platform_message_id` | string | for `platform_accepted` of a message | the platform's id of the sent message; not for an action or admin action |
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

### HTTP outcomes

| Status | When |
|---|---|
| 200 | the answers above; attachment bytes |
| 400 | malformed JSON, a body size outside its limit, a field out of shape, or a path outside `/v1/channels/{channel_id}/…` |
| 403 | authentication (an unknown channel included), route, identity, capability or receipt refused |
| 404 | an unknown endpoint of an authenticated channel |
| 503 | the worker is reconfiguring or stopping, or failed; it records a redacted diagnostic (`host.channel_error`) |

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
| `CORE_WRITABLE_KEYS` (`render.budget_tokens`, `heartbeat.*` pace and visits, `heartbeat.dice_*`, `self_development.night_*`) | a package may default them; she sets them with `set_policy` within their ranges |
| `OWNER_KEYS` (`heartbeat.enabled`) | a package may default it; only the owner changes it |
| `policy_keys` | keys the package declares for her; may not redeclare core keys |

| Key | Core default | Meaning |
|---|---|---|
| `render.budget_tokens` | 6144 (256–12,288) | estimated-token budget of her persona and voice render |
| `render.max_window_share` | 0.25 | the render never takes more of the character route's window than this |
| `render.action_persona` | `core` | who the action brain is told she is: `core` (her core sentences), `values` (public sections tagged `render.values_tag`), `persona` (the persona's every-turn sections) |
| `render.values_tag` | `values` | the tag `values` reads |
| `people.owner_label` | `本机用户` | the start of the owner's label in her conversations |
| `people.self_names` | `[]` | other names she answers to in groups |
| `people.familiarity` | `{}` | her words and stance for each familiarity level |
| `speak.max_messages` | 1 | her usual lines of `speak` text in one turn: past it the text is sent and the result gives the count; past `role_tools.SPEAK_HARD_LINES` a call is refused |
| `speak.chars_per_second`, `speak.min_gap_s`, `speak.max_gap_s` | 12, 1, 5 | typing pace between her parts |
| `heartbeat.enabled` | `false` | her heartbeat ([Schedules](#schedules)) |
| `self_review.tag` | — | the tag of her own sections her reviews read |

Every other group (`affect`, `memory`, `recall_protocol`, `phrasing`, `rhythm.settle_at`, `self_development.every_min`) is defined in `CORE_DEFAULTS` and the schema.

A seed section tagged `place:home`, `place:peer`, `place:group` or `place:dm` renders only in turns at that place; an untagged one everywhere (`src/asuna/visibility.py` `PLACES`). An edit that would grow her persona or voice past the render budget is refused (`PERSONA_RENDER_OVER_BUDGET`); one that shrinks it applies.

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
| `FACES`, `STICKERS` | no | the platform's faces by name → id; whether it sends stickers |
| `HOME` | no | its conversations are home ones (owner-private) |
| `TEXT_ONLY` | no | it carries no pictures |
| `OWNER_JOINS` | no | the owner is a member of each line and writes there from the Web |
| `PEER_LINE` | no | she opens and closes each direct line herself |
| `ROUTE_KEYS` | no | each route has its own key ([Route keys](#route-keys)) |
| `MARKS_ANSWERS`, `answerer(scene)` | no | who on a line marks the lines that answer her questions |
| `REQUESTS` | no | its adapter posts friend and group requests ([notices](#post-a-notice-for-her-home)) |
| `REPLY_PARTS` | no | she speaks there only in these parts (`text`, `sticker`, `picture`, `poke`, `react`, `recall`) |
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
| a conversation's tool list, fixed when its session starts | `src/asuna/role_tools.py` (`session_specs`) |
| the context blocks a turn carries, their limits, and their words | `src/asuna/context.py` (`ContextBuilder`), `src/asuna/context_budget.py`, `src/asuna/block_guide.py` |
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
| workspace: `list_files`, `read_file`, `write_file` | `tasks.py` `WORKSPACE_TOOLS` | every task |
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

### Web search and fetch

- `web_search` is DSH's tool with 10 sources and a `detail` argument (`titles`: title, link and date only); snippets are cut to `search.snippet_chars` (default 300). Its backend is the core's `asuna-search` provider, which tries `deployment.search.order` (default `searxng`, `gemini`, `exa`, `deepseek-official`) per query (`packages/cognition-core/src/search.js`). Settings: [RUN_ASUNA.md](RUN_ASUNA.md#web-search).
- `web_fetch` is DSH's tool over the core's `asuna-fetch` provider: at most 5,000,000 bytes, 30 seconds and 5 redirects; a Cloudflare challenge page answers `WEB_HUMAN_VERIFICATION` (`packages/cognition-core/src/fetch.js`).

### Skills

A task sees skills by where it came from (`src/asuna/skills.py`): from an owner-private conversation every skill root; otherwise only skills whose `SKILL.md` header lists that place in `scene_kinds` (`home`, `group`, `dm`; absent means `home` only). A header with an unknown key or kind is refused at publication (`python -m asuna.skills`).

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
| temporary folder | `TEMP`, `TMP`, `TMPDIR` = `.tmp` inside its own folder (for `development_run`, only in a core candidate) |
| git | nothing prompts (`GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`; not set for `development_run`); with `character_git` set, a home task's commits carry her name as author and committer |
| home task's commands | also `ASUNA_MONGO_URI`, `ASUNA_DATABASE`, `ASUNA_TIMEZONE` for `asuna.dbread` (`src/asuna/dbread.py`; skill `asuna-database`) |
| working copy | each home place's folder holds `working-copy`, a full clone of the checkout whose `origin` is the checkout's origin; made at start when missing, never changed after (`packages/cognition-core/src/working-copy.js`) |

- `deployment.sandbox.backend` is `auto` (use the Host's sandbox when it has one) or `none`. Without a sandbox, `sandbox_run`, `generate_image`, the managed integration, persona jobs and self-development are off (`SANDBOX_UNAVAILABLE` if called).
- On Windows the Host must be able to change permissions on the data folder.

### Credentials

A credential is a name (`^[a-z][a-z0-9-]{1,31}$`), a note and at most 6 environment variables; its values live only in DSH's credential store, one record `asuna-cognition-core/<name>` (`src/asuna/credentials.py`).

- She files and drops one with her `credential` tool in her local chat; a turn sees names, notes and variable names, never a value.
- Only a task from home may use one: `sandbox_run` with `credentials` sets those variables for that command (`CREDENTIALS_HOME_ONLY` elsewhere).
- Every stored value is replaced by `[凭据已隐藏]` in tool results, briefs, messages to the action brain and reports.

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

- At most 8 items of a message are listed (`MAX_ITEMS_PER_MESSAGE`). Each gets a reference `att-…`; a reference stays readable for 7 days (`REF_DAYS`).
- A picture the owner attaches in her local chat is stored by the core plugin as an image artifact and recorded on the input as `raw.asuna_media` with `origin: local_upload`. Only the program's own input can carry that origin.

### Reading images

`read_image` (both brains) takes a reference, a stored image's `artifact_id`, or in an owner-private conversation a file path. It is offered only where the brain's route declares image input and `vision.image_hosts` is not empty.

| `vision` setting | Default | Effect |
|---|---|---|
| `image_hosts` | the hosts the installed kinds declare (`IMAGE_HOSTS`) | hosts a link may be fetched from (an entry starting with `.` allows its subdomains); `[]` refuses every link |
| `max_bytes` | 8 MiB | fetch limit; never above 8 MiB |
| `timeout_seconds` | 15 | fetch timeout |
| `image_dirs` | none | local folders a bare file name is read from |
| `allow_insecure_http` | `false` | allow `http` links |

- Bytes are accepted as PNG, JPEG, WebP or GIF by file signature. A video (at most 32 MB, `VIDEO_MAX_MB`) is read as a contact sheet and not kept; an animated picture is read as a contact sheet too (`src/asuna/animated.py`).
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
- A publication probes the candidate's boot, packs it and commits its files in the project's source under `character_git` (else the checkout's identity), only those paths; a failed commit is reported as `commit_error` and does not undo the publication. The receipt's fields are the record built in `PublicationFloor.publish` plus the result of `commitPublished`.

| Publication state | When | Takes effect |
|---|---|---|
| `ACTIVE` | the package is byte for byte the running one | at once; nothing restarts |
| `APPLIED` | any other change | a core publication restarts the worker; a persona or channel publication loads its resources and skills without a restart, and the next `integration_start` runs its adapter |
| `HOST_RESTART_REQUIRED` | a changed JavaScript file, `package.json`, `package-lock.json`, `cordis.patch.yml`, `uv.lock`, `pyproject.toml`, or a package's `python/` | at the next Host start |

While a project waits for a restart, a self-improvement turn cannot publish to it again (`DEVELOPMENT_PUBLISH_WAITING_RESTART`).
