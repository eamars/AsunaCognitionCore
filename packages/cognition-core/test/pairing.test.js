// A tool call and its result stay adjacent (pairing.js): a line that arrives while her tool call waits is held to the
// next step boundary, and a line already written between them is emptied in place on DSH's own surface.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { createToolResultMessage, createUserMessage } from '@deepseek-ai/dsh-llm';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import { compactionOpen, hold, isHeld, release, repair, strayLines, toolCallOpen } from '../src/pairing.js';

const line = (receipt, text = '群里的一句') => createUserMessage({ source: { kind: 'user', channel: 'qq', receipt },
  content: [{ type: 'text', text }] });

test('a tool call is open from its call to its result, and never past a step boundary', () => {
  const call = { type: 'tool/call', data: { callId: 'c1' } };
  const result = { type: 'tool/result', data: { message: { source: { callId: 'c1' } } } };
  assert.equal(toolCallOpen([{ type: 'step/start' }, call]), true);
  assert.equal(toolCallOpen([{ type: 'step/start' }, call, result]), false);
  assert.equal(toolCallOpen([call, { type: 'step/end' }]), false);
  assert.equal(toolCallOpen([{ type: 'step/start' }, call, { type: 'tool/call', data: { callId: 'c2' } }, result]), true,
    'one of two calls still waits');
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
