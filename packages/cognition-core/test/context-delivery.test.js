import test from 'node:test';
import assert from 'node:assert/strict';
import { composeContext, visibleCarried } from '../src/context-delivery.js';

// A minimal session surface: what the model currently sees, newest last.
function surface(events) {
  return { surface: { nodes: events.map((_, index) => index) }, eventAt: seq => events[seq],
    deriveEventMessage: event => ({ content: event.data.content }) };
}
const notice = (composed, episode) => ({ type: 'user/message', data: {
  content: [{ type: 'text', text: JSON.stringify(composed.context) }],
  source: { kind: 'asuna', carried: { ...composed.carried, episode } } } });
const context = (rows, extra = {}) => ({ scene: '本机私聊', self_state_from_program: { core: '同一份自我' },
  relationship: { body: '认识' }, delivered_history: rows, memories: [{ _id: 'm1', body_markdown: '记忆' }],
  event: { text: '新的话' }, ...extra });

test('a role notice repeats only what the visible session no longer shows', () => {
  const first = composeContext(context([{ _id: 'in-1', direction: 'inbound', text: '旧话' }]), visibleCarried(surface([])));
  assert.deepEqual(Object.keys(first.context), ['scene', 'self_state_from_program', 'relationship', 'delivered_history', 'memories', 'event']);
  const reply = { type: 'assistant/message', data: { content: [{ type: 'text', text: '她的回复' }] } };
  const events = [notice(first, 'ep-1'), reply];

  // Same blocks, the earlier row, and her own reply (its turn is visible): only the new row and the trigger.
  const second = composeContext(context([{ _id: 'in-1', direction: 'inbound', text: '旧话' },
    { _id: 'out-1', direction: 'outbound', episode_id: 'ep-1', text: '她的回复' },
    { _id: 'in-2', direction: 'inbound', text: '新的话' }], { relationship: { body: '认识加深' } }), visibleCarried(surface(events)));
  assert.deepEqual(second.context.delivered_history, [{ _id: 'in-2', direction: 'inbound', text: '新的话' }]);
  assert.deepEqual(second.context.memories, []);
  assert.deepEqual(second.context.relationship, { body: '认识加深' }, 'a changed block is sent again');
  assert.equal(second.context.self_state_from_program, undefined);
  assert.deepEqual(second.omitted, { blocks: ['self_state_from_program'], history_rows: 2, memories: 1 });
  assert.equal(second.context.event.text, '新的话');

  // Once the carrier is outside the reuse window (compaction may have absorbed it), everything returns.
  const filler = { type: 'user/message', data: { content: [{ type: 'text', text: 'x'.repeat(40000 * 4) }] } };
  const third = composeContext(context([{ _id: 'in-1', direction: 'inbound', text: '旧话' }]),
    visibleCarried(surface([...events, filler])));
  assert.deepEqual(third.context.self_state_from_program, { core: '同一份自我' });
  assert.equal(third.context.delivered_history.length, 1);
});

test('group lines already projected into the conversation are not listed again as history', () => {
  const line = (id, text) => ({ type: 'user/message', data: { content: [{ type: 'text', text }],
    source: { kind: 'user', channel: 'qq', receipt: id } } });
  const events = [line('in-7', '[名字 #1]\n  第一句'), line('in-8', '[名字 #2]\n  第二句')];
  const composed = composeContext(context([{ _id: 'in-6', direction: 'inbound', text: '更早的话' },
    { _id: 'in-7', direction: 'inbound', text: '第一句' }, { _id: 'in-8', direction: 'inbound', text: '第二句' }]),
    visibleCarried(surface(events)));
  assert.deepEqual(composed.context.delivered_history.map(row => row._id), ['in-6']);
  assert.equal(composed.omitted.history_rows, 2);
});

test('lines waiting for a conversation\'s first turn are not repeated in its first notice', () => {
  const waiting = ['in-1', 'in-2'].map(receipt => ({ content: [{ type: 'text', text: '群里的话' }],
    source: { kind: 'user', channel: 'qq', receipt } }));
  const rows = [{ _id: 'in-1', direction: 'inbound', text: '群里的话' }, { _id: 'in-2', direction: 'inbound', text: '群里的话' },
    { _id: 'in-3', direction: 'inbound', text: '叫她的话' }];
  const first = composeContext(context(rows), visibleCarried(surface([]), waiting));
  assert.deepEqual(first.context.delivered_history, [{ _id: 'in-3', direction: 'inbound', text: '叫她的话' }]);
  assert.equal(first.omitted.history_rows, 2);
});

test('her own thoughts the session still shows where she wrote them are not repeated', () => {
  const thought = id => ({ type: 'assistant/message', data: { content: [
    { type: 'tool-call', id, name: 'think', arguments: { thought: '心里话' } }] } });
  const recent = { items: [{ _id: 'mono-ep-1:call_a', thought: '旧的' }, { _id: 'mono-ep-2:call_b', thought: '新的' }],
    note: '此前的心里话' };
  const recalled = [{ _id: 'mono-ep-1:call_a', kind: 'monologue', body_markdown: '旧的' },
    { _id: 'mono-ep-9:call_z', kind: 'monologue', body_markdown: '很早以前的', then: ['所以我说了「好」'] },
    { _id: 'm1', body_markdown: '记忆' }];
  const composed = composeContext(context([], { memories: recalled, recent_thoughts_from_program: recent }),
    visibleCarried(surface([thought('call_a'), thought('call_b')])));
  assert.deepEqual(composed.context.memories.map(m => m._id), ['mono-ep-9:call_z', 'm1']);
  assert.equal(composed.context.recent_thoughts_from_program, undefined, 'every recent thought is still visible');
  assert.equal(composed.omitted.thoughts, 3);
  assert.equal(composed.context.repeated_from_program.your_thoughts, 3);
  // After a compaction (nothing visible) they all come back.
  const fresh = composeContext(context([], { memories: recalled, recent_thoughts_from_program: recent }), visibleCarried(surface([])));
  assert.equal(fresh.context.recent_thoughts_from_program.items.length, 2);
  assert.equal(fresh.context.memories.length, 3);
});

test('a list block goes item by item: what she still sees folds into one line with its states, what waits on her never does', () => {
  const notes = items => ({ notes_from_program: { items } });
  const read = { from: '群 A', at: '2026-10-12 19:00', text: '早到了', state: '读过了' };
  const waiting = { from: '群 B', at: '2026-10-12 19:05', text: '等你回', waiting_on_you: true };
  const first = composeContext(context([], notes([read, waiting])), visibleCarried(surface([])));
  assert.deepEqual(first.context.notes_from_program.items, [read, waiting], 'first time: all of it');
  const events = [notice(first, 'ep-1')];

  const fresh = { from: '群 C', at: '2026-10-12 19:30', text: '新便条', state: '读过了' };
  const second = composeContext(context([], notes([fresh, read, waiting])), visibleCarried(surface(events)));
  assert.deepEqual(second.context.notes_from_program, { items: [fresh, waiting], same_as_before: '其余 1 条同前（读过了 1）' });
  assert.equal(second.omitted.items, 1);

  // The same block again: every item is visible, but it was never sent whole, so it is not called unchanged.
  const third = composeContext(context([], notes([fresh, read, waiting])), visibleCarried(surface([...events, notice(second, 'ep-2')])));
  assert.deepEqual(third.context.notes_from_program, { items: [waiting], same_as_before: '其余 2 条同前（读过了 2）' });

  // A plain list (her plans) keeps the same rule; the delivery's own lines carry no explanation.
  const plans = [{ _id: 'p1', intent: '喝水' }, { _id: 'p2', intent: '看群' }];
  const once = composeContext(context([], { plans_from_program: plans }), visibleCarried(surface([])));
  const twice = composeContext(context([], { plans_from_program: [plans[0], { _id: 'p2', intent: '看两个群' }] }),
    visibleCarried(surface([notice(once, 'ep-3')])));
  assert.deepEqual(twice.context.plans_from_program, { items: [{ _id: 'p2', intent: '看两个群' }], same_as_before: '其余 1 条同前' });
  assert.deepEqual(twice.context.unchanged_from_program, ['self_state_from_program', 'relationship']);

  // ADR-063 D9: that same block once more, every item still visible: named unchanged, no empty wrapper.
  const thrice = composeContext(context([], { plans_from_program: [plans[0], { _id: 'p2', intent: '看两个群' }] }),
    visibleCarried(surface([notice(once, 'ep-3'), notice(twice, 'ep-4')])));
  assert.equal(thrice.context.plans_from_program, undefined);
  assert.deepEqual(thrice.context.unchanged_from_program, ['self_state_from_program', 'relationship', 'plans_from_program']);
  // A block whose every item is visible but which differs as a whole (an item gone) still says what it holds.
  const fewer = composeContext(context([], { plans_from_program: [plans[0]] }),
    visibleCarried(surface([notice(once, 'ep-3'), notice(twice, 'ep-4')])));
  assert.deepEqual(fewer.context.plans_from_program, { items: [], same_as_before: '其余 1 条同前' });
});

test('a group thread line or the speaker\'s last lines still on the surface are not listed again', () => {
  const line = (receipt, text) => ({ type: 'user/message', data: { content: [{ type: 'text', text }],
    source: { kind: 'user', channel: 'qq', receipt } } });
  const reply = { type: 'assistant/message', data: { content: [{ type: 'text', text: '她接的话' }] } };
  const first = composeContext(context([]), visibleCarried(surface([])));
  const events = [line('in-a', '第一句'), notice(first, 'ep-9'), reply, line('in-b', '第二句')];
  const group = { wake_reason: 'reply_to_character', topic_id: 't1',
    related_messages: [{ _id: 'in-a', direction: 'inbound', text: '第一句' },
      { _id: 'out-9', direction: 'outbound', episode_id: 'ep-9', text: '她接的话' },
      { _id: 'in-old', direction: 'inbound', text: '早就看不到的' }],
    current_speaker_tail: [{ _id: 'in-b', direction: 'inbound', text: '第二句' }] };
  const composed = composeContext(context([], { group_continuity_from_program: group }), visibleCarried(surface(events)));
  assert.deepEqual(composed.context.group_continuity_from_program, { wake_reason: 'reply_to_character', topic_id: 't1',
    related_messages: [{ _id: 'in-old', direction: 'inbound', text: '早就看不到的' }], current_speaker_tail: [] });
  assert.equal(composed.omitted.history_rows, 3);
  assert.ok(composed.carried.rows.includes('in-old'), 'a line sent here counts as visible for the next notice');
});

test('a recalled memory whose every source line is still on the surface is not listed again', () => {
  const line = (receipt, text) => ({ type: 'user/message', data: { content: [{ type: 'text', text }],
    source: { kind: 'user', channel: 'qq', receipt } } });
  const events = [line('in-a', '第一句'), line('in-b', '第二句')];
  const memories = [{ _id: 'chunk-a', kind: 'chunk', source_event_ids: ['in-a'], body_markdown: '第一句' },
    { _id: 'sum-ab', kind: 'derived_summary', source_event_ids: ['in-a', 'in-b', 'in-gone'], body_markdown: '摘要' },
    { _id: 'mono-1', kind: 'monologue', source_event_ids: ['in-a'], body_markdown: '心里话' },
    { _id: 'chunk-x', kind: 'chunk', body_markdown: '没有来源' }];
  const composed = composeContext(context([], { memories }), visibleCarried(surface(events)));
  assert.deepEqual(composed.context.memories.map(item => item._id), ['sum-ab', 'mono-1', 'chunk-x']);
  assert.equal(composed.omitted.memories, 1);
  assert.deepEqual(composed.context.repeated_from_program, { history_rows: 0, memories: 1 });
});

test('object lists inside a block fold by their field path; an item waiting on her is always sent', () => {
  const task = (id, state) => ({ _id: id, title: '事 ' + id, state });
  const experience = tasks => ({ recent_experience_from_program: { window: '最近一天', tasks,
    nested: { reasons: [{ why: '下雨' }] } } });
  const first = composeContext(context([], experience([task('t1', '做完了'), task('t2', '做完了')])), visibleCarried(surface([])));
  assert.deepEqual(first.context.recent_experience_from_program.tasks.length, 2, 'first time: all of it');
  const events = [notice(first, 'ep-1')];

  const asks = { ...task('t4', '在问你'), waiting_on_you: true };
  const second = composeContext(context([], experience([task('t3', '在做'), task('t1', '做完了'), task('t2', '做完了'), asks])),
    visibleCarried(surface(events)));
  assert.deepEqual(second.context.recent_experience_from_program, { window: '最近一天',
    tasks: { items: [task('t3', '在做'), asks], same_as_before: '其余 2 条同前（做完了 2）' },
    nested: { reasons: { items: [], same_as_before: '其余 1 条同前' } } });
  assert.equal(second.omitted.items, 3);
  // The same block once more, everything still visible but the item waiting on her, which is sent again.
  const third = composeContext(context([], experience([task('t3', '在做'), task('t1', '做完了'), task('t2', '做完了'), asks])),
    visibleCarried(surface([...events, notice(second, 'ep-2')])));
  assert.deepEqual(third.context.recent_experience_from_program.tasks, { items: [asks], same_as_before: '其余 3 条同前（在做 1、做完了 2）' });
});
