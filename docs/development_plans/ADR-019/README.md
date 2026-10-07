# ADR-019: Linux deployment, with the plugin inheriting DSH's platform layer

| Item | Content |
| --- | --- |
| Status | **Draft for the owner's review (2026-10-07).** §2 is a survey of the code as it is. The launcher items marked *done* were built the same day. §6 lists the decisions the owner still has to make. |
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
| Tests confine commands only with DSH's Windows ACL runner, so on Linux the sandboxed tests are skipped | `tests/conftest.py` (`ACL_RUNNER`, `HOST_SANDBOX`) | Ask DSH's sandbox provider (`dsh-sandbox-local`) for the wrapped argv through a small Node helper, the same way the host does. This works with any runner DSH picks. |
| The launcher always binds `127.0.0.1` | `tools/asuna-launch.mjs` | Add `--host`, for a container that binds inside and publishes only to the host's loopback. The default stays `127.0.0.1`. |
| `check_dsh_release.py` calls `npm.cmd` | operator tool | Use `npm` off Windows. |
| `fingerprint_models.py` reads model weights through WSL | operator tool, for the owner's independent model server | Leave as it is. It is not part of Asuna's runtime, and the model server is the owner's. |
| `build_dsh_inline.mjs` goes through PowerShell on Windows | builds the pinned rendering extension from a dedicated DSH checkout | It already has a non-Windows branch. Check it on Linux once, or take the built artifacts from the GitHub Release (ADR-010). |
| The note that `.runtime` needs full control | RUN_ASUNA, ADR-015 | This is Windows-only (the ACL runner). On Linux the runner needs user namespaces (§3.3). |

## 3. Design

### 3.1 The rule in code

Asuna calls DSH's interfaces for anything a platform does differently: sandboxing, subprocesses, plugin installation, credentials and storage. Branches on `process.platform` or `os.name` exist only where Node or Python themselves differ, which means executable names (`npm` or `npm.cmd`) and venv layout (`Scripts` or `bin`). Asuna owns no ACL code, no namespace code and no per-OS shell. A contract test lists the files allowed to branch on the platform, and why. A new branch has to be added to that list, which shows up in review.

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
- **The web token** is printed in the container's log, as it is in a console. The port is published to `127.0.0.1` on the host only. The launcher binds inside the container through `--host` (§2.3).
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
| M1 | Portability fixes from §2.3: tests confine through DSH's sandbox provider, launcher `--host`, `check_dsh_release.py`, the contract test that lists platform branches | Full test suite on Windows, unchanged |
| M2 | A Linux machine (§6 Q1): install by §3.2, the sandbox probe's enforcement level, the full Python and native test suites, one start with synthetic inference (AGENTS.md: no real model unless authorized) | Test reports, the probe result, the Web page loading |
| M3 | Docker image and compose file by §3.3, with volumes and the entrypoint | First start installs; a second start installs nothing; a change to the checkout is installed on the next start; sandbox enforcement reported |
| M4 | RUN_ASUNA and INSTALL: a Linux section, the systemd example, the Docker section | Docs reviewed |
| M5 | The owner's review on the real page, on Linux | — |

## 6. Decisions for the owner

1. **Where to verify Linux.** A Linux machine or VM the owner provides (recommended: closest to a real deployment), or Docker Desktop on this PC. Docker Desktop runs on WSL2, which ADR-015 ruled out for the runtime, but only for verifying here.
2. **Her core self-development in a container.**
   - *Bind-mounted checkout (recommended):* the checkout lives on a volume, so her publications persist and the launcher installs them, exactly as on bare metal.
   - *Artifacts only:* her publications live as packages in the data folder; an image rebuild drops them unless they are upstreamed.
   - *Off:* core self-development is disabled in containers.
3. **The sandbox inside a container.**
   - *Landlock only (recommended):* no extra container privileges; enforcement as DSH reports it.
   - *Allow bubblewrap:* user namespaces through a seccomp or AppArmor setting.
4. **Web exposure.** The port is published to the host's loopback only, and reached from elsewhere through the owner's own tunnel or proxy (recommended). The alternative is publishing on the LAN, which would rely on the token alone.
5. **NapCat placement** on Linux: on the same host, or in its own container. This is a deployment choice; Asuna only needs its address.
