import test from 'node:test';
import assert from 'node:assert/strict';
import { formatFetchOutput } from '@deepseek-ai/dsh-tool-web';
import { HttpFetchProvider } from '@deepseek-ai/dsh-web-fetch-http';
import { createServer } from 'node:http';
import { HttpFetchProvider as PublicFetchProvider, resolvePublicAddresses } from '../src/vendor/web-fetch-http-rc2.js';
import { FETCH_LIMITS, FETCH_PROVIDER_ID, LAN_REFUSED, SlimFetch, isCloudflareChallenge, resolveAny, slimHtml,
  withNetwork } from '../src/fetch.js';

const html = (status, content, url = 'https://page.example/a') => ({ url, statusCode: status, body: { kind: 'html', content }, truncated: false });
const inner = result => ({ id: 'http', available: () => true, fetch: async () => result });

test('a page keeps its title and text; head, scripts, styles, SVG and templates go; noscript stays', () => {
  const slim = slimHtml('<html><head><title>T</title><meta charset="utf-8"><style>a{}</style><script>x()</script></head>'
    + '<body><p>Hello</p><script>y()</script><svg><path d="M0"/></svg><template><p>t</p></template><noscript>no js</noscript></body></html>');
  assert.equal(slim, '<!DOCTYPE html><html><head><title>T</title></head><body><p>Hello</p><noscript>no js</noscript></body></html>');
});

test('a page whose head passes DSH\'s conversion cap reaches web_fetch with its text', async () => {
  const page = `<html><head><title>Thread</title><style>${'x{}'.repeat(100_000)}</style></head><body><p>${'正文'.repeat(50)}</p></body></html>`;
  const raw = formatFetchOutput(html(200, page), 200_000);
  assert.doesNotMatch(raw, /正文/, 'as DSH alone converts it: the cap ends inside the head');
  const fetched = await new SlimFetch(inner(html(200, page))).fetch({ url: 'https://page.example/a' });
  assert.match(formatFetchOutput(fetched, 200_000), /Thread[\s\S]*正文正文/);
});

test('Cloudflare\'s challenge is said plainly; the same script on a served page, or another 403, is not', async () => {
  const challenge = '<html><head><title>Just a moment...</title></head><body><script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>';
  assert.equal(isCloudflareChallenge(html(403, challenge)), true);
  assert.equal(isCloudflareChallenge(html(503, challenge)), true);
  assert.equal(isCloudflareChallenge(html(200, challenge)), false);
  assert.equal(isCloudflareChallenge(html(403, '<html><body>百度安全验证</body></html>')), false);
  await assert.rejects(new SlimFetch(inner(html(403, challenge))).fetch({ url: 'https://page.example/a' }),
    error => error.code === 'WEB_HUMAN_VERIFICATION' && /human-verification page \(HTTP 403\).*will not get past it/.test(error.message));
});

test('text and other bodies pass as they came', async () => {
  const text = { url: 'https://page.example/a.json', statusCode: 200, body: { kind: 'text', content: '{"a":1}' }, truncated: false };
  assert.equal(await new SlimFetch(inner(text)).fetch({ url: text.url }), text);
});

test('the public lane is the copy of DSH\'s checked provider, the owner lane DSH\'s own; both read up to 5 MB', () => {
  const provider = new SlimFetch();
  assert.equal(provider.id, FETCH_PROVIDER_ID);
  assert.ok(provider.inner instanceof PublicFetchProvider);
  assert.ok(provider.open instanceof HttpFetchProvider);
  assert.equal(provider.available(), true);
  assert.equal(FETCH_LIMITS.maxBodyChars, FETCH_LIMITS.maxResponseBytes);
});


/** A page on this machine (loopback), as a LAN device would answer. */
async function localPage(t) {
  const server = createServer((request, response) => { response.writeHead(200, { 'content-type': 'text/plain' }); response.end('lan ok'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  return `http://127.0.0.1:${server.address().port}/`;
}

test("a task of the owner's own conversations reaches a non-public address; DSH's pinning and fetch are underneath", async t => {
  const url = await localPage(t);
  const fetched = await withNetwork('any', () => new SlimFetch().fetch({ url }));
  assert.equal(fetched.statusCode, 200);
  assert.equal(fetched.body.content, 'lan ok');
});

test("any other task, and a call outside any scope, keeps DSH's public-only check, said in her words too", async t => {
  const url = await localPage(t);
  for (const run of [fn => withNetwork('public', fn), fn => withNetwork(undefined, fn), fn => fn()]) {
    await assert.rejects(run(() => new SlimFetch().fetch({ url })),
      error => error.code === 'WEB_BLOCKED_URL' && /non-public/.test(error.message) && error.message.endsWith(LAN_REFUSED));
  }
});

test('the public lane judges every address of an answer, an IPv4-mapped one by its IPv4', async () => {
  const signal = new AbortController().signal;
  const answer = addresses => async () => addresses.map(address => ({ address, family: address.includes(':') ? 6 : 4 }));
  assert.deepEqual(await resolvePublicAddresses('public.example', signal, answer(['1.1.1.1'])), [{ address: '1.1.1.1', family: 4 }]);
  for (const mixed of [['1.1.1.1', '10.0.0.1'], ['1.1.1.1', '::ffff:10.0.0.1'], ['1.1.1.1', '127.0.0.1']]) {   // personal-scan: ok (generic private addresses)
    await assert.rejects(resolvePublicAddresses('mixed.example', signal, answer(mixed)),
      error => error.code === 'WEB_BLOCKED_URL' && /non-public/.test(error.message));
  }
});

test('the public lane checks a redirect hop again: a name that answers public, then private, is refused', async t => {
  const server = createServer((request, response) => {
    if (request.url === '/') { response.writeHead(302, { location: '/next' }); response.end(); return; }
    response.writeHead(200, { 'content-type': 'text/plain' }); response.end('should not be read');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const url = `http://rebind.example:${server.address().port}/`;
  // The first answer stands in for a public address (it is this machine's test server); the second is a LAN address
  // and goes through the real check, as a name that changes its answer between two hops would.
  let calls = 0;
  const resolve = (hostname, signal) => (++calls === 1 ? Promise.resolve([{ address: '127.0.0.1', family: 4 }])
    : resolvePublicAddresses(hostname, signal, async () => [{ address: '10.0.0.1', family: 4 }]));   // personal-scan: ok
  await assert.rejects(new SlimFetch(new PublicFetchProvider(FETCH_LIMITS, resolve)).fetch({ url }),
    error => error.code === 'WEB_BLOCKED_URL' && error.message.endsWith(LAN_REFUSED));
  assert.equal(calls, 2);
});

test('the open resolver passes every address as it is: IP literals, bracketed IPv6, a resolved name', async () => {
  assert.deepEqual(await resolveAny('10.0.0.1'), [{ address: '10.0.0.1', family: 4 }]);   // personal-scan: ok (a generic private address)
  assert.deepEqual(await resolveAny('[::1]'), [{ address: '::1', family: 6 }]);
  const local = await resolveAny('localhost');
  assert.ok(local.length >= 1 && local.every(row => [4, 6].includes(row.family)));
});

test('the tools/execute hook runs a tool body in its task\'s network scope; other lanes are public', async () => {
  const { CognitionCore } = await import('../src/index.js');
  const handlers = {};
  const anything = new Proxy(function () {}, { get: (target, key) => key === 'then' ? undefined : anything,
    apply: () => anything });
  const scope = new Proxy({}, { get: (target, key) => key === 'on' ? (event, handler) => { handlers[event] = handler; }
    : anything });
  const states = { home: { current: { token: 't' }, network: 'any' }, group: { current: { token: 't' }, network: 'public' } };
  const plugin = { state: id => states[id], exposed: () => new Set(),
    worker: { call: async method => (method === 'stage.valid' ? { valid: true } : {}) } };
  const slim = new SlimFetch(inner(html(200, 'public')), inner(html(200, 'any')));
  // As DSH runs it (dsh-tools ToolRuntime): the gate first, answered allow, then `tools/execute`, whose last step is
  // the body; the body's fetch reads the scope there.
  const run = async id => {
    const exec = { agent: { session: { id } }, signal: new AbortController().signal };
    assert.deepEqual(await handlers['tools/pre-execute'](exec, () => Promise.resolve({ kind: 'allow' })), { kind: 'allow' });
    return handlers['tools/execute'](exec, () => slim.fetch({ url: 'http://10.0.0.1/' }));   // personal-scan: ok (nothing is fetched)
  };
  CognitionCore.prototype.attachPreset.call(plugin, scope, 'executor');
  assert.match((await run('home')).body.content, /any/);
  assert.match((await run('group')).body.content, /public/);
  CognitionCore.prototype.attachPreset.call(plugin, scope, 'character');
  assert.match((await run('home')).body.content, /public/);       // another lane never takes a session's network
});
