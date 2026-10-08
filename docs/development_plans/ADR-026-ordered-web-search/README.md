# ADR-026: Her web search tries the owner's SearXNG first

Status: **Accepted and built** 2026-10-08. The owner's proposal; the owner decided each open point from measured
options. **Amended** 2026-10-08: a Gemini backend between SearXNG and Exa (§4), accepted, not built.

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

## 4. Amendment: Gemini grounding between SearXNG and Exa (owner, 2026-10-08)

Status: **Accepted and built** 2026-10-08; **out of the live order** (owner, the same day): the free tier gives
new keys no Google Search grounding (§4.5).

### 4.1 Context

- Google turns the owner's SearXNG away (§1), and an automated browser signed in to a Google account is not a way
  around it: Google's terms forbid automated queries, and the account would be challenged or suspended. Google's own
  sanctioned path to its results is the Gemini API's Grounding with Google Search: a Gemini request with the search
  tool on, in which Gemini runs the Google queries and answers with citations. It returns no raw result page.
- Request (`generateContent`): `POST /v1beta/models/<model>:generateContent`, header `x-goog-api-key`, body with
  `"tools": [{"google_search": {}}]`. The response's `candidates[0].groundingMetadata` carries `webSearchQueries`,
  `groundingChunks[].web.{uri,title}` (each `uri` is a `vertexaisearch.cloud.google.com/grounding-api-redirect/...`
  link, not the page's address), `groundingSupports` (answer spans to chunks) and `searchEntryPoint.renderedContent`
  (search suggestions HTML that Google's terms ask to show with grounded results). The current docs also describe a
  newer `POST /v1beta/interactions` endpoint (`"tools": [{"type": "google_search"}]`, `url_citation` annotations).
- Price, read 2026-10-08 from the Gemini API pricing page:

  | Model | Free | Beyond |
  |---|---|---|
  | 2.5 Flash-Lite / 2.5 Flash | 500 requests a day (free tier); 1,500 a day (paid tier); shared by both | $35 per 1,000 grounded requests |
  | 3.x Flash, 3.5 Flash-Lite | 5,000 searches a month, paid tier only, shared by all 3.x | $14 per 1,000 searches, each query Gemini runs counted |

- Fit against §1's usage (up to 39 calls a day): 2.5 Flash-Lite's free tier is about 8% used at the peak; 3.x at
  2–4 queries per call is about 2,300–4,700 searches a month against 5,000. Placed after SearXNG, Gemini sees only
  the calls SearXNG skips, rests on or misses, so less. Free-tier prompts may be used by Google to improve its
  products; free-tier keys also have a per-minute limit, which §1's bursts may reach (unmeasured).

### 4.2 Decision

- **D6 — A `gemini` backend between SearXNG and Exa.** The default order becomes `searxng`, `gemini`, `exa`,
  `deepseek-official`; like the others it is skipped when not configured, a failure falls through, and the order
  stays configurable. It is configured in the core's `search` section on the existing card (D4), with a write-only
  credential control for its key.

### 4.3 Decisions on the open points (owner, 2026-10-08, from measured options)

- **D7 — 2.5 Flash-Lite on the free tier.** 500 grounded requests a day, free; the owner accepted that Google may use
  free-tier prompts (her search queries) to improve its products. The model is configurable.
- **D8 — Sources only.** Gemini's cited pages fill `web_search`'s source list like the other backends'; its answer
  text is dropped, as DSH drops DeepSeek's. The grounding supports are Gemini's wording, so sources carry no snippet.
- **D9 — Real addresses.** Each `grounding-api-redirect` link is followed one hop (`HEAD`, no body, 5 s) to the
  page's own URL, so she cites and fetches the page; a link that does not resolve stays as it was.
- **D10 — A 429 rests Gemini until its quota refreshes.** The owner: for 2.5 Flash-Lite, daily, matching its refresh
  cycle. The 429's `QuotaFailure` names the quota: a per-day quota rests until midnight Pacific time (when Gemini's
  daily quotas reset); any other rests for the error's `retryDelay`, or a minute without one. Following the named
  quota rather than the model keeps a per-minute 429 from resting it all day.
- Not decided: Google's terms ask that search suggestions (`searchEntryPoint`) be shown with grounded results. Here
  the results reach a model, not a person, and nothing renders them; raised with the owner.

### 4.4 As built

`search.js`: `gemini` step (`OrderedSearch.gemini`, `geminiSources`, `resolve`, `geminiRetryAt`,
`nextPacificMidnight`), `GEMINI_DEFAULTS` (`gemini-2.5-flash-lite`, v1beta `generateContent`, 20 s), default order
`searxng`, `gemini`, `exa`, `deepseek-official`. Its key is a credential reference in `search.gemini.api_key`; an
unset one is passed over (§3). Tests stub Gemini's responses; no real Gemini call was made in development.

### 4.5 Tried live (2026-10-08)

The owner gave two free-tier keys. With both: every Gemini 2.5 model answers 404 "no longer available to new users"
(Flash-Lite and Flash); `gemini-3.5-flash-lite` answers a plain request (200) but a request with `google_search`
answers 429 "exceeded your current quota" with no quota details, i.e. a limit of zero: grounding on 3.x models is
paid-tier only. D7's free tier is therefore not available to a new key. The owner took Gemini out of the live
order; the code, its default model (now `gemini-3.5-flash-lite`) and the stored key stay for when billing is on.

## 5. Amendment: result size, and a cache not built (owner, 2026-10-08)

### 5.1 Context

- Exa's snippets are whole page sections: one real result was about 6,000 characters for 8 sources, against a
  median of 1,273 (p90 1,802) for her 84 earlier results, which came from DeepSeek.
- The owner asked for a 7-day cache that she may choose to use, matched by embedding as well as by text. Her 222
  accepted queries (2026-10-05 to 10-08) were all distinct, even ignoring word order. With Asuna's own embedding
  model (query prefix), the closest earlier query within 7 days was at least 0.95 similar for 2, 0.90 for 7 (3%),
  0.85 for 33 and 0.80 for 56. At 0.90 and above they were the same question reworded; between 0.85 and 0.90 mostly
  deliberate refinements (the same price search narrowed to a shop, or to a year-on-year comparison), where an old
  answer would undo the refinement.

### 5.2 Decisions

- **D11 — No cache now.** About 3% of her searches would hit. Recorded for when her volume or repetition grows: a
  shared cache where a hit from another conversation shows only the results and their age, not that query's text.
- **D12 — Snippets capped, titles on request.** Every backend's snippet is cut to 300 characters (configurable,
  `search.snippet_chars`) with an ellipsis; a `detail: "titles"` argument returns only title, link and date. This
  extends D1: the tool keeps DSH's name, output text and cards, and gains one optional argument.
- **D13 — 10 sources a call** (DSH's default is 8).
- Publication times reach her on the conversation's clock (the owner's rule that every time a model reads is local):
  the session binding names the zone, and the tool formats `publishedAt` as `YYYY-MM-DD HH:MM`.

### 5.3 As built

`search.js`: `capSnippets` in the provider; `registerWebSearch` builds the action scope's `web_search` from
dsh-tool-web's exported `formatSearchOutput`, `presentSearchCall`, `presentSearchResult` and `searchMetaFromValue`,
with copies of its unexported argument check and merge (`parseSearchArgs`, `mergeResults`) and its guidance text;
`web_fetch` stays DSH's (`search: false`). `localStamp` formats publication times; `native_worker`'s `session` reply
carries `timezone` and `utc_offset_minutes`. Measured with real searches: the same Exa query is about 4,100
characters for 10 sources with snippets, 1,400 as titles.
