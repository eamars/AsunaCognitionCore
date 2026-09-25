# Web UI integration

The UI plugin is an adapter between DSH's local Web page and the existing Asuna Python host. It does not own conversation state, task execution, memory, or publication.

## DSH extension points

The pinned DSH package is declared in the root `package.json` and plugin package manifest. The client loads DSH's shared React runtime and public primitives through `window.__ModuleLoader__`. It registers the Asuna panel in the `main` slot and an Asuna entry in `sidebar.panellist`. The host plugin registers `/asuna` assets and API forwarding through `ctx.webServer.register`.

The client composes public DSH primitives such as `Button`, `Input`, `DisclosureRow`, `MarkdownText`, `CodeBlock`, and status indicators. Asuna code maps its own scene, message, execution, and inspector data into those primitives.

## Request path

```text
Browser → DSH /asuna plugin → loopback UiBridge → Workbench / Chat / RuntimeHost
```

`host.js` requires DSH to bind to `127.0.0.1`, checks the request Host and Origin, applies a same-origin content security policy, and accepts only the registered UI paths. The Python `UiBridge` uses a random bearer token passed only to the DSH child process. The browser does not receive the bridge token, Mongo credentials, or provider credentials.

The bridge exposes these UI operations through the DSH prefix route:

| Operation | Behavior |
| --- | --- |
| `GET /asuna/api/state` | Return the selected scene's paged messages, status, inspector records, model settings, and send permissions. |
| `GET /asuna/api/stream` | Stream live character and action text observations for the selected conversation. |
| `GET /asuna/api/provider-diagnostic` | Return authorized provider metadata for an output event in the selected scene. |
| `POST /asuna/api/send` | Submit a local message or, for a configured owner route, an explicit group-speaking prompt. |
| `POST /asuna/api/new` | Request a new DSH context for the local scene while retaining persisted memory. |
| `POST /asuna/api/models` and `/models/discover` | Apply lane settings when idle, or discover model IDs from a configured endpoint. |
| `POST /asuna/api/stop` | Request shutdown of the complete runtime host. |
| `POST /asuna/api/integration/stop` | Stop and disable restoration of the configured managed integration. |
| `POST /asuna/api/self-development/offer` | Queue an internal self-development opportunity in the owner scene. |

The DSH forwarding layer limits UI command bodies to 64 KiB and requires its UI marker header for POST operations. The host validates request methods, payloads, current scene permissions, and available capabilities.

## State and display mapping

- Conversation rows come from authorized scenes and their configured local or channel routes. Historical contexts are selectable for inspection but cannot receive messages.
- Inbound messages appear as user turns. Public character output appears as assistant turns with its actual delivery state. Internal task feedback is attached to the relevant turn rather than shown as a new user message.
- Character phases, action output, tool calls, tool results, and failures are projected from scoped audit events and artifact receipts. Unknown event types retain their type and payload.
- The inspector reads active memory units and the current relationship revision for the selected scene. Preference tabs remain empty when the corresponding structured record does not exist.
- Channel scenes are read-only in the Web UI. A local owner group prompt is marked as a local instruction and is not represented as a platform inbound event.
- The UI offers earlier-message pagination and streams current generation content. The inspector is a current-scene projection, not a snapshot of whichever historical context is selected.

## Runtime boundary

The UI submits work through `Chat` and the `RuntimeHost`. It does not call terminal `chat()` or `terminal()` adapters. Closing or disconnecting the browser stops observation only; it does not cancel a host task. The explicit stop action shuts down the host and its workers.

See [README.md](README.md) for user-facing behavior and [LIMITATIONS.md](LIMITATIONS.md) for current scope limits.
