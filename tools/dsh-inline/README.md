# Native Chat composition extension

Optional. Shows the action brain's original records inside the main conversation instead of DSH's subagent view.

Stock DSH lets one owner declare the `conversation.chat.flow` slot and rejects reuse of the same factory under a
different session. Two commits on the Asuna branch of the DSH fork add a Session-scoped native Chat factory,
`conversation.chat.content`, and permit different authorized source bindings while keeping cycle protection. Native
messages, tools, attachments, disclosures, history and context ownership stay native. A fragment renders the
source Session's grouped Chat entries through DSH's own Chat flow, so an action turn folds, groups tool calls and
discloses thinking exactly as the character brain's turn does. Fragment anchors do not enter main-session
navigation. The extension changes rendering only.

## Build

[`source.json`](source.json) names the fork, the branch (`asuna/<DSH version>`: the DSH release tag plus the two
commits), the exact commit, and the DSH version it extends. Build in a **dedicated checkout** of that commit, with
Node (pnpm comes through corepack):

```bash
git clone --branch <branch> --depth 1 https://github.com/eamars/deepseek-harness.git <dsh-inline-checkout>
node tools/build_dsh_inline.mjs --source <dsh-inline-checkout>
```

The builder refuses a different commit or local changes. It installs frozen dependencies without
lifecycle scripts, builds Host Remote contributions before client typechecking, and packages only the two changed
native packages. Hashes and provenance go to `.runtime/adr008/packages/native-inline-manifest.json`.

From then on `tools/pack_plugins.py` includes the two packages in the delivery manifest, and
`tools/setup_native_profile.py` installs them with the Asuna plugins through DSH's official plugin installer. They
are profile dependencies, not Asuna bundles. Workspace `node_modules` is never edited. `node tools/probe_plugin_install.mjs`
checks the installed result. Without a build, packing and installing skip the extension.

## Review scenarios

UI review uses an isolated Web profile with real adapters disabled and [the synthetic fixture](../fixtures/inline_brains.mjs).
Entered in that profile's native composer:

- `dual-flow`: a real native task with two tool consultations; `dual-failure`: an actual native failure;
  `dual-media`: a native file link and image from the action's distinct workspace.
- `dual-long`: 600 native assistant steps and 599 numbered tool receipts. DSH counts assistant/user messages toward
  its 500-message page cap; cold loading shows the final 500 steps, and the shipped Load earlier control retrieves
  the rest.
- `dual-continue-first` then `dual-continue-next`: cold continuation of a native source across separate tasks on
  the same execution binding; `dual-continue-auto` announces the successor inside the first Turn's result
  acknowledgement. Both tasks keep their own grants and source ranges.

These scenarios run no external model or channel consumer.
