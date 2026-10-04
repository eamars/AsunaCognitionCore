import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { PERSONA_PREFIX_SECTION } from '@deepseek-ai/dsh-system-prompt';
import { defineTool } from '@deepseek-ai/dsh-tools';
import * as todoTool from '@deepseek-ai/dsh-tool-todo';
import * as webTool from '@deepseek-ai/dsh-tool-web';
import * as skillTool from '@deepseek-ai/dsh-tool-skill';
import * as skillFilesystem from '@deepseek-ai/dsh-skill-filesystem';
import SkillService from '@deepseek-ai/dsh-skill';
import ScheduleService from '@deepseek-ai/dsh-schedule';
import { attachImage, asunaRender } from './tool-output.js';
import { BusinessWorker } from './worker.js';
import { NativeSchedules } from './schedule.js';
import { AsunaApi } from './api.js';
import { readSpill } from './spill.js';
import { normalizePersona } from './persona.js';
import z from '@deepseek-ai/schemastery';

export const name = 'asuna-cognition-core';
export const inject = ['agents', 'agentPresets', 'sessionPersistence', 'sessions',
  'sessionController', 'workspaceController', 'workspaceRegistry', 'storageDomain', 'tools', 'asunaFloor', 'llm'];

const Route = z.object({ provider: z.string(), model: z.string(), reasoningEffort: z.string(), maxTokens: z.number() });
export const Config = z.object({ python: z.string().volatile(), workspace: z.string().volatile(),
  configPath: z.string().volatile(), persona: z.string().volatile(),
  // D-6: mount DSH Schedule when the Host has none (default). By DSH design its schedule_* tools are
  // visible to every root agent; Asuna's role and action presets already restrict their own tools.
  mountSchedule: z.boolean().default(true),
  routes: z.object({ character: Route, action: Route, appraiser: Route.required(false) }).volatile() });

// Responsibility routes are configured independently; a lane name never implies a model.
const routeOf = lane => lane === 'character' ? 'character' : lane === 'appraiser' ? 'appraiser' : 'action';
const textOf = message => (message?.content ?? []).filter(x => x.type === 'text').map(x => x.text).join('\n');

export class CognitionCore {
  constructor(ctx, config) {
    this.ctx = ctx;
    this.savedConfig = () => Object.fromEntries(Object.entries(config).map(([key, value]) => [key,
      value && typeof value.get === 'function' ? value.get() : value]));
    this.config = this.savedConfig();
    this.personas = new Map();
    this.states = new Map();
    this.handles = new Map();
    this.schedules = new NativeSchedules(this);
    this.lifecycle = { state: 'unconfigured', error: null, restarts: 0 };
  }

  registerPersona(persona) {
    if (this.personas.has(persona?.id)) throw new Error('Duplicate Asuna persona: ' + persona.id);
    let normalized;
    try { normalized = normalizePersona(persona); }
    catch (error) {
      // A malformed persona package never registers; Core stays inert and says why.
      if (persona?.id === this.config.persona) { this.lifecycle.state = 'inert'; this.lifecycle.error = String(error); }
      throw error;
    }
    this.personas.set(persona.id, normalized);
    if (persona.id === this.config.persona && this.config.python && this.config.configPath && this.config.workspace)
      this.ready().catch(error => {
        this.ctx.logger.warn(String(error));
        process.stderr.write('Asuna worker could not start: ' + String(error) + '\n');
      });
    return () => this.personas.delete(persona.id);
  }

  ready() {
    if (!this.initializing) this.initializing = (async () => {
      const persona = this.personas.get(this.config.persona);
      if (!persona) throw new Error('Select an installed Asuna persona');
      if (!this.config.python || !this.config.configPath || !this.config.workspace)
        throw new Error('Configure the Asuna Python worker, workspace, and local configuration');
      this.lifecycle.state = 'starting';
      const models = await this.resolveRoutes(this.config.routes);
      const schedule = await this.attachSchedule();
      this.worker = new BusinessWorker({ ...this.config, pythonPath: await this.ctx.asunaFloor.workerPath() },
        event => this.onEvent(event), this.ctx.logger);
      this.worker.onFailure = error => this.workerFailed(error);
      const status = await this.worker.call('initialize', { persona: await this.ctx.asunaFloor.persona(persona),
        skill_directories: await this.ctx.asunaFloor.skillPaths(persona), routes: this.config.routes, models,
        integration_project: await this.ctx.asunaFloor.integrationProject(persona),
        skill_workspace: await this.ctx.asunaFloor.skillWorkspace(), schedule });
      await this.worker.call('publication.activated', { publications: await this.ctx.asunaFloor.workerReady() });
      await this.ctx.workspaceController.create({ path: status.workspace });
      this.specs = await this.worker.call('tool_specs');
      this.lifecycle.state = 'ready'; this.lifecycle.error = null;
    })().catch(async error => {
      this.lifecycle.state = 'failed'; this.lifecycle.error = String(error);
      if (this.worker) { this.worker.onFailure = null; await this.worker.dispose(); }
      throw error;
    });
    return this.initializing;
  }

  // Schedule is optional in the stock Web profile. Reuse it if installed; otherwise mount that
  // same native service once in this Host, unless mountSchedule is false (then plans are off).
  async attachSchedule() {
    if (!this.ctx.get('schedule')) {
      if (this.config.mountSchedule === false) return false;
      if (!this.scheduleMounted) { this.scheduleMounted = true; await this.ctx.plugin(ScheduleService, {}); }
    }
    await new Promise(resolve => { this.ctx.inject(['schedule'], ctx => {
      this.schedules.ctx = ctx; resolve();
    }); });
    return true;
  }

  async resolveRoutes(routes) {
    const models = {};
    for (const lane of ['character', 'action', 'appraiser']) {
      const route = routes[lane];
      if (!route?.provider && lane === 'appraiser') continue;   // optional: the affect appraiser is off when unset
      const model = await this.ctx.llm.resolveModelInfo(route.provider, route.model);
      if (!Number.isInteger(route.maxTokens) || route.maxTokens < 1
          || model.context && route.maxTokens >= model.context.contextWindow)
        throw new Error('INVALID_OUTPUT_LIMIT: ' + lane);
      if (model.reasoning && !model.reasoning.efforts.some(e => e.id === route.reasoningEffort))
        throw new Error('INVALID_REASONING_EFFORT: ' + lane);
      models[lane] = { model: route.model, provider: route.provider, max_tokens: route.maxTokens,
        reasoning_effort: route.reasoningEffort, input_modalities: model.inputModalities ?? [],
        context_window: model.context?.contextWindow ?? null, token_counter: 'native-host' };
    }
    return models;
  }

  state(id) {
    if (!this.states.has(id)) this.states.set(id, {
      queue: [], current: null, waiter: null, claimed: [], admitted: null, system: '', finish: null,
    });
    return this.states.get(id);
  }

  next(id, signal) {
    const state = this.state(id);
    if (state.queue.length) return Promise.resolve(state.queue.shift());
    if (state.waiter) throw new Error('Asuna stage already awaited');
    return new Promise((resolve, reject) => {
      const abort = () => { state.waiter = null; reject(signal.reason ?? new Error('Cancelled')); };
      signal?.addEventListener('abort', abort, { once: true });
      state.waiter = {
        resolve: value => { signal?.removeEventListener('abort', abort); resolve(value); },
        reject: error => { signal?.removeEventListener('abort', abort); reject(error); },
      };
      if (signal?.aborted) abort();
    });
  }

  message(stage) {
    return createUserMessage({ content: [{ type: 'text', text: stage.text }],
      source: { kind: 'asuna', form: 'notice', summary: 'Asuna · ' + stage.phase,
        operation: stage.token, phase: stage.phase } });
  }

  async onEvent(event) {
    if (event.kind === 'restart_requested') { await this.restart(); return; }
    if (event.kind === 'host_request') {
      try {
        let value = event.method === 'schedule' ? await this.schedules.request(event.args)
          : event.method === 'development' ? await this.ctx.asunaFloor.call(event.args.tool, event.args.args, event.args.origin)
          : (() => { throw new Error('Unknown Host request'); })();
        if (event.method === 'development' && value.project === this.ctx.asunaFloor.config.defaultProject
            && value.state === 'APPLIED') {
          const persona = this.personas.get(this.config.persona);
          await this.worker.call('persona.resources', { persona: await this.ctx.asunaFloor.persona(persona),
            skill_directories: await this.ctx.asunaFloor.skillPaths(persona) });
          [value] = await this.ctx.asunaFloor.workerReady(value.project);
        }
        await this.worker.call('host_result', { request_id: event.request_id, value });
      } catch (error) {
        await this.worker.call('host_result', { request_id: event.request_id, error: String(error) });
      }
      return;
    }
    const state = this.state(event.session_id);
    if (state.waiter) {
      const waiter = state.waiter; state.waiter = null; waiter.resolve(event); return;
    }
    if (event.kind !== 'stage') return;
    try {
      const agent = await this.ensureAgent(event);
      if (event.lane === 'executor') await this.linkAction(event);
      const saved = agent.session.snapshotEvents().find(e => e.type === 'asuna/stage-result'
        && e.data.operation === event.token);
      if (saved) {
        const actual = agent.session.snapshotEvents().find(e => e.seq === saved.data.assistant_seq
          && e.type === 'assistant/message' && !e.data.interrupted);
        if (!actual) throw new Error('Saved Asuna receipt has no native assistant event');
        await this.worker.call('result', { token: event.token,
          result: this.result(event, agent, actual, saved.data.finish_reason) });
        return;
      }
      if (state.current) { state.queue.push(event); return; }
      state.current = event;
      state.system = event.system;
      agent.followup(this.message(event));
    } catch (error) {
      await this.worker.call('result', { token: event.token, error: String(error) });
    }
  }

  async ensureAgent(stage) {
    const existing = this.ctx.agents.get(stage.session_id);
    if (existing) return existing;
    const preset = stage.lane === 'executor' ? 'asuna-action' : stage.lane === 'summary'
      ? 'asuna-summary' : stage.lane === 'appraiser' ? 'asuna-appraiser' : this.personas.get(this.config.persona).preset;
    const setup = agentCtx => this.ctx.agentPresets.mount(agentCtx, preset).then(() => undefined);
    const options = this.config.routes?.[routeOf(stage.lane)];
    const persisted = await this.ctx.sessionPersistence.stat(stage.session_id);
    const handle = persisted
      ? await this.ctx.agents.resume({ resumeSessionId: stage.session_id, agentOptions: options, setup })
      : await this.ctx.agents.create({ sessionId: stage.session_id,
        meta: { cwd: stage.binding.cwd, agentPreset: preset }, agentOptions: options, setup });
    this.handles.set(stage.session_id, handle);
    const workspace = await this.ctx.workspaceRegistry.create(stage.binding.cwd);
    await workspace.attachSession(stage.session_id);
    if (!persisted && stage.lane === 'executor')
      await this.ctx.sessionController.rename({ sessionId: stage.session_id,
        title: 'Asuna Action · ' + stage.binding.task_id });
    return handle.agent;
  }

  async linkAction(stage) {
    const role = this.ctx.agents.get(stage.binding.role_session_id);
    if (!role || role.session.snapshotEvents().some(e => e.type === 'asuna/action-linked'
        && e.data.session_id === stage.session_id)) return;
    const turn = role.session.snapshotEvents().filter(e => e.type === 'turn/start').at(-1)?.data.turn;
    if (!turn) return;
    role.session.append('asuna/action-linked', { turn, session_id: stage.session_id,
      task_id: stage.binding.task_id });
    await this.ctx.sessions.flush(role.session);
  }

  result(stage, agent, last, finishReason) {
    return {
      content: textOf(last.data.message), finish_reason: finishReason,
      tool_calls: last.data.message.content.filter(x => x.type === 'tool-call'),
      reasoning: last.data.message.content.filter(x => x.type === 'reasoning').map(x => x.text).join(''),
      receipt: stage.token, request_refs: [agent.session.id + ':' + last.seq],
      // D-3: completed compactions; the worker resends the full history window when this changes.
      compaction_generation: agent.session.snapshotEvents()
        .filter(event => event.type === 'compaction/end' && !event.data?.error).length,
    };
  }

  workerFailed(error) {
    this.lifecycle.state = 'failed'; this.lifecycle.error = String(error);
    for (const [id, state] of this.states) {
      state.waiter?.reject(error); state.waiter = null;
      if (state.current) this.ctx.agents.get(id)?.cancel({ kind: 'user' });
      state.current = null; state.admitted = null; state.claimed = []; state.queue = [];
    }
    if (!this.disposed && !this.restarting && this.lifecycle.restarts < 3) {
      this.restartTimer = setTimeout(() => this.restart().catch(e => this.ctx.logger.warn(String(e))), 1000);
      this.restartTimer.unref();
    }
  }

  async restart() {
    if (this.restarting) return this.restarting;
    this.restarting = (async () => {
      this.lifecycle.state = 'restarting'; this.lifecycle.restarts++;
      for (const [id, state] of this.states) {
        if (state.current) this.ctx.agents.get(id)?.cancel({ kind: 'user' });
        state.waiter?.reject(new Error('Asuna worker restarting'));
        state.current = null; state.waiter = null; state.queue = []; state.claimed = []; state.admitted = null;
      }
      if (this.worker) { this.worker.onFailure = null; await this.worker.dispose(); }
      this.initializing = null;
      await this.ready();
    })();
    try { await this.restarting; } finally { this.restarting = null; }
  }

  attachPreset(scope, lane) {
    // DSH 0.2 mounts a standing preset once and routes each member Agent's
    // events through it. Keep registrations here and state on session IDs.
    if (lane === 'character') scope.tools.restrict({ allow: [] });
    scope.tools.guard(exec => lane !== 'executor'
      || !this.state(exec.agent.session.id).allowed?.has(exec.name) ? 'Asuna capability not granted' : undefined);
    scope.on('tools/pre-execute', async (exec, next) => {
      await this.worker.call('session', { session_id: exec.agent.session.id });
      return next();
    });
    scope.systemPrompt.section({ name: PERSONA_PREFIX_SECTION,
      order: scope.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX'),
      interpolate: false, text: ({ agent }) => agent ? this.state(agent.session.id).system : '' });
    // A role session's system prompt is exactly the worker render (ADR-009 D-1):
    // no harness identity, no runtime-context snapshot. The render for a Web
    // turn is only known inside the assemble waterfall below (after the worker
    // admits the claimed input), so it is enforced there as the sole section;
    // a `complete` section's text is resolved before the waterfall runs.
    if (lane === 'character') scope.systemPrompt.suppressRuntimeContext();
    scope.on('agent/inbox/claimed', ({ agent, message }) => {
      if (message.source.kind === 'user') this.state(agent.session.id).claimed.push(message);
    });
    // DSH assembles BEFORE pre-step. Claimed input is prepared at this public
    // scoped assembly boundary, so the first request has its actual persona.
    scope.on('system-prompt/assemble', async (_assembly, { agent, signal }, next) => {
      if (!agent) return next();
      const state = this.state(agent.session.id);
      await this.ready();
      if (state.claimed.length) {
        if (lane !== 'character') throw new Error('Action sessions accept only their bound task');
        if (state.current) throw new Error('Asuna role input arrived during an unfinished stage');
        const humans = state.claimed.splice(0);
        const waiting = this.next(agent.session.id, signal);
        // Observe both failures immediately; the signal also releases waiting.
        const [, stage] = await Promise.all([
          this.worker.call('input', { session_id: agent.session.id,
            message_ids: humans.map(x => x.id), text: humans.map(textOf).join('\n') }), waiting,
        ]);
        if (stage.error) throw new Error(stage.error);
        state.admitted = stage;
        if (stage.kind === 'stage') { state.current = stage; state.system = stage.system; }
      }
      const assembly = await next();
      return { ...assembly,
        tools: assembly.tools.filter(tool => lane === 'executor' && state.allowed?.has(tool.name)),
        sections: lane === 'character'
          ? [{ name: PERSONA_PREFIX_SECTION, text: state.system, interpolate: false }]
          : assembly.sections.map(section =>
            section.name === PERSONA_PREFIX_SECTION ? { ...section, text: state.system } : section) };
    });
    // Route selection only. All model-visible material uses the durable inbox.
    scope.on('agent/request', async (_payload, next) => ({ ...await next(),
      ...this.config.routes?.[routeOf(lane)] }));
    scope.on('agent/pre-step', async ({ agent }, next) => {
      const state = this.state(agent.session.id);
      const decision = await next();
      if (decision.kind !== 'enter') return decision;
      const stage = state.admitted; state.admitted = null;
      if (!stage) return decision;
      return stage.kind === 'stage'
        ? { ...decision, messages: [...decision.messages, this.message(stage)] }
        : { kind: 'reject' };
    });
    scope.on('agent/assistant-stream', ({ agent, frame }) => {
      const state = this.state(agent.session.id);
      if (frame.type === 'start') state.finish = null;
      if (frame.type === 'chunk' && frame.chunk.type === 'finish') state.finish = frame.chunk.reason.kind;
    });
    scope.on('agent/turn-stopping', async ({ agent, turn, signal }) => {
      const state = this.state(agent.session.id);
      const stage = state.current;
      if (!stage) return;
      const last = agent.session.snapshotEvents().filter(event => event.type === 'assistant/message'
        && event.data.turn === turn).at(-1);
      if (!last || last.data.interrupted) throw new Error('Native stage has no complete assistant output');
      const finishReason = state.finish === 'max-tokens' ? 'length' : 'stop';
      agent.session.append('asuna/stage-result', { operation: stage.token,
        assistant_seq: last.seq, finish_reason: finishReason });
      await this.ctx.sessions.flush(agent.session);
      const waiting = lane === 'character' && stage.phase !== 'CONSULT'
        ? this.next(agent.session.id, signal) : null;
      state.current = null;
      await this.worker.call('result', { token: stage.token,
        result: this.result(stage, agent, last, finishReason) });
      if (waiting) {
        const nextStage = await waiting;
        if (nextStage.error) throw new Error(nextStage.error);
        if (nextStage.kind === 'stage') {
          state.current = nextStage; state.system = nextStage.system; agent.steer(this.message(nextStage));
        }
      }
    });
    scope.on('agent/error', ({ agent, error }) => {
      const state = this.state(agent.session.id);
      const stage = state.current; state.current = null; state.admitted = null; state.claimed = [];
      state.waiter?.reject(error); state.waiter = null;
      if (stage) this.worker?.call('result', { token: stage.token, error: String(error) }).catch(() => {});
    });
    scope.on('agent/status', ({ agent, status }) => {
      const state = this.states.get(agent.session.id);
      if (!state) return;
      if (status !== 'idle' || !state.current) return;
      const stage = state.current; state.current = null;
      this.worker?.call('result', { token: stage.token, error: 'Native turn stopped before stage completion' }).catch(() => {});
    });
    scope.on('agent/disposed', ({ agent }) => {
      const state = this.states.get(agent.session.id);
      if (!state) return;
      state.waiter?.reject(new Error('Asuna session disposed')); state.waiter = null;
      this.states.delete(agent.session.id);
    });
  }

  async attachAction(agent) {
    const scope = agent.ctx;
    await this.ready();
    const binding = await this.worker.call('session', { session_id: agent.session.id });
    if (binding.lane !== 'executor') throw new Error('Invalid action binding');
    const allowed = new Set(binding.allowed_capabilities);
    this.state(agent.session.id).allowed = allowed;
    // Restrictions filter inherited/global tools; each granted tool below is
    // registered in this action scope. Do not pass scoped names as globals.
    scope.tools.restrict({ allow: [] });
    if (allowed.has('todo_write')) await scope.plugin(todoTool, { allowParallelInProgress: true });
    if (allowed.has('web_search') || allowed.has('web_fetch'))
      await scope.plugin(webTool, { search: allowed.has('web_search'), fetch: allowed.has('web_fetch') });
    if (allowed.has('skill') && (binding.skill_directories?.length || binding.skills_dir)) {
      const skills = scope.isolate('skills');
      await skills.plugin(SkillService, {});
      await skills.plugin(skillFilesystem, { includeDefaultRoots: false,
        customSkillDirs: binding.skill_directories ?? [binding.skills_dir], watchFollowSymlinks: false });
      await skills.plugin(skillTool, {});
    }
    for (const spec of this.specs.filter(spec => allowed.has(spec.name))) {
      scope.tools.register(defineTool({ ...spec,
        output: { schema: { type: 'json' }, render: asunaRender },
        execute: async (args, exec) => {
          if (spec.name === 'read_file') {
            const spill = await readSpill(this.ctx.get('spillStore'), agent.session.id, args);
            if (spill) return spill;
          }
          return attachImage(scope, await this.worker.call('tool', {
            session_id: agent.session.id, call_id: exec.callId, tool: spec.name, args,
          }));
        },
      }));
    }
  }

  async dispose() {
    this.disposed = true;
    clearTimeout(this.restartTimer);
    if (this.worker) this.worker.onFailure = null;
    await this.worker?.dispose();
    for (const handle of this.handles.values()) await handle.dispose();
    this.handles.clear();
  }
}

export function apply(ctx, config = {}) {
  const core = new CognitionCore(ctx, config);
  ctx.provide('asuna', core);
  const activateRecovery = async value => {
    const status = core.lifecycle.state === 'ready' ? await core.worker.call('status') : null;
    if (status?.active_role || status?.active_task || status?.queued_inputs || status?.queued_tasks)
      return { ...value, activation_note: 'Business work is active; apply saved settings when idle to load the selected artifact.' };
    await core.restart();
    return (await ctx.asunaFloor.selected()).projects[value.project];
  };
  ctx.asunaFloor.activateRecovery = activateRecovery;
  new AsunaApi(ctx, core);
  ctx.inject(['settings'], child => child.effect(() => child.settings.configure({ auto: false }, ctx.fiber)));
  ctx.on('dispose', () => {
    if (ctx.asunaFloor.activateRecovery === activateRecovery) delete ctx.asunaFloor.activateRecovery;
    return core.dispose();
  });
}
