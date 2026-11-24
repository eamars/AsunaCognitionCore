// ADR-135 D8: the guard's door in the plugin. In an outside conversation or task a call the step does not offer is
// asked of the worker and comes back as the worker's sentence; a denial a body raised and a local address an outside
// task's fetch reached come back the same way. The result is error-shaped with the sentence as its only content: DSH
// keeps such a result's content as it is (a thrown body would be prefixed). At home the call runs as before.
import test from 'node:test';
import assert from 'node:assert/strict';
import { LAN_REFUSED } from '../src/fetch.js';

const SENTENCE = '这一步没有做。';

async function door(state, lane, exec, run, replies = {}) {
  const { CognitionCore } = await import('../src/index.js');
  const asked = [];
  const plugin = { state: () => state, exposed: () => new Set(['speak']), roleAliases: {},
    outside: CognitionCore.prototype.outside, deny: CognitionCore.prototype.deny,
    worker: { call: async (method, args) => { asked.push([method, args.tool]); return replies[method] ?? {}; } } };
  const result = await CognitionCore.prototype.door.call(plugin, lane, { agent: { session: { id: 's' } }, ...exec }, run);
  return { result, asked };
}

const only = text => ({ isError: true, error: { message: text }, content: [{ type: 'text', text }] });
const never = () => { throw new Error('the call ran'); };

test('an outside call the step does not offer is the worker\'s sentence, as the whole result', async () => {
  const mine = await door({ current: { outside: true, token: 't' } }, 'character', { name: 'set_policy', callId: 'c1' },
    never, { role_tool: { denied: SENTENCE } });
  assert.deepEqual(mine.result, only(SENTENCE));
  assert.deepEqual(mine.asked, [['role_tool', 'set_policy']]);
  const task = await door({ outside: true, current: { token: 't' } }, 'executor', { name: 'sandbox_run', callId: 'c2' },
    never, { tool: { asuna_guard: true, denied: SENTENCE } });
  assert.deepEqual(task.result, only(SENTENCE));
});

test('a denial its body raised and an outside task\'s local address come back as the sentence', async () => {
  const state = { outside: true, current: { token: 't' } };
  const { CognitionCore } = await import('../src/index.js');
  const raised = await door(state, 'character', { name: 'speak', callId: 'c3' }, async () => {
    CognitionCore.prototype.deny.call({ state: () => state }, 's', 'c3', SENTENCE);
    return { isError: true, content: [{ type: 'text', text: 'Error: ' + SENTENCE }] };
  });
  assert.deepEqual(raised.result, only(SENTENCE));
  const lan = await door(state, 'executor', { name: 'speak', callId: 'c4' },
    async () => ({ isError: true, content: [{ type: 'text', text: 'Error: blocked ' + LAN_REFUSED }] }),
    { 'guard.task': { sentence: SENTENCE } });
  assert.deepEqual(lan.result, only(SENTENCE));
  assert.deepEqual(lan.asked, [['guard.task', 'speak']]);
});

test('at home the call runs as before and nothing is asked', async () => {
  const ran = { content: [{ type: 'text', text: 'ok' }] };
  const home = await door({ current: { outside: false } }, 'character', { name: 'set_policy', callId: 'c5' }, async () => ran);
  assert.equal(home.result, ran);
  assert.deepEqual(home.asked, []);
});
