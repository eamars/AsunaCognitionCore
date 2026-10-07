# ADR-019: Linux deployment, with the plugin inheriting DSH's platform layer

| Item | Content |
| --- | --- |
| Status | **Implemented through M3 (2026-10-07); M4 docs and M5 owner review open.** 一之瀬アスナ runs as a Portainer stack on the owner's Docker host, and the owner tested that she answers. The owner decided every question in §6. |
| Date | 2026-10-07 |
| Author | The implementer (Claude), at the owner's request |
| Relation | Builds on ADR-010 (distributable plugin, data folder) and ADR-015 (DSH's sandbox replaces WSL). Amends neither. |
| Code baseline | Commit `0896113d`. |

## 0. Problem

Asuna has only ever run on the owner's Windows machine. The owner wants it to run on Linux, and later in Docker. Nothing in Asuna should depend on which operating system the host runs.

## 1. The owner's rules (2026-10-07)

1. **Asuna inherits whatever DSH uses.** The plugin does not assume the host operating system. Where DSH has a platform layer (sandbox, process spawning, plugin installation, credentials, storage), Asuna calls it. Asuna adds no mechanism of its own for one OS.
2. **Docker is on the way.** The design should work as a container deployment, not only on a Linux machine someone sets up by hand.
3. **Starts apply changes automatically** (done 2026-10-07; see §2.2). This has to keep working on Linux and in a container.
4. **Windows without Docker stays a first-class install** (owner, 2026-10-07). Docker is one deployment layer on top of DSH. The cognition core and its plugins do not rely on Docker and know nothing about it. Everything Docker-specific lives in a separate deployment folder: the Dockerfile, the compose file, the Caddy configuration, and the LAN login patch of §6.1 Q6.

## 2. What exists today

### 2.1 Already inherited from DSH, or already platform-neutral

| Area | How it works | Status |
| --- | --- | --- |
| Command sandbox | The worker asks the host (`ctx.sandbox.confine`, `sandbox_backend.py`). `dsh-sandbox-local` picks the runner: a restricted token and ACLs on Windows; bubblewrap, falling back to Landlock, on Linux; Seatbelt on macOS. Asuna reports the enforcement level DSH gives it. `sandbox.py` recognises a launch failure from both the Windows runner (`windows-acl-run:`) and bubblewrap (`bwrap:`). | Inherited |
| Plugin installation | DSH's own `plugin add`, which runs pnpm. The launcher and the installer add a corepack shim when pnpm is missing (`pnpm.cmd` on Windows, `pnpm` elsewhere). | Inherited |
| Worker Python | `python-env.js` builds a venv in the data folder from the package's lock, with uv or Python 3.12+. It knows both venv layouts and both sets of Python launcher names. | Neutral |
| Her self-development publish | `floor.js` runs `npm pack`, through `cmd.exe` on Windows only. | Neutral |
| Cross-process locks | `queue.py` uses `msvcrt` or `fcntl`. | Neutral |
| npm dependencies | The lockfile carries Linux and macOS builds of every platform-specific package (the system addon, the LibreOffice kit, ripgrep, sharp, koffi). `dsh-sandbox-windows-acl` is plain JavaScript and stays unused on Linux. | Inherited |
| Python dependencies | `uv.lock` has wheels for every platform. | Neutral |
| Configuration | `config/*.json` holds no Windows paths. Code builds paths with `pathlib` and `path.join`. | Neutral |
| Prompts and core skills | No OS is named in core prompts or core skills. Her persona package's self-check skill mentions `cmd.exe`; that skill is hers, so ADR-019 changes nothing there. | Neutral |
| External services | MongoDB, the model and embedding servers, image generation, NapCat (the QQ client) and the old-home peer are all reached over the network. NapCat has Linux builds. | Neutral |

### 2.2 Done on 2026-10-07

- **Each start installs the checkout when it changed** (`tools/asuna-launch.mjs`). The launcher packs the profile's packages, compares the digests with what is installed, and reruns the installer only when they differ. `--no-sync` skips this. The installer records the previous running package, so a start that never comes up still returns to it.
- **`start-asuna.sh`** is the Linux and macOS entry, the same as `start-asuna.cmd`. The logic is in the Node launcher.
- **The installers no longer name Windows executables.** `pack_plugins.py` calls `npm`, which is `npm.cmd` only on Windows. `setup_native_profile.py` runs DSH as `node …/dsh/lib/bin.js`, not `dsh.cmd`.
- **Her publications cannot change the start path.** The packer, the installer and `start-asuna.sh` joined the floor's protected paths, because every start now runs them.

### 2.3 Still tied to Windows

| Item | Where | What changes |
| --- | --- | --- |
| Tests confined commands only with DSH's Windows ACL runner, so on Linux the sandboxed tests were skipped | `tests/conftest.py` | **Done (M1):** `tests/dsh_sandbox.mjs` mounts DSH's own provider (`dsh-sandbox-local`) and returns the wrapping for a write root, once per root. It works with any runner DSH picks. On Windows it is the same ACL runner as before |
| The launcher always binds `127.0.0.1` | `tools/asuna-launch.mjs` | Nothing to change. In a host-network container, a reverse proxy on the host reaches `127.0.0.1` (§3.3). |
| `check_dsh_release.py` called `npm.cmd` | operator tool | **Done (M1):** `npm` off Windows |
| `fingerprint_models.py` reads model weights through WSL | operator tool, for the owner's independent model server | Leave as it is. It is not part of Asuna's runtime, and the model server is the owner's. |
| `build_dsh_inline.mjs` goes through PowerShell on Windows | builds the pinned rendering extension from a dedicated DSH checkout | It already has a non-Windows branch. Check it on Linux once, or take the built artifacts from the GitHub Release (ADR-010). |
| The note that `.runtime` needs full control | RUN_ASUNA, ADR-015 | This is Windows-only (the ACL runner). On Linux the runner needs user namespaces (§3.3). |

### 2.4 The target host (inventory 2026-10-07, read-only, taken by a Claude session on that host)

The owner's Docker host. Its address and names stay out of this file (AGENTS.md: personal data).

| Fact | Value | Consequence |
| --- | --- | --- |
| OS and kernel | Ubuntu 22.04 LTS, Linux 5.15, x86-64; 36 CPUs, 62 GiB memory | Plenty of headroom |
| Disk | The root disk is 76% full (about 23 GB free); Docker's data is on it | An Asuna image plus her Python environment and data fit, but the free space should be watched |
| Docker | Engine 29, running as root (not rootless), cgroup v2, AppArmor and seccomp on | Standard. The owner's user is in the docker group |
| Compose | Neither the compose plugin nor `docker-compose` is installed. Stacks are deployed through Portainer | The compose file of §3.3 is deployed as a Portainer stack. Nothing has to be installed on the host |
| Sandbox | Landlock is in the active LSMs. Unprivileged user namespaces are allowed (Ubuntu 22.04 has no AppArmor restriction on them). `bwrap` is not installed | DSH's Landlock path is available. Linux 5.15 provides Landlock ABI 1, which confines file writes but has no rules for truncating or for the network. DSH reports the enforcement level it gets, and Asuna passes that on |
| Host toolchain | python3 3.10 and git. No node, npm or uv | The host runs nothing of Asuna's itself. The image brings Node, uv and Python 3.12 |
| Already running | Her MongoDB (with vector search), NapCat, a SearXNG search instance, another DSH instance behind Caddy, and Portainer | Asuna runs next to her database and NapCat. Nothing of those is changed. Ports already taken there are avoided; Asuna's 8780 is free |
| Earlier incident (that host's notes) | The vector-search stack crash-looped on 2026-10-03, from leaked `asuna_v2_test_*` databases and a low open-file limit. Both were fixed | Tests must keep dropping their own databases (AGENTS.md). A container deployment does not run the test suite against that MongoDB |

## 3. Design

### 3.1 The rule in code

Asuna calls DSH's interfaces for anything a platform does differently: sandboxing, subprocesses, plugin installation, credentials and storage. Branches on `process.platform` or `os.name` exist only where Node or Python themselves differ, which means executable names (`npm` or `npm.cmd`) and venv layout (`Scripts` or `bin`). Asuna owns no ACL code, no namespace code and no per-OS shell. A contract test lists the files allowed to branch on the platform, and why. A new branch has to be added to that list, which shows up in review.

### 3.1a Where Docker lives

Docker files go in `deploy/docker/` and nowhere else. Nothing under `src/`, `packages/` or `tools/` mentions Docker, checks whether it runs in a container, or reads a container-only setting. A container gets its differences only through what any deployment can set: the launcher's arguments, the profile's settings and the environment DSH already reads.

A contract test (`tests/test_no_docker_in_core.py`) keeps it that way: it fails if Docker is named anywhere in the core or plugin sources (`src/`, `packages/`). The operator diagnostics in `tools/` may talk to a Docker host; they are not part of what runs. A Windows install never needs Docker, Portainer or Caddy. The Windows checks (§5) are run on Windows without Docker at every milestone.

### 3.2 A Linux machine

Prerequisites:
- Node (the version DSH's pinned release needs);
- `uv`, or Python 3.12+;
- a reachable MongoDB;
- a kernel that lets DSH's sandbox run: unprivileged user namespaces for bubblewrap, or Landlock (Linux 5.13+) as DSH's fallback. Ubuntu 23.10 and later restrict unprivileged user namespaces through AppArmor; DSH then uses Landlock, or the host allows `bwrap`.

Steps, the same as on Windows:
1. `npm ci`
2. `uv sync`
3. Get the rendering extension: build it or take the Release artifact.
4. Pack and install once.
5. `./start-asuna.sh`

Every later start installs changes by itself (§2.2). A systemd unit that runs `start-asuna.sh` as an unprivileged user is the service form. It goes into RUN_ASUNA as an example, with no personal paths.

### 3.3 Docker

The container uses the same launcher path, so there is one way to run Asuna:

- **The image** holds the toolchain and the checkout's dependencies: Node, uv, `npm ci` and `uv sync`. It does not hold an installed DSH profile. The profile directory mixes installed plugins with the owner's settings and credentials, and those must survive an image change.
- **Volumes:**
  - the DSH home (profile settings, credentials, sessions);
  - the data folder (`.runtime`: her worker Python, workspaces, her published artifacts, evidence);
  - the checkout (§6 Q2).
- **The entrypoint** is `start-asuna.sh`.
  - On the first start, and after any change to the checkout, the launcher's sync packs and installs into the volume's profile.
  - Unchanged starts cost a pack, which takes a few seconds.
  - Her published packages are applied by the launcher, as they are today.
- **The sandbox inside a container:**
  - bubblewrap needs user namespaces, which Docker's default seccomp profile blocks.
  - Landlock works without extra privileges on a host kernel that has it.
  - DSH chooses between them and Asuna reports the enforcement it gets. The compose file documents whichever setting the owner picks (§6 Q3).
- **Web access follows the owner's existing DSH container** (its own repository, outside this one), as the owner asked (§6.1):
  - The Asuna container uses host networking, and the launcher keeps binding `127.0.0.1:8780`.
  - A Caddy container, also on host networking, terminates HTTPS with Caddy's internal certificate authority. It serves the root certificate once over plain HTTP, and certificates are issued per connection, so no LAN address is written into the stack.
  - Caddy reverse-proxies to `localhost:8780` and rewrites `Host` and `Origin` to that loopback authority, so DSH's server-side fence accepts the request.
  - Ports 80 and 443 are already the existing DSH stack's. Asuna's Caddy takes a free HTTPS port (proposed: 8443; checked on the host with `ss` before deploying).
  - The DSH token gate is removed on the LAN, as in that container (§6.1 Q6).
- **The rest also follows that container:**
  - a non-root user;
  - `init`, a health check against the web port, and `restart: unless-stopped`;
  - a Portainer stack with its settings in the stack environment, not in tracked files.
- **Other services** run as their own containers or hosts: MongoDB, NapCat, and the owner's model server (independent, untouched). A compose file can include MongoDB for a fresh install. The owner's existing MongoDB stays where it is.

### 3.4 Her self-development in a container

A core publication writes the changed files back into the checkout (`floor.js publish`), and the next start installs them. That works in a container only if the checkout persists. See §6 Q2.

## 4. What does not change

- The data model, MongoDB, the channels, and the tools she has.
- ADR-015: commands run only under DSH's sandbox, and only from the owner's scenes.
- ADR-010's package format and Release artifacts.
- `start-asuna.cmd` stays the Windows entry (AGENTS.md).

## 5. Plan

| Step | Content | Evidence |
| --- | --- | --- |
| M0 | The owner answers §6. Update this ADR | — |
| M1 | **Done 2026-10-07.** Portability fixes from §2.3: tests confine through DSH's sandbox provider, `check_dsh_release.py`, the contract test that lists the files allowed to branch on the OS (`tests/test_platform_branches.py`), and the no-Docker-in-core test | Windows: 376 Python and 50 native tests pass; the sandbox test that was skipped now runs |
| M2 | **Done 2026-10-07.** On the owner's Docker host (§6.1), in the image of `deploy/docker/` (written 2026-10-07): the full Python and native test suites against a throwaway MongoDB container (never the live one, §2.4), the sandbox probe's enforcement level, and one start of the demo profile with every model route on a closed port (AGENTS.md: synthetic inference) | Linux: 375 passed and 1 skipped (pytest), 50/50 native. DSH picked Landlock (partial). Found and fixed on the way: `lockf` → `flock`, time-zone-dependent tests, missing data folder in two native tests, two lockfiles out of step (npm workspaces, `tzdata` in `uv.lock`, now guarded by `test_lock_files`), and the shallow-clone hash length in the inline extension check |
| M3 | **Done 2026-10-07.** Docker image and compose file in `deploy/docker/` by §3.3 (deployed as a Portainer stack on the owner's host), with volumes and the entrypoint. The Windows install is checked again without Docker | Stack `asuna-ichinose`: her own MongoDB, her container (healthy) and Caddy. 8790 on loopback only; HTTPS 8443 answers 200 on the LAN with no token. Persona 一之瀬アスナ (`packages/ichinose-asuna`, a new persona package) on the owner's model server, local chat only; the owner tested that she answers |
| M4 | RUN_ASUNA and INSTALL: a Linux section, the systemd example, the Docker section | Docs reviewed |
| M5 | The owner's review on the real page, on Linux | — |

## 6. Decisions

### 6.1 Decided by the owner (2026-10-07)

1. **Verify on the owner's Docker host**, in a new container separate from everything already there. A Claude session on that host does the host-side steps, each approved there. It cannot send messages back to the PC session; its transcript is read instead.
2. **Her core self-development: the checkout lives on a volume.** Her publications persist, and every start installs them, as on bare metal.
3. **Sandbox: DSH's defaults, nothing added.** No bubblewrap installed by Asuna, no extra container privileges, no relaxed seccomp or AppArmor. DSH picks its runner (on that host, Landlock), and Asuna reports the enforcement level DSH gives it.
4. **Web access: as the owner's existing DSH container does it** (§3.3).
5. **NapCat** already runs on that host; Asuna only needs its address.

6. **No login token on the LAN, as in the owner's existing DSH container.** The Asuna image applies the same build-time patch to DSH's client connection:
   - the browser reports loopback;
   - the page and RPC authentication checks accept every request;
   - the build fails loudly if DSH's code no longer matches the patch.

   The LAN, and the host's firewall, are the access boundary. The owner chose this knowing her page holds her private home chat and their settings. It is the second DSH patch Asuna carries, after the reviewed rendering extension. Both are deployment patches, not changes to the plugin, so §1 rule 1 holds for the plugin itself.

### 6.3 The original questions (for the record)

1. **Where to verify Linux.** The owner's Docker host (§2.4, recommended: it is the target, and it already runs her database and NapCat), in a container that is separate from everything already there. The alternative is Docker Desktop on this PC, which runs on WSL2 (ADR-015 ruled WSL out for the runtime, but only for verifying here). A Claude session on the host does the host-side steps; every one of its actions is approved in that session.
2. **Her core self-development in a container.**
   - *Bind-mounted checkout (recommended):* the checkout lives on a volume, so her publications persist and the launcher installs them, exactly as on bare metal.
   - *Artifacts only:* her publications live as packages in the data folder; an image rebuild drops them unless they are upstreamed.
   - *Off:* core self-development is disabled in containers.
3. **The sandbox inside a container.**
   - *Landlock only (recommended):* no extra container privileges; the host kernel has Landlock (ABI 1, §2.4); enforcement as DSH reports it.
   - *Allow bubblewrap:* user namespaces through a seccomp or AppArmor setting.
4. **Web exposure.** The port is published to the host's loopback only, and reached from elsewhere through the owner's own tunnel or proxy (recommended). The alternative is publishing on the LAN, which would rely on the token alone.
5. **NapCat placement** on Linux: on the same host, or in its own container. This is a deployment choice; Asuna only needs its address.
