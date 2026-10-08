/** Her web_search, underneath (ADR-026): one search provider on DSH's web seam (ctx.web) that tries the backends of
 * `deployment.search.order` in turn. The model-facing tool, its schema and its output stay DSH's (dsh-tool-web).
 *
 * - `searxng`: the owner's SearXNG instance (JSON API). At most one query per `cooldown_seconds`; after a failure, or
 *   an empty answer in which every asked engine was blocked, it rests for `rest_minutes`.
 * - `exa`: DSH's Exa provider (dsh-web-search-exa), keyed by a credential reference.
 * - any other id: a provider registered on ctx.web (DSH's `deepseek-official`).
 *
 * A backend that is resting, unconfigured, failing or answers with no sources passes the query to the next one; a
 * cancelled call stops. When none answered with sources, an empty answer is the result; otherwise the call fails. */
import { WebError } from '@deepseek-ai/dsh-web';
import { ExaSearchProvider } from '@deepseek-ai/dsh-web-search-exa';
import { credentialRef } from '@deepseek-ai/dsh-credentials';

export const SEARCH_PROVIDER_ID = 'asuna-search';
export const DEFAULT_ORDER = ['searxng', 'exa', 'deepseek-official'];
export const SEARXNG_DEFAULTS = { cooldown_seconds: 30, rest_minutes: 15, timeout_seconds: 10 };

/** The providers registered on the seam, by id. ctx.web exposes no lookup by id; the pinned DSH keeps them in this
 * map (a contract test guards it). */
export function registered(web) {
  return web?.searchProviders instanceof Map ? web.searchProviders : new Map();
}

const positive = (value, fallback) => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback);

/** SearXNG JSON results as the seam's sources: url required, deduplicated, in rank order. */
export function searxngResult(body) {
  const seen = new Set(), sources = [];
  for (const item of Array.isArray(body?.results) ? body.results : []) {
    if (typeof item?.url !== 'string' || !item.url || seen.has(item.url)) continue;
    seen.add(item.url);
    sources.push({ url: item.url,
      ...(typeof item.title === 'string' && item.title.trim() ? { title: item.title.trim() } : {}),
      ...(typeof item.content === 'string' && item.content.trim() ? { snippet: item.content.trim() } : {}),
      ...(typeof item.publishedDate === 'string' && item.publishedDate ? { publishedAt: item.publishedDate } : {}) });
  }
  const answers = (Array.isArray(body?.answers) ? body.answers : [])
    .map(answer => (typeof answer === 'string' ? answer : answer?.answer)).filter(text => typeof text === 'string' && text.trim());
  const blocked = (Array.isArray(body?.unresponsive_engines) ? body.unresponsive_engines : [])
    .map(entry => (Array.isArray(entry) ? String(entry[0]) : String(entry)));
  return { result: { ...(answers.length ? { content: answers.join('\n') } : {}), sources, truncated: false }, blocked };
}

export class OrderedSearch {
  id = SEARCH_PROVIDER_ID;

  /** settings(): the live `deployment.search`; registry(): providers on the seam; secret(ref): a credential value. */
  constructor({ settings, registry, secret, record = () => {}, now = Date.now, fetch = globalThis.fetch }) {
    Object.assign(this, { settings, registry, secret, record, now, fetch });
    this.searxngUntil = 0;
  }

  /** Selection is per call: a backend that cannot run is passed over then, so the seam always reaches this one. */
  available() { return true; }

  async search(request, signal) {
    const config = this.settings() ?? {};
    const order = Array.isArray(config.order) && config.order.length ? config.order : DEFAULT_ORDER;
    const route = [];
    let empty = null;
    for (const id of order) {
      signal?.throwIfAborted();
      let outcome;
      try {
        outcome = await this.step(id, config, request, signal);
      } catch (error) {
        if (signal?.aborted) throw error;
        outcome = { failed: String(error?.message ?? error).slice(0, 300) };
      }
      if (outcome.result?.sources.length) {
        this.record({ query: request.query, provider: id, route });
        return outcome.result;
      }
      if (outcome.result) { empty ??= outcome.result; route.push({ provider: id, outcome: 'no results' }); }
      else route.push({ provider: id, outcome: outcome.skipped ?? 'failed: ' + outcome.failed });
    }
    this.record({ query: request.query, provider: empty ? 'none (no results)' : null, route });
    if (empty) return empty;
    throw new WebError('web search is unavailable right now ('
      + route.map(step => step.provider + ': ' + step.outcome).join('; ') + ')', 'WEB_PROVIDER_UNAVAILABLE');
  }

  async step(id, config, request, signal) {
    if (id === 'searxng') return this.searxng(config.searxng ?? {}, request, signal);
    if (id === 'exa') return this.exa(config.exa ?? {}, request, signal);
    const provider = this.registry().get(id);
    if (!provider || provider === this) return { skipped: 'not installed' };
    if (!provider.available()) return { skipped: 'not configured' };
    return { result: await provider.search(request, signal) };
  }

  async searxng(options, request, signal) {
    if (typeof options.url !== 'string' || !options.url) return { skipped: 'not configured' };
    const now = this.now();
    if (now < this.searxngUntil) return { skipped: 'resting, ' + Math.ceil((this.searxngUntil - now) / 1000) + ' s left' };
    // Claimed before the request, so the other queries of one web_search call go to the next backend.
    this.searxngUntil = now + positive(options.cooldown_seconds, SEARXNG_DEFAULTS.cooldown_seconds) * 1000;
    const rest = () => { this.searxngUntil = this.now() + positive(options.rest_minutes, SEARXNG_DEFAULTS.rest_minutes) * 60_000; };
    const url = new URL(options.url);
    url.searchParams.set('q', request.query);
    url.searchParams.set('format', 'json');
    const engines = Array.isArray(options.engines) ? options.engines.filter(name => typeof name === 'string' && name) : [];
    if (engines.length) url.searchParams.set('engines', engines.join(','));
    const timeout = AbortSignal.timeout(positive(options.timeout_seconds, SEARXNG_DEFAULTS.timeout_seconds) * 1000);
    let body;
    try {
      const response = await this.fetch(url, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        redirect: 'error', headers: { accept: 'application/json' } });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      body = await response.json();
    } catch (error) {
      if (signal?.aborted) throw error;
      rest();
      throw error;
    }
    const { result, blocked } = searxngResult(body);
    // An empty answer from blocked engines means the instance is being turned away upstream: let it rest.
    if (!result.sources.length && blocked.length && (!engines.length || engines.every(name => blocked.includes(name)))) rest();
    return { result };
  }

  async exa(options, request, signal) {
    const ref = options.api_key?.$secret;
    const apiKey = typeof ref === 'string' ? await this.secret(ref) : undefined;
    if (!apiKey) return { skipped: 'no API key' };
    const provider = new ExaSearchProvider({ apiKey, baseURL: options.base_url || 'https://api.exa.ai',
      searchType: options.search_type || 'auto', highlightsPerResult: 1 });
    return { result: await provider.search(request, signal) };
  }
}

/** Registers the ordered provider on ctx.web for this plugin's lifetime. */
export function applySearch(ctx, core) {
  ctx.inject(['web'], child => {
    const search = new OrderedSearch({
      settings: () => core.config?.deployment?.search,
      registry: () => registered(child.web),
      secret: async ref => (await core.credentialStore()?.resolve(credentialRef(ref)))?.value,
      // Which backend answered, in the calling conversation's log (not model-facing).
      record: route => {
        try { ctx.get('agents')?.currentInitiator()?.session.append('asuna/web-search', route); } catch { /* no session */ }
      },
    });
    child.web.registerSearchProvider(search);
  });
}
