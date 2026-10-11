/** Per-turn context delivery for the character brain: of the whole context the worker prepares every turn, only
 * what her session does not still show is sent.
 *
 * A block, history row or memory is left out, and so is one of her own thoughts (a recalled one, or one of her
 * recent thoughts) whose `think` call the session still shows, only while an identical copy sits inside the newest REUSE_WINDOW_TOKENS
 * of the session surface. That stretch is inside DSH's retained tail, so any
 * compaction, including one that runs right before this message joins the
 * surface, keeps it verbatim. Anything older is sent again. Each notice records
 * what it carries in its own `source.carried`, so the session log is the only
 * state; nothing is cached in the worker or Mongo. */
import { createHash } from 'node:crypto';

/** Must stay below the role preset's retained tail (DSH chars/4 estimate):
 * (262144 − 32768) × retainRatio 0.16 ≈ 36.7K. */
export const REUSE_WINDOW_TOKENS = 32768;
/** Orientation and the turn's trigger are always sent. */
const ALWAYS = new Set(['scene', 'speaker', 'session_class', 'event']);
const HEAD = ['scene', 'speaker', 'session_class'];

const digest = value => createHash('sha256').update(JSON.stringify(value ?? null)).digest('hex').slice(0, 16);

/** What the newest stretch of the surface already carries (DSH's chars/4 token estimate). Lines still
 * waiting in the inbox (navigation.js) count too: the same step claims them just before this notice. */
export function visibleCarried(session, pending = [], windowTokens = REUSE_WINDOW_TOKENS) {
  const visible = { blocks: new Set(), rows: new Set(), memories: new Set(), episodes: new Set(), thoughts: new Set() };
  const nodes = session.surface.nodes;
  let used = 0;
  for (const line of pending.toReversed()) {
    used += Math.ceil(JSON.stringify(line.content).length / 4);
    if (used > windowTokens) return visible;
    if (line.source?.channel && line.source.receipt) visible.rows.add(line.source.receipt);
  }
  for (let index = nodes.length - 1; index >= 0; index--) {
    const event = session.eventAt(nodes[index]);
    if (!event) continue;
    const content = session.deriveEventMessage(event)?.content ?? '';
    used += Math.ceil(JSON.stringify(content).length / 4);
    if (used > windowTokens) break;
    // Her own thought, as she wrote it with `think` (its call id ends the stored thought's id).
    if (Array.isArray(content)) for (const block of content)
      if (block?.type === 'tool-call' && block.name === 'think' && block.id) visible.thoughts.add(block.id);
    const source = event.type === 'user/message' ? event.data?.source : undefined;
    // A platform line projected into the conversation as it arrived (navigation.js) is its own row.
    if (source?.kind === 'user' && source.channel && source.receipt) { visible.rows.add(source.receipt); continue; }
    const carried = source?.kind === 'asuna' ? source.carried : undefined;
    if (!carried) continue;
    for (const [key, value] of Object.entries(carried.blocks ?? {})) visible.blocks.add(key + ':' + value);
    for (const id of carried.rows ?? []) visible.rows.add(id);
    for (const id of carried.memories ?? []) visible.memories.add(id);
    if (carried.episode) visible.episodes.add(carried.episode);
  }
  return visible;
}

/** The context this notice sends, what it carries, and what it left out (for the audit). */
export function composeContext(context, visible) {
  const entries = [], carried = { blocks: {}, rows: [], memories: [] }, unchanged = [];
  let rows = 0, memories = 0, thoughts = 0;
  const shownThought = id => typeof id === 'string' && id.startsWith('mono-')
    && (visible.thoughts ?? new Set()).has(id.slice(id.lastIndexOf(':') + 1));
  for (let [key, value] of Object.entries(context)) {
    if (key === 'recent_thoughts_from_program' && Array.isArray(value?.items)) {
      // Her recent thoughts she can still read where she wrote them are not listed again.
      const items = value.items.filter(item => !shownThought(item._id));
      thoughts += value.items.length - items.length;
      if (!items.length) continue;
      value = { ...value, items };
    }
    if (key === 'delivered_history' && Array.isArray(value)) {
      // Her own reply is visible while the turn that produced it is.
      const kept = value.filter(row => !visible.rows.has(row._id)
        && !(row.direction === 'outbound' && row.episode_id && visible.episodes.has(row.episode_id)));
      rows += value.length - kept.length;
      carried.rows.push(...kept.map(row => row._id).filter(Boolean));
      entries.push([key, kept.map(({ episode_id: _episode, ...row }) => row)]);
    } else if (key === 'memories' && Array.isArray(value)) {
      const kept = value.filter(item => !visible.memories.has(item._id) && !shownThought(item._id));
      thoughts += value.filter(item => !visible.memories.has(item._id) && shownThought(item._id)).length;
      memories += value.filter(item => visible.memories.has(item._id)).length;
      carried.memories.push(...kept.map(item => item._id).filter(Boolean));
      entries.push([key, kept]);
    } else if (ALWAYS.has(key)) {
      entries.push([key, value]);
    } else {
      const value_digest = digest(value);
      if (visible.blocks.has(key + ':' + value_digest)) unchanged.push(key);
      else { carried.blocks[key] = value_digest; entries.push([key, value]); }
    }
  }
  const notes = [];
  if (unchanged.length) notes.push(['unchanged_from_program', { blocks: unchanged,
    note: '这些资料和本会话前面给出的一样，没有变化，仍以前面那份为准。' }]);
  if (rows || memories || thoughts) notes.push(['repeated_from_program', { history_rows: rows, memories,
    ...(thoughts ? { your_thoughts: thoughts } : {}),
    note: '已经在本会话里的消息、记忆和你自己写下的心里话不再重复列出；delivered_history、memories 和 recent_thoughts_from_program 只含新的。' }]);
  const head = entries.filter(([key]) => HEAD.includes(key)), rest = entries.filter(([key]) => !HEAD.includes(key));
  return { context: Object.fromEntries([...head, ...notes, ...rest]), carried,
    omitted: { blocks: unchanged, history_rows: rows, memories, ...(thoughts ? { thoughts } : {}) } };
}
