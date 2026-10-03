/** Genuine task delegation through the shipped DSH subagent runtime. */
import { nativeRoute } from './settings.js';

export class NativeChildren {
  constructor(core) {
    this.core = core; this.pending = new WeakMap(); this.runs = new Set();
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
        await core.actionRecords.link(stage, { completed: true });
        await core.worker.call('result', { token: stage.token,
          result: core.result(stage, stage.session_id, actual, receipt.data.finish_reason) });
        return;
      }
    }
    if (!this.registered) {
      this.registered = ctx.subagents.registerProvider({ name: 'asuna-worker', inheritsParentContext: false,
        capabilities: { agentOptions: true, outputSchema: false, depthLimit: false, toolFilter: false, persona: false },
        start: request => this.create(this.pending.get(request.prompt), request) });
    }
    const binding = await core.worker.call('session', { session_id: stage.binding.parent_session_id });
    const parent = await core.ensureAgent({ session_id: binding._id, lane: 'character', binding });
    const prompt = [{ type: 'text', text: stage.text }];
    this.pending.set(prompt, stage);
    const request = { parent, prompt,
      label: stage.lane === 'executor' ? '行动脑 · ' + stage.binding.task_id : '交流摘要 · ' + stage.binding.scene_id,
      signal: new AbortController().signal, agentOptions: nativeRoute(core.config.routes.action) };
    const descriptor = stored.find(event => event.type === 'subagent/descriptor')?.data;
    // Resume the owned native source for a crash recovery or a successor task
    // on this execution binding. Its first descriptor and catalog remain intact.
    // Each foreground business run owns/disposes its handle; generic native
    // human continuation is deliberately unavailable on this action preset.
    const catalogued = parent.session.snapshotEvents().some(event => event.type === 'subagent/catalog'
      && event.data.childId === stage.session_id);
    const run = descriptor && catalogued ? await this.create(stage, { ...request, descriptor })
      : await ctx.subagents.start('asuna-worker', request);
    this.pending.delete(prompt);
    this.runs.add(run);
    // The business worker consumes stage results. Complete native teardown
    // before another business operation acquires this same source session.
    try { await ctx.sessions.flush(parent.session); await run.result; }
    finally { await run.dispose(); this.runs.delete(run); }
  }

  async create(stage, request) {
    if (!stage) throw new Error('ASUNA_DELEGATION_NOT_PREPARED');
    const core = this.core;
    request.signal.throwIfAborted();
    const agent = await core.ensureAgent(stage, request.parent, request.descriptor);
    const handle = core.handles.get(agent.id);
    const cancel = () => agent.cancel({ kind: 'user' });
    request.signal.addEventListener('abort', cancel, { once: true });
    const state = core.state(agent.id);
    state.current = stage; state.system = stage.system;
    await core.linkAction(stage);
    agent.followup(core.message(stage));
    const result = agent.whenIdle().then(() => {
      const events = agent.session.snapshotEvents();
      const end = events.findLast(event => event.type === 'turn/end');
      const last = events.findLast(event => event.type === 'assistant/message');
      return { output: last?.data.message.content ?? [], stopReason:
        end?.data.reason.kind === 'completed' ? 'completed' : end?.data.reason.kind === 'aborted' ? 'aborted' : 'error' };
    });
    // Freeze the visible range only after the native Turn end is durable.
    const settled = result.then(async value => { await core.actionRecords.finish(stage); return value; });
    let disposed = false;
    return { id: agent.id, localAgent: agent, result: settled, dispose: async () => {
      if (disposed) return; disposed = true;
      request.signal.removeEventListener('abort', cancel);
      await handle.dispose(); core.handles.delete(agent.id);
    } };
  }

  async dispose() {
    this.closed = true;
    await Promise.all([...this.runs].map(run => run.dispose())); this.runs.clear();
    await Promise.allSettled(this.admissions.values());
  }
}
