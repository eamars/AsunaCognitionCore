// Executable native-timer probe: actual DSH scheduler, loop, JSON storage and
// JSONL sessions. No model request, Mongo connection, channel or message sink.
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import path from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime from '@deepseek-ai/dsh-llm';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import Persistence from '../packages/cognition-core/src/persistence.js';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import Storage from '@deepseek-ai/dsh-storage';
import * as StorageJson from '@deepseek-ai/dsh-storage-json';
import * as StorageDomain from '@deepseek-ai/dsh-storage-domain';
import ScheduleService from '@deepseek-ai/dsh-schedule';
import { CognitionCore } from '../packages/cognition-core/src/index.js';

const root = await mkdtemp(path.resolve('.runtime/adr008/schedule-probe-'));
const ctx = new Context();
new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx);
new Persistence(ctx, { root: path.join(root, 'sessions') });
new AgentRegistry(ctx); new SystemPrompt(ctx, {}); new Tools(ctx);
new AgentLoop(ctx, { agents: [], maxParallelToolCalls: 4 });
new Loader(ctx, { baseUrl: import.meta.url });
new AgentPresetRegistry(ctx, { default: 'asuna-scheduler', selectedDefault: { get: () => undefined } });
new Storage(ctx);
await ctx.plugin(StorageJson, { root: path.join(root, 'storage') });
await ctx.plugin(StorageDomain, { backend: 'json' });
// The probe only needs the controller's public live-agent lookup and title.
ctx.provide('sessionController', {
  resolveAgent: async id => ({ agent: ctx.agents.get(id) }), rename: async () => {},
});
await ctx.plugin(ScheduleService, {});
const core = new CognitionCore(ctx, { workspace: root });
ctx.provide('asuna', core);
core.ready = async () => {};
let delivered;
const delivery = new Promise(resolve => { delivered = resolve; });
core.worker = { call: async (method, args) => { if (method === 'schedule.deliver') delivered(args); } };
await ctx.agentPresets.register({ id: 'asuna-scheduler',
  plugins: [{ name: new URL('../packages/cognition-core/src/scheduler.js', import.meta.url).href }] });
let timer;
try {
  const sessionId = 'native-scheduler-probe';
  const created = await core.schedules.request({ session_id: sessionId, path: '/schedule/create',
    payload: { plan_id: 'probe', after_seconds: 1 } });
  const acknowledgment = await Promise.race([delivery, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('Native timer did not reach the business boundary')), 12000);
  })]);
  await ctx.agents.get(sessionId).whenIdle();
  assert.equal(acknowledgment.id, created.id);
  const events = await core.schedules.request({ session_id: sessionId, path: '/schedule/events', payload: {} });
  assert.equal(events.filter(e => e.data.operation === 'dispatch').length, 1);
  const native = ctx.agents.get(sessionId).session.snapshotEvents();
  assert.equal(native.filter(e => e.type === 'agent/inbox/spliced'
    && e.data.inserted.some(m => m.source.kind === 'schedule')).length, 1);
  assert.equal(native.filter(e => e.type === 'assistant/message').length, 0);
  assert.equal(native.filter(e => e.type === 'schedule/change').length, 0);
  await ctx.sessions.flush(ctx.agents.get(sessionId).session);
  await core.handles.get(sessionId).dispose(); core.handles.delete(sessionId);
  const resumed = await core.schedules.agent(sessionId);
  assert.equal((await core.schedules.refresh(resumed)).filter(e => e.data.operation === 'dispatch').length, 1);
  assert.equal(resumed.session.snapshotEvents().filter(e => e.type === 'asuna/schedule').every(e => e.ignorable), true);
  console.log(JSON.stringify({ result: 'passed', native_timer: created.id,
    actual_native_delivery: true, model_requests: 0, durable_evidence: root }));
} catch (error) {
  console.error(JSON.stringify({ catalog: await ctx.schedule.catalog(),
    events: ctx.agents.get('native-scheduler-probe')?.session.snapshotEvents() }, null, 2));
  throw error;
} finally {
  clearTimeout(timer);
  for (const handle of core.handles.values()) await handle.dispose();
  await ctx.fiber.dispose();
}
