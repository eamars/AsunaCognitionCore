import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore } from '../src/index.js';

const route = { provider: 'local', model: 'm', reasoningEffort: 'high', maxTokens: 1024 };

function core(services) {
  const ctx = { get: name => services[name], agents: { get: id => services.agents?.[id] }, llm: {} };
  return new CognitionCore(ctx, { routes: { character: route }, deployment: {} });
}

test('ADR-049: a conversation is condensed on request through DSH compaction, never during a turn there', async () => {
  const calls = [];
  const agent = { id: 'role-g' };
  const compaction = { compactNow: async (target, signal) => {
    calls.push([target, signal instanceof AbortSignal]);
    return { shadowedSeqs: [1, 2, 3], shadowedTokenCount: 4096 };
  } };
  const asuna = core({ compaction, agents: { 'role-g': agent } });
  assert.deepEqual(await asuna.compactSession({ session_id: 'role-g', scene_id: 'g' }),
    { compacted: true, items: 3, tokens: 4096 });
  assert.deepEqual(calls, [[agent, true]]);

  asuna.states.set('role-g', { current: { token: 'turn-1' } });
  assert.deepEqual(await asuna.compactSession({ session_id: 'role-g', scene_id: 'g' }),
    { compacted: false, reason: 'busy' });
  assert.equal(calls.length, 1, 'a running turn is never cut into');
});

test('ADR-049: without a compaction service, or with nothing to condense, it says so', async () => {
  assert.deepEqual(await core({}).compactSession({ session_id: 's', scene_id: 'g' }),
    { compacted: false, reason: 'no_compaction_service' });
  const empty = core({ compaction: { compactNow: async () => null }, agents: { s: {} } });
  assert.deepEqual(await empty.compactSession({ session_id: 's', scene_id: 'g' }),
    { compacted: false, reason: 'nothing_to_compact' });
});

test('ADR-049: a stage result carries how long the conversation was on that request', () => {
  const asuna = core({});
  const last = { seq: 9, data: { message: { content: [{ type: 'text', text: '好' }] },
    usage: { inputTokens: 300, cacheReadTokens: 150000, cacheWriteTokens: 0, outputTokens: 20 } } };
  const result = asuna.result({ token: 'op' }, 'role-g', last, 'stop');
  assert.equal(result.prompt_tokens, 150300);
  assert.equal(asuna.result({ token: 'op' }, 'role-g', { ...last, data: { ...last.data, usage: undefined } }, 'stop')
    .prompt_tokens, undefined);
});
