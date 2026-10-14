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
import Persistence from '../src/persistence.js';
import { CognitionCore, completedPrefix } from '../src/index.js';

test('a copy is cut at the end of the last completed turn, with what stands after it', () => {
  const events = [{ type: 'session/title', seq: 0 }, { type: 'turn/start', seq: 1 }, { type: 'turn/end', seq: 2 },
    { type: 'model/selection', seq: 3 }, { type: 'turn/start', seq: 4 }];
  assert.equal(completedPrefix(events), 3);
  assert.equal(completedPrefix(events.slice(0, 2)), undefined, 'no completed turn: nothing to copy');
});

test('an errand runs in a copy of the conversation and leaves the list when its turn ends (ADR-066)', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-errand-'));
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
    async *stream() {
      yield { type: 'text-delta', index: 0, text: 'answered there' };
      yield { type: 'finish', reason: { kind: 'stop' } };
    }
  }
  ctx.llm.registerAdapter(['fixture'], new Adapter());
  const route = { provider: 'fixture', model: 'single-model' };
  const core = new CognitionCore(ctx, { persona: 'demo', deployment: { chat: { workspace: local } }, routes: { character: route } });
  core.ready = async () => {}; core.personas.set('demo', { preset: 'ordinary' });
  core.uiTitles = { errand: 'Errand' };
  ctx.provide('asuna', core);
  await ctx.agentPresets.register({ id: 'ordinary', plugins: [] });

  const args = { session_id: 'asuna-errand-1', source_session_id: 'group', scene_id: 'local', cwd: local };
  assert.deepEqual(await core.errandSession(args), { forked: false, reason: 'no_conversation' });
  const group = await ctx.agents.create({ sessionId: 'group', meta: { cwd: local }, agentOptions: route });
  await (await ctx.workspaceRegistry.create(local, 'Local')).attachSession('group');
  group.agent.session.append('session/title', { title: 'The group', source: { kind: 'user' }, messageSeqs: [] });
  assert.deepEqual(await core.errandSession(args), { forked: false, reason: 'no_completed_turn' });
  group.agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: 'hello there' }] }));
  await group.agent.whenIdle();
  core.states.set('group', { current: { token: 'x' }, queue: [] });
  assert.deepEqual(await core.errandSession(args), { forked: false, reason: 'busy' }, 'never cut in a turn');
  core.states.delete('group');

  assert.deepEqual(await core.errandSession(args), { forked: true });
  const copy = ctx.agents.get('asuna-errand-1');
  const events = copy.session.snapshotEvents();
  assert.ok(events.some(event => event.type === 'user/message' && JSON.stringify(event.data).includes('hello there')),
    'the conversation up to its last completed turn is in the copy');
  assert.equal(copy.session.header.parentSession, 'group');
  assert.equal(events.findLast(event => event.type === 'session/title').data.title, 'The group · Errand');
  assert.deepEqual(await core.errandSession(args), { forked: true }, 'made once');
  assert.ok(!group.agent.session.snapshotEvents().some(event => event.type === 'session/title'
    && event.data.title.includes('Errand')), 'the conversation itself is untouched');

  core.retireErrand('asuna-errand-1');
  for (let i = 0; i < 50 && !ctx.workspaceRegistry.archivedSessionIds.includes('asuna-errand-1'); i++)
    await new Promise(resolve => setTimeout(resolve, 20));
  assert.ok(ctx.workspaceRegistry.archivedSessionIds.includes('asuna-errand-1'), 'the copy is archived once idle');
  assert.ok(!ctx.workspaceRegistry.archivedSessionIds.includes('group'));
  await group.dispose();
});
