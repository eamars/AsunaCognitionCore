# ADR-036: The brains' models are DSH providers

Status: **Accepted and built 2026-10-10**, owner's decision.

## Context

The early design gave Asuna its own model settings. `config/local.json` (and an adjacent `*.models.local.json`) held
each brain's address, model, request options, effort mapping, sampling, token counter and key. The installer turned
them into two DSH providers of its own (`asuna-character`, `asuna-action`) with keys `ASUNA_NATIVE_*_KEY`, set
`local-no-auth` when there was no key, and overwrote DSH's default model. The address had to be a literal private
IP. The worker itself never read those settings: it takes both models from DSH's catalog.

The owner, checking whether a cloud provider such as DeepSeek still works: a plugin with its own model-key settings,
where DSH already has them, is a red flag; Asuna should inherit DSH's settings and use only what DSH understands.

## Decision

- **D1. Address check at DSH's level.** A model or embedding address is checked as DSH's Models page checks one: an
  http or https URL with a host. Nothing more.
- **D2. Effort from DSH.** Each route's effort, and the character route's efforts for her relevance gate
  (`attendEffort`) and her group turns (`groupEffort`), are chosen on the settings card from the levels DSH reports
  for the model, under DSH's own names. Empty is the route's effort (or the model's default). A level the model does
  not offer is refused, never dropped. Asuna has no built-in effort names or defaults.
- **D3. Models only in DSH.** Providers and their keys are defined on DSH's Models page (or, for a self-hosted
  server's reasoning options the form does not show, in the provider's `llm-pi-ai` settings). Asuna's settings card
  picks a provider and model per brain; a brain without one uses DSH's default model. Asuna's config has no model
  routes; the installer writes no provider, key, route or default model. Embedding stays in Asuna's deployment
  settings: DSH has no embedding providers.

## Consequences

- A cloud provider pi-ai knows needs only its key on DSH's Models page.
- The live profile's two providers stay as ordinary DSH providers; nothing was migrated. Its stage efforts moved from
  `deployment.reasoning_effort` to the character route (gate low, groups medium, as before).
- A config that still names `character` or `executor` is refused with `MODEL_ROUTES_ARE_DSH_PROVIDERS`.

## Trial: DeepSeek V4.1 Flash as the character brain (2026-10-11)

At the owner's request her character route was switched on the settings card to DSH's `deepseek-official` provider,
model `deepseek-flash`: effort High, gate Low, groups following High because the model offers no Medium. Her action
brain stayed local. It ran about 9 minutes, 15:41–15:50 NZDT, and was switched back early on the owner's call.

- **It works with the harness:** about 40 requests and no tool errors. From the second request in each
  conversation, about 99.9% of each prompt was read from cache. Its token counts for her content are within 1% of
  the local model's.
- **Her words were unchanged, but the "think first" habit was not:** 6 of 12 turns skipped `think` and were
  repaired automatically, against about 3.5% of turns on the local model. Her own reading: "what I say is mine;
  following the rule depends on the model."
- **Context is the risk when switching back.** DeepSeek's window is 1M, so her conversations don't compact until
  about 800K. The local model compacts at about 210K and can compact nothing past about 235K: replaying the prefix
  plus the 24,576-token summary cap must fit 262K. The agent line reached 225K and compacted on its first local
  turn, at the edge.
- **Before a longer run:**
  - add a per-model compaction policy for `deepseek-official/deepseek-flash` (`modelPolicies` in
    `dsh-compaction-basic`), compacting near 200K and keeping a tail the size the local model keeps;
  - close or watch fast-growing lines;
  - accept the extra repair requests for skipped thoughts, or patch DSH for tool choice (it has none today).
- **Separate from the trial:** one resting group sits at 229K. Its next local compaction needs about 254K of the
  262K window, which fits only barely. A lower threshold or summary cap would add margin; the owner's call.
- **Owner's decision (2026-10-11):** no switching between models in the short term; a persona sticks to one model at
  a time. So neither the per-model compaction policy nor extra margin for the 229K group is needed now.

