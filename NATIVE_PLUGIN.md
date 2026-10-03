# Native DSH plugins

Asuna uses DSH **0.2.0-rc.2** (release commit `639ed015397290b3745d163aafe02ffee4aa3f84`) in one Web Host. The two local installable packages are `@asuna/cognition-core` and `@asuna/xiaoman`. The Python SDK and separate Asuna Web workbench are retired.

## Build and install

Use the existing deployment configuration and Mongo database. Follow [RUN_ASUNA.md](RUN_ASUNA.md) for prerequisites, then:

```powershell
npm.cmd ci
npm.cmd run pack:plugins
.\.venv\Scripts\python.exe tools\setup_native_profile.py --shared-action-model
.\start-asuna.cmd
```

The optional shared-model flag seeds independent native provider references to the available action model. Later installations preserve settings saved in the editable native profile. Change routes in **Plugins → @asuna/cognition-core**; save and apply are separate operations. Credentials stay in local configuration and the launch environment, outside prompts and artifacts.

The packer writes content-addressed `.tgz` files and hashes to `.runtime/adr008/packages/manifest.json`. Setup calls the official DSH plugin installer and compares installed files to the tarballs. Nothing is published to npm. For another existing DSH Web profile, install both artifacts with:

```text
dsh plugin --profile <web-profile> add <core.tgz> <xiaoman.tgz>
```

Core includes its Python business modules, generic prompts and JSON schemas. It runs without this checkout's `src/asuna`. Supply Python 3.12+ with the exact dependencies from the installed `python/pyproject.toml`, then configure the Core and publication-floor entries as described in [the Core package](packages/cognition-core/README.md). Source projects, private configuration, Mongo, model services and tool sandbox remain deployment inputs. Core alone does not invent a persona or start a worker without complete settings.

DSH's profile resolver supplies Core's native peer dependencies from the Host installation. A standalone `pnpm peers check` inside a profile does not see that runtime mapping. `tools/probe_plugin_install.mjs` installs the actual tarballs outside this checkout and imports all Host exports through DSH's public profile resolver, without starting business consumers.

The Xiaoman package contains the existing distributable persona baseline, selected skills and adapter implementation. Its resource provenance records the original export. The installed contribution preserves the `local-xiaoman` to `xiaoman` identity mapping. Package upgrades seed missing heads only; existing Character Core, Current Self, voice, relationships and history remain authoritative.

## Enter the real sessions

Open the private authenticated address printed by the launcher. Select the authorized owner workspace and **小满**. The native composer, Chat, Trajectory, attachments and model stream belong to DSH. A delegated task uses an actual **Asuna Action** session linked from its originating role turn. Consultation returns through the same role and task binding. **Standard mode** remains an ordinary DSH session.

Core adds only the **记忆** right-tab body, its plugin settings card and the action association. Memory lists are bounded; details and original sources load on opening a row. Closing or switching releases the request scope. Read permissions come from the current session's scene, person, policy epoch and A2 links, not the operator's unrelated local workspace. The tab is not a Mongo editor.

## Execution and persistence

The Host owns native agents, model requests, tools, compaction, streaming, scheduling and durable transcripts. One managed private stdio Python worker retains Asuna's existing queues, coordinator, memory, task fences, publication, channels and integration supervision. It never starts another DSH runtime or proxies model tokens.

DSH assembles before `agent/pre-step`; the scoped assembly boundary prepares claimed input before its first model call. Sourced business context enters the actual native request. Native assistant events are flushed before business receipts are committed. Recovery uses those events and original receipt IDs; it does not manufacture assistant history or replay completed side effects. Role/action hooks are scoped and state is keyed by native session ID.

DSH 0.2's public `Session.append` does not accept an `ignorable` envelope option. Core therefore disables the stock JSONL component and inserts a thin public `SessionPersistence` adapter. It marks only `asuna/stage-result`, `asuna/action-linked` and `asuna/schedule` as informational, delegating storage, leases, compression and reading to the native backend. No DSH files are patched. The optional repair utility preserves original compressed backups and changes only those missing envelope flags in earlier development logs; use it offline.

Legacy lane logs and Mongo history remain intact. Their separate runtime homes are not merged or replayed into this Host. New native bindings record migration context recovery under the original authorization. This does not preserve old model KV caches or pretend that separate histories were uninterrupted.

QQ ingress, outbox receipts and enabled integration snapshots retain their existing configuration and ownership lock. Only final SPEAK publications enter the original channel target; internal stages and consultation remain internal. Plans use the Host's native scheduler and durable schedule inbox sources.

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

The focused native suite exercises real installed DSH loop, preset and persistence services with synthetic inference; it is separate from live-model Web evidence. The publication probe executes the actual local npm pack command and checks immutable selection, bounded reads and session-scoped spilled output. The timer probe executes the native scheduler and durable inbox without issuing a model request. Python native-worker tests and offline business suites do not create another Mongo database.

```powershell
npm.cmd run test:native
.\.venv\Scripts\python.exe -m pytest tests/test_native_worker.py -q
node tools/probe_native_schedule.mjs
node tools/probe_plugin_install.mjs
```

Live Web checks use the existing database and one available model for both brain routes. They cover actual role/action/consultation and original feedback, ordinary-preset isolation, memory pagination/detail, saved versus applied settings, publication and recovery. The implementation plan remains in `docs/development_plans/ADR-008-dsh-plugin`; current operation is documented here, in [RUN_ASUNA.md](RUN_ASUNA.md) and [RUNTIME_API.md](RUNTIME_API.md).
