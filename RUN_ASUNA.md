# Running Asuna

This runbook covers the local Web workbench and the optional runtime profiles. Normal conversation and product interaction use the Web UI.

## Prerequisites

- Windows with the repository's Python virtual environment and pinned DSH UI dependency installed.
- Python 3.12 or newer, as declared by `pyproject.toml`.
- A reachable MongoDB database and reachable provider endpoints for the configured lanes. The UI can start without a model service in read-only mode.
- An existing local configuration at `config/local.json`.

For a new development environment, install the locked dependencies once:

```powershell
uv sync --frozen
npm.cmd ci
```

Copy `config/local.example.json` to `config/local.json` only when a local file does not already exist. Review and replace deployment-specific addresses, model IDs, scene and person IDs, database allowlists, and runtime paths before starting. Keep credentials and local overrides out of Git. Do not seed or reset a database that already contains Asuna data.

## Start and open the Web UI

Run the repository entry point from PowerShell or Command Prompt:

```powershell
.\start-asuna.cmd
```

`start-asuna-ui.cmd` is an alias. The default UI address is `http://127.0.0.1:8765/asuna/`. To use a different UI port:

```powershell
.\start-asuna.cmd --port 8780
```

The browser is an interface to the running host. Closing the browser tab does not stop the host. Do not run two writable hosts against the same database and DSH home.

## Stop and restart

Use **停止整个服务** in the workbench or press Ctrl+C in the process window. Restart with `start-asuna.cmd`.

The host persists accepted input before processing it and recovers eligible queued work on restart. It does not blindly replay an external send whose outcome is unknown. See [RUNTIME_API.md](RUNTIME_API.md) for task and publication recovery semantics.

## Configuration

- `config/local.json` holds the local database, runtime paths, lane routes, and owner scene. This file is ignored by Git.
- Model settings changed in the UI are saved to the adjacent `*.models.local.json` override. The character and action lanes can use the same or different providers and models. API keys are local and are not returned by the UI.
- To enable channel routes, create `asuna-channel.local.json` beside the selected base configuration from `config/asuna-channel.example.json`, then configure the channel, authorized identities, scenes, targets, and a unique token. Channel routes are disabled unless the local channel file has `enabled: true`.
- To enable managed integration, configure `integration.local.json` beside the base configuration using `config/integration.example.json`. Its owner binding and endpoint allowlist determine whether integration tools are available.
- Self-development availability is controlled by the local `self_development` configuration. Its candidate workspace is separate from ordinary action workspaces.

Do not put credentials, real platform account IDs, or machine-specific connection details in tracked manuals or examples.

## Model settings

Open **模型设置** in the workbench to edit each lane's endpoint, model ID, context and output limits, sampling, compatibility options, reasoning options, and token counter. Use **读取服务模型列表** to request IDs from a configured endpoint, or enter an ID directly.

Settings can be applied while the host is idle. The UI reports and rejects a change when active or queued work prevents a safe switch. Provider and protocol support is limited to the current Asuna bridge; DSH's other provider options are not automatically available through it.

## Channels

The host channel service accepts authenticated normalized events and exposes an outbox for a configured platform adapter. It listens on loopback only; its default port is `8766`. Route configuration binds the platform account, sender, scene, and target. A running adapter process alone is not proof of platform delivery; delivery state comes from the adapter's receipt. See [RUNTIME_API.md](RUNTIME_API.md) for event, outbox, media, and receipt details.

## Development and self-development

Normal development tasks are submitted through the Web UI and receive only the capabilities granted to their scene and task. Owner-granted integration work uses a separate managed workspace and configured endpoints. The self-development tools edit a persistent project candidate; publication freezes a snapshot and performs a non-consuming boot probe before applying it. These tools do not turn ordinary conversation into a development task.

## Debug CLI

CLI commands other than `ui` are for explicit diagnosis or maintenance and require `--debug`. They do not replace Web interaction or UI review. For example:

```powershell
.\.venv\Scripts\asuna.exe doctor --debug --config config/local.json
.\.venv\Scripts\asuna.exe inspect episode EPISODE_ID --debug --config config/local.json
```

The `chat()` and `terminal()` functions are debug terminal adapters. The Web UI reuses the `Chat` queue and action controller directly.

## Read-only UI

To inspect existing records without starting writable workers or calling a model:

```powershell
.\.venv\Scripts\python.exe -m asuna.cli ui --config config/local.json --read-only
```

Add `--port 8780` if the default UI port is occupied. Read-only mode cannot send messages or apply model settings.

## Troubleshooting

- **The UI does not open:** check the process window for its listening address and port. If the selected port is in use, restart with `--port` and open that port under `/asuna/`.
- **Configuration fails to load:** validate the JSON, local database allowlist, private or loopback provider endpoint addresses, and runtime paths under this repository's `.runtime` directory.
- **The page opens but messages cannot be sent:** check whether the UI is read-only, the host is stopping or reconfiguring, and both required lane endpoints are reachable.
- **An external message is not delivered:** check the configured route and adapter, then inspect the publication receipt in the UI. `RUNNING` adapter status does not mean the platform accepted a message.
- **A task stopped with an error:** expand its execution details in the UI. Ordinary action tool errors are available to the active DSH action loop; host or provider failures are recorded with their original diagnostic.
