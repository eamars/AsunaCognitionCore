# Running Asuna

The default is the native DSH Web profile. One Host owns model execution and the Web UI; its managed Python worker owns business state and existing channel/integration services.

## How Asuna is put together

Asuna runs as plugins in one native DSH **0.2.0-rc.2** Web Host:

- `@asuna/cognition-core` supplies cognition, task/channel authorization, the business worker, and publication tools.
- A persona package (for example `packages/xiaoman`, the persona installed in this deployment) supplies the persona baseline, selected skills and its role preset. The core contains no persona; any persona package can replace it, and `tests/fixtures/personas/demo` is a synthetic one.
- A channel package per platform supplies that platform's id formats, its adapter and the adapter's skill: `packages/napcat-qq` for QQ through NapCat, `packages/dsh-peer` for an agent in another DSH (ADR-013). The core names no platform.

DSH owns model requests, agents, Chat, Trajectory, attachments, compaction and scheduling. One Python worker reuses the existing Mongo state, queues, memory, summaries, channel receipts and integration supervision. Brain names describe responsibilities; both routes may use one model.

The right sidebar offers **记忆** for authorized state and source records. **Plugins → @asuna/cognition-core** contains the Asuna settings card. Save and apply are separate operations; providers and credentials stay in native/local configuration. Existing Mongo persona, self, relationships, history and grants remain authoritative. Package upgrades seed only missing state. Old native lane logs remain on disk for diagnosis and are never replayed or merged into new transcripts.

Owner actions edit the persistent candidate of the selected persona package by default; use `project="core"` for cognition code. `development_publish` builds a frozen artifact and reports its actual activation state. Skill resources apply without restarting the Host; Python updates replace the worker when idle; JS/composition/dependency changes require a Host restart. **Asuna recovery** provides native project tools even when the mutable business worker cannot start. See [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md) for package contracts and lifecycle, [RUNTIME_API.md](RUNTIME_API.md) for channel/tool semantics, and [AGENTS.md](AGENTS.md) for development rules. Plans in `docs/development_plans/` preserve design history rather than current runtime documentation.

To install the released plugins into another DeepSeek Harness profile, follow [INSTALL.md](INSTALL.md). The core and the channel packages are licensed under the GNU General Public License v3.0 only ([LICENSE](LICENSE)); persona packages are not part of the release.

## Prerequisites and installation

Use the existing Mongo database and private deployment configuration. A compatible Node runtime, Python **3.12+**, and the existing WSL Ubuntu/bubblewrap environment are required for the configured workspace tools. Model and embedding services run independently.

```powershell
npm.cmd ci
.\.venv\Scripts\uv.exe sync
node tools/build_dsh_inline.mjs --source <dedicated-DSH-rc.2-checkout>
.\.venv\Scripts\python.exe tools\pack_plugins.py --persona packages\xiaoman --channel packages\napcat-qq
.\.venv\Scripts\python.exe tools\setup_native_profile.py --persona-package packages\xiaoman --channel-package packages\napcat-qq --shared-action-model
.\start-asuna.cmd
```

The core names no persona and no platform: pass the persona package and each channel package to both the packer and the installer. A configured channel (`channels.qq`) needs its channel package installed; Core reports `CHANNEL_PLUGIN_NOT_INSTALLED` otherwise.

The installer does not initialize, reset, copy or replace Mongo. `--shared-action-model` seeds independent character/action references pointing to the available action model. Omit it on a new profile to seed separate routes. Reinstallation preserves saved profile settings; change routes in the native settings card after initial installation.

Artifacts and hashes are in `.runtime/adr008/packages/manifest.json`. The two Asuna plugins include two reviewed native rendering dependencies in the delivery manifest; see [the pinned extension build](tools/dsh-inline/README.md) for preparing its dedicated checkout. Setup uses DSH's official plugin installer, then verifies every installed file against its content-addressed tarball. No npm publication occurs. For installation into another existing DSH Host, follow the package instructions in [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md).

## Start, review, stop

`start-asuna.cmd` launches the stable Node entry directly, so a broken Python worker cannot prevent the native repair interface from opening. `start-asuna-ui.cmd` and `asuna ui --config config/local.json --port 8780` select the same profile. Both launchers accept `--profile <name>` and `--config <path>` (or `ASUNA_PROFILE` / `ASUNA_CONFIG`); the defaults are `asuna-native` and `config/local.json`. A profile other than `asuna-native` keeps its own DSH home, activation state and candidates under `.runtime/adr008/profiles/<name>/`. `--dry-run` prints the resolved profile, config and database without starting anything. There is no terminal chat.

Open the authenticated `dsh web:` address printed by the launcher. The token is private. Under **Local**, continue **小满 · 本地私聊**. Under **QQ**, each active DM or group has one continuous main conversation; its composer is view-only, so reply through QQ. Use native Chat for conversation and Trajectory for actual steps/tools. Actions and exchange summaries are native children of their role conversation. **Standard mode** remains ordinary DSH. Native New Session remains available for deliberate additional or recovery conversations. Older sessions remain accessible using native View options to show archives.

The colored labels show only **角色脑** (purple) or **行动脑** (blue). Main Chat references the actual action session's thinking, tools and output inline, with character consultations between the corresponding action ranges. Both labels remain visible outside the native process disclosure by default; expanding or collapsing the records does not add another label. Expand DSH's process disclosure and analysis row to inspect full native reasoning, text and tools. DSH's own controls show execution status. Both brains can use the same model without losing their identity labels. In a character conversation the composer shows two context wheels, both DSH's own meter with its click-open breakdown: the stock one, tinted purple, for the character brain, and a second instance fed the latest action session's context projections, tinted blue. DSH does not export the meter; the plugin reads it from the rendered stock meter, and if a DSH revision changes that, the blue wheel is simply absent.

Role, action, summary and recovery presets mount DSH's native compaction backend and tool-result pruner; the action, summary and recovery presets also mount DSH's `/compact` command, the character preset does not (manual compaction is not something a person does; automatic compaction stays). Automatic compaction replaces older model context with a summary while retaining the durable originals and recent history; this does not reset the conversation or merge the two brains' contexts. The action, summary and recovery presets keep DSH's engineering summary template (8,192 output tokens, 32% retained). The character preset uses `@asuna/cognition-core/compaction`: DSH's engine with a Chinese role-play checkpoint (conversation thread, open threads, promises, corrections, the other person's state, delegated work) that leaves out the program-provided blocks, 24,576 output tokens (the character route reasons first), a 16% retained tail and a 32,768-token reserve. Where mounted, `/compact` remains subject to the model's capacity: an already oversized selected span can fail, and a summary must be smaller than the history it replaces. Check native compaction records and the actual reply before treating context recovery as successful.

Each character turn's context is prepared in full by the worker and composed by the plugin when the notice enters the session: a block, history row or recalled memory identical to a copy within the newest 32,768 estimated tokens (inside every compaction's retained tail) is not repeated, and the notice names what it left out. Anything older, including what a compaction absorbed, is sent again. Long text in the context is cut with a marker: history rows at 1,500 characters, recalled memories at 1,200, task reports at 6,000 with the last four tool observations at 600 each; the full records stay readable.

Recall ranking forgets by time and by volume (persona model `memory.forgetting`, defaults: 30-day and 1,500-message half-lives). Each candidate's score is multiplied by 0.5^(days since its last real use / half_life_days) × 0.5^(messages in its conversation since then / half_life_messages); a memory a character turn actually used is fresh again, while consultations, probes and the history tool do not count as use. Pinned memories (owner-private turns only) do not fade. A raw chat chunk below `step_back_below` (0.1) whose message a summary already covers is left out of automatic recall; an explicit recall round and the history tool still reach it. Nothing is deleted.

Ctrl+C stops this Host and its managed worker/adapters. Let active work settle before a manual restart. Do not start two instances consuming the same channel routes. Restart with the same command. Unfinished old actions and task feedback pause instead of calling either brain automatically; their native context, results and receipts remain. In the existing local conversation, explicitly ask to continue the paused work. The character's new decision can reuse its original execution binding and must first check prior results. A task cancelled by the user cannot be revived this way. Completed feedback is reconciled without generation. External model services are not stopped by Asuna.

To adjust an ongoing action, describe the change in the same local conversation. If the character delegates a revision of its own READY/RUNNING task, the task keeps its identity, advances its intent revision and stops the exact old native operation. The new version resumes that action's existing history after native teardown. Old callbacks cannot borrow the new version's tool grant, and an accepted earlier effect is not automatically undone. Continuing already returned work creates a new task grant on the preserved action history; restart-paused work still needs an explicit new local request, and user-cancelled work cannot be continued. The two brains' actual records stay in the same main Chat.

UI development uses an isolated native DSH profile with synthetic inference for both brains. It must not start the production worker, consume live QQ queues or call real model endpoints (including background summaries). The operator's external model server remains independent. Re-enabling real-model use requires the operator's explicit instruction. Character labels are purple and action labels blue; their text remains the authoritative distinction in both light and dark themes.

## Settings and private files

- `config/local.json`: migration source for existing Mongo, workspace and business configuration. Set `timezone` (an IANA name) here; without it clocks and schedules are shown in UTC and say so — the core has no built-in time zone.
- Adjacent `*.models.local.json`: deployment seed routes and model credentials. After installation, active model references belong to the native profile.
- Adjacent `asuna-channel.local.json`: initial authenticated routes, identities, grants and A2 read links; imported only when enabled.
- Adjacent `integration.local.json`: initial managed adapter configuration and approved network aliases.
- These two sibling files belong to `config/local.json` only. Any other config file names them explicitly with `channel_config` / `integration_config`, so a second config never inherits real routes.
- `config/personal-denylist.local.txt` (ignored; template `config/personal-denylist.example.txt`): your own account names, host names and similar literals for `tools/check_staged_secrets.py --personal`.
- `.runtime/adr008/home/profiles/asuna-native/cordis.patch.yml`: editable native provider and Asuna settings. Do not pass it again as a command-line overlay.
- A thinking model needs a thinking budget, or one step can think through its whole output limit and say nothing. Give its provider `compat` `"supportsThinkingTokenBudget": true` and the field its server reads (`"thinkingTokenBudgetField": "thinking_token_budget"`, `thinking_budget` or `thinking_budget_tokens`). DSH then sends a per-effort budget (medium 8,192, high 16,384, set per model with `thinkingBudgets`), capped so at least 1,024 tokens stay for the answer. The server must end its thinking at that budget; one that ignores the field gets no protection from it.

After migration the native profile's `deployment` is authoritative and its secrets are in DSH's credential store (the setup tool moves them there; the settings keep only `ASUNA_…` references); editing the old JSON files does not silently override saved settings. DSH's native Models page owns provider definitions and model API keys. No launcher environment override shadows keys changed there.

In **Plugins → @asuna/cognition-core**, edit business values (structured fields use JSON), persona/model references and credential fields, save, then **应用已保存设置**. Set **QQ 接入策略** to `automatic` for new DMs/groups/members, or `explicit` for configured enrollment. New contacts get isolated workspaces; they inherit no owner access. Use `channels.<id>.blocked_senders` / `blocked_groups` to refuse specific QQ identities. The native write-only JSON credential field can provision new secret references in the same save.

The card reports saved-but-not-applied state and actual failures. Save preflights without model calls; invalid drafts remain editable. Apply pauses ingress/background summaries and requires user/action work to be idle. It reloads an already-enabled adapter from the installed persona package, and restores the previous running configuration if activation fails. Old native conversation names and deliberate archives survive restart; the next QQ message reopens that target's same conversation. Reasoning, input modalities and limits come from configured model metadata, never the lane name. No process-running label is a QQ delivery guarantee.

The **记忆** right tab reads bounded pages for the current native scene binding. Open a row for full authorized details and sources. It does not edit Mongo or broaden A2 access.

## Self-development and recovery

`development_files/read/write/run/publish` target the selected persona package by default; `project="core"` selects the existing authorized cognition source project. Skills live in the candidate too and change only through these tools; native discovery uses the selected immutable artifact. Core updates do not overwrite existing self heads.

Only two sources hand work with these tools to the action brain (ADR-011): the owner asking in a private chat (the local chat or the owner's DM) and her own self-improvement turns, with `self_development.enabled`. Anyone else's request can only become an entry in her improvement-idea notebook (`note_idea`, from either brain), which she reads and decides (`review_idea`, with reasons kept) in her self-improvement turns or when the owner asks in private (`read_ideas`). Core ships the persona-agnostic skill `asuna-self-improvement`.

`BOOT_FAILED` / `PACK_FAILED` preserve the failed candidate and diagnostics. The boot probe checks syntax, imports the plugin entry in a child process (resolving Host packages from this installation), and reads `persona-model.json` (its persona id cannot change) and `cordis.patch.yml`. `APPLIED` means selected, not yet confirmed running. `ACTIVE` means the relevant worker/resources loaded successfully. `HOST_RESTART_REQUIRED` means restart this Host to install the selected JS/composition/dependency artifact. The launcher retains installation failures and still opens the installed repair floor. A selection that is installed but never confirms running for more than two starts is replaced by the previous ACTIVE selection, which the launcher installs again; the published source is never rolled back.

If the worker fails, create a native session using **Asuna recovery** in the authorized local workspace. Its project tools operate independently of Python, preserve the selected candidate and publish a forward correction. A normal Python correction can restart only the worker. Protected publication/repair/persistence modules, the modules they import (`persona.js`, `channel.js`, `settings.js`) and the stable entry remain outside autonomous edits.

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
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\check_staged_secrets.py --personal --all
.\.venv\Scripts\python.exe tools/probe_qq_admission.py packages/napcat-qq
node tools/probe_native_schedule.mjs
```

The tests keep only invariants whose breakage would be visible or harmful: privacy and visibility boundaries, authorization and epoch fencing, exactly-once ingest/publication, crash recovery, audit integrity, sandbox isolation and the visible native behavior. The `store` fixture builds the migrated, audited fixture world once per session and resets a reused `asuna_v2_test_*` database to it for each test; every test database is dropped at session end. The personal-data scan prints only `file:line:category`, never the matched value, and always exits 0. `tools/p2_offline_check.py`, `tools/p3_offline_check.py`, `tools/p5_offline_check.py` and `tools/p1c_offline_check.py` need no Mongo; they are the persona's self-development checks inside its sandbox. Skip Mongo tests while the service is unavailable.
