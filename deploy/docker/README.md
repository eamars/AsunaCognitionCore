# Asuna in Docker

ADR-019 §3.3. Docker is one deployment layer on top of DSH. The cognition core and its plugins neither need it nor know about it, and a Windows or Linux install without Docker stays first-class (see [RUN_ASUNA.md](../../RUN_ASUNA.md)). Everything Docker-specific is in this folder.

## What the stack does

- **`asuna`** runs the toolchain image (`Dockerfile`: Node 24, uv, git, a compiler). The **checkout lives on a volume** (`/srv/asuna`), so her publications and the data folder `.runtime` persist across image rebuilds. On start, `entrypoint.sh`:
  1. clones the repository into the empty volume (once);
  2. installs Node dependencies again whenever `package-lock.json` changes, and syncs the Python environment from `uv.lock`;
  3. applies the LAN login patch (`lan-login.mjs`, below);
  4. builds the reviewed native rendering extension (`tools/dsh-inline`) once, from DSH's public release tag;
  5. installs the profile the first time;
  6. starts `start-asuna.sh`, the same launcher every install uses. Every later start installs the checkout when it changed.
- **`caddy`** serves HTTPS on the LAN with Caddy's internal certificate authority, and proxies to Asuna on loopback. It rewrites `Host` and `Origin` to that loopback address, so DSH's server-side fence accepts the request. This is how the owner's existing DSH container works. Both containers use host networking, so Asuna reaches MongoDB and NapCat as any process on that host would.
- **Sandbox:** DSH's defaults. The image installs no sandbox tool and the stack adds no privileges. DSH picks its runner (Landlock on a kernel that has it), and Asuna reports the enforcement level DSH gives it.
- **No login token on the LAN** (owner, 2026-10-07). `lan-login.mjs` patches DSH's client connection the way the owner's DSH container does: the browser reports loopback, so Settings works from the LAN address, and page and RPC authentication accept every request. The LAN and the host's firewall are the boundary. The patch fails loudly if DSH's code no longer matches it.

## Settings (Portainer stack environment)

| Variable | Default | Meaning |
| --- | --- | --- |
| `ASUNA_PROFILE` | `asuna-demo` | DSH profile. The default is the synthetic demo persona with its own database and no channels, so a new stack cannot reach the live persona or QQ |
| `ASUNA_CONFIG` | `config/demo.local.json` | Config path inside the checkout |
| `ASUNA_MONGO_URI` | — | Demo profile only. Its config is made from the tracked example, with every model route on a closed local port, so no model is called |
| `ASUNA_CONFIG_JSON` | — | For any other profile: the config written to `ASUNA_CONFIG` on first start, unless the file is already in the volume. Kept in the stack environment, never in tracked files |
| `ASUNA_PERSONA_PACKAGE`, `ASUNA_CHANNEL_PACKAGES` | demo persona, none | Package directories for the first install. Channels are separated by spaces |
| `ASUNA_SHARED_ACTION_MODEL` | `0` | `1` routes both brains to the action model |
| `ASUNA_PORT`, `ASUNA_HTTPS_PORT`, `ASUNA_HTTP_PORT` | 8780, 8443, 8781 | Asuna's loopback port, Caddy's HTTPS port, and the plain-HTTP port that serves Caddy's root certificate. Pick ports that are free on the host |
| `TZ` | `UTC` | The container's local time zone (an IANA name). Default quiet hours follow local time, as on any host, so set it to where she lives |
| `ASUNA_REPO`, `ASUNA_REF` | this repository, `main` | What the first start clones |

## Deploy

Deploy this folder as a Portainer stack (the compose file builds the image), or without compose:

```bash
docker build -t asuna:local "https://github.com/eamars/AsunaCognitionCore.git#main:deploy/docker"
```

Install Caddy's root certificate once per client from `http://<host>:8781/caddy-local-root.crt`, then open `https://<host>:8443/`.

Two Asuna instances must never serve the same persona, database or QQ route at the same time. A live profile in a container replaces the Windows one; it does not run beside it.
