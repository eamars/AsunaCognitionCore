# Asuna Cognition Core

Asuna runs as plugins in one native DSH **0.2.0-rc.2** Web Host:

- `@asuna/cognition-core` supplies cognition, task/channel authorization, the business worker, and publication tools.
- A persona package (for example `packages/xiaoman`, the persona installed in this deployment) supplies the persona baseline, selected skills and its role preset. The core contains no persona; any persona package can replace it, and `tests/fixtures/personas/demo` is a synthetic one.
- A channel package per platform (`packages/napcat-qq` for QQ through NapCat) supplies that platform's id formats, its adapter and the adapter's skill. The core names no platform.

DSH owns model requests, agents, Chat, Trajectory, attachments, compaction and scheduling. One Python worker reuses the existing Mongo state, queues, memory, summaries, channel receipts and integration supervision. Brain names describe responsibilities; both routes may use one model.

## Start

After installing the local profile as described in [RUN_ASUNA.md](RUN_ASUNA.md):

```powershell
.\start-asuna.cmd
```

`start-asuna-ui.cmd` is an alias; `asuna ui` opens the same native profile. Open the authenticated localhost address printed by DSH (default port **8780**), select **Local** or **QQ**, and use the native composer. Delegated tasks keep real native action sessions; their original records appear in the main conversation, with blue **行动脑** and purple **角色脑** labels. Native reasoning and tool disclosures expand to show details. QQ conversations remain view-only.

The right sidebar offers **记忆** for authorized state and source records. **Plugins → @asuna/cognition-core** contains the Asuna settings card. Save and apply are separate operations; providers and credentials stay in native/local configuration.

Existing Mongo persona, self, relationships, history and grants remain authoritative. Package upgrades seed only missing state. Old native lane logs remain on disk for diagnosis and are never replayed or merged into new transcripts.

## Develop

Owner actions edit the persistent candidate of the selected persona package by default; use `project="core"` for cognition code. `development_publish` builds a frozen artifact and reports its actual activation state. Skill resources apply without restarting the Host; Python updates replace the worker when idle; JS/composition/dependency changes require a Host restart. **Asuna recovery** provides native project tools even when the mutable business worker cannot start.

See [NATIVE_PLUGIN.md](NATIVE_PLUGIN.md) for package contracts and lifecycle, [RUNTIME_API.md](RUNTIME_API.md) for channel/tool semantics, and [AGENTS.md](AGENTS.md) for development rules. Plans in `docs/development_plans/` preserve design history rather than current runtime documentation.

## Install and licence

To install the released plugins into a DeepSeek Harness profile, follow [INSTALL.md](INSTALL.md) (written for the
agent or person doing the install). The core (`packages/cognition-core`) and the channel packages are licensed under
the GNU General Public License v3.0 only ([LICENSE](LICENSE)). Persona packages are not part of the release and carry
no licence from this repository.
