# ADR-037: Following DSH alpha by alpha

Status: **Accepted 2026-10-10**, owner's decisions. The fork is set up; the routine below is handed to a dedicated
upgrade agent.

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

- **D1. Follow every DSH alpha**, so each merge covers about a week of upstream work.
- **D2. Supply-chain delay: 7 days.** A DSH tag is taken once it is at least 7 days old (for DSH this replaces the
  general two-week rule for dependencies).
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

## The routine (one alpha)

1. **Pick the tag**: the newest `dsh-v*` tag on `upstream` that is at least 7 days old. Read its release notes for
   breaking changes; grep Asuna for each.
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
