# Asuna in Docker

A Portainer (or `docker compose`) stack that runs Asuna on a Linux Docker host. Docker is a deployment layer on top
of DSH: the cognition core and its plugins neither need it nor know about it, and installs without Docker work as
described in [RUN_ASUNA.md](../../RUN_ASUNA.md). Everything Docker-specific is in this folder.

## What the stack does

- **`asuna`** runs the toolchain image (`Dockerfile`: Node 24, uv, git, a compiler, and DejaVu and Noto CJK fonts for text in rendered SVGs). The **checkout lives on a
  volume** (`/srv/asuna`), so her publications and the data folder `.runtime` persist across image rebuilds. On
  start, `entrypoint.sh`:
  1. clones the repository into the empty volume (once);
  2. installs Node dependencies whenever `package-lock.json` changes, and syncs the Python environment from `uv.lock`;
  3. applies the LAN login patch (`lan-login.mjs`, below);
  4. builds the DSH patches (`tools/dsh-inline`: the rendering extension and the compaction engine) from the DSH fork branch named in `tools/dsh-inline/source.json` when it is missing
     or out of date;
  5. installs the profile when it has never been installed, or when the stack names other packages than the ones
     recorded in its `launch.json`;
  6. starts `start-asuna.sh`, the same launcher every install uses. It installs any other change to the checkout.
- **Network:** the three containers share the stack's own network. **Caddy publishes the LAN ports**: 8443 (the
  page, HTTPS) and 8781 (Caddy's root certificate); `mongo` is published only on the host's loopback (below). Asuna shares Caddy's network namespace: DSH listens only on
  loopback (port 8780), where Caddy reaches it. Asuna reaches MongoDB as `mongo` and NapCat, the model servers and
  the embedding service at their LAN addresses. Recreating the caddy container needs a restart of `asuna` too.
- **`mongo`** is the stack's own MongoDB, `mongo:27017` inside the stack and `127.0.0.1:27099` on the host:
  `mongodb/mongodb-atlas-local`, which runs mongod and
  its search process (mongot) together, so memory recall's vector search works. Embeddings come from the embedding
  service in each profile's config. `asuna` starts once the image's own health check reports both up. To use an
  existing MongoDB instead, point the config at one with vector search and remove this service.
- **`caddy`** serves HTTPS with Caddy's internal certificate authority and proxies to `localhost:8780`. It rewrites
  `Host` and `Origin` to a loopback address, so DSH's server-side fence accepts the request.
- **Sandbox:** DSH's defaults. The image installs no sandbox tool and the stack adds no privileges. DSH picks its
  runner (Landlock on a kernel that has it), and Asuna reports the enforcement level DSH gives it.
- **No login token on the LAN.** `lan-login.mjs` patches DSH's client connection: the browser reports loopback, so
  Settings works from the LAN address, and page and RPC authentication accept every request. The LAN and the host's
  firewall are the boundary. The patch fails loudly if DSH's code no longer matches it.

## Settings (stack environment)

| Variable | Default | Meaning |
| --- | --- | --- |
| `ASUNA_PROFILE` | `asuna-demo` | DSH profile. The default is the synthetic demo persona with its own database and no channels |
| `ASUNA_CONFIG` | `config/demo.local.json` | Config path inside the checkout |
| `ASUNA_MONGO_URI` | `mongodb://mongo:27017/?directConnection=true` | Demo profile only. Its config is made from the tracked example, with every model route on a closed local port, so no model is called |
| `ASUNA_CONFIG_JSON` | — | For any other profile: the config written to `ASUNA_CONFIG` when that file is missing |
| `ASUNA_PERSONA_PACKAGE` | `tests/fixtures/personas/demo` | The persona package directory |
| `ASUNA_CHANNEL_PACKAGES` | none | Channel package directories, separated by spaces (e.g. `packages/channels/napcat-qq`) |
| `ASUNA_CHANNEL_CONFIG_JSON`, `ASUNA_INTEGRATION_CONFIG_JSON` | — | The channel and integration settings (the shapes of `config/asuna-channel.example.json` and `config/integration.example.json`). Written beside the config when missing, and read by the installer into a profile that has none. An enabled adapter for a channel starts by itself on the first start |
| `ASUNA_CHANNEL_ADMISSION` | `explicit` | `automatic` admits new DMs, groups and members on their first valid message. A first choice only: the settings card's saved choice wins |
| `ASUNA_HTTPS_PORT`, `ASUNA_HTTP_PORT` | 8443, 8781 | The host ports Caddy publishes: the page (HTTPS) and its root certificate (HTTP). Pick ports that are free on the host |
| `TZ` | `UTC` | The container's local time zone (an IANA name): her clock when the config's `timezone` is not set. Default quiet hours follow local time, so set it to where she lives |
| `ASUNA_NAME` | `asuna` | Container name prefix (`<name>`, `<name>-https`, `<name>-mongo`), so several stacks can run side by side |
| `ASUNA_MONGO_PORT` | 27099 | The host loopback port the stack MongoDB is published on, for tools on the host |
| `ASUNA_REPO`, `ASUNA_REF` | this repository, `main` | What the first start clones |

Keep secrets (tokens, the config) in the stack environment, never in tracked files.

## Deploy

Deploy this folder as a Portainer stack (the compose file builds the image), or build without compose:

```bash
docker build -t asuna:local "https://github.com/eamars/AsunaCognitionCore.git#main:deploy/docker"
```

Install Caddy's root certificate once per client from `http://<host>:8781/caddy-local-root.crt`, then open
`https://<host>:8443/`.

### Models and the owner on a new volume

The stack environment carries no model settings. A profile on a new volume starts with `MODEL_NOT_CONFIGURED` until
its models are set, once ([step by step below](#5-models)):

1. On DSH's **Models** page, add the model provider with its API key (kept in DSH's credential store).
2. On the Asuna settings card, choose each brain's route, save, then **Apply saved settings**. A save is checked
   against the routes in the draft; a brain without a route uses DSH's default model.

The owner link can come from the stack: `canonical_persons` and `context_links` in `ASUNA_CHANNEL_CONFIG_JSON`
(the shape of `config/asuna-channel.example.json`) are installed with the channel settings. On a profile that already
has settings, set them on the settings card instead.

Two Asuna instances must never serve the same database or platform account at the same time (a second Host on a database is refused; a shared QQ account is not). Several characters: [Running several characters](../../RUN_ASUNA.md#running-several-characters).

## How to deploy a character with QQ on Portainer

The whole path for one character: a persona, its own database, a QQ account served by NapCat, and model routes. The
examples use placeholders: `<docker-host>` is the host that runs the stack, `<napcat-host>` the host that runs NapCat,
`<profile>` the DSH profile name (`ASUNA_PROFILE`), `<persona-id>` the persona package's id.

### 0. What you need

- A Docker host with Portainer, and a Portainer access token (My account > Access tokens) if you script the steps.
- Three free host ports: the page (HTTPS), Caddy's root certificate (HTTP) and the stack MongoDB (host loopback).
  A stopped container keeps its port bindings, so check all containers, not only running ones: in Portainer
  *Containers* (tick *Show stopped*), or `GET /api/endpoints/<id>/docker/containers/json?all=1` and each container's
  `HostConfig.PortBindings`.
- An embedding service the Docker host can reach (OpenAI-compatible `/v1`): its base URL and model.
- A key for each model provider you route to (step 5).
- A NapCat logged in to the bot's QQ account, with its OneBot v11 **forward WebSocket server** enabled and an access
  token, reachable from the Docker host at `<napcat-host>:<ws-port>`. One QQ account serves one running character.
- The owner's QQ number.

### 1. Write the stack environment

The settings table above lists every variable. For a persona with QQ, set these (values are single-line JSON where
the name ends in `_JSON`):

| Variable | Value |
| --- | --- |
| `ASUNA_NAME` | a name for this stack, e.g. `asuna-<persona-id>`; prefixes the container names |
| `ASUNA_PROFILE` | `<profile>` |
| `ASUNA_CONFIG` | `config/<profile>-stack.local.json` |
| `ASUNA_CONFIG_JSON` | the config below |
| `ASUNA_PERSONA_PACKAGE` | `packages/personas/<persona-id>` |
| `ASUNA_CHANNEL_PACKAGES` | `packages/channels/napcat-qq` |
| `ASUNA_CHANNEL_CONFIG_JSON` | the channel settings below |
| `ASUNA_INTEGRATION_CONFIG_JSON` | the adapter settings below |
| `ASUNA_CHANNEL_ADMISSION` | `explicit` (only the routes you list can reach her) |
| `TZ` | the IANA zone she lives in |
| `ASUNA_HTTPS_PORT`, `ASUNA_HTTP_PORT`, `ASUNA_MONGO_PORT` | the three free ports from step 0 |

`ASUNA_CONFIG_JSON` (shape: `config/local.example.json`). The database name is the character's own; no other
character may use it:

```json
{
  "database": "asuna_v2_<profile>",
  "allowed_databases": ["asuna_v2_<profile>"],
  "mongo_uri": "mongodb://mongo:27017/?directConnection=true",
  "dsh_home": "/srv/asuna/.runtime/<profile>-dsh",
  "embedding": {
    "base_url": "http://<embedding-host>:<port>/v1",
    "model": "<embedding-model>",
    "query_prefix": "search_query: ",
    "document_prefix": "search_document: ",
    "api_key": "<key, or empty>"
  },
  "workflow_timeout_seconds": 1800,
  "provider_idle_timeout_seconds": 1800,
  "timezone": "<IANA zone>",
  "self_development": {"enabled": false},
  "chat": {"scene_id": "local-dm", "person_id": "local-user", "persona": "<persona-id>",
           "workspace": "/srv/asuna/.runtime/work/local-user", "read_only_paths": []},
  "persona_runtime": {"<persona-id>": {"heartbeat_target": "local-dm"}}
}
```

`ASUNA_CHANNEL_CONFIG_JSON` (shape: `config/asuna-channel.example.json`). `token` is a random string of at least 24
characters that you make up; the adapter and Core's channel API share it:

```json
{
  "enabled": true,
  "port": 8766,
  "context_links": {"local-dm": ["qq:<bot-account>:dm:<owner-account>"]},
  "canonical_persons": {"qq:<owner-account>": "local-user"},
  "channels": {"qq": {
    "token": "<random 24+ characters>",
    "account_id": "<bot-account>",
    "routes": {"owner-dm": {
      "sender_id": "<owner-account>",
      "person_id": "qq:<owner-account>",
      "scene_id": "qq:<bot-account>:dm:<owner-account>",
      "target": {"type": "dm", "id": "<owner-account>"}
    }}
  }}
}
```

`ASUNA_INTEGRATION_CONFIG_JSON` (shape: `config/integration.example.json`). The adapter runs in DSH's sandbox and
reaches only the addresses listed in `endpoints`: each `port` is a local alias, each `target_port` the device's port.
`napcat` points at NapCat's WebSocket server, `host` at Core's channel API inside the container:

```json
{
  "enabled": true,
  "scene_id": "local-dm",
  "person_id": "local-user",
  "endpoints": [
    {"name": "napcat", "host": "<napcat-host IP>", "port": 15001, "target_port": <ws-port>},
    {"name": "host", "host": "127.0.0.1", "port": 18766, "target_port": 8766}
  ],
  "adapter_config": {
    "napcat": {"transport": "websocket_forward", "url": "ws://127.0.0.1:15001", "token": "<NapCat access token>"},
    "host": {"base_url": "http://127.0.0.1:18766", "channel_id": "qq"}
  }
}
```

`endpoints[].host` is an IP address. Both tokens move into DSH's credential store when the profile installs; the
settings card then shows them as *Configured* and the settings keep only references. More channel options are in the
[QQ package README](../../packages/channels/napcat-qq/README.md#setting-up-qq).

### 2. Create the stack

In Portainer: *Stacks* > *Add stack* > *Repository*. Repository URL `https://github.com/eamars/AsunaCognitionCore.git`,
reference `refs/heads/main`, compose path `deploy/docker/compose.yaml`; add the variables from step 1 as environment
variables; *Deploy the stack*. The stack name is free; it prefixes the volume names.

Scripted, with the same values:

```bash
curl -sk -X POST "https://<docker-host>:9443/api/stacks/create/standalone/repository?endpointId=<id>" \
  -H "X-API-Key: <portainer token>" -H "Content-Type: application/json" \
  -d '{"Name": "<stack name>", "RepositoryURL": "https://github.com/eamars/AsunaCognitionCore.git",
       "RepositoryReferenceName": "refs/heads/main", "ComposeFile": "deploy/docker/compose.yaml",
       "Env": [{"name": "ASUNA_NAME", "value": "<name>"}, {"name": "ASUNA_PROFILE", "value": "<profile>"}, ...]}'
```

The call returns when the image is built and the containers are created; the build takes minutes.

### 3. First start

Three containers start: `<name>-mongo`, `<name>` and `<name>-https`. `<name>` reports *starting* while it clones the
repository, installs dependencies, builds the DSH patches and installs the profile (the health check allows 30
minutes). It is ready when its log ends with `dsh web: http://127.0.0.1:8780/` and the health check reports
*healthy*.

Until step 5 is done the business worker logs `Asuna worker could not start (attempt n): MODEL_NOT_CONFIGURED:
character` and retries at growing intervals (up to 300 s). That is the expected state of a new volume.

### 4. Open the page

Install Caddy's root certificate once per client from `http://<docker-host>:<http port>/caddy-local-root.crt`, then open
`https://<docker-host>:<https port>/`. A client that does not trust the certificate cannot open the page. The
Asuna settings card is under *Plugins* > *Asuna Cognition Core*.

### 5. Models

**5.1 Provider and key.** *More* > *Settings* > *Models* > *Add model provider*: choose the provider and enter its
API key. A provider with a key shows a green dot. Keys are kept in DSH's credential store.

**5.2 Routes.** On the settings card choose each brain's route: *model service*, *model* and *reasoning effort* for
the character brain and for the action brain. The lists offer the models of the providers on the Models page. Which
model may run which brain is in [MODELS.md](../../docs/MODELS.md). Press *Save settings*, then *Apply saved
settings*. Applying restarts the worker, so do it while she is idle. The card then reads *Saved settings match what
is running*. A save is refused with `MODEL_NOT_CONFIGURED: <brain>` when that brain's route names no provider or a
model the provider does not list.

### 6. Check the QQ link

1. On the card, the status line says `adapter running`.
2. The adapter's health file shows the NapCat identity it connected to:

   ```bash
   docker exec <name> cat /srv/asuna/.runtime/adr008/profiles/<profile>/integration/owner/service-data/health.json
   ```

   `identity.ok` and `identity.match` are `true` and `identity.user_id` is the bot account; `frames_api` and
   `frames_event` grow while NapCat talks.
3. Send her a DM from the owner's account. Her first reply is the first model call.

A message from an account without a route gets no answer under `explicit` admission.

### Services outside the stack

A service she reaches (an image service, for one) must listen on an address the container can reach; another
machine's loopback is not one. Name it in `endpoints` of the integration settings (apply on the card; the endpoint
named `image` enables image generation) with that machine's LAN IP.

Voice messages are transcribed only when the SenseVoice model files are present in the profile's `models` folder;
without them the log says `ASUNA_VOICE_MODEL_UNAVAILABLE` and voice messages are not transcribed.

### When it does not work

| Symptom | Cause | What to do |
| --- | --- | --- |
| Card: *Saving failed; your draft is kept*, with `MODEL_NOT_CONFIGURED: <brain>` | that brain's route has no provider, or a model the provider does not list | choose the route from the lists on the card (step 5.2); add the provider first if the list is empty (step 5.1) |
| Log: `MODEL_NOT_CONFIGURED: character`, repeating | no route saved and applied yet | step 5.2 |
| The page shows a certificate error | the client does not trust Caddy's CA | step 4 |
| `identity.match` is `false`, or no frames | wrong `account_id`, token or `target_port`, or the Docker host cannot reach `<napcat-host>:<ws-port>` | check each against NapCat; from the host: `nc -z <napcat-host> <ws-port>` |
| Stack creation fails on a port | a port is already bound, by a stopped container too | pick another (step 0) |
| `DATABASE_IN_USE` | another Host holds the database | stop that Host, or use another database name |
| She answers nobody | no route for that account under `explicit` admission | add a route in the channel settings, or set admission on the card |

## Update the checkout

The volume's checkout changes only when someone pulls (`docker exec <name> git -C /srv/asuna pull`) or she publishes.
Restart the container afterwards; the next start installs what changed. If a package directory moved, update
`ASUNA_PERSONA_PACKAGE` / `ASUNA_CHANNEL_PACKAGES` in the same redeploy.

## Add or remove a package

1. Change `ASUNA_CHANNEL_PACKAGES` (or `ASUNA_PERSONA_PACKAGE`) in the stack environment.
2. For a new channel on a profile that has no channel settings yet, give `ASUNA_CHANNEL_CONFIG_JSON` (and
   `ASUNA_INTEGRATION_CONFIG_JSON` for a managed adapter such as QQ). On a profile that already has settings, add the
   channel on the settings card after the redeploy instead. What a channel needs is in its package README
   ([QQ](../../packages/channels/napcat-qq/README.md#setting-up-qq)).
3. Redeploy the stack. The entrypoint sees the package list differ from the recorded one and installs again.

To remove a channel, delete its settings on the card and apply first, then remove the package from
`ASUNA_CHANNEL_PACKAGES` and redeploy; uninstall it on DSH's Plugins page.
