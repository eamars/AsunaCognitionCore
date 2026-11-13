/** The `asunaApi` remote service the Web page calls: worker and model status, the settings card's save and apply,
 * her memory pages, brain context views, session kinds and titles, and persona jobs.
 *
 * DSH's Gateway carries each call; a method reads the plugin core (index.js) or asks the worker. client.js calls it. */
import { TypertRemoteService, Remote } from '@deepseek-ai/dsh-typert-protocol';
import { editSettings } from './settings.js';
import { workspaceTitle } from './navigation.js';
import { applyLanguage } from './ui-language.js';

const initializers = [];

/** A session's events, live or persisted (collab.js reads an action session the same way). */
export async function sessionEvents(ctx, sessionId) {
  const live = ctx.agents?.get(sessionId)?.session.snapshotEvents();
  if (live) return live;
  if (!await ctx.sessionPersistence.stat(sessionId)) return [];
  const handle = await ctx.sessionPersistence.open(sessionId, 'read');
  try { return (await handle.read()).events; } finally { await handle.close(); }
}

/** Whether these events hold her speak call `callId` made in a step of the stage `operation` (its `asuna/stage` mark,
 * index.js), with a result in the same Turn that is not an error: the page asks only about a call of this session
 * (ADR-129 D5(b)). A call id may come back in another Turn (some providers number calls per request): each call with
 * it is tried, never only the first. */
export function speakCallIn(events, callId, operation) {
  return events.some(call => call.type === 'tool/call' && call.data?.callId === callId
    && ['speak', 'reply'].includes(call.data.name)
    && events.some(event => event.type === 'asuna/stage' && event.seq < call.seq && event.data?.operation === operation
      && event.data.turn === call.data.turn && event.data.step === call.data.step)
    && [events.find(event => event.type === 'tool/result' && event.seq > call.seq && event.data?.turn === call.data.turn
      && event.data.message?.toolCallId === callId)].some(result => result && result.data.message.isError !== true));
}

export class AsunaApi extends TypertRemoteService {
  constructor(ctx, core) {
    super(ctx, 'asunaApi'); this.core = core;
    for (const initialize of initializers) initialize.call(this);
  }

  async status() {
    const core = this.core;
    let worker = null;
    if (core.lifecycle.state === 'ready') worker = await core.worker.call('status');
    const providers = await Promise.all(core.ctx.llm.listProviders().map(async provider => ({
      id: provider.id, name: provider.name,
      models: await Promise.all((await core.ctx.llm.listModels(provider.id)).map(async entry => {
        const model = await core.ctx.llm.resolveModelInfo(provider.id, entry.id);
        return { id: model.id, name: model.name, contextWindow: model.context?.contextWindow,
          maxTokens: model.defaultMaxTokens, inputModalities: model.inputModalities, reasoning: model.reasoning };
      })),
    })));
    // Only configuration references and capability metadata cross this boundary.
    return JSON.parse(JSON.stringify({ lifecycle: core.lifecycle, worker, providers,
      personas: [...core.personas.values()].map(p => ({ id: p.id, name: p.display_name, version: p.version })),
      applied: core.publicConfig(), pending: JSON.stringify(core.config) !== JSON.stringify(core.savedConfig()),
      actionHigh: core.tierStatus(),
      // ADR-098: the root table (its size, or why there is none) and her rewritten requests since this start.
      roots: (({ by_session: _, ...totals }) => totals)(core.roots.status()),
      publications: Object.values((await core.ctx.asunaFloor.selected()).projects).map(p => ({
        project: p.project, state: p.state, candidate: p.candidate, changed_files: p.changed_files,
        activated_at: p.activated_at, published_at: p.published_at,
      })) }));
  }

  async memory(request) {
    if (!request || typeof request.session_id !== 'string') throw new Error('NATIVE_SESSION_REQUIRED');
    await this.core.ready();
    return this.core.worker.call(request.id ? 'memory.detail' : 'memory.page', {
      session_id: request.session_id, ...(request.id ? { id: request.id } : {
        category: request.category, offset: request.offset, search: request.search }),
    });
  }

  async inputPolicies(sessionIds) {
    if (!Array.isArray(sessionIds) || sessionIds.length > 500 || sessionIds.some(id => typeof id !== 'string'))
      throw new Error('INVALID_SESSION_IDS');
    await this.core.ready();
    const sessions = await Promise.all(sessionIds.map(async id => {
      const header = this.core.ctx.sessions.get(id)?.header
        ?? (await this.core.ctx.sessionPersistence.stat(id))?.header;
      return { id, cwd: header?.cwd, preset: header?.agentPreset };
    }));
    const policies = await this.core.worker.call('input_policies', { sessions: sessions.map(({ id, cwd }) => ({ id, cwd })) });
    // The schedule session only delivers her plans and alarms; nothing written there reaches her.
    for (const session of sessions) if (session.preset === 'asuna-scheduler') policies[session.id] = { key: 'schedules' };
    return policies;
  }

  /** For a character session: the context projections of its latest action session, exactly as DSH's
   * own meter reads them (contextPressure, contextBreakdown). Null for any other session. */
  async brainContext(sessionId) {
    if (typeof sessionId !== 'string' || !sessionId) throw new Error('INVALID_SESSION_ID');
    await this.core.ready();
    const binding = await this.core.worker.call('session', { session_id: sessionId }).catch(() => null);
    if (binding?.lane !== 'character') return null;
    const role = this.core.ctx.sessions.get(sessionId);
    // The newest action session of her collaboration threads (collab.js).
    const action = role?.snapshotEvents().findLast(event => event.type === 'asuna/collab' && event.data.child_session_id)
      ?.data.child_session_id;
    return { action: action ? await this.contextProjections(action) : null };
  }

  async contextProjections(id) {
    const { ctx } = this.core, keys = ['contextPressure', 'contextBreakdown'];
    const hot = ctx.sessions.get(id);
    if (hot) return ctx.sessionProjections.snapshot(hot, keys).values;
    const header = (await ctx.sessionPersistence.stat(id))?.header;
    return (header && ctx.sessionProjectionCache.cachedSnapshot(header, keys)?.values) ?? null;
  }

  /** Her platform conversations among these sessions, 'group' or 'dm' (the sidebar mark in client.js). */
  async sessionKinds(sessionIds) {
    if (!Array.isArray(sessionIds) || sessionIds.length > 500 || sessionIds.some(id => typeof id !== 'string'))
      throw new Error('INVALID_SESSION_IDS');
    await this.core.ready();
    return this.core.worker.call('session_kinds', { session_ids: sessionIds });
  }

  /** The browser's language for the names the program gives (ui-language.js); unsupported means English. */
  async uiLanguage(locale) {
    if (typeof locale !== 'string' || locale.length > 35) throw new Error('INVALID_LOCALE');
    return applyLanguage(this.core, locale);
  }

  /** Workspace titles in the viewer's language: DSH stores them as plain text, so the client says which
   * words it shows (client.js). Only workspaces navigation created can be titled. */
  async workspaceTitles(titles) {
    if (!titles || typeof titles !== 'object' || Array.isArray(titles)) throw new Error('INVALID_TITLES');
    await this.core.ready();
    const titled = [];
    for (const [key, title] of Object.entries(titles)) {
      if (typeof title !== 'string' || !title.trim() || title.length > 40) throw new Error('INVALID_TITLE');
      const workspace = this.core.navigationWorkspaces?.get(key);
      if (!workspace) continue;
      this.core.workspaceTitles = { ...this.core.workspaceTitles, [key]: title.trim() };
      await workspace.setTitle(workspaceTitle(this.core, key)); titled.push(key);
    }
    return { titled };
  }

  /** The presets her two brains run in: her persona's and the action brain's. DSH's permission presets set
   * its own shell sandbox and approvals, which neither uses (her character has no DSH tools; the action
   * brain's run in Asuna's sandbox under her grants), so the client does not show that picker there. */
  async brainPresets() {
    return [...new Set([...this.core.personas.values()].map(persona => persona.preset)
      .filter(preset => typeof preset === 'string' && preset)), 'asuna-action'];
  }

  /** ADR-129 D5(b): what one speak call of hers sent, for its node on the page: the parts as they left. */
  async speakParts(request) {
    const call = await this.speakCall(request);
    return this.core.worker.call('speak.parts', call);
  }

  /** ADR-129 D5(b): one part's picture of that call (base64), one part per request. */
  async speakPicture(request) {
    if (!Number.isInteger(request?.index) || request.index < 0) throw new Error('INVALID_PART');
    const call = await this.speakCall(request);
    return this.core.worker.call('speak.picture', { ...call, index: request.index });
  }

  /** The fence of both: a character session's own speak call, found with its result in that session's events. */
  async speakCall(request) {
    const { session_id: sessionId, operation, call_id: callId } = request ?? {};
    if ([sessionId, operation, callId].some(value => typeof value !== 'string' || !value)) throw new Error('INVALID_SPEAK_CALL');
    await this.core.ready();
    const binding = await this.core.worker.call('session', { session_id: sessionId }).catch(() => null);
    if (binding?.lane !== 'character') throw new Error('ROLE_SESSION_REQUIRED');
    if (!speakCallIn(await sessionEvents(this.core.ctx, sessionId), callId, operation)) throw new Error('SPEAK_CALL_NOT_FOUND');
    return { session_id: sessionId, operation, call_id: callId };
  }

  async personaSources() {
    await this.core.ready();
    return this.core.worker.call('persona.sources', {});
  }

  /** Owner operations from the settings card: dry-run / run a persona job, export documents. */
  async personaJob(request) {
    if (!request || typeof request.job !== 'string') throw new Error('PERSONA_JOB_REQUIRED');
    await this.core.ready();
    return this.core.worker.call('persona.job_run', { job: request.job, dry_run: request.dry_run !== false, args: {} });
  }

  async personaExport() {
    await this.core.ready();
    return this.core.worker.call('persona.export', {});
  }

  async applySettings() {
    await this.core.applySettings(this.core.savedConfig());
    return this.status();
  }

  async saveSettings(ops, revision) {
    const { core } = this, settings = core.settings;
    if (!settings) throw new Error('NATIVE_SETTINGS_UNAVAILABLE');
    const descriptor = settings.describe().find(row => row.ns === 'asuna-cognition-core');
    if (!descriptor || !Number.isInteger(revision) || descriptor.revision !== revision)
      throw new Error('SETTINGS_CONFLICT: settings changed since this draft was started');
    const next = editSettings(core.savedConfig(), ops, descriptor.base);
    await core.validateSettings(next);
    // DSH rechecks the revision inside its serialized durable write.
    await settings.mutate('asuna-cognition-core', ops, revision);
    return { saved: true };
  }
}

// Standard Remote decorators, applied without requiring a TS build at install.
// The native Gateway's source mode owns discovery, auth, request scope and RPC.
for (const name of ['status', 'memory', 'inputPolicies', 'brainContext', 'brainPresets', 'sessionKinds', 'workspaceTitles', 'uiLanguage', 'applySettings', 'saveSettings', 'personaSources', 'personaJob', 'personaExport', 'speakParts', 'speakPicture']) {
  Remote(AsunaApi.prototype[name], { name, kind: 'method', static: false, private: false,
    addInitializer: initialize => initializers.push(initialize) });
}
