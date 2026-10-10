/** The `asunaApi` remote service the Web page calls: worker and model status, the settings card's save and apply,
 * her memory pages, brain context views, session kinds and titles, and persona jobs.
 *
 * DSH's Gateway carries each call; a method reads the plugin core (index.js) or asks the worker. client.js calls it. */
import { TypertRemoteService, Remote } from '@deepseek-ai/dsh-typert-protocol';
import { editSettings } from './settings.js';
import { workspaceTitle } from './navigation.js';
import { applyLanguage } from './ui-language.js';

const initializers = [];
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
for (const name of ['status', 'memory', 'inputPolicies', 'brainContext', 'brainPresets', 'sessionKinds', 'workspaceTitles', 'uiLanguage', 'applySettings', 'saveSettings', 'personaSources', 'personaJob', 'personaExport']) {
  Remote(AsunaApi.prototype[name], { name, kind: 'method', static: false, private: false,
    addInitializer: initialize => initializers.push(initialize) });
}
