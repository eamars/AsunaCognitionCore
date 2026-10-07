# ADR-020: Several characters at once

Status: **Proposed** 2026-10-07. Decisions for the owner are in §7; nothing is built yet.

## 1. Context

The owner asked (2026-10-07) that Asuna support several characters running at the same time, each with its own
pointers to a database, a NapCat server and its token; that the design say which services may be shared and which
must be separate; and how the Web UI should present several profiles. It came up after 一之瀬アスナ and 杏山カズサ were
deployed beside 小满 (ADR-019), and Kazusa had to borrow 小满's QQ account.

What exists today, as of `main` 2026-10-07:

- **One persona per profile.** A DSH profile has one Asuna core; several persona packages may be installed, but the
  core runs only the one its `persona` setting names (`packages/cognition-core/src/index.js`).
- **A profile already owns most of its state:** its DSH home and saved settings
  (`.runtime/adr008/profiles/<name>/home`), its credential store (inside that home), its data folder
  (`$DSH_HOME/asuna/<profile>`: workspaces, development candidates, integration runs), its `launch.json` and
  `activation.json`, and its config file, which names its database and its channel and integration files
  (`channel_config`, `integration_config`).
- **Database:** every profile names its database in its config (`database`, `allowed_databases`). Asuna's
  collections have fixed names inside that database. A Host takes a lock per *server address + database name*, but
  the lock is a file in the machine's temp folder (`config.database_lock`, `LOCKS`): it stops a second Host on the
  same machine, not one on another machine pointing at the same server.
- **Sessions are bound to their data folder.** A conversation binding records its working folder, so a database
  cannot be moved to another profile (found deploying Kazusa: `NATIVE_BINDING_IDENTITY_CHANGED`).
- **Platform accounts are not guarded.** NapCat accepts several WebSocket clients; two Hosts on one QQ account both
  receive every message and both answer. Only the manuals forbid it.
- **Models:** requests go through DSH's own model routes. Nothing in Asuna serialises one profile's requests behind
  another's (`queue.EndpointLock` is no longer used).
- **Web UI:** one DSH Web server per profile, each on its own port. DSH serves one profile per process. On Windows the
  launcher's port defaults to 8780 for every profile; Docker stacks each publish their own ports.
- **Self-development:** on one machine, all profiles share one checkout. A core publication by one character changes
  the source every profile there installs on its next start; persona and channel projects are per package.

## 2. Goal

Any number of characters can run at the same time, on one machine or several, each a profile with its own state and
its own platform accounts, sharing whatever services are safe to share. A mistake that would make two Hosts act as
one (one database, one platform account) is refused, not merely documented.

Not in scope: two personas in one profile; merging profiles; moving a character's database to another profile.

## 3. What a profile owns, and what may be shared

| Resource | Rule | Why |
|---|---|---|
| DSH profile, home, saved settings, credential store | **Own** | Already so. |
| Data folder (workspaces, candidates, integration runs) | **Own** | Already so. Session bindings point into it. |
| Database | **Own**, on a server that may be shared | The database name is the namespace; Asuna's collections, indexes, vector search index, erasure and backups are per database. See §4.1. |
| MongoDB server (Atlas Local, Atlas, Community + mongot) | **Shared** allowed | Each profile its own database on it. |
| Model servers (character and action routes) | **Shared** allowed | Each profile names its routes. Load adds up: several characters thinking at once queue at the server. |
| Embedding service | **Shared** allowed | Vectors stay in each profile's database. One database must keep one embedding model. |
| Image service and other LAN endpoints | **Shared** allowed | Each profile's owner grants them separately (integration endpoints). |
| Platform account (a QQ number, a peer session) | **Own, exclusively** | Two Hosts on one account both answer everything. Guarded in §4.2. |
| NapCat server | **Shared** allowed, one account per profile | A NapCat process logs in one account; a NapCat deployment may run several, each with its own WebSocket port and token. The profile's integration names its endpoint and token. |
| Channel API port and token | **Own** | Per Host: `channel_port` (default 8766) must differ for profiles on one machine outside Docker; the token is the profile's. |
| Web port | **Own** | Per Host. See §4.3. |
| Checkout and installed DSH | **Shared** on one machine | Saves disk and build time. Core self-development needs one owner: §4.4. |
| Docker stack | **Own** per character | Already so: its own Caddy, data volumes and ports; it may point at a shared MongoDB server instead of its own. |

## 4. Design

### 4.1 Database per profile, not collections per profile

Recommended: each profile gets its own **database** on a shared server (`asuna_v2_xiaoman`, `asuna_v2_kazusa`), as
today. The alternative, one database with a collection prefix per profile, would touch every query in the worker,
the vector search index definition, erasure, backups and the test teardown, and buys nothing a database name does not
already give.

### 4.2 Leases instead of local locks

A Host holds two leases while it runs, renewed every 30 s and expiring after 90 s, both stored in the profile's
**own database** (`host_leases` collection):

- **The database lease** replaces the machine-local file lock: a second Host on the same database, from any
  machine, refuses to start (`DATABASE_IN_USE_BY <host, profile, since>`).
- **A channel account lease** per configured platform account (`qq:<account>`). It needs a place every Host using
  that account can see. Options (decision D2):
  - **A.** A small shared registry database on the shared MongoDB server (`asuna_registry.leases`), named in each
    profile's config. Works across machines when the profiles share a server; profiles on separate servers are not
    guarded.
  - **B.** The adapter detects a second consumer: messages from its own account that it did not send. Catches every
    case, but misfires when a person also uses the account by hand (小满's account is marked `shared_account`).
  - **C.** Documentation only.

  Recommended: **A**, with **B** as a warning (status line, no refusal) where `shared_account` is false.

### 4.3 Ports and addresses

- The launcher records a profile's Web port in its `launch.json` on install (`--port` at setup, default: the first
  free port from 8780), so `start-asuna --profile kazusa` always opens the same address, and refuses to start on a
  port another profile recorded.
- The same for `channel_port`, chosen at install when the profile configures a channel.
- Docker stacks keep publishing their own ports (ADR-019); the stack README lists them.

### 4.4 Core self-development on a shared checkout

Persona and channel projects are per package, so characters do not touch each other's. The core project is shared.
Recommended: a checkout records which profile may publish core changes (`self_development.core` in that profile's
settings, at most one per checkout, refused for the rest); the others keep persona and channel development.
Docker stacks have their own checkout and are unaffected.

### 4.5 Web UI

DSH serves one profile per Web server, and each profile's page already shows its persona: the role preset is named
`<persona> · 角色脑`, the persona package's icon is on the Plugins page, and conversations are titled by the persona.
Options (decision D3):

- **A. One address per profile** (today), plus a list: `asuna profiles` (and the launcher's `--list`) prints every
  installed profile, its persona, port, database and whether it is running. No UI of our own.
- **B.** A as above, plus each profile's browser tab named and iconed after its persona (DSH's page title and
  favicon), so several open tabs are told apart. A small UI change of ours, needs approval.
- **C.** A landing page listing all profiles on the machine (persona, icon, running or not, link), served by the
  launcher or by Caddy. Our own UI; needs approval and a home outside DSH.
- **D.** One DSH Web server showing every profile with a switcher. DSH 0.2 does not support it, and one core runs
  one persona; it would mean changing DSH. Rejected.

Recommended: **A** now, **B** next; **C** only if one bookmark for all characters matters.

## 5. Configuration per profile

Everything a profile points at stays in its own config and settings; nothing is read from another profile:

```text
config/<profile>.local.json         database, mongo_uri, model routes, embedding, channel_config, integration_config
config/asuna-channel.<profile>.local.json   channels.<id>: account_id, token, routes; canonical_persons
config/integration.<profile>.local.json     endpoints (NapCat host:port), adapter_config.napcat (url, token)
```

After the first install these move into the profile's saved settings and credential store (as today). The only new
setting is the shared registry for channel leases (§4.2 A), e.g. `"registry": {"database": "asuna_registry"}` on the
same `mongo_uri`.

## 6. Milestones

- **M1** Leases: database lease in the profile's database; channel account lease in the registry; status line shows
  the holder when refused. Tests: two Hosts on one database, two on one account, a lease expiring after a crash.
- **M2** Ports: recorded per profile; `--list`; channel port per profile outside Docker.
- **M3** Core self-development owner per checkout.
- **M4** Manuals: "Running several characters" in RUN_ASUNA (owns / may share table, one account per profile), the
  Docker README, the QQ README; `docs/DEVELOPMENT.md`.
- **M5** (if approved) browser tab title and icon per persona.
- **M6** Owner review: 小满 on Windows and Kazusa in Docker on separate QQ accounts at the same time.

## 7. Decisions for the owner

- **D1** Database per profile on a shared server (recommended), or collection prefixes in one database.
- **D2** Channel account guard: shared registry lease (recommended, with the adapter's warning), adapter detection
  only, or documentation only.
- **D3** Web UI: one address per profile with a list (recommended now), plus tab title and icon per persona (next),
  or a landing page.
- **D4** Core self-development on a shared checkout: one owning profile per checkout (recommended), or off for all
  but the default profile, or unrestricted.
