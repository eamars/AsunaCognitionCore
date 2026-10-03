# Running Asuna

The default is the native DSH Web profile. One Host owns model execution and the Web UI; its managed Python worker owns business state and existing channel/integration services.

## Prerequisites and installation

Use the existing Mongo database and private deployment configuration. A compatible Node runtime, Python **3.12+**, and the existing WSL Ubuntu/bubblewrap environment are required for the configured workspace tools. Model and embedding services run independently.

```powershell
npm.cmd ci
.\.venv\Scripts\uv.exe sync
npm.cmd run pack:plugins
.\.venv\Scripts\python.exe tools\setup_native_profile.py --shared-action-model
.\start-asuna.cmd
```

The installer does not initialize, reset, copy or replace Mongo. `--shared-action-model` seeds independent character/action references pointing to the available action model. Omit it on a new profile to seed separate routes. Reinstallation preserves saved profile settings; change routes in the native settings card after initial installation.

Artifacts and hashes are in `.runtime/adr008/packages/manifest.json`. Setup uses DSH's official plugin installer, then verifies every installed file against its content-addressed tarball. No npm publication occurs. For installation into another existing DSH Host, follow the package instructions in [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md).

## Start, review, stop

`start-asuna.cmd` launches the stable Node entry directly, so a broken Python worker cannot prevent the native repair interface from opening. `start-asuna-ui.cmd` and `asuna ui --config config/local.json --port 8780` select the same profile. `--native` remains a compatibility flag. The retired `/asuna/` page and `--read-only` Web server are no longer used.

Open the authenticated `dsh web:` address printed by the launcher. The token is private. Under **Local**, continue **小满 · 本地私聊**. Under **QQ**, each active DM or group has one continuous main conversation; its composer is view-only, so reply through QQ. Use native Chat for conversation and Trajectory for actual steps/tools. Actions and exchange summaries are native children of their role conversation. **Standard mode** remains ordinary DSH. Native New Session remains available for deliberate additional or recovery conversations. Older sessions remain accessible using native View options to show archives.

The colored labels show only **角色脑** (purple) or **行动脑** (blue). The compact labels appear in the running header and above the reasoning inside the native process details. No extra label is added below the output. Expand DSH's process disclosure and analysis row to inspect native reasoning, text and tools. DSH's own controls show execution status. Both brains can use the same model without losing their identity labels.

Ctrl+C stops this Host and its managed worker/adapters. Let active work settle before a manual restart. Do not start two instances consuming the same channel routes. Restart with the same command; persisted input, task fences, feedback and native bindings determine recovery. An interrupted action is reported with its existing evidence, without blindly replaying side effects. External model services are not stopped by Asuna.

UI development uses an isolated native DSH profile with synthetic inference for both brains. It must not start the production worker, consume live QQ queues or call real model endpoints (including background summaries). The operator's external model server remains independent. Re-enabling real-model use requires the operator's explicit instruction. Character labels are purple and action labels blue; their text remains the authoritative distinction in both light and dark themes.

## Settings and private files

- `config/local.json`: migration source for existing Mongo, workspace and business configuration.
- Adjacent `*.models.local.json`: deployment seed routes and model credentials. After installation, active model references belong to the native profile.
- Adjacent `asuna-channel.local.json`: initial authenticated routes, identities, grants and A2 read links; imported only when enabled.
- Adjacent `integration.local.json`: initial managed adapter configuration and approved network aliases.
- `.runtime/adr008/home/profiles/asuna-native/cordis.patch.yml`: editable native provider and Asuna settings. Do not pass it again as a command-line overlay.

After migration the native profile's `deployment` and write-only `secrets` are authoritative; editing the old JSON files does not silently override saved settings. DSH's native Models page owns provider definitions and model API keys. No launcher environment override shadows keys changed there.

In **Plugins → @asuna/cognition-core**, edit business values (structured fields use JSON), persona/model references and credential fields, save, then **应用已保存设置**. Set **QQ 接入策略** to `automatic` for new DMs/groups/members, or `explicit` for configured enrollment. New contacts get isolated workspaces; they inherit no owner access. Use `channels.<id>.blocked_senders` / `blocked_groups` to refuse specific QQ identities. The native write-only JSON credential field can provision new secret references in the same save.

The card reports saved-but-not-applied state and actual failures. Save preflights without model calls; invalid drafts remain editable. Apply pauses ingress/background summaries and requires user/action work to be idle. It reloads an already-enabled adapter from the installed persona package, and restores the previous running configuration if activation fails. Old native conversation names and deliberate archives survive restart; the next QQ message reopens that target's same conversation. Reasoning, input modalities and limits come from configured model metadata, never the lane name. No process-running label is a QQ delivery guarantee.

The **记忆** right tab reads bounded pages for the current native scene binding. Open a row for full authorized details and sources. It does not edit Mongo or broaden A2 access.

## Self-development and recovery

`development_files/read/write/run/publish` target `xiaoman` by default; `project="core"` selects the existing authorized cognition source project. `/skills` is the writable persona candidate; native discovery uses the selected immutable artifact. Core updates do not overwrite existing self heads.

`BOOT_FAILED` / `PACK_FAILED` preserve the failed candidate and diagnostics. `APPLIED` means selected, not yet confirmed running. `ACTIVE` means the relevant worker/resources loaded successfully. `HOST_RESTART_REQUIRED` means restart this Host to install the selected JS/composition/dependency artifact. The launcher retains installation failures and still opens the installed repair floor. There is no automatic rollback.

If the worker fails, create a native session using **Asuna recovery** in the authorized local workspace. Its project tools operate independently of Python, preserve the selected candidate and publish a forward correction. A normal Python correction can restart only the worker. Protected publication/repair/persistence modules and the stable entry remain outside autonomous edits.

## Maintenance

Other CLI operations require `--debug`; use them for explicit maintenance and read-only evidence, not normal chat or model execution. For example:

```powershell
.\.venv\Scripts\python.exe -m asuna.cli --debug inspect task TASK_ID
```

Legacy `run`, `chat`, `reflect`, `compact` and model-evaluation drivers no longer start separate SDK runtimes. Historic reports and logs remain readable. Old UI/proxy-specific tests were retired with their implementation. The native contract suite and offline business checks do not require another Mongo database:

```powershell
npm.cmd run test:native
.\.venv\Scripts\python.exe -m pytest tests/test_native_worker.py tests/test_native_product.py -q
.\.venv\Scripts\python.exe tools/probe_qq_admission.py
node tools/probe_native_schedule.mjs
```

The older tests using the `store` fixture create isolated Mongo databases; they are not part of the single-world migration verification.
