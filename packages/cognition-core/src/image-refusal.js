/**
 * A model that refuses a picture must not end her turn, nor leave the conversation resending it (owner 2026-10-06).
 *
 * DSH renders a tool's picture once into the session log and rebuilds every request from that log, so a picture the
 * provider cannot take (e.g. a WebP its server cannot decode) fails this request and every later one in the same
 * conversation. When a request from one of Asuna's sessions is refused as invalid while the conversation still sends
 * pictures, every retained picture becomes DSH's own offload placeholder (an `image/offload` decision, the same event
 * and projection `@deepseek-ai/dsh-compaction-image-offload` records) and the request is tried once more. Pictures she
 * looks at later in that conversation are sent as usual. A refusal with no picture left to omit goes on as before.
 */

export const OWN_SESSION = /^asuna-/;
const INVALID = 'INVALID_REQUEST';

/**
 * Record one decision omitting every retained input picture of the session's current surface.
 * @returns how many pictures were omitted (0: none left, nothing recorded).
 */
export function offloadAllImages(session) {
  const targets = [];
  let omitted = 0;
  for (const seq of session.surface.nodes) {
    const event = session.eventAt(seq);
    if (!event || (event.type !== 'user/message' && event.type !== 'tool/result')) continue;
    const message = session.deriveEventMessage(event);
    if (!message) continue;
    const imageIndexes = [];
    let index = 0;
    const visit = (blocks) => {
      for (const block of blocks) {
        if (block.type === 'image') {
          if (block.offloaded !== true) imageIndexes.push(index);
          index += 1;
        } else if (block.type === 'tool-result') visit(block.content);
      }
    };
    visit(message.content);
    if (imageIndexes.length) {
      targets.push({ seq, imageIndexes });
      omitted += imageIndexes.length;
    }
  }
  if (targets.length) session.append('image/offload', { targets });
  return omitted;
}

/** The `agent/request-error` waterfall listener; `log(text)` notes what was done. */
export function imageRefusalListener(log = () => {}) {
  return ({ agent, failure }, next) => {
    const session = agent?.session;
    if (failure?.code !== INVALID || !OWN_SESSION.test(String(session?.id ?? ''))) return next();
    const omitted = offloadAllImages(session);
    if (!omitted) return next();
    log(`the model refused a request with pictures (${String(failure.message ?? '').slice(0, 160)}); `
      + `${omitted} picture(s) in ${session.id} are placeholders from now on, retrying once`);
    return Promise.resolve({ kind: 'retry' });
  };
}
