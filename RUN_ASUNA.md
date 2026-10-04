# Running Asuna

The default is the native DSH Web profile. One Host owns model execution and the Web UI; its managed Python worker owns business state and existing channel/integration services.

## Prerequisites and installation

Use the existing Mongo database and private deployment configuration. A compatible Node runtime, Python **3.12+**, and the existing WSL Ubuntu/bubblewrap environment are required for the configured workspace tools. Model and embedding services run independently.

```powershell
npm.cmd ci
.\.venv\Scripts\uv.exe sync
.\.venv\Scripts\python.exe tools\pack_plugins.py --persona packages\xiaoman
.\.venv\Scripts\python.exe tools\setup_native_profile.py --persona-package packages\xiaoman --shared-action-model
.\start-asuna.cmd
```

The core names no persona: pass the persona package directory to both the packer and the installer.

The installer does not initialize, reset, copy or replace Mongo. `--shared-action-model` seeds independent character/action references pointing to the available action model. Omit it on a new profile to seed separate routes. Reinstallation preserves saved profile settings; change routes in the native settings card after initial installation.

Artifacts and hashes are in `.runtime/adr008/packages/manifest.json`. Setup uses DSH's official plugin installer, then verifies every installed file against its content-addressed tarball. No npm publication occurs. For installation into another existing DSH Host, follow the package instructions in [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md).

## Start, review, stop

`start-asuna.cmd` launches the stable Node entry directly, so a broken Python worker cannot prevent the native repair interface from opening. `start-asuna-ui.cmd` and `asuna ui --config config/local.json --port 8780` select the same profile. Both launchers accept `--profile <name>` and `--config <path>` (or `ASUNA_PROFILE` / `ASUNA_CONFIG`); the defaults are `asuna-native` and `config/local.json`. A profile other than `asuna-native` keeps its own DSH home, activation state and candidates under `.runtime/adr008/profiles/<name>/`. `--dry-run` prints the resolved profile, config and database without starting anything. There is no terminal chat.

Open the authenticated `dsh web:` address printed by the launcher. The token is private. Select the authorized owner workspace and the persona's preset. Use native Chat for conversation and Trajectory for actual steps/tools. **Asuna Action**, summaries and schedules are bound by Core; they are not fresh human conversation presets. **Standard mode** remains ordinary DSH.

Ctrl+C stops this Host and its managed worker/adapters. Let active work settle before a manual restart. Do not start two instances consuming the same channel routes. Restart with the same command; persisted input, task fences, feedback and native bindings determine recovery. An interrupted action is reported with its existing evidence, without blindly replaying side effects. External model services are not stopped by Asuna.

## Settings and private files

- `config/local.json`: existing Mongo, workspace and business configuration. Set `timezone` (an IANA name) here; without it clocks and schedules are shown in UTC and say so — the core has no built-in time zone.
- Adjacent `*.models.local.json`: deployment seed routes and model credentials. After installation, active model references belong to the native profile.
- Adjacent `asuna-channel.local.json`: existing authenticated routes, identities, grants and A2 read links; loaded only when enabled. A link that would let a public scene (a group, or someone else's DM) read an owner-private scene (the local scene or the owner's own DM) is refused at Host start with `LINK_PRIVACY_DOWNGRADE` and recorded in the audit log.
- Adjacent `integration.local.json`: existing managed adapter configuration and approved network aliases.
- These two sibling files belong to `config/local.json` only. Any other config file names them explicitly with `channel_config` / `integration_config`, so a second config never inherits real routes.
- `config/personal-denylist.local.txt` (ignored; template `config/personal-denylist.example.txt`): your own account names, host names and similar literals for `tools/check_staged_secrets.py --personal`.
- `.runtime/adr008/home/profiles/asuna-native/cordis.patch.yml`: editable native provider and Asuna settings. Do not pass it again as a command-line overlay.

In **Plugins → @asuna/cognition-core**, save selected persona/model references, then **应用已保存设置** when business work is idle. The card reports saved-but-not-applied state and actual worker failures. Reasoning, input modalities and limits come from the selected native route, never the lane name. Provider secrets are not sent through prompts or plugin artifacts.

The **记忆** right tab reads bounded pages for the current native scene binding. Open a row for full authorized details and sources. It does not edit Mongo or broaden A2 access.

## Self-development and recovery

`development_files/read/write/run/publish` target the selected persona package by default; `project="core"` selects the existing authorized cognition source project. `/skills` is the writable persona candidate; native discovery uses the selected immutable artifact. Core updates do not overwrite existing self heads.

`BOOT_FAILED` / `PACK_FAILED` preserve the failed candidate and diagnostics. `APPLIED` means selected, not yet confirmed running. `ACTIVE` means the relevant worker/resources loaded successfully. `HOST_RESTART_REQUIRED` means restart this Host to install the selected JS/composition/dependency artifact. The launcher retains installation failures and still opens the installed repair floor. There is no automatic rollback.

If the worker fails, create a native session using **Asuna recovery** in the authorized local workspace. Its project tools operate independently of Python, preserve the selected candidate and publish a forward correction. A normal Python correction can restart only the worker. Protected publication/repair/persistence modules and the stable entry remain outside autonomous edits.

## Demo environment

Manual Web checks of new behavior use a synthetic persona and a separate database, never the real profile:

```powershell
.\.venv\Scripts\python.exe tools\make_demo_config.py
.\.venv\Scripts\python.exe tools\pack_plugins.py --persona tests\fixtures\personas\demo
.\.venv\Scripts\python.exe tools\setup_native_profile.py --profile asuna-demo --config config\demo.local.json --persona-package tests\fixtures\personas\demo
.\start-asuna.cmd --profile asuna-demo --config config\demo.local.json --port 8790
```

`make_demo_config.py` copies only the Mongo URI and model routes from `config/local.json` into the ignored `config/demo.local.json` (database `asuna_v2_demo_main`, persona `demo`, no channels, integrations or QQ routes, self-development off). Add `--shared-action-model` to the setup command when only the action model is running.

## Maintenance

Other CLI operations require `--debug`; use them for explicit maintenance and read-only evidence, not normal chat or model execution. For example:

```powershell
.\.venv\Scripts\python.exe -m asuna.cli --debug inspect task TASK_ID
```

The maintenance commands are `db-init`, `inspect`, `rollback`, `index`, `delete`, `cancel` and `replay`; `seed --fixture tests/fixtures/world.json` is for tests only. The ADR-001 evaluation commands (`doctor`, `report`, `export`, `review-*`) and the terminal chat were removed. Checks:

```powershell
npm.cmd run test:native
.\.venv\Scripts\python.exe tools\adr009_offline_check.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\check_staged_secrets.py --personal --all
```

`tools/adr009_offline_check.py` needs no Mongo, model or sandbox. The pytest suite creates an isolated `asuna_v2_test_*` database per test and drops it afterwards. The personal-data scan prints only `file:line:category`, never the matched value, and always exits 0.
