# Approved native Chat composition extension

ADR-008's [2026-10-03 amendment](../../docs/development_plans/ADR-008-dsh-plugin/AMENDMENT-20261003-INLINE-BRAINS.md) approves displaying original action records in the main conversation. Stock DSH rc.2 gives one owner the `conversation.chat.node` slot and rejects reuse of the same factory under a different session. `rc2-inline.patch` adds a Session-scoped native Chat factory and permits different authorized source bindings while retaining cycle protection. Native messages, tools, attachments, disclosures, history and context ownership remain native. A fragment renders the source Session's grouped Chat entries through the main Chat's own list, so an action turn folds, groups tool calls and discloses thinking exactly as the character brain's turn does. Fragment anchors do not enter main-session navigation.

The patch applies only to DSH commit `639ed015397290b3745d163aafe02ffee4aa3f84` (`dsh-v0.2.0-rc.2`). Build in a **dedicated checkout**, using Node and pnpm:

```powershell
git -C C:\workspace\deepseek-harness fetch origin tag dsh-v0.2.0-rc.2
git -C C:\workspace\deepseek-harness worktree add --detach C:\workspace\dsh-asuna-inline dsh-v0.2.0-rc.2
node tools/build_dsh_inline.mjs --source C:\workspace\dsh-asuna-inline
npm.cmd run pack:plugins
node tools/probe_plugin_install.mjs
```

The builder refuses a different base commit or unrelated source changes. It installs frozen dependencies without lifecycle scripts, builds Host Remote contributions before client typechecking, and packages only the two changed native packages. Hashes and provenance go to `.runtime/adr008/packages/native-inline-manifest.json`; the Asuna packer includes them in the delivery manifest. `tools/setup_native_profile.py` installs the two native packages with the Asuna plugins through DSH's official plugin installer. They are profile dependencies, not additional Asuna bundles. Workspace `node_modules` is never edited.

The running production profile is not changed by building or installation probes. UI review uses an isolated Web profile with real adapters disabled and [the synthetic fixture](../fixtures/inline_brains.mjs). `dual-flow` entered in that profile's native composer creates a real native task with two tool consultations; `dual-failure` exercises an actual native failure. `dual-media` adds a native file link and image from the action's distinct workspace. These scenarios run no external model or QQ consumer.

`dual-long` creates 600 native assistant steps and 599 numbered tool receipts. DSH counts assistant/user messages toward its 500-message page cap; tool receipts alone cannot exercise that cap. Cold loading shows the final 500 steps, and the shipped Load earlier control retrieves the remaining steps without a second history store or pager.

This extension changes rendering only. The Core now preserves a native source across separate tasks on the same execution binding. `dual-continue-first` then `dual-continue-next` exercise cold continuation; `dual-continue-auto` announces the successor inside the first Turn's result acknowledgement to probe teardown ordering. Both tasks retain their own current grants and source ranges. Proactive steering of an in-flight task still requires separate implementation and evidence.
