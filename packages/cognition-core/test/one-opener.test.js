import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore } from '../src/index.js';

/** A conversation is opened by one writer at a time: a line written into it while it is not loaded holds its file, and
 * DSH refuses to load it meanwhile (a relevance gate failed that way, 2026-10-15). */
test('loading a conversation waits for a line being written into it, and loads of it queue', async () => {
  const order = [];
  let finishWrite;
  const core = { channelWrites: new Map(), opening: new Map(),
    openAgent: async stage => { order.push('open ' + stage.tag); await null; order.push('opened ' + stage.tag); return stage.tag; } };
  const ensure = stage => CognitionCore.prototype.ensureAgent.call(core, { session_id: 's', ...stage });
  core.channelWrites.set('s', new Promise(resolve => { finishWrite = resolve; }).then(() => order.push('written')));
  const first = ensure({ tag: 'a' }), second = ensure({ tag: 'b' });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(order, [], 'nothing opens while the line is being written');
  finishWrite();
  assert.deepEqual(await Promise.all([first, second]), ['a', 'b']);
  assert.deepEqual(order, ['written', 'open a', 'opened a', 'open b', 'opened b']);
  assert.equal(core.opening.size, 0, 'nothing left behind');
  core.channelWrites.set('t', Promise.reject(new Error('write failed')));
  assert.equal(await CognitionCore.prototype.ensureAgent.call(core, { session_id: 't', tag: 'c' }), 'c',
    'a failed write does not stop the load');
});
