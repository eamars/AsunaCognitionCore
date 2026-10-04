import { TypertRemoteService, Remote } from '@deepseek-ai/dsh-typert-protocol';
import { editSettings } from './settings.js';

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
      credentials: Object.keys(core.savedConfig().secrets ?? {}),
      publications: Object.values((await core.ctx.asunaFloor.selected()).projects).map(p => ({
        project: p.project, state: p.state, candidate: p.candidate, changed_files: p.changed_files,
        activated_at: p.activated_at,
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
      return { id, cwd: header?.cwd };
    }));
    return this.core.worker.call('input_policies', { sessions });
  }

  /** Context occupancy of a character session and of its latest action session (DSH contextPressure). */
  async brainContext(sessionId) {
    if (typeof sessionId !== 'string' || !sessionId) throw new Error('INVALID_SESSION_ID');
    await this.core.ready();
    const binding = await this.core.worker.call('session', { session_id: sessionId }).catch(() => null);
    if (binding?.lane !== 'character') return null;
    const role = this.core.ctx.sessions.get(sessionId);
    const action = role?.snapshotEvents().findLast(event => event.type === 'asuna/action-linked')?.data.session_id;
    return { character: await this.occupancy(sessionId), action: action ? await this.occupancy(action) : null };
  }

  async occupancy(id) {
    const { ctx } = this.core;
    const hot = ctx.sessions.get(id);
    let pressure;
    if (hot) pressure = ctx.sessionProjections.snapshot(hot, ['contextPressure']).values.contextPressure;
    else {
      const header = (await ctx.sessionPersistence.stat(id))?.header;
      pressure = header && ctx.sessionProjectionCache.cachedSnapshot(header, ['contextPressure'])?.values.contextPressure;
    }
    // The same reading DSH's own meter shows.
    const used = pressure?.projectedTokens ?? pressure?.pressureTokens;
    if (used === undefined || !pressure?.contextWindow) return null;
    return { used, window: pressure.contextWindow, percent: Math.min(100, Math.round(used / pressure.contextWindow * 100)) };
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
for (const name of ['status', 'memory', 'inputPolicies', 'brainContext', 'applySettings', 'saveSettings', 'personaSources', 'personaJob', 'personaExport']) {
  Remote(AsunaApi.prototype[name], { name, kind: 'method', static: false, private: false,
    addInitializer: initialize => initializers.push(initialize) });
}
