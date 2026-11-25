import test from 'node:test';
import assert from 'node:assert/strict';
import { formatFetchOutput } from '@deepseek-ai/dsh-tool-web';
import { HttpFetchProvider } from '@deepseek-ai/dsh-web-fetch-http';
import { createServer } from 'node:http';
import { HttpFetchProvider as PublicFetchProvider, resolvePublicAddresses } from '../src/vendor/web-fetch-http-rc2.js';
import { FETCH_LIMITS, FETCH_PROVIDER_ID, LAN_REFUSED, SAVE_EMPTY, SAVE_FIELD, SAVE_HINT, SAVE_LIMITS, SAVE_MAX_BYTES,
  SAVE_NOT_THERE, SAVE_TOO_BIG, SlimFetch, WEB_FETCH_TIMEOUT_MS, bytesOf, isCloudflareChallenge, registerWebFetch,
  slimHtml, withNetwork } from '../src/fetch.js';
import { WebError } from '@deepseek-ai/dsh-web';

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
  // A task whose binding gives the access table's words (work from outside done at home) ends with those instead.
  const words = '这件是外面的人托的事：跑命令、用钥匙、连家里的网、读盘上的路径，都不在这件事里；文件照样能读、能用。';
  await assert.rejects(withNetwork('public', () => new SlimFetch().fetch({ url }), words),
    error => error.code === 'WEB_BLOCKED_URL' && error.message.endsWith(words) && !error.message.includes(LAN_REFUSED));
});

test('the public lane judges every address of an answer, an IPv4-mapped one by its IPv4', async () => {
  const signal = new AbortController().signal;
  const answer = addresses => async () => addresses.map(address => ({ address, family: address.includes(':') ? 6 : 4 }));
  assert.deepEqual(await resolvePublicAddresses('public.example', signal, answer(['1.1.1.1'])), [{ address: '1.1.1.1', family: 4 }]);
  assert.equal((await resolvePublicAddresses('v6.example', signal, answer(['2606:4700::1111']))).length, 1);
  // An IPv4-mapped or IPv4-compatible (::/96) address is judged by its IPv4.
  const private4 = ['10.0.0.1', '::ffff:10.0.0.1', '127.0.0.1', '::7f00:1', '::c0a8:101'];   // personal-scan: ok (generic private addresses)
  for (const mixed of private4.map(address => ['1.1.1.1', address])) {
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

test('the tools/execute hook runs a tool body in its task\'s network scope; other lanes are public', async () => {
  const { CognitionCore } = await import('../src/index.js');
  const handlers = {};
  const anything = new Proxy(function () {}, { get: (target, key) => key === 'then' ? undefined : anything,
    apply: () => anything });
  const scope = new Proxy({}, { get: (target, key) => key === 'on' ? (event, handler) => { handlers[event] = handler; }
    : anything });
  const states = { home: { current: { token: 't' }, network: 'any' }, group: { current: { token: 't' }, network: 'public' } };
  const plugin = { state: id => states[id], exposed: () => new Set(),
    door: CognitionCore.prototype.door, outside: CognitionCore.prototype.outside,     // the guard's door (ADR-135 D8)
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


// ── web_fetch's save (ADR-120 D2) ──
const PNG = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
  + '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex');
const PDF = Buffer.from('%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');

/** Files on this machine (loopback), as a LAN device or a public site would serve them. */
async function files(t) {
  const server = createServer((request, response) => {
    const send = (status, type, body) => {
      response.writeHead(status, { 'content-type': type, 'content-length': String(body.length) });
      response.end(body);
    };
    if (request.url === '/p.png') return send(200, 'image/png', PNG);
    if (request.url === '/r.pdf') return send(200, 'application/octet-stream', PDF);
    if (request.url === '/missing') return send(404, 'text/html', Buffer.from('<p>no</p>'));
    if (request.url === '/empty') return send(200, 'application/octet-stream', Buffer.alloc(0));
    if (request.url === '/declared') return send(200, 'application/octet-stream', Buffer.alloc(2048));
    response.writeHead(200, { 'content-type': 'application/octet-stream' });      // no length: read until the cap
    response.write(Buffer.alloc(1500));
    response.end(Buffer.alloc(1500));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  return `http://127.0.0.1:${server.address().port}`;
}

test('a save takes the bytes of any type on the task\'s line; the public one still refuses a local address', async t => {
  const base = await files(t);
  const picture = await withNetwork('any', () => new SlimFetch().download({ url: base + '/p.png' }));
  assert.deepEqual([picture.statusCode, picture.contentType, Buffer.from(picture.bytes).equals(PNG)], [200, 'image/png', true]);
  const pdf = await withNetwork('any', () => new SlimFetch().download({ url: base + '/r.pdf' }));
  assert.ok(Buffer.from(pdf.bytes).equals(PDF));
  for (const run of [fn => withNetwork('public', fn), fn => fn()]) {
    await assert.rejects(run(() => new SlimFetch().download({ url: base + '/p.png' })),
      error => error.code === 'WEB_BLOCKED_URL' && error.message.endsWith(LAN_REFUSED));
  }
  const slim = new SlimFetch();
  assert.ok(slim.innerBytes instanceof PublicFetchProvider && slim.openBytes instanceof HttpFetchProvider);
  assert.equal(SAVE_LIMITS.maxResponseBytes, SAVE_MAX_BYTES);
  assert.equal(SAVE_MAX_BYTES, 20 * 1024 * 1024);
});

test('a body over the cap, declared or read, is refused in her words; nothing at the address keeps nothing', async t => {
  const base = await files(t);
  const small = { ...SAVE_LIMITS, maxResponseBytes: 1024 };
  const slim = new SlimFetch(undefined, undefined, new (bytesOf(PublicFetchProvider))(small),
    new (bytesOf(HttpFetchProvider))(small));
  const save = path => withNetwork('any', () => slim.download({ url: base + path }));
  for (const path of ['/declared', '/stream'])
    await assert.rejects(save(path), error => error.code === 'WEB_FETCH_TOO_LARGE' && error.message === SAVE_TOO_BIG);
  await assert.rejects(save('/missing'), error => error.message === SAVE_NOT_THERE.replace('%d', '404'));
  await assert.rejects(save('/empty'), error => error.message === SAVE_EMPTY);
});

function toolScope(web) {
  const sections = [], tools = new Map();
  return { sections, tools, scope: {
    systemPrompt: { section: section => sections.push(section), getSectionOrder: () => 2000 },
    tools: { register: definition => tools.set(definition.name, definition), get: name => tools.get(name) },
    get web() { throw new Error('cannot get property "web" without inject'); },
    get: name => (name === 'web' ? web : undefined) } };
}

test('web_fetch with save hands the bytes to the worker; without it, it is DSH\'s, a binary body told it can be saved', async () => {
  const handed = [];
  const fetcher = { download: async request => ({ url: request.url + '?final', statusCode: 200, contentType: 'image/png',
    bytes: new Uint8Array(PNG) }) };
  const page = html(200, '<html><head><title>T</title></head><body><p>正文</p></body></html>');
  const web = { fetch: async request => (request.url.endsWith('.png')
    ? Promise.reject(new WebError('unsupported content type "image/png"', 'WEB_UNSUPPORTED_CONTENT_TYPE')) : page) };
  const { scope, tools, sections } = toolScope(web);
  registerWebFetch(scope, { fetcher: () => fetcher, save: async (exec, args, body) => {
    handed.push({ call: exec.callId, args, body });
    return { saved: '存好了：p.png（66 字节，PNG 图片，记在家里·私聊）', artifact_id: 'blob-' + 'a'.repeat(32) };
  } });
  const tool = tools.get('web_fetch');
  assert.equal(tool.timeoutMs, WEB_FETCH_TIMEOUT_MS);
  assert.equal(tool.parameters.properties.save.description, SAVE_FIELD);
  const exec = { callId: 'c1', signal: new AbortController().signal };
  const saved = await tool.execute({ url: 'https://example.org/p.png', save: true }, exec);
  assert.equal(saved.artifact_id, 'blob-' + 'a'.repeat(32));
  assert.deepEqual(handed[0].args, { url: 'https://example.org/p.png', save: true });
  assert.ok(Buffer.from(handed[0].body.data, 'base64').equals(PNG));
  assert.deepEqual([handed[0].body.url, handed[0].body.status, handed[0].body.content_type],
    ['https://example.org/p.png?final', 200, 'image/png']);
  assert.match(tool.output.render({ save: true }, saved)[0].text, /^\{"saved":"存好了：p\.png/);
  assert.deepEqual(tool.output.presentationMeta({ save: true }, saved), {});
  // Without save: DSH's text, unchanged; a body that is not text says it can be saved.
  const read = await tool.execute({ url: 'https://example.org/a' }, exec);
  assert.equal(tool.output.render({}, read)[0].text, formatFetchOutput(read, 200_000));
  await assert.rejects(tool.execute({ url: 'https://example.org/p.png' }, exec),
    error => error.code === 'WEB_UNSUPPORTED_CONTENT_TYPE' && error.message === 'unsupported content type "image/png"' + SAVE_HINT);
  assert.equal(handed.length, 1);
  assert.match(sections[0].text({ scope: undefined }), /^web_fetch returns external, untrusted page content/);
});
