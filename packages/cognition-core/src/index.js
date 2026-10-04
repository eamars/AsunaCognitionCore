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
import { composeContext, visibleCarried } from './context-delivery.js';
import { BusinessWorker } from './worker.js';
import { NativeSchedules } from './schedule.js';
import { AsunaApi } from './api.js';
import { readSpill } from './spill.js';
import { normalizePersona } from './persona.js';
import { normalizeChannel } from './channel.js';
import { organizeNativeWorkspaces, recordChannelInput } from './navigation.js';
import { NativeChildren } from './children.js';
import { ActionRecords } from './action-records.js';
import { redactSecrets } from '@deepseek-ai/dsh-settings';
import { assertSecretReferences, nativeRoute } from './settings.js';
import z from '@deepseek-ai/schemastery';

export const name = 'asuna-cognition-core';
export const inject = ['agents', 'agentPresets', 'sessionPersistence', 'sessions',
  'sessionController', 'sessionProjections', 'sessionProjectionCache', 'workspaceController', 'workspaceRegistry', 'storageDomain', 'tools', 'asunaFloor', 'llm', 'subagents'];

const Route = z.object({ provider: z.string(), model: z.string(), reasoningEffort: z.string(), maxTokens: z.number() });
export const Config = z.object({ python: z.string().volatile(), workspace: z.string().volatile(),
  configPath: z.string().volatile(), persona: z.string().volatile(),
  // D-6: mount DSH Schedule when the Host has none (default). By DSH design its schedule_* tools are
  // visible to every root agent; Asuna's role and action presets already restrict their own tools.
  mountSchedule: z.boolean().default(true),
  deployment: z.transform(z.dict(z.any()), value => assertSecretReferences(value)).volatile(),
  secrets: z.dict(z.string().role('secret')).volatile(),
  channelAdmission: z.union(['explicit', 'automatic']).default('explicit').volatile(),
  routes: z.object({ character: Route, action: Route, appraiser: Route.required(false) }).volatile() });

// Responsibility routes are configured independently; a lane name never implies a model.
// The relevance gate (attend) is her own judgment, so it uses the character route.
const routeOf = lane => lane === 'character' || lane === 'attend' ? 'character' : lane === 'appraiser' ? 'appraiser' : 'action';
const PRESETS = { executor: 'asuna-action', summary: 'asuna-summary', appraiser: 'asuna-appraiser', attend: 'asuna-attend' };
const textOf = message => (message?.content ?? []).filter(x => x.type === 'text').map(x => x.text).join('\n');

export class CognitionCore {
  constructor(ctx, config) {
    this.ctx = ctx;
    this.savedConfig = () => Object.fromEntries(Object.entries(config).map(([key, value]) => [key,
      value && typeof value.get === 'function' ? value.get() : value]));
    this.config = this.savedConfig();
    this.personas = new Map();
    this.channels = new Map();
    this.channelWaiters = [];
    this.states = new Map();
    this.handles = new Map();
    this.channelWrites = new Map();
    this.schedules = new NativeSchedules(this);
    this.children = new NativeChildren(this);
    this.actionRecords = new ActionRecords(this);
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

  /** A platform plugin (e.g. @asuna/napcat-qq) contributes its channel kind, adapter and skills. */
  registerChannel(channel) {
    if (this.channels.has(channel?.kind)) throw new Error('Duplicate Asuna channel kind: ' + channel.kind);
    this.channels.set(channel.kind, normalizeChannel(channel));
    for (const wake of this.channelWaiters.splice(0)) wake();
    return () => this.channels.delete(channel.kind);
  }

  channelOf(sceneId) {
    const [kind, ...rest] = String(sceneId ?? '').split(':');
    return rest.length ? this.channels.get(kind) ?? null : null;
  }

  /** Every configured channel's plugin, waited for (plugins register on their own schedule), with resolved paths. */
  async channelPlugins(deployment, timeoutMs = 15000) {
    const wanted = Object.keys(deployment?.channels ?? {}), deadline = Date.now() + timeoutMs;
    for (let missing = wanted.filter(kind => !this.channels.has(kind)); missing.length;
         missing = wanted.filter(kind => !this.channels.has(kind))) {
      if (Date.now() >= deadline) throw new Error('CHANNEL_PLUGIN_NOT_INSTALLED: ' + missing.join(', '));
      await new Promise(resolve => {
        const timer = setTimeout(resolve, 500);
        this.channelWaiters.push(() => { clearTimeout(timer); resolve(); });
      });
    }
    return Promise.all([...this.channels.values()].map(channel => this.ctx.asunaFloor.channel(channel)));
  }

  async skillDirectories(persona, channels) {
    return [...await this.ctx.asunaFloor.skillPaths(persona), ...channels.flatMap(channel => channel.skill_directories)];
  }

  ready() {
    if (!this.initializing) this.initializing = (async () => {
      const persona = this.personas.get(this.config.persona);
      if (!persona) throw new Error('Select an installed Asuna persona');
      if (!this.config.python || !this.config.configPath || !this.config.workspace)
        throw new Error('Configure the Asuna Python worker, workspace, and local configuration');
      this.lifecycle.state = 'starting';
      const models = await this.resolveRoutes(this.config.routes);
      this.efforts = await this.stageEfforts();
      this.ctx.logger.info('Asuna stage efforts on the character route: ' + JSON.stringify(this.efforts));
      const schedule = await this.attachSchedule();
      this.worker = new BusinessWorker({ ...this.config, pythonPath: await this.ctx.asunaFloor.workerPath() },
        event => this.onEvent(event), this.ctx.logger);
      this.worker.onFailure = error => this.workerFailed(error);
      const nativeSessions = (await this.ctx.sessionPersistence.list()).map(row => ({
        id: row.header.id, createdAt: row.header.createdAt, agentPreset: row.header.agentPreset }));
      const channels = await this.channelPlugins(this.config.deployment);
      const status = await this.worker.call('initialize', { persona: await this.ctx.asunaFloor.persona(persona),
        skill_directories: await this.skillDirectories(persona, channels),
        routes: Object.fromEntries(Object.entries(this.config.routes).map(([lane, route]) => [lane, nativeRoute(route)])), models,
        // Her integration_* tools work on the development copy of the adapter its channel plugin ships.
        integration_project: await this.ctx.asunaFloor.integrationProject(
          [...this.channels.values()].find(channel => channel.integration_directory)),
        skill_workspace: await this.ctx.asunaFloor.skillWorkspace(), native_sessions: nativeSessions,
        deployment: this.config.deployment, secrets: this.config.secrets, admission: this.config.channelAdmission,
        channels, apply_integrations: !!this.applying, schedule });
      await this.worker.call('publication.activated', { publications: await this.ctx.asunaFloor.workerReady() });
      await organizeNativeWorkspaces(this, status.navigation);
      // Publish the native controller's own summaries after cold metadata
      // repair, including to clients already connected during worker startup.
      const primary = new Set(status.navigation.entries.map(entry => entry.session_id));
      const catalog = await this.ctx.sessionController.list({}, new AbortController().signal);
      for (const summary of catalog.items)
        if (primary.has(summary.sessionId)) this.ctx.emit('api-session/added', summary);
      this.specs = await this.worker.call('tool_specs');
      this.lifecycle.state = 'ready'; this.lifecycle.error = null;
      await this.worker.call('navigation.ready');
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
      if (!routes[lane]?.provider && lane === 'appraiser') continue;   // optional: the affect appraiser is off when unset
      const route = nativeRoute(routes[lane]);
      if (!(await this.ctx.llm.listModels(route.provider)).some(model => model.id === route.model))
        throw new Error('MODEL_NOT_CONFIGURED: ' + lane);
      const model = await this.ctx.llm.resolveModelInfo(route.provider, route.model);
      if (!Number.isInteger(route.maxTokens) || route.maxTokens < 1
          || model.context && route.maxTokens >= model.context.contextWindow)
        throw new Error('INVALID_OUTPUT_LIMIT: ' + lane);
      if (route.reasoningEffort !== undefined && !model.reasoning?.efforts.some(e => e.id === route.reasoningEffort))
        throw new Error('INVALID_REASONING_EFFORT: ' + lane);
      models[lane] = { model: route.model, provider: route.provider, max_tokens: route.maxTokens,
        reasoning_effort: route.reasoningEffort ?? model.reasoning?.defaultEffort, input_modalities: model.inputModalities ?? [],
        context_window: model.context?.contextWindow ?? null, token_counter: 'native-host' };
    }
    return models;
  }

  /** Per-stage effort on the character route, from what its model offers: the gate thinks briefly
   * (default low), and group turns may think less than the local chat (deployment.reasoning_effort.group). */
  async stageEfforts() {
    const route = nativeRoute(this.config.routes.character);
    const model = await this.ctx.llm.resolveModelInfo(route.provider, route.model);
    const offered = new Set((model.reasoning?.efforts ?? []).map(effort => effort.id));
    const wanted = { attend: 'low', ...(this.config.deployment?.reasoning_effort ?? {}) };
    return Object.fromEntries(Object.entries(wanted).filter(([, id]) => offered.has(id)));
  }

  effortFor(lane, stage) {
    if (lane === 'attend') return this.efforts?.attend;
    if (lane === 'character' && stage?.scene_kind === 'group') return this.efforts?.group;
    return undefined;
  }

  publicConfig() { return redactSecrets(Config, this.config).value; }

  async validateSettings(next) {
    if (!this.personas.has(next.persona)) throw new Error('PERSONA_NOT_INSTALLED');
    const models = await this.resolveRoutes(next.routes);
    if (!next.deployment) throw new Error('NATIVE_DEPLOYMENT_REQUIRED: import the existing deployment with setup_native_profile.py');
    assertSecretReferences(next.deployment);
    // This process imports and validates the proposed business configuration.
    // It does not initialize a RuntimeHost, consume queues, or call any model.
    const probe = new BusinessWorker({ ...next, pythonPath: await this.ctx.asunaFloor.workerPath() }, () => {}, this.ctx.logger);
    try {
      await probe.call('validate_settings', { deployment: next.deployment, secrets: next.secrets,
        models, persona: next.persona, admission: next.channelAdmission ?? 'explicit',
        channels: await this.channelPlugins(next.deployment) });
    } finally { await probe.dispose(); }
  }

  async applySettings(next) {
    if (this.applying || this.restarting) throw new Error('ASUNA_CONFIGURATION_BUSY');
    this.applying = true;
    const previous = this.config;
    try {
      await this.validateSettings(next);
      if (this.lifecycle.state === 'ready') await this.worker.call('settings.quiesce');
      this.config = next;
      try { await this.restart(); }
      catch (error) {
        this.config = previous;
        try { await this.restart(); }
        catch (recovery) { throw new Error('SETTINGS_ACTIVATION_AND_RECOVERY_FAILED: ' + String(error) + '; ' + String(recovery)); }
        throw new Error('SETTINGS_NOT_APPLIED_PREVIOUS_CONFIGURATION_RESTORED: ' + String(error));
      }
    } finally { this.applying = false; }
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

  message(stage, session, pending = []) {
    let text = stage.text, carried;
    if (stage.context && session) {
      // Composed when the notice is created: only what the session no longer shows verbatim.
      const composed = composeContext(stage.context, visibleCarried(session, pending));
      text = JSON.stringify(composed.context) + '\n' + stage.tail;
      carried = { ...composed.carried, episode: stage.episode_id };
      stage.delivery = composed.omitted;
    }
    return createUserMessage({ content: [{ type: 'text', text }],
      source: { kind: 'asuna', form: 'notice', summary: ({ character: '角色脑', executor: '行动脑', attend: '接话判断' }[stage.lane] ?? '交流摘要') + ' · ' + stage.phase,
        operation: stage.token, lane: stage.lane, phase: stage.phase, ...(carried ? { carried } : {}) } });
  }

  async onEvent(event) {
    if (event.kind === 'channel_input' || event.channel_input) {
      const receipt = event.channel_input ?? event, id = receipt.session_id;
      const previous = this.channelWrites.get(id) ?? Promise.resolve();
      const worker = this.worker;
      const writing = previous.catch(() => {}).then(async () => {
        await recordChannelInput(this, receipt);
        await worker.call('channel_input.ack', { input_id: receipt.input.id, session_id: id });
      });
      this.channelWrites.set(id, writing);
      try { await writing; } finally { if (this.channelWrites.get(id) === writing) this.channelWrites.delete(id); }
      if (event.kind === 'channel_input') return;
    }
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
            skill_directories: await this.skillDirectories(persona, await this.channelPlugins(this.config.deployment)) });
          [value] = await this.ctx.asunaFloor.workerReady(value.project);
        }
        await this.worker.call('host_result', { request_id: event.request_id, value });
      } catch (error) {
        await this.worker.call('host_result', { request_id: event.request_id, error: String(error) });
      }
      return;
    }
    if (event.kind === 'task_fenced') {
      const active = this.states.get(event.session_id)?.current;
      if (active?.token === event.token) this.ctx.agents.get(event.session_id)?.cancel(
        { kind: 'hook', reason: event.reason }, { keepInbox: true });
      return;
    }
    const state = this.state(event.session_id);
    if (state.waiter) {
      const waiter = state.waiter; state.waiter = null; waiter.resolve(event); return;
    }
    if (event.kind !== 'stage') return;
    try {
      if (event.lane !== 'character' && event.binding?.parent_session_id) {
        await this.children.start(event);
        return;
      }
      const agent = await this.ensureAgent(event);
      if (event.lane === 'executor') await this.linkAction(event);
      const saved = agent.session.snapshotEvents().find(e => e.type === 'asuna/stage-result'
        && e.data.operation === event.token);
      if (saved) {
        const actual = agent.session.snapshotEvents().find(e => e.seq === saved.data.assistant_seq
          && e.type === 'assistant/message' && !e.data.interrupted);
        if (!actual) throw new Error('Saved Asuna receipt has no native assistant event');
        await this.worker.call('result', { token: event.token,
          result: this.result(event, agent.id, actual, saved.data.finish_reason) });
        return;
      }
      if (state.current) { state.queue.push(event); return; }
      state.current = event;
      state.system = event.system;
      agent.followup(this.message(event, agent.session, agent.inbox.nextStep));
    } catch (error) {
      await this.worker.call('result', { token: event.token, error: String(error) });
    }
  }

  async ensureAgent(stage, parentAgent, descriptor) {
    // Native Archive hides a monitored conversation until its next activity.
    // It does not disable the channel. Reopen before DSH's archive gate.
    if (stage.lane === 'character' && this.channelOf(stage.binding.scene_id))
      await this.ctx.workspaceRegistry.unarchiveSession(stage.session_id);
    const existing = this.ctx.agents.get(stage.session_id);
    if (existing) return existing;
    const preset = PRESETS[stage.lane] ?? this.personas.get(this.config.persona).preset;
    const setup = async agentCtx => {
      await this.ctx.agentPresets.mount(agentCtx, preset);
      if (descriptor) agentCtx.on('agent/pre-step', async ({ agent }, next) => {
        if (!agent.session.snapshotEvents().some(event => event.type === 'subagent/descriptor'))
          agent.session.append('subagent/descriptor', descriptor);
        return next();
      });
    };
    const options = nativeRoute(this.config.routes?.[routeOf(stage.lane)]);
    const persisted = await this.ctx.sessionPersistence.stat(stage.session_id);
    const handle = persisted
      ? await this.ctx.agents.resume({ resumeSessionId: stage.session_id, parentAgent, agentOptions: options, setup })
      : await this.ctx.agents.create({ sessionId: stage.session_id,
        parentAgent, meta: { cwd: stage.binding.cwd, agentPreset: preset,
          ...(parentAgent ? { parentSession: parentAgent.id, origin: 'subagent',
            delegationDepth: (parentAgent.session.header.delegationDepth ?? 0) + 1 } : {}) },
        agentOptions: options, setup });
    this.handles.set(stage.session_id, handle);
    if (!parentAgent) {
      const workspace = await this.ctx.workspaceRegistry.create(stage.binding.cwd,
        this.channelOf(stage.binding.scene_id)?.title ?? 'Local');
      await workspace.attachSession(stage.session_id);
    }
    if (!persisted && stage.lane === 'executor') {
      // Child Agents are owned by native subagent routing; the top-level
      // session command controller deliberately refuses to acquire them.
      handle.agent.session.append('session/title', { title: stage.title ?? '行动脑 · ' + stage.binding.task_id,
        source: { kind: 'user' }, messageSeqs: [] });
      await this.ctx.sessions.flush(handle.agent.session);
    }
    return handle.agent;
  }

  async linkAction(stage) {
    await this.actionRecords.link(stage);
  }

  result(stage, sessionId, last, finishReason) {
    return {
      content: textOf(last.data.message), finish_reason: finishReason,
      tool_calls: last.data.message.content.filter(x => x.type === 'tool-call'),
      reasoning: last.data.message.content.filter(x => x.type === 'reasoning').map(x => x.text).join(''),
      receipt: stage.token, request_refs: [sessionId + ':' + last.seq],
      ...(stage.delivery ? { delivery: stage.delivery } : {}),
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
      exec.signal.throwIfAborted();
      await this.worker.call('session', { session_id: exec.agent.session.id });
      if (lane === 'executor') {
        const stage = this.state(exec.agent.session.id).current;
        const admission = await this.worker.call('stage.valid', {
          token: stage?.token, session_id: exec.agent.session.id,
        });
        if (admission.valid !== true) throw new Error('ASUNA_ACTION_STAGE_SUPPRESSED');
        exec.signal.throwIfAborted();
      }
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
    // A platform line that waited for the conversation's first turn (navigation.js) is history, not local input.
    scope.on('agent/inbox/claimed', ({ agent, message }) => {
      if (message.source.kind === 'user' && !message.source.channel) this.state(agent.session.id).claimed.push(message);
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
          this.worker.call('input', { session_id: agent.session.id, cwd: agent.session.header.cwd,
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
    scope.on('agent/request', async ({ agent, turn, step }, next) => {
      const request = await next();
      const stage = this.state(agent.session.id).current;
      if (lane === 'executor') {
        const admission = await this.worker.call('stage.valid', { token: stage?.token, session_id: agent.id });
        if (admission.valid !== true) throw new Error('ASUNA_ACTION_STAGE_SUPPRESSED');
      }
      if (lane === 'character' && stage) await this.actionRecords.pause(agent.id);
      // Business attribution only. DSH still owns the request, stream, tools,
      // process folding and assistant body. Every tool-followup step retains
      // its actual lane, even when both lanes use the same model.
      if (stage) agent.session.append('asuna/stage', { turn, step,
        operation: stage.token, lane: stage.lane, phase: stage.phase });
      // A deliberate native model selection remains authoritative for this
      // session. The plugin routes are defaults for sessions without one.
      const selected = agent.session.snapshotEvents().findLast(event => event.type === 'model/selection')?.data;
      const route = selected ?? this.config.routes?.[routeOf(lane)];
      const effort = selected ? undefined : this.effortFor(lane, stage);
      return nativeRoute({ ...request, ...route, reasoningEffort: effort ?? route?.reasoningEffort });
    });
    scope.on('agent/pre-step', async ({ agent }, next) => {
      const state = this.state(agent.session.id);
      const decision = await next();
      if (decision.kind !== 'enter') return decision;
      const stage = state.admitted; state.admitted = null;
      if (!stage) return decision;
      return stage.kind === 'stage'
        ? { ...decision, messages: [...decision.messages, this.message(stage, agent.session)] }
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
        turn, step: last.data.step, lane: stage.lane, phase: stage.phase,
        assistant_seq: last.seq, finish_reason: finishReason });
      await this.ctx.sessions.flush(agent.session);
      const waiting = lane === 'character' && stage.phase !== 'CONSULT'
        ? this.next(agent.session.id, signal) : null;
      state.current = null;
      if (lane === 'character' && stage.phase === 'CONSULT') await this.actionRecords.resume(agent.id);
      await this.worker.call('result', { token: stage.token,
        result: this.result(stage, agent.id, last, finishReason) });
      if (waiting) {
        const nextStage = await waiting;
        if (nextStage.error) throw new Error(nextStage.error);
        if (nextStage.kind === 'stage') {
          state.current = nextStage; state.system = nextStage.system; agent.steer(this.message(nextStage, agent.session));
        } else await this.actionRecords.resume(agent.id);
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

  async attachAction(agent, attachments) {
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
          exec.signal.throwIfAborted();
          const operation = this.state(agent.session.id).current?.token;
          if (spec.name === 'read_file') {
            const spill = await readSpill(this.ctx.get('spillStore'), agent.session.id, args);
            if (spill) return spill;
          }
          // The action plugin owns the declared attachment injection. An
          // Agent's context does not inherit that plugin's service grants.
          return attachImage({ attachments }, await this.worker.call('tool', {
            session_id: agent.session.id, operation, call_id: exec.callId, tool: spec.name, args,
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
    await this.children.dispose();
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
  ctx.inject(['settings'], child => child.effect(() => {
    const settings = child.settings;
    core.settings = settings;
    const release = settings.configure({ auto: false }, ctx.fiber);
    return () => { if (core.settings === settings) core.settings = null; return release(); };
  }));
  ctx.on('dispose', () => {
    if (ctx.asunaFloor.activateRecovery === activateRecovery) delete ctx.asunaFloor.activateRecovery;
    return core.dispose();
  });
}
