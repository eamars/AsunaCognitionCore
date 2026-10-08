# Developing Asuna

For people and coding agents working on this repository. The rules in [AGENTS.md](../AGENTS.md) are binding; this
page is the map. Running and installing are in [RUN_ASUNA.md](../RUN_ASUNA.md), how the packages compose inside DSH
in [NATIVE_PLUGIN.md](../NATIVE_PLUGIN.md), and the contracts in [RUNTIME_API.md](../RUNTIME_API.md).

## Repository map

| Path | What it holds |
|---|---|
| `src/asuna/` | The Python business worker (queues, cognition, memory, channels, integration supervision). `resources/prompts` and `resources/schemas` are the neutral core prompts and JSON schemas. |
| `packages/cognition-core/` | The Host plugin: `src/` (JS), `test/` (node tests), `skills/` (core skills), `locale/`. `runtime-manifest.json` is written by the packer; `python/` is the packer's ignored copy of `src/asuna`. |
| `packages/channels/<name>/` | A channel package: `src/index.js` (`registerChannel`), `python/<module>/` (the kind module), `integration/` (a managed adapter, if any), `skills/`, `test/`. |
| `packages/personas/<name>/` | A persona package: `src/index.js` (`registerPersona`), `persona-model.json`, `seeds/`, `skills/`, `cordis.patch.yml` (its role preset), `locale/`, `icon.*`. |
| `tests/` | pytest suites (`test_*.py`); case modules shared with the offline checks (`*_cases.py`); fixtures (`fixtures/world.json`, the synthetic persona `fixtures/personas/demo`); `dsh_sandbox.mjs`, which wraps test commands in DSH's sandbox. |
| `tools/` | Install, launch, pack and build scripts, repository checks and diagnostics: see [tools/README.md](../tools/README.md). |
| `config/` | Tracked templates (`*.example.*`). Real configuration (`local.json`, `*.local.json`) is ignored. |
| `deploy/docker/` | The Docker stack; the only place that knows about Docker. |
| `docs/development_plans/` | ADRs: decisions, designs and plans, with their dates. Not a reference for current behavior. |
| root | `start-asuna.cmd` / `start-asuna.sh` (entry), `package.json` (npm workspaces), `pyproject.toml`, `package-lock.json`, `uv.lock`, the reference docs. |

Ignored and local: `.runtime/`, `.venv/`, `node_modules/`, `reports/`, `config/local.json` and `config/*.local.json`.

## Where state lives

- **MongoDB**: all business state — persona, memories, people, messages, tasks, audit. One database per profile; the
  running Host's claim on it is the `host_leases` document (`host_lease.py`), and the data folder's `host-id` names
  the deployment.
- **`.runtime/adr008/`** (profile `asuna-native`; another profile uses `.runtime/adr008/profiles/<name>/`):
  - `packages/`: packed `.tgz` files (packing removes those that no manifest, installed profile or `activation.json`
    names), `manifest.json`, and `native-inline-manifest.json` when the inline extension is built;
  - `launch.json`: the config, the installed package list (`setup`) and digests (`installed`);
  - `activation.json`: the selected artifact per development project, and the last one that ran;
  - `home/`: the DSH home (`DSH_HOME`), with the profile under `home/profiles/<profile>/` (its `cordis.patch.yml`
    holds the saved settings, its `node_modules` the installed plugins).
- **The profile's data folder**, `$DSH_HOME/asuna/<profile>/`: development candidates, the worker's Python
  environment, bridge positions, integration runs.
- **The worker's data root** (`ASUNA_DATA_ROOT`, default `.runtime/`): task and channel workspaces (`work/`,
  `channels/`), the evidence of the last five worker starts (`reports/native-host-*`) and the worker's own files.
  Everything under `.runtime/` is local and disposable except what a profile needs; never commit it.

## How a change reaches the running Host

Edit the source, then restart with the start script. The launcher packs the recorded packages, sees the digest
change and installs again ([RUN_ASUNA.md](../RUN_ASUNA.md#start-review-stop)). There is no hot reload: Python in
`src/asuna/` ships inside the core package, so it changes the core's digest too. Restart only when the character is
idle, and never run two instances on the same channel routes. Check the result on the Web page, in an isolated demo
profile for new UI or behavior ([Demo environment](../RUN_ASUNA.md#demo-environment)).

## Python modules by area

- **Entry and hosting:** `native_worker` (the worker the Host plugin starts), `host`, `application`, `cli`, `config`,
  `native_settings`, `model_settings`, `lanes`, `queue`, `state` (the Mongo store), `audit`, `evidence`, `testing`.
- **A turn:** `ingress`, `router`, `coordinator`, `context`, `context_budget`, `render`, `role_tools`, `tool_args`,
  `answers`, `publish`, `lines`, `chat`.
- **Groups and people:** `attend` (the relevance gate), `proactive`, `rhythm`, `people`, `peer_context`,
  `familiarity`, `group_admin`, `watches`, `places`, `notes`, `scene_links`, `visibility`.
- **Memory:** `memory`, `memory_indexer`, `retrieval`, `history_query`, `dialogue_summary`, `discussion_digest`,
  `summary_trigger`, `summary_attribution`, `documents`, `self_state`, `affect`, `blobs`, `privacy`.
- **Persona:** `persona_model`, `persona_data`, `persona_jobs`, `policy`, `skills`.
- **Channels:** `channels` (the channel API), `channel_kinds`, `channel_admission`, `stickers`, `vision`,
  `outbound_media`.
- **Work and tools:** `tasks`, `grants`, `schedule`, `schedule_rules`, `sandbox`, `sandbox_backend`, `development`,
  `credentials`, `image_generation`, `integration`, `integration_fetch`, `integration_image`, `integration_import`.
- **The Web page's data:** `native_api`, `native_cognition`, `native_ui`.

Each module's docstring says what it owns. The Host plugin's modules are in `packages/cognition-core/src/`
(`index.js` composes them; `floor.js` is the publication floor; `client.js` the Web page contributions).

## Tests

```powershell
npm.cmd run test:native                       # node tests of the core and every channel package
.\.venv\Scripts\python.exe -m pytest -q       # Python suites
.\.venv\Scripts\python.exe tools\check_staged_secrets.py --personal --all
```

On Linux and macOS use `npm run test:native` and `.venv/bin/python`.

- The tests keep only invariants whose breakage would be visible or harmful: privacy and visibility boundaries,
  authorization and epoch fencing, exactly-once ingest and publication, crash recovery, audit integrity, sandbox
  isolation and the visible native behavior.
- Python suites read `config/local.json` for the MongoDB address. The `store` fixture builds the fixture world once
  per session and resets a reused `asuna_v2_test_*` database for each test; every test database is dropped at
  session end, failures included. Mongo tests skip when the service is unavailable.
- Native node tests and the native worker/product tests use synthetic inference and create no database.
- **Repository guards** fail the suite when the tree drifts: `test_line_endings` (LF everywhere),
  `test_lock_files` (both locks match `package.json` / `pyproject.toml`), `test_no_docker_in_core` (no Docker in
  `src/` or `packages/`), `test_platform_branches` (OS branches only in the files it lists),
  `persona.test.js` (every persona and channel package registers).
- `tools/p*_offline_check.py`, `tools/integration_import_offline_check.py` and `tools/outbound_image_offline_check.py`
  run the `tests/*_cases.py` modules without Mongo or pytest; they are the character's own checks inside her sandbox.
- The personal-data scan prints only `file:line:category`, never the matched value.

## Writing a persona or channel package

**A persona package:**

1. Copy `tests/fixtures/personas/demo` to `packages/personas/<name>`.
2. In `package.json`, set `name` (`@asuna/<name>`), `version` and `description`; keep `peerDependencies`
   (`@asuna/cognition-core` `0.2.x`) and the `dsh.bundle.patch` entry.
3. In `src/index.js`, set `name` and the `registerPersona` fields: `id`, `character_id`, `display_name`, `version`,
   the seeds (one with kind `persona`), any jobs, and `preset`.
4. In `cordis.patch.yml`, rename the plugin and preset ids and the preset's `names` (and `descriptions`), one entry per shipped language (`en`, `zh`). The row is `@asuna/cognition-core/preset`: DSH shows a declared preset name as written, so it registers the words of the language the program's names follow (English when that language has none).
5. Write `seeds/` and `persona-model.json` (schema: `src/asuna/resources/schemas/persona-model.schema.json`).
   Seeds may be any length the character model's window allows: the prompt limit grows with them
   ([RUNTIME_API.md](../RUNTIME_API.md), "Her persona"). Leave `render.budget_tokens` out unless the persona needs
   a larger fixed budget.
6. `npm install` (records the workspace in `package-lock.json`), then `npm run test:native`.
7. Install it in a demo profile ([RUN_ASUNA.md](../RUN_ASUNA.md#demo-environment)) with its own database.

**A channel package:** start from `packages/channels/dsh-peer` (adapter in the Host process) or
`packages/channels/napcat-qq` (managed adapter in the sandbox).

1. `src/index.js` calls `registerChannel({kind, title, project, resource_root, python, module,
   integration_directory, skill_directories})`.
2. `python/<module>/__init__.py` is the kind module: the names listed in `src/asuna/channel_kinds.py`'s docstring
   (id formats, mentions, media hosts, derived adapter settings; optional faces, stickers, home or text-only, and
   `SERVICE_ARGV`, the managed adapter's resident command, which an enabled integration starts by itself).
3. The adapter speaks the channel API in [RUNTIME_API.md](../RUNTIME_API.md#channel-api) with the channel's token.
4. The README says what a deployment configures (see the QQ package's "Setting up QQ").
5. `npm install`, `npm run test:native`, then add it to a profile
   ([Add or remove an optional package](../RUN_ASUNA.md#add-or-remove-an-optional-package)).

Core code, core prompts and example configs never name a persona or a platform.

## Writing tool errors

Every error a tool call can return is read by a model that has to act on it, so it says the cause and the fix:

- Form: `CODE: 原因（带实际值）；怎么办`, in Chinese. The code comes first and stays stable; tests, logs and the
  character brain's `WORDS` table (`role_tools.py`) key on it. A code has an underscore.
- The cause carries the values the raise site knows: what was given, the limit, the allowed set.
- The fix is concrete: the correction, the program list that holds the valid values (named as her context names
  it), or, when no retry can help, `重试也一样` and what to do instead.
- A condition that is not the caller's fault (a service missing, a task fenced off) says so.
- A library error on a path driven by the caller's input is caught at that site and raised as a coded error with
  the library's short message.
- The worker sends a coded message as it is. Any other exception reaching a tool result is a program fault and
  arrives as `TOOL_FAULT: 程序内部出错（Class: message）…`, which tells the caller its arguments are not the cause.
- The character brain sees `WORDS[code] （CODE: detail）` for a code in the table, otherwise the message itself; a
  `Refused` raised in `role_tools.py` is shown as written.

## Writing docs and recording decisions

- Reference docs (`README*`, `INSTALL.md`, `RUN_ASUNA.md`, `NATIVE_PLUGIN.md`, `RUNTIME_API.md`, package and tool
  READMEs, this page) describe the current state only: what it is, how to use it, what it needs. No history, dates,
  ADR provenance or reasons. Change them in the same commit as the behavior.
- Decisions, designs and plans go in an ADR: `docs/development_plans/ADR-0NN-<slug>/README.md`, with a row in
  [the index](development_plans/README.md). ADRs keep their history and dates.
- Code comments may say why; keep them to what a reader of that code needs.
