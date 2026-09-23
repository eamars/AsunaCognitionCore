import { createServer } from 'node:http';
import { mkdirSync, existsSync, readFileSync, writeFileSync, renameSync, openSync, fsyncSync, closeSync } from 'node:fs';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import * as skillTool from '@deepseek-ai/dsh-tool-skill';
import * as scheduleTool from '@deepseek-ai/dsh-schedule';

// v1 remains frozen for already-running experiments. v2 adds only a validated
// completed-silent-episode boundary; Python still owns business state.
export const name = 'asuna-runtime-operations-v2';
export const inject = ['agents', 'sessions', 'sessionPersistence', 'systemPrompt', 'compaction', 'tokenMeter', 'skills', 'tools'];

// A runtime capability bridge, not a second business coordinator. SDK 0.1.5-rc.2
// exposes initialize/prompt/shutdown only; it cannot resume persisted sessions.
export function apply(ctx, config) {
  mkdirSync(config.receipts, { recursive: true });
  const handles = new Map();
  const prompts = new Map();
  const skillAccess = new Map();
  const active = new Map();
  let schedulerAgent;
  let queue = Promise.resolve();
  const hash = value => createHash('sha256').update(value).digest('hex');
  function save(path, data) {
    const tmp = path + '.tmp';
    writeFileSync(tmp, JSON.stringify(data));
    const fd = openSync(tmp, 'r+'); fsyncSync(fd); closeSync(fd);
    renameSync(tmp, path);
  }
  ctx.on('agent/pre-step', async ({ agent, signal }, next) => {
    if (config.schedulerSession && agent.session.id === config.schedulerSession) {
      const decision = await next();
      if (decision.kind === 'enter' && decision.messages.some(message =>
        message.source?.kind === 'plugin' && message.source.plugin === 'schedule')) {
        // The installed schedule plugin has already appended its dispatch to
        // this native session. Make that record durable before notifying the
        // host, then consume the followup without a model request.
        if (!await ctx.sessions.flush(agent.session)) throw new Error('SCHEDULE_DISPATCH_NOT_DURABLE');
        for (const event of agent.session.snapshotEvents().filter(e => e.type === 'schedule/change' && e.data.operation === 'dispatch')) {
          const response = await fetch(config.schedulerCallbackUrl, {
            method: 'POST', headers: { Authorization: 'Bearer ' + config.schedulerCallbackToken,
              'Content-Type': 'application/json' },
            body: JSON.stringify({ session: agent.session.id, seq: event.seq, id: event.data.id }) });
          if (!response.ok) throw new Error('SCHEDULE_HOST_DELIVERY: ' + response.status + ' ' + await response.text());
        }
      }
      // This root owns the native clock and log; role cognition enters through
      // the host queue after a verified dispatch, never through this agent.
      return { kind: 'reject' };
    }
    const operation = active.get(agent.session.id);
    // Native continuations keep their authorized session; an operation is
    // receipt bookkeeping, not permission for each native generation step.
    if (!operation) return next();
    ++operation.steps;
    if ((operation.compact && !operation.compacted) || operation.compactAt.includes(operation.steps)) {
      operation.compacted = true;
      const nodes = agent.session.surface.nodes;
      const first = nodes.find(seq => agent.session.eventAt(seq)?.type !== 'system/message');
      const last = nodes.at(-1);
      if (first === undefined || first === last) throw new Error('NO_COMPLETE_COMPACTION_SPAN');
      // At the first pre-step, the newly admitted user message has not yet
      // entered the surface. The prior operation ended at a full episode/task
      // boundary validated below; compact the entire closed history, not a
      // token-sliced tail ending between MONOLOGUE and SPEAK.
      const result = await ctx.compaction.compactRegion(first, last, agent, signal);
      if (!await ctx.sessions.flush(agent.session)) throw new Error('COMPACTION_NOT_DURABLE');
      operation.compactionResult = result;
      operation.compactions.push(result);
    }
    return next();
  });
  async function handleSession(id, system, skillsEnabled = false) {
    if (!/^[a-z0-9-]{1,100}$/.test(id)) throw new Error('INVALID_SESSION_ID');
    if (typeof system !== 'string' || system.trim().length < 80) throw new Error('MISSING_SYSTEM');
    prompts.set(id, system);
    if (skillAccess.has(id) && skillAccess.get(id) !== skillsEnabled) throw new Error('SESSION_SKILL_ACCESS_CHANGED');
    skillAccess.set(id, skillsEnabled);
    if (handles.has(id)) return handles.get(id).agent;
    const setup = async (agentCtx) => {
      // Native loader/catalog are scoped to this authorized action agent.
      if (skillsEnabled) await agentCtx.plugin(skillTool, {});
      if (config.schedulerSession && id === config.schedulerSession) await agentCtx.plugin(scheduleTool, {});
      agentCtx.systemPrompt.section({ name: 'asuna-complete', order: 0, complete: true,
        interpolate: false, text: () => prompts.get(id) });
      agentCtx.systemPrompt.suppressRuntimeContext();
    };
    const options = { provider: 'asuna-local', model: config.model,
      reasoningEffort: config.reasoningEffort ?? 'off', maxTokens: config.maxTokens };
    const persisted = await ctx.sessionPersistence.stat(id);
    const handle = persisted
      ? await ctx.agents.resume({ resumeSessionId: id, agentOptions: options, setup })
      : await ctx.agents.create({ sessionId: id, meta: { cwd: config.workdir }, agentOptions: options, setup });
    handles.set(id, handle);
    return handle.agent;
  }
  const schedulerReady = config.schedulerSession
    ? handleSession(config.schedulerSession,
      'Asuna native schedule owner. This root only persists native reminders and dispatches them to the host. It never calls a language model or publishes a message.', false)
        .then(agent => { schedulerAgent = agent; return agent; })
    : null;
  async function scheduleOperation(path, input) {
    const agent = await schedulerReady;
    if (!agent) throw new Error('SCHEDULER_NOT_CONFIGURED');
    if (path === '/schedule/events') return agent.session.snapshotEvents()
      .filter(e => e.type === 'schedule/change').map(e => ({ seq: e.seq, data: e.data }));
    const name = path === '/schedule/create' ? 'schedule_create'
      : path === '/schedule/delete' ? 'schedule_delete' : null;
    if (!name) throw new Error('UNKNOWN_SCHEDULE_OPERATION');
    const args = path === '/schedule/create'
      ? { prompt: 'ASUNA_PLAN:' + input.plan_id,
          ...(input.after_seconds !== undefined ? { after_seconds: input.after_seconds } : {}),
          ...(input.every_seconds !== undefined ? { every_seconds: input.every_seconds } : {}) }
      : { id: input.id };
    const result = await ctx.tools.execute({ callId: 'asuna-' + name + '-' + randomUUID(),
      name, arguments: args, agent, signal: new AbortController().signal });
    if (result.isError) throw new Error('NATIVE_SCHEDULE_TOOL: ' + JSON.stringify(result.error));
    return result.value;
  }
  function resultFrom(events, messageId) {
    const start = events.findIndex(e => e.type === 'user/message' && e.data.id === messageId);
    if (start < 0) {
      // Pre-step compaction can fail after inbox acceptance but before the user
      // message enters the surface. Preserve that exact native error only;
      // inbox delivery alone must never manufacture a successful model result.
      const accepted = events.findIndex(e => e.type === 'agent/inbox/spliced' &&
        e.data.target === 'next-turn' && e.data.inserted?.length === 1 &&
        e.data.inserted[0].id === messageId);
      if (accepted < 0) return undefined;
      const suffix = events.slice(accepted);
      const turn = suffix.find(e => e.type === 'turn/start');
      if (!turn) return undefined;
      const end = suffix.find(e => e.seq > turn.seq && e.type === 'turn/end');
      if (!end || end.data.turn !== turn.data.turn || end.data.reason.kind !== 'error') return undefined;
      if (suffix.some(e => e.seq > turn.seq && e.seq < end.seq &&
        (e.type === 'turn/start' || e.type === 'user/message' || e.type === 'assistant/message'))) return undefined;
      return { content: '', reasoning: '', finish_reason: 'error',
        native_reason: end.data.reason, message_admitted_to_surface: false,
        events: suffix.filter(e => e.seq <= end.seq), message_id: messageId };
    }
    const suffix = events.slice(start);
    const end = suffix.find(e => e.type === 'turn/end');
    if (!end) return undefined;
    const messages = suffix.filter(e => e.type === 'assistant/message' && e.seq < end.seq);
    const last = messages.at(-1)?.data.message;
    return { content: (last?.content ?? []).filter(b => b.type === 'text').map(b => b.text).join(''),
      reasoning: (last?.content ?? []).filter(b => b.type === 'reasoning').map(b => b.text).join(''),
      finish_reason: end.data.reason.kind, native_reason: end.data.reason,
      message_admitted_to_surface: true, events: suffix.filter(e => e.seq <= end.seq), message_id: messageId };
  }
  async function run(input) {
    const path = join(config.receipts, hash(input.operation) + '.json');
    const semantic = [input.session, input.phase, input.text, input.system, !!input.compact_before, input.compact_at_steps ?? [], input.completed_episode_boundary ?? null];
    if (input.skills_enabled) semantic.push({ skills_enabled: true });
    const inputHash = hash(JSON.stringify(semantic));
    let record = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : undefined;
    if (record && record.inputHash !== inputHash) throw new Error('OPERATION_CONTENT_MISMATCH');
    if (record?.state === 'DONE') return record.result;
    const compactAt = input.compact_at_steps ?? [];
    if (!Array.isArray(compactAt) || compactAt.some(x => !Number.isInteger(x) || x < 2 || x > 64)) throw new Error('INVALID_COMPACTION_STEPS');
    if (compactAt.length && !input.phase.startsWith('execution')) throw new Error('MID_EPISODE_COMPACTION_FORBIDDEN');
    active.set(input.session, { steps: 0, compact: !!input.compact_before, compacted: false, compactAt, compactions: [] });
    if (input.skills_enabled && !config.skillsEnabled) throw new Error('SKILLS_NOT_CONFIGURED');
    const agent = await handleSession(input.session, input.system, !!input.skills_enabled);
    if (record) {
      await agent.whenIdle();
      const recovered = resultFrom(agent.session.snapshotEvents(), record.message.id);
      if (!recovered) throw new Error('UNKNOWN_DELIVERY_REQUIRES_RECONCILIATION');
      await ctx.sessions.flush(agent.session);
      save(path, { ...record, state: 'DONE', result: recovered });
      return recovered;
    }
    const message = createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: input.text }] });
    const boundaryPath = join(config.receipts, 'boundary-' + input.session + '.json');
    const boundary = existsSync(boundaryPath) ? JSON.parse(readFileSync(boundaryPath, 'utf8')) : undefined;
    let completedSilent = false;
    if (boundary?.phase === 'DECIDE' && input.completed_episode_boundary === boundary.operation && boundary.finish_reason === 'completed') {
      const priorPath = join(config.receipts, hash(boundary.operation) + '.json');
      const prior = existsSync(priorPath) ? JSON.parse(readFileSync(priorPath, 'utf8')) : undefined;
      try {
        completedSilent = prior?.state === 'DONE' && prior.session === input.session &&
          prior.result?.finish_reason === 'completed' && JSON.parse(prior.result.content).next === 'silent';
      } catch { completedSilent = false; }
    }
    if (input.compact_before && (!boundary || !(['SPEAK', 'execution', 'execution-repair'].includes(boundary.phase) || completedSilent))) throw new Error('COMPACTION_REQUIRES_COMPLETED_EPISODE_OR_TASK');
    record = { state: 'INTENT', inputHash, session: input.session, message };
    save(path, record);
    agent.followup(message);
    // followup is delivery, not a completion handle. This bridge serializes one
    // operation per lane and correlates the accepted user message to its turn.
    await agent.whenIdle();
    if (!await ctx.sessions.flush(agent.session)) throw new Error('NO_DURABLE_SESSION_LISTENER');
    const result = resultFrom(agent.session.snapshotEvents(), message.id);
    if (!result) throw new Error('NO_CAUSAL_TURN_RESULT');
    result.compaction = active.get(input.session)?.compactionResult;
    result.compactions = active.get(input.session)?.compactions ?? [];
    result.surface = [...agent.session.surface.nodes];
    result.compaction_events = agent.session.snapshotEvents().filter(e => e.type.startsWith('compaction/'));
    save(path, { ...record, state: 'DONE', result });
    save(boundaryPath, { phase: input.phase, operation: input.operation, finish_reason: result.finish_reason });
    return result;
  }
  const server = createServer(async (req, res) => {
    try {
      if (req.headers.authorization !== 'Bearer ' + process.env.ASUNA_BRIDGE_TOKEN) throw new Error('UNAUTHORIZED');
      if (req.method === 'GET' && req.url === '/skills') {
        const snapshot = config.skillsEnabled ? await ctx.skills.snapshot({ cwd: config.workdir }) : { skills: [], complete: true };
        const skills = snapshot.skills.filter(s => s.invocation.modelInvocable).map(s => ({ name: s.name, description: s.description.slice(0, 500) }));
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ skills, complete: snapshot.complete })); return;
      }
      if (config.schedulerSession && req.method === 'GET' && req.url === '/schedule/events') {
        const result = await scheduleOperation(req.url, {});
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(result)); return;
      }
      if (config.schedulerSession && req.method === 'POST' && ['/schedule/create','/schedule/delete'].includes(req.url)) {
        let body = ''; for await (const chunk of req) { body += chunk; if (body.length > 4096) throw new Error('INPUT_TOO_LARGE'); }
        const input = JSON.parse(body);
        if (req.url === '/schedule/create' && (!/^plan-[a-z0-9-]{1,100}$/.test(input.plan_id)
            || Number(input.after_seconds !== undefined) + Number(input.every_seconds !== undefined) !== 1)) throw new Error('INVALID_SCHEDULE_PLAN');
        if (req.url === '/schedule/delete' && typeof input.id !== 'string') throw new Error('INVALID_SCHEDULE_ID');
        const work = queue.then(() => scheduleOperation(req.url, input)); queue = work.catch(() => {});
        const result = await work;
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(result)); return;
      }
      if (req.method !== 'POST' || req.url !== '/run') throw new Error('UNKNOWN_OPERATION');
      let body = ''; for await (const chunk of req) { body += chunk; if (body.length > 2 * 1024 * 1024) throw new Error('INPUT_TOO_LARGE'); }
      const input = JSON.parse(body);
      const work = queue.then(() => run(input)); queue = work.catch(() => {});
      const result = await work;
      res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(result));
    } catch (error) {
      res.writeHead(409, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: String(error) }));
    }
  });
  server.listen(0, '127.0.0.1', () => save(config.endpointFile, { port: server.address().port }));
  ctx.on('dispose', async () => {
    server.close();
    await Promise.allSettled([...handles.values()].map(h => h.dispose()));
  });
}
