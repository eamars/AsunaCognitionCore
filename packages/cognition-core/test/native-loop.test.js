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
import Loader, { Group } from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import TokenMeter from '@deepseek-ai/dsh-token-meter';
import Commands from '@deepseek-ai/dsh-commands';
import { serviceForAgent } from '@deepseek-ai/dsh-agent-preset-registry';
import fs from 'node:fs/promises';
import YAML from 'yaml';
import { CognitionCore } from '../src/index.js';
import { asunaRender, attachImage } from '../src/tool-output.js';

async function harness(t, finish = 'stop', composition) {
  const ctx = new Context();
  new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx);
  new AgentRegistry(ctx); new SystemPrompt(ctx, {}); new Tools(ctx);
  new AgentLoop(ctx, { agents: [], maxParallelToolCalls: 4 });
  new Loader(ctx, { baseUrl: import.meta.url });
  new AgentPresetRegistry(ctx, { default: 'asuna', selectedDefault: { get: () => undefined } });
  if (composition) { ctx.loader.builtins.group = Group; new TokenMeter(ctx); new Commands(ctx); }
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
  await ctx.agentPresets.register({ id: 'asuna', plugins: composition ?? [{ name: new URL('../src/role.js', import.meta.url).href }] });
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
  assert.equal(h.requests.length, 1, JSON.stringify(role.session.snapshotEvents().filter(event => event.type === 'turn/end')));
  assert.match(JSON.stringify(h.requests[0].messages), /Current persona from existing state/);
  assert.equal(h.business.filter(x => x.method === 'input').length, 1);
  const events = role.session.snapshotEvents();
  assert.equal(events.filter(x => x.type === 'assistant/message').length, 1);
  assert.equal(events.filter(x => x.type === 'user/message' && x.data.source.kind === 'user').length, 1);
  assert.equal(events.filter(x => x.type === 'user/message' && x.data.source.kind === 'asuna').length, 1);
  const stage = events.find(x => x.type === 'asuna/stage');
  assert.deepEqual(stage.data, { turn: 1, step: 1, operation: 'stage-role', lane: 'character', phase: 'MONOLOGUE' });
  assert.equal(events.find(x => x.type === 'user/message' && x.data.source.kind === 'asuna').data.source.lane, 'character');
  assert.ok(stage.seq < events.find(x => x.type === 'assistant/message').seq);
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
  assert.equal(ordinary.session.snapshotEvents().filter(event => event.type === 'asuna/stage').length, 0);
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

test('business revision cancels only its exact running native operation', async t => {
  const h = await harness(t, 'wait');
  const role = await h.create('role');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Input' }] }));
  await h.entered;
  await h.core.onEvent({ kind: 'task_fenced', session_id: role.id, token: 'older-operation', reason: 'task_revised' });
  assert.equal(h.requests[0].signal.aborted, false, 'a delayed old notice cannot abort a newer native run');
  await h.core.onEvent({ kind: 'task_fenced', session_id: role.id, token: 'stage-role', reason: 'task_revised' });
  await role.whenIdle();
  const end = role.session.snapshotEvents().findLast(event => event.type === 'turn/end');
  assert.deepEqual(end.data.reason, { kind: 'aborted', reason: { kind: 'hook', reason: 'task_revised' } });
  assert.ok(h.business.find(row => row.method === 'result').args.error);
  assert.equal(role.session.snapshotEvents().filter(event => event.type === 'asuna/stage-result').length, 0);
});

test('T0.5 role system prompt is exactly the worker render, without harness identity or runtime context', async t => {
  const h = await harness(t);
  h.ctx.systemPrompt.context({ name: 'fixture-runtime-context', order: 1, text: 'RUNTIME_CONTEXT_FIXTURE' });
  const role = await h.create('role');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Human input' }] }));
  await role.whenIdle();
  const ordinary = await h.create('ordinary', false);
  ordinary.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Ordinary input' }] }));
  await ordinary.whenIdle();
  const system = request => request.messages.filter(m => m.role === 'system')
    .map(m => typeof m.content === 'string' ? m.content : m.content.map(x => x.text).join('')).join('\n');
  const [roleRequest, ordinaryRequest] = h.requests;
  assert.equal(system(roleRequest), 'Current persona from existing state: role');
  assert.doesNotMatch(JSON.stringify(roleRequest.messages), /powered by DeepSeek Harness|RUNTIME_CONTEXT_FIXTURE/);
  // Ordinary sessions keep the native identity and runtime context untouched.
  assert.match(system(ordinaryRequest), /You are an AI agent powered by DeepSeek Harness\./);
  assert.match(JSON.stringify(ordinaryRequest.messages), /RUNTIME_CONTEXT_FIXTURE/);
});

test('ADR-011: her other lanes carry neither the harness identity nor the host runtime context', async t => {
  const h = await harness(t);
  h.ctx.systemPrompt.context({ name: 'fixture-runtime-context', order: 1, text: 'RUNTIME_CONTEXT_FIXTURE' });
  await h.ctx.agentPresets.register({ id: 'summary-fixture',
    plugins: [{ name: new URL('../src/summary.js', import.meta.url).href }] });
  const handle = await h.ctx.agents.create({ sessionId: 'summary', agentOptions: { provider: 'fixture', model: 'one-model' },
    setup: async scope => { await h.ctx.agentPresets.mount(scope, 'summary-fixture'); } });
  t.after(() => handle.dispose());
  handle.agent.followup(createUserMessage({ source: { kind: 'asuna', form: 'notice', lane: 'summary', phase: 'summary' },
    content: [{ type: 'text', text: 'Summarize' }] }));
  await handle.agent.whenIdle();
  assert.equal(h.requests.length, 1);
  assert.doesNotMatch(JSON.stringify(h.requests[0].messages), /powered by DeepSeek Harness|RUNTIME_CONTEXT_FIXTURE/);
});

test('T6.4 CONSULT runs in the idle role session while the action tool waits; the role keeps no lock', async t => {
  const h = await harness(t);
  const role = await h.create('role');
  let toolDone = false;
  let releaseTool;
  const actionTool = new Promise(resolve => { releaseTool = resolve; }).then(() => { toolDone = true; });
  await h.core.onEvent({ kind: 'stage', session_id: 'role', token: 'task-1:consult:0', phase: 'CONSULT',
    lane: 'character', system: 'Current persona from existing state: role', text: 'Question from the action',
    binding: { scene_id: 'local-scene' } });
  await role.whenIdle();
  const consult = h.business.find(x => x.method === 'result' && x.args.token === 'task-1:consult:0');
  assert.equal(consult.args.result.content, 'actual native assistant event');
  assert.equal(toolDone, false, 'the action tool was still waiting when the role answered');
  const state = h.core.states.get('role');
  assert.equal(state.current, null);
  assert.equal(state.waiter, null, 'a consultation does not wait for a next stage');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Human input' }] }));
  await role.whenIdle();
  assert.equal(h.business.filter(x => x.method === 'input').length, 1);
  assert.equal(h.business.filter(x => x.method === 'result').length, 2);
  releaseTool();
  await actionTool;
});

