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
