# Asuna Runtime API

This is the current business contract for the two native DSH plugins. See [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md) for composition and [RUN_ASUNA.md](RUN_ASUNA.md) for installation. DSH owns model execution and Web sessions; its managed Python worker preserves the existing normalized channel API below.

## Runtime responsibilities

`RuntimeHost` inside the business worker owns Application, the queue/action `Chat` controller, memory indexing and summaries, and configured channels/integrations. The Core Host plugin owns actual native agents and the DSH schedule service. Native composer input enters through SessionController and is associated with persisted input by native message ID; the Web UI never reads a parallel Asuna chat store.

Inbound work is persisted before retrieval or model calls. Character turns and action tasks use separate queues. The host binds each turn and task to a scene, person, policy epoch, and capability set. A new context changes the DSH conversation context while retaining persisted scene memory.

The character brain decides whether to answer, reflect, manage a plan, or delegate an action. The action brain uses the DSH loop and the tools granted to its task. `RETURNED` means the action turn returned; it does not establish that the requested goal was completed. The action brain returns a natural-language report; the program attaches the actual tool receipts. Delegation requires a workspace grant for the scene (the owner's local scene, or a channel route that names a workspace). The action brain's system prompt is `executor.md` plus the persona: with persona model `render.action_persona: values` (core default) only public sections tagged `render.values_tag`; with `persona` the persona document's every-turn sections readable in the class of the conversation the task came from. It never receives memory, relationships, emotion or other state.

Where the program needs a model's answer before it can go on (each role stage, the relevance gate, an appraisal, the action brain's report, a dialogue summary), the answer is checked deterministically: it stopped on its own, it has text (thinking alone is not an answer; tool calls count only for the action brain), and it has that point's shape (DECIDE's JSON and schema, SELF's two fields, the gate's 接话／不理 first line, the appraisal's JSON array). A failed check goes back to the model in the same session as a program note that names the problem and what the point needs, the way DSH returns a failed tool call, and the point asks again. After two repairs it fails with the named problem: a role stage fails its episode, the gate lets the message pass quietly, an appraisal is skipped, an action ends `BLOCKED`, and a summary waits for its next run. Transport errors and empty completions are retried by DSH's own retry first, and an interrupted turn is not repaired. Each failed check is audited (`phase.rejected`, `execution.rejected`, `summary.rejected`).

Ordinary tool errors are returned to the active DSH action loop so it can inspect the error and continue. A task revision, cancellation, changed policy epoch, or expired lease fences further calls. The host records tool inputs and results as artifacts; result claims are checked against those records and any required effect receipts.

The active action lane uses DSH's native agent loop. Asuna does not add a fixed action-step termination limit or reject turns using a separate token-budget gate. Token measurements are observational; context pressure is handled through DSH compaction, using the selected native model metadata.

## Configuration

- `config/local.json` is the initial migration source. The example is `config/local.example.json`. After migration the DSH profile's Core `deployment`, `secrets`, `channelAdmission` and route settings are authoritative.
- Model credentials and initial route defaults may be supplied in an adjacent `*.models.local.json` file; after installation active routes are saved in the native profile. The character and action routes are independent; either may use the same or a different configured provider and model.
- An adjacent `asuna-channel.local.json` is loaded only when `enabled` is `true`. Its example is `config/asuna-channel.example.json`.
- An adjacent `integration.local.json` provides the optional owner-bound managed integration profile. Its example is `config/integration.example.json`.
- Credentials, account IDs, scene IDs, provider addresses, and local paths come from deployment configuration. They are not fixed by lane name or stored in this contract.

Core's native plugin settings page uses DSH's settings mirror, staged form controls, revision fence and durable profile writes. Business secrets are write-only values referenced by `{"$secret":"name"}`; LLM secrets remain in DSH's provider credential store. Save performs model-free validation. Apply quiesces ingress and background summaries at an idle user/action boundary, restarts the worker, and reloads an already-enabled adapter from the installed channel package. A settings startup failure restores the previous runtime configuration while retaining the saved proposal for correction.

Native `asuna/stage` informational events attribute each actual request's `turn`, `step`, `operation`, `lane` and `phase`. Stage input notices also retain `source.lane`; `asuna/stage-result` links the final original assistant sequence to the same attribution. These envelopes are ignorable by plain DSH readers and contain no duplicate assistant content. Client projection uses DSH's location store and original assistant events, including native stream settlement and older-page loading. Brain names describe responsibilities, independently of provider/model. Only a recorded `SPEAK` phase is an outward-expression generation; neither an arbitrary closing assistant text nor a successful model call is a platform delivery receipt.

Host restart marks unfinished managed actions/results `PAUSED` with `pause_reason=host_restart` and advances their fencing token; it does not enqueue action execution or old result feedback. Native execution bindings, artifacts and results remain intact. A new explicit request in the existing local conversation may produce a `continue_task_id` decision that reuses the prior execution binding under a new task grant. Internal opportunities and stale feedback cannot resume paused work. Pending feedback checks its original durable input's task/revision before and after model stages and at effect boundaries. Cancellation, revision or restart pause suppresses further stages; completed public history is retained. An in-flight output may remain in diagnostics, but it cannot become another decision or publication after suppression.

A character `delegate` decision referencing its own READY/RUNNING task through `continue_task_id` revises that task in place, advances its intent revision and fences the prior execution. The Host cancels the exact old native operation and waits for source teardown before resuming that same action history. Tool calls carry their immutable operation binding; a delayed old call cannot acquire the successor's grant from a mutable session record. Task context prioritizes live work and then durable input time, rather than the number of database writes, so recently returned work remains available for continuation.

Continued tasks on the same authorized execution binding reuse their actual native action session via `agents.create/resume`. Each task receives its current grant and system context; a different role, actor or policy epoch cannot import the old source. The plugin admits a successor after the preceding native Turn and handle teardown, without blocking its business result acknowledgement. Main Chat references a separate, disjoint source range for each task and consultation segment. Receipt replay does not create another range or execute a completed stage. The business-bound action preset uses foreground native handles; it does not accept generic human prompts through DSH's continuation manager, which inherits the role preset rather than the required action composition.

## Channel API

When channel routes are configured, the host binds the channel server to `127.0.0.1`; the default port is `8766`. It is separate from the Web UI and is not exposed through the Web proxy. Each configured channel has a unique bearer token of at least 24 characters. A route binds the platform account, sender, Asuna person, scene, and publication target.

A configured channel's id names its platform (`channels.qq`), and that platform's channel package must be installed. A channel package (`packages/napcat-qq`) calls `registerChannel({kind, title, project, resource_root, python, module, integration_directory, skill_directories})`. Its Python kind module gives the platform's id formats (`qq:<account>`, `qq:<bot>:<dm|group>:<target>`), how the adapter writes a real @ in inbound text and how her @ reaches it, the media hosts vision may fetch from by default, and the adapter's derived settings. Its adapter is the integration that her owner-granted `integration_*` tools develop and run, from the package's own development project. Its skill joins her skill directories. A platform's conversations live in a workspace named by its title.

`channelAdmission=automatic` admits authenticated, valid platform messages from previously unknown DMs/groups/members. The adapter derives `auto-dm-<id>` / `auto-group-<id>` route IDs; existing configured targets keep their routes. Core persists admissions in the existing `artifacts` collection and creates separate per-member channel workspaces without owner grants. An automatically admitted group member does not start another conversation or bump the group's authorization epoch. Removals/blocking revoke membership; old task epochs remain fenced. `explicit` requires configured enrollment. Both modes honor channel `blocked_senders` and `blocked_groups` before admission and outbox delivery.

Receipt projects to the target's real native QQ conversation before inference, including non-waking group activity. It uses the original durable input ID to deduplicate; an acknowledgment in `sink_receipts` permits projection retry after interruption without replaying execution. Historical rows predating projection migration remain in Memory. DSH requires a conversation's first visible entry to be the system head her agent writes on its first step, so until she has had a turn in a conversation its lines wait in that conversation's DSH inbox (next-step, the newest 40; older ones stay in Memory). Her first step there claims them right after the head, in arrival order and before the stage notice, which leaves out of its history what they already show. A line that arrives while that first turn is starting waits for its head. DSH lists a conversation in the sidebar from its first turn. The Web composer is view-only for QQ; native archive hides until the next platform activity.

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

`route_id`, `account_id`, `sender_id`, `event_id`, and `text` are required. `occurred_at` and `raw` are optional. Text is limited to 16,000 characters. The host derives person, scene, and target from the route; callers cannot supply a scope, task, or internal episode kind. Of `raw`, the host stores only the sender profile in `raw.asuna_peer` after checking it against the authenticated sender and group, the media block in `raw.asuna_media`, and `raw.group_name`; the platform event itself is not stored. Every QQ person, configured or automatically admitted, is `qq:<account>`.

Group events use the same endpoint and add `group_id`, `mentioned_account_ids`, and optionally `reply_to`. These values must come from the adapter's parsed platform event. Direct-message routes reject group-only fields. The host checks the configured group and member bindings. A group event wakes the character only under the configured mention and saved-reply rules; other authorized group messages can be persisted without starting a character turn.

A group message wakes her for one of five reasons. An @ of her account or a reply to a message of hers runs her full turn. Three reasons go through the relevance gate first:

- a reply inside a thread she was in;
- her name without an @ (her display name or the persona's `people.self_names`);
- the proactive rules of a group that opted in.

The gate is one short request in a small per-group child session (`asuna-attend-…`, preset `asuna-attend`). It runs on the character route at a low effort, and compacts at about 5% of the context window. It reads only words:
- why she is asked;
- the speaker's label, notes and familiarity;
- the lines since she last spoke there (at least 10, at most 60 minutes back, at most 40 lines);
- how long ago that was;
- her public mood.

She answers 接话 or 不理 with a short reason. An answer in another shape is told so and asked again; after two repairs, or when the gate cannot answer at all, the message passes quietly. 不理 commits the episode before any recall (`processing_outcome: ATTEND_QUIET`). 接话 prepares her full context, says her reason in `attend_from_program`, and continues (`ATTEND_JOIN`). Every other message is stored without a turn.

In a group, a turn's history covers the same catch-up window, and never fewer than the last 12 lines. `deployment.reasoning_effort` sets the character route's effort per stage, where the model offers it: `attend` (default `low`) for the gate, and `group` for group turns. The local chat keeps the route's own effort.

The host persists accepted input before any retrieval or model call and returns:

```json
{"status":"accepted","episode_id":"ep-…","received_at":"…"}
```

An identical event for the same channel, account, route scene, and platform event ID returns `duplicate` without a second queue entry. Reusing an event ID with conflicting identity or content is rejected. `accepted` confirms durable host receipt, not a reply or publication.

Adapters that normalize media may provide bounded metadata under `raw.asuna_media`. The host does not interpret arbitrary platform payloads. Media metadata and an image placeholder do not mean the character brain has seen the image; image reading is described below.

### Claim public output

```http
GET /v1/channels/{channel_id}/outbox?wait_seconds=25&supports=image
```

`wait_seconds` is capped at 25. The host atomically claims a queued public `SPEAK` message and returns its frozen target, text, publication ID, attempt ID, and optional platform reply target. Internal monologue, reasoning, traces, and tool output are never placed in the outbox.

`supports` is an optional comma-separated list of what the adapter can handle today (`supports=image`). An adapter that does not declare a capability receives text only. When a message carries an accepted image and the adapter declared `image`, the item also carries `attachment` metadata — `{artifact_id, media_type, sha256, size}`, never base64; the bytes come from the endpoint below. When the adapter did not declare it, the text still goes out and the message row records that the picture did not (`attachment_skipped`), so delivered history cannot later claim an image arrived that never left the host.

The adapter sends only the returned text — plus the declared attachment, when the item carries one — to the returned target. Starting an adapter or claiming a message is not a platform receipt.

### Fetch attachment bytes

```http
GET /v1/channels/{channel_id}/outbox/{publication_id}/attachment?attempt_id=…&artifact_id=…
Authorization: Bearer <channel token>
```

The same channel token authorizes this request. It returns the bytes of the one artifact that this publication's own claim declared, with `Content-Type` taken from the file signature. Only a publication currently in `SENDING` whose `attempt_id` matches the request may read it. The artifact must belong to that message's own scope, and the stored bytes are re-verified against the row's `sha256` before anything is written to the socket. `artifact_id` is optional and only ever narrows the request: a different artifact is refused, never substituted.

A row that records `attachment_skipped` is treated as never having declared the picture: its metadata stays on the row so delivered history can say the message was meant to carry one, and the byte endpoint refuses it with `ATTACHMENT_NOT_DECLARED` rather than handing out bytes for an image that never went out. A later claim that does carry the image clears that marker, so the flag always describes the current attempt.

Refusals are `403` with a code — `PUBLICATION_NOT_FOUND`, `PUBLICATION_ATTEMPT_MISMATCH`, `ATTACHMENT_NOT_DECLARED`, `ATTACHMENT_ARTIFACT_DENIED`, `ATTACHMENT_SCOPE_DENIED`, `ATTACHMENT_SHA_MISMATCH`, `ATTACHMENT_HASH_MISMATCH`, `ATTACHMENT_NOT_AN_IMAGE`, `ATTACHMENT_OVER_LIMIT`, `ATTACHMENT_MEDIA_TYPE_MISMATCH` — and carry no partial body. The adapter re-checks the digest and the file signature on its side. Neither side treats a successful claim as proof the image arrived: only a platform receipt says that.

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

Asuna tools include scoped workspace operations, history search, structured discussion digest, optional `consult_character`, and `read_image` when the action route declares image input. Owner grants can add managed integration tools or self-development tools. A tool being registered does not grant it to every task. `import_integration_artifact` belongs to the managed integration group, not to the ordinary workspace group: a QQ task's grant never carries it.

`consult_character` is optional internal advice in the task's authorized character context. It does not create a public reply, a new task goal, or additional authority. The action session resumes with the returned advice or error.

## History, retrieval, and summaries

Conversation and memory records are scoped by scene and policy epoch. Memory indexing runs in the background. History search reads authorized inbound messages and delivered `SPEAK` messages; it can return literal matches and, when available, semantic candidates. It does not turn a derived summary into a verbatim quote.

Structured discussion digests use the same scene-bound history reader. They report their actual time and source coverage, preserve source references, and identify partial results rather than claiming an unread window was fully covered.

Background dialogue summaries process new messages in direct-message and authorized-group scenes after the summary boundary is initialized. They include inbound messages and delivered public `SPEAK` messages, and do not block the conversation. Each summary stores its source IDs, source window, participants, and per-speaker attribution. The participant list is computed from stored authors, not inferred by the summarizing model. Correction annotations resolve only against records in the same scene and policy epoch; unresolved references remain unresolved. When a later correction points to an earlier summary, the host appends a correction marker without rewriting the earlier summary text. A summary is evidence for a person only when its recorded participants include that person.

## People in conversations

Identity is the account: an author's `person_id`, mapped to its canonical person by `canonical_persons`. That mapping is read from configuration only, so removing an alias immediately ends owner-private access for that entry point. A display name never decides who someone is. Each person gets a fixed label in each scene the first time they appear (`[name #n]`, stored in `scene_people`). The number never changes, so renames, members who share a name, and compaction neither merge nor split people. Names come from the verified platform profile on that person's own messages; a name the operator set in `identities.display_name` takes precedence for everyone except the owner. Names are NFKC-normalized, reduced to one line of visible characters, and stripped of the characters labels are built from (`[ ] 【 】 「 」 『 』 # < >`).

In the character's conversation, a QQ message is its label line followed by the message text indented by two spaces. A reply adds an indented `> 回复 <label>：<excerpt>` line. An @mention of a known person reads as that person's label, and a mention of her own account reads as her name. After the label, the program notes in words: a group owner or admin role, another member with the same or a look-alike name, a name containing the owner's label or her own name, and a rename within the last 24 hours. The owner's label starts with the persona's `people.owner_label` (core default `本机用户`) and is decided by account. Context blocks name authors by `speaker` label instead of author ids, and a recalled summary gives `who`, `about_current_speaker` and correction sentences. The summarizing model receives the same labels. QQ numbers stay in program data. Her context names conversations instead of giving their ids: `scene` is 本机私聊, 群聊「name」 or 私聊 with the person's label, and a row or memory from another conversation carries that conversation's name (a shared memory reads 不分场合, an owner-only one 只在私下). Scene ids, scope keys, policy epochs and platform message numbers are not in her context.

To @ someone in a group she writes their label (`@[name #4]`, or `@#4`). The outbox turns it into the adapter's `@qq:<account>` marker when the item leaves the host; the stored message keeps the label, and a label that names nobody in the scene is sent as a plain `@name`. A stored `@qq:<account>` reads back to her as the label.

The history and discussion-digest tools take `person` as a label, a `#number`, an id, or a name. A name resolves against the scene's people (current, former and operator-given names, and names shown on their own verified messages); when it matches several people the tool answers with their labels and runs no query, and the filter is always by author, never by a name on a message. Results name writers by label and carry no author or person ids.

How well she knows the current speaker reaches her in `relationship` as words: `familiarity` is one level (the owner; known, when she has written an understanding of them or answered them many times; regular; met; new), computed from the owner's account, her written understanding, the turns in which she answered them and the lines they wrote, across every conversation of the canonical person. Nothing a message says raises it. A persona words each level and gives its `stance` in `people.familiarity`. `understanding` is what she has written about them. No relationship record is seeded: everyone starts with none, which reads as 你还没写过对这个人的理解, and her first reflected understanding creates the record.

## Her place in a group

Her own role in each group reaches her in words in `your_place_from_program`: 群主, 管理员, 普通成员, or not yet known. The adapter asks the platform for the logged-in account's own role (cached for ten minutes) and sends it in `raw.asuna_self`. The host keeps only a valid role, and only on group events.

Where she is the group's owner or an admin, the block also tells her how to use `group_action`. That field is an optional DECIDE item, at most one per turn:

- `kind`: `mute`, `unmute`, `recall` or `kick`;
- `who`: a label or `#n`;
- `duration`: 1分钟, 10分钟, 1小时 or 1天 (mute only);
- `which`: 这条 or 他刚才那条 (recall only);
- `reason`.

The program refuses any of these, by name:

- she is not an admin;
- the route sets `admin_actions: false` (admin actions are on by default);
- the target is unclear or unknown;
- the target is the owner, herself, the group's owner or another admin;
- a mute without a duration;
- there is no recent message to recall (recall takes the message that woke her, or the target's last line within 10 minutes);
- more than 6 actions in an hour in that group.

An accepted action becomes a `group_action` artifact. The outbox hands it to the adapter before any message, and the adapter calls `set_group_ban`, `delete_msg` or `set_group_kick`. The platform's answer arrives through the same receipt endpoint and updates the artifact (DONE, FAILED or UNKNOWN). An action interrupted while it was being sent becomes UNKNOWN and is never retried. Her words for the result say 已交给平台，等确认 until the platform answers; the account and message numbers stay in program data.

`group_notes_from_program` shows her own notes about the group: who is who, its customs, how she acts there. She writes them from that group's own turns with `write_docs` and `doc: "group_notes"` (`append_section` or `replace_section`). The program maps that name to the group's document and makes its sections public to that group.

## Media and image reading

An adapter may normalize non-text segments into bounded `raw.asuna_media` metadata. The host preserves placeholders and does not treat them as visual input. The action task receives a bounded list of image attachments from its own scene and policy epoch, plus images from scenes it may read only through a configured cross-scene read link; every entry carries `scene_id` and `linked_scene`, so the listing states where each image came from.

The action brain can call `read_image({"ref": "…", "max_bytes": 4194304})` when `executor.input_modalities` includes `image`. The reference selects an attachment already visible to that task; it cannot widen the read scope. That scope is recomputed from configuration at call time (`context_links` or route-level `read_scenes`, own scene first), so deleting the configured edge returns to own-scene-only, and a linked scene missing from the database or sitting in another policy epoch is simply not scanned. Bytes pulled from a linked scene are still stored under the calling task's own scope key. URL fetching requires an allowed host and safe redirect, enforces a byte limit, and accepts PNG, JPEG, WebP, or GIF data identified by file signature. An optional local image directory can also be configured. Pulled bytes are stored through the scoped blob store and passed to DSH as a durable image attachment. The stored tool receipt contains metadata and blob references, not base64 image bytes.

The default byte limit equals the 8 MiB hard limit: QQ photos are routinely 4-6 MiB and DSH re-encodes request images toward a 1 MiB target, so blocking at pull time would be an Asuna fence, not a route capability. Host allowlists, timeout, local directories, and insecure HTTP policy are configured under `vision`; the allowlist defaults to the multimedia host this deployment has actually received. Unsupported routes, disallowed sources, and fetch failures return real error codes, and a non-2xx response carries the server's bounded reason with any temporary `rkey` redacted; placeholders are not reported as viewed images. Download URLs are re-read from the stored message at pull time and are never embedded in the listing or truncated. Durable image references enter the native attachment pipeline; request image limits and pricing belong to the selected DSH provider. There is no Asuna token proxy.

### Sending an image with her words

A turn may also carry an image out. When the scene is the owner's own private conversation (`session_class=owner_private`) and its channel route targets a `dm`, the context gains `image_artifacts_from_program`: the image artifacts this turn may reference, each with `artifact_id`, `sha256` and `size`, plus a note that these are program-held artifacts and not file paths. She may answer with `attach: [{"artifact_id": "…", "why": "…"}]` — at most one item, and only an `artifact_id` from that list. Each item is validated on its own: a direction this version does not open, an artifact that was not offered this turn, bytes that are not an image by file signature, a size over 8 MiB, or a silent turn is refused as a rejection with a code and a reason, and the turn continues. Group turns and non-owner sessions are refused deterministically in this first version instead of silently degrading into text whose receipt reports a picture as delivered.

Two things put images on that list: bytes this scene already stored (`read_image`, and `import_integration_artifact` when the imported bytes turn out to be an image), and images registered in **one other scene belonging to the same person**. That exception exists because generation and import only run in the local owner task while the turn that speaks the picture is usually the QQ private chat, and both entries are the owner's own private space. `outbound_media.image_scopes` computes the readable set from configuration at read time: this turn must be `owner_private`, the peer scene must be a `dm` whose canonical person is the same owner, and the two scenes must be joined by a `context_links` / route `read_scenes` edge. Between two owner-private scenes of one person the edge counts in either direction — neither end can downgrade owner-private data into a public session, which is what `visibility.without_link_downgrades` exists to refuse. Groups, another person's scenes, unlinked scenes and public turns never extend the list, and offered items that came from the peer scene say so (`from_linked_scene`, plus its `scene_id`). The attachment endpoint recomputes the same list from the publication row itself (scene, the person on its route, session class): a caller cannot pass a scope, and deleting the configured edge returns the fence to own-scene-only without any code change.

An accepted attachment writes metadata only, on the first `SPEAK` row (`attachment`); bytes stay in the scoped blob store and travel over the attachment endpoint above. Delivered history then shows the picture as something she sent, with its media type and size, and says so differently when the adapter never declared image support, when the platform receipt's attachment evidence does not match the stored digest, or when the row was never delivered. Text-only messages keep their previous shape exactly: no attachment slot, no extra wording, in her context and in history search results.

## Schedules

The host uses DSH's native scheduler; it does not run a second host timer wheel. Scheduling, updating, or cancelling a plan is a character decision in the authorized scene. A due plan re-enters that scene and asks the character to decide what to do. A due event is not new authorization and does not mean its requested work has completed. Plan status and policy epoch are checked before dispatch.

Asuna reuses an installed DSH Schedule service. When the Host has none, it mounts that same service once, unless the `asuna-cognition-core` setting `mountSchedule` is `false`; then plans, heartbeat and settlement are off. By DSH design the `schedule_*` tools of a mounted Schedule are visible to every root agent in the Host; Asuna's role and action presets restrict their own tools.

## Managed integration and self-development

The managed integration runner is available only to the configured local owner profile. It uses a separate persistent development directory. `integration_test` runs a frozen, read-only `/app` snapshot with separate writable `/data`; `integration_start` enables a new frozen snapshot as a managed process; later development edits are not deployed automatically. `integration_status` reports process state and bounded logs, not platform connectivity or delivery. `integration_stop` stops the managed process and disables host restart restoration.

Integration processes run in the configured isolated environment and can reach only explicitly configured local or LAN TCP endpoints. Their commands are argument arrays, not host-shell strings. Connection credentials are supplied through the local integration profile and are not copied into ordinary task files.

`import_integration_artifact` reads one artifact over one of those configured endpoint aliases: the model supplies the alias and a path, never a URL, host or port, and the fetch performs a single HTTP/1.1 GET without following redirects. The host writes the bytes into the task workspace bound to this action at a relative path — existing files are kept unless `overwrite=true`, protected inputs are never written through, and the size cap is 4 MiB (1 MiB by default). The result reports the relative path, absolute path, byte count and SHA-256 actually written, or the real failure: unknown endpoint, URL rejected, path outside the workspace, target exists, over limit, HTTP status or transport error. When the bytes actually written are a PNG/JPEG/WebP/GIF by file signature (not by file name or `Content-Type`), the host additionally registers them as an `image` artifact in the scope this task is bound to — never a scope the model names: `kind=image`, `storage=gridfs`, `state=DONE`, media type from the bytes, and a SHA-256 the host recomputes and re-reads itself, with the result then carrying an `artifact` block (`artifact_id`, digest, size) so a later turn can send that picture out. Bytes that are not an image change nothing: the result keeps exactly its previous field set and no artifact row is written. A registration that cannot happen (a scope the store does not know, bytes over the 8 MiB outbound cap, a storage error) never turns a completed import into a failure — the reason is reported honestly under `artifact`. Offline: `python3 tools/integration_import_offline_check.py` and `python3 tools/outbound_image_offline_check.py`.

Self-development uses persistent project candidates separate from ordinary task workspaces. The default target is the selected persona package; `project="core"` selects the authorized cognition source. Tools inspect bounded file pages, edit/run candidate files, read bounded records from the existing database, and publish frozen artifacts after a non-consuming boot probe. Persona resources activate without restarting DSH. Python code replaces the worker at an idle boundary; JS/composition/dependency changes return `HOST_RESTART_REQUIRED`. Failed candidates remain for forward correction through the independent native recovery preset. Existing grants still control every ordinary action; QQ scenes do not inherit local owner development permissions.
