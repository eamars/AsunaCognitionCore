/** ADR-075: her action brain's two routes. A job she sent to 高 runs on `routes.actionHigh` until a request there ends
 * in an error DSH's own retries could not cure; then the job falls to the action route for good. What the failure
 * was decides whether 高 rests: a failure of the line rests it for 高's own idle minutes (its cache is gone by then
 * anyway), one that waits on the owner (key, credential, quota) rests it with no clock, and a refusal of this job's
 * content does not rest it at all. Routing goes by DSH's failure codes, never by parsing a message. */

const CLASSES = {
  AUTH: 'owner', QUOTA: 'owner', ACCOUNT_QUOTA: 'owner', INVALID_CREDENTIAL: 'owner', MISSING_CREDENTIAL: 'owner',
  RATE_LIMIT: 'busy',
  SERVER: 'down', TIMEOUT: 'down', TRANSPORT: 'down', STREAM_CLOSED: 'down',
};
// Not a failure of 高: a stop by her or the owner, and a context DSH's compaction handles.
const NOT_FALLS = new Set(['ABORTED', 'CONTEXT_WINDOW_EXCEEDED']);

/** What a failure on 高 was: 'owner', 'busy', 'down', 'refused' (anything else that ended the request), or null. */
export function failureClass(code) {
  if (NOT_FALLS.has(code)) return null;
  return CLASSES[code] ?? 'refused';
}

/** The rest a failure starts: null for a refusal; no clock when it waits on the owner. */
export function restFor(kind, idleMinutes, now = Date.now()) {
  if (!kind || kind === 'refused') return null;
  return { reason: kind, until: kind === 'owner' ? null : new Date(now + (idleMinutes || 30) * 60000).toISOString() };
}

/** Whether 高 is resting now. */
export function resting(rest, now = Date.now()) {
  return Boolean(rest) && (!rest.until || Date.parse(rest.until) > now);
}
