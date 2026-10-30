// A platform line waits for the end of a step that is open (pairing.js), so her conversation says in the order of
// what she saw; a line already written between a tool call and its result is emptied in place on DSH's own surface.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { createToolResultMessage, createUserMessage } from '@deepseek-ai/dsh-llm';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import { compactionOpen, hold, isHeld, mustHold, release, releaseAtBoundary, repair, stepOpen, strayLines } from '../src/pairing.js';

const line = (receipt, text = '群里的一句') => createUserMessage({ source: { kind: 'user', channel: 'qq', receipt },
  content: [{ type: 'text', text }] });

test('a step is open from its start to its end, however it ends', () => {
  const call = { type: 'tool/call', data: { callId: 'c1' } };
  const result = { type: 'tool/result', data: { message: { source: { callId: 'c1' } } } };
  assert.equal(stepOpen([{ type: 'step/start' }]), true, 'the request is in flight');
  assert.equal(stepOpen([{ type: 'step/start' }, call]), true, 'a tool call waits for its result');
  assert.equal(stepOpen([{ type: 'step/start' }, call, result]), true, 'her next step has not begun: still inside');
  assert.equal(stepOpen([{ type: 'step/start' }, call, result, { type: 'step/end' }]), false);
  assert.equal(stepOpen([{ type: 'step/start' }, { type: 'step/end' }, { type: 'user/message' }]), false,
    'a step that failed or was aborted is closed by the same step/end (DSH appends it in a finally)');
  assert.equal(stepOpen([{ type: 'step/start' }, { type: 'turn/end' }]), false, 'never past the turn');
  assert.equal(stepOpen([]), false);
  assert.equal(stepOpen([{ type: 'step/start' }, { type: 'session/end-seed' }]), false,
    'a step the process stopped in runs no more once the conversation is opened again');
});

test('a line waits only in a conversation that has its head, and only while a step or a compaction runs', () => {
  const head = { type: 'system/message' }, start = { type: 'step/start' }, end = { type: 'step/end' };
  assert.equal(mustHold([head, start], true), true);
  assert.equal(mustHold([head, start, end], true), false, 'between steps a line is written at once');
  assert.equal(mustHold([head, start], false), false, 'a conversation without an agent runs no step');
  assert.equal(mustHold([start], true), false, 'before the head the line goes to the inbox, not to the hold');
  assert.equal(mustHold([head, { type: 'compaction/start' }], false), true, 'a compaction holds it with or without an agent');
  assert.equal(mustHold([head, start, end, { type: 'session/end-seed' }], true), false);
});

test('a compaction is open from its start to its end, failed or committed', () => {
  assert.equal(compactionOpen([{ type: 'compaction/start' }]), true);
  assert.equal(compactionOpen([{ type: 'compaction/start' }, { type: 'user/message' }]), true);
  assert.equal(compactionOpen([{ type: 'compaction/start' }, { type: 'compaction/end', data: { error: {} } }]), false);
  assert.equal(compactionOpen([{ type: 'user/message' }]), false);
  assert.equal(compactionOpen([{ type: 'compaction/start' }, { type: 'session/end-seed' }, { type: 'user/message' }]), false,
    'a compaction the process stopped in runs no more once the conversation is opened again');
});

test('a held line joins the conversation once, after the result, in arrival order', () => {
  const appended = [], written = [], core = { held: new Map(), written: (session, receipts) => written.push(...receipts) };
  const session = { id: 's', snapshotEvents: () => [], append: (type, data) => appended.push(data.source.receipt) };
  hold(core, 's', line('r1')); hold(core, 's', line('r2')); hold(core, 's', line('r1'));
  assert.equal(isHeld(core, 's', 'r2'), true);
  assert.equal(release(core, session), true);
  assert.deepEqual(appended, ['r1', 'r2']);
  assert.deepEqual(written, ['r1', 'r2'], 'their receipts are acknowledged as they are written, not when held');
  assert.equal(release(core, session), false, 'released once');
});

// A held line is written when the step that held it ends. Fakes stand for the session and the core's listener.
function boundary(events) {
  const appended = [], written = [], flushed = [], listeners = [];
  const core = { held: new Map(), written: (session, receipts) => written.push(...receipts),
    ctx: { on: (name, listener) => { assert.equal(name, 'session/event'); listeners.push(listener); return () => {}; },
      sessions: { flush: async () => { flushed.push(1); } }, logger: { warn: () => {} } } };
  const session = { id: 's', snapshotEvents: () => events,
    append: (type, data) => { appended.push(data.source?.receipt ?? type); events.push({ type, data }); } };
  releaseAtBoundary(core);
  const fire = type => { events.push({ type }); for (const listener of listeners) listener(session, { type }); };
  return { core, session, appended, written, flushed, fire };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('a held line is written once when its step ends, after the step\'s last result, and acknowledged after it is written', async () => {
  const call = { type: 'tool/call', data: { callId: 'c1' } };
  const result = { type: 'tool/result', data: { message: { source: { callId: 'c1' } } } };
  const events = [{ type: 'system/message' }, { type: 'step/start' }, call, result];
  const { core, session, appended, written, flushed, fire } = boundary(events);
  hold(core, 's', line('r1')); hold(core, 's', line('r2'));
  fire('step/end');
  assert.deepEqual(appended, [], 'not inside the observer that saw the event');
  await tick();
  assert.deepEqual(appended, ['r1', 'r2'], 'in arrival order');
  assert.ok(events.findIndex(event => event.data?.source?.receipt === 'r1') > events.indexOf(result), 'after the result');
  assert.deepEqual(written, ['r1', 'r2']);
  assert.equal(flushed.length, 1);
  assert.equal(isHeld(core, 's', 'r1'), false);
});

test('a step that fails or is aborted still releases its held lines: turn-stopping never ran', async () => {
  // DSH: the error leaves the loop, `step/end` is appended in a finally, then `turn/end`; agent/turn-stopping is not dispatched.
  const events = [{ type: 'system/message' }, { type: 'step/start' }];
  const { core, appended, fire } = boundary(events);
  hold(core, 's', line('r1'));
  fire('step/end');
  fire('turn/end');
  await tick();
  assert.deepEqual(appended, ['r1']);
});

test('a line held through a compaction that ends inside a step waits for the step\'s end', async () => {
  const events = [{ type: 'system/message' }, { type: 'step/start' }, { type: 'compaction/start' }];
  const { core, appended, fire } = boundary(events);
  hold(core, 's', line('r1'));
  fire('compaction/end');
  await tick();
  assert.deepEqual(appended, [], 'the step is still open: not written inside it');
  fire('step/end');
  await tick();
  assert.deepEqual(appended, ['r1']);
});

test('a release that throws is logged and never an uncaught exception', async () => {
  const events = [{ type: 'system/message' }, { type: 'step/start' }];
  const { core, session, fire } = boundary(events), warned = [];
  core.ctx.logger.warn = text => warned.push(text);
  session.append = () => { throw new Error('the log refused the append'); };
  hold(core, 's', line('r1'));
  fire('step/end');
  await tick();
  assert.equal(warned.length, 1);
  assert.match(warned[0], /not released: Error: the log refused the append/);
});

test('a line held when the next step starts before the microtask runs is not written twice', async () => {
  const events = [{ type: 'system/message' }, { type: 'step/start' }];
  const { core, session, appended, fire } = boundary(events);
  hold(core, 's', line('r1'));
  fire('step/end');
  release(core, session);                                  // agent/pre-step of the next step got there first
  await tick();
  assert.deepEqual(appended, ['r1']);
});

test('a line already between a call and its result is emptied in place on a real DSH session', async t => {
  const ctx = new Context();
  new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx);
  t.after(() => ctx.fiber.dispose());
  await ctx.fiber.ready?.();
  const session = await ctx.sessions.create('pairing');
  session.append('user/message', line('before'), { surfaceOp: 'append' });
  session.append('tool/call', { turn: 1, step: 1, callId: 'c1', name: 'recall', arguments: {} });
  const stray = session.append('user/message', line('during'), { surfaceOp: 'append' }).seq;
  session.append('tool/result', { turn: 1, step: 1, message: createToolResultMessage({ callId: 'c1',
    content: [{ type: 'text', text: '结果' }], isError: false }) }, { surfaceOp: 'append' });
  assert.deepEqual(strayLines(session.snapshotEvents(), session.surface.nodes), [stray]);
  assert.equal(repair(session), 1);
  assert.deepEqual(strayLines(session.snapshotEvents(), session.surface.nodes), [], 'repaired once');
  assert.equal(repair(session), 0);
  const kept = session.surface.nodes.map(seq => session.snapshotEvents(seq, seq + 1)[0]);
  const emptied = kept.find(event => event.type === 'user/message' && event.data.source.receipt === 'during');
  assert.deepEqual(emptied.data.content, [], 'the line keeps its place, with nothing sent');
  assert.equal(kept.find(event => event.data.source?.receipt === 'before').data.content.length, 1);
});
