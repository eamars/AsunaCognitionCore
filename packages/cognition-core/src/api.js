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
for (const name of ['status', 'memory', 'inputPolicies', 'applySettings', 'saveSettings']) {
  Remote(AsunaApi.prototype[name], { name, kind: 'method', static: false, private: false,
    addInitializer: initialize => initializers.push(initialize) });
}
