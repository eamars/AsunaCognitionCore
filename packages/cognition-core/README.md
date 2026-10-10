# Asuna Cognition Core

The home of an Asuna character: a native DSH **0.2.1-alpha.2** plugin with its Python business worker. It names no
persona and no platform; a persona package and any channel packages register with it.

Install its `.tgz` with `dsh plugin --profile <web-profile> add <artifact>` (see [INSTALL.md](../../INSTALL.md)). The
artifact includes the Python worker and the neutral prompts and schemas; it does not depend on `src/asuna` in the
development checkout. No credentials, `.runtime`, private chats or memory, model weights, virtual environment,
bytecode or Node dependencies are distributed.

## Configuration

- **Python:** the worker needs `uv` or Python **3.12+**. With the `python` setting empty, Core builds its environment
  on first start in the data folder from the included `python/requirements.lock` (uv when on PATH, otherwise
  `python -m venv` and pip) and reuses it until the lock changes. Set `python` to use an interpreter of your own.
- **`asuna-cognition-core`:** `persona`, `deployment`, and independent `routes.character` / `routes.action` native
  provider/model references. Core uses DSH Web's Schedule service for her plans;
  `mountSchedule: false` (default `true`) turns plans off.
- **`asuna-publication-floor`:** the authorized writable source projects, Python path and recovery route.
- **Data folder:** everything Asuna writes for a profile goes to the floor's `dataRoot`, by default
  `$DSH_HOME/asuna/<profile>/`. The installed package is never written.

Providers, credentials, Mongo state, workspaces and model services are local deployment inputs. After migration the
native profile owns `deployment`, channel admission and lane routes; business and provider credentials both live in
DSH's credential store, referenced from the settings by name.

## Contracts

- **Persona:** a persona plugin injects `asuna` and calls `registerPersona({id, character_id, display_name, version,
  resource_root, model, seeds, jobs, skill_directories, preset})` (contract v2; one seed has kind `persona`). Its
  thin role preset loads `@asuna/cognition-core/role`. Core without a selected persona is inert.
- **Channel:** a channel plugin injects `asuna` and calls `registerChannel({kind, title, project, resource_root,
  python, module, integration_directory, skill_directories})`. The worker imports its kind module; its adapter is
  the managed integration; its skills join the persona's.

What the package adds to DSH, how execution and persistence work, and the publication lifecycle are described in
[NATIVE_PLUGIN.md](../../NATIVE_PLUGIN.md). The channel API and tools are in [RUNTIME_API.md](../../RUNTIME_API.md).
