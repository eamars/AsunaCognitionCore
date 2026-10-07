/**
 * Reasoning markup in a conversation is kept from teaching the model a fault.
 *
 * A model server can take a think-like tag (`</think>`, `</next_thinking>`) written as text for the end of the
 * reasoning: a message mentioning one splits the reasoning there, and the answer comes back with the rest of the
 * reasoning, the tag, and often the answer again around it. A mention and a real boundary look the same in the
 * text, so the program never guesses which part is her answer:
 * - Her text that is one answer written again around such tags (each part the same, or a cut-off start of it) is
 *   read as that answer (`cleanMessage`); that is what she says and what the program reads from the stage.
 *   Any other text with such a tag is left as it is, and the end-of-turn check asks her to write it again.
 * - Before each request of an Asuna session, every message in the model's view is checked once, and one that needs
 *   it gets an `asuna/model-view` record, a DSH message projection (registerMessageProjection, as `image/offload`
 *   does): in her messages the model sees a repeated answer once, nothing of any other text with reasoning markup,
 *   and no reasoning where it copied the previous message's word for word; in every other message it sees each such
 *   tag, and each `<|…|>` control token, written with full-width brackets (`＜/think＞`), so a line quoting one cannot
 *   end her reasoning. The session log keeps what was written.
 */

const THINK_TAG = /<\/?\s*[a-z_]*think[a-z_]*\s*>/gi;
const HAS_THINK_TAG = /<\/?\s*[a-z_]*think[a-z_]*\s*>/i;
const CONTROL_TOKEN = /<(\|[^|<>\s]{1,40}\|)>/g;
// A reasoning shorter than this repeating the previous one is not a copy worth omitting.
const COPY_MIN = 20;
export const MODEL_VIEW = 'asuna/model-view';

/** True when the text carries a think-like tag. */
export const hasReasoningMarkup = text => HAS_THINK_TAG.test(text);

/** One answer written again around think-like tags, as that answer; any other text unchanged. */
export function cleanText(text) {
  if (!HAS_THINK_TAG.test(text)) return text;
  const parts = text.split(THINK_TAG).map(part => part.trim()).filter(Boolean);
  const answer = parts.reduce((longest, part) => part.length > longest.length ? part : longest, '');
  return parts.length > 1 && parts.every(part => answer.startsWith(part)) ? answer : text;
}

/** The message with every text cleaned; the same object when nothing changed. */
export function cleanMessage(message) {
  const content = message?.content ?? [];
  const cleaned = content.map(block => block.type === 'text' ? cleanText(block.text) : null);
  if (content.every((block, index) => block.type !== 'text' || cleaned[index] === block.text)) return message;
  return { ...message, content: content.map((block, index) => block.type === 'text' ? { ...block, text: cleaned[index] } : block) };
}

/** Think-like tags and control tokens written with full-width brackets. */
export const disarm = text => text.replace(THINK_TAG, tag => '＜' + tag.slice(1, -1) + '＞')
  .replace(CONTROL_TOKEN, (_, token) => '＜' + token + '＞');

const textsOf = message => (message?.content ?? []).filter(block => block.type === 'text').map(block => block.text);
const reasoningOf = message => (message?.content ?? []).filter(block => block.type === 'reasoning')
  .map(block => block.text).join('');
const messageOf = event => event.type === 'user/message' ? event.data : event.data.message;
const VIEWED = new Set(['assistant/message', 'user/message', 'tool/result']);

const checked = new WeakMap();

/** What the model should see of one of her messages instead (null: as it is). */
function herMessage(raw, copied) {
  const before = textsOf(raw);
  const texts = before.map(text => {
    const cleaned = cleanText(text);
    return hasReasoningMarkup(cleaned) ? '' : cleaned;
  });
  if (!copied && texts.every((text, index) => text === before[index])) return null;
  return { texts, ...(copied ? { reasoning: false } : {}) };
}

/**
 * Record one `asuna/model-view` decision for the messages of the session's model view that need one and have none.
 * Each message is read once per live session (her reasoning is kept to compare the next one).
 * @returns the recorded targets (none: nothing recorded).
 */
export function correctModelView(session) {
  const seen = checked.get(session) ?? new Map();
  checked.set(session, seen);
  const targets = [];
  let previous = '';
  for (const seq of session.surface.nodes) {
    const event = session.eventAt(seq);
    if (!VIEWED.has(event?.type)) continue;
    if (!seen.has(seq)) {
      const raw = messageOf(event);
      const derived = session.deriveEventMessage(event);
      const reasoning = reasoningOf(raw);
      seen.set(seq, reasoning);
      if (event.type === 'assistant/message') {
        const copied = reasoning.trim().length >= COPY_MIN && reasoning === previous;
        const view = derived === raw ? herMessage(raw, copied) : null;      // otherwise decided before
        if (view) targets.push({ seq, ...view });
      } else if (derived) {
        const before = textsOf(derived);
        const texts = before.map(disarm);
        if (texts.some((text, index) => text !== before[index])) targets.push({ seq, texts });
      }
    }
    if (event.type === 'assistant/message') previous = seen.get(seq);
  }
  if (targets.length) session.append(MODEL_VIEW, { targets });
  return targets;
}

const isSeq = value => Number.isSafeInteger(value) && value >= 0;

/** The pure replay of an `asuna/model-view` record, for DSH's message projections. */
export const modelViewProjection = {
  type: MODEL_VIEW,
  project(event, context) {
    const targets = event.data?.targets;
    if (!Array.isArray(targets) || !targets.length) throw new Error(MODEL_VIEW + ': data must contain a nonempty targets array');
    const nodes = new Set(context.nodes);
    const messages = new Map();
    for (const target of targets) {
      const { seq, texts, reasoning } = target ?? {};
      if (!isSeq(seq) || !nodes.has(seq) || messages.has(seq)) throw new Error(`${MODEL_VIEW}: target ${seq} is not a current surface node`);
      const source = context.events[seq - context.baseSeq];
      if (!VIEWED.has(source?.type)) throw new Error(`${MODEL_VIEW}: target ${seq} must be a user, assistant or tool message`);
      const message = context.messages.get(seq) ?? messageOf(source);
      const count = message.content.filter(block => block.type === 'text').length;
      if (!Array.isArray(texts) || texts.length !== count || !texts.every(text => typeof text === 'string'))
        throw new Error(`${MODEL_VIEW}: target ${seq} needs one text for each of its ${count} text blocks`);
      if (reasoning !== undefined && (reasoning !== false || source.type !== 'assistant/message'))
        throw new Error(`${MODEL_VIEW}: reasoning may only be false, on an assistant message`);
      let index = 0;
      const content = message.content.map(block => Object.freeze(block.type === 'text' ? { ...block, text: texts[index++] }
        : block.type === 'reasoning' && reasoning === false ? { ...block, text: '' } : block));
      messages.set(seq, Object.freeze({ ...message, content: Object.freeze(content) }));
    }
    return messages;
  },
};
