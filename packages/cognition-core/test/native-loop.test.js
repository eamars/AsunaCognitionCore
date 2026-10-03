// Installed DSH loop and scope services; only inference and business I/O are
// synthetic. Live-model/Web evidence is recorded separately in NATIVE_PLUGIN.md.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools, { defineTool } from '@deepseek-ai/dsh-tools';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import { CognitionCore } from '../src/index.js';
import { asunaRender, attachImage } from '../src/tool-output.js';

async function harness(t, finish = 'stop') {
  const ctx = new Context();
  new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx);
  new AgentRegistry(ctx); new SystemPrompt(ctx, {}); new Tools(ctx);
  new AgentLoop(ctx, { agents: [], maxParallelToolCalls: 4 });
  new Loader(ctx, { baseUrl: import.meta.url });
  new AgentPresetRegistry(ctx, { default: 'asuna', selectedDefault: { get: () => undefined } });
  const requests = [];
  let enter;
  const entered = new Promise(resolve => { enter = resolve; });
  class Adapter extends LlmAdapter {
    async *stream(options) {
      requests.push(options);
      enter();
      if (finish === 'wait') await new Promise((_, reject) => {
        options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
      });
      yield { type: 'text-delta', index: 0, text: 'actual native assistant event' };
      yield { type: 'finish', reason: { kind: finish } };
    }
  }
  ctx.llm.registerAdapter(['fixture'], new Adapter());
  const core = new CognitionCore(ctx, { routes: { character: { provider: 'fixture', model: 'one-model' } } });
  core.ready = async () => {};
  ctx.provide('asuna', core);
  const business = [];
  core.worker = { async call(method, args) {
    business.push({ method, args });
    if (method === 'input') await core.onEvent({ kind: 'stage', session_id: args.session_id,
      token: 'stage-' + args.session_id, phase: 'MONOLOGUE', lane: 'character',
      system: 'Current persona from existing state: ' + args.session_id, text: 'Internal context' });
    if (method === 'result') await core.onEvent({ kind: 'episode_finished', session_id: args.token.slice(6) });
    return { accepted: true };
  } };
  const handles = [];
  t.after(async () => { for (const handle of handles) await handle.dispose(); await ctx.fiber.dispose(); });
  await ctx.agentPresets.register({ id: 'asuna', plugins: [{ name: new URL('../src/role.js', import.meta.url).href }] });
  await ctx.agentPresets.register({ id: 'ordinary', plugins: [] });
  async function create(id, asuna = true) {
    const handle = await ctx.agents.create({ sessionId: id, agentOptions: { provider: 'fixture', model: 'one-model' },
      setup: async scope => { await ctx.agentPresets.mount(scope, asuna ? 'asuna' : 'ordinary'); } });
    handles.push(handle);
    return handle.agent;
  }
  return { ctx, core, requests, business, create, entered };
}

test('first native request has persona; one real input and no duplicate assistant history', async t => {
  const h = await harness(t);
  const role = await h.create('role');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Human input' }] }));
  await role.whenIdle();
  assert.equal(h.requests.length, 1);
  assert.match(JSON.stringify(h.requests[0].messages), /Current persona from existing state/);
  assert.equal(h.business.filter(x => x.method === 'input').length, 1);
  const events = role.session.snapshotEvents();
  assert.equal(events.filter(x => x.type === 'assistant/message').length, 1);
  assert.equal(events.filter(x => x.type === 'user/message' && x.data.source.kind === 'user').length, 1);
  assert.equal(events.filter(x => x.type === 'user/message' && x.data.source.kind === 'asuna').length, 1);
  assert.equal(h.business.find(x => x.method === 'result').args.result.content, 'actual native assistant event');
});

test('ordinary native sessions retain their own prompt, tools and input handling', async t => {
  const h = await harness(t);
  h.ctx.tools.register(defineTool({ name: 'ordinary_tool', description: 'ordinary only', parameters: {},
    output: { schema: { type: 'json' }, render: () => [] }, execute: () => ({}) }));
  await h.create('role');
  const ordinary = await h.create('ordinary', false);
  ordinary.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Ordinary input' }] }));
  await ordinary.whenIdle();
  assert.equal(h.business.length, 0);
  assert.doesNotMatch(JSON.stringify(h.requests[0].messages), /Current persona|Internal context/);
  assert.ok(h.requests[0].tools.some(x => x.name === 'ordinary_tool'));
});

test('native max-token finish remains incomplete at the business boundary', async t => {
  const h = await harness(t, 'max-tokens');
  const role = await h.create('role');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Input' }] }));
  await role.whenIdle();
  assert.equal(h.business.find(x => x.method === 'result').args.result.finish_reason, 'length');
});

test('one standing preset serves two role agents without sharing input or persona state', async t => {
  const h = await harness(t);
  const first = await h.create('role-one');
  const second = await h.create('role-two');
  for (const agent of [first, second]) agent.followup(createUserMessage({ source: { kind: 'user' },
    content: [{ type: 'text', text: 'Input for ' + agent.id }] }));
  await Promise.all([first.whenIdle(), second.whenIdle()]);
  assert.equal(h.requests.length, 2);
  for (const id of ['role-one', 'role-two']) {
    const request = h.requests.find(x => JSON.stringify(x.messages).includes('Input for ' + id));
    assert.match(JSON.stringify(request.messages), new RegExp('Current persona from existing state: ' + id));
    assert.equal(h.business.filter(x => x.method === 'input' && x.args.session_id === id).length, 1);
    assert.equal(h.business.filter(x => x.method === 'result' && x.args.token === 'stage-' + id).length, 1);
  }
});

test('removing a blank role preset removes every Asuna hook and inherited-tool restriction', async t => {
  const h = await harness(t);
  h.ctx.tools.register(defineTool({ name: 'ordinary_tool', description: 'ordinary only', parameters: {},
    output: { schema: { type: 'json' }, render: () => [] }, execute: () => ({}) }));
  const agent = await h.create('role');
  await h.ctx.agentPresets.select(agent, 'ordinary');
  agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Ordinary input' }] }));
  await agent.whenIdle();
  assert.equal(h.business.length, 0);
  assert.doesNotMatch(JSON.stringify(h.requests[0].messages), /Current persona|Internal context/);
  assert.ok(h.requests[0].tools.some(x => x.name === 'ordinary_tool'));
});

test('image tool results persist bytes before returning a native image block', async () => {
  let saved;
  const value = await attachImage({ attachments: { async saveImage(image) {
    saved = image; return { attachmentId: 'native-image', mediaType: 'image/png' };
  } } }, { image: { media_type: 'image/png', data: 'YWJj' }, ref: 'authorized' });
  assert.equal(Buffer.from(saved.data).toString(), 'abc');
  const blocks = asunaRender({}, value);
  assert.equal(blocks[0].type, 'image');
  assert.doesNotMatch(JSON.stringify(blocks), /YWJj/);
});

test('native cancellation fails the pending business stage instead of reporting success', async t => {
  const h = await harness(t, 'wait');
  const role = await h.create('role');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Input' }] }));
  await h.entered;
  role.cancel({ kind: 'user' });
  await role.whenIdle();
  const results = h.business.filter(x => x.method === 'result');
  assert.equal(results.length, 1);
  assert.ok(results[0].args.error);
  assert.equal(results[0].args.result, undefined);
  assert.equal(role.session.snapshotEvents().findLast(x => x.type === 'turn/end').data.reason.kind, 'aborted');
});

test('selecting recovery on an existing blank native session exposes its independent project tools', async t => {
  const h = await harness(t);
  let ordinaryCalls = 0;
  h.ctx.tools.register(defineTool({ name: 'ordinary_tool', description: 'Not a recovery capability', parameters: {},
    output: { schema: { type: 'json' }, render: () => [] }, execute: () => { ordinaryCalls++; return {}; } }));
  h.ctx.provide('asunaFloor', { config: { route: { provider: 'fixture', model: 'one-model' } },
    call: async () => ({ state: 'NO_CHANGES' }) });
  await h.ctx.agentPresets.register({ id: 'recovery', plugins: [{ name: new URL('../src/recovery.js', import.meta.url).href }] });
  const agent = await h.create('repair', false);
  await h.ctx.agentPresets.select(agent, 'recovery');
  agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Inspect the project' }] }));
  await agent.whenIdle();
  assert.deepEqual((h.requests[0].tools ?? []).map(tool => tool.name).sort(),
    ['development_files', 'development_publish', 'development_read', 'development_run', 'development_write']);
  assert.equal(h.business.length, 0);
  await h.ctx.tools.execute({ callId: 'denied-recovery-call', name: 'ordinary_tool', arguments: {},
    agent, signal: new AbortController().signal });
  assert.equal(ordinaryCalls, 0);
});
