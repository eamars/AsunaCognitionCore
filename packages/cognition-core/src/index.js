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
import { imageRefusalListener } from './image-refusal.js';
import { holdSteeredInput } from './steer.js';
import { composeContext, visibleCarried } from './context-delivery.js';
import { BusinessWorker } from './worker.js';
import { appendFile } from 'node:fs/promises';
import { NativeSchedules } from './schedule.js';
import { AsunaApi } from './api.js';
import { readSpill } from './spill.js';
import { normalizePersona } from './persona.js';
import { normalizeChannel } from './channel.js';
import { lineBeforeTurn, organizeNativeWorkspaces, recordChannelInput } from './navigation.js';
import { NativeChildren } from './children.js';
import { applySearch, registerWebSearch } from './search.js';
import { applyFetch } from './fetch.js';
import { renderSvg } from './svg.js';
import { Collab } from './collab.js';
import { redactSecrets } from '@deepseek-ai/dsh-settings';
import { assertSecretReferences, nativeRoute, secretReferences } from './settings.js';
import { credentialKey, credentialRef } from '@deepseek-ai/dsh-credentials';
import { ensurePythonEnvironment } from './python-env.js';
import z from '@deepseek-ai/schemastery';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const name = 'asuna-cognition-core';
export const inject = ['agents', 'agentPresets', 'sessionPersistence', 'sessions',
  'sessionController', 'sessionProjections', 'sessionProjectionCache', 'workspaceController', 'workspaceRegistry', 'storageDomain', 'tools', 'asunaFloor', 'llm', 'subagents'];

const Route = z.object({ provider: z.string(), model: z.string(), reasoningEffort: z.string(), maxTokens: z.number() });
export const Config = z.object({ python: z.string().volatile(), persona: z.string().volatile(),
  // D-6: mount DSH Schedule when the Host has none (default). By DSH design its schedule_* tools are
  // visible to every root agent; Asuna's role and action presets already restrict their own tools.
  mountSchedule: z.boolean().default(true),
  deployment: z.transform(z.dict(z.any()), value => assertSecretReferences(value)).volatile(),
  channelAdmission: z.union(['explicit', 'automatic']).default('explicit').volatile(),
  routes: z.object({ character: Route, action: Route, appraiser: Route.required(false) }).volatile() });

// Responsibility routes are configured independently; a lane name never implies a model.
// The relevance gate (attend) is her own judgment, so it uses the character route.
const routeOf = lane => lane === 'character' || lane === 'attend' ? 'character' : lane === 'appraiser' ? 'appraiser' : 'action';
// Her credentials' records in DSH's credential store: <scope>/<name> (credentialRecords).
const CREDENTIAL_SCOPE = 'asuna-cognition-core';
// A tool's own refusal comes back from the worker written for the brain that called it. A lost connection
// (the worker exited or is restarting) is not, and its text names this machine's files: say what it means instead.
const WORKER_DOWN = 'ASUNA_WORKER_UNAVAILABLE: 处理工具的后台进程这会儿断开了（它会自己重启），这次调用没有完成——不是参数的问题；'
  + '这回合别再重试，没做成的事照实说（行动里写进报告）';
async function toolReply(call) {
  try { return await call(); } catch (error) { throw error?.reply ? error : new Error(WORKER_DOWN); }
}
const PRESETS = { executor: 'asuna-action', summary: 'asuna-summary', appraiser: 'asuna-appraiser', attend: 'asuna-attend' };
const textOf = message => (message?.content ?? []).filter(x => x.type === 'text').map(x => x.text).join('\n');

/** What one stage of her turn said and saw, from her session's log (coordinator: her speech, and the lines it
 * answers for). `said`: every text she wrote in the stage, in order — beside a tool call too, since her
 * conversation shows each as hers. `seen_inputs`: platform lines in her view for the first time — after the
 * last request of any earlier stage, before this stage's last request; DSH builds a request before the
 * `asuna/stage` mark it gets, so a line written after that mark waits for the next stage to be seen. */
/** Pictures attached to the owner's local messages (DSH keeps them in her conversation, so she sees them),
 * read back for the program's own record: history, her action brain's read_image, an image she may send on.
 * At most 8; one that cannot be read is reported, never skipped. */
export async function imagesOf(attachments, messages, signal) {
  const refs = messages.flatMap(message => (message?.content ?? [])
    .filter(block => block.type === 'image' && block.attachment).map(block => block.attachment)).slice(0, 8);
  const images = [];
  for (const ref of refs) {
    try {
      const { data } = await attachments.readImage(ref, signal);
      images.push({ data: Buffer.from(data).toString('base64'), media_type: ref.mediaType, name: ref.name ?? null,
        width: ref.width, height: ref.height, attachment_id: ref.attachmentId });
    } catch (error) {
      images.push({ name: ref.name ?? null, error: String(error?.code ?? error?.message ?? error).slice(0, 120) });
    }
  }
  return images;
}

/** The pictures that come with a turn, saved as DSH attachments: one that cannot be saved is left out (her
 * context says read_image reaches any picture that did not appear). */
export async function pictureParts(attachments, pictures) {
  const parts = [];
  for (const picture of pictures.slice(0, 4)) {
    if (typeof picture?.data !== 'string' || typeof picture.media_type !== 'string') continue;
    try {
      const attachment = await attachments.saveImage({ data: new Uint8Array(Buffer.from(picture.data, 'base64')),
        mediaType: picture.media_type, name: typeof picture.ref === 'string' ? picture.ref : undefined });
      parts.push({ type: 'image', attachment });
    } catch { /* left out: read_image still reaches it */ }
  }
  return parts;
}

export function stageView(events, token, turn) {
  const marks = events.filter(event => event.type === 'asuna/stage' && event.data.operation === token);
  const first = marks[0]?.seq ?? Infinity, lastRequest = marks.at(-1)?.seq ?? -1;
  const before = events.findLast(event => event.type === 'asuna/stage' && event.seq < first)?.seq ?? -1;
  const said = events.filter(event => event.type === 'assistant/message' && event.data.turn === turn
    && event.seq > first && !event.data.interrupted).map(event => textOf(event.data.message)).filter(text => text.trim());
  const seen = events.filter(event => event.type === 'user/message' && event.seq > before && event.seq < lastRequest
    && event.data.source?.kind === 'user' && event.data.source.channel && event.data.source.receipt)
    .map(event => event.data.source.receipt);
  return { said, seen_inputs: [...new Set(seen)] };
}

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
    this.collab = new Collab(this);
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
    if (persona.id === this.config.persona && this.config.deployment)
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

  /** A channel plugin that is its own adapter (it runs in this Host, not in the integration sandbox) reaches the
   *  channel API like any adapter: HTTP on this machine with its channel's token (RUNTIME_API.md). Null when the
   *  channel is not configured. */
  async channelEndpoint(kind) {
    const deployment = this.config.deployment ?? {};
    const channel = deployment.channels?.[kind];
    if (!channel) return null;
    const token = typeof channel.token === 'string' ? channel.token
      : (await this.credentialValues({ token: channel.token }))[channel.token?.$secret];
    return { url: 'http://127.0.0.1:' + (deployment.channel_port ?? 8766), channelId: kind,
             accountId: channel.account_id, token: token ?? null };
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
    // Core's own persona-agnostic skills (asuna-self-improvement), from the core artifact that is running.
    const core = path.join((await this.ctx.asunaFloor.effective('core'))?.packageRoot
      ?? fileURLToPath(new URL('../', import.meta.url)), 'skills');
    return [core, ...await this.ctx.asunaFloor.skillPaths(persona), ...channels.flatMap(channel => channel.skill_directories)];
  }

  ready() {
    if (!this.initializing) this.initializing = (async () => {
      const persona = this.personas.get(this.config.persona);
      // A profile not yet set up (a fresh install) is waiting for its settings, not failed.
      const unconfigured = message => Object.assign(new Error(message), { unconfigured: true });
      if (!persona) throw unconfigured('Select an installed Asuna persona');
      if (!this.config.deployment) throw unconfigured('Fill in the deployment settings');
      const python = await this.workerPython(this.config);
      this.lifecycle.state = 'starting';
      const models = await this.resolveRoutes(this.config.routes);
      this.efforts = await this.stageEfforts();
      this.ctx.logger.info('Asuna stage efforts on the character route: ' + JSON.stringify(this.efforts));
      const schedule = await this.attachSchedule();
      this.worker = new BusinessWorker({ ...this.config, python, dataRoot: this.ctx.asunaFloor.dataRoot,
        pythonPath: await this.ctx.asunaFloor.workerPath() },
        event => this.onEvent(event), this.ctx.logger);
      this.worker.onFailure = error => this.workerFailed(error);
      // A core candidate's worker is checked against these settings before it can be published (floor.js).
      this.releaseProbe?.();
      this.releaseProbe = this.ctx.asunaFloor.setCoreProbe(workerPath => this.validateSettings(this.config, workerPath).then(
        () => ({ exit_code: 0, stdout: ' Profile settings validated against the existing database; no live consumers started.\n', stderr: '' }),
        error => ({ exit_code: 1, stdout: '', stderr: String(error?.message ?? error) })));
      const nativeSessions = (await this.ctx.sessionPersistence.list()).map(row => ({
        id: row.header.id, createdAt: row.header.createdAt, agentPreset: row.header.agentPreset }));
      const channels = await this.channelPlugins(this.config.deployment);
      const status = await this.worker.call('initialize', { persona: await this.ctx.asunaFloor.persona(persona),
        skill_directories: await this.skillDirectories(persona, channels),
        routes: Object.fromEntries(Object.entries(this.config.routes).map(([lane, route]) => [lane, nativeRoute(route)])), models,
        // Her integration_* tools work on the development copy of the adapter its channel plugin ships.
        integration_project: await this.ctx.asunaFloor.integrationProject(
          [...this.channels.values()].find(channel => channel.integration_directory)),
        native_sessions: nativeSessions,
        deployment: this.config.deployment, secrets: await this.credentialValues(this.config.deployment), admission: this.config.channelAdmission,
        channels, apply_integrations: !!this.applying, schedule, sandbox: await this.sandboxStatus() });
      await this.worker.call('publication.activated', { publications: await this.ctx.asunaFloor.workerReady() });
      await organizeNativeWorkspaces(this, status.navigation);
      // Publish the native controller's own summaries after cold metadata
      // repair, including to clients already connected during worker startup.
      const primary = new Set(status.navigation.entries.map(entry => entry.session_id));
      const catalog = await this.ctx.sessionController.list({}, new AbortController().signal);
      for (const summary of catalog.items)
        if (primary.has(summary.sessionId)) this.ctx.emit('api-session/added', summary);
      this.specs = await this.worker.call('tool_specs');
      this.roleSpecs = await this.worker.call('role_tool_specs');
      this.lifecycle.state = 'ready'; this.lifecycle.error = null;
      await this.worker.call('navigation.ready');
    })().catch(async error => {
      if (error.unconfigured) {
        this.lifecycle.state = 'unconfigured'; this.lifecycle.error = error.message; this.initializing = null;
        throw error;
      }
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
      // An empty output limit uses what the model service declares for the model.
      route.maxTokens ??= model.defaultMaxTokens;
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

  /** The worker's interpreter: the python setting when given (a development checkout), otherwise the environment
   * built from the package's lock in the data folder on first start (python-env.js). The floor checks candidates
   * with the same interpreter. */
  async workerPython(config) {
    let python = config.python;
    if (!python) {
      const previous = { state: this.lifecycle.state, error: this.lifecycle.error };
      this.lifecycle.state = 'preparing'; this.lifecycle.error = null;
      try {
        python = await ensurePythonEnvironment({ dataRoot: this.ctx.asunaFloor.dataRoot,
          workerPath: await this.ctx.asunaFloor.workerPath(), report: step => { this.lifecycle.step = step; } });
      } finally { this.lifecycle.step = undefined; if (this.lifecycle.state === 'preparing') Object.assign(this.lifecycle, previous); }
    }
    this.ctx.asunaFloor.workerPython = python;
    return python;
  }

  /** DSH's credential store, when this Host mounts one. */
  credentialStore() {
    try { return this.ctx.get('credentials'); } catch { return undefined; }
  }

  /** Her credentials (owner 2026-10-07): one DSH credential record per name under this plugin's scope, a grant whose
   * payload is {note, env}. Only the worker asks, and it hands values to one sandboxed command at a time; a list
   * carries names, notes and variable names, never values. */
  async credentialRecords({ op, name, note, env }) {
    const store = this.credentialStore();
    if (!store) throw new Error('CREDENTIAL_STORE_MISSING: 这个 Host 没装凭据存储，凭据用不了——不是参数的问题；'
      + '重试也一样：不用凭据能做的先做，要用凭据的那一步写进报告');
    if (op === 'list') {
      const out = [];
      for (const { key } of await store.listRecords()) {
        if (!key.startsWith(CREDENTIAL_SCOPE + '/')) continue;
        const payload = (await store.readRecord(key))?.payload ?? {};
        out.push({ name: key.slice(CREDENTIAL_SCOPE.length + 1), note: String(payload.note ?? ''), env: Object.keys(payload.env ?? {}) });
      }
      return out;
    }
    const key = credentialKey(CREDENTIAL_SCOPE, name);
    if (op === 'read') return (await store.readRecord(key))?.payload ?? null;
    if (op === 'write') {
      await store.modifyRecord(key, async () => ({ kind: 'grant', payload: { note, env } }));
      return { written: name };
    }
    if (op === 'delete') { await store.deleteRecord(key); return { deleted: name }; }
    throw new Error('Unknown credentials op');
  }

  /** DSH's own sandbox (dsh-sandbox-local), when this Host mounts one: the worker runs commands under it. */
  sandboxProvider() {
    try { return this.ctx.get('sandbox'); } catch { return undefined; }
  }

  /** Whether the Host can confine the worker's commands, said once at initialize (sandbox_backend.py). Wrapping a
   * probe argv selects the platform's runner without running anything or touching any folder. */
  async sandboxStatus() {
    const sandbox = this.sandboxProvider();
    if (!sandbox) return { available: false, reason: '这个 Host 没装沙箱提供者' };
    try {
      const probe = await sandbox.confine(['probe'], { mode: 'workspace-write', workspaceRoot: this.ctx.asunaFloor.dataRoot });
      return { available: true, enforcement: probe.enforcement };
    } catch (error) { return { available: false, reason: String(error?.message ?? error) }; }
  }

  /** One command wrapped by DSH's sandbox: writes confined to `root` (owner 2026-10-06: no read or network rule). */
  async confine({ argv, root }) {
    const sandbox = this.sandboxProvider();
    if (!sandbox) throw new Error('SANDBOX_UNAVAILABLE: 这个 Host 没装沙箱提供者，命令跑不了——不是参数的问题；'
      + '重试也一样：不跑命令能做的先做，要跑命令的那一步写进报告');
    const confined = await sandbox.confine(argv, { mode: 'workspace-write', workspaceRoot: root });
    return { argv: confined.argv, enforcement: confined.enforcement };
  }

  /** The values behind the settings' credential references, resolved for this one start or check and handed to the
   * worker; never kept, never written to the settings. A reference with no value is left out, and the worker
   * names it (CREDENTIAL_NOT_CONFIGURED). */
  async credentialValues(deployment) {
    const refs = secretReferences(deployment);
    if (!refs.length) return {};
    const store = this.credentialStore();
    if (!store) throw new Error('CREDENTIAL_STORE_MISSING: this Host mounts no credential provider');
    const values = {};
    for (const ref of refs) {
      const resolved = await store.resolve(credentialRef(ref));
      if (resolved?.value) values[ref] = resolved.value;
    }
    return values;
  }

  publicConfig() { return redactSecrets(Config, this.config).value; }

  async validateSettings(next, pythonPath) {
    if (!this.personas.has(next.persona)) throw new Error('PERSONA_NOT_INSTALLED');
    const models = await this.resolveRoutes(next.routes);
    if (!next.deployment) throw new Error('NATIVE_DEPLOYMENT_REQUIRED: fill in the deployment settings');
    assertSecretReferences(next.deployment);
    // This process imports and validates the proposed business configuration.
    // It does not initialize a RuntimeHost, consume queues, or call any model.
    const probe = new BusinessWorker({ ...next, python: await this.workerPython(next), dataRoot: this.ctx.asunaFloor.dataRoot,
      pythonPath: pythonPath ?? await this.ctx.asunaFloor.workerPath() }, () => {}, this.ctx.logger);
    try {
      await probe.call('validate_settings', { deployment: next.deployment, secrets: await this.credentialValues(next.deployment),
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
      try { await this.restart('settings applied'); }
      catch (error) {
        this.config = previous;
        try { await this.restart('settings restored after a failed apply'); }
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
    // The summary is a stable identifier, never shown as prose; the client titles a turn's trigger
    // from `trigger` in the viewer's language (client.js).
    return createUserMessage({ content: [{ type: 'text', text }, ...(stage.pictureParts ?? [])],
      source: { kind: 'asuna', form: 'notice', summary: 'asuna:' + stage.lane + ':' + stage.phase,
        operation: stage.token, lane: stage.lane, phase: stage.phase,
        ...(stage.trigger ? { trigger: stage.trigger } : {}), ...(carried ? { carried } : {}) } });
  }

  /** Her words for a running action session (collab.js), marked so its claim can be acknowledged. */
  relay(message) {
    return createUserMessage({ content: [{ type: 'text', text: '她补充：\n' + message.text }],
      source: { kind: 'asuna', form: 'notice', summary: 'asuna:executor:message', lane: 'executor',
        phase: 'message', trigger: 'follow-up', message_id: message.id } });
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
    if (event.kind === 'restart_requested') {
      // A request from the worker a restart is still bringing up would otherwise be lost, leaving that
      // worker holding its queues for a restart that never comes. Honor it once the current one settles.
      if (this.restarting) { this.restartAgain = true; this.ctx.logger.warn('Asuna: restart requested during a restart; queued'); return; }
      await this.restart('worker asked: ' + (event.reason ?? 'unspecified')); return;
    }
    if (event.kind === 'host_request') {
      try {
        let value = event.method === 'schedule' ? await this.schedules.request(event.args)
          : event.method === 'development' ? await this.ctx.asunaFloor.call(event.args.tool, event.args.args, event.args.origin)
          : event.method === 'sandbox' ? await this.confine(event.args)
          : event.method === 'credentials' ? await this.credentialRecords(event.args)
          : event.method === 'render_svg' ? await renderSvg(event.args)
          : (() => { throw new Error('Unknown Host request'); })();
        if (event.method === 'development' && value.state === 'APPLIED' && value.project !== 'core') {
          // A persona or channel publication that needs no restart: new action scopes discover its
          // skills, and the next integration_start runs its adapter. A core one restarts the worker.
          const persona = this.personas.get(this.config.persona);
          const channels = await this.channelPlugins(this.config.deployment);
          await this.worker.call('persona.resources', { persona: await this.ctx.asunaFloor.persona(persona),
            skill_directories: await this.skillDirectories(persona, channels), channels });
          [value] = await this.ctx.asunaFloor.workerReady(value.project);
        }
        await this.worker.call('host_result', { request_id: event.request_id, value });
      } catch (error) {
        await this.worker.call('host_result', { request_id: event.request_id, error: error?.message ?? String(error) });
      }
      return;
    }
    // The two brains' thread and her words for a running action session (ADR-011 §4, §7.1). These name
    // her role session but never answer a stage, so they are handled before any stage waiter.
    if (event.kind === 'collab') { await this.collab.entry(event); return; }
    if (event.kind === 'action_message') { await this.collab.message(event); return; }
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
      if (event.lane === 'executor') await this.collab.start(event);
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
      if (event.channel_input && await lineBeforeTurn(this, agent, event.channel_input))
        this.ctx.logger.warn('Asuna: the line for ' + event.token + ' was not in its conversation; queued it before the turn');
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
      handle.agent.session.append('session/title', { title: stage.title ?? stage.task?.title ?? stage.binding.task_id,
        source: { kind: 'user' }, messageSeqs: [] });
      await this.ctx.sessions.flush(handle.agent.session);
    }
    return handle.agent;
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
      this.restartTimer = setTimeout(() => this.restart('worker failed: ' + String(error))
        .catch(e => this.ctx.logger.warn(String(e))), 1000);
      this.restartTimer.unref();
    }
  }

  /** Every in-place restart says why: in the status (lifecycle.history) and in a durable log beside the worker's
   * data, since the Host's own log is not kept. */
  async restart(reason = 'unspecified') {
    if (this.restarting) return this.restarting;
    const entry = { at: new Date().toISOString(), reason: String(reason).slice(0, 500) };
    this.lifecycle.history = [...(this.lifecycle.history ?? []), entry].slice(-10);
    this.ctx.logger.warn('Asuna worker restart: ' + entry.reason);
    await appendFile(path.join(this.ctx.asunaFloor.dataRoot, 'worker-restarts.jsonl'), JSON.stringify(entry) + '\n')
      .catch(error => this.ctx.logger.warn('Asuna: restart not logged: ' + String(error)));
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
    if (this.restartAgain) { this.restartAgain = false; await this.restart('a restart requested during the last one'); }
  }

  /** The tools a stage exposes: her turn's (role_tools.exposed) or the action task's grant. */
  exposed(lane, sessionId) {
    const state = this.state(sessionId);
    return lane === 'executor' ? state.allowed : lane === 'character' ? new Set(state.current?.tools ?? []) : new Set();
  }

  attachPreset(scope, lane) {
    // DSH 0.2 mounts a standing preset once and routes each member Agent's
    // events through it. Keep registrations here and state on session IDs.
    if (lane === 'character') scope.tools.restrict({ allow: [] });
    scope.tools.guard(exec => {
      const exposed = this.exposed(lane, exec.agent.session.id) ?? new Set();
      if (exposed.has(exec.name)) return undefined;
      const usable = [...exposed].join('、') || '（没有）';
      return lane === 'character' ? `这回合没有 ${exec.name} 这个工具；能用的是：${usable}。用其中一个，或者不用工具接着说。`
        : `CAPABILITY_DENIED: 这个任务没有 ${exec.name} 这个工具；能用的是：${usable}。要用它，在报告里写明，让她另交一件授予它的任务。`;
    });
    scope.on('tools/pre-execute', async (exec, next) => {
      exec.signal.throwIfAborted();
      await toolReply(() => this.worker.call('session', { session_id: exec.agent.session.id }));
      if (lane === 'executor') {
        const stage = this.state(exec.agent.session.id).current;
        const admission = await toolReply(() => this.worker.call('stage.valid', {
          token: stage?.token, session_id: exec.agent.session.id,
        }));
        if (admission.valid !== true) throw new Error('ASUNA_ACTION_STAGE_SUPPRESSED: 这一步所属的任务已经结束、被取消或被接替，'
          + '这次调用没有执行——不是参数的问题；重试也一样：别再调用工具，直接结束这一步');
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
    // Every other lane is her too (or her internal machinery): none carries the harness identity or the
    // host's runtime snapshot (checkout path, Web GUI); deployment details stay in diagnostics (AGENTS.md).
    scope.systemPrompt.suppressRuntimeContext();
    scope.systemPrompt.section({ name: 'harness:identity',
      order: scope.systemPrompt.getSectionOrder('HARNESS_IDENTITY'), text: '' });
    // Steer into her running turn waits as the next turn instead of failing it (steer.js).
    if (lane === 'character') scope.on('agent/inbox/inserted', ({ agent, message }) => {
      if (agent) queueMicrotask(() => holdSteeredInput(agent, message, Boolean(this.state(agent.session.id).current)));
    });
    // A platform line that waited for the conversation's first turn (navigation.js) is history, not local input.
    scope.on('agent/inbox/claimed', ({ agent, message }) => {
      if (message.source.kind === 'user' && !message.source.channel) this.state(agent.session.id).claimed.push(message);
      // Her message reached the running action session at a step: no extra round for it (tasks.py).
      if (lane === 'executor' && message.source.kind === 'asuna' && message.source.message_id)
        this.worker?.call('action_message.delivered', { message_id: message.source.message_id }).catch(() => {});
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
        // DSH's attachment store when the host provides one (read without making it a requirement of the role).
        const attachments = scope.reflect.get('attachments');
        const images = attachments ? await imagesOf(attachments, humans, signal) : [];
        const waiting = this.next(agent.session.id, signal);
        // Observe both failures immediately; the signal also releases waiting.
        const [, stage] = await Promise.all([
          this.worker.call('input', { session_id: agent.session.id, cwd: agent.session.header.cwd,
            message_ids: humans.map(x => x.id), text: humans.map(textOf).join('\n'),
            ...(images.length ? { images } : {}) }), waiting,
        ]);
        if (stage.error) throw new Error(stage.error);
        // A group turn's pictures (role_tools.turn_pictures) become image parts of her turn's message.
        if (stage.pictures?.length && attachments) stage.pictureParts = await pictureParts(attachments, stage.pictures);
        state.admitted = stage;
        if (stage.kind === 'stage') { state.current = stage; state.system = stage.system; }
      }
      const assembly = await next();
      const exposed = this.exposed(lane, agent.session.id);
      return { ...assembly,
        tools: assembly.tools.filter(tool => exposed?.has(tool.name)),
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
      const events = agent.session.snapshotEvents();
      const last = events.filter(event => event.type === 'assistant/message' && event.data.turn === turn).at(-1);
      if (!last || last.data.interrupted) throw new Error('Native stage has no complete assistant output');
      const finishReason = state.finish === 'max-tokens' ? 'length' : 'stop';
      const view = lane === 'character' ? stageView(events, stage.token, turn) : {};
      agent.session.append('asuna/stage-result', { operation: stage.token,
        turn, step: last.data.step, lane: stage.lane, phase: stage.phase,
        assistant_seq: last.seq, finish_reason: finishReason });
      await this.ctx.sessions.flush(agent.session);
      // Her turn may continue with the program's note (a failed end-of-turn check): wait for the
      // worker's next stage, or its word that the episode finished.
      const waiting = lane === 'character' ? this.next(agent.session.id, signal) : null;
      state.current = null;
      await this.worker.call('result', { token: stage.token,
        result: { ...this.result(stage, agent.id, last, finishReason), ...view } });
      if (waiting) {
        const nextStage = await waiting;
        if (nextStage.error) throw new Error(nextStage.error);
        if (nextStage.kind === 'stage') {
          state.current = nextStage; state.system = nextStage.system; agent.steer(this.message(nextStage, agent.session));
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
      // The thread's entries that arrived during her turn are appended once she is idle (collab.js).
      if (lane === 'character' && status === 'idle')
        this.collab.flush(agent.session.id).catch(error => this.ctx.logger.warn(String(error)));
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

  /** Her mind's tools in a role session (ADR-011 §5.1); each turn exposes some of them (exposed()). */
  async attachRole(agent) {
    const scope = agent.ctx;
    await this.ready();
    for (const spec of this.roleSpecs ?? []) {
      scope.tools.register(defineTool({ ...spec,
        output: { schema: { type: 'json' }, render: asunaRender },
        execute: async (args, exec) => {
          exec.signal.throwIfAborted();
          const operation = this.state(agent.session.id).current?.token;
          const reply = await toolReply(() => this.worker.call('role_tool', {
            session_id: agent.session.id, operation, call_id: exec.callId, tool: spec.name, args }));
          // A refusal is hers to correct in this turn: the tool error says what to do instead.
          if (reply.refused) throw new Error(reply.refused);
          if (reply.conclude) exec.concludeTurn();
          // read_image is the action brain's tool, shared: its bytes become an attachment she sees this turn.
          return attachImage({ attachments: scope.reflect.get('attachments') }, reply.value);
        },
      }));
    }
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
    // web_fetch is DSH's; web_search is DSH's tool with a `detail` choice and 10 sources (search.js, ADR-026).
    if (allowed.has('web_fetch')) await scope.plugin(webTool, { search: false, fetch: true });
    if (allowed.has('web_search')) registerWebSearch(scope, { fetchEnabled: allowed.has('web_fetch'),
      zone: { timezone: binding.timezone ?? null, utc_offset_minutes: binding.utc_offset_minutes } });
    if (allowed.has('skill') && binding.skill_directories?.length) {
      const skills = scope.isolate('skills');
      await skills.plugin(SkillService, {});
      await skills.plugin(skillFilesystem, { includeDefaultRoots: false,
        customSkillDirs: binding.skill_directories, watchFollowSymlinks: false });
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
          return attachImage({ attachments }, await toolReply(() => this.worker.call('tool', {
            session_id: agent.session.id, operation, call_id: exec.callId, tool: spec.name, args,
          })));
        },
      }));
    }
  }

  async dispose() {
    this.disposed = true;
    this.releaseProbe?.();
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
    await core.restart('recovery activated ' + value.project);
    return (await ctx.asunaFloor.selected()).projects[value.project];
  };
  ctx.asunaFloor.activateRecovery = activateRecovery;
  new AsunaApi(ctx, core);
  // Her web_search tries the configured backends in order (ADR-026); the profile pins this provider on ctx.web.
  applySearch(ctx, core);
  // web_fetch reads whole pages and drops what is not content before DSH converts them (ADR-026 §6).
  applyFetch(ctx);
  // ADR-012 §8: /heartbeat gives her one heartbeat now, through DSH's own command surface (no model message),
  // and says when the next scheduled one is due. Her rhythm stays program-owned; this only knocks early.
  ctx.inject(['commands'], child => child.effect(() => child.commands.register({
    name: 'heartbeat',
    description: 'Give her one heartbeat now (her own moment at home); shows when the next one is due',
    handler: async ({ rawInput }) => {
      if (String(rawInput ?? '').trim()) return { kind: 'error', text: 'Usage: /heartbeat (no arguments)' };
      if (core.lifecycle.state !== 'ready') return { kind: 'error', text: 'Asuna is not ready yet: ' + core.lifecycle.state };
      const result = await core.worker.call('heartbeat_now', {});
      const next = result.next_at ? new Date(result.next_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : null;
      if (result.state === 'ENQUEUED')
        return { kind: 'success', text: 'Heartbeat given: her inner time starts at home as soon as she is free.'
          + (next ? ' Next scheduled beat: ' + next + '.' : '') };
      if (result.state === 'OFF' || result.state === 'NO_SCHEDULE')
        return { kind: 'error', text: 'Her heartbeat is off (no heartbeat_target, or heartbeat.enabled is false).' };
      return { kind: 'error', text: 'The heartbeat was not given: ' + result.state };
    },
  })));
  ctx.inject(['settings'], child => child.effect(() => {
    const settings = child.settings;
    core.settings = settings;
    const release = settings.configure({ auto: false }, ctx.fiber);
    return () => { if (core.settings === settings) core.settings = null; return release(); };
  }));
  // A picture the model refuses becomes DSH's offload placeholder in that conversation, and the request is tried
  // once more, instead of ending her turn and every later one there (image-refusal.js).
  ctx.on('agent/request-error', imageRefusalListener(text => ctx.logger.warn('Asuna: ' + text)));
  ctx.on('dispose', () => {
    if (ctx.asunaFloor.activateRecovery === activateRecovery) delete ctx.asunaFloor.activateRecovery;
    return core.dispose();
  });
}
