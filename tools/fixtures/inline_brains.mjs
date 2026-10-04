/** Native Web fixture (ADR-011): one synthetic model, two brains on native tool calls, no Python/Mongo/QQ.
 *
 * Her turn: think, then (for `dual-*` input) delegate, then her words. The action brain reads two
 * synthetic records, asks her once (ask_character → her internal turn with answer_action), leaves a
 * progress note, and reports; then her turn reads the result. Every model call is synthetic. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { LlmAdapter } from '@deepseek-ai/dsh-llm';
import { CognitionCore } from '../../packages/cognition-core/src/index.js';
import { AsunaApi } from '../../packages/cognition-core/src/api.js';

export const inject = ['llm', 'agents', 'agentPresets', 'sessions', 'sessionPersistence',
  'sessionController', 'workspaceRegistry', 'subagents', 'tools'];

const ROLE_SPECS = [
  { name: 'think', description: 'Write this turn\'s short thought first.', parameters: { thought: { type: 'string', required: true } } },
  { name: 'recall', description: 'Recall.', parameters: { query: { type: 'string', required: true } } },
  { name: 'delegate', description: 'Hand a task to the action brain.',
    parameters: { title: { type: 'string', required: true }, brief: { type: 'string', required: true } } },
  { name: 'stay_silent', description: 'End the turn without speaking.', parameters: { reason: { type: 'string', required: true } } },
  { name: 'answer_action', description: 'Answer the action brain.', parameters: { answer: { type: 'string', required: true } } },
];
const ACTION_SPECS = [
  { name: 'ask_character', description: 'Ask her and wait.', parameters: { question: { type: 'string', required: true } } },
  { name: 'report_progress', description: 'Leave her a note.', parameters: { note: { type: 'string', required: true } } },
  { name: 'fixture_record', description: 'Read one numbered synthetic source record',
    parameters: { step: { type: 'integer', required: true } } },
];

export function apply(ctx, config) {
  // Resolved like the worker's paths, so the sidebar files each session under its workspace.
  const localDir = path.resolve(config.root, 'Local'), actionDir = path.resolve(config.root, 'Action');
  const route = { provider: 'inline-fixture', model: 'synthetic-one' };
  const call = (index, id, name, args) => ({ type: 'tool-call-delta', index, id, name, argumentsDelta: JSON.stringify(args) });
  class Adapter extends LlmAdapter {
    async listModels(provider) { return [{ provider, id: route.model, name: 'Synthetic offline' }]; }
    async resolveModel(provider, id) { return { provider, id, name: 'Synthetic offline' }; }
    async *stream(options) {
      const source = options.messages.findLast(m => m.role === 'user' && m.source?.kind === 'asuna');
      const phase = source?.source.phase, trigger = source?.source.trigger;
      const boundary = options.messages.lastIndexOf(source);
      const after = options.messages.slice(boundary + 1);
      const done = after.filter(m => m.role === 'tool').length;
      const text = (source?.content ?? []).map(b => b.text ?? '').join('');
      const pause = () => delay(600, undefined, { signal: options.signal });
      const id = `${source?.source.operation ?? 'x'}:${done}`;
      if (phase === 'execution' || phase === 'message') {
        yield { type: 'reasoning-delta', index: 0, text: `行动推理 ${done + 1}：先核对资料，再看要不要问她。` };
        await pause();
        const steps = [call(1, id, 'fixture_record', { step: 1 }), call(1, id, 'ask_character', { question: '要查本地的，还是也看看邻近城市？' }),
          call(1, id, 'report_progress', { note: '本地的资料读完了，正在核对邻近城市。' }), call(1, id, 'fixture_record', { step: 2 })];
        if (text.includes('dual-failure') && done === 1) throw new Error('Synthetic action failure');
        if (done < steps.length) { yield steps[done]; yield { type: 'finish', reason: { kind: 'tool-calls' } }; return; }
        yield { type: 'text-delta', index: 1, text: '查完了：本地明天有小雨，邻近城市晴。建议带一把折叠伞。\n\n- 来源记录 1、2 都已核对\n- 降水概率 60%' };
        yield { type: 'finish', reason: { kind: 'stop' } };
        return;
      }
      if (phase === 'TURN' || phase === 'REPAIR') {
        yield { type: 'reasoning-delta', index: 0, text: '角色推理：结合自己的判断作答。' };
        await pause();
        const thought = trigger === 'question' ? '它问城市。他说的是本地，邻近的顺带看看也好。'
          : trigger === 'task_result' ? '结果回来了：有小雨。提醒他带伞。'
          : text.includes('dual-') ? '他想知道明天要不要带伞。我自己查不了，交给行动脑去看。' : '他来打招呼了，挺开心的，简单回一句。';
        const plan = trigger === 'question' ? [call(1, id, 'think', { thought }), call(1, id, 'answer_action', { answer: '主要看本地，邻近城市顺带看一眼就行。' })]
          : text.includes('dual-') && !trigger ? [call(1, id, 'think', { thought }),
            call(1, id, 'delegate', { title: '查明天的天气', brief: '帮我查一下明天本地的天气，看要不要带伞；邻近城市也顺带看一眼。只要结论和依据。' })]
          : [call(1, id, 'think', { thought })];
        if (done < plan.length) { yield plan[done]; yield { type: 'finish', reason: { kind: 'tool-calls' } }; return; }
        yield { type: 'text-delta', index: 1, text: trigger === 'task_result' ? '查到了，明天有小雨，记得带把折叠伞。'
          : text.includes('dual-') ? '我让行动脑去查了，等它回来告诉你。' : '你好呀，今天过得怎么样？' };
        yield { type: 'finish', reason: { kind: 'stop' } };
        return;
      }
      yield { type: 'text-delta', index: 1, text: '普通原生会话输出。' };
      yield { type: 'finish', reason: { kind: 'stop' } };
    }
  }
  ctx.llm.registerAdapter(['inline-fixture'], new Adapter());
  const core = new CognitionCore(ctx, { persona: 'inline-fixture', routes: { character: route, action: route } });
  core.ready = async () => {};
  core.personas.set('inline-fixture', { preset: 'inline-role' });
  core.roleSpecs = ROLE_SPECS;
  core.specs = ACTION_SPECS;
  ctx.provide('asuna', core); new AsunaApi(ctx, core);
  const roleId = 'brain-inline-role-v2', bindings = new Map(), operations = new Map(), turns = new Map();
  const now = () => new Date().toISOString();
  const stage = (id, phase, text, extra = {}) => {
    const event = { kind: 'stage', session_id: id, lane: bindings.get(id).lane, phase,
      token: `${id}:${phase}:${Date.now()}:${Math.random().toString(36).slice(2, 6)}`, text: text ?? `offline:${phase}`,
      system: 'Synthetic offline UI fixture. No external services.', binding: bindings.get(id), ...extra };
    operations.set(event.token, event); return event;
  };
  const collab = (task, entry) => core.onEvent({ kind: 'collab', session_id: roleId, task_id: task.id, thread: task.id,
    title: task.title, entry: { at: now(), ...entry } });
  const roleTurn = async (trigger, text) => {
    const event = stage(roleId, 'TURN', text, { tools: trigger === 'question' ? ['think', 'recall', 'answer_action']
      : ['think', 'recall', 'delegate', 'stay_silent'], trigger });
    turns.set(event.token, { trigger });
    await core.onEvent(event);
    return event;
  };
  const startTask = async task => {
    const id = 'brain-inline-action-' + task.id;
    bindings.set(id, { ...bindings.get(roleId), _id: id, lane: 'executor', cwd: actionDir,
      parent_session_id: roleId, role_session_id: roleId, task_id: task.id,
      allowed_capabilities: ACTION_SPECS.map(spec => spec.name) });
    await core.onEvent(stage(id, 'execution', task.brief + '\n\n—— 程序附注（不是她说的话）——\n' + JSON.stringify({ original_input: task.input }),
      { trigger: 'brief', title: task.title, task: { _id: task.id, thread: task.id, title: task.title, parent_session_id: roleId } }));
  };
  const asked = new Map();
  core.worker = { async call(method, args) {
    if (method === 'stage.valid') return { valid: operations.has(args.token)
      && (!args.session_id || operations.get(args.token).session_id === args.session_id) };
    if (method === 'session') return bindings.get(args.session_id);
    if (method === 'input_policies') {
      if (config.policyDelayMs) await delay(config.policyDelayMs);
      return config.policyReadOnly ? { [roleId]: { key: 'read_only', platform: 'QQ' } } : {};
    }
    if (method === 'action_message.delivered') return { recorded: true };
    if (method === 'input') {
      const event = stage(args.session_id, 'TURN', args.text, { tools: ['think', 'recall', 'delegate', 'stay_silent'] });
      turns.set(event.token, { input: args.text });
      await core.onEvent(event);
    } else if (method === 'role_tool') {
      const turn = turns.get(args.operation) ?? {};
      if (args.tool === 'delegate') {
        const task = { id: 'task-' + Date.now().toString(36), title: args.args.title, brief: args.args.brief, input: turn.input };
        turn.delegated = task;
        await collab(task, { id: 'brief:' + task.id, kind: 'message', from: 'character', text: task.brief, title: task.title });
        return { value: { task: task.id, state: '已交给行动脑，正在排队' } };
      }
      if (args.tool === 'answer_action') { turn.answer = args.args.answer; return { value: { answered: true }, conclude: true } }
      if (args.tool === 'stay_silent') return { value: { silent: true }, conclude: true };
      return { value: { saved: true } };
    } else if (method === 'result') {
      const event = operations.get(args.token);
      if (args.error) { operations.delete(args.token); return {}; }
      if (event?.lane === 'character') {
        const turn = turns.get(args.token) ?? {};
        setTimeout(() => core.onEvent({ kind: 'turn_done', session_id: event.session_id }), 5);
        if (turn.delegated) setTimeout(() => startTask(turn.delegated)
          .catch(error => fs.writeFile(config.root + '/inline-fixture-failed.txt', error.stack)), 50);
        if (turn.trigger === 'question') asked.get('pending')?.(turn.answer);
      } else if (event?.lane === 'executor') {
        const task = event.task;
        await collab({ id: task._id, title: task.title }, { id: 'status:' + task._id + ':finished', kind: 'status', state: 'done' });
        setTimeout(() => roleTurn('task_result', '你交给行动脑的「' + task.title + '」有了结果。')
          .catch(error => fs.writeFile(config.root + '/inline-fixture-failed.txt', error.stack)), 300);
      }
    } else if (method === 'tool') {
      const operation = operations.get(args.operation);
      if (!operation || operation.session_id !== args.session_id) throw new Error('NATIVE_OPERATION_NOT_ACTIVE');
      const task = { id: operation.task._id, title: operation.task.title };
      if (args.tool === 'fixture_record') return { source_record: args.args.step,
        text: `完整来源记录 ${String(args.args.step).padStart(3, '0')}：这一行来自真实原生工具回执。` };
      if (args.tool === 'report_progress') {
        await collab(task, { id: 'progress:' + args.call_id, kind: 'progress', from: 'action', text: args.args.note });
        return { noted: true };
      }
      await collab(task, { id: 'q:' + args.call_id, kind: 'question', from: 'action', text: args.args.question });
      const answer = new Promise(resolve => asked.set('pending', resolve));
      await roleTurn('question', '行动脑在做「' + task.title + '」时问你：' + args.args.question);
      const value = await answer;
      await collab(task, { id: 'a:' + args.call_id, kind: 'answer', from: 'character', text: value });
      return { answer: value, internal: true };
    }
    return {};
  }, async dispose() {} };
  ctx.on('dispose', () => core.dispose());
  void (async () => {
    await fs.mkdir(localDir, { recursive: true });
    await fs.mkdir(actionDir, { recursive: true });
    const role = new URL('../../packages/cognition-core/src/role.js', import.meta.url).href;
    const action = new URL('../../packages/cognition-core/src/action.js', import.meta.url).href;
    await ctx.agentPresets.register({ id: 'inline-role', title: 'Demo role', plugins: [{ name: role }] });
    await ctx.agentPresets.register({ id: 'asuna-action', title: 'Action', plugins: [{ name: action }] });
    bindings.set(roleId, { _id: roleId, lane: 'character', cwd: localDir,
      scene_id: 'local:inline-probe', persona: 'inline-fixture', allowed_capabilities: [] });
    const agent = await core.ensureAgent({ session_id: roleId, lane: 'character', binding: bindings.get(roleId) });
    if (!agent.session.snapshotEvents().some(e => e.type === 'session/title'))
      agent.session.append('session/title', { title: 'Demo · two brains', source: { kind: 'user' }, messageSeqs: [] });
    await ctx.sessions.flush(agent.session);
    // A conversation is listed once it has a turn: open with one internal moment.
    if (!agent.session.snapshotEvents().some(e => e.type === 'turn/start')) {
      await roleTurn('internal', 'offline:hello');
      await agent.whenIdle();
    }
    await fs.writeFile(config.root + '/inline-fixture-ready.json', JSON.stringify({ roleId, provider: route.provider }));
  })().catch(error => fs.writeFile(config.root + '/inline-fixture-failed.txt', error.stack));
}
