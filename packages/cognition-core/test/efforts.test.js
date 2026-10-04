import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore } from '../src/index.js';

const route = { provider: 'local', model: 'm', reasoningEffort: 'high', maxTokens: 1024 };
const offering = (...ids) => ({ llm: { resolveModelInfo: async () => ({ reasoning: { efforts: ids.map(id => ({ id })) } }) } });

test('the gate thinks briefly; group turns use the deployment group effort; only efforts the model offers', async () => {
  const core = new CognitionCore(offering('low', 'medium', 'high'),
    { routes: { character: route }, deployment: { reasoning_effort: { group: 'medium' } } });
  core.efforts = await core.stageEfforts();
  assert.equal(core.effortFor('attend'), 'low');
  assert.equal(core.effortFor('character', { scene_kind: 'group' }), 'medium');
  assert.equal(core.effortFor('character', { scene_kind: 'dm' }), undefined, 'the local chat keeps the route effort');
  assert.equal(core.effortFor('executor', { scene_kind: 'group' }), undefined);
  const limited = new CognitionCore(offering('high'), { routes: { character: route }, deployment: {} });
  limited.efforts = await limited.stageEfforts();
  assert.equal(limited.effortFor('attend'), undefined, 'an effort the model lacks falls back to the route');
});
