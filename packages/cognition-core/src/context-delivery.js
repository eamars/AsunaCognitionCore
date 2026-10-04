/* Per-turn context delivery for the character brain (ADR-009 D-3, revised).
 *
 * The worker prepares the whole context every turn; this module decides what
 * the session still needs to be shown. A block, history row or memory is left
 * out only while an identical copy sits inside the newest REUSE_WINDOW_TOKENS
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
const ALWAYS = new Set(['scene_id', 'scope_key', 'policy_epoch', 'speaker', 'session_class', 'event']);
const HEAD = ['scene_id', 'scope_key', 'policy_epoch', 'speaker', 'session_class'];

const digest = value => createHash('sha256').update(JSON.stringify(value ?? null)).digest('hex').slice(0, 16);

/** What the newest stretch of the surface already carries (DSH's chars/4 token estimate). */
export function visibleCarried(session, windowTokens = REUSE_WINDOW_TOKENS) {
  const visible = { blocks: new Set(), rows: new Set(), memories: new Set(), episodes: new Set() };
  const nodes = session.surface.nodes;
  let used = 0;
  for (let index = nodes.length - 1; index >= 0; index--) {
    const event = session.eventAt(nodes[index]);
    if (!event) continue;
    used += Math.ceil(JSON.stringify(session.deriveEventMessage(event)?.content ?? '').length / 4);
    if (used > windowTokens) break;
    const carried = event.type === 'user/message' && event.data?.source?.kind === 'asuna'
      ? event.data.source.carried : undefined;
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
  let rows = 0, memories = 0;
  for (const [key, value] of Object.entries(context)) {
    if (key === 'delivered_history' && Array.isArray(value)) {
      // Her own reply is visible while the turn that produced it is.
      const kept = value.filter(row => !visible.rows.has(row._id)
        && !(row.direction === 'outbound' && row.episode_id && visible.episodes.has(row.episode_id)));
      rows += value.length - kept.length;
      carried.rows.push(...kept.map(row => row._id).filter(Boolean));
      entries.push([key, kept.map(({ episode_id: _episode, ...row }) => row)]);
    } else if (key === 'memories' && Array.isArray(value)) {
      const kept = value.filter(item => !visible.memories.has(item._id));
      memories += value.length - kept.length;
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
  if (rows || memories) notes.push(['repeated_from_program', { history_rows: rows, memories,
    note: '已经在本会话里的消息和记忆不再重复列出；delivered_history 与 memories 只含新的。' }]);
  const head = entries.filter(([key]) => HEAD.includes(key)), rest = entries.filter(([key]) => !HEAD.includes(key));
  return { context: Object.fromEntries([...head, ...notes, ...rest]), carried,
    omitted: { blocks: unchanged, history_rows: rows, memories } };
}
