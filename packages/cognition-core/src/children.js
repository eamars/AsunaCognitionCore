/** Her action brain's children: tasks (catalogued DSH subagents) and the worker's own hidden stages. */

export class NativeChildren {
  constructor(core) {
    this.core = core; this.runs = new Set();
    this.admissions = new Map(); this.closed = false;
  }

  async start(stage) {
    // Worker results can announce a successor before the native Turn finishes
    // stopping. Admit it after that source handle is released, without making
    // the worker's result acknowledgement wait for its own Turn to become idle.
    const previous = this.admissions.get(stage.session_id) ?? Promise.resolve();
    const running = previous.then(() => {
      if (this.closed) throw new Error('ASUNA_DELEGATION_CLOSED');
      return this.open(stage);
    }).catch(async error => {
      this.core.ctx.logger.warn(String(error));
      await this.core.worker.call('result', { token: stage.token, error: String(error) }).catch(() => {});
    });
    const settled = running.finally(() => {
      if (this.admissions.get(stage.session_id) === settled) this.admissions.delete(stage.session_id);
    });
    this.admissions.set(stage.session_id, settled);
  }

  async open(stage) {
    const core = this.core, { ctx } = core;
    const admission = await core.worker.call('stage.valid', { token: stage.token });
    if (admission.valid !== true) throw new Error('ASUNA_ACTION_STAGE_SUPPRESSED');
    let stored = [];
    if (await ctx.sessionPersistence.stat(stage.session_id)) {
      const handle = await ctx.sessionPersistence.open(stage.session_id, 'read');
      try { stored = (await handle.read()).events; } finally { await handle.close(); }
      const receipt = stored.find(event => event.type === 'asuna/stage-result' && event.data.operation === stage.token);
      if (receipt) {
        const actual = stored.find(event => event.seq === receipt.data.assistant_seq
          && event.type === 'assistant/message' && !event.data.interrupted);
        if (!actual) throw new Error('Saved Asuna receipt has no native assistant event');
        await core.worker.call('result', { token: stage.token,
          result: core.result(stage, stage.session_id, actual, receipt.data.finish_reason) });
        return;
      }
    }
    const binding = await core.worker.call('session', { session_id: stage.binding.parent_session_id });
    const parent = await core.ensureAgent({ session_id: binding._id, lane: 'character', binding });
    const label = stage.title ?? stage.task?.title ?? stage.binding.task_id ?? stage.binding.scene_id;
    // Only a task is a delegation: a child that carries a subagent descriptor and enters its parent's catalog,
    // which DSH's subagent list and view read. A summary, attention gate or appraisal is the worker's own
    // machinery: a hidden child session (its header keeps it out of the sidebar) without a catalog entry, so the
    // conversation's subagent list shows her tasks only (ADR-011 §4). The worker owns the child either way; DSH's
    // subagent runtime composes its own children from the parent's preset, not her action brain.
    const descriptor = stored.find(event => event.type === 'subagent/descriptor')?.data ?? (stage.lane === 'executor'
      ? { version: 3, mode: 'one-shot', provider: 'asuna-worker', label } : undefined);
    const run = await this.create(stage, parent, descriptor);
    if (stage.lane === 'executor' && !parent.session.snapshotEvents().some(event => event.type === 'subagent/catalog'
      && event.data.childId === stage.session_id)) {
      parent.session.append('subagent/catalog', { version: 0, childId: stage.session_id, mode: 'one-shot', label,
        childCreatedAt: ctx.agents.get(stage.session_id).session.header.createdAt });
    }
    this.runs.add(run);
    // The business worker consumes stage results. Complete native teardown
    // before another business operation acquires this same source session.
    try { await ctx.sessions.flush(parent.session); await run.result; }
    finally { await run.dispose(); this.runs.delete(run); }
  }

  async create(stage, parent, descriptor) {
    const core = this.core;
    const agent = await core.ensureAgent(stage, parent, descriptor);
    const handle = core.handles.get(agent.id);
    const state = core.state(agent.id);
    state.current = stage; state.system = stage.system;
    await core.collab.start(stage);
    agent.followup(core.message(stage));
    // Freeze the visible range only after the native Turn end is durable.
    const result = agent.whenIdle().then(() => core.collab.finish(stage));
    let disposed = false;
    return { result, dispose: async () => {
      if (disposed) return; disposed = true;
      await handle.dispose(); core.handles.delete(agent.id);
    } };
  }

  async dispose() {
    this.closed = true;
    await Promise.all([...this.runs].map(run => run.dispose())); this.runs.clear();
    await Promise.allSettled(this.admissions.values());
  }
}
