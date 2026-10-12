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
 * (ADR-056), and so does every list of objects in a block's fields (by its field path): an item still visible is
 * folded into one `same_as_before` line that says how many and in what state,
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

/** Fold a block's object lists: its own list (a list, or `items`) under the block's key, and every object list in
 * its fields, at any depth, under that field's path (`block.field.field`). An item still visible under its path folds,
 * except one waiting on her. Returns the value to send, the digests of the items sent per path, and how many items
 * were folded and kept. */
function fold(path, value, seen) {
  const list = listOf(value);
  if (list) {
    const kept = list.items.filter(item => item.waiting_on_you === true || !seen.has(path + ':' + digest(item)));
    const folded = list.items.filter(item => !kept.includes(item));
    return { value: folded.length ? list.wrap(kept, sameAsBefore(folded)) : value,
      sent: { [path]: kept.map(digest) }, folded: folded.length, kept: kept.length };
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { value, sent: {}, folded: 0, kept: 0 };
  const out = {}, sent = {};
  let folded = 0, kept = 0;
  for (const [field, inner] of Object.entries(value)) {
    const nested = fold(path + '.' + field, inner, seen);
    out[field] = nested.value; Object.assign(sent, nested.sent); folded += nested.folded; kept += nested.kept;
  }
  return { value: folded ? out : value, sent, folded, kept };
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
      if (visible.blocks.has(key + ':' + value_digest)) { unchanged.push(key); continue; }
      const folding = fold(key, value, visible.items ?? new Set());
      Object.assign(carried.items, folding.sent);
      if (!folding.folded) { carried.blocks[key] = value_digest; entries.push([key, value]); continue; }
      // Only a block sent whole may later count as unchanged: the folded items rest on older notices. The same block
      // again with every item still visible, though, is wholly before her: it is named unchanged, with no wrapper.
      items += folding.folded;
      if (!folding.kept && visible.lists?.has(key + ':' + value_digest)) { unchanged.push(key); continue; }
      carried.lists[key] = value_digest;
      entries.push([key, folding.value]);
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

/** The turn's ceiling on what this notice sends (the worker's table, context_budget.ceiling): over it, the oldest rows
 * of the listed lists go first, then the longest text left is halved, again and again, saying how much went. Under it
 * nothing is cut, so a block she still sees never costs another one its text, and the same content is sent the same
 * way. What is cut is no longer counted as carried. Returns what was left out. */
export function trimTurn(composed, ceiling) {
  const size = value => JSON.stringify(value ?? null).length;
  if (!ceiling || size(composed.context) <= ceiling.chars) return {};
  const context = structuredClone(composed.context), carried = composed.carried, left = {}, touched = new Set();
  let total = size(context);
  const ROWS = new Set(['delivered_history', 'group_continuity_from_program']);
  // A row or memory goes from what the notice carries; a block that lost anything no longer counts as sent whole.
  const forget = (block, path, row) => {
    touched.add(block);
    if (ROWS.has(block) && row?._id) carried.rows = carried.rows.filter(id => id !== row._id);
    else if (block === 'memories' && row?._id) carried.memories = carried.memories.filter(id => id !== row._id);
    else if (row && carried.items[path]) {
      const index = carried.items[path].indexOf(digest(row));
      if (index >= 0) carried.items[path].splice(index, 1);
    }
  };
  for (const [block, inner, end] of ceiling.order) {
    const holder = context[block];
    let rows = inner && holder && typeof holder === 'object' && !Array.isArray(holder) ? holder[inner] : holder;
    if (rows && !Array.isArray(rows) && Array.isArray(rows.items)) rows = rows.items;      // a folded list
    if (!Array.isArray(rows)) continue;
    const floor = block === 'delivered_history' ? ceiling.keep_history_rows : 0;
    const path = !inner || inner === 'items' ? block : block + '.' + inner, name = block + (inner ? '.' + inner : '');
    while (rows.length > floor && total > ceiling.chars) {
      const [row] = rows.splice(end === 'oldest' ? 0 : -1, 1);
      total -= size(row) + 1;
      forget(block, path, row);
      left[name] = (left[name] ?? 0) + 1;
    }
    if (total <= ceiling.chars) break;
  }
  let shortened = 0;
  while (total > ceiling.chars) {
    const found = longestText(context);
    if (!found) break;
    const { holder, key, text, block, row } = found;
    const keep = Math.max(ceiling.short_text, Math.floor(text.length / 2));
    const cut = text.slice(0, keep) + ceiling.cut_note.replace('%d', String(text.length - keep));
    if (cut.length >= text.length) break;
    holder[key] = cut;
    total = size(context);
    shortened += 1;
    if (ROWS.has(block) || block === 'memories') forget(block, block, row);
    else {
      touched.add(block);
      for (const path of Object.keys(carried.items)) if (path === block || path.startsWith(block + '.')) delete carried.items[path];
    }
  }
  if (shortened) left.shortened_texts = shortened;
  for (const block of touched) { delete carried.blocks[block]; delete carried.lists[block]; }
  const entries = Object.entries(context), at = entries.findIndex(([key]) => !HEAD.includes(key));
  entries.splice(at < 0 ? entries.length : at, 0, ['trimmed_from_program', { left_out: left, note: ceiling.note }]);
  composed.context = Object.fromEntries(entries);
  composed.omitted.trimmed = left;
  return left;
}

/** The longest string in the context, where it sits, its top-level block and the nearest row with an `_id` above it. */
function longestText(context) {
  let best = null;
  for (const [block, value] of Object.entries(context)) {
    const stack = [[value, null]];
    while (stack.length) {
      const [node, row] = stack.pop();
      const near = node && typeof node === 'object' && !Array.isArray(node) && node._id ? node : row;
      const pairs = Array.isArray(node) ? node.entries() : node && typeof node === 'object' ? Object.entries(node) : [];
      for (const [key, inner] of pairs) {
        if (typeof inner === 'string') {
          if (!best || inner.length > best.text.length) best = { holder: node, key, text: inner, block, row: near };
        } else if (inner && typeof inner === 'object') stack.push([inner, near]);
      }
    }
  }
  return best;
}
