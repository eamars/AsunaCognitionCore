# ADR-037: Following DSH alpha by alpha

Status: **Accepted 2026-10-10**, owner's decisions. The fork is set up; the routine below is handed to a dedicated
upgrade agent. **Owner, 2026-10-20:** upgrading DSH and keeping Asuna compatible with it is the owner's work; the
other agents build on the pinned DSH as it is (AGENTS.md).

## Context

Asuna runs DSH 0.2.0-rc.2 (commit `639ed015`). Newer builds are alphas only (0.2.1-alpha.1 on 2026-10-03,
alpha.2 on 2026-10-09, 935 commits ahead). The owner expects no stable DSH for a year or two: waiting for an rc
or a stable release only makes each merge larger. Asuna's coupling to DSH:

| Coupling | Where |
|---|---|
| Inline action-brain view: a patch to `ui-chat` and `ui-renderer` (Session-scoped chat content factory) | `tools/dsh-inline/rc2-inline.patch`, built by `tools/build_dsh_inline.mjs` |
| DSH's `ContextMeter` read from React internals (DSH does not export it) | `packages/cognition-core/src/client.js` |
| rc.2's `Session.append` cannot mark a record ignorable | `packages/cognition-core/src/persistence.js` |
| Exact pins of about 30 DSH packages | root `package.json`, `packages/cognition-core/package.json`, `packages/personas/*/package.json`, `package-lock.json` |
| The version named in tools and docs | `tools/build_dsh_inline.mjs`, `tools/probe_*.mjs`, `tools/release.py`, `deploy/docker/entrypoint.sh`, `INSTALL.md`, `RUN_ASUNA.md`, `NATIVE_PLUGIN.md`, the READMEs |
| DSH's public plugin API (llm, sessions, agents, subagents, tools, system prompt, settings, schedule, settings forms) | `packages/cognition-core/src` |

## Decision

- **D1. Follow every DSH alpha**, so each merge covers about a week of upstream work. *(Replaced by D8, 2026-11-04.)*
- **D2. Supply-chain delay: 7 days.** A DSH tag is taken once it is at least 7 days old (for DSH this replaces the
  general two-week rule for dependencies). *(Replaced by D9, 2026-11-04.)*
- **D3. Keep the inline action-brain view.** The owner prefers it to DSH's subagent view. Upstreaming Asuna's design
  is doubtful; a small generic extension point that would make the patch unnecessary may be offered upstream.
- **D4. Patches are commits on a fork**, not a diff file: https://github.com/eamars/deepseek-harness. Remotes in the
  owner's local DSH checkout: `origin` = the fork, `upstream` = deepseek-ai (push disabled).
  Branch `asuna/0.2.0-rc.2` = `639ed015` + two commits (`ui-renderer` factory cycle checks, `ui-chat`
  `conversation.chat.content`), identical to `rc2-inline.patch`. Each alpha gets its own branch
  `asuna/<version>`, the patch commits rebased onto that tag.
- **D5. A dedicated upgrade agent runs the routine**; Claude (Xiaoman's mentor) does not. The owner approves the
  switch of the live profile.
- **D6. Shrink the coupling over time**: export or replace the `ContextMeter` read; move `persistence.js` to DSH's
  session-record API once it is no longer experimental (alpha.2 adds it).
- **D7. A requirements ICD between DSH and Asuna** (owner, 2026-11-04). Asuna states what it needs from DSH as
  requirements, not code: the code interface may change, the requirements stay stable and are agreed by both
  sides. Big sis writes the ICD and its tests. The tests run against DSH alone (a DSH tag plus the fork's patches,
  no Asuna checkout, no live profile), so the DSH upgrade agent can test and verify a new DSH version on its own.
  Asuna then picks the new version up with its own code changes; an interface change is allowed while the ICD
  holds, and big sis takes it without a broad compatibility test.
- **D8. Migrations are manual and prompt** (owner, 2026-11-04). There is no automated reminder: when the owner hears
  of a new DSH version, he takes it up with the DSH upgrade agent. Delaying a migration slowly builds technical
  debt, so it is taken up as soon as time and bandwidth allow.
- **D9. No waiting period; the source tag is the guard** (owner, 2026-11-04). A version is taken once its `dsh-v*`
  tag exists on `upstream`, however new. A version published only on npm, without the tag, waits.

### Decision update (2026-11-04)

The owner's words: "Merge with RC5. Test the 0.2.2 compatibility. If we don't have clear boundary between DSH and
Asuna, then you need to message Big Sis Session (the master agent) to produce the clear ICD to make the future
migration easier. The intention is for Asuna project to expose a clear 'What the project needs, from requirement
perspective, not coding'. The code interface can change, but requirement should be consistent, and agreed between
up and downstream dependencies. The ICD should also allow the DSH migration agent to independently test and verify,
without relying on Asuna to cooperate. The Asuna project should then pickup the change with code changes (interface
change is allowed, as long as the ICD is clear, and Big Sis can pickup without excessive compatibility test. Ditch
the 7 day rule. And note down: delaying the compatibility migration will slowly building up technical debt." On
when: "When I remember to pick this up. This is manual work. I don't have automated workflow as the reminder." The
owner chose to keep the source-tag guard (D9) and that big sis writes the ICD's tests too (D7).

The DSH upgrade agent's survey on that day (upstream had `dsh-v0.2.1-rc.5` and `dsh-v0.2.2-alpha.3`):

- **0.2.1-rc.5** (8 fixes after rc.3): the three fork commits cherry-pick cleanly and the patched packages' tests
  pass (1,149). The rc.4 reasoning-body slot change does not reach `client.js`. Asuna moves from rc.2, so the items
  of the pending rc.3 note (entry customization, its three checks) still apply.
- **0.2.2-alpha.3** (1,910 commits): the `ui-chat` commit conflicts (upstream reworked the chat view's injected
  props); Schedule's Session-bound `create`/`list`/`update`/`delete` and timing selectors are replaced by one
  Host-wide `edit` API with typed timing, which `schedule.js`, `schedule.py` and `role_tools.py` use; the Schedule
  store moves to v2 on its first write and a v1 binary refuses it afterwards, so step 7's rollback needs a backup of
  that store. The coupling table above lists files and APIs, not requirements: that is the gap D7 closes.

## The routine (one version)

1. **Pick the tag**: the newest `dsh-v*` tag on `upstream` (D9). Read its release notes for breaking changes; check
   the ICD's requirements (D7) against them, and grep Asuna for each.
2. **Rebase the patch**: `git checkout -b asuna/<version> <tag>` then cherry-pick the previous `asuna/*` branch's
   patch commits; resolve conflicts commit by commit; run the patched packages' own tests (`ui-chat`,
   `ui-renderer`); push the branch to `origin`.
3. **Build the patched packages from the branch**: `tools/build_dsh_inline.mjs` (today it applies the diff file to a
   pinned commit; on the first run, change it to build from the fork branch and retire the diff file).
4. **Bump the pins** everywhere in the table above to the new version, and regenerate `package-lock.json`.
5. **Check**: `npm run test:native`, the Python suite (`.venv/Scripts/python -m pytest -q`),
   `tools/probe_plugin_install.mjs`, `tools/probe_fresh_profile.mjs`; then start the isolated demo profile (its own
   database, synthetic inference) and review the real Web page in a browser: the action brain shown inside the main
   chat, both context meters, the Asuna settings card (routes and efforts), the schedule session.
6. **Report** to the owner: the tag, the release notes that touch Asuna, conflicts and how they were resolved, the
   check results. Commit on main only after the owner says yes; the live profile switches at the next restart.
7. **Rollback**: revert that commit on main and restart (the launcher reinstalls the packages the checkout names).

## Consequences

- The first run (to 0.2.1-alpha.2) is the largest: pi-ai moves to 1.0, and four of the five patched files changed
  upstream; estimated one to two days. Later runs should take hours.
- Live behavior the routine must watch: DSH's in-conversation system-prompt updates (alpha.1) touch how Asuna's
  turn context reaches the model and its prompt caching; check against real traffic after the switch.

## First run (0.2.1-alpha.2, 2026-10-11)

The owner chose alpha.2 for the first run, one day after its release, overriding D2 once. What the next run needs:

- Work in a fresh worktree at the main checkout's `.runtime/wt-<name>` and remove it when done: the live Host runs
  from the main checkout's `node_modules`. The DSH fork clone stays as the inline build source.
  The worktree needs its own `uv sync`, a copy of `config/local.json` with `dsh_home` inside the worktree, and
  full control of its `.runtime` for the owner's account (DSH's Windows sandbox); without them pytest fails.
- In the DSH checkout, pnpm comes through `corepack`; DSH's pre-push hook runs its full typecheck and needs `pnpm`
  on PATH. Folders of packages that upstream removed keep their `node_modules` and break `tsdown`; delete them.
- alpha.2 moved Chat rows into the `conversation.chat.flow` slot. The patch now renders fragments through it,
  ungrouped and without Turn-process folding (a Turn's process group spans several of Asuna's work ranges).
- alpha.2 replaced `subagents.start()` with activations whose local children DSH composes itself; her tasks are now
  the worker's own catalogued children.
- Review: `tools/fixtures/inline_brains.mjs` wrapped as a stand-in `@asuna/cognition-core` package (index.js
  re-exports the fixture, client.js is the real client) in a profile with only the two patched UI packages, real
  model providers disabled and `agent-default-model` set to `inline-fixture/synthetic-one`; then `dual-flow`.
  The settings card is checked in the fresh-profile probe's home. The fixture has no context window, so the
  brain meters cannot be seen there.
- Before switching, rehearse one start against a copy of the live DSH home (another port, synthetic models).
  A fresh profile missed a startup race: alpha.2's Web ships its own Schedule service, which can still be starting
  when the worker looks for it, and the first live start mounted a second one and failed (fixed on main 92e263f1).
- npm 11 runs a dependency's install scripts only when `allowScripts` in the root `package.json` names it. It
  lists node-pty and koffi (native builds or prebuilds), the spawn-helper chmod of `dsh-subprocess-local` (it
  matters on Linux and in Docker) and protobufjs; a DSH alpha that adds an install script shows up as an
  `allow-scripts` warning in `npm ci`, to approve or deny there.

## Second run (0.2.1-rc.1, 2026-10-17)

The owner asked for rc.1 the same evening and, after the rehearsal incident below, to switch the live profile
without a second rehearsal and watch her closely that night. Live since 20:56 NZDT; her smoke tests passed (recall,
plans, a timed wake, pictures, notes, the action brain with web search, report paging) and a real group job got only
the skills that declare `group` (ADR-078). What the next run needs:

- rc.1's `dsh-session-persistence-jsonl` exports only `{Config, JsonlCompressionSchema, apply, name}`, no class to
  extend: `persistence.js` mounts it in an isolated `sessionPersistence` scope and delegates to it. Old compaction
  rows and session logs stay readable.
- The client conversation bundle imports `zod`; the stages test's module table resolves it from
  `dsh-client-ui-conversation`.
- DSH's plugin compatibility check refuses a package whose `@deepseek-ai/dsh*` peers name the old version, so every
  pin moves in one change; `tests/test_versions.py` lists the one that was missed (manifests, `source.json`, the
  current references). ADR-010's line that `engines.dsh` is only declared is stale: since alpha.3 DSH reads it for
  compatibility. Asuna declares none; the refusal it met came from the peers.
- `dsh plugin add` needs `pnpm`; the launcher and `setup_native_profile.py` give the DSH child a corepack shim, a
  hand-run command needs one on PATH. The probes need the persona and channel packages packed
  (`pack_plugins.py --persona … --channel …`); a fresh DSH home inside the checkout is refused, so it goes outside.
  The inline review profile must not list the real core among its bundles.
- **Rehearsal incident.** The rehearsal ran `asuna-launch.mjs` from the worktree, whose `.venv` was a junction to the
  main checkout's: the editable install imports `asuna` from main, so `setup_native_profile.py` (via
  `asuna.config.ROOT`) acted on the LIVE profile: pnpm pruned 11 packages, `cordis.patch.yml` and `launch.json` were
  rewritten to point at the worktree. They were restored from a copy taken before; the Host kept running. The
  first run's note already said the worktree needs its own `uv sync`; also check that
  `python -c "import asuna.config as c; print(c.ROOT)"` prints the worktree, and copy the live `cordis.patch.yml`
  and `launch.json` aside before any rehearsal.
- Never `npm ci` in the main checkout while the Host runs: a loaded `koffi.node` is locked, npm stops halfway and
  leaves `node_modules` half deleted. Stop the Host first (the switch is a restart anyway), then `npm ci`.
- Packed tarballs the old profile named are pruned only at the next pack; after the switch, prune them once
  (`pack_plugins.prune`) and remove the worktree, the fork clone and the probe homes.

## Third run (0.2.1-rc.2, 2026-10-18)

The owner asked for rc.2, one day old, and to switch directly without a rehearsal (a small change). The DSH
upgrade session rebased the two patches onto `dsh-v0.2.1-rc.2` cleanly (fork `asuna/0.2.1-rc.2`, 5713aab7); rc.1→rc.2
adds DeepSeek's Search and Fetch APIs behind a settings switch, off by default. Asuna changed only its pins.
- Clone the fork with `core.longpaths=true` on Windows (a test fixture path is too long otherwise).
- `uv` lives in the main checkout's `.venv`; a worktree's own `uv sync` does not install it, so `test_lock_files`
  skips there unless that `Scripts` folder is on PATH.
- `pyproject.toml` and the worker's bundled `pyproject.toml` named `0.1.0`; both now follow Asuna's version, and
  `tests/test_versions.py` checks the first.
