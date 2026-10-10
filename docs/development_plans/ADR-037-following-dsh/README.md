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
