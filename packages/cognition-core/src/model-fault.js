/**
 * A model fault in her own output is corrected where it was made: in what she says, and in what her conversation
 * shows the model from then on.
 *
 * A model can leak its reasoning markup into the answer (`</think>`, `</next_thinking>`, the answer written again
 * around such a tag), or write the previous step's reasoning again word for word. Left in the conversation, every
 * later request shows the fault as her own earlier output and the model repeats it. So:
 * - Her text is read as the last segment between think-like tags (a closed think block is dropped first); that is
 *   what she says, and what the program reads from the stage (`cleanMessage`).
 * - Before each request of an Asuna session, every assistant message in the model's view is checked once; a faulty
 *   one gets an `asuna/model-fault` record whose message projection (DSH's registerMessageProjection, as
 *   `image/offload` does) shows the model the corrected texts, and no reasoning where it copied the previous
 *   message's. The session log keeps what the model wrote.
 */

const THINK_TAG = /<\/?\s*[a-z_]*think[a-z_]*\s*>/gi;
const HAS_THINK_TAG = /<\/?\s*[a-z_]*think[a-z_]*\s*>/i;
const THINK_BLOCK = /<\s*([a-z_]*think[a-z_]*)\s*>[\s\S]*?<\/\s*\1\s*>/gi;
// A reasoning shorter than this repeating the previous one is not a copy worth omitting.
const COPY_MIN = 20;
export const MODEL_FAULT = 'asuna/model-fault';

/** Her text without the model's reasoning markup: the last segment between think-like tags. */
export function cleanText(text) {
  if (!HAS_THINK_TAG.test(text)) return text;
  return text.replace(THINK_BLOCK, '\n').split(THINK_TAG).map(part => part.trim()).filter(Boolean).at(-1) ?? '';
}

/** The message with every text cleaned; the same object when nothing changed. */
export function cleanMessage(message) {
  const content = message?.content ?? [];
  if (!content.some(block => block.type === 'text' && HAS_THINK_TAG.test(block.text))) return message;
  return { ...message, content: content.map(block => block.type === 'text' ? { ...block, text: cleanText(block.text) } : block) };
}

const reasoningOf = message => (message?.content ?? []).filter(block => block.type === 'reasoning')
  .map(block => block.text).join('');

const checked = new WeakMap();

/**
 * Record one correction for the assistant messages of the session's model view that are faulty and not yet
 * corrected. Each message is read once per live session (its reasoning is kept to compare the next one).
 * @returns the corrected targets (none: nothing recorded).
 */
export function correctModelFaults(session) {
  const seen = checked.get(session) ?? new Map();
  checked.set(session, seen);
  const targets = [];
  let previous = '';
  for (const seq of session.surface.nodes) {
    const event = session.eventAt(seq);
    if (event?.type !== 'assistant/message') continue;
    const raw = event.data.message;
    if (!seen.has(seq)) {
      const reasoning = reasoningOf(raw);
      seen.set(seq, reasoning);
      if (session.deriveEventMessage(event) === raw) {             // not corrected before (a resumed session)
        const before = raw.content.filter(block => block.type === 'text').map(block => block.text);
        const texts = before.map(cleanText);
        const copied = reasoning.trim().length >= COPY_MIN && reasoning === previous;
        if (copied || texts.some((text, index) => text !== before[index]))
          targets.push({ seq, texts, ...(copied ? { reasoning: false } : {}) });
      }
    }
    previous = seen.get(seq);
  }
  if (targets.length) session.append(MODEL_FAULT, { targets });
  return targets;
}

const isSeq = value => Number.isSafeInteger(value) && value >= 0;

/** The pure replay of an `asuna/model-fault` record, for DSH's message projections. */
export const modelFaultProjection = {
  type: MODEL_FAULT,
  project(event, context) {
    const targets = event.data?.targets;
    if (!Array.isArray(targets) || !targets.length) throw new Error(MODEL_FAULT + ': data must contain a nonempty targets array');
    const nodes = new Set(context.nodes);
    const messages = new Map();
    for (const target of targets) {
      const { seq, texts, reasoning } = target ?? {};
      if (!isSeq(seq) || !nodes.has(seq) || messages.has(seq)) throw new Error(`${MODEL_FAULT}: target ${seq} is not a current surface node`);
      const source = context.events[seq - context.baseSeq];
      if (source?.type !== 'assistant/message') throw new Error(`${MODEL_FAULT}: target ${seq} must be assistant/message`);
      const message = context.messages.get(seq) ?? source.data.message;
      const count = message.content.filter(block => block.type === 'text').length;
      if (!Array.isArray(texts) || texts.length !== count || !texts.every(text => typeof text === 'string'))
        throw new Error(`${MODEL_FAULT}: target ${seq} needs one text for each of its ${count} text blocks`);
      if (reasoning !== undefined && reasoning !== false) throw new Error(`${MODEL_FAULT}: reasoning may only be false`);
      let index = 0;
      const content = message.content.map(block => Object.freeze(block.type === 'text' ? { ...block, text: texts[index++] }
        : block.type === 'reasoning' && reasoning === false ? { ...block, text: '' } : block));
      messages.set(seq, Object.freeze({ ...message, content: Object.freeze(content) }));
    }
    return messages;
  },
};
