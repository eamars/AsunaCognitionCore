# Asuna Web UI

The Asuna workbench is a local operator view embedded in DSH. `/asuna/` opens the DSH main page with the Asuna panel selected. The workbench reuses the running Python host and its `Chat` controller; it is not a separate chat runtime.

## Start

From the repository root, use the standard entry point:

```powershell
.\start-asuna.cmd
```

Open the URL printed by the process, or use `http://127.0.0.1:8765/asuna/` when the default port is selected. `start-asuna-ui.cmd` is an alias. See the root [runbook](../../RUN_ASUNA.md) for local configuration and read-only mode. Closing the page does not stop the host.

## Workbench areas

- **Left — scenes and channels:** search and select the local DM or an authorized channel scene, such as an owner QQ DM or group. The list navigates scenes; it does not expose DSH contexts or sessions.
- **Center — conversation and execution:** send messages, load earlier messages, follow live character/action output, and expand tool calls, results, or errors. Failed steps keep a short visible error summary and the full payload in the expandable execution record. A send whose response is interrupted is not automatically repeated.
- **Right — inspector:** search and inspect memory, preference, group-preference, relationship, and integration records available in the current scene. Details are read-only. Empty preference views represent missing records; the UI does not infer preferences from message text.
- **Model settings:** edit the character and action routes independently, discover model IDs from a configured endpoint, and apply settings when the host is idle.
- **Host controls:** refresh the view, request an internal self-development opportunity for the owner scene, or stop the whole host and its actions.

Messages from every internal context generation remain in that scene's history. Selecting an authorized interactive scene opens its existing cognition session and allows a message to be sent. For configured owner QQ DM and group routes, the composer submits an explicitly labeled local instruction to that channel scene. Routes without a local owner send permission remain read-only.

## DSH integration

The client uses the fixed DSH `0.1.5-rc.2` public UI primitives, including `Button`, `Input`, `DisclosureRow`, `MarkdownText`, `CodeBlock`, and status indicators. DSH owns page delivery and lifecycle; the plugin registers the Asuna main-panel and sidebar entries. Asuna supplies scene projection, inspector records, stable message identity, and trusted callbacks to the existing host.

The workbench keeps a light three-column layout. Body text uses DSH Markdown rendering. Inline code, JSON, tool payloads, and structured details use the shared monospace font stack.

## Development

There is no separate UI build script in `dsh-plugin/ui/package.json`; DSH loads the client module and static assets from the plugin package. Install the repository's locked dependencies with `npm.cmd ci` when setting up the project. Edit the client, inspector, or CSS in this directory, then restart the host to load the changes. Keep UI changes on the existing public DSH primitive and Web API surfaces.

Current UI limitations are listed in [LIMITATIONS.md](LIMITATIONS.md); the host-side bridge and data mapping are in [INTEGRATION.md](INTEGRATION.md).
