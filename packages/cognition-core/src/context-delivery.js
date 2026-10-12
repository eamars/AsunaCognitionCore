/** Per-turn context delivery for the character brain: of the whole context the worker prepares every turn, only
 * what her session does not still show is sent.
 *
 * A block, history row (of `delivered_history`, or a line in `group_continuity_from_program`) or memory is left out,
 * and so is one of her own thoughts (a recalled one, or one of her
 * recent thoughts) whose `think` call the session still shows, only while an identical copy sits inside the newest REUSE_WINDOW_TOKENS
 * of the session surface. That stretch is inside DSH's retained tail, so any
 * compaction, including one that runs right before this message joins the
 * surface, keeps it verbatim. Anything older is sent again. Each notice records
 * what it carries in its own `source.carried`, so the session log is the only
 * state; nothing is cached in the worker or Mongo. A recalled memory (not one of her thoughts) whose every source
 * line is visible is left out too.
 *
 * A list block (a list of items, or a block with `items`) whose whole copy is not visible goes item by item
 * (ADR-056): an item still visible is folded into one `same_as_before` line that says how many and in what state,
 * except an item waiting on her (`waiting_on_you`), which is always sent; the same block again with every item still
 * visible is named in `unchanged_from_program` instead of sending an empty wrapper. What these lines mean is in her system
 * prompt (block_guide.py), so they carry no explanation of their own. */
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
  const visible = { blocks: new Set(), items: new Set(), lists: new Set(), rows: new Set(), memories: new Set(),
    episodes: new Set(), thoughts: new Set() };
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
    for (const [key, values] of Object.entries(carried.items ?? {})) for (const value of values) visible.items.add(key + ':' + value);
    // A list block sent folded: the whole block as it was then (its items on this and older notices).
    for (const [key, value] of Object.entries(carried.lists ?? {})) visible.lists.add(key + ':' + value);
    for (const id of carried.rows ?? []) visible.rows.add(id);
    for (const id of carried.memories ?? []) visible.memories.add(id);
    if (carried.episode) visible.episodes.add(carried.episode);
  }
  return visible;
}

/** A list block's items and how to rebuild the block around fewer of them, or null for any other block. */
function listOf(value) {
  const objects = items => items.length > 0 && items.every(item => item && typeof item === 'object' && !Array.isArray(item));
  if (Array.isArray(value)) return objects(value) ? { items: value, rest: {}, wrap: (items, same) => ({ items, same_as_before: same }) } : null;
  if (value && typeof value === 'object' && Array.isArray(value.items) && objects(value.items)) {
    const { items, ...rest } = value;
    return { items, rest, wrap: (kept, same) => ({ ...rest, items: kept, same_as_before: same }) };
  }
  return null;
}

/** "其余 4 条同前（读过了 3、已送到 1）": how many items were folded, and their states when they have one. */
function sameAsBefore(folded) {
  const states = new Map();
  for (const item of folded) if (typeof item.state === 'string') states.set(item.state, (states.get(item.state) ?? 0) + 1);
  const tally = [...states].map(([state, count]) => state + ' ' + count).join('、');
  return '其余 ' + folded.length + ' 条同前' + (tally ? '（' + tally + '）' : '');
}

/** The context this notice sends, what it carries, and what it left out (for the audit). */
export function composeContext(context, visible) {
  const entries = [], carried = { blocks: {}, items: {}, lists: {}, rows: [], memories: [] }, unchanged = [];
  let rows = 0, memories = 0, thoughts = 0, items = 0;
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
    // Her own reply is visible while the turn that produced it is.
    const unseen = row => !visible.rows.has(row._id)
      && !(row.direction === 'outbound' && row.episode_id && visible.episodes.has(row.episode_id));
    if (key === 'group_continuity_from_program' && value && typeof value === 'object') {
      // The thread's lines and the speaker's last lines that the conversation still shows are not listed again.
      const lines = {};
      for (const field of ['related_messages', 'current_speaker_tail']) if (Array.isArray(value[field])) {
        const kept = value[field].filter(unseen);
        rows += value[field].length - kept.length;
        carried.rows.push(...kept.map(row => row._id).filter(Boolean));
        lines[field] = kept.map(({ episode_id: _episode, ...row }) => row);
      }
      value = { ...value, ...lines };
    }
    if (key === 'delivered_history' && Array.isArray(value)) {
      const kept = value.filter(unseen);
      rows += value.length - kept.length;
      carried.rows.push(...kept.map(row => row._id).filter(Boolean));
      entries.push([key, kept.map(({ episode_id: _episode, ...row }) => row)]);
    } else if (key === 'memories' && Array.isArray(value)) {
      // A memory is shown already when its copy is, or when every line it was made from is still on the surface.
      const shown = item => visible.memories.has(item._id) || item.kind !== 'monologue'
        && Array.isArray(item.source_event_ids) && item.source_event_ids.length > 0
        && item.source_event_ids.every(id => visible.rows.has(id));
      const kept = value.filter(item => !shown(item) && !shownThought(item._id));
      thoughts += value.filter(item => !shown(item) && shownThought(item._id)).length;
      memories += value.filter(shown).length;
      carried.memories.push(...kept.map(item => item._id).filter(Boolean));
      entries.push([key, kept]);
    } else if (ALWAYS.has(key)) {
      entries.push([key, value]);
    } else {
      const value_digest = digest(value);
      const list = visible.blocks.has(key + ':' + value_digest) ? null : listOf(value);
      if (!list) {
        if (visible.blocks.has(key + ':' + value_digest)) unchanged.push(key);
        else { carried.blocks[key] = value_digest; entries.push([key, value]); }
        continue;
      }
      const seen = visible.items ?? new Set();
      const kept = list.items.filter(item => item.waiting_on_you === true || !seen.has(key + ':' + digest(item)));
      const folded = list.items.filter(item => !kept.includes(item));
      carried.items[key] = kept.map(digest);
      if (!folded.length) { carried.blocks[key] = value_digest; entries.push([key, value]); continue; }
      // Only a block sent whole may later count as unchanged: the folded items rest on older notices. The same block
      // again with every item still visible, though, is wholly before her: it is named unchanged, with no wrapper.
      items += folded.length;
      if (!kept.length && visible.lists?.has(key + ':' + value_digest)) { unchanged.push(key); continue; }
      carried.lists[key] = value_digest;
      entries.push([key, list.wrap(kept, sameAsBefore(folded))]);
    }
  }
  const notes = [];
  if (unchanged.length) notes.push(['unchanged_from_program', unchanged]);
  if (rows || memories || thoughts) notes.push(['repeated_from_program', { history_rows: rows, memories,
    ...(thoughts ? { your_thoughts: thoughts } : {}) }]);
  const head = entries.filter(([key]) => HEAD.includes(key)), rest = entries.filter(([key]) => !HEAD.includes(key));
  return { context: Object.fromEntries([...head, ...notes, ...rest]), carried,
    omitted: { blocks: unchanged, history_rows: rows, memories, ...(thoughts ? { thoughts } : {}), ...(items ? { items } : {}) } };
}
