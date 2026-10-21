/** Per-turn context delivery for the character brain: of the whole context the worker prepares every turn, only
 * what her session does not still show is sent.
 *
 * A block, history row (of `delivered_history`, or a line in `group_continuity_from_program`) or memory is left out,
 * and so is one of her own thoughts (a recalled one, or one of her recent thoughts) whose `think` call the session
 * still shows, while an identical copy is anywhere on the session surface (everything after the last compaction
 * checkpoint). A recalled memory (not one of her thoughts) whose every source line is visible is left out too. Within
 * one notice a line (by its message id) is sent once, in its primary block: `delivered_history` (the conversation)
 * first, then the group's thread lines, then her recent experience; a task's original input that is such a line is
 * named by its id (`original_input_id`) instead of its text. Each
 * notice records what it carries in its own `source.carried`, so the session log is the only state; nothing is cached
 * in the worker or Mongo.
 *
 * A compaction can take a copy a notice relied on off the surface. When one commits after a notice was composed, the
 * next step's start (index.js pre-step) sends what of that notice's context is no longer visible as a short follow-up
 * notice (`restoreContext`), so nothing a notice called unchanged is missing when the model reads the next request.
 *
 * A list block (a list of items, or a block with `items`) whose whole copy is not visible goes item by item
 * (ADR-056), and so does every list of objects in a block's fields (by its field path): an item still visible is
 * folded into one `same_as_before` line that says how many and in what state,
 * except an item waiting on her (`waiting_on_you`), which is always sent; the same block again with every item still
 * visible is named in `unchanged_from_program` instead of sending an empty wrapper. What these lines mean is in her system
 * prompt (block_guide.py), so they carry no explanation of their own. */
import { createHash } from 'node:crypto';

/** Orientation and the turn's trigger are always sent, and so is the line beside the trigger saying her words cannot
 * go out where she is muted. */
const ALWAYS = new Set(['scene', 'speaker', 'session_class', 'muted_here_from_program', 'event']);
const HEAD = ['scene', 'speaker', 'session_class'];
const NOTES = new Set(['unchanged_from_program', 'repeated_from_program']);

const digest = value => createHash('sha256').update(JSON.stringify(value ?? null)).digest('hex').slice(0, 16);

/** A block's digest with each of its object lists taken as a set of items: the same items in another order (a mood's
 * reasons re-ranked as they fade) are the same block, which every visible item already shows. */
function shapeDigest(value) {
  const shape = node => {
    const list = listOf(node);
    if (list) return { items: list.items.map(digest).sort(), rest: shape(list.rest) };
    if (!node || typeof node !== 'object' || Array.isArray(node)) return node;
    return Object.fromEntries(Object.entries(node).map(([key, inner]) => [key, shape(inner)]));
  };
  return digest(shape(value));
}

/** What the surface already carries. Messages about to join it in the same step (lines waiting in the inbox,
 * navigation.js, and notices claimed with them) count too, as its newest. A block counts only as its newest copy:
 * the last notice that sent it, whole (its digest) or folded (its shape), hides every older copy. */
export function visibleCarried(session, pending = []) {
  const visible = { blocks: new Set(), items: new Set(), lists: new Set(), rows: new Set(), memories: new Set(),
    episodes: new Set(), thoughts: new Set(), native: new Set() };
  const newest = new Map();
  const take = (content, source) => {
    // Her own thought, as she wrote it with `think` (its call id ends the stored thought's id).
    if (Array.isArray(content)) for (const block of content)
      if (block?.type === 'tool-call' && block.name === 'think' && block.id) visible.thoughts.add(block.id);
    // A platform line projected into the conversation as it arrived (navigation.js) is its own row.
    if (source?.kind === 'user' && source.channel && source.receipt) { visible.rows.add(source.receipt); return; }
    const carried = source?.kind === 'asuna' ? source.carried : undefined;
    if (!carried) return;
    // A list block sent folded: the whole block as it was then (its items on this and older notices).
    const blocks = carried.blocks ?? {}, lists = carried.lists ?? {};
    for (const key of new Set([...Object.keys(blocks), ...Object.keys(lists)])) newest.set(key, { block: blocks[key], list: lists[key] });
    for (const [key, values] of Object.entries(carried.items ?? {})) for (const value of values) visible.items.add(key + ':' + value);
    for (const id of carried.rows ?? []) visible.rows.add(id);
    for (const id of carried.memories ?? []) visible.memories.add(id);
    if (carried.episode) visible.episodes.add(carried.episode);
  };
  for (const seq of session.surface.nodes) {
    const event = session.eventAt(seq);
    if (!event) continue;
    const message = session.deriveEventMessage(event);
    // A line written in the Web composer is on the surface as itself: its id is the line's platform event id.
    if (event.type === 'user/message' && !event.data?.source?.channel && message?.id) visible.native.add(message.id);
    take(message?.content ?? '', event.type === 'user/message' ? event.data?.source : undefined);
  }
  for (const message of pending) take(message.content, message.source);
  for (const [key, { block, list }] of newest) {
    if (block !== undefined) visible.blocks.add(key + ':' + block);
    if (list !== undefined) visible.lists.add(key + ':' + list);
  }
  return visible;
}

/** An `ask` read result (ADR-061) without the text of an answer whose line the conversation still shows, by its
 * message id or, for a line written in the Web composer, its platform event id: the answer is named, not sent again. */
export function withoutVisibleAnswers(value, visible) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.to)) return value;
  const shown = answer => answer && typeof answer.text === 'string'
    && (visible.rows.has(answer.line) || (visible.native ?? new Set()).has(answer.event_id));
  return { ...value, to: value.to.map(place => !Array.isArray(place?.answers) || !place.answers.some(shown) ? place
    : { ...place, answers: place.answers.map(answer => {
      if (!shown(answer)) return answer;
      const { text: _text, ...rest } = answer;
      return { ...rest, text: ANSWER_IN_VIEW };
    }) }) };
}

/** What an answer still in view reads instead of its text. */
const ANSWER_IN_VIEW = '这句就在这个对话里，往上看';

/** After a compaction, what of a notice's context is no longer visible: the blocks, rows, memories and items to send
 * again (the turn's own orientation and trigger only when the notice itself is gone), with `restored_from_program`
 * naming the blocks; null when nothing fell out. */
export function restoreContext(context, visible, episode) {
  const composed = composeContext(context, visible);
  const gone = !visible.episodes.has(episode);
  const entries = Object.entries(composed.context).filter(([key, value]) => !NOTES.has(key)
    && !composed.empty.has(key) && !(Array.isArray(value) && !value.length) && (gone || !ALWAYS.has(key)));
  if (!entries.length) return null;
  composed.context = { restored_from_program: entries.map(([key]) => key), ...Object.fromEntries(entries) };
  return composed;
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

/** The fields an item is acted on by (a plan's _id, a picture's artifact_id, a place): copied, never recalled. */
const HANDLES = ['_id', 'id', 'plan_id', 'task_id', 'artifact_id', 'event_id', 'place'];

/** "其余 4 条同前（读过了 3、已送到 1）：p1、p2、p3、p4": how many items were folded, their states when they have one,
 * and the handle of each that has one. The copy shown earlier can be far back; the handle to act on it is here. */
function sameAsBefore(folded) {
  const states = new Map();
  for (const item of folded) if (typeof item.state === 'string') states.set(item.state, (states.get(item.state) ?? 0) + 1);
  const tally = [...states].map(([state, count]) => state + ' ' + count).join('、');
  const handles = folded.map(item => HANDLES.map(field => item[field]).find(value => typeof value === 'string' && value))
    .filter(Boolean);
  return '其余 ' + folded.length + ' 条同前' + (tally ? '（' + tally + '）' : '') + (handles.length ? '：' + handles.join('、') : '');
}

/** The context this notice sends, what it carries, and what it left out (for the audit). */
export function composeContext(context, visible) {
  const entries = [], carried = { blocks: {}, items: {}, lists: {}, rows: [], memories: [] }, unchanged = [], empty = new Set();
  let rows = 0, memories = 0, thoughts = 0, items = 0;
  const shownThought = id => typeof id === 'string' && id.startsWith('mono-')
    && (visible.thoughts ?? new Set()).has(id.slice(id.lastIndexOf(':') + 1));
  // Her own reply is visible while the turn that produced it is.
  const unseen = row => !visible.rows.has(row._id)
    && !(row.direction === 'outbound' && row.episode_id && visible.episodes.has(row.episode_id));
  // The lines this notice places in the conversation itself; another block does not send them again.
  const placed = new Set((Array.isArray(context.delivered_history) ? context.delivered_history : [])
    .filter(unseen).map(row => row?._id).filter(Boolean));
  const inView = id => placed.has(id) || visible.rows.has(id);
  for (let [key, value] of Object.entries(context)) {
    if (key === 'recent_thoughts_from_program' && Array.isArray(value?.items)) {
      // Her recent thoughts she can still read where she wrote them are not listed again.
      const items = value.items.filter(item => !shownThought(item._id));
      thoughts += value.items.length - items.length;
      if (!items.length) continue;
      value = { ...value, items };
    }
    if (key === 'group_continuity_from_program' && value && typeof value === 'object') {
      // The thread's lines and the speaker's last lines that the conversation still shows, or this notice's history
      // carries, are not listed again.
      const lines = {};
      for (const field of ['related_messages', 'current_speaker_tail']) if (Array.isArray(value[field])) {
        const kept = value[field].filter(row => unseen(row) && !placed.has(row._id));
        rows += value[field].length - kept.length;
        for (const row of kept) if (row._id) placed.add(row._id);
        carried.rows.push(...kept.map(row => row._id).filter(Boolean));
        lines[field] = kept.map(({ episode_id: _episode, ...row }) => row);
      }
      value = { ...value, ...lines };
    }
    if (key === 'recent_experience_from_program' && Array.isArray(value?.messages)) {
      // Lines of the conversation in front of her are not listed again among her recent experience.
      const kept = value.messages.filter(row => !inView(row?._id));
      rows += value.messages.length - kept.length;
      value = { ...value, messages: kept };
    }
    if (key === 'event' && Array.isArray(value?.trusted_context_events)) {
      // A task's original input that is a line in front of her is named by its id, not sent again.
      value = { ...value, trusted_context_events: value.trusted_context_events.map(item => {
        if (!item || typeof item !== 'object' || !('original_input_id' in item)) return item;
        const { original_input: text, original_input_id: id, ...rest } = item;
        return inView(id) ? { ...rest, original_input_id: id } : { ...rest, original_input: text };
      }) };
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
      const shape_digest = shapeDigest(value);
      if (!folding.folded) {
        carried.blocks[key] = value_digest;
        if (folding.kept) carried.lists[key] = shape_digest;
        entries.push([key, value]); continue;
      }
      // Only a block sent whole may later count as unchanged: the folded items rest on older notices. The same block
      // again (its lists' items in any order) with every item still visible, though, is wholly before her: it is
      // named unchanged, with no wrapper.
      items += folding.folded;
      if (!folding.kept && visible.lists?.has(key + ':' + shape_digest)) { unchanged.push(key); continue; }
      carried.lists[key] = shape_digest;
      if (!folding.kept) empty.add(key);
      entries.push([key, folding.value]);
    }
  }
  const notes = [];
  if (unchanged.length) notes.push(['unchanged_from_program', unchanged]);
  if (rows || memories || thoughts) notes.push(['repeated_from_program', { history_rows: rows, memories,
    ...(thoughts ? { your_thoughts: thoughts } : {}) }]);
  const head = entries.filter(([key]) => HEAD.includes(key)), rest = entries.filter(([key]) => !HEAD.includes(key));
  return { context: Object.fromEntries([...head, ...notes, ...rest]), carried, empty,
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
