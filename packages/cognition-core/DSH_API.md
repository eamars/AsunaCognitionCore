# What Asuna relies on in DSH

The DSH services, hooks, events, APIs, UI facilities and file formats the core plugin (`packages/cognition-core`) uses, each with what it is used for and where in our code. For the owner at a DSH upgrade: when DSH changes one of these, the row says what to check. Paths are under `packages/cognition-core/src/` unless given otherwise; the profile's composition is `packages/cognition-core/cordis.patch.yml`. Patches Asuna carries on DSH itself are commits on the fork's `asuna/<version>` branches ([AGENTS.md](../../AGENTS.md)).

## Services (Cordis injection)

| DSH thing | What Asuna uses it for | file:name |
|---|---|---|
| `agents` (`create`, `resume`, `get`) | open and resume her role sessions, action sessions and the scheduler session | `index.js` `openAgent`; `schedule.js` |
| `agentPresets` (`mount`) | mount the role, action, summary, appraiser, attend, scheduler and recovery presets | `index.js` `openAgent`; `preset.js` |
| `agentDefaultModel` (`currentSelection`) | the model a brain uses when its route is unset | `index.js` `routeFor` |
| `sessionPersistence` (`stat`, `open`, `create`, `list`) | read and write her conversations' logs without loading an agent | `navigation.js` `recordChannelInput`; `persistence.js` `AsunaPersistence` |
| `sessions` (`get`, `prepare`, `flush`, `list`, `retain`, `binding`) | write received lines into loaded conversations; client session lists | `navigation.js`; `client.js` |
| `sessionController` (`list`, `rename`) | announce conversations to the sidebar; titles | `navigation.js`; `carry.js`; `schedule.js` |
| `sessionProjections` (`snapshot`) | read a loaded session's projection for the API | `api.js` |
| `sessionProjectionCache` (`coldSnapshot`, `cachedSnapshot`, `write`) | checkpoint a conversation written cold so the sidebar can read it | `navigation.js` `checkpointCold` |
| `workspaceRegistry` (`create`, `list`, `insertBefore`, `delete`, `archiveSession`, `unarchiveSession`) | her workspaces (Local and one per channel), archiving and unarchiving conversations | `navigation.js` `organizeNativeWorkspaces`; `index.js` `openAgent` |
| `workspaceController`, `storageDomain`, `subagents` | injected by the core plugin; `subagents` catalogues her action tasks as DSH subagents | `index.js` `inject`; `children.js` |
| `tools` (`register`, `guard`, `restrict`) | register her role tools and the action tools, refuse a tool a session may not use, tool-free presets | `index.js` `attachPreset`; `attend.js`; `appraiser.js`; `recovery.js` |
| `systemPrompt` (`section`, `getSectionOrder`) | her persona prefix, identity and the web search section | `index.js` `attachPreset`; `search.js` |
| `llm` (`listProviders`, `listModels`, `resolveModelInfo`, `stream`) | the settings card's catalog, route checks, her compaction engine | `api.js`; `index.js` `resolveRoutes`; `compaction.js` |
| `tokenMeter` | a conversation's size in DSH's own measure, for condensing | `index.js` `conversationSize` |
| `commands` (`register`) | register `/heartbeat`; run `/compact` on a group's session | `index.js` `apply`, `compactSession` |
| `schedule` (`create`, `update`, `delete`, `list`, `catalog`) | her plans and rhythms; the worker waits up to a minute for it | `index.js` `attachSchedule`; `schedule.js` |
| `settings` | the plugin's settings and their revision fence | `index.js` `apply`; `api.js` |
| `credentials` | her credential records `asuna-cognition-core/<name>` and secret references | `index.js` `credentialRecords`, `credentialValues` |
| `sandbox` (`confine`) | confine the worker's and the floor's commands to one folder | `index.js` `sandboxProvider`; `floor.js` `apply` |
| `web` (`registerSearchProvider`, `registerFetchProvider`) | the `asuna-search` and `asuna-fetch` providers | `search.js`; `fetch.js` |
| `spillStore` | page an action session's spilled tool output | `index.js`; `spill.js` |
| `attachments` | the action preset's image attachments | `action.js` |

## Agent and session hooks

| DSH thing | What Asuna uses it for | file:name |
|---|---|---|
| `tools/pre-execute` | check each action tool call against its task's fence (`stage.valid`) | `index.js` `attachPreset` |
| `agent/inbox/inserted`, `agent/inbox/claimed` | lines waiting in her conversation's next-step inbox | `index.js` `attachPreset` |
| `system-prompt/assemble` | her role system prompt | `index.js` `attachPreset`; `recovery.js` |
| `agent/request` | route each request to the brain's model and effort; attribute it (`asuna/stage`) | `index.js` `attachPreset` |
| `agent/pre-step` | deliver the turn's notice and held lines at a step boundary | `index.js` `attachPreset`, `openAgent`; `scheduler.js` |
| `agent/assistant-stream`, `agent/turn-stopping`, `agent/status`, `agent/error`, `agent/disposed` | follow her turns and end them | `index.js` `attachPreset` |
| `agent/request-error` | the action brain's second tier falling back; refused pictures offloaded and retried | `index.js` `attachPreset`; `image-refusal.js` |
| `agent/created` | attach the role and action presets to a new agent | `role.js`; `action.js` |
| `session/event`, `domain/changed` | wait for a session's head and its projection checkpoint | `navigation.js`; `pairing.js` |
| `agent.inbox.splice`, `agent.inbox.nextStep`, `agent.followup` | queue lines before her first step; continue a stage | `navigation.js`; `children.js` |

## Session event types

| DSH thing | What Asuna uses it for | file:name |
|---|---|---|
| `user/message` | received platform lines written into her conversation | `navigation.js` `recordChannelInput`; `pairing.js` |
| `agent/inbox/spliced` (target `next-step`) | lines waiting before her first turn (at most 40) | `navigation.js` `queueing` |
| `system/message` | the session head that must come before any line | `navigation.js` `recordChannelInput` |
| `step/start`, `step/end`, `turn/start`, `turn/end` | a platform line waits while a step is open (the request, her reply, its tool calls and results); `step/end` is appended in a `finally`, so a failed or aborted step closes too, and is where the held lines are released: `agent/turn-stopping` is dispatched only after a step that returned | `pairing.js` `stepOpen`, `mustHold`, `releaseAtBoundary` |
| `tool/call`, `tool/result` | find a line already written between a call and its result | `pairing.js` `strayLines` |
| `systemPrompt.context` (`working-directory:current`, registered `required`, which `suppressRuntimeContext()` keeps) | her lanes register an empty context of the same name through their own scope, which shadows it; the action brain keeps it | `contexts.js` `withoutWorkingDirectory` |
| `compaction/start`, `compaction/end`, `compaction/summary`, `session/end-seed` | hold lines during a compaction (and release them as it ends); a step or compaction started before an `end-seed` runs no more; carry a conversation past its window | `pairing.js` `compactionOpen`, `releaseAtBoundary`; `carry.js` |
| surface replace (`surfaceOp: {op: "replace"}`) | empty a stray line in place | `pairing.js` `repair` |
| `image/offload` | turn retained pictures into DSH's placeholders after a refusal | `image-refusal.js` |
| `session/title` | conversation titles | `navigation.js` |
| `assistant/message`, `assistant/live-chunk`, `subagent/descriptor`, `subagent/catalog`, `model/selection` | read in the client and API projections | `client.js`; `api.js` |
| Asuna's own `asuna/stage`, `asuna/stage-result`, `asuna/schedule`, `asuna/collab`, `asuna/web-search` | written `ignorable: true`, so plain DSH readers skip them | `persistence.js` `ASUNA_EVENTS` |

## Package APIs

| DSH thing | What Asuna uses it for | file:name |
|---|---|---|
| `@deepseek-ai/dsh-llm` (`createUserMessage`, `BlockAssembler`, `LlmError`, `contentHasImage`, `CONTEXT_WINDOW_EXCEEDED_CODE`) | messages she receives; compaction; carrying an overflowing conversation | `navigation.js`; `pairing.js`; `compaction.js`; `carry.js` |
| `@deepseek-ai/dsh-session/fork` (`buildForkSeed`) | an errand's copy of a conversation | `index.js` `openAgent` |
| `@deepseek-ai/dsh-session-persistence`, `@deepseek-ai/dsh-session-persistence-jsonl` | the persistence service Asuna wraps to mark its events | `persistence.js` |
| `@deepseek-ai/dsh-session-projection-cache` (`projectionCacheDomainSpec`) | the checkpoint a cold write waits for | `navigation.js` |
| `@deepseek-ai/dsh-compaction-basic` | base of her compaction engine (`floorTokens`, `turnEndTokens`; `compactNow` with `options.keepFrom` at her turn's end, when it takes one) | `compaction.js` `RoleCompactionEngine`, `compactAtTurnEnd`, `TurnEnds`; `index.js` `turnEnd` |
| `@deepseek-ai/dsh-tools` (`defineTool`, `validateArgs`) | tool definitions; argument refusals in DSH's own terms | `index.js`; `tool-args.js`; `search.js` |
| `@deepseek-ai/dsh-system-prompt` (`PERSONA_PREFIX_SECTION`) | her persona section's place | `index.js`; `recovery.js` |
| `@deepseek-ai/dsh-skill`, `dsh-skill-filesystem`, `dsh-tool-skill`, `dsh-tool-todo`, `dsh-tool-web` | the action brain's `skill`, `todo_write`, `web_search`, `web_fetch` | `index.js`; `search.js` `registerWebSearch` |
| `@deepseek-ai/dsh-web`, `dsh-web-fetch-http`, `dsh-web-search-exa` | the search and fetch providers | `search.js`; `fetch.js` |
| `@deepseek-ai/dsh-credentials` (`credentialKey`, `credentialRef`), `@deepseek-ai/dsh-settings` (`redactSecrets`) | secret references and redaction | `index.js`; `search.js` |
| `@deepseek-ai/dsh-spill-local` (`sessionDir`) | where a session's spilled output is | `spill.js` |
| `@deepseek-ai/dsh-typert-protocol` (`TypertRemoteService`, `Remote`) | the plugin's `/api` service the Web client calls | `api.js` `AsunaApi`; `client.js` |
| `@deepseek-ai/cordis`, `cordis-plugin-loader` (`EntryGroup`), `@deepseek-ai/schemastery` | the preset service and the settings schema | `preset.js`; `index.js` `Config` |

## Web UI facilities

| DSH thing | What Asuna uses it for | file:name |
|---|---|---|
| slots `sidebar.right.pane.tab`, `plugins.bundle.config`, `conversation.composer.dock`, `conversation.chat.node`, `conversation.input.permission`, `conversation.session.header.actions`, `sidebar.session.row.leading`, `tool.call.toolview` | the memory tab, the settings card, brain meters, stage and thread rows, read-only composer notes | `client.js` `apply` |
| `sidebarRightTabs`, `sidebarRight` | the memory tab and opening resources in it | `client.js` |
| `configForms`, `remote.settings`, `remote.credentials` | the settings card's form, its staged values and secret fields | `client.js` |
| `uiConversation` (`events.register`, `binding`), `conversation.blocks` | her thread entries and composer policy in the conversation view | `client.js` |
| `locale` (`register`, `subscribe`, `getSnapshot`, `bind`) | the client's words; the language reported back for task titles | `client.js`; `ui-language.js` |
| `connection.rpc` | calls to `/api` | `client.js` |
| `@deepseek-ai/dsh-client-ui-schedule` | DSH's task page, mounted for the owner | `cordis.patch.yml` (`asuna-ui-schedule`) |

## Composition and file formats

| DSH thing | What Asuna uses it for | file:name |
|---|---|---|
| `cordis.patch.yml` | mounts the JSONL persistence, spill store, Asuna's persistence wrapper, floor, core plugin and presets; each preset's compaction (`dsh-compaction-basic`, `dsh-command-compact`, `dsh-compaction-tool-result-pruner`) | `packages/cognition-core/cordis.patch.yml` |
| session logs (JSONL, event `seq`, `ignorable`) | written through `sessionPersistence`; read cold by `recordChannelInput` | `persistence.js`; `navigation.js` |
| credential store records | `asuna-cognition-core/<name>`, kind `grant`, payload `{note, env}` | `index.js` `credentialRecords` |
| profile data folder (`$DSH_HOME/asuna/<profile>/`) | the default data root | `paths.js` `dataRoot` |
