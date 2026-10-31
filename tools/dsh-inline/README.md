# DSH patches built inline

Optional. Three packages from the Asuna branch of the DSH fork, installed in the profile in place of the released
ones:

- **The native Chat composition extension** (`dsh-client-ui-chat`, `dsh-client-ui-renderer`): shows the action
  brain's original records inside the main conversation instead of DSH's subagent view (below).
- **The compaction engine** (`dsh-compaction-basic`): its `compactNow` takes an optional keep-from point
  (`options.keepFrom`), so her conversation is compacted at the end of a turn with that whole turn kept as it is
  (`packages/cognition-core/src/compaction.js`, `compactTurnEnd`). Without it nothing is compacted at a turn's end;
  DSH's in-turn compaction works either way. With no options it behaves as the released package. And the recent
  history a compaction inside a turn keeps (`retainRatio`, `retainTokens`) is counted in the model's own tokens, the
  unit its threshold is checked in, not in DSH's estimate of them. Its DSH dependencies are peers, so the profile's
  copy uses DSH's own.

Stock DSH lets one owner declare the `conversation.chat.flow` slot and rejects reuse of the same factory under a
different session. Two commits on the Asuna branch of the DSH fork add a Session-scoped native Chat factory,
`conversation.chat.content`, and permit different authorized source bindings while keeping cycle protection. Native
messages, tools, attachments, disclosures, history and context ownership stay native. A fragment renders the
source Session's grouped Chat entries through DSH's own Chat flow, so an action turn folds, groups tool calls and
discloses thinking exactly as the character brain's turn does. Fragment anchors do not enter main-session
navigation. The extension changes rendering only.

## Build

[`source.json`](source.json) names the fork, the branch (`asuna/<DSH version>`: the DSH release tag plus the two
commits; `asuna/<DSH version>-<what it adds>` for a branch built on it), the exact commit, and the DSH version it
extends. Build in a **dedicated checkout** of that commit, with
Node (pnpm comes through corepack):

```bash
git clone --branch <branch> --depth 1 https://github.com/eamars/deepseek-harness.git <dsh-inline-checkout>
node tools/build_dsh_inline.mjs --source <dsh-inline-checkout>
```

The builder refuses a different commit or local changes. It installs frozen dependencies without
lifecycle scripts, builds Host Remote contributions before client typechecking, and packages the three changed
packages: the two client packages from their built `lib`, and `dsh-compaction-basic` as the released package with the
fork's built `lib` in place of its own. Hashes and provenance go to `.runtime/adr008/packages/native-inline-manifest.json`.

From then on `tools/pack_plugins.py` includes the two packages in the delivery manifest, and
`tools/setup_native_profile.py` installs them with the Asuna plugins through DSH's official plugin installer. They
are profile dependencies, not Asuna bundles. Workspace `node_modules` is never edited. `node tools/probe_plugin_install.mjs`
checks the installed result. Without a build, packing and installing skip the extension.

## Review scenarios

UI review uses an isolated Web profile with real adapters disabled and [the synthetic fixture](../fixtures/inline_brains.mjs).
Entered in that profile's native composer:

- `dual-flow` (any input containing `dual-`): her turn delegates a real native task; the action brain reads two
  synthetic records, asks her once, leaves a progress note and reports, and her next turn reads the result.
- `dual-failure`: the same task with an actual native failure in the action session.

These scenarios run no external model or channel consumer.
