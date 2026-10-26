// Installed DSH loop and scope services; only inference and business I/O are
// synthetic. Live-model/Web evidence is recorded separately in NATIVE_PLUGIN.md.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { LlmAdapter, createUserMessage, requestImageHandleText, resolveImageAttachmentAccess }
  from '@deepseek-ai/dsh-llm';
import LocalFileSystem from '@deepseek-ai/dsh-fs-local';
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
import fs from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import YAML from 'yaml';
import { CognitionCore, pictureParts } from '../src/index.js';
import { asunaRender, attachImage } from '../src/tool-output.js';
import { rootsAtTheModel } from '../src/roots.js';

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
  const notes = [];
  let note;              // what DSH's DeepSeek adapter writes beside an image, built while the request is read
  class Adapter extends LlmAdapter {
    async *stream(options) {
      requests.push(options);
      enter();
      if (note) { await new Promise(resolve => setTimeout(resolve, 2)); notes.push([options.sessionId, note()]); }
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
  const business = [], stages = new Map();
  // The worker ends each character turn with turn_done (coordinator._turn); stages name their session.
  const onEvent = core.onEvent.bind(core);
  core.onEvent = async event => { if (event.kind === 'stage') stages.set(event.token, event.session_id); return onEvent(event); };
  core.worker = { async call(method, args) {
    if (method === 'role_tool_specs') return [];          // her tools for the session: none in these fixtures
    business.push({ method, args });
    if (method === 'input') await core.onEvent({ kind: 'stage', session_id: args.session_id,
      token: 'stage-' + args.session_id, phase: 'TURN', lane: 'character',
      system: 'Current persona from existing state: ' + args.session_id, text: 'Internal context' });
    if (method === 'result') await core.onEvent({ kind: 'turn_done', session_id: stages.get(args.token) ?? args.token.slice(6) });
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
  return { ctx, core, requests, business, create, entered, notes, imageNote: fn => { note = fn; } };
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
  assert.deepEqual(stage.data, { turn: 1, step: 1, operation: 'stage-role', lane: 'character', phase: 'TURN' });
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

test('T6.4 the action brain question runs as her turn in the idle role session while its tool waits; no lock is kept', async t => {
  const h = await harness(t);
  const role = await h.create('role');
  let toolDone = false;
  let releaseTool;
  const actionTool = new Promise(resolve => { releaseTool = resolve; }).then(() => { toolDone = true; });
  await h.core.onEvent({ kind: 'stage', session_id: 'role', token: 'task-1:consult:0', phase: 'TURN', trigger: 'question',
    lane: 'character', system: 'Current persona from existing state: role', text: 'Question from the action',
    binding: { scene_id: 'local-scene' } });
  await role.whenIdle();
  const consult = h.business.find(x => x.method === 'result' && x.args.token === 'task-1:consult:0');
  assert.equal(consult.args.result.content, 'actual native assistant event');
  assert.equal(toolDone, false, 'the action tool was still waiting when the role answered');
  const state = h.core.states.get('role');
  assert.equal(state.current, null);
  assert.equal(state.waiter, null, 'the worker ended her answering turn (turn_done)');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'Human input' }] }));
  await role.whenIdle();
  assert.equal(h.business.filter(x => x.method === 'input').length, 1);
  assert.equal(h.business.filter(x => x.method === 'result').length, 2);
  releaseTool();
  await actionTool;
});


// ADR-063 D2: a compaction after her notice was composed takes the copies it relied on; the next request has them.
test('what a compaction took from under her notice is in the next request again', async t => {
  const h = await harness(t);
  const role = await h.create('role');
  const context = { scene: 'home', self_state_from_program: { core: 'SELF-COPY' }, event: { text: 'one' } };
  const stage = (token, episode) => ({ kind: 'stage', session_id: 'role', token, phase: 'TURN', lane: 'character',
    system: 'Current persona from existing state: role', text: 'Internal context', context, episode_id: episode,
    binding: { scene_id: 'local-scene' } });
  await h.core.onEvent(stage('op-1', 'ep-1'));
  await role.whenIdle();
  assert.match(JSON.stringify(h.requests[0].messages), /SELF-COPY/);
  // The next turn's notice relies on the first one's copy; a compaction at that turn's first step summarizes it.
  let compact = true;
  h.ctx.on('agent/pre-step', async ({ agent }, next) => {
    if (compact && agent === role) {
      compact = false;
      const session = role.session, nodes = session.surface.nodes;
      const first = nodes.find(seq => session.eventAt(seq).type !== 'system/message'), last = nodes.at(-1);
      const turn = session.snapshotEvents().findLast(event => event.type === 'turn/start').data.turn;
      session.append('compaction/start', { compactionId: 'c1', turn });
      const summary = session.append('compaction/summary', { compactionId: 'c1', summary: [{ type: 'text', text: 'earlier' }],
        shadowedRange: { start: first, end: last }, shadowedSeqs: nodes.filter(seq => seq >= first),
        shadowedTokenCount: 10, provider: 'fixture', model: 'one-model' });
      session.append('user/message', createUserMessage({ source: { kind: 'compact-checkpoint', compactionId: 'c1' },
        content: [{ type: 'text', text: '<compacted-summary>earlier</compacted-summary>' }] }),
      { surfaceOp: { op: 'replace', startSeq: first, endSeq: last }, sourceEventSeqs: [summary.seq, ...nodes.filter(seq => seq >= first)] });
      session.append('compaction/end', { compactionId: 'c1', turn });
    }
    return next();
  });
  await h.core.onEvent(stage('op-2', 'ep-2'));
  await role.whenIdle();
  const sent = JSON.stringify(h.requests.at(-1).messages);
  assert.match(sent, /unchanged_from_program/, 'the notice relied on the earlier copy');
  assert.match(sent, /SELF-COPY/, 'and the copy is back before the request');
  assert.match(sent, /restored_from_program/);
});

test('a picture that cannot become an attachment says why, in a result the tool host accepts', async () => {
  const value = { ref: 'att-1', image: { media_type: 'image/gif', data: Buffer.from('GIF89a').toString('base64') } };
  const refused = Object.assign(new Error('unsupported'), { code: 'ATTACHMENT_TYPE_UNSUPPORTED' });
  for (const ctx of [{ attachments: { saveImage: async () => { throw refused; } } }, {}]) {
    const result = await attachImage(ctx, value);
    assert.equal('image' in result, false, 'the inline bytes are dropped, not set to undefined');
    assert.deepEqual(JSON.parse(JSON.stringify(result)), result);
    assert.match(result.visual, /^unavailable:(ATTACHMENT_TYPE_UNSUPPORTED|ATTACHMENT_SERVICE_MISSING)$/);
    assert.match(result.note, /重试也一样/);
  }
});

test('pictures of a group turn become image parts; one that cannot be saved is left out', async () => {
  const saved = [];
  const attachments = { saveImage: async ({ name, mediaType }) => {
    if (name === 'att-bad') throw new Error('unsupported');
    saved.push(name); return { attachmentId: 'a-' + name, mediaType };
  } };
  const data = Buffer.from('png').toString('base64');
  const parts = await pictureParts(attachments, [{ ref: 'att-1', media_type: 'image/png', data },
    { ref: 'att-bad', media_type: 'image/png', data }, { ref: 'att-2' }]);
  assert.deepEqual(parts, [{ type: 'image', attachment: { attachmentId: 'a-att-1', mediaType: 'image/png' } }]);
  assert.deepEqual(saved, ['att-1']);
});

// ADR-098: what the model reads in her lanes holds no local root of this computer; the action brain's requests and
// every stored message stay as they were.
const PATHS = JSON.parse(readFileSync(new URL('../../../tests/fixtures/path_placeholders.json', import.meta.url), 'utf8'));
const WIN = PATHS.hosts.windows;
const BS = '\\';

async function rootsHarness(t, wire, refused) {
  const h = await harness(t);
  h.core.config.persona = 'fixture';
  h.core.personas.set('fixture', { preset: 'asuna' });
  h.core.roots.take(wire, refused);
  rootsAtTheModel(h.core);
  // DSH's working-folder line, a required runtime context as dsh-working-directory registers it.
  h.ctx.systemPrompt.context({ name: 'working-directory:current', order: 1, required: true, interpolate: false,
    text: ({ agent }) => agent ? 'Current working directory: ' + JSON.stringify(agent.session.header.cwd) + '.' : '' });
  const calls = [];
  const call = h.core.worker.call.bind(h.core.worker);
  h.core.worker.call = async (method, args) => {
    calls.push({ method, args });
    if (method === 'roots.tally' || method === 'roots.refused') return { kept: true };
    if (method === 'input') {
      await h.core.onEvent({ kind: 'stage', session_id: args.session_id, token: 'stage-' + args.session_id, phase: 'TURN',
        lane: 'character', system: 'Persona. 你的源码在 ' + WIN.workspace + BS + 'packages', text: 'Internal context' });
      return { accepted: true };
    }
    return call(method, args);
  };
  const open = async (id, preset, mount) => {
    const handle = await h.ctx.agents.create({ sessionId: id, agentOptions: { provider: 'fixture', model: 'one-model' },
      meta: { cwd: WIN.data + BS + 'work' + BS + 'local-user', agentPreset: preset },
      setup: async scope => { await h.ctx.agentPresets.mount(scope, mount); } });
    t.after(() => handle.dispose());
    return handle.agent;
  };
  return { ...h, calls, open };
}

// Any of the fixture's roots or its account name, in any count of backslashes, any case.
const ROOTS = new RegExp([WIN.workspace, WIN.home, WIN.user].map(text => text.split(BS)
  .map(part => part.replace(/[.^$|?*+()[\]{}]/g, ch => BS + ch)).join('[' + BS + BS + '/]+')).join('|'), 'i');

test('ADR-098: her requests carry zero roots and zero user names; the action brain\'s are unchanged', async t => {
  const h = await rootsHarness(t, PATHS.tables.windows);
  const role = await h.open('role', 'asuna', 'asuna');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text',
    text: '看 ' + WIN.home + BS + 'Desktop' + BS + 'a.txt 和 ' + JSON.stringify(WIN.workspace + BS + 'src')
      + '，whoami 是 ' + WIN.user }] }));
  await role.whenIdle();
  const action = await h.open('action', 'asuna-action', 'ordinary');
  action.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'do ' + WIN.workspace }] }));
  await action.whenIdle();
  assert.equal(h.requests.length, 2);
  const [hers, actions] = h.requests.map(request => request.messages.flatMap(m => m.content.map(x => x.text ?? '')).join('\n'));
  assert.doesNotMatch(hers, ROOTS, 'no root and no user name in the request of her lane');
  assert.ok(hers.includes('Current working directory: "${ASUNA_DATA}' + BS + BS + 'work' + BS + BS + 'local-user".'));
  assert.ok(hers.includes('你的源码在 ${ASUNA_WORKSPACE}' + BS + 'packages'));
  assert.ok(hers.includes('看 ${ASUNA_HOME}' + BS + 'Desktop' + BS + 'a.txt 和 "${ASUNA_WORKSPACE}' + BS + BS + 'src"'));
  assert.ok(hers.includes('whoami 是 ${ASUNA_USER}'));
  assert.match(actions, ROOTS, "the action brain's request keeps the real paths");
  // Storage stays raw: her conversation's log keeps what was written.
  assert.match(JSON.stringify(role.session.snapshotEvents()), ROOTS);
  h.core.roots.flush();
  const tally = h.calls.find(x => x.method === 'roots.tally').args.sessions;
  assert.deepEqual(tally, [{ session_id: 'role', lane: 'character', requests: 1, rewritten: 1 }]);
  assert.equal(h.core.roots.status().rewritten, 1);
});

test('ADR-098: without a table her lane is refused with the coded fault and one audit event; the action lane runs', async t => {
  const h = await rootsHarness(t, null, 'ROOT_TABLE_REFUSED: fixture');
  for (const id of ['role', 'role-two']) {
    const role = await h.open(id, 'asuna', 'asuna');
    role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'hello' }] }));
    await role.whenIdle();
  }
  assert.equal(h.requests.length, 0, 'nothing of hers reached the model');
  const failed = h.calls.filter(x => x.method === 'result' && x.args.error);
  assert.equal(failed.length, 2);
  assert.ok(failed.every(x => x.args.error.startsWith('Error: ASUNA_ROOT_TABLE_MISSING:')), failed[0]?.args.error);
  assert.equal(h.calls.filter(x => x.method === 'roots.refused').length, 1);
  const action = await h.open('action', 'asuna-action', 'ordinary');
  action.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'do it' }] }));
  await action.whenIdle();
  assert.equal(h.requests.length, 1);
  assert.equal(h.core.roots.status().refused, 'ROOT_TABLE_REFUSED: fixture');
});

test("ADR-098: the image note's path is contracted in her request only (DSH's fs host-path mapping, in her scope)", async t => {
  const h = await rootsHarness(t, PATHS.tables.windows);
  new LocalFileSystem(h.ctx, { cwd: process.cwd(), diffBasisMaxBytes: 1 << 20 });
  const host = WIN.data + BS + 'adr008' + BS + 'home' + BS + 'attachments' + BS + 'ab' + BS + 'abcdef.jpg';
  const ref = { attachmentId: 'sha256:abcdef0123456789', name: 'photo.jpg', width: 64, height: 48, mediaType: 'image/jpeg' };
  // As dsh-llm-deepseek resolves it: the attachment's host path through the fs service of its own scope.
  const adapterScope = h.ctx.extend ? h.ctx.extend() : h.ctx;
  h.imageNote(() => requestImageHandleText(ref, { width: 64, height: 48 }, resolveImageAttachmentAccess(
    { imageHostPath: () => host }, path => adapterScope.get('fs')?.processPathFromHostPath(path), ref)));
  const role = await h.open('role', 'asuna', 'asuna');
  role.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'look' }] }));
  await role.whenIdle();
  const action = await h.open('action', 'asuna-action', 'ordinary');
  action.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'open it' }] }));
  await action.whenIdle();
  const hers = h.notes.find(([id]) => id === 'role')?.[1], actions = h.notes.find(([id]) => id === 'action')?.[1];
  assert.ok(hers && actions, 'both requests built an image note');
  assert.doesNotMatch(hers, ROOTS, 'no root in the note of her request');
  assert.ok(hers.includes('"${ASUNA_DATA}' + BS + BS + 'adr008'), hers);
  assert.match(actions, ROOTS, "the action brain's note keeps the real path");
  assert.equal(h.ctx.get('fs').processPathFromHostPath(host), host, 'outside a request of hers the mapping is unchanged');
});

