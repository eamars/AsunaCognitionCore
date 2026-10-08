import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import WebRuntime from '@deepseek-ai/dsh-web';
import { OrderedSearch, registered, registerWebSearch, localStamp, searxngResult, geminiRetryAt, nextPacificMidnight, SEARCH_PROVIDER_ID } from '../src/search.js';

const SEARX = { url: 'http://searx.invalid:8080/search', engines: ['bing', 'yandex'], cooldown_seconds: 30, rest_minutes: 15 };
const page = (results, unresponsive = []) => ({ results, answers: [], unresponsive_engines: unresponsive });
const hit = url => ({ url, title: 'T ' + url, content: 'snippet', engines: ['bing'] });

function harness({ search = { order: ['searxng', 'exa', 'deepseek-official'], searxng: SEARX }, bodies = [], secrets = {} } = {}) {
  let clock = 1_000_000;
  const asked = [], fallback = [], routes = [];
  const deepseek = { id: 'deepseek-official', available: () => true,
    search: async request => { fallback.push(request.query); return { sources: [{ url: 'https://paid.example/' + request.query }], truncated: false }; } };
  const provider = new OrderedSearch({
    settings: () => search, registry: () => new Map([['deepseek-official', deepseek]]),
    secret: async ref => secrets[ref], record: route => routes.push(route), now: () => clock,
    fetch: async url => {
      asked.push(url);
      const body = bodies.shift();
      if (body instanceof Error) throw body;
      return { ok: true, status: 200, json: async () => body };
    },
  });
  return { provider, asked, fallback, routes, advance: seconds => { clock += seconds * 1000; } };
}

test('SearXNG answers first, with the configured engines; within its cooldown the next query goes on', async () => {
  const h = harness({ bodies: [page([hit('https://a.example/1'), hit('https://a.example/1'), hit('https://a.example/2')])] });
  const first = await h.provider.search({ query: 'one', maxResults: 8 });
  assert.deepEqual(first.sources.map(source => source.url), ['https://a.example/1', 'https://a.example/2']);
  assert.equal(first.sources[0].snippet, 'snippet');
  const url = new URL(h.asked[0]);
  assert.equal(url.searchParams.get('format'), 'json');
  assert.equal(url.searchParams.get('engines'), 'bing,yandex');
  const second = await h.provider.search({ query: 'two' });
  assert.equal(second.sources[0].url, 'https://paid.example/two');
  assert.equal(h.asked.length, 1, 'no second SearXNG request inside 30 s');
  assert.match(h.routes[1].route[0].outcome, /^resting, 30 s left/);
  assert.match(h.routes[1].route[1].outcome, /no API key/);
  h.advance(30);
  await h.provider.search({ query: 'three' });
  assert.equal(h.asked.length, 2, 'after the cooldown SearXNG is asked again');
});

test('concurrent queries of one call: one goes to SearXNG, the others to the next backend', async () => {
  const h = harness({ bodies: [page([hit('https://a.example/1')])] });
  const results = await Promise.all(['a', 'b', 'c'].map(query => h.provider.search({ query })));
  assert.equal(h.asked.length, 1);
  assert.deepEqual(h.fallback, ['b', 'c']);
  assert.equal(results[0].sources[0].url, 'https://a.example/1');
});

test('an empty answer from blocked engines falls through and rests SearXNG; a failure does too', async () => {
  const h = harness({ bodies: [page([], [['bing', 'CAPTCHA'], ['yandex', 'access denied']]), new Error('connect ECONNREFUSED')] });
  const blocked = await h.provider.search({ query: 'one' });
  assert.equal(blocked.sources[0].url, 'https://paid.example/one');
  assert.equal(h.routes[0].route[0].outcome, 'no results');
  h.advance(60);
  await h.provider.search({ query: 'two' });
  assert.equal(h.asked.length, 1, 'resting 15 min, not 30 s');
  h.advance(15 * 60);
  await h.provider.search({ query: 'three' });
  assert.equal(h.asked.length, 2);
  assert.match(h.routes.at(-1).route[0].outcome, /^failed: connect ECONNREFUSED/);
  h.advance(60);
  await h.provider.search({ query: 'four' });
  assert.equal(h.asked.length, 2, 'a failure rests it as well');
});

test('an empty answer with a working engine is a miss, not a rest', async () => {
  const h = harness({ bodies: [page([], [['bing', 'CAPTCHA']])] });
  await h.provider.search({ query: 'obscure' });
  h.advance(30);
  assert.ok(h.provider.searxngUntil <= 1_000_000 + 30_000, 'only the ordinary cooldown');
});

test('nothing configured but an empty answer: that answer is the result; nothing at all: a WebError naming each step', async () => {
  const empty = harness({ search: { order: ['searxng'], searxng: SEARX }, bodies: [page([])] });
  assert.deepEqual((await empty.provider.search({ query: 'x' })).sources, []);
  const none = harness({ search: { order: ['searxng', 'exa', 'missing'] } });
  await assert.rejects(none.provider.search({ query: 'x' }), error => error.code === 'WEB_PROVIDER_UNAVAILABLE'
    && /searxng: not configured; exa: no API key; missing: not installed/.test(error.message));
});

test('no search settings keep the shipped DeepSeek search', async () => {
  const h = harness({ search: null });
  assert.equal((await h.provider.search({ query: 'q' })).sources[0].url, 'https://paid.example/q');
  assert.equal(h.asked.length, 0);
});

test('a cancelled call stops instead of falling through', async () => {
  const controller = new AbortController();
  const h = harness();
  h.provider.fetch = async (url, { signal }) => { controller.abort(); signal.throwIfAborted(); };
  await assert.rejects(h.provider.search({ query: 'q' }, controller.signal));
  assert.deepEqual(h.fallback, []);
});

test('Exa runs through DSH\'s provider with the referenced credential', async t => {
  const h = harness({ search: { order: ['exa'], exa: { api_key: { $secret: 'EXA_API_KEY' } } }, secrets: { EXA_API_KEY: 'k' } });
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  let headers;
  globalThis.fetch = async (url, init) => { headers = init.headers;
    return new Response(JSON.stringify({ results: [{ url: 'https://exa.example/1', title: 'E', highlights: ['h'] }] }), { status: 200 }); };
  const result = await h.provider.search({ query: 'q', maxResults: 4 });
  assert.equal(result.sources[0].url, 'https://exa.example/1');
  assert.equal(new Headers(headers).get('authorization'), 'Bearer k');
});

test('SearXNG answers and dates map to the seam', () => {
  const { result, blocked } = searxngResult({ results: [{ url: 'https://d.example', title: ' D ', content: '', publishedDate: '2026-10-01T00:00:00' }],
    answers: [{ answer: '42' }, 'forty-two'], unresponsive_engines: [['google', 'access denied']] });
  assert.deepEqual(result, { content: '42\nforty-two', sources: [{ url: 'https://d.example', title: 'D', publishedAt: '2026-10-01T00:00:00' }], truncated: false });
  assert.deepEqual(blocked, ['google']);
});

test('the pinned dsh-web keeps its search providers where registered() reads them', t => {
  const ctx = new Context();
  t.after(() => ctx.fiber.dispose());
  const web = new WebRuntime(ctx, { searchProvider: SEARCH_PROVIDER_ID });
  const provider = { id: 'deepseek-official', available: () => true, search: async () => ({ sources: [], truncated: false }) };
  web.registerSearchProvider(provider);
  assert.equal(registered(web).get('deepseek-official'), provider);
});

const grounded = (...chunks) => ({ candidates: [{ content: { parts: [{ text: 'Gemini says…' }] },
  groundingMetadata: { groundingChunks: chunks.map(([uri, title]) => ({ web: { uri, title } })) } }] });
const REDIRECT = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/';

function geminiHarness(replies, { order = ['gemini', 'deepseek-official'] } = {}) {
  const h = harness({ search: { order, gemini: { api_key: { $secret: 'GEMINI_API_KEY' } } }, secrets: { GEMINI_API_KEY: 'g' } });
  const calls = [];
  h.provider.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    if (init.method === 'HEAD') {
      const target = { [REDIRECT + 'a']: 'https://page.example/a', [REDIRECT + 'b']: 'https://page.example/a' }[url];
      if (!target) throw new Error('unreachable');
      return { status: 302, headers: new Headers({ location: target }) };
    }
    const [status, body] = replies.shift();
    return { ok: status === 200, status, json: async () => body };
  };
  return { ...h, calls };
}

test('Gemini: its cited pages are the sources, redirects resolved, its own answer dropped', async () => {
  const h = geminiHarness([[200, grounded([REDIRECT + 'a', 'page.example'], [REDIRECT + 'b', 'dup'], [REDIRECT + 'c', 'other.example'])]]);
  const result = await h.provider.search({ query: 'q' });
  assert.deepEqual(result, { sources: [{ url: 'https://page.example/a', title: 'page.example' },
    { url: REDIRECT + 'c', title: 'other.example' }], truncated: false }, 'deduplicated after resolving; an unresolved link kept');
  const request = h.calls[0];
  assert.match(request.url, /\/models\/gemini-3\.5-flash-lite:generateContent$/);
  assert.equal(request.init.headers['x-goog-api-key'], 'g');
  assert.deepEqual(JSON.parse(request.init.body).tools, [{ google_search: {} }]);
});

test('Gemini: no grounding falls through; no key is skipped', async () => {
  const h = geminiHarness([[200, { candidates: [{ content: { parts: [{ text: 'no search' }] } }] }]]);
  assert.equal((await h.provider.search({ query: 'q' })).sources[0].url, 'https://paid.example/q');
  const none = harness({ search: { order: ['gemini'] } });
  await assert.rejects(none.provider.search({ query: 'q' }), /gemini: no API key/);
});

test('Gemini: a 429 on a daily quota rests it until midnight Pacific; a per-minute one for its retry delay', async () => {
  const daily = { error: { code: 429, message: 'quota', details: [
    { '@type': 'type.googleapis.com/google.rpc.QuotaFailure', violations: [{ quotaId: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' }] },
    { '@type': 'type.googleapis.com/google.rpc.RetryInfo', retryDelay: '23s' }] } };
  const h = geminiHarness([[429, daily]]);
  const now = Date.UTC(2026, 9, 8, 20, 0);            // 13:00 Pacific daylight time
  h.provider.now = () => now;
  assert.equal((await h.provider.search({ query: 'one' })).sources[0].url, 'https://paid.example/one');
  assert.equal(h.provider.geminiUntil, Date.UTC(2026, 9, 9, 7, 0));
  await h.provider.search({ query: 'two' });
  assert.equal(h.calls.length, 1, 'resting');
  assert.match(h.routes[1].route[0].outcome, /^rate limited, 660 min left/);
  const minute = { error: { code: 429, details: [{ violations: [{ quotaId: 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier' }] },
    { retryDelay: '23.5s' }] } };
  assert.equal(geminiRetryAt(minute, now), now + 24_000);
  assert.equal(geminiRetryAt({}, now), now + 60_000);
});

test('midnight Pacific across both daylight-saving changes', () => {
  assert.equal(nextPacificMidnight(Date.UTC(2026, 10, 1, 8, 0)), Date.UTC(2026, 10, 2, 8, 0));   // 25-hour day
  assert.equal(nextPacificMidnight(Date.UTC(2027, 2, 14, 12, 0)), Date.UTC(2027, 2, 15, 7, 0));  // 23-hour day
});

function toolScope(search) {
  const sections = [], tools = new Map();
  return { sections, tools, scope: {
    systemPrompt: { section: section => sections.push(section), getSectionOrder: () => 2000 },
    tools: { register: definition => tools.set(definition.name, definition), get: name => tools.get(name) },
    web: { search } } };
}
const many = (prefix, n) => ({ sources: Array.from({ length: n }, (_, i) => ({ url: `https://${prefix}.example/${i}`, title: `${prefix} ${i}`,
  snippet: 'about ' + prefix, publishedAt: '2026-10-01' })), truncated: false });

test('web_search: DSH\'s output, 10 sources merged round-robin, and titles without snippets', async () => {
  const asked = [];
  const { scope, tools, sections } = toolScope(async request => { asked.push(request); return many(request.query, 8); });
  registerWebSearch(scope);
  const tool = tools.get('web_search');
  const full = await tool.execute({ queries: ['a', 'b', 'a'] }, { signal: new AbortController().signal });
  assert.deepEqual(asked.map(request => [request.query, request.maxResults]), [['a', 10], ['b', 10]]);
  assert.equal(full.sources.length, 10);
  assert.deepEqual(full.sources.slice(0, 3).map(source => source.url), ['https://a.example/0', 'https://b.example/0', 'https://a.example/1']);
  assert.equal(full.truncated, true);
  const text = tool.output.render({}, full)[0].text;
  assert.match(text, /^External web content follows/);
  assert.match(text, /- \[a 0\]\(https:\/\/a\.example\/0\) — about a \(2026-10-01\)/);
  const titles = await tool.execute({ queries: ['a'], detail: 'titles' }, { signal: new AbortController().signal });
  assert.ok(titles.sources.every(source => source.snippet === undefined && source.title && source.publishedAt));
  assert.match(tool.output.render({}, titles)[0].text, /- \[a 0\]\(https:\/\/a\.example\/0\) — \(2026-10-01\)\n/);
  assert.match(sections[0].text({ scope: undefined }), /Use the returned source snippets/, 'no web_fetch registered here');
});

test('web_search: DSH\'s argument errors, and the first failing query fails the call', async () => {
  const { scope, tools } = toolScope(async (request, signal) => {
    if (request.query === 'bad') throw new Error('backend down');
    await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
  });
  registerWebSearch(scope);
  const tool = tools.get('web_search');
  await assert.rejects(tool.execute({ queries: [] }, { signal: new AbortController().signal }), /at least one query/);
  await assert.rejects(tool.execute({ queries: ['a', 'b', 'c', 'd', 'e'] }, { signal: new AbortController().signal }), /at most 4 queries/);
  await assert.rejects(tool.execute({ queries: ['slow', 'bad'] }, { signal: new AbortController().signal }), /backend down/);
});

test('every backend\'s snippets are capped (300 characters by default)', async () => {
  const h = harness({ search: { order: ['deepseek-official'] } });
  h.provider.registry = () => new Map([['deepseek-official', { id: 'deepseek-official', available: () => true,
    search: async () => ({ sources: [{ url: 'https://x.example', snippet: 'x'.repeat(1000) }, { url: 'https://y.example', snippet: 'short' }], truncated: false }) }]]);
  const result = await h.provider.search({ query: 'q' });
  assert.equal(result.sources[0].snippet, 'x'.repeat(300) + '…');
  assert.equal(result.sources[1].snippet, 'short');
  h.provider.settings = () => ({ order: ['deepseek-official'], snippet_chars: 50 });
  assert.equal((await h.provider.search({ query: 'q' })).sources[0].snippet.length, 51);
});

test('web_search puts publication times on the conversation\'s clock; a date alone stays', async () => {
  const zone = { timezone: 'Pacific/Auckland', utc_offset_minutes: 780 };
  assert.equal(localStamp('2026-03-30T20:03:39.000Z', zone), '2026-03-31 09:03', 'daylight time, +13');
  assert.equal(localStamp('2026-06-03T10:52:34Z', zone), '2026-06-03 22:52', 'standard time, +12');
  assert.equal(localStamp('2026-10-01T00:00:00', zone), '2026-10-01 13:00', 'no offset: UTC');
  assert.equal(localStamp('2026-10-01', zone), '2026-10-01');
  assert.equal(localStamp('2026-10-01T00:00:00Z', { timezone: 'Not/AZone', utc_offset_minutes: 780 }), '2026-10-01 13:00');
  const { scope, tools } = toolScope(async () => ({ sources: [{ url: 'https://d.example', publishedAt: '2026-03-30T20:03:39.000Z' }], truncated: false }));
  registerWebSearch(scope, { zone });
  const value = await tools.get('web_search').execute({ queries: ['q'], detail: 'titles' }, { signal: new AbortController().signal });
  assert.equal(value.sources[0].publishedAt, '2026-03-31 09:03');
  assert.doesNotMatch(tools.get('web_search').output.render({}, value)[0].text, /\d{2}:\d{2}:\d{2}(\.\d+)?Z/);
});
