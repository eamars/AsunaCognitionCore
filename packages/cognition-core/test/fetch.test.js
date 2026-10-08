import test from 'node:test';
import assert from 'node:assert/strict';
import { formatFetchOutput } from '@deepseek-ai/dsh-tool-web';
import { HttpFetchProvider } from '@deepseek-ai/dsh-web-fetch-http';
import { FETCH_LIMITS, FETCH_PROVIDER_ID, SlimFetch, isCloudflareChallenge, slimHtml } from '../src/fetch.js';

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

test('it is DSH\'s HTTP provider underneath, reading up to the 5 MB response limit', () => {
  const provider = new SlimFetch();
  assert.equal(provider.id, FETCH_PROVIDER_ID);
  assert.ok(provider.inner instanceof HttpFetchProvider);
  assert.equal(provider.available(), true);
  assert.equal(FETCH_LIMITS.maxBodyChars, FETCH_LIMITS.maxResponseBytes);
});
