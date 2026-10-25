import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import { CognitionCore } from '../src/index.js';
import RoleCompactionEngine, { summaryAsNextRequest } from '../src/compaction.js';

// ADR-094 §10.2: a compaction summary is sent as its conversation's next request would be, per instance across the
// action brain's two tiers.
const LOCAL = { reasoning: { efforts: ['low', 'medium', 'high'].map(id => ({ id })), defaultEffort: 'medium' },
  defaultMaxTokens: 32768 };
const HOSTED = { reasoning: { efforts: ['low', 'medium', 'high'].map(id => ({ id })), defaultEffort: 'high' },
  defaultMaxTokens: 128000 };

function host({ routes = {}, preset } = {}) {
  const calls = [];
  const ctx = { get: name => name === 'agentPresets'
    ? { serviceFor: () => (preset ? { summaryReasoningEffort: preset } : {}) } : undefined,
  llm: { resolveModelInfo: async (provider, model) => (model === 'hosted' ? HOSTED : LOCAL) } };
  const core = new CognitionCore(ctx, { persona: 'p', routes: {
    character: { provider: 'local-c', model: 'local', reasoningEffort: 'high', maxTokens: 32768, groupEffort: 'medium' },
    action: { provider: 'local-a', model: 'local', reasoningEffort: 'high', maxTokens: 32768 },
    actionHigh: { provider: 'cloud', model: 'hosted', reasoningEffort: 'medium' }, ...routes } });
  core.personas.set('p', { preset: 'asuna-p' });
  core.worker = { call: async (method, value) => { calls.push([method, value]); return {}; } };
  return { core, calls };
}

const agentOf = (id, preset, header) => ({ id, session: { id, header: { agentPreset: preset },
  snapshotEvents: () => [], requestHeader: () => (header ? { config: header } : undefined) }, options: {} });

test('an action job\'s summary goes where its next request goes: 高 while on 高, 低 after it fell, at that tier\'s level and limit', async () => {
  const { core, calls } = host();
  const job = agentOf('act', 'asuna-action', { provider: 'cloud', model: 'hosted', reasoningEffort: 'medium' });
  core.state('act').current = { token: 't', task: { _id: 'k', tier: 'high' } };
  assert.deepEqual(await core.summaryInstance(job), { lane: 'executor', from: "the conversation's", provider: 'cloud',
    model: 'hosted', reasoningEffort: 'medium', maxTokens: 128000 }, '高: its own level, the model\'s own limit');
  core.state('act').fell = true;                              // the job fell to 低; its last header still names 高
  assert.deepEqual(await core.summaryInstance(job), { lane: 'executor', from: "the conversation's", provider: 'local-a',
    model: 'local', reasoningEffort: 'high', maxTokens: 32768 }, 'never the model it fell from, nor that model\'s level');
  core.state('act').fell = false;
  core.highRest = { reason: 'rate limit', until: new Date(Date.now() + 60_000).toISOString() };
  assert.equal((await core.summaryInstance(job)).provider, 'local-a', '高 resting: the step will fall, so 低');
  assert.equal(core.state('act').fell, false, 'asking records nothing: the step\'s own request decides the fall');
  assert.equal(calls.length, 0);
  assert.equal(core.tierRoute(job, core.state('act').current), undefined);
  assert.equal(core.state('act').fell, true, 'the request itself still falls');
});

test('her conversation\'s summary takes its stage\'s level; a route with no level takes the preset\'s, else the model\'s default, never none', async () => {
  const { core } = host();
  core.efforts = { group: 'medium' };                         // stageEfforts, as the Host reads them at start
  const group = agentOf('g', 'asuna-p');
  core.state('g').current = { token: 't', scene_kind: 'group' };
  assert.equal((await core.summaryInstance(group)).reasoningEffort, 'medium', 'a group turn\'s own effort');
  core.state('g').current = { token: 't', scene_kind: 'dm' };
  assert.equal((await core.summaryInstance(group)).reasoningEffort, 'high');
  const plain = host({ routes: { action: { provider: 'local-a', model: 'local', maxTokens: 32768 } }, preset: 'low' });
  const job = agentOf('a', 'asuna-action');
  assert.deepEqual([(await plain.core.summaryInstance(job)).reasoningEffort, (await plain.core.summaryInstance(job)).from],
    ['low', "the preset's"]);
  const none = host({ routes: { action: { provider: 'local-a', model: 'local', maxTokens: 32768 } }, preset: 'xhigh' });
  assert.deepEqual([(await none.core.summaryInstance(job)).reasoningEffort, (await none.core.summaryInstance(job)).from],
    ['medium', "the model's default"], 'a preset level the model does not offer: the model\'s default');
  assert.equal(await core.summaryInstance(agentOf('x', 'someone-else')), undefined, 'a session not hers');
});

test('the summary listener sends a mismatched summary request again as the next request would go; others pass', async () => {
  let listener;
  const sent = [];
  const logged = [];
  const instance = { lane: 'executor', from: "the conversation's", provider: 'local-a', model: 'local',
    reasoningEffort: 'high', maxTokens: 32768 };
  const ctx = { on: (name, fn, options) => { assert.equal(name, 'llm/stream'); assert.equal(options.global, true); listener = fn; },
    agents: { get: id => (id === 'act' ? agentOf('act', 'asuna-action') : undefined) },
    logger: { info: line => logged.push(line) },
    llm: { async *stream(options) { sent.push(options); yield { type: 'finish', reason: { kind: 'stop' } }; } } };
  summaryAsNextRequest({ ctx, summaryInstance: async () => instance });
  const drain = async stream => { const out = []; for await (const chunk of stream) out.push(chunk); return out; };
  let passed = 0;
  const next = () => (async function* () { passed += 1; yield { type: 'finish', reason: { kind: 'stop' } }; })();
  const dsh = { provider: 'cloud', model: 'hosted', maxTokens: 8192, sessionId: 'act', purpose: 'compaction', messages: [] };
  await drain(listener(dsh, next));
  assert.equal(passed, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(sent[0])), { ...dsh, provider: 'local-a', model: 'local', maxTokens: 32768,
    reasoningEffort: 'high' });
  assert.match(logged.at(-1), /thinks at "high" \(the conversation's\), output limit 32768, on local-a\/local \(executor\) in act$/);
  // The request it sent comes round again and passes on, and so do a matching one, a turn's request and another session's.
  await drain(listener(sent[0], next));
  await drain(listener({ ...dsh, ...instance, lane: undefined, from: undefined }, next));
  await drain(listener({ ...dsh, purpose: undefined }, next));
  await drain(listener({ ...dsh, sessionId: 'other' }, next));
  assert.equal(passed, 4);
  assert.equal(sent.length, 1);
});

test('her conversation\'s own engine asks the Host too: the instance\'s level, and its limit for the request and the fit check', async t => {
  let sent;
  const logged = [];
  const plugins = new Context();
  t.after(() => plugins.fiber.dispose());
  const engine = new RoleCompactionEngine(plugins, { maxTokens: 24576, summaryReasoningEffort: 'medium', auto: false });
  const instance = { lane: 'character', from: "the conversation's", provider: 'local-c', model: 'local',
    reasoningEffort: 'high', maxTokens: 32768 };
  engine.ctx = { get: name => (name === 'asuna' ? { summaryInstance: async () => instance } : undefined),
    logger: { info: line => logged.push(line) },
    llm: { resolveModelInfo: async () => assert.fail('the Host decided'),
      async *stream(options) {
        sent = options;
        yield { type: 'text-delta', index: 0, text: ['## 对话脉络', '## 未了的话头', '## 答应过的事', '## 更正与分歧',
          '## 对方此刻', '## 委托中的事'].join('\n- （无）\n') + '\n- （无）' };
        yield { type: 'finish', reason: { kind: 'stop' } };
      } } };
  const agent = { session: { id: 's', requestHeader: () => ({ config: { provider: 'old', model: 'gone' } }), toolHistory: () => [] },
    options: {} };
  await engine.summarize({ messages: [{ role: 'user', content: [{ type: 'text', text: '在吗' }] }] }, agent);
  assert.deepEqual([sent.provider, sent.model, sent.reasoningEffort, sent.maxTokens], ['local-c', 'local', 'high', 32768]);
  assert.match(logged.at(-1), /thinks at "high" \(the conversation's\), output limit 32768, on local-c\/local \(character\) in s$/);
});
