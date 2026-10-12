import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore } from '../src/index.js';

const route = { provider: 'local', model: 'm', reasoningEffort: 'high', maxTokens: 1024 };

function core(services) {
  const ctx = { get: name => services[name], agents: { get: id => services.agents?.[id] }, llm: {} };
  return new CognitionCore(ctx, { routes: { character: route }, deployment: {} });
}

test('ADR-049: a conversation is condensed through its own /compact command, never during a turn there', async () => {
  const calls = [];
  const agent = { id: 'role-g' };
  const commands = { execute: async (target, line, attachments, signal) => {
    calls.push([target, line, attachments.length, signal instanceof AbortSignal]);
    return { commandId: 'c1', result: { kind: 'success', text: 'Compacted 3 history items (~4096 tokens).' } };
  } };
  const asuna = core({ commands, agents: { 'role-g': agent } });
  assert.deepEqual(await asuna.compactSession({ session_id: 'role-g', scene_id: 'g' }),
    { compacted: true, items: 3, tokens: 4096 });
  assert.deepEqual(calls, [[agent, '/compact', 0, true]]);

  asuna.states.set('role-g', { current: { token: 'turn-1' } });
  assert.deepEqual(await asuna.compactSession({ session_id: 'role-g', scene_id: 'g' }),
    { compacted: false, reason: 'busy' });
  assert.equal(calls.length, 1, 'a running turn is never cut into');
});

test('ADR-049: no commands service, no /compact for the session, nothing to condense, or a failure: it says which', async () => {
  assert.deepEqual(await core({}).compactSession({ session_id: 's', scene_id: 'g' }),
    { compacted: false, reason: 'no_commands_service' });
  const answer = result => core({ commands: { execute: async () => result }, agents: { s: {} } })
    .compactSession({ session_id: 's', scene_id: 'g' });
  assert.deepEqual(await answer(undefined), { compacted: false, reason: 'no_compact_command' });
  assert.deepEqual(await answer({ result: { kind: 'success', text: 'No compactable history yet.' } }),
    { compacted: false, reason: 'nothing_to_compact' });
  assert.deepEqual(await answer({ result: { kind: 'error', text: 'Compaction cancelled.' } }),
    { compacted: false, reason: 'Compaction cancelled.' });
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

test('ADR-049: a conversation\'s size is DSH\'s own measure, with the floor its compaction engine sets', async () => {
  const agent = { id: 'role-g', session: { id: 'role-g' } };
  const engine = { floorTokens: async target => (target === agent ? 104857 : undefined) };
  const asuna = core({ agents: { 'role-g': agent },
    tokenMeter: { measure: session => ({ totalTokens: session === agent.session ? 150000 : 0 }) },
    agentPresets: { serviceFor: (target, name) => (target === agent && name === 'compaction' ? engine : undefined) } });
  assert.deepEqual(await asuna.conversationSize({ session_id: 'role-g', scene_id: 'g' }), { tokens: 150000, floor: 104857 });
  const plain = core({ agents: { 'role-g': agent }, tokenMeter: { measure: () => ({ totalTokens: 1 }) },
    agentPresets: { serviceFor: () => ({}) } });
  assert.deepEqual(await plain.conversationSize({ session_id: 'role-g', scene_id: 'g' }), { reason: 'no_floor' });
});

test('ADR-063 D2: a copy counts as visible as far back as the tail her compaction keeps, else the fixed window', async () => {
  const agent = { id: 'role-g', session: { id: 'role-g' } }, meter = { measure: () => ({ nodes: [] }) };
  const asuna = core({ tokenMeter: meter,
    agentPresets: { serviceFor: () => ({ retainedTokens: async () => 36700 }) } });
  assert.deepEqual(await asuna.reach(agent), { tokens: 36700, meter });
  assert.deepEqual(await core({ tokenMeter: meter, agentPresets: { serviceFor: () => ({}) } }).reach(agent),
    { tokens: 32768 });
});
