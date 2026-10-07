# Asuna in Docker

A Portainer (or `docker compose`) stack that runs Asuna on a Linux Docker host. Docker is a deployment layer on top
of DSH: the cognition core and its plugins neither need it nor know about it, and installs without Docker work as
described in [RUN_ASUNA.md](../../RUN_ASUNA.md). Everything Docker-specific is in this folder.

## What the stack does

- **`asuna`** runs the toolchain image (`Dockerfile`: Node 24, uv, git, a compiler). The **checkout lives on a
  volume** (`/srv/asuna`), so her publications and the data folder `.runtime` persist across image rebuilds. On
  start, `entrypoint.sh`:
  1. clones the repository into the empty volume (once);
  2. installs Node dependencies whenever `package-lock.json` changes, and syncs the Python environment from `uv.lock`;
  3. applies the LAN login patch (`lan-login.mjs`, below);
  4. builds the native rendering extension (`tools/dsh-inline`) from DSH's public release tag when it is missing
     or out of date;
  5. installs the profile when it has never been installed, or when the stack names other packages than the ones
     recorded in its `launch.json`;
  6. starts `start-asuna.sh`, the same launcher every install uses. It installs any other change to the checkout.
- **Network:** the three containers share the stack's own network. **Only Caddy publishes ports**: 8443 (the
  page, HTTPS) and 8781 (Caddy's root certificate). Asuna shares Caddy's network namespace: DSH listens only on
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
| `ASUNA_SHARED_ACTION_MODEL` | `0` | `1` routes both brains to the action model |
| `ASUNA_HTTPS_PORT`, `ASUNA_HTTP_PORT` | 8443, 8781 | The host ports Caddy publishes: the page (HTTPS) and its root certificate (HTTP). Pick ports that are free on the host |
| `TZ` | `UTC` | The container's local time zone (an IANA name). Default quiet hours follow local time, so set it to where she lives |
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

Two Asuna instances must never serve the same persona, database or channel route at the same time.

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
