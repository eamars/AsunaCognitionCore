import test from 'node:test';
import assert from 'node:assert/strict';
import RoleCompactionEngine, { ROLE_COMPACTION_INSTRUCTION } from '../src/compaction.js';

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
