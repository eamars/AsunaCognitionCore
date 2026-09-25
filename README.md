# Asuna Cognition Core

Asuna is a local-first, persistent dual-lane cognition runtime built on the pinned DSH runtime.

## Overview

- **Character brain:** maintains persona and self-understanding, considers relationships, decides whether to delegate, and shapes the public response.
- **Action brain:** investigates and carries out delegated work with scoped tools, then returns observations to the character brain. Ordinary tool errors stay in the active DSH action loop for diagnosis and recovery.
- **Host:** binds scenes and identities, stores conversation and memory records, enforces capabilities, coordinates queues and schedules, and tracks publication receipts and task continuity.

The two lanes have independent provider and model settings. Their names describe responsibilities; either lane can use the same or a different configured model.

## Current capabilities

- A local Web workbench for conversation, model settings, memory and execution details.
- Persistent, scene-scoped conversation history, memory retrieval, relationship state, and source-bound background dialogue summaries.
- Authorized history search and structured discussion digests through the action path.
- DSH-native action capabilities for skills, schedules, web search, and page fetching, subject to the configured grants and providers.
- Optional authenticated channel routes for direct messages and groups. The host accepts normalized events and exposes public output with platform receipt handling; a platform adapter must be configured separately.
- Owner-scoped integration and self-development tools with separate workspaces and publication controls.
- On-demand image reading by the action brain when its configured route declares image input and the source passes the configured checks.

Available actions depend on the current configuration and authorization for the scene. A configured capability does not mean its provider or external service is online.

## Quick start

Create and review `config/local.json` from `config/local.example.json`, then start the Web workbench:

```powershell
.\start-asuna.cmd
```

The default UI is at `http://127.0.0.1:8765/asuna/`. `start-asuna-ui.cmd` is an alias. See [RUN_ASUNA.md](RUN_ASUNA.md) for prerequisites, configuration, stop and restart steps, and troubleshooting.

## Configuration

`config/local.example.json` is the configuration template. `config/local.json`, model overrides, channel settings, integration settings, credentials, and deployment-specific values belong in ignored local files. Replace template connection addresses, identities, paths, and database choices with values for the local deployment; do not commit secrets or private deployment details.

The optional channel and integration examples are `config/asuna-channel.example.json` and `config/integration.example.json`. See [RUNTIME_API.md](RUNTIME_API.md) for their host contracts.

## Documentation

- [RUN_ASUNA.md](RUN_ASUNA.md) — current runbook.
- [RUNTIME_API.md](RUNTIME_API.md) — current runtime, channel, tool, and recovery contract.
- [AGENTS.md](AGENTS.md) — persistent development and interaction rules.
- [dsh-plugin/ui/README.md](dsh-plugin/ui/README.md) — current Web UI behavior.
- [docs/development_plans/](docs/development_plans/README.md) — ADRs and development plans; these record design history and future direction, not current runtime status.
- [migrations/](migrations/002_artifact_blobs.md) — durable database contract notes.

## Project status

Experimental, local-first, and actively evolving.
