/** Probe of a picture in the action brain's native tool loop: `read_image` returns an image that DSH stores as an
 * attachment, the next model request carries it, and a cold reload of the session replays it unchanged.
 *
 * The DSH action scope, tool loop, attachment storage and session persistence are real; only inference and the
 * worker's image answer are synthetic. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { LlmAdapter } from '@deepseek-ai/dsh-llm';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import { AgentPresetRegistry } from '@deepseek-ai/dsh-agent-preset-registry';
import LocalAttachmentStore from '@deepseek-ai/dsh-attachment-local';
import Persistence from '../packages/cognition-core/src/persistence.js';
import { CognitionCore } from '../packages/cognition-core/src/index.js';

const root = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-native-image-'));
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAEUlEQVR4nGMQSNiAFTEMpAQAtXc2ARPYJ6YAAAAASUVORK5CYII=';
const ctx = new Context();
new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx);
new AgentRegistry(ctx); new SystemPrompt(ctx, {}); new Tools(ctx);
new AgentLoop(ctx, { agents: [], maxParallelToolCalls: { get: () => 4 } });
new Loader(ctx, { baseUrl: import.meta.url });
new AgentPresetRegistry(ctx, { default: 'asuna-action', selectedDefault: { get: () => undefined } });
await ctx.plugin(LocalAttachmentStore, { dshHome: root });
new Persistence(ctx, { root: path.join(root, 'sessions') });
// Match the Web Host's injected business-plugin context. Creating Agents
// directly from the root Context bypasses Cordis's service access checks.
let host;
await ctx.plugin({ name: 'image-probe-host',
  inject: ['llm', 'agents', 'agentPresets', 'sessions', 'sessionPersistence'],
  apply(scope) { host = scope; } });
const requests = [], business = [];
class Adapter extends LlmAdapter {
  async *stream(options) {
    requests.push(options);
    if (requests.length === 1) {
      yield { type: 'tool-call-delta', index: 0, id: 'read-authorized-image', name: 'read_image',
        argumentsDelta: JSON.stringify({ ref: 'offline-image' }) };
      yield { type: 'finish', reason: { kind: 'tool-calls' } };
    } else {
      yield { type: 'text-delta', index: 0, text: '离线图片已读取。' };
      yield { type: 'finish', reason: { kind: 'stop' } };
    }
  }
}
host.llm.registerAdapter(['fixture'], new Adapter());
const binding = { lane: 'executor', allowed_capabilities: ['read_image'] };
const core = new CognitionCore(host, { routes: { action: { provider: 'fixture', model: 'one-model' } } });
core.ready = async () => {};
core.specs = [{ name: 'read_image', description: 'Read an authorized offline image',
  parameters: { ref: { type: 'string', required: true } } }];
core.worker = { async call(method, args) {
  business.push({ method, args });
  if (method === 'session') return binding;
  if (method === 'tool') return { ref: args.args.ref, image: { data: png, media_type: 'image/png' } };
  return {};
} };
ctx.provide('asuna', core);
let handle;
try {
  await host.agentPresets.register({ id: 'asuna-action',
    plugins: [{ name: new URL('../packages/cognition-core/src/action.js', import.meta.url).href }] });
  handle = await host.agents.create({ sessionId: 'image-action-probe', meta: { cwd: root },
    agentOptions: { provider: 'fixture', model: 'one-model' },
    setup: async scope => { await host.agentPresets.mount(scope, 'asuna-action'); } });
  const agent = handle.agent;
  assert.throws(() => agent.ctx.attachments, /without inject/,
    'The probe must retain the same service boundary as the loaded Web plugin');
  const stage = { session_id: agent.id, lane: 'executor', phase: 'execution', token: 'image-stage',
    text: 'Read the supplied offline image.', system: 'Synthetic offline attachment verification only.' };
  Object.assign(core.state(agent.id), { current: stage, system: stage.system });
  agent.followup(core.message(stage));
  await agent.whenIdle();
  assert.equal(requests.length, 2, JSON.stringify(agent.session.snapshotEvents().filter(event =>
    ['turn/end', 'assistant/message', 'tool/result', 'agent/error'].includes(event.type))));
  assert.equal(business.filter(call => call.method === 'tool').length, 1);
  const result = agent.session.snapshotEvents().find(event => event.type === 'tool/result');
  assert(result, 'The real native loop must create the tool result');
  const image = result.data.message.content.find(block => block.type === 'image');
  assert(image, JSON.stringify(result.data));
  assert.equal(image.attachment.width, 8);
  assert.equal(image.attachment.height, 6);
  const saved = await ctx.attachments.readImage(image.attachment);
  assert(saved.data.byteLength > 0);
  assert(requests[1].messages.some(message => message.content?.some(block =>
    block.type === 'image' && block.attachment.attachmentId === image.attachment.attachmentId)),
  'The next native request must carry the durable image block');
  await ctx.sessions.flush(agent.session);
  await handle.dispose(); handle = undefined;
  const cold = await ctx.sessionPersistence.open(agent.id, 'read');
  try {
    const persisted = (await cold.read()).events.find(event => event.type === 'tool/result');
    assert.deepEqual(persisted.data.message.content, result.data.message.content);
  } finally { await cold.close(); }
  console.log(JSON.stringify({ result: 'passed', real_native_tool_loop: true,
    durable_image: image.attachment, cold_replay: true, external_model_requests: 0, evidence: root }));
} finally {
  await handle?.dispose();
  await ctx.fiber.dispose();
}
