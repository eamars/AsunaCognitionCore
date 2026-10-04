/** Native Web fixture: one synthetic model, two brains, repeated real tool consultation. */
import fs from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { LlmAdapter } from '@deepseek-ai/dsh-llm';
import { CognitionCore } from '../../packages/cognition-core/src/index.js';
import { AsunaApi } from '../../packages/cognition-core/src/api.js';

export const inject = ['llm', 'agents', 'agentPresets', 'sessions', 'sessionPersistence',
  'sessionController', 'workspaceRegistry', 'subagents', 'tools'];

export function apply(ctx, config) {
  const route = { provider: 'inline-fixture', model: 'synthetic-one' };
  class Adapter extends LlmAdapter {
    async listModels(provider) { return [{ provider, id: route.model, name: 'Synthetic offline' }]; }
    async resolveModel(provider, id) { return { provider, id, name: 'Synthetic offline' }; }
    async *stream(options) {
      const source = options.messages.findLast(m => m.role === 'user' && m.source?.kind === 'asuna');
      const phase = source?.source.phase;
      const media = source?.content.some(b => b.text === 'dual-media');
      const long = source?.content.some(b => b.text?.includes('dual-long'));
      const continuation = source?.content.some(b => b.text?.includes('dual-continue'));
      const intervention = source?.content.some(b => b.text?.includes('dual-intervention'));
      const held = source?.content.some(b => b.text === 'dual-intervention-start');
      const boundary = options.messages.lastIndexOf(source);
      const count = (continuation || intervention ? options.messages.slice(boundary + 1) : options.messages)
        .filter(m => m.role === 'tool').length;
      const priorAction = (continuation || intervention) && options.messages.slice(0, boundary)
        .some(m => m.role === 'assistant' && m.content.some(b => b.text?.includes(intervention ? '行动记录 A' : '行动记录 C')));
      // Native history caps pages by assistant/user messages, not tool receipts.
      const longSteps = config.longSteps ?? 600;
      const pause = () => delay(long ? 10 : 1200, undefined, { signal: options.signal });
      if (phase === 'execution' && held && count > 0) {
        yield { type: 'reasoning-delta', index: 0, text: '旧行动已读取资料，等待角色调整。' };
        await fs.writeFile(config.root + '/intervention-waiting.json', JSON.stringify({ operation: source.source.operation }));
        await new Promise((_, reject) => {
          const abort = () => {
            fs.writeFile(config.root + '/intervention-aborted.json', JSON.stringify({ operation: source.source.operation }));
            reject(options.signal.reason);
          };
          options.signal.addEventListener('abort', abort, { once: true });
          if (options.signal.aborted) abort();
        });
      }
      yield { type: 'reasoning-delta', index: 0, text: phase === 'execution'
        ? (long ? `长行动推理 ${String(count + 1).padStart(3, '0')}：核对当前来源。`
          : `行动推理 ${count + 1}：先核对资料，再按角色判断继续。`) : '角色推理：结合自己的判断作答。' };
      await pause();
      const text = phase === 'execution' ? (long ? `长行动记录 ${String(count + 1).padStart(3, '0')} / ${longSteps}。`
        : ['行动记录 A：准备询问角色。', '行动记录 B：第一次咨询后继续，重新核对。', '行动记录 C：两次咨询后完成任务。'][count])
        : ({ MONOLOGUE: '角色独白：我先想清楚，再让行动脑去处理。', DECIDE: '{"speak":false,"reason":"准备执行离线任务"}',
          SPEAK: '角色表达：我来看看，稍后告诉你结果。', CONSULT: '角色咨询答复：保留原来的资料，继续核对。' })[phase];
      yield { type: 'text-delta', index: 1, text: (text ?? '普通原生会话输出。')
        + (phase === 'execution' && (continuation || intervention) ? ` 续接上下文：${priorAction ? '已读取上一轮行动记录 ' + (intervention ? 'A' : 'C') : '首次执行'}。` : '')
        + (phase === 'execution' && media && count === 2
          ? '\n\n[行动资料](./action-note.txt)\n\n![离线附件](./inline.png)' : '') };
      await pause();
      if (phase === 'execution' && source.content.some(b => b.text === 'dual-failure')) throw new Error('Synthetic action failure');
      if (phase === 'execution' && (held && count === 0 || long && count < longSteps - 1)) {
        yield { type: 'tool-call-delta', index: 2, id: `record-${count + 1}`, name: 'fixture_record',
          argumentsDelta: JSON.stringify({ step: count + 1 }) };
        yield { type: 'finish', reason: { kind: 'tool-calls' } };
      } else if (phase === 'execution' && !long && count < 2) {
        yield { type: 'tool-call-delta', index: 2, id: `${source.source.operation}:consult-${count + 1}`, name: 'consult_character',
          argumentsDelta: JSON.stringify({ query: `第 ${count + 1} 次咨询` }) };
        yield { type: 'finish', reason: { kind: 'tool-calls' } };
      } else yield { type: 'finish', reason: { kind: 'stop' } };
    }
  }
  ctx.llm.registerAdapter(['inline-fixture'], new Adapter());
  const core = new CognitionCore(ctx, { persona: 'inline-fixture', routes: { character: route, action: route } });
  core.ready = async () => {};
  core.personas.set('inline-fixture', { preset: 'inline-role' });
  core.specs = [{ name: 'consult_character', description: 'Ask the character in this offline fixture',
    parameters: { query: { type: 'string', required: true } } },
    { name: 'fixture_record', description: 'Read one numbered synthetic source record',
      parameters: { step: { type: 'integer', required: true } } }];
  ctx.provide('asuna', core); new AsunaApi(ctx, core);
  const roleId = 'brain-inline-role-v1', bindings = new Map(), plans = new Map(), operations = new Map();
  const stage = (id, phase, text, extra = {}) => {
    const event = { kind: 'stage', session_id: id, lane: bindings.get(id).lane, phase,
      token: `${id}:${phase}:${Date.now()}`, text: text ?? `offline:${phase}`,
      system: 'Synthetic offline UI fixture. No external services.', binding: { ...bindings.get(id), ...extra } };
    operations.set(event.token, event); return event;
  };
  const startTask = async text => {
    const marker = config.root + '/inline-continuity.json';
    const interventionMarker = config.root + '/inline-intervention.json';
    const prior = text.includes('dual-intervention-next') ? JSON.parse(await fs.readFile(interventionMarker, 'utf8'))
      : text.includes('dual-continue-next') ? JSON.parse(await fs.readFile(marker, 'utf8')) : null;
    const id = prior?.id ?? `brain-inline-action-${Date.now()}`;
    const taskId = text.includes('dual-intervention-next') ? prior.taskId : `inline-task-${Date.now()}`;
    bindings.set(id, { ...bindings.get(roleId), _id: id, lane: 'executor', cwd: config.root + '/Action',
      parent_session_id: roleId, role_session_id: roleId, task_id: taskId, allowed_capabilities: ['consult_character', 'fixture_record'] });
    if (text.includes('dual-continue')) await fs.writeFile(marker, JSON.stringify({ id, taskId }));
    if (text.includes('dual-intervention-next')) {
      operations.delete(prior.token);
      await core.onEvent({ kind: 'task_fenced', token: prior.token, session_id: id,
        task_id: taskId, intent_revision: 2, reason: 'task_revised' });
    }
    const event = stage(id, 'execution', text);
    if (text.includes('dual-intervention')) await fs.writeFile(interventionMarker, JSON.stringify({ id, taskId,
      token: event.token, prior_token: prior?.token }));
    await core.onEvent(event);
  };
  core.worker = { async call(method, args) {
    if (method === 'stage.valid') return { valid: operations.has(args.token)
      && (!args.session_id || operations.get(args.token).session_id === args.session_id) };
    if (method === 'session') return bindings.get(args.session_id);
    if (method === 'input_policies') {
      if (config.policyDelayMs) await delay(config.policyDelayMs);
      return config.policyReadOnly ? { [roleId]: 'QQ 会话仅供查看，请在 QQ 中回复。' } : {};
    }
    if (method === 'input') {
      const plan = { sequence: ['MONOLOGUE', 'DECIDE', 'SPEAK'], text: args.text };
      plans.set(args.session_id, plan);
      await core.onEvent(stage(args.session_id, plan.sequence.shift()));
    } else if (method === 'result') {
      const event = operations.get(args.token);
      if (args.error) { operations.delete(args.token); return {}; }
      if (event?.phase === 'CONSULT') return {};
      const plan = plans.get(event?.session_id);
      if (event?.lane === 'character' && plan) {
        if (plan.sequence.length) await core.onEvent(stage(event.session_id, plan.sequence.shift()));
        else {
          plans.delete(event.session_id);
          await core.onEvent({ kind: 'episode_finished', session_id: event.session_id });
          if (plan.text?.includes('dual-')) setTimeout(() => {
            startTask(plan.text).catch(error => fs.writeFile(config.root + '/inline-fixture-failed.txt', error.stack));
          }, 20);
        }
      } else if (event?.lane === 'character') await core.onEvent({ kind: 'episode_finished', session_id: event.session_id });
      else if (event?.lane === 'executor' && event.text === 'dual-continue-auto') {
        // Deliver the successor while the first native Turn is still stopping.
        // Waiting for that Turn in the result acknowledgement would deadlock.
        await startTask('dual-continue-next');
      }
    } else if (method === 'tool') {
      const operation = operations.get(args.operation);
      if (!operation || operation.session_id !== args.session_id) throw new Error('NATIVE_OPERATION_NOT_ACTIVE');
      if (args.tool === 'fixture_record') return { source_record: args.args.step,
        text: `完整来源记录 ${String(args.args.step).padStart(3, '0')}：这一行来自真实原生工具回执。` };
      const action = bindings.get(args.session_id);
      await core.onEvent(stage(roleId, 'CONSULT', args.args.query, { task_id: action.task_id }));
      await ctx.agents.get(roleId).whenIdle();
      const answer = ctx.agents.get(roleId).session.snapshotEvents().findLast(e => e.type === 'assistant/message');
      return { answer: answer.data.message.content.filter(b => b.type === 'text').map(b => b.text).join('') };
    }
    return {};
  }, async dispose() {} };
  ctx.on('dispose', () => core.dispose());
  void (async () => {
    await fs.mkdir(config.root + '/Local', { recursive: true });
    await fs.mkdir(config.root + '/Action', { recursive: true });
    await fs.writeFile(config.root + '/Action/action-note.txt', '行动会话来源文件：保留原来的资料，完成核对。');
    await fs.writeFile(config.root + '/Action/inline.png', Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF1cAAAAASUVORK5CYII=', 'base64'));
    const role = new URL('../../packages/cognition-core/src/role.js', import.meta.url).href;
    const action = new URL('../../packages/cognition-core/src/action.js', import.meta.url).href;
    await ctx.agentPresets.register({ id: 'inline-role', title: '演示 · 角色脑', plugins: [{ name: role }] });
    await ctx.agentPresets.register({ id: 'asuna-action', title: '行动脑', plugins: [{ name: action }] });
    bindings.set(roleId, { _id: roleId, lane: 'character', cwd: config.root + '/Local',
      scene_id: 'local:inline-probe', persona: 'inline-fixture', allowed_capabilities: [] });
    const agent = await core.ensureAgent(stage(roleId, 'MONOLOGUE'));
    if (!agent.session.snapshotEvents().some(e => e.type === 'session/title'))
      agent.session.append('session/title', { title: '双脑连续记录 · 离线验证', source: { kind: 'user' }, messageSeqs: [] });
    await ctx.sessions.flush(agent.session);
    if (!agent.session.snapshotEvents().some(e => e.type === 'turn/start')) {
      await core.onEvent(stage(roleId, 'MONOLOGUE'));
      await agent.whenIdle();
    }
    await ctx.workspaceRegistry.archiveSession('brain-role-probe-v4');
    await fs.writeFile(config.root + '/inline-fixture-ready.json', JSON.stringify({ roleId, provider: route.provider }));
  })().catch(error => fs.writeFile(config.root + '/inline-fixture-failed.txt', error.stack));
}
