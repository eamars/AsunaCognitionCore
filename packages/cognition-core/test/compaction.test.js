import test from 'node:test';
import assert from 'node:assert/strict';
import { CONTEXT_WINDOW_EXCEEDED_CODE } from '@deepseek-ai/dsh-llm';
import RoleCompactionEngine, { ROLE_COMPACTION_INSTRUCTION, inSteps } from '../src/compaction.js';

// The role summary must reuse the replayed prefix byte for byte (provider cache)
// and differ from DSH's request only in the final, Chinese instruction.
test('role compaction keeps the replayed prefix and asks for a Chinese role-play checkpoint', async () => {
  let sent;
  const engine = Object.create(RoleCompactionEngine.prototype);
  engine.config = { summarizationProvider: '', summarizationModel: '', maxTokens: 24576 };
  engine.ctx = { llm: { async *stream(options) {
    sent = options;
    yield { type: 'text-delta', index: 0, text: '## 对话脉络\n- 聊到周末安排' };
    yield { type: 'finish', reason: { kind: 'stop' } };
  } } };
  const prefix = [{ role: 'system', content: [{ type: 'text', text: 'render' }] },
    { role: 'user', content: [{ type: 'text', text: '周末去哪' }] }];
  const agent = { session: { id: 's', requestHeader: () => ({ config: { provider: 'p', model: 'm' } }), toolHistory: () => [] },
    options: {} };
  const result = await engine.summarize({ messages: prefix }, agent);
  assert.deepEqual(sent.messages.slice(0, 2), prefix);
  assert.equal(sent.messages.at(-1).content[0].text, ROLE_COMPACTION_INSTRUCTION);
  assert.doesNotMatch(ROLE_COMPACTION_INSTRUCTION, /coding assistant|English/);
  assert.equal(sent.provider, 'p');
  assert.equal(sent.purpose, 'compaction');
  assert.equal(result.summary[0].text, '## 对话脉络\n- 聊到周末安排');

  engine.ctx.llm.stream = async function *() { yield { type: 'finish', reason: { kind: 'max-tokens' } }; };
  await assert.rejects(engine.summarize({ messages: prefix }, agent), { code: 'MAX_TOKENS' });
});

// ADR-028/049: a span too large for one summary request (a quiet group's whole conversation) is summarized in steps.
test('a span the model refuses for its window is summarized in steps, cut only before a user message', async () => {
  const user = text => ({ role: 'user', content: [{ type: 'text', text }] });
  const body = [user('a'), { role: 'assistant', content: [{ type: 'tool-call', id: 'c' }] },
    { role: 'tool', content: [{ type: 'text', text: 'r' }] }, user('b'), user('c'), user('d')];
  const tooLong = () => Object.assign(new Error('too long'), { code: CONTEXT_WINDOW_EXCEEDED_CODE });
  const sent = [];
  const once = async messages => {
    sent.push(messages.map(message => message.content[0].text ?? message.role));
    if (messages.length > 5) throw tooLong();
    return { summary: [{ type: 'text', text: 'S' + sent.length }] };
  };
  const result = await inSteps([{ role: 'system', content: [{ type: 'text', text: 'sys' }] }], body, once);
  assert.equal(result.summary[0].text, 'S3');
  assert.deepEqual(sent[1], ['sys', 'a', 'assistant', 'r'], 'the tool call keeps its result');
  assert.deepEqual(sent[2], ['sys', '<compacted-summary>\nS2\n</compacted-summary>', 'b', 'c', 'd']);
  // A single message too large, or any other failure, stays DSH's to handle.
  await assert.rejects(inSteps([], [user('x')], async () => { throw tooLong(); }), /too long/);
  await assert.rejects(inSteps([], body, async () => { throw new Error('refused'); }), /refused/);
});

test('the size floor is half the engine\'s own compaction threshold for the conversation\'s model', async () => {
  const engine = Object.create(RoleCompactionEngine.prototype);
  engine.config = { thresholdRatio: 0.8, headroomTokens: 6144, modelPolicies: [] };
  engine.ctx = { llm: { resolveModelInfo: async () => ({ context: { contextWindow: 262144 }, defaultMaxTokens: 32768 }) } };
  const agent = { session: { requestHeader: () => ({ config: { provider: 'p', model: 'm', maxTokens: 32768 } }) }, options: {} };
  assert.equal(await engine.floorTokens(agent), Math.floor(Math.floor(262144 * 0.8) / 2));
  engine.ctx.llm.resolveModelInfo = async () => ({});
  assert.equal(await engine.floorTokens(agent), undefined, 'no window declared: no floor');
});
