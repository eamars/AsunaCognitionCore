# Asuna Runtime API

This document describes the current host contract. The Python host uses the pinned DSH runtime for its character and action lanes. Platform adapters translate their platform events into the normalized channel API below; the host does not parse a platform's wire protocol.

## Runtime responsibilities

`RuntimeHost` owns the application, the Web-reused `Chat` controller, memory indexing and background summaries, the native DSH schedule service, and any configured channel or integration services. The Web UI uses `Chat.submit`, `Chat.new_context`, and the host's scoped records directly; it does not use the terminal adapters.

Inbound work is persisted before retrieval or model calls. Character turns and action tasks use separate queues. The host binds each turn and task to a scene, person, policy epoch, and capability set. A new context changes the DSH conversation context while retaining persisted scene memory.

The character brain decides whether to answer, reflect, manage a plan, or delegate an action. The action brain uses the DSH loop and the tools granted to its task. `RETURNED` means the action turn returned; it does not establish that the requested goal was completed. The action brain may return a natural-language result; it is not required to call `task_status`.

Ordinary tool errors are returned to the active DSH action loop so it can inspect the error and continue. A task revision, cancellation, changed policy epoch, or expired lease fences further calls. The host records tool inputs and results as artifacts; result claims are checked against those records and any required effect receipts.

The active action lane uses DSH's native agent loop. Asuna does not add a fixed action-step termination limit or reject turns using a separate token-budget gate. Token measurements are observational; context pressure is handled through DSH compaction, including the bridge's pending-input pressure check.

## Configuration

- `config/local.json` is the local base configuration. The example is `config/local.example.json`.
- Model settings may be overridden in an adjacent `*.models.local.json` file. The character and action routes are independent; either may use the same or a different configured provider and model.
- An adjacent `asuna-channel.local.json` is loaded only when `enabled` is `true`. Its example is `config/asuna-channel.example.json`.
- An adjacent `integration.local.json` provides the optional owner-bound managed integration profile. Its example is `config/integration.example.json`.
- Credentials, account IDs, scene IDs, provider addresses, and local paths come from deployment configuration. They are not fixed by lane name or stored in this contract.

## Channel API

When channel routes are configured, the host binds the channel server to `127.0.0.1`; the default port is `8766`. It is separate from the Web UI and is not exposed through the Web proxy. Each configured channel has a unique bearer token of at least 24 characters. A route binds the platform account, sender, Asuna person, scene, and publication target.

All endpoints require:

```http
Authorization: Bearer <channel-token>
```

POST bodies are JSON objects, limited to 256 KiB. Unsupported envelope fields are rejected.

### Receive an event

```http
POST /v1/channels/{channel_id}/events
Content-Type: application/json
```

Direct message example:

```json
{
  "route_id": "authorized-dm",
  "account_id": "configured-account",
  "sender_id": "configured-sender",
  "event_id": "platform-event-id",
  "text": "Message text",
  "occurred_at": "2026-01-01T00:00:00Z"
}
```

`route_id`, `account_id`, `sender_id`, `event_id`, and `text` are required. `occurred_at` and `raw` are optional. Text is limited to 16,000 characters. The host derives person, scene, and target from the route; callers cannot supply a scope, task, or internal episode kind.

Group events use the same endpoint and add `group_id`, `mentioned_account_ids`, and optionally `reply_to`. These values must come from the adapter's parsed platform event. Direct-message routes reject group-only fields. The host checks the configured group and member bindings. A group event wakes the character only under the configured mention and saved-reply rules; other authorized group messages can be persisted without starting a character turn.

The host persists accepted input before any retrieval or model call and returns:

```json
{"status":"accepted","episode_id":"ep-…","received_at":"…"}
```

An identical event for the same channel, account, route scene, and platform event ID returns `duplicate` without a second queue entry. Reusing an event ID with conflicting identity or content is rejected. `accepted` confirms durable host receipt, not a reply or publication.

Adapters that normalize media may provide bounded metadata under `raw.asuna_media`. The host does not interpret arbitrary platform payloads. Media metadata and an image placeholder do not mean the character brain has seen the image; image reading is described below.

### Claim public output

```http
GET /v1/channels/{channel_id}/outbox?wait_seconds=25
```

`wait_seconds` is capped at 25. The host atomically claims a queued public `SPEAK` message and returns its frozen target, text, publication ID, attempt ID, and optional platform reply target. Internal monologue, reasoning, traces, and tool output are never placed in the outbox.

The adapter sends only the returned text to the returned target. Starting an adapter or claiming a message is not a platform receipt.

### Record a platform receipt

```http
POST /v1/channels/{channel_id}/outbox/{publication_id}/receipt
Content-Type: application/json
```

```json
{
  "attempt_id": "claimed-attempt-id",
  "status": "platform_accepted",
  "platform_message_id": "platform-message-id",
  "response": {"platform": "response"}
}
```

`status` is `platform_accepted`, `failed`, or `unknown`; `response` must be an object. `platform_accepted` requires a non-empty `platform_message_id` and records `DELIVERED` with `delivery_basis=platform_ack`. It means the platform accepted the message, not that a person read it. A matching receipt may be repeated idempotently; a conflicting attempt or terminal receipt is rejected.

If the send result cannot be determined, the adapter records `unknown`. A host restart converts an in-flight `SENDING` attempt to `UNKNOWN`. The host does not automatically claim it again. A later definitive receipt for that same attempt may resolve the state.

### HTTP outcomes

- `400` — malformed JSON, invalid size, or invalid field values.
- `403` — authentication, route, identity, capability, or receipt denied.
- `404` — unknown channel endpoint.
- `503` — host-side service failure; the host records a redacted diagnostic.

## Action capabilities

Action tool visibility is bound to the persisted task grant and route configuration. The action lane receives the DSH-native `skill`, `todo_write`, `web_search`, and `web_fetch` capabilities, plus Asuna tools allowed for that task.

Asuna tools include scoped workspace operations, history search, structured discussion digest, optional `consult_character`, and `read_image` when the action route declares image input. Owner grants can add managed integration tools or self-development tools. A tool being registered does not grant it to every task.

`consult_character` is optional internal advice in the task's authorized character context. It does not create a public reply, a new task goal, or additional authority. The action session resumes with the returned advice or error.

## History, retrieval, and summaries

Conversation and memory records are scoped by scene and policy epoch. Memory indexing runs in the background. History search reads authorized inbound messages and delivered `SPEAK` messages; it can return literal matches and, when available, semantic candidates. It does not turn a derived summary into a verbatim quote.

Structured discussion digests use the same scene-bound history reader. They report their actual time and source coverage, preserve source references, and identify partial results rather than claiming an unread window was fully covered.

Background dialogue summaries process new messages in direct-message and authorized-group scenes after the summary boundary is initialized. They include inbound messages and delivered public `SPEAK` messages, and do not block the conversation. Each summary stores its source IDs, source window, participants, and per-speaker attribution. The participant list is computed from stored authors, not inferred by the summarizing model. Correction annotations resolve only against records in the same scene and policy epoch; unresolved references remain unresolved. When a later correction points to an earlier summary, the host appends a correction marker without rewriting the earlier summary text. A summary is evidence for a person only when its recorded participants include that person.

## Media and image reading

An adapter may normalize non-text segments into bounded `raw.asuna_media` metadata. The host preserves placeholders and does not treat them as visual input. The action task receives a bounded list of image attachments from its own scene and policy epoch.

The action brain can call `read_image({"ref": "…", "max_bytes": 4194304})` when `executor.input_modalities` includes `image`. The reference selects an attachment already visible to that task; it cannot change the scene. URL fetching requires an allowed host and safe redirect, enforces a byte limit, and accepts PNG, JPEG, WebP, or GIF data identified by file signature. An optional local image directory can also be configured. Pulled bytes are stored through the scoped blob store and passed to DSH as a durable image attachment. The stored tool receipt contains metadata and blob references, not base64 image bytes.

The default byte limit is 4 MiB and the hard limit is 8 MiB. Host allowlists, timeout, local directories, and insecure HTTP policy are configured under `vision`. Unsupported routes, disallowed sources, and fetch failures return errors; placeholders are not reported as viewed images.

## Schedules

The host uses DSH's native scheduler; it does not run a second host timer wheel. Scheduling, updating, or cancelling a plan is a character decision in the authorized scene. A due plan re-enters that scene and asks the character to decide what to do. A due event is not new authorization and does not mean its requested work has completed. Plan status and policy epoch are checked before dispatch.

## Managed integration and self-development

The managed integration runner is available only to the configured local owner profile. It uses a separate persistent development directory. `integration_test` runs a frozen, read-only `/app` snapshot with separate writable `/data`; `integration_start` enables a new frozen snapshot as a managed process; later development edits are not deployed automatically. `integration_status` reports process state and bounded logs, not platform connectivity or delivery. `integration_stop` stops the managed process and disables host restart restoration.

Integration processes run in the configured isolated environment and can reach only explicitly configured local or LAN TCP endpoints. Their commands are argument arrays, not host-shell strings. Connection credentials are supplied through the local integration profile and are not copied into ordinary task files.

Self-development uses a persistent project candidate separate from ordinary task workspaces. Its tools inspect, edit, and run candidate files, read bounded records from the existing database, and publish a frozen candidate only after a non-consuming boot probe succeeds. Publication requests a host restart before the new runtime becomes active. These capabilities are available only through the self-development or owner-granted path.
