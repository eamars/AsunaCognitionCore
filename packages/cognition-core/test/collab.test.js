import test from 'node:test';
import assert from 'node:assert/strict';
import { Collab } from '../src/collab.js';

/** Her role session and one action session; the action session's log grows as the test says. */
function harness() {
  const events = [], source = [];
  const role = { status: 'idle', session: { snapshotEvents: () => events,
    append: (type, data) => events.push({ type, data, seq: events.length }) } };
  const action = { status: 'running', session: { snapshotEvents: () => source } };
  const injected = [];
  action.inject = message => injected.push(message);
  const core = { states: new Map([['same-source', { current: { token: 'run' } }]]),
    relay: message => ({ relayed: message.text }),
    ctx: { agents: { get: id => id === 'role' ? role : id === 'same-source' ? action : undefined },
      sessions: { flush: async () => {} } } };
  let seq = 0;
  const step = (calls = 1, text = '') => {
    for (let index = 0; index < calls; index++) source.push({ seq: seq++, type: 'tool/call', data: {} });
    if (text) source.push({ seq: seq++, type: 'assistant/message',
      data: { message: { content: [{ type: 'text', text }] } } });
  };
  const thread = events => events.filter(e => e.type === 'asuna/collab').map(e => e.data);
  return { collab: new Collab(core), role, action, events, step, thread, injected };
}
const stage = (token, task = 'task-one') => ({ lane: 'executor', token, session_id: 'same-source',
  task: { _id: task, thread: 'task-one', title: '查天气', parent_session_id: 'role' } });

test('successive runs of one thread get disjoint work ranges and their own reports; replay adds nothing', async () => {
  const h = harness();
  await h.collab.start(stage('first')); h.step(3, '明天有雨'); await h.collab.finish(stage('first'));
  await h.collab.start(stage('second', 'task-two')); h.step(2, '后天晴'); await h.collab.finish(stage('second', 'task-two'));
  const entries = h.thread(h.events);
  assert.deepEqual(entries.map(e => e.kind), ['open', 'work', 'report', 'open', 'work', 'report'], 'each run opens');
  const [, first, , , second] = entries;
  assert.equal(first.tool_calls, 3); assert.equal(second.tool_calls, 2);
  assert.equal(second.after_seq, first.through_seq, 'the second range starts where the first ended');
  assert.deepEqual(entries.filter(e => e.kind === 'report').map(e => e.text), ['明天有雨', '后天晴']);
  const count = h.events.length;
  await h.collab.add('role', entries[0]);
  assert.equal(h.events.length, count, 'an entry with the same id is not appended twice');
});

test('an entry after the conversation moved on starts a new block there, from either brain', async () => {
  const h = harness();
  const say = (id, kind, from, text, extra = {}) => h.collab.entry({ session_id: 'role', thread: 'task-one',
    task_id: 'task-one', entry: { id, kind, from, text, ...extra } });
  await say('brief:task-one', 'message', 'character', '查一下明天的天气', { title: '查天气' });
  await h.collab.start(stage('run')); h.step(2);
  const first = h.thread(h.events);
  assert.deepEqual(first.map(e => e.kind), ['message', 'open']);
  assert.equal(new Set(first.map(e => e.block)).size, 1, 'a handover and the run it starts are one block');
  h.events.push({ type: 'turn/start', data: { turn: 2 }, seq: h.events.length });     // the conversation moves on
  await say('m:1', 'message', 'character', '顺便看看后天');
  const second = h.thread(h.events).slice(first.length);
  assert.deepEqual(second.map(e => e.kind), ['continued', 'open', 'work', 'message']);
  assert.equal(second[0].block, first[0].block, 'the earlier block reads as continued below');
  const block = second[1].block;
  assert.ok(block !== first[0].block && second.slice(1).every(e => e.block === block));
  assert.equal(second[1].title, '查天气', 'a new block carries the thread title');
  assert.equal(second[1].child_session_id, 'same-source', 'it opens on the run still going, so its work shows there');
  h.step(1, '明天有雨，后天晴');
  h.events.push({ type: 'user/message', data: {}, seq: h.events.length });            // the owner says something
  await h.collab.finish(stage('run'));
  const third = h.thread(h.events).slice(first.length + second.length);
  assert.deepEqual(third.map(e => e.kind), ['continued', 'open', 'work', 'report'], "the action brain's report shows where it arrives");
  assert.equal(third[0].block, block);
  await say('a:2', 'progress', 'action', '不会再分块');
  assert.equal(h.thread(h.events).at(-1).block, third[1].block, 'without new conversation, entries stay in the block');
});

test('a question in the middle of a run splits its work, so the thread reads in order', async () => {
  const h = harness();
  await h.collab.start(stage('run'));
  h.step(2);
  await h.collab.entry({ session_id: 'role', thread: 'task-one', task_id: 'task-one',
    entry: { id: 'q:1', kind: 'question', from: 'action', text: '查哪个城市？' } });
  await h.collab.entry({ session_id: 'role', thread: 'task-one', task_id: 'task-one',
    entry: { id: 'a:1', kind: 'answer', from: 'character', text: '本地' } });
  h.step(1, '本地明天有雨');
  await h.collab.finish(stage('run'));
  assert.deepEqual(h.thread(h.events).map(e => e.kind), ['open', 'work', 'question', 'answer', 'work', 'report']);
});

test('entries wait while she is in a turn and are appended once she is idle', async () => {
  const h = harness();
  h.role.status = 'running';
  await h.collab.entry({ session_id: 'role', thread: 'task-one', task_id: 'task-one',
    entry: { id: 'brief:task-one', kind: 'message', from: 'character', text: '查一下明天的天气' } });
  assert.equal(h.thread(h.events).length, 0, 'not inside her turn');
  h.role.status = 'idle';
  await h.collab.flush('role');
  assert.deepEqual(h.thread(h.events).map(e => [e.kind, e.text]), [['message', '查一下明天的天气']]);
});

test('her message reaches only a running action session with a current stage', async () => {
  const h = harness();
  await h.collab.start(stage('run'));
  assert.equal(await h.collab.message({ thread: 'task-one', message: { id: 'm1', text: '顺便看看风' } }), true);
  assert.deepEqual(h.injected, [{ relayed: '顺便看看风' }]);
  h.action.status = 'idle';
  assert.equal(await h.collab.message({ thread: 'task-one', message: { id: 'm2', text: '还有温度' } }), false,
    'an idle session is not woken; the worker delivers it with the next round');
  assert.equal(h.injected.length, 1);
});

test('thread entries are informational: plain DSH readers may skip them', async () => {
  const { ASUNA_EVENTS } = await import('../src/persistence.js');
  assert.ok(ASUNA_EVENTS.has('asuna/collab'), 'without ignorable, DSH refuses to load the conversation');
});

test('where a result stands on its way back stays in its run\'s block, though her turn on it came between', async () => {
  const h = harness();
  await h.collab.start(stage('run')); h.step(2, '查完了'); await h.collab.finish(stage('run'));
  const say = (id, entry) => h.collab.entry({ session_id: 'role', thread: 'task-one', task_id: 'task-one', entry: { id, ...entry } });
  await say('status:done', { kind: 'status', state: 'done' });
  await say('handback:handing', { kind: 'handback', state: 'handing' });
  h.events.push({ type: 'turn/start', data: { turn: 2 }, seq: h.events.length });     // her turn on the result
  await say('handback:taken', { kind: 'handback', state: 'taken' });
  const entries = h.thread(h.events);
  assert.deepEqual(entries.map(e => e.kind), ['open', 'work', 'report', 'status', 'handback', 'handback']);
  assert.equal(new Set(entries.map(e => e.block)).size, 1);
});
