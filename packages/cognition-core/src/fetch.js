/** Her web_fetch, underneath (ADR-026 §6): one fetch provider on DSH's web seam. DSH's own HTTP provider retrieves
 * the page, with its address checks, pinning and redirect rules, reading up to its 5 MB response limit instead of
 * the first 100,000 characters; an HTML page then loses what is not its content before DSH's web_fetch converts it:
 * the head (its title kept), scripts, styles, SVG and templates. A page whose head alone passed 100,000 characters
 * used to reach her as its title only.
 *
 * A Cloudflare human-verification page (HTTP 403 or 503 that loads Cloudflare's challenge platform) is said plainly
 * as an error: another route will not get past it. No other site or wording is recognised. */
import domino from '@mixmark-io/domino';
import { WebError } from '@deepseek-ai/dsh-web';
import { DEFAULT_USER_AGENT, HttpFetchProvider } from '@deepseek-ai/dsh-web-fetch-http';

export const FETCH_PROVIDER_ID = 'asuna-fetch';
export const FETCH_LIMITS = { maxResponseBytes: 5_000_000, maxBodyChars: 5_000_000, timeoutMs: 30_000, maxRedirects: 5,
  userAgent: DEFAULT_USER_AGENT };
const NOT_CONTENT = 'script, style, svg, template';
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

  constructor(inner = new HttpFetchProvider(FETCH_LIMITS)) { this.inner = inner; }

  available() { return this.inner.available(); }

  async fetch(request, signal) {
    const result = await this.inner.fetch(request, signal);
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
