/** Genuine task delegation through the shipped DSH subagent runtime. */
import { nativeRoute } from './settings.js';

export class NativeChildren {
  constructor(core) { this.core = core; this.pending = new WeakMap(); this.runs = new Set(); }

  async start(stage) {
    const core = this.core, { ctx } = core;
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
    // A crash may leave an already-catalogued one-shot run unfinished. Resume
    // that owned run without declaring a second child in the parent's catalog.
    const catalogued = parent.session.snapshotEvents().some(event => event.type === 'subagent/catalog'
      && event.data.childId === stage.session_id);
    const run = descriptor && catalogued ? await this.create(stage, { ...request, descriptor })
      : await ctx.subagents.start('asuna-worker', request);
    this.pending.delete(prompt);
    this.runs.add(run);
    await ctx.sessions.flush(parent.session);
    // The business worker consumes stage results. Native DSH owns discovery,
    // status, cancellation, and this child handle's lifetime.
    run.result.finally(async () => { await run.dispose(); this.runs.delete(run); })
      .catch(error => ctx.logger.warn(String(error)));
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
    agent.followup(core.message(stage));
    const result = agent.whenIdle().then(() => {
      const events = agent.session.snapshotEvents();
      const end = events.findLast(event => event.type === 'turn/end');
      const last = events.findLast(event => event.type === 'assistant/message');
      return { output: last?.data.message.content ?? [], stopReason:
        end?.data.reason.kind === 'completed' ? 'completed' : end?.data.reason.kind === 'aborted' ? 'aborted' : 'error' };
    });
    return { id: agent.id, localAgent: agent, result, dispose: async () => {
      request.signal.removeEventListener('abort', cancel);
      await handle.dispose(); core.handles.delete(agent.id);
    } };
  }

  async dispose() { await Promise.all([...this.runs].map(run => run.dispose())); this.runs.clear(); }
}
