import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import WebRuntime from '@deepseek-ai/dsh-web';
import { OrderedSearch, registered, searxngResult, SEARCH_PROVIDER_ID } from '../src/search.js';

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
