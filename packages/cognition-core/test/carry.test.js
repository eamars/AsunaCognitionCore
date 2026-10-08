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
import LlmRuntime, { CONTEXT_WINDOW_EXCEEDED_CODE, LlmAdapter, LlmError, createUserMessage } from '@deepseek-ai/dsh-llm';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import Persistence from '../src/persistence.js';
import { CognitionCore } from '../src/index.js';
import { carrySession, lastSummary, overflowed } from '../src/carry.js';

test('DSH\'s context-window rejection is recognized on the error or anywhere in its causes', () => {
  const rejected = new LlmError('context window exceeded', CONTEXT_WINDOW_EXCEEDED_CODE, { status: 400 });
  assert.ok(overflowed(rejected));
  assert.ok(overflowed(new Error('turn failed', { cause: new Error('request', { cause: rejected }) })));
  assert.ok(overflowed(new AggregateError([new Error('other'), rejected])));
  assert.ok(!overflowed(new LlmError('slow down', 'RATE_LIMIT')));
  assert.ok(!overflowed(new Error('context window exceeded')), 'the code decides, never the wording');
  assert.ok(!overflowed(undefined));
});

test('the carried summary is the last one the session kept, as text', () => {
  const summary = text => ({ type: 'compaction/summary', data: { summary: [{ type: 'text', text }] } });
  assert.equal(lastSummary([summary('first'), { type: 'user/message', data: {} }, summary('second')]), 'second');
  assert.equal(lastSummary([{ type: 'compaction/summary', data: { summary: 'plain' } }]), 'plain');
  assert.equal(lastSummary([{ type: 'user/message', data: {} }]), '');
});

test('a turn the model refuses for its window reports it, and the Host prepares the new session', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-carry-'));
  const ctx = new Context();
  t.after(() => ctx.fiber.dispose());
  new SessionStore(ctx); new SessionProjectionRegistry(ctx); new Storage(ctx);
  ctx.sessionProjections.register(titleProjectionDefinition);
  new LlmRuntime(ctx); new AgentRegistry(ctx); new SystemPrompt(ctx, {}); new Tools(ctx);
  new AgentLoop(ctx, { agents: [], maxParallelToolCalls: 4 });
  new Loader(ctx, { baseUrl: import.meta.url });
  new AgentPresetRegistry(ctx, { default: 'ordinary', selectedDefault: { get: () => undefined } });
  await ctx.plugin(JsonStorage, { root: path.join(root, 'state') });
  await ctx.plugin(Domain, { backend: 'json' });
  await ctx.plugin(Persistence, { root: path.join(root, 'sessions') });
  await ctx.plugin(SessionProjectionCache, { writeEveryEvents: 100, writeIntervalMs: 1000 });
  await ctx.plugin(Workspace);
  await new Promise(resolve => ctx.inject(['workspaceRegistry', 'sessionProjectionCache'], () => resolve()));
  const local = path.join(root, 'work', 'local-user');
  await fs.mkdir(local, { recursive: true });
  ctx.provide('asunaFloor', { dataRoot: root });
  class Adapter extends LlmAdapter {
    // eslint-disable-next-line require-yield
    async *stream() { throw new LlmError('maximum context length exceeded', CONTEXT_WINDOW_EXCEEDED_CODE, { status: 400 }); }
  }
  ctx.llm.registerAdapter(['fixture'], new Adapter());
  const route = { provider: 'fixture', model: 'single-model' };
  const core = new CognitionCore(ctx, { persona: 'demo', deployment: { chat: { workspace: local } }, routes: { character: route } });
  core.ready = async () => {}; core.personas.set('demo', { preset: 'ordinary' });
  ctx.provide('asuna', core);
  const added = [];
  ctx.on('api-session/added', summary => added.push(summary.sessionId));
  ctx.provide('sessionController', { list: async () => ({ items: [{ sessionId: 'carried' }] }) });
  await ctx.agentPresets.register({ id: 'ordinary', plugins: [] });

  const errors = [];
  ctx.on('agent/error', ({ error }) => errors.push(error));
  const old = await ctx.agents.create({ sessionId: 'old', meta: { cwd: local }, agentOptions: route });
  await (await ctx.workspaceRegistry.create(local, 'Local')).attachSession('old');
  old.agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'hello' }] }));
  await old.agent.whenIdle();
  assert.ok(errors.length && overflowed(errors.at(-1)), 'the failure reaching agent/error carries DSH\'s code');

  const binding = { _id: 'carried', cwd: local, scene_id: 'local', native_title: 'Local chat' };
  const result = await carrySession(core, { session_id: 'old', plan: { first: false, archive_ids: [],
    workspaces: { Local: local }, entries: [{ session_id: 'carried', workspace: 'Local', binding }] } });
  assert.equal(result.session_id, 'carried');
  const header = (await ctx.sessionPersistence.stat('carried')).header;
  assert.equal(header.parentSession, undefined, 'nothing of the old session is seeded');
  assert.equal(ctx.sessionProjectionCache.cachedSnapshot(header).values.title, 'Local chat');
  assert.deepEqual(added, ['carried']);
  for (let i = 0; i < 50 && !ctx.workspaceRegistry.archivedSessionIds.includes('old'); i++)
    await new Promise(resolve => setTimeout(resolve, 20));
  assert.ok(ctx.workspaceRegistry.archivedSessionIds.includes('old'), 'the old session is archived once idle');
  assert.ok(!ctx.workspaceRegistry.archivedSessionIds.includes('carried'));
  await old.dispose();
});
