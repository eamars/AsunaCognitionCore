/** Her web_fetch, underneath (ADR-026 §6): one fetch provider on DSH's web seam. An HTTP provider retrieves
 * the page, with its address checks, pinning and redirect rules, reading up to its 5 MB response limit instead of
 * the first 100,000 characters; an HTML page then loses what is not its content before DSH's web_fetch converts it:
 * the head (its title kept), scripts, styles, SVG and templates. A page whose head alone passed 100,000 characters
 * used to reach her as its title only.
 *
 * A Cloudflare human-verification page (HTTP 403 or 503 that loads Cloudflare's challenge platform) is said plainly
 * as an error: another route will not get past it. No other site or wording is recognised.
 *
 * Where a fetch may go (ADR-116): a call made for an action task whose origin the access table allows the owner's own
 * network (the worker's access.py, home by default) runs in the scope `any` (index.js sets it per tool call from the
 * task's binding) and reaches every address, the LAN and this machine included, through DSH's own provider, which
 * checks none; every other call, and one outside
 * any scope, goes through the public-only provider in vendor/web-fetch-http-rc2.js: DSH's own check as DSH 0.2.1-rc.2
 * ships it, kept by Asuna since later DSH drops it (ADR-116 §7). Pinning and the same-origin redirect rule hold in
 * both. */
import { AsyncLocalStorage } from 'node:async_hooks';
import domino from '@mixmark-io/domino';
import { WebError } from '@deepseek-ai/dsh-web';
import { DEFAULT_USER_AGENT, HttpFetchProvider } from '@deepseek-ai/dsh-web-fetch-http';
import { HttpFetchProvider as PublicFetchProvider } from './vendor/web-fetch-http-rc2.js';

export const FETCH_PROVIDER_ID = 'asuna-fetch';
export const FETCH_LIMITS = { maxResponseBytes: 5_000_000, maxBodyChars: 5_000_000, timeoutMs: 30_000, maxRedirects: 5,
  userAgent: DEFAULT_USER_AGENT };
const NOT_CONTENT = 'script, style, svg, template';
/** The network of the action task this call is made for: { scope: 'any' or 'public', refused: words } (none: public). */
const NETWORK = new AsyncLocalStorage();
/** What a public-only task is told when its address is on the local network or this machine, after DSH's line, unless
 * its binding gives its own words (the access table's, for a task that is not an outside one). */
export const LAN_REFUSED = '这个地址在局域网或本机上；这件任务不是在主人自己的对话里交的，只能上公网。';

/** Run `fn` as a call of a task whose network is `network` (anything but 'any' is public); `refused`: the words a
 * local address is refused with, LAN_REFUSED when none are given. */
export function withNetwork(network, fn, refused) {
  return NETWORK.run({ scope: network === 'any' ? 'any' : 'public',
    refused: typeof refused === 'string' && refused ? refused : LAN_REFUSED }, fn);
}

const CHALLENGE_PLATFORM = '/cdn-cgi/challenge-platform/';

/** The page without what is not its content: the head reduced to its title, no scripts, styles, SVG or templates. */
export function slimHtml(html) {
  const document = domino.createDocument(html);
  for (const node of [...(document.head?.childNodes ?? [])]) if (node.nodeName !== 'TITLE') node.remove();
  for (const node of [...document.querySelectorAll(NOT_CONTENT)]) node.remove();
  return '<!DOCTYPE html>' + document.documentElement.outerHTML;
}

/** Cloudflare's challenge: it answers 403 or 503 and loads its challenge platform. (A served page may load the same
 * platform with 200, so the status is part of the test.) */
export function isCloudflareChallenge(result) {
  return [403, 503].includes(result.statusCode) && result.body?.kind === 'html' && result.body.content.includes(CHALLENGE_PLATFORM);
}

export class SlimFetch {
  id = FETCH_PROVIDER_ID;

  constructor(inner = new PublicFetchProvider(FETCH_LIMITS), open = new HttpFetchProvider(FETCH_LIMITS)) {
    this.inner = inner;
    this.open = open;
  }

  available() { return this.inner.available(); }

  async fetch(request, signal) {
    const scope = NETWORK.getStore();
    const any = scope?.scope === 'any';
    let result;
    try {
      result = await (any ? this.open : this.inner).fetch(request, signal);
    } catch (error) {
      if (!any && error?.code === 'WEB_BLOCKED_URL' && /non-public/.test(String(error.message)))
        throw new WebError(`${error.message} ${scope?.refused ?? LAN_REFUSED}`, 'WEB_BLOCKED_URL', { cause: error });
      throw error;
    }
    if (result.body?.kind !== 'html') return result;
    if (isCloudflareChallenge(result))
      throw new WebError(`${result.url} answered with Cloudflare's human-verification page (HTTP ${result.statusCode}); `
        + 'fetching it again, through a proxy or another reader will not get past it. Use the search snippet or another source.',
      'WEB_HUMAN_VERIFICATION');
    return { ...result, body: { kind: 'html', content: slimHtml(result.body.content) } };
  }
}

/** Registers the fetch provider on ctx.web for this plugin's lifetime; the profile pins it. */
export function applyFetch(ctx) {
  ctx.inject(['web'], child => { child.web.registerFetchProvider(new SlimFetch()); });
}
