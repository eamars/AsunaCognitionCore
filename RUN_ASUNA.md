# Running Asuna

This page runs Asuna from a checkout of this repository: installing, starting, adding packages, settings and
checks. To install the released plugins into a DeepSeek Harness you already have, follow [INSTALL.md](INSTALL.md)
instead. How the packages fit together inside DSH is in [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md); the channel and tool
contracts are in [RUNTIME_API.md](RUNTIME_API.md); working on the code is in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## How Asuna is put together

Asuna runs as plugins in one native DSH **0.2.0-rc.2** Web Host:

- `@asuna/cognition-core` (`packages/cognition-core`) supplies cognition, task/channel authorization, the business worker, and publication tools. It names no persona and no platform.
- **One persona package** (`packages/personas/*`) supplies the persona baseline, selected skills and its role preset. Any persona package can replace another; `tests/fixtures/personas/demo` is a synthetic one.
- **Any number of channel packages** (`packages/channels/*`) supply a platform's id formats, its adapter and the adapter's skill: `napcat-qq` for QQ through NapCat, `dsh-peer` for an agent in another DSH.
- Optionally, the **inline rendering extension** (`tools/dsh-inline`): two patched DSH UI packages, built locally, that show the action brain's work inside the main conversation.

DSH owns model requests, agents, Chat, Trajectory, attachments, compaction and scheduling. One Python worker owns the Mongo state, queues, memory, summaries, channel receipts and integration supervision. Brain names describe responsibilities; both routes may use one model.

The right sidebar offers **记忆** for authorized state and source records. **Plugins → @asuna/cognition-core** contains the Asuna settings card. Existing Mongo persona, self, relationships, history and grants remain authoritative: package upgrades seed only missing state.

The core and the channel packages are licensed under the GNU General Public License v3.0 only ([LICENSE](LICENSE)); persona packages are not part of the release.

## Install from a checkout

You need Node (the version DSH 0.2.0-rc.2 supports), Python **3.12+** through [uv](https://docs.astral.sh/uv/), MongoDB with vector search (Atlas, Atlas Local, or Community with mongot; see [INSTALL.md](INSTALL.md#what-you-need)), and a model server for each brain (both may share one). Model and embedding services run independently of Asuna. Commands run under DSH's own sandbox.

First write `config/local.json` from [config/local.example.json](config/local.example.json) (see [Settings and private files](#settings-and-private-files)). Then pack the packages and install them into the profile. Pass the persona package and **every** channel package you want to both the packer and the installer:

### Windows

```powershell
npm.cmd ci
.\.venv\Scripts\uv.exe sync
node tools/build_dsh_inline.mjs --source <dedicated-DSH-rc.2-checkout>
.\.venv\Scripts\python.exe tools\pack_plugins.py --persona packages\personas\xiaoman --channel packages\channels\napcat-qq
.\.venv\Scripts\python.exe tools\setup_native_profile.py --persona-package packages\personas\xiaoman --channel-package packages\channels\napcat-qq --shared-action-model
.\start-asuna.cmd
```

This install's `.runtime` grants the owner's account full control, which DSH's Windows sandbox needs. The `build_dsh_inline.mjs` line is optional (see [the extension's README](tools/dsh-inline/README.md)).

### Linux or macOS

The steps are the same; only the shell differs: Asuna uses DSH's platform layer and assumes no OS. DSH's sandbox needs unprivileged user namespaces for bubblewrap, or Landlock (Linux 5.13+), which it falls back to; Ubuntu 23.10 and later restrict user namespaces through AppArmor, so DSH uses Landlock there unless `bwrap` is allowed.

```bash
npm ci
uv sync
node tools/build_dsh_inline.mjs --source <dedicated-DSH-rc.2-checkout>
.venv/bin/python tools/pack_plugins.py --persona packages/personas/xiaoman --channel packages/channels/napcat-qq --channel packages/channels/dsh-peer
.venv/bin/python tools/setup_native_profile.py --persona-package packages/personas/xiaoman --channel-package packages/channels/napcat-qq --channel-package packages/channels/dsh-peer --shared-action-model
./start-asuna.sh
```

As a service, a systemd unit runs the same entry under an unprivileged user (adjust the user and the checkout path):

```ini
[Unit]
Description=Asuna (native DSH Web host)
After=network-online.target

[Service]
User=<user>
WorkingDirectory=<checkout>
Environment=TZ=<IANA time zone>
ExecStart=<checkout>/start-asuna.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Docker

Deploy `deploy/docker/` as a stack (see [its README](deploy/docker/README.md)): the image holds the toolchain, the checkout lives on a volume, and the container starts through the same launcher. Docker is one deployment layer on top of DSH; nothing above needs it.

### What the installer does

- It installs through DSH's official plugin installer, then checks every installed file against its content-addressed tarball. Artifacts and hashes are in `.runtime/adr008/packages/manifest.json`. Nothing is published to npm.
- It does not initialize, reset, copy or replace Mongo.
- `--shared-action-model` routes both brains to the configured action model. Omit it on a new profile to seed separate routes.
- `--channel-admission automatic` admits new DMs, groups and members on a profile that has not saved its own choice (the default is `explicit`).
- Reinstalling keeps the profile's saved settings; after the first install, change routes on the settings card.
- It records the package list in `.runtime/adr008/launch.json` (`setup`), which later starts reuse (below).
- A configured channel (`channels.qq`) needs its channel package installed; Core reports `CHANNEL_PLUGIN_NOT_INSTALLED` otherwise.

## Start, review, stop

`start-asuna.cmd` (Windows) and `./start-asuna.sh` (Linux, macOS) run the same stable Node entry, `tools/asuna-launch.mjs`, so a broken Python worker cannot prevent the native repair interface from opening. `start-asuna-ui.cmd` and `asuna ui --config config/local.json --port 8780` select the same profile. There is no terminal chat.

**Each start installs the checkout when it changed:**

1. The launcher packs the packages recorded in `launch.json` and compares their digests with the installed ones.
2. Only when one differs does it run the installer again, with the same arguments. Packing is deterministic, so an unchanged checkout costs a few seconds and installs nothing.
3. Whatever is on disk is installed: uncommitted edits and her published changes alike.
4. The installer records the previous running package, so a start that never comes up returns to it (two tries).

`--no-sync` starts what is installed without looking at the checkout. A profile with no `setup` in `launch.json` (installed before the launcher synced) needs the installer once by hand.

Both launchers accept `--profile <name>` and `--config <path>` (or `ASUNA_PROFILE` / `ASUNA_CONFIG`); the defaults are `asuna-native` and `config/local.json`. A profile other than `asuna-native` keeps its own DSH home, activation state and candidates under `.runtime/adr008/profiles/<name>/`. `--dry-run` prints the resolved profile, config and database without starting anything.

Open the authenticated `dsh web:` address printed by the launcher. The token is private. Workspaces carry the character's name (**<persona> · 本地**, **<persona> · QQ**). Under the local workspace, continue the persona's local chat. Under each channel's workspace, each active DM or group has one continuous main conversation; its composer is view-only, so reply on the platform. Use native Chat for conversation and Trajectory for actual steps and tools. **Standard mode** remains ordinary DSH. Native New Session remains available for deliberate additional or recovery conversations; archived sessions show through native View options.

Ctrl+C stops this Host and its managed worker and adapters. Let active work settle before a manual restart, and restart with the same command. **Never start two instances that consume the same channel routes.** Unfinished old actions and task feedback pause instead of calling either brain automatically; their native context, results and receipts remain. In the local conversation, explicitly ask to continue the paused work: the character's new decision can reuse its original execution binding and must first check prior results. A task cancelled by the user cannot be revived this way. External model services are not stopped by Asuna.

To adjust an ongoing action, describe the change in the same local conversation. If the character delegates a revision of its own READY/RUNNING task, the task keeps its identity, advances its intent revision and stops the exact old native operation; the new version resumes that action's existing history. Old callbacks cannot borrow the new version's tool grant, and an accepted earlier effect is not automatically undone. Continuing already returned work creates a new task grant on the preserved action history.

## Add or remove an optional package

Optional packages are channel packages, a different persona package, and the inline rendering extension. A profile has exactly one persona and any number of channels. The rule for all of them: **install the package first, configure it second; remove the configuration first, the package second.** A channel package without its configuration is idle; a configured channel without its package stops the worker (`CHANNEL_PLUGIN_NOT_INSTALLED`).

### From a checkout (Windows, Linux, macOS)

1. **Stop the Host** (Ctrl+C).
2. **Pack and install with the full list**: the persona and every channel the profile should have, the new one included. Use the same commands as [the first install](#install-from-a-checkout), for example adding `--channel packages/channels/dsh-peer` and `--channel-package packages/channels/dsh-peer`. The installer records the new list in `launch.json`; every later start keeps it.
3. **Configure it.** For a channel, open **Plugins → @asuna/cognition-core** and add `channels.<id>` (and, for a channel with a managed adapter, `integration`) to the deployment fields; credential fields take its tokens. The channel package's README lists exactly what it needs: [QQ](packages/channels/napcat-qq/README.md#setting-up-qq), [DSH peer](packages/channels/dsh-peer/README.md#configuration-owner-local). **Save**, then **Apply saved settings**.
4. **Start** with the usual command and check the Plugins page lists the package, and the card's status line is `ready`.

To replace the persona, pass the other persona package in step 2. Rather than switching the persona of a live profile, give a different persona its own profile and database, as the demo environment and the Docker stack do.

To remove a channel: delete `channels.<id>` (and its `integration` entries) on the settings card and apply; stop the Host; uninstall the package on DSH's Plugins page (or `dsh plugin --profile <name> remove <package name>`, which forwards to pnpm); run the installer once with the remaining list, so `launch.json` stops packing it.

The inline rendering extension is not in the list: build it once (`node tools/build_dsh_inline.mjs --source <checkout>`), and every later pack and install includes it. Without a build, the action brain's work opens in DSH's own subagent view. To go back to that view, delete `.runtime/adr008/packages/native-inline-manifest.json` and uninstall its two packages on the Plugins page.

### In Docker

The stack's environment holds the list and the channel settings; see [deploy/docker/README.md](deploy/docker/README.md#add-or-remove-a-package). Change `ASUNA_CHANNEL_PACKAGES` (and give the channel's settings in `ASUNA_CHANNEL_CONFIG_JSON` / `ASUNA_INTEGRATION_CONFIG_JSON` on a profile's first start, or on the settings card later) and redeploy: the entrypoint installs again when the list differs from the recorded one.

### Into a released install

Add the package's `.tgz` with `dsh plugin --profile <name> add <package.tgz>` and restart the profile; see [INSTALL.md](INSTALL.md#5-optional-a-channel).

## Running several characters

Each character is a profile with one persona and its own Web page, whose workspaces carry the character's name. Several can run at once, on one machine or several.

| Each character has its own | May be shared between characters |
|---|---|
| profile: DSH home, saved settings, credentials, data folder | the MongoDB server (each character its own database on it) |
| database | the model servers and the embedding service |
| platform accounts: a QQ number, a peer session | a NapCat server that logs in several accounts, each with its own WebSocket port and token |
| Web port, and `channel_port` (default 8766) on a machine with more than one | the checkout and installed DSH on one machine |

- **One platform account per running character.** Nothing stops two characters on the same QQ account: both receive
  every message and both answer it, from one account in two voices. Stop one before starting the other.
- **One running Host per database.** A second Host on the same database, from any machine, is refused with
  `DATABASE_IN_USE`, naming the character and machine holding it. A crashed Host's claim expires after 90 seconds;
  a restart of the same deployment takes over at once.
- **A database stays with its profile.** Conversations are bound to the profile's data folder, so a database cannot
  be moved to another profile; a new profile starts with a new database.
- **Ports:** `tools/setup_native_profile.py --port <port>` records a profile's Web port, and every start uses it.
  `start-asuna.cmd --list` (or `./start-asuna.sh --list`) prints each installed profile with its persona, port,
  database and whether something answers on its port.
- **Self-development:** characters on one checkout share the core, so a core change one of them publishes reaches
  the others on their next start. Persona and channel packages stay each character's own.
- A Docker stack is one character with its own checkout; several stacks need different `ASUNA_NAME` and ports
  ([deploy/docker](deploy/docker/README.md)).

## Using the Web page

The colored labels show only **角色脑** (purple) or **行动脑** (blue). Main Chat references the actual action session's thinking, tools and output inline, with character consultations between the corresponding action ranges. Both labels remain visible outside the native process disclosure by default. Expand DSH's process disclosure and analysis row to inspect full native reasoning, text and tools. DSH's own controls show execution status. Both brains can use the same model without losing their identity labels.

In a character conversation the composer shows two context wheels, both DSH's own meter with its click-open breakdown: the stock one, tinted purple, for the character brain, and a second instance fed the latest action session's context projections, tinted blue. DSH does not export the meter; the plugin reads it from the rendered stock meter, and if a DSH revision changes that, the blue wheel is simply absent.

UI development uses an isolated native DSH profile with synthetic inference for both brains (see [Demo environment](#demo-environment)). It must not start the production worker, consume live channel queues or call real model endpoints (including background summaries). Re-enabling real-model use requires the operator's explicit instruction.

## Context, compaction and recall

Role, action, summary and recovery presets mount DSH's native compaction backend and tool-result pruner; the action, summary and recovery presets also mount DSH's `/compact` command, the character preset does not (manual compaction is not something a person does; automatic compaction stays). Automatic compaction replaces older model context with a summary while retaining the durable originals and recent history; this does not reset the conversation or merge the two brains' contexts. The action, summary and recovery presets keep DSH's engineering summary template (8,192 output tokens, 32% retained). The character preset uses `@asuna/cognition-core/compaction`: DSH's engine with a Chinese role-play checkpoint (conversation thread, open threads, promises, corrections, the other person's state, delegated work) that leaves out the program-provided blocks, 24,576 output tokens (the character route reasons first), a 16% retained tail and a 32,768-token reserve. Where mounted, `/compact` remains subject to the model's capacity: an already oversized selected span can fail, and a summary must be smaller than the history it replaces. Check native compaction records and the actual reply before treating context recovery as successful.

Each character turn's context is prepared in full by the worker and composed by the plugin when the notice enters the session: a block, history row or recalled memory identical to a copy within the newest 32,768 estimated tokens (inside every compaction's retained tail) is not repeated, and the notice names what it left out. Anything older, including what a compaction absorbed, is sent again. Long text in the context is cut with a marker: history rows at 1,500 characters, recalled memories at 1,200, task reports at 6,000 with the last four tool observations at 600 each; the full records stay readable.

Recall ranking forgets by time and by volume (persona model `memory.forgetting`, defaults: 30-day and 1,500-message half-lives). Each candidate's score is multiplied by 0.5^(days since its last real use / half_life_days) × 0.5^(messages in its conversation since then / half_life_messages); a memory a character turn actually used is fresh again, while consultations, probes and the history tool do not count as use. Pinned memories (owner-private turns only) do not fade. A raw chat chunk below `step_back_below` (0.1) whose message a summary already covers is left out of automatic recall; an explicit recall round and the history tool still reach it. Nothing is deleted.

## Settings and private files

All of these are ignored by git. Templates are tracked next to them as `*.example.*`.

- `config/local.json` (template `config/local.example.json`): migration source for Mongo, workspace and business configuration. Set `timezone` (an IANA name) here; without it clocks and schedules are shown in UTC and say so — the core has no built-in time zone.
- Adjacent `*.models.local.json`: deployment seed routes and model credentials. After installation, active model references belong to the native profile.
- Adjacent `asuna-channel.local.json` (template `config/asuna-channel.example.json`): initial authenticated routes, identities, grants and A2 read links; imported only when `enabled`.
- Adjacent `integration.local.json` (template `config/integration.example.json`): initial managed adapter configuration and approved network endpoints.
- These two sibling files belong to `config/local.json` only. Any other config file names them explicitly with `channel_config` / `integration_config`, so a second config never inherits real routes.
- `config/personal-denylist.local.txt` (template `config/personal-denylist.example.txt`): your own account names, host names and similar literals for `tools/check_staged_secrets.py --personal`.
- `.runtime/adr008/home/profiles/asuna-native/cordis.patch.yml`: editable native provider and Asuna settings. Do not pass it again as a command-line overlay.

A thinking model needs a thinking budget, or one step can think through its whole output limit and say nothing. Give its provider `compat` `"supportsThinkingTokenBudget": true` and the field its server reads (`"thinkingTokenBudgetField": "thinking_token_budget"`, `thinking_budget` or `thinking_budget_tokens`). DSH then sends a per-effort budget (medium 8,192, high 16,384, set per model with `thinkingBudgets`), capped so at least 1,024 tokens stay for the answer. The server must end its thinking at that budget; one that ignores the field gets no protection from it.

After migration the native profile's `deployment` is authoritative and its secrets are in DSH's credential store (the setup tool moves them there; the settings keep only `ASUNA_…` references); editing the old JSON files does not silently override saved settings. DSH's native Models page owns provider definitions and model API keys. No launcher environment override shadows keys changed there.

In **Plugins → @asuna/cognition-core**, edit business values (structured fields use JSON), persona/model references and credential fields, save, then **应用已保存设置**. Set **QQ 接入策略** to `automatic` for new DMs/groups/members, or `explicit` for configured enrollment. New contacts get isolated workspaces; they inherit no owner access. Use `channels.<id>.blocked_senders` / `blocked_groups` to refuse specific identities. The native write-only JSON credential field can provision new secret references in the same save.

The card reports saved-but-not-applied state and actual failures. Save preflights without model calls; invalid drafts remain editable. Apply pauses ingress/background summaries and requires user/action work to be idle. It reloads an already-enabled adapter from the installed channel package, and restores the previous running configuration if activation fails. Reasoning, input modalities and limits come from configured model metadata, never the lane name. No process-running label is a delivery guarantee.

The **记忆** right tab reads bounded pages for the current native scene binding. Open a row for full authorized details and sources. It does not edit Mongo or broaden A2 access.

## Self-development and recovery

`development_files/read/write/run/publish` target the selected persona package by default; `project="core"` selects the cognition source, and a channel package is its own project (`napcat-qq`). Skills live in the candidate too and change only through these tools; native discovery uses the selected immutable artifact. Core updates do not overwrite existing self heads.

Only two sources hand work with these tools to the action brain: the owner asking in a private chat (the local chat or the owner's DM) and her own self-improvement turns, with `self_development.enabled`. Anyone else's request can only become an entry in her improvement-idea notebook (`note_idea`, from either brain), which she reads and decides (`review_idea`, with reasons kept) in her self-improvement turns or when the owner asks in private (`read_ideas`). Core ships the persona-agnostic skill `asuna-self-improvement`.

`development_publish` builds a frozen artifact and reports its actual state:

- `BOOT_FAILED` / `PACK_FAILED`: the failed candidate and diagnostics are kept; nothing new was activated. The boot probe checks syntax, imports the plugin entry in a child process (resolving Host packages from this installation), and reads `persona-model.json` (its persona id cannot change) and `cordis.patch.yml`.
- `APPLIED`: selected, not yet confirmed running.
- `ACTIVE`: the relevant worker or resources loaded successfully.
- `HOST_RESTART_REQUIRED`: restart this Host to install the selected JS, composition or dependency change.

At night she gets self-improvement turns in stages: inside a window on her clock (default 01:00–06:00) one every N minutes (default 30), each with the development grant. A stage is skipped while an earlier one's turn or task is still at work, or while one of her publications is still being activated, so one stage does one thing. The window and pace are her policy keys (`self_development.night_start_hour`, `night_hours`, `night_every_min`); `self_development.night: false` in the local config switches the stages off. A publication that needs a Host restart waits for the owner to restart the Host; until then the Asuna plugin card says which project's change waits and since when, the stages go on, and a self-improvement turn cannot publish to that project.

Skill resources apply without restarting the Host; Python updates replace the worker when idle. A selection that is installed but never confirms running for more than two starts is replaced by the previous ACTIVE selection, which the launcher installs again; the published source is never rolled back.

If the worker fails, create a native session using **Asuna recovery** in the authorized local workspace. Its project tools operate independently of Python, preserve the selected candidate and publish a forward correction. Protected publication/repair/persistence modules, the modules they import (`persona.js`, `channel.js`, `settings.js`), the launcher and the install tools remain outside autonomous edits.

## Demo environment

Manual Web checks of new behavior use a synthetic persona and a separate database, never the real profile:

```powershell
.\.venv\Scripts\python.exe tools\make_demo_config.py
.\.venv\Scripts\python.exe tools\pack_plugins.py --persona tests\fixtures\personas\demo
.\.venv\Scripts\python.exe tools\setup_native_profile.py --profile asuna-demo --config config\demo.local.json --persona-package tests\fixtures\personas\demo
.\start-asuna.cmd --profile asuna-demo --config config\demo.local.json --port 8790
```

`make_demo_config.py` copies only the Mongo URI and model routes from `config/local.json` into the ignored `config/demo.local.json` (database `asuna_v2_demo_main`, persona `demo`, no channels, integrations or QQ routes, self-development off). Add `--shared-action-model` to the setup command when only the action model is running.

## Maintenance and checks

Other CLI operations require `--debug`; use them for explicit maintenance and read-only evidence, not normal chat or model execution:

```powershell
.\.venv\Scripts\python.exe -m asuna.cli --debug inspect task TASK_ID
```

The maintenance commands are `db-init` (create collections and indexes in an authorized database), `inspect`, `rollback`, `index`, `delete`, `cancel` and `replay`; `seed --fixture tests/fixtures/world.json` is for tests only.

```powershell
npm.cmd run test:native
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\check_staged_secrets.py --personal --all
```

What the tests guarantee and how they treat Mongo is in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#tests). Every script under `tools/` is listed in [tools/README.md](tools/README.md).
