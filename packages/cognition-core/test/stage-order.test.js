// ADR-127 on the installed DSH loop: one copy of a stage's message (S1), a stage current only in the turn that answers
// it (S2), and a malformed step requested again once (R1). Inference is a scripted fixture adapter.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import { start } from './dsh-start.js';
import * as NativeToolExecutor from '@deepseek-ai/dsh-tool-executor-native';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import { CognitionCore, another, failureText } from '../src/index.js';

/** Each request takes the next answer: 'ok', a failure code, or a promise the answer waits for first. */
async function harness(t, answers, onInput) {
  const ctx = new Context();
  new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx);
  await start(new AgentRegistry(ctx)); new SystemPrompt(ctx, {}); new Tools(ctx);
  await ctx.plugin(AgentLoop, { agents: [], maxParallelToolCalls: 4 });
  await ctx.plugin(NativeToolExecutor);
  new Loader(ctx, { baseUrl: import.meta.url });
  await start(new AgentPresetRegistry(ctx, { default: 'asuna', selectedDefault: { get: () => undefined } }));
  const requests = [];
  class Adapter extends LlmAdapter {
    async *stream(options) {
      requests.push(JSON.stringify(options.messages));
      let answer = answers.shift() ?? 'ok';
      if (answer instanceof Promise) answer = await answer;
      if (answer === 'ok') {
        yield { type: 'text-delta', index: 0, text: 'answer ' + requests.length };
        yield { type: 'finish', reason: { kind: 'stop' } };
        return;
      }
      yield { type: 'text-delta', index: 0, text: 'cut' };
      yield { type: 'finish', reason: { kind: 'error', failure: { message: 'arguments are not JSON', code: answer } } };
    }
  }
  ctx.llm.registerAdapter(['fixture'], new Adapter());
  const core = new CognitionCore(ctx, { routes: { character: { provider: 'fixture', model: 'one-model' } } });
  core.ready = async () => {};
  ctx.provide('asuna', core);
  const results = [];
  core.worker = { async call(method, args) {
    if (method === 'role_tool_specs') return [];
    if (method === 'input') await onInput?.(core, args);
    if (method === 'result') {
      results.push(args);
      await core.onEvent({ kind: 'turn_done', session_id: 'role' });
    }
    return { accepted: true };
  } };
  const handles = [];
  t.after(async () => { for (const handle of handles) await handle.dispose(); await ctx.fiber.dispose(); });
  await ctx.agentPresets.register({ id: 'asuna', plugins: [{ name: new URL('../src/role.js', import.meta.url).href }] });
  const handle = await ctx.agents.create({ sessionId: 'role', agentOptions: { provider: 'fixture', model: 'one-model' },
    setup: async scope => { await ctx.agentPresets.mount(scope, 'asuna'); } });
  handles.push(handle);
  return { core, requests, results, role: handle.agent };
}

const stage = (token, extra = {}) => ({ kind: 'stage', session_id: 'role', token, phase: 'TURN', lane: 'character',
  system: 'persona', text: 'stage text ' + token, binding: { scene_id: 'local-scene' }, ...extra });
const of = (role, type) => role.session.snapshotEvents().filter(event => event.type === type);
const settled = async role => { await role.whenIdle(); await new Promise(resolve => setTimeout(resolve, 20)); await role.whenIdle(); };

test('R1: a malformed step is requested again once, and its turn answers once', async t => {
  const h = await harness(t, ['MALFORMED_RESPONSE', 'ok']);
  await h.core.onEvent(stage('s1'));
  await settled(h.role);
  assert.deepEqual(of(h.role, 'asuna/retry').map(event => event.data), [{ turn: 1, step: 1, code: 'MALFORMED_RESPONSE' }]);
  assert.equal(of(h.role, 'assistant/message').length, 1);
  assert.equal(h.results.length, 1);
  assert.equal(h.results[0].result.content, 'answer 2');
  // The step's input was sent once: the second request is the first one again, not the stage twice.
  assert.equal(h.requests[1].split('stage text s1').length, 2);
});

test('R1: broken again, the turn fails once, its cause led by the code and marked as requested again', async t => {
  const h = await harness(t, ['MALFORMED_RESPONSE', 'MALFORMED_RESPONSE']);
  await h.core.onEvent(stage('s1'));
  await settled(h.role);
  assert.equal(of(h.role, 'asuna/retry').length, 1);
  assert.equal(h.requests.length, 2);
  assert.equal(h.results.length, 1);
  assert.match(h.results[0].error, /^ASUNA_RETRIED_ONCE\nMALFORMED_RESPONSE: /);
});

test('R1: another code keeps DSH\'s own handling', async t => {
  const h = await harness(t, ['TRANSPORT']);
  await h.core.onEvent(stage('s1'));
  await settled(h.role);
  assert.equal(of(h.role, 'asuna/retry').length, 0);
  assert.equal(h.requests.length, 1);
  assert.match(h.results[0].error, /^TRANSPORT: /);
});

test('R1: not when that step holds a tool call, nor when its records cannot be read; another step\'s call does not stop it', () => {
  const core = Object.create(CognitionCore.prototype);
  core.ctx = { logger: { warn() {} } };
  const failure = { code: 'MALFORMED_RESPONSE' };
  const agent = events => ({ session: { appended: [], snapshotEvents: () => events,
    append(type, data) { this.appended.push([type, data]); } } });
  const failed = { kind: undefined };
  const own = agent([{ type: 'tool/call', data: { turn: 3, step: 2 } }]);
  assert.equal(core.retryBroken({ agent: own, turn: 3, step: 2, failure }, failed), failed);
  const other = agent([{ type: 'tool/call', data: { turn: 3, step: 1 } }, { type: 'tool/result', data: { turn: 3, step: 1 } }]);
  assert.deepEqual(core.retryBroken({ agent: other, turn: 3, step: 2, failure }, failed), { kind: 'retry' });
  assert.deepEqual(other.session.appended, [['asuna/retry', { turn: 3, step: 2, code: 'MALFORMED_RESPONSE' }]]);
  const unreadable = { session: { snapshotEvents() { throw new Error('unreadable'); }, append() { throw new Error('no'); } } };
  assert.equal(core.retryBroken({ agent: unreadable, turn: 3, step: 2, failure }, failed), failed);
  const retried = agent([{ type: 'asuna/retry', data: { turn: 3, step: 2 } }]);
  assert.equal(core.retryBroken({ agent: retried, turn: 3, step: 2, failure }, failed), failed);
  assert.equal(core.retryBroken({ agent: other, turn: 3, step: 2, failure: { code: 'TIMEOUT' } }, failed), failed);
  // A retry DSH already decided stands as it is.
  const dsh = { kind: 'retry', delayMs: 5 };
  assert.equal(core.retryBroken({ agent: agent([]), turn: 3, step: 2, failure }, dsh), dsh);
});

test('S1: a stage sent again while its copy waits in DSH\'s inbox leaves one copy, the removed one recorded', async t => {
  const h = await harness(t, []);
  const copy = createUserMessage({ content: [{ type: 'text', text: 'stage text s1' }],
    source: { kind: 'asuna', form: 'notice', summary: 'asuna:character:TURN', operation: 's1', lane: 'character', phase: 'TURN' } });
  h.role.send(copy, 'next-turn', false);         // kept by DSH across a restart, no turn started for it
  await h.core.onEvent(stage('s1'));
  await settled(h.role);
  assert.deepEqual(of(h.role, 'asuna/stage-copy-replaced').map(event => event.data),
    [{ operation: 's1', where: 'next-turn', chars: 'stage text s1'.length }]);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].split('stage text s1').length, 2);
  assert.equal(h.results.length, 1);
});

test('S2: a stage arriving while a turn with no stage runs waits, and is answered by its own turn', async t => {
  let release;
  const gate = new Promise(resolve => { release = () => resolve('ok'); });
  const h = await harness(t, [gate, 'ok']);
  // A turn of the program's notice with no stage of its own (a stale copy).
  h.role.followup(createUserMessage({ content: [{ type: 'text', text: 'stale copy' }],
    source: { kind: 'asuna', form: 'notice', summary: 'asuna:character:TURN', operation: 'old', lane: 'character', phase: 'TURN' } }));
  while (h.requests.length === 0) await new Promise(resolve => setTimeout(resolve, 2));
  await h.core.onEvent(stage('s2'));
  assert.equal(h.core.state('role').current, null, 'not current under a turn that never read it');
  release();
  await settled(h.role);
  assert.equal(h.requests.length, 2);
  assert.ok(!h.requests[0].includes('stage text s2'));
  assert.ok(h.requests[1].includes('stage text s2'));
  assert.deepEqual(h.results.map(r => [r.token, r.result?.content]), [['s2', 'answer 2']]);
});

test('S2: a stage arriving while her Web input is admitted leaves that turn its own stage', async t => {
  const h = await harness(t, [], async (core, args) => {
    await core.onEvent(stage('beat', { inputs: [] }));                       // not an answer to this input
    await core.onEvent(stage('web', { inputs: args.message_ids }));
  });
  h.role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Human input' }] }));
  await settled(h.role);
  assert.equal(h.requests.length, 2);
  assert.ok(h.requests[0].includes('stage text web') && !h.requests[0].includes('stage text beat'));
  assert.ok(h.requests[1].includes('stage text beat'));
  assert.deepEqual(h.results.map(r => r.token), ['web', 'beat']);
});

test('another and failureText', () => {
  assert.equal(another({ inputs: ['m2'] }, ['m1']), true);
  assert.equal(another({ inputs: ['m1'] }, ['m1']), false);
  assert.equal(another({}, ['m1']), false);
  assert.equal(another({ inputs: [] }, null), false);
  const session = { snapshotEvents: () => [] };
  assert.equal(failureText(session, Object.assign(new Error('multi\nline'), { code: 'TIMEOUT' })), 'TIMEOUT: Error: multi line');
  assert.equal(failureText(session, new Error('plain')), 'Error: plain');
});
