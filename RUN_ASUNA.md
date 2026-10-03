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

Open the authenticated `dsh web:` address printed by the launcher. The token is private. Select the authorized owner workspace and **小满** preset. Use native Chat for conversation and Trajectory for actual steps/tools. **Asuna Action**, summaries and schedules are bound by Core; they are not fresh human conversation presets. **Standard mode** remains ordinary DSH.

Ctrl+C stops this Host and its managed worker/adapters. Let active work settle before a manual restart. Do not start two instances consuming the same channel routes. Restart with the same command; persisted input, task fences, feedback and native bindings determine recovery. An interrupted action is reported with its existing evidence, without blindly replaying side effects. External model services are not stopped by Asuna.

## Settings and private files

- `config/local.json`: existing Mongo, workspace and business configuration.
- Adjacent `*.models.local.json`: deployment seed routes and model credentials. After installation, active model references belong to the native profile.
- Adjacent `asuna-channel.local.json`: existing authenticated routes, identities, grants and A2 read links; loaded only when enabled.
- Adjacent `integration.local.json`: existing managed adapter configuration and approved network aliases.
- `.runtime/adr008/home/profiles/asuna-native/cordis.patch.yml`: editable native provider and Asuna settings. Do not pass it again as a command-line overlay.

In **Plugins → @asuna/cognition-core**, save selected persona/model references, then **应用已保存设置** when business work is idle. The card reports saved-but-not-applied state and actual worker failures. Reasoning, input modalities and limits come from the selected native route, never the lane name. Provider secrets are not sent through prompts or plugin artifacts.

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
.\.venv\Scripts\python.exe -m pytest tests/test_native_worker.py -q
node tools/probe_native_schedule.mjs
```

The older tests using the `store` fixture create isolated Mongo databases; they are not part of the single-world migration verification.
