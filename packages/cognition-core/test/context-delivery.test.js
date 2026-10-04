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
