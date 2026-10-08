# ADR-026: Her web search tries the owner's SearXNG first

Status: **Accepted and built** 2026-10-08. The owner's proposal; the owner decided each open point from measured
options.

## 1. Context

Her action brain's `web_search` is DSH's tool (`dsh-tool-web`) over DSH's web service (`ctx.web`). DSH's base bundle
pins the service's search provider to `deepseek-official` (`dsh-web-search-deepseek`): each search is a DeepSeek
Messages request with server-side search, paid with the `DEEPSEEK_API_KEY` that DSH's Models page stores. That was
how the owner's account was being charged.

The owner runs a SearXNG instance on the LAN and may add Exa later. Measured on 2026-10-08:

- Usage: 86 `web_search` calls in four days, up to 39 a day, in bursts (48 of 85 gaps under 30 s).
- The instance's `settings.yml` is upstream's file at its commit with only `json` added to `search.formats`; its
  limiter is off. A query fans out to every default general engine (Google, DuckDuckGo, Brave, Startpage, Wikipedia,
  Wikidata). The instance is shared with an MCP SearXNG client on the same host.
- Upstream engines were turning the instance away: Google `access denied`, DuckDuckGo, Startpage and Baidu `CAPTCHA`,
  Brave `too many requests`; SearXNG suspends such an engine for a day (an hour for 429). Default searches came back
  empty. One probe per engine, four seconds apart: Bing, Yandex, 360search and Fynd answered; Qwant, Sogou,
  Searchmysite were denied; Ask, Yep, Presearch, Yahoo errored; Quark, Seznam, Yacy timed out; Mojeek, Wiby, Naver,
  Crowdview, Encyclosearch answered nothing.
- SearXNG has no per-engine pacing option (its engine settings are timeouts, proxies, pools, retries); its limiter
  throttles clients of the instance, not the instance's requests upstream. `suspended_times` only sets how long an
  engine pauses after a block. Pacing therefore belongs to the caller.
- The search API selects engines per request (`engines=`), including engines disabled on the instance, so the
  engine choice needs no change on the owner's server.
- DSH publishes `dsh-web-search-exa` at the pinned version; there is no DSH SearXNG provider.

## 2. Decisions (owner, 2026-10-08)

- **D1 — Same tool, ordered backends.** She keeps DSH's `web_search`, its schema and its output. Underneath, a
  priority list: SearXNG first, Exa second when configured, DSH's DeepSeek search last; the order is configurable.
- **D2 — SearXNG cooldown.** At most one SearXNG query per 30 seconds, and a 15-minute rest when it fails or answers
  with every asked engine blocked. Both configurable. During a cooldown or rest the query goes to the next backend.
- **D3 — An empty SearXNG answer is a miss.** It falls through to the next backend rather than reaching her as "No
  results found"; an empty answer is returned only when no backend had sources.
- **D4 — Configured on the cognition core's card.** A `search` section in the core's deployment settings, edited on
  its existing card (structured JSON field, write-only credential control for the Exa key); no new UI.
- **D5 — Engines per request, not on the server.** The owner allowed changing the instance through its web or REST
  interface and asked for every engine that works. The engines go in `search.searxng.engines`, sent with each
  query: the ones that answered from this address (Bing, Yandex, 360search, Fynd) and the instance's general
  defaults (Wikipedia, Wikidata, Google, DuckDuckGo, Brave, Startpage), which SearXNG skips while suspended and asks
  again when the suspension ends. The instance itself is unchanged.

## 3. As built

- `packages/cognition-core/src/search.js`: `OrderedSearch`, registered on `ctx.web` as `asuna-search`
  (`applySearch`). Per query it walks `deployment.search.order` (default `searxng`, `exa`, `deepseek-official`):
  `searxng` calls the instance's JSON API with the configured engines and a per-request timeout (default 10 s),
  claiming its cooldown before the request so the other queries of one call move on; `exa` builds DSH's
  `ExaSearchProvider` with the credential the reference names; any other id is a provider registered on the
  service. A cancelled call stops; any other failure is recorded and passed over. Every search appends a log-only
  `asuna/web-search` event (query, the backend that answered, why earlier ones were passed over).
- `ctx.web` has no lookup by id, so `registered()` reads the pinned `dsh-web`'s provider map; a test guards that.
- `tools/setup_native_profile.py` pins the `web` row to `asuna-search`, restating `fetchProvider: http` because a
  profile patch replaces the whole row config.
- `native_settings.runtime_settings` drops `search` before resolving credentials: the worker never reads it, and
  an Exa reference without a stored key would otherwise stop the worker (`CREDENTIAL_NOT_CONFIGURED`).
- The cooldown lives in the Host process: a restart forgets it, at most one early query.
- Tests: `packages/cognition-core/test/search.test.js`, `tests/test_search_profile.py`. Current reference:
  [RUN_ASUNA.md](../../../RUN_ASUNA.md#web-search).
