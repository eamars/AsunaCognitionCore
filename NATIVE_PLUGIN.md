# Native DSH plugins

How Asuna's packages compose inside DSH **0.2.0-rc.2** (release commit `639ed015397290b3745d163aafe02ffee4aa3f84`): what each package contributes, what the Web page shows, and where execution and state live. Installing and running are in [RUN_ASUNA.md](RUN_ASUNA.md) (from a checkout) and [INSTALL.md](INSTALL.md) (released plugins); the channel and tool contracts are in [RUNTIME_API.md](RUNTIME_API.md).

## The packages

| Package | Folder | Contributes |
|---|---|---|
| `@asuna/cognition-core` | `packages/cognition-core` | The Host plugin (presets, settings card, memory tab, labels, publication floor, recovery) and the Python business worker with its neutral prompts and schemas. |
| a persona package | `packages/personas/<name>` | `registerPersona({id, character_id, display_name, version, resource_root, model, seeds, jobs, skill_directories, preset})` (contract v2; one seed has kind `persona`) and a thin role preset that loads `@asuna/cognition-core/role`. Seeds fill only missing persona documents. |
| a channel package | `packages/channels/<name>` | `registerChannel({kind, title, project, resource_root, python, module, integration_directory, skill_directories})`: a Python kind module (id formats, mentions, media hosts, derived adapter settings), its adapter, and the adapter's skill. |
| the inline rendering extension | `tools/dsh-inline` | Two patched DSH UI packages, built locally from the pinned release ([README](tools/dsh-inline/README.md)). Optional. |

Core without a selected persona is inert, and Core names no platform: it waits for the plugins of the channels the deployment configures before the worker reads a route. The synthetic persona `tests/fixtures/personas/demo` is used by the tests and the demo environment. How to write a new persona or channel package is in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#writing-a-persona-or-channel-package).

Core includes its Python business modules and, under `python/asuna/resources/`, the neutral core prompts and JSON schemas (sources in `src/asuna/resources/`). It runs without this checkout's `src/asuna` or `docs/`. DSH's profile resolver supplies Core's native peer dependencies from the Host installation; a standalone `pnpm peers check` inside a profile does not see that runtime mapping. `tools/probe_plugin_install.mjs` installs the actual tarballs outside this checkout and imports all Host exports through DSH's public profile resolver, without starting business consumers.

## The conversations on the Web page

The shipped workspace list contains the local workspace and one per configured channel, each titled with the character's name first (**杏山カズサ · QQ**, **杏山カズサ · 本地**), so every page says whose conversations it holds. The persona's local chat is under Local. A channel has one main role session per DM or group; different group speakers continue that same session. Channel input is view-only in the native composer and is also refused by the worker: reply on the platform. DSH hides unused blank conversations until they have activity.

With **QQ 接入策略** `automatic`, new DMs, groups and group members are admitted on their first valid message; `explicit` keeps configured enrollment. New identities receive isolated channel workspaces, without owner source, credential or integration grants. Admission facts persist in the database and restore after restart. `channels.<id>.blocked_senders` and `blocked_groups` deny input, work grants and new outbox sends; changing membership authorization can retire the old native session rather than redirect old tasks into a new epoch.

An incoming platform message is appended as an actual native user receipt before retrieval or inference, including quiet group messages. Native-log acknowledgments deduplicate retries; startup retries unacknowledged projection work without re-running models or tools. Earlier business history stays accessible in Memory. Conversation names use `私聊 · <display_name or ID>` / `群聊 · <display_name or ID>`; manual native renames survive startup. Archiving hides a conversation until its next activity; use admission/block settings to stop receiving a target.

The native composer, Chat, Trajectory, attachments and model stream belong to DSH. The character brain, **行动脑** and **交流摘要** identify their responsibilities through native preset labels. New tasks and exchange summaries are actual native child agents of the relevant role conversation; they do not create workspace groups. An action retains its requester's authorized execution directory and is accessible through the native child catalog. Consultation retains the initiating task's identity. **Standard mode** remains an ordinary DSH session.

Channel role agents have only the tools her turn exposes (her mind's tools) and use the deployment directory `.runtime/work/<channel>`; Local keeps its configured workspace. Scene, persona and policy context remain the authorization boundary, and every group turn checks its actual sender again.

## What Core adds to the page

Core adds the **记忆** right-tab body, its plugin settings card, the action association and the approved small brain/stage labels.

Memory opens on conversation summaries, with the existing type menu for self, relationships and original messages, and **自我 / 对人的认识 / 对世界的认识 / 当时的理解**. Date-ordered lists show short content titles and single-line excerpts; full bodies and time-ordered sources load on opening a row. The shipped search input performs literal text matching across the selected category's authorized records before pagination. Dates use the browser's local timezone; summary dates describe when the summary was generated. Read permissions come from the current session's scene, person, policy epoch and A2 links, not the operator's unrelated local workspace. The tab is not a Mongo editor. Categories not implemented yet (structured portrait consolidation, world-knowledge consolidation) are marked so; these placeholders are view metadata and never create cognitive state. Details distinguish saved records from versions selected in the most recent matching prepared context; this is not proof of model consumption or causal influence.

Brain attribution uses DSH's native Chat process disclosures and public node and header extension slots. The compact native `Pill` labels name only the character brain (purple) or the action brain (blue), in the viewer's DSH language, without phase, purpose or status. Summary work receives no brain label. Light and dark palettes follow DSH's theme. Older transcripts recover attribution only from their recorded Asuna phase notices, never from model names. Her thought is a `think` tool row inside the turn's folded process, showing its first sentence; each of her tools has a light row (Core registers `tool.call.toolview` entries built on DSH's `DisclosureRow`). Provider reasoning remains a native reasoning block. A turn started by an Asuna notice (a platform message, an action result, a question from the action brain, an internal moment, a plan) is titled by what started it, through DSH's own trigger notice.

The role's main Chat shows each task as a collaboration thread after the turn that delegated it: a header with the task title, its state and duration and a button that opens the full action session in the sidebar (DSH's subagent chat resource). Once the action brain finishes, the state says where its result stands: being handed to her, read by her (her turn on it finished), or never reached her, with the reason and whether the program will hand it back again or has told the developer; her messages and the action brain's messages as bubbles with their labels; and between them the action brain's own work, folded as "worked N minutes · M tool calls". With the inline extension installed, opening a work row renders that range of the original native action log with DSH's own fragment renderer; without it, the row links to DSH's subagent view. Durable `asuna/action-linked` / `asuna/action-range` events contain parent/source identities and sequence bounds, with no copied messages. Long reports show their first lines with a button for the rest. There is one main composer. The native subagent catalog lists only tasks (summaries and gates are hidden child sessions).

Every word of Core's UI comes from its `asuna` locale namespace (zh and en) and follows DSH's language setting; the memory and input-policy APIs send keys with parameters. Only her content (speech, thoughts, documents, the persona's names and words for feelings) is in the persona's language. Conversation titles are stored by DSH and shown as they are, so Core titles a conversation by content only: the persona name, a group or person name, or a task's title.

## Execution and persistence

The Host owns native agents, model requests, tools, compaction, streaming, scheduling and durable transcripts. One managed private stdio Python worker owns Asuna's queues, coordinator, memory, task fences, publication, channels and integration supervision. It never starts another DSH runtime or proxies model tokens.

DSH assembles before `agent/pre-step`; the scoped assembly boundary prepares claimed input before its first model call. A role session's system prompt is exactly the worker's render (neutral core header, then the persona): the role scope suppresses runtime-context snapshots and replaces every other section, including the native harness identity sentence. Episodes store only `system_ref` (revisions and hashes) and re-render per stage. The action brain receives the neutral executor prompt and the persona's display name, never the persona body. Native assistant events are flushed before business receipts are committed. Recovery uses those events and original receipt IDs; it does not manufacture assistant history or replay completed side effects. Role/action hooks are scoped and state is keyed by native session ID.

DSH 0.2's public `Session.append` does not accept an `ignorable` envelope option. Core therefore disables the stock JSONL component and inserts a thin public `SessionPersistence` adapter. It marks its stage, result, action-link/range and schedule attribution events as informational, delegating storage, leases, compression and reading to the native backend. It does not patch DSH storage. Uninstalling the bundle restores the stock profile composition; retained marked events are safely ignorable.

Channel ingress, outbox receipts and enabled integration snapshots keep their configuration and ownership lock. Only her final text enters the original channel target; her thoughts, tool calls and answers to the action brain remain internal. Plans use the Host's native scheduler and durable schedule inbox sources.

The editable DSH profile is authoritative after migration: `deployment` holds structured business values; `secrets` holds write-only values referenced as `{"$secret":"name"}`. Structured fields accept JSON. The native secret-map field can add references for a new channel without restating existing secrets. Mongo, embeddings, channel routes/block lists, A2 links, integration endpoints, vision and self-development are editable on the plugin page. Provider definitions and API keys stay in DSH's Models settings. Persona baselines, prompts and protected publication-floor source grants belong to installed artifacts and deployment composition rather than an arbitrary state editor.

Persona, channel admission, provider, model and reasoning effort use DSH's shipped Menu/Button selection controls. Model and effort choices come from the native provider catalog for the exact route; no model family is inferred from a brain label. The provider-default effort choice omits an explicit effort from native requests.

Save validates model catalog references, business bindings and the database connection without starting consumers or requesting inference. DSH owns revision checking and durable writes; rejected drafts stay on screen. Apply fences ingress and refuses active user/action work; background summaries may be interrupted and resumed. It restarts the worker and an already-enabled adapter from the installed channel package's artifact. A failed settings activation restores the previously running configuration and leaves the proposed saved values pending for correction. This settings recovery is separate from forward-only code publication. Process startup alone does not prove platform connectivity or delivery.

## Develop and publish forward

The persistent writable candidate is the selected persona package by default; `project="core"` is the cognition source and each channel package is its own project. Native skills discovery reads published resources. Skills, adapters and code change only through the development tools and take effect only through `development_publish`; no sandbox mounts them writable, and `integration_start` runs only the published adapter. Ordinary channel identities do not acquire the local owner's source or credential access.

`development_files` is paged. Read/write/run act on the selected project; commands keep the configured isolated workspace execution boundary. Publication freezes a candidate, checks source revisions, checks syntax, imports the plugin entry in a child process, reads the persona model and Cordis patch, packs an immutable artifact and keeps lineage and actual failure evidence. The current source is never imported halfway through an edit. The publication states and what each needs are in [RUN_ASUNA.md](RUN_ASUNA.md#self-development-and-recovery). Python updates replace only the worker at an idle boundary; only a core publication ever asks for that, and a newer publication of the same project supersedes one still waiting to start (`SUPERSEDED`).

**Asuna recovery** is a native preset with project tools backed by the stable publication floor, independent of the mutable worker. It can inspect a failed candidate and publish a forward correction when Python cannot import. It does not grant database mutation or platform messages. The launcher, publication floor, recovery component and persistence boundary are protected from these project writes. Native Web and ordinary sessions remain available during worker failure.

## Verification boundaries

The focused native suite exercises real installed DSH loop, preset and persistence services with synthetic inference; it is separate from live-model Web evidence. The publication probe executes the actual local npm pack command and checks immutable selection, bounded reads and session-scoped spilled output. The timer probe executes the native scheduler and durable inbox without issuing a model request. Python native-worker/product tests do not create Mongo databases.

```powershell
npm.cmd run test:native
.\.venv\Scripts\python.exe -m pytest tests/test_native_worker.py tests/test_native_product.py -q
.\.venv\Scripts\python.exe tools/probe_qq_admission.py packages/channels/napcat-qq
node tools/probe_native_schedule.mjs
node tools/probe_plugin_install.mjs
node tools/probe_native_image.mjs
```

The image probe loads the actual attachment plugin, preserves Cordis's service-injection boundary, executes the native action/tool loop and verifies durable image blocks after cold replay. The action preset supplies its declared attachment service; an Agent context does not inherit that preset's injection grants. DSH's Trajectory tool result provides the shipped thumbnail and original-image preview. In the pinned release, the Chat image card recognizes `file_path` calls, so Asuna's authorized QQ `ref` calls still use the generic textual result in Chat.

Known DSH limits: the native bubble clock shows DSH event time rather than the original platform send time (the source receipt time is kept). Changing these needs a supported DSH extension; modifying the Host requires the operator's decision. UI probes do not establish live delivery.
