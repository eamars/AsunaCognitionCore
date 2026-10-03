# Native DSH plugins

Asuna uses DSH **0.2.0-rc.2** (release commit `639ed015397290b3745d163aafe02ffee4aa3f84`) in one Web Host. The two local installable packages are `@asuna/cognition-core` and `@asuna/xiaoman`. The Python SDK and separate Asuna Web workbench are retired.

## Build and install

Use the existing deployment configuration and Mongo database. Follow [RUN_ASUNA.md](RUN_ASUNA.md) for prerequisites, then:

```powershell
npm.cmd ci
node tools/build_dsh_inline.mjs --source <dedicated-DSH-rc.2-checkout>
npm.cmd run pack:plugins
.\.venv\Scripts\python.exe tools\setup_native_profile.py --shared-action-model
.\start-asuna.cmd
```

The optional shared-model flag seeds independent native provider references to the available action model. Later installations preserve settings saved in the editable native profile. **Plugins → @asuna/cognition-core** uses DSH's shipped settings form and fields for business configuration, route defaults, admission, and write-only secrets. Save and apply are separate operations. Model API keys use DSH's native provider credential store; the launcher no longer shadows migrated keys with environment values. Credentials remain outside prompts and artifacts.

The [reviewed native extension](tools/dsh-inline/README.md) builds from the exact pinned release. It adds a public native Chat composition factory and preserves source-scoped cycle protection; it does not replace native message/tool renderers. The packer writes four content-addressed `.tgz` files and hashes to `.runtime/adr008/packages/manifest.json`: two Asuna plugins and two native rendering dependencies. Setup calls the official DSH plugin installer and compares installed files to the tarballs. Nothing is published to npm. For another existing DSH Web profile, install the delivery artifacts with:

```text
dsh plugin --profile <web-profile> add <native-chat.tgz> <native-renderer.tgz> <core.tgz> <xiaoman.tgz>
```

Core includes its Python business modules, generic prompts and JSON schemas. It runs without this checkout's `src/asuna`. Supply Python 3.12+ with the exact dependencies from the installed `python/pyproject.toml`, then configure the Core and publication-floor entries as described in [the Core package](packages/cognition-core/README.md). Source projects, private configuration, Mongo, model services and tool sandbox remain deployment inputs. Core alone does not invent a persona or start a worker without complete settings.

DSH's profile resolver supplies Core's native peer dependencies from the Host installation. A standalone `pnpm peers check` inside a profile does not see that runtime mapping. `tools/probe_plugin_install.mjs` installs the actual tarballs outside this checkout and imports all Host exports through DSH's public profile resolver, without starting business consumers.

The Xiaoman package contains the existing distributable persona baseline, selected skills and adapter implementation. Its resource provenance records the original export. The installed contribution preserves the `local-xiaoman` to `xiaoman` identity mapping. Package upgrades seed missing heads only; existing Character Core, Current Self, voice, relationships and history remain authoritative.

## Enter the real sessions

Open the private authenticated address printed by the launcher. The shipped workspace list contains **QQ** and **Local**. Continue **小满 · 本地私聊** under Local. QQ has one main role session per DM or group; different group speakers continue that same session. QQ input is view-only in the native composer and is also refused by the worker. Reply through QQ. DSH hides unused blank conversations until they have activity.

Set **QQ 接入策略** to `automatic` to admit new DMs, groups and group members on their first valid message. `explicit` retains configured enrollment. New identities receive isolated channel workspaces, without owner source, credential or integration grants. Admission facts persist in the existing database and restore after restart. `channels.<id>.blocked_senders` and `blocked_groups` deny input, work grants and new outbox sends; changing membership authorization can retire the old native session rather than redirect old tasks into a new epoch.

An incoming QQ message is appended as an actual native user receipt before retrieval or inference, including quiet group messages. Native-log acknowledgments deduplicate retries; startup retries unacknowledged projection work without re-running models or tools. Earlier business history stays accessible in Memory. Conversation names use `私聊 · <display_name or ID>` / `群聊 · <display_name or ID>`; manual native renames survive startup. Archiving hides a conversation until its next QQ activity; use admission/block settings to stop receiving a target.

The native composer, Chat, Trajectory, attachments and model stream belong to DSH. **小满 · 角色脑**, **行动脑**, and **交流摘要** identify their responsibilities through native preset labels. New tasks and exchange summaries are actual native child agents of the relevant role conversation; they do not create workspace groups. An action retains its requester's authorized execution directory and is accessible through the native child catalog. Historical action links remain readable. Consultation retains the initiating task's identity. **Standard mode** remains an ordinary DSH session; native New Session is still available when deliberately needed.

QQ role agents have no tools and use the real deployment directory `.runtime/work/qq`; Local retains its configured workspace. The initial organization continues the newest eligible QQ role history through an exact native fork prefix because DSH session cwd is immutable. Other existing sessions are archived, not deleted or spliced into that prefix; use native **View options → All conversations (show archived)** to inspect them. The newest eligible Local role keeps its ID and history. Workspace registration cleanup does not delete directories. Scene/persona/policy context remains the authorization boundary, and every group turn checks its actual sender again.

Core adds the **记忆** right-tab body, its plugin settings card, the action association and the approved small brain/stage labels. Memory opens on conversation summaries, with the existing type menu for self, relationships and original messages. Date-ordered lists show short content titles and single-line excerpts; full bodies and time-ordered sources load on opening a row. The shipped search input performs literal text matching across the selected category's authorized records before pagination, not just the loaded page. Dates use the browser's local timezone; summary dates describe when the summary was generated. Internal scope and revision IDs do not occupy the list. Closing or switching releases the request scope. Read permissions come from the current session's scene, person, policy epoch and A2 links, not the operator's unrelated local workspace. The tab is not a Mongo editor.

The existing type menu also exposes **自我 / 对人的认识 / 对世界的认识 / 当时的理解**. Self includes the scene-specific overlay and distinguishes missing Core/Current Self records from the explicitly unimplemented mood state. People shows the bound conversation actor, the actual relationship prose and recorded levels, and the authenticated QQ peer projection; separate structured portrait consolidation is marked unimplemented. World-knowledge consolidation is likewise marked unimplemented, with existing summaries, interpretations and original sources remaining readable. These placeholders are view metadata and never create cognitive state. Interpretation dates come from actual persistence receipts when the unit has no timestamp. Details distinguish saved records from versions selected in the most recent matching prepared context, constrained by native session, scene, actor, persona and policy epoch; this is not proof of model consumption or causal influence. A bounded audit lookup that cannot locate a matching context reports it unavailable. Current-turn interpretations can also be identified through the episode's real monologue references. Native conversation history, group continuity, plans and action feedback remain in their original native conversation path. Revision sources retain whether they are original messages, summaries or interpretations.

Brain attribution uses DSH's native Chat process disclosures and public node and header extension slots. The labels contain only **角色脑** or **行动脑**, without phase, purpose or status descriptions. DSH's original controls show execution and completion states. Business phases remain recorded in the native log; older transcripts recover attribution only from their recorded Asuna phase notices, never from model names. MONOLOGUE remains ordinary assistant text; provider reasoning remains a native reasoning block.

The existing compact native `Pill` labels above the reasoning use purple for the character brain and blue for the action brain. There is no duplicate label below the output. Only their text/background palette is scoped by explicit lane; summary work does not receive a brain label. Light and dark palettes follow DSH's theme. Native reasoning and assistant text keep their original rendering and colors.

The role's main Chat displays actual action records alongside role judgments and consultation, using references to the original native action log. Expand the shipped reasoning/tool disclosures to read complete output and IN/OUT. There is one main composer. The native subagent catalog and **Trajectory** remain optional diagnostics; opening an action child is no longer the default reading path. Continued tasks on the same authorized execution binding retain their native action context and receive disjoint display ranges. The catalog also contains summaries; its count alone does not establish action execution. Memory rows keep the native disclosure arrow visible while collapsed; clicking the title or arrow opens the detail body instead of the list excerpt.

## Execution and persistence

The Host owns native agents, model requests, tools, compaction, streaming, scheduling and durable transcripts. One managed private stdio Python worker retains Asuna's existing queues, coordinator, memory, task fences, publication, channels and integration supervision. It never starts another DSH runtime or proxies model tokens.

DSH assembles before `agent/pre-step`; the scoped assembly boundary prepares claimed input before its first model call. Sourced business context enters the actual native request. Native assistant events are flushed before business receipts are committed. Recovery uses those events and original receipt IDs; it does not manufacture assistant history or replay completed side effects. Role/action hooks are scoped and state is keyed by native session ID.

DSH 0.2's public `Session.append` does not accept an `ignorable` envelope option. Core therefore disables the stock JSONL component and inserts a thin public `SessionPersistence` adapter. It marks its stage, result, action-link/range and schedule attribution as informational, delegating storage, leases, compression and reading to the native backend. This adapter does not patch DSH storage. The separately approved native Chat/renderer extension is built from the pinned source and installed as artifacts. The optional repair utility preserves original compressed backups and changes only those missing envelope flags in earlier development logs; use it offline.

Legacy lane logs and Mongo history remain intact. Their separate runtime homes are not merged or replayed into this Host. New native bindings record migration context recovery under the original authorization. This does not preserve old model KV caches or pretend that separate histories were uninterrupted.

QQ ingress, outbox receipts and enabled integration snapshots retain their existing configuration and ownership lock. Only final SPEAK publications enter the original channel target; internal stages and consultation remain internal. Plans use the Host's native scheduler and durable schedule inbox sources.

The editable DSH profile is authoritative after migration: `deployment` holds structured business values; `secrets` holds write-only values referenced as `{"$secret":"name"}`. Structured fields accept JSON. The native secret-map field can add references for a new channel without restating existing secrets. Mongo, embeddings, channel routes/block lists, A2 links, integration endpoints, vision and self-development are editable on the plugin page. Provider definitions/API keys remain in DSH's Models settings. Persona baselines, prompts and protected publication-floor source grants belong to installed artifacts/deployment composition rather than an arbitrary state editor.

Persona, QQ admission, provider, model and reasoning effort use DSH's shipped Menu/Button selection controls. Model and effort choices come from the native provider catalog for the exact route; no model family is inferred from a brain label. The provider-default effort choice omits an explicit effort from native requests. Output limits accept positive integers; paths and addresses remain text inputs. Structured business sections retain native JSON value fields.

Save validates model catalog references, business bindings and the existing database connection without starting consumers or requesting inference. DSH owns revision checking and durable writes; rejected drafts stay on screen. Apply fences ingress and refuses active user/action work; background summaries may be interrupted and resumed. It restarts the worker and an already-enabled adapter using the installed persona artifact. A failed settings activation restores the previously running configuration and leaves the proposed saved values pending for correction. This settings recovery is separate from forward-only code publication. Process startup alone does not prove QQ connectivity or delivery.

## Develop and publish forward

The persistent writable candidate is `xiaoman` by default. Use `project="core"` for the authorized cognition source. Native skills discovery reads published resources; `/skills` mounts the authorized writable persona candidate. Ordinary QQ identities do not acquire the local owner's source or credential access.

`development_files` is paged. Read/write/run act on the selected project; commands retain the configured isolated workspace execution boundary. Publication freezes a candidate, checks source revisions, performs minimum structural/import checks, packs an immutable artifact and keeps lineage and actual failure evidence. The current source is never imported halfway through an edit.

- `BOOT_FAILED` or `PACK_FAILED`: the candidate and reason remain available; nothing new was activated.
- `APPLIED`: an artifact is selected; successful loading is not yet confirmed.
- `ACTIVE`: the corresponding resources or worker loaded successfully.
- `HOST_RESTART_REQUIRED`: JS, composition or dependency changes need an explicit Host restart to install the selected package. The launcher records installer failure while keeping the installed native repair entry available.

Persona resources apply without restarting the Host. Python updates replace only the worker at an idle boundary. No automatic rollback substitutes an earlier version for a failed forward update. Publication feedback retains its original task/goal association.

**Asuna recovery** is a native preset with project tools backed by the stable publication floor, independent of the mutable worker. It can inspect a failed candidate and publish a forward correction when Python cannot import. It does not grant database mutation or platform messages. The launcher, publication floor, recovery component and persistence boundary are protected from these project writes. Native Web and ordinary sessions remain available during worker failure.

## Verification boundaries

The focused native suite exercises real installed DSH loop, preset and persistence services with synthetic inference; it is separate from live-model Web evidence. The publication probe executes the actual local npm pack command and checks immutable selection, bounded reads and session-scoped spilled output. The timer probe executes the native scheduler and durable inbox without issuing a model request. Python native-worker/product tests do not create Mongo databases. Business integration tests use owned isolated test databases, export file evidence and drop those databases during teardown, including failures; they skip when Mongo is unavailable.

```powershell
npm.cmd run test:native
.\.venv\Scripts\python.exe -m pytest tests/test_native_worker.py tests/test_native_product.py -q
.\.venv\Scripts\python.exe tools/probe_qq_admission.py
node tools/probe_native_schedule.mjs
node tools/probe_plugin_install.mjs
node tools/probe_native_image.mjs
```

UI development uses an isolated native Web profile with synthetic inference. The image probe loads the actual attachment plugin, preserves Cordis's service-injection boundary, executes the native action/tool loop and verifies durable image blocks after cold replay. The action preset supplies its declared attachment service; an Agent context does not inherit that preset's injection grants. DSH's Trajectory tool result provides the shipped thumbnail and original-image preview. In the pinned release, the Chat image card recognizes `file_path` calls, so Asuna's authorized QQ `ref` calls still use the generic textual result in Chat. No custom image renderer or altered native history is used to bypass that limitation.

The operator subsequently authorized real-model delivery testing and resumed the production profile with one model for both routes. A real group delivery is recorded in [the product follow-up](reports/ADR-008-product-fixes-20261003.md); a fresh owner DM round trip is still unverified. UI probes do not establish live delivery. QQ source receipt times are retained, but the native bubble clock currently shows DSH event time rather than the original QQ send time. These display limits require a supported DSH extension; modifying the Host requires the operator's decision. The implementation plan remains in `docs/development_plans/ADR-008-dsh-plugin`; current operation is documented here, in [RUN_ASUNA.md](RUN_ASUNA.md) and [RUNTIME_API.md](RUNTIME_API.md).
