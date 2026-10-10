import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore } from '../src/index.js';

const route = { provider: 'local', model: 'm', reasoningEffort: 'high', maxTokens: 1024 };
const offering = (...ids) => ({ llm: { resolveModelInfo: async () => ({ reasoning: { efforts: ids.map(id => ({ id })) } }) },
  get: () => undefined });

test('the gate and group turns take the efforts chosen on the card; empty is the route effort', async () => {
  const core = new CognitionCore(offering('low', 'medium', 'high'),
    { routes: { character: { ...route, attendEffort: 'low', groupEffort: 'medium' } }, deployment: {} });
  core.efforts = await core.stageEfforts();
  assert.equal(core.effortFor('attend'), 'low');
  assert.equal(core.effortFor('character', { scene_kind: 'group' }), 'medium');
  assert.equal(core.effortFor('character', { scene_kind: 'dm' }), undefined, 'the local chat keeps the route effort');
  assert.equal(core.effortFor('executor', { scene_kind: 'group' }), undefined);
  const plain = new CognitionCore(offering('high'), { routes: { character: route }, deployment: {} });
  plain.efforts = await plain.stageEfforts();
  assert.equal(plain.effortFor('attend'), undefined, 'nothing chosen: the route effort');
});

test('an effort the model does not offer is refused, not dropped', async () => {
  const core = new CognitionCore(offering('off', 'high', 'max'),
    { routes: { character: { ...route, groupEffort: 'medium' } }, deployment: {} });
  await assert.rejects(core.stageEfforts(), /INVALID_REASONING_EFFORT: character groupEffort/);
});

test('a brain without its own route uses DSH default model', () => {
  const ctx = { get: name => name === 'agentDefaultModel'
    ? { currentSelection: () => ({ provider: 'dsh-default', model: 'd', reasoningEffort: 'high' }) } : undefined };
  const core = new CognitionCore(ctx, { routes: { character: route, action: { maxTokens: 2048 } }, deployment: {} });
  assert.deepEqual(core.routeFor('character'), route);
  assert.deepEqual(core.routeFor('action'), { maxTokens: 2048, provider: 'dsh-default', model: 'd' });
  assert.equal(core.routeFor('appraiser'), undefined, 'the appraiser stays off when not chosen');
});
