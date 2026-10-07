import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import SessionProjectionCache from '@deepseek-ai/dsh-session-projection-cache';
import { titleProjectionDefinition } from '@deepseek-ai/dsh-session-title';
import Storage from '@deepseek-ai/dsh-storage';
import * as JsonStorage from '@deepseek-ai/dsh-storage-json';
import * as Domain from '@deepseek-ai/dsh-storage-domain';
import Workspace from '@deepseek-ai/dsh-workspace';
import LlmRuntime, { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import Subagents from '@deepseek-ai/dsh-subagent';
import Persistence from '../src/persistence.js';
import { CognitionCore } from '../src/index.js';
import { PENDING_LINES, lineBeforeTurn, organizeNativeWorkspaces, recordChannelInput } from '../src/navigation.js';

test('native continuation preserves history and task children retain their actual execution directory', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-navigation-'));
  const ctx = new Context();
  t.after(() => ctx.fiber.dispose());
  new SessionStore(ctx); new SessionProjectionRegistry(ctx); new Storage(ctx);
  ctx.sessionProjections.register(titleProjectionDefinition);
  new LlmRuntime(ctx); new AgentRegistry(ctx); new SystemPrompt(ctx, {}); new Tools(ctx);
  new AgentLoop(ctx, { agents: [], maxParallelToolCalls: 4 });
  new Loader(ctx, { baseUrl: import.meta.url });
  new AgentPresetRegistry(ctx, { default: 'ordinary', selectedDefault: { get: () => undefined } });
  new Subagents(ctx, { maxActiveSubagents: { get: () => 8 }, maxDepth: { get: () => 1 } });
  await ctx.plugin(JsonStorage, { root: path.join(root, 'state') });
  await ctx.plugin(Domain, { backend: 'json' });
  await ctx.plugin(Persistence, { root: path.join(root, 'sessions') });
  await ctx.plugin(SessionProjectionCache, { writeEveryEvents: 100, writeIntervalMs: 1000 });
  await ctx.plugin(Workspace);
  await new Promise(resolve => ctx.inject(['workspaceRegistry', 'sessionProjectionCache'], () => resolve()));
  // The local chat's folder is derived from the data folder (paths.js), like the worker's.
  const local = path.join(root, 'work', 'local-user'), qq = path.join(root, 'QQ'), execution = path.join(root, 'sender');
  for (const directory of [local, qq, execution]) await fs.mkdir(directory, { recursive: true });
  ctx.provide('asunaFloor', { dataRoot: root });
  let requests = 0;
  class Adapter extends LlmAdapter {
    async *stream() {
      requests++;
      yield { type: 'text-delta', index: 0, text: 'native response' };
      yield { type: 'finish', reason: { kind: 'stop' } };
    }
  }
  ctx.llm.registerAdapter(['fixture'], new Adapter());
  const route = { provider: 'fixture', model: 'single-model' };
  const core = new CognitionCore(ctx, { persona: 'demo', deployment: { chat: { workspace: local } }, routes: { character: route, action: route } });
  core.ready = async () => {}; core.specs = []; core.personas.set('demo', { preset: 'ordinary' });
  core.channels.set('qq', { kind: 'qq', title: 'QQ' });          // what @asuna/napcat-qq registers
  ctx.provide('asuna', core);
  ctx.provide('attachments', {});
  ctx.provide('sessionController', { list: async () => ({ items: [] }), rename: async ({ sessionId, title }) => {
    ctx.agents.get(sessionId).session.append('session/title', { title, source: { kind: 'user' }, messageSeqs: [] });
  } });
  await ctx.agentPresets.register({ id: 'ordinary', plugins: [] });
  await ctx.agentPresets.register({ id: 'asuna-action', plugins: [{ name: new URL('../src/action.js', import.meta.url).href }] });
  await ctx.agentPresets.register({ id: 'asuna-summary', plugins: [{ name: new URL('../src/summary.js', import.meta.url).href }] });
  const original = await ctx.agents.create({ sessionId: 'original', meta: { cwd: local }, agentOptions: route });
  original.agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'existing conversation' }] }));
  await original.agent.whenIdle();
  const prefix = original.agent.session.snapshotEvents();
  await original.dispose();
  const role = { _id: 'qq-main', cwd: qq, scene_id: 'qq:bot:group:one', native_title: '群聊 · one', source_session_id: 'original' };
  const plan = { first: true, workspaces: { QQ: qq, Local: local }, archive_ids: ['original'],
    entries: [{ session_id: role._id, workspace: 'QQ', binding: role }] };
  await organizeNativeWorkspaces(core, plan);
  const header = (await ctx.sessionPersistence.stat(role._id)).header;
  assert.equal(ctx.sessionProjectionCache.cachedSnapshot(header).values.title, '群聊 · one');
  role.previous_native_title = role.native_title;
  role.native_title = '群聊 · renamed';
  await organizeNativeWorkspaces(core, { ...plan, first: false });
  await organizeNativeWorkspaces(core, { ...plan, first: false });
  assert.equal(ctx.sessionProjectionCache.cachedSnapshot(header).values.title, role.native_title);
  assert.equal(requests, 1, 'cold migration and title repair must not activate an Agent');
  const continued = await ctx.sessionPersistence.open(role._id, 'read');
  const { events } = await continued.read(); await continued.close();
  assert.deepEqual(events.slice(0, prefix.length), prefix);
  assert.equal(continued.header.parentSession, 'original');
  assert.deepEqual(ctx.workspaceRegistry.archivedSessionIds, ['original']);
  await ctx.workspaceRegistry.archiveSession(role._id);
  await organizeNativeWorkspaces(core, { ...plan, first: false });
  assert.ok(ctx.workspaceRegistry.archivedSessionIds.includes(role._id), 'a restart preserves a deliberate archive');
  const receipt = { session_id: role._id, binding: role,
    input: { id: 'quiet-qq-message', sender: '10001', text: 'a real quiet group message', received_at: '2026-10-03' } };
  await recordChannelInput(core, receipt);
  await recordChannelInput(core, receipt);
  const readQuiet = await ctx.sessionPersistence.open(role._id, 'read');
  const quietEvents = (await readQuiet.read()).events; await readQuiet.close();
  assert.equal(quietEvents.filter(event => event.type === 'user/message' && event.data.source.receipt === receipt.input.id).length, 1);
  assert.equal(quietEvents.filter(event => event.type === 'turn/start').length, prefix.filter(event => event.type === 'turn/start').length);
  assert.equal(requests, 1, 'quiet reception never starts a model turn');
  assert.ok(!ctx.workspaceRegistry.archivedSessionIds.includes(role._id), 'new platform activity reopens the same native conversation');
  // A brand-new conversation has no system head until its agent's first step; a line placed before it would
  // make DSH refuse to reload the log after that first turn, so it waits in the conversation's inbox.
  const fresh = { _id: 'qq-fresh', cwd: qq, scene_id: 'qq:bot:group:two', native_title: '群聊 · two' };
  const line = index => ({ session_id: fresh._id, binding: fresh,
    input: { id: 'before-' + index, sender: '10002', text: 'line ' + index + ' before her first turn', received_at: '2026-10-03' } });
  for (let index = 0; index < PENDING_LINES + 2; index++) await recordChannelInput(core, line(index));
  await recordChannelInput(core, line(PENDING_LINES + 1));
  const readFresh = await ctx.sessionPersistence.open(fresh._id, 'read');
  const freshEvents = (await readFresh.read()).events; await readFresh.close();
  assert.equal(freshEvents.filter(event => event.type === 'user/message').length, 0);
  const waiting = ctx.sessionProjectionCache.cachedSnapshot(readFresh.header).values.inbox['next-step'];
  assert.deepEqual(waiting.map(message => message.source.receipt),
    Array.from({ length: PENDING_LINES }, (_, index) => 'before-' + (index + 2)), 'the newest lines wait, once each');
  const first = await ctx.agents.resume({ resumeSessionId: fresh._id, agentOptions: route });
  first.agent.followup(createUserMessage({ source: { kind: 'asuna', form: 'notice' }, content: [{ type: 'text', text: 'stage' }] }));
  await first.agent.whenIdle();
  await recordChannelInput(core, line(PENDING_LINES + 2));
  const surface = first.agent.session.surface.nodes.map(seq => first.agent.session.eventAt(seq));
  assert.equal(surface[0].type, 'system/message', 'the head stays first');
  assert.deepEqual(surface.filter(event => event.type === 'user/message').map(event => event.data.source.receipt ?? 'notice'),
    [...Array.from({ length: PENDING_LINES }, (_, index) => 'before-' + (index + 2)), 'notice', 'before-' + (PENDING_LINES + 2)]);
  assert.equal(first.agent.inbox.nextStep.length, 0);
  await first.dispose();
  const again = await ctx.agents.resume({ resumeSessionId: fresh._id, agentOptions: route });
  assert.equal(again.agent.session.eventAt(again.agent.session.surface.nodes[0]).type, 'system/message', 'the log reloads');
  await again.dispose();
  let complete;
  const completed = new Promise(resolve => { complete = resolve; });
  const child = { _id: 'action', lane: 'executor', cwd: execution, scene_id: role.scene_id,
    parent_session_id: role._id, role_session_id: role._id, task_id: 'task-one', allowed_capabilities: [] };
  core.worker = { async call(method, args) {
    if (method === 'stage.valid') return { valid: true };
    if (method === 'session') return args.session_id === role._id ? role : child;
    if (method === 'result') { assert.ok(args.result, args.error); complete(args.result); }
  } };
  const stage = { session_id: 'action', lane: 'executor', phase: 'execution', trigger: 'brief',
    token: 'task-one:execute:0', text: 'execute assigned task', system: 'action role', binding: child,
    task: { _id: 'task-one', thread: 'task-one', title: 'one', parent_session_id: role._id } };
  await core.children.start(stage);
  const result = await completed;
  assert.equal(result.content, 'native response');
  // A summary is the worker's own bookkeeping, not a delegation: a hidden child without a catalog entry.
  let summarized;
  const summaryDone = new Promise(resolve => { summarized = resolve; });
  const summaryBinding = { _id: 'summary-one', lane: 'summary', cwd: execution, scene_id: role.scene_id,
    parent_session_id: role._id, role_session_id: role._id, allowed_capabilities: [] };
  core.worker = { async call(method, args) {
    if (method === 'stage.valid') return { valid: true };
    if (method === 'session') return args.session_id === role._id ? role : summaryBinding;
    if (method === 'result') summarized(args);
  } };
  await core.children.start({ session_id: 'summary-one', lane: 'summary', phase: 'dialogue-summary',
    token: 'summary-one:0', text: 'summarize this', system: 'summary role', binding: summaryBinding });
  assert.ok((await summaryDone).result, 'the summary still ran');
  const summaryHeader = (await ctx.sessionPersistence.stat('summary-one')).header;
  assert.equal(summaryHeader.origin, 'subagent', 'a child header keeps it out of the sidebar');
  assert.equal(summaryHeader.parentSession, role._id);
  const listed = ctx.agents.get(role._id).session.snapshotEvents().filter(event => event.type === 'subagent/catalog');
  assert.deepEqual(listed.map(event => event.data.childId), ['action'], 'the subagent list shows the task only');
  const settledRequests = requests;
  await core.children.dispose();
  const saved = await ctx.sessionPersistence.stat('action');
  assert.equal(saved.header.cwd, execution);
  assert.equal(saved.header.origin, 'subagent');
  assert.equal(saved.header.parentSession, role._id);
  const childLog = await ctx.sessionPersistence.open('action', 'read');
  const childEvents = (await childLog.read()).events; await childLog.close();
  assert.equal(childEvents.find(event => event.type === 'session/title').data.title, 'one', 'her task title, no UI words');
  assert.equal(childEvents.find(event => event.type === 'asuna/stage').data.lane, 'executor');
  const parent = ctx.agents.get(role._id);
  parent.session.append('session/title', { title: 'My QQ name', source: { kind: 'user' }, messageSeqs: [] });
  await organizeNativeWorkspaces(core, { ...plan, first: false });
  assert.equal(ctx.sessionProjectionCache.cachedSnapshot(parent.session.header).values.title, 'My QQ name',
    'native user renaming must survive organization and startup');
  assert.ok(parent.session.snapshotEvents().some(event => event.type === 'subagent/catalog' && event.data.childId === 'action'));
  // ADR-011 §7.1: the thread in her conversation opens on the task, then the work range and the report.
  const thread = parent.session.snapshotEvents().filter(event => event.type === 'asuna/collab').map(event => event.data);
  assert.deepEqual(thread.map(entry => entry.kind), ['open', 'work', 'report']);
  assert.equal(thread[0].child_session_id, 'action');
  assert.equal(thread[0].parent_session_id, role._id);
  assert.ok(thread[1].after_seq < childEvents.find(event => event.type === 'user/message').seq, 'the range covers her brief');
  assert.ok(thread[1].through_seq >= childEvents.find(event => event.type === 'assistant/message').seq);
  assert.equal(thread[2].text, 'native response');
  await core.children.start(stage);
  assert.equal(requests, settledRequests, 'a durable stage receipt must not rerun inference or tools');
  assert.equal(parent.session.snapshotEvents().filter(event => event.type === 'subagent/catalog').length, 1);
  assert.equal(parent.session.snapshotEvents().filter(event => event.type === 'asuna/collab').length, 3);
  assert.deepEqual(ctx.workspaceRegistry.list().map(workspace => workspace.title), ['QQ', 'Local']);
  // A line the record missed is queued again on the agent before its stage's turn, so a new conversation's
  // first turn still reads head, line, notice (not head, notice, monologue, line).
  const lost = { _id: 'qq-lost', cwd: qq, scene_id: 'qq:bot:group:three', native_title: '群聊 · three' };
  await organizeNativeWorkspaces(core, { first: false, archive_ids: [], workspaces: { QQ: qq, Local: local },
    entries: [{ session_id: lost._id, workspace: 'QQ', binding: lost }] });
  const opened = await ctx.agents.resume({ resumeSessionId: lost._id, agentOptions: route });
  const missed = { session_id: lost._id, binding: lost,
    input: { id: 'missed', sender: '10003', text: 'the line this turn answers', received_at: '2026-10-05' } };
  assert.equal(await lineBeforeTurn(core, opened.agent, missed), true);
  assert.equal(await lineBeforeTurn(core, opened.agent, missed), false, 'queued once');
  opened.agent.followup(createUserMessage({ source: { kind: 'asuna', form: 'notice' }, content: [{ type: 'text', text: 'stage' }] }));
  await opened.agent.whenIdle();
  const order = opened.agent.session.surface.nodes.map(seq => opened.agent.session.eventAt(seq));
  assert.equal(order[0].type, 'system/message');
  assert.deepEqual(order.filter(event => event.type === 'user/message').map(event => event.data.source.receipt ?? 'notice'),
    ['missed', 'notice']);
  assert.equal(await lineBeforeTurn(core, opened.agent, missed), false, 'present after the turn');
  await opened.dispose();
  await core.handles.get(role._id).dispose();
  await ctx.fiber.dispose();
  const reopened = new Context();
  t.after(() => reopened.fiber.dispose());
  new SessionStore(reopened); new SessionProjectionRegistry(reopened); new Storage(reopened);
  reopened.sessionProjections.register(titleProjectionDefinition);
  await reopened.plugin(JsonStorage, { root: path.join(root, 'state') });
  await reopened.plugin(Domain, { backend: 'json' });
  await reopened.plugin(SessionProjectionCache, { writeEveryEvents: 100, writeIntervalMs: 1000 });
  await new Promise(resolve => reopened.inject(['sessionProjectionCache'], () => resolve()));
  assert.equal(reopened.sessionProjectionCache.cachedSnapshot(header).values.title, 'My QQ name',
    'the cold sidebar must retain its native title after host restart');
});
