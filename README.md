# Asuna Cognition Core

Asuna runs as two plugins in one native DSH **0.2.0-rc.2** Web Host:

- `@asuna/cognition-core` supplies cognition, task/channel authorization, the business worker, and publication tools.
- `@asuna/xiaoman` supplies the existing 小满 persona baseline, selected skills, QQ adapter source, and its role preset.

DSH owns model requests, agents, Chat, Trajectory, attachments, compaction and scheduling. One Python worker reuses the existing Mongo state, queues, memory, summaries, channel receipts and integration supervision. Brain names describe responsibilities; both routes may use one model.

## Start

After installing the local profile as described in [RUN_ASUNA.md](RUN_ASUNA.md):

```powershell
.\start-asuna.cmd
```

`start-asuna-ui.cmd` is an alias; `asuna ui` opens the same native profile. Open the authenticated localhost address printed by DSH (default port **8780**), select the owner workspace and **小满**, and use the native composer. Delegated tasks have real **Asuna Action** sessions, linked from their initiating role turn.

The right sidebar offers **记忆** for authorized state and source records. **Plugins → @asuna/cognition-core** contains the Asuna settings card. Save and apply are separate operations; providers and credentials stay in native/local configuration.

Existing Mongo persona, self, relationships, history and grants remain authoritative. Package upgrades seed only missing state. Old native lane logs remain on disk for diagnosis and are never replayed or merged into new transcripts.

## Develop

Owner actions edit the persistent `xiaoman` candidate by default; use `project="core"` for cognition code. `development_publish` builds a frozen artifact and reports its actual activation state. Skill resources apply without restarting the Host; Python updates replace the worker when idle; JS/composition/dependency changes require a Host restart. **Asuna recovery** provides native project tools even when the mutable business worker cannot start.

See [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md) for package contracts and lifecycle, [RUNTIME_API.md](RUNTIME_API.md) for channel/tool semantics, and [AGENTS.md](AGENTS.md) for development rules. Plans in `docs/development_plans/` preserve design history rather than current runtime documentation.
