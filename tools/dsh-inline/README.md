# Native Chat composition extension

Optional. Shows the action brain's original records inside the main conversation instead of DSH's subagent view.

Stock DSH rc.2 gives one owner the `conversation.chat.node` slot and rejects reuse of the same factory under a
different session. `rc2-inline.patch` adds a Session-scoped native Chat factory and permits different authorized
source bindings while keeping cycle protection. Native messages, tools, attachments, disclosures, history and
context ownership stay native. A fragment renders the source Session's grouped Chat entries through the main
Chat's own list, so an action turn folds, groups tool calls and discloses thinking exactly as the character brain's
turn does. Fragment anchors do not enter main-session navigation. The extension changes rendering only.

## Build

The patch applies only to DSH commit `639ed015397290b3745d163aafe02ffee4aa3f84` (`dsh-v0.2.0-rc.2`). Build in a
**dedicated checkout**, with Node and pnpm:

```bash
git clone --branch dsh-v0.2.0-rc.2 --depth 1 https://github.com/deepseek-ai/deepseek-harness.git <dsh-inline-checkout>
node tools/build_dsh_inline.mjs --source <dsh-inline-checkout>
```

The builder refuses a different base commit or unrelated source changes. It installs frozen dependencies without
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
