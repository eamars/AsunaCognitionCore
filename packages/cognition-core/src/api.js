import { TypertRemoteService, Remote } from '@deepseek-ai/dsh-typert-protocol';

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
      id: provider.id, models: (await core.ctx.llm.listModels(provider.id)).map(model => ({
        id: model.id, contextWindow: model.context?.contextWindow, maxTokens: model.context?.defaultMaxTokens,
        inputModalities: model.inputModalities,
      })),
    })));
    // Only configuration references and capability metadata cross this boundary.
    return JSON.parse(JSON.stringify({ lifecycle: core.lifecycle, worker, providers,
      personas: [...core.personas.values()].map(p => ({ id: p.id, name: p.display_name, version: p.version })),
      applied: core.config, pending: JSON.stringify(core.config) !== JSON.stringify(core.savedConfig()),
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
        category: request.category, offset: request.offset }),
    });
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
    const core = this.core, next = core.savedConfig();
    const status = core.lifecycle.state === 'ready' ? await core.worker.call('status') : null;
    if (status?.active_role || status?.active_task || status?.queued_inputs || status?.queued_tasks)
      throw new Error('ASUNA_BUSY: wait for the current role and action to finish');
    if (!core.personas.has(next.persona)) throw new Error('PERSONA_NOT_INSTALLED');
    for (const lane of ['character', 'action']) {
      const route = next.routes[lane];
      if (!(await core.ctx.llm.listModels(route.provider)).some(model => model.id === route.model))
        throw new Error('MODEL_NOT_IN_NATIVE_CATALOG: ' + lane);
    }
    await core.resolveRoutes(next.routes);
    core.config = next;
    await core.restart();
    return this.status();
  }
}

// Standard Remote decorators, applied without requiring a TS build at install.
// The native Gateway's source mode owns discovery, auth, request scope and RPC.
for (const name of ['status', 'memory', 'applySettings', 'personaSources', 'personaJob', 'personaExport']) {
  Remote(AsunaApi.prototype[name], { name, kind: 'method', static: false, private: false,
    addInitializer: initialize => initializers.push(initialize) });
}
