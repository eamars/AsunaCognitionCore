import { createServer } from 'node:http';
import { mkdirSync, existsSync, readFileSync, writeFileSync, renameSync, openSync, fsyncSync, closeSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { createUserMessage } from '@deepseek-ai/dsh-llm';

export const name = 'asuna-runtime-operations';
export const inject = ['agents', 'sessions', 'sessionPersistence', 'systemPrompt'];

// A runtime capability bridge, not a second business coordinator. SDK 0.1.5-rc.2
// exposes initialize/prompt/shutdown only; it cannot resume persisted sessions.
export function apply(ctx, config) {
  mkdirSync(config.receipts, { recursive: true });
  const handles = new Map();
  const prompts = new Map();
  let queue = Promise.resolve();
  const hash = value => createHash('sha256').update(value).digest('hex');
  function save(path, data) {
    const tmp = path + '.tmp';
    writeFileSync(tmp, JSON.stringify(data));
    const fd = openSync(tmp, 'r+'); fsyncSync(fd); closeSync(fd);
    renameSync(tmp, path);
  }
  async function handleSession(id, system) {
    if (!/^[a-z0-9-]{1,100}$/.test(id)) throw new Error('INVALID_SESSION_ID');
    if (typeof system !== 'string' || system.trim().length < 80) throw new Error('MISSING_SYSTEM');
    prompts.set(id, system);
    if (handles.has(id)) return handles.get(id).agent;
    const setup = (agentCtx) => {
      agentCtx.systemPrompt.section({ name: 'asuna-complete', order: 0, complete: true,
        interpolate: false, text: () => prompts.get(id) });
      agentCtx.systemPrompt.suppressRuntimeContext();
    };
    const options = { provider: 'asuna-local', model: config.model,
      reasoningEffort: 'high', maxTokens: config.maxTokens };
    const persisted = await ctx.sessionPersistence.stat(id);
    const handle = persisted
      ? await ctx.agents.resume({ resumeSessionId: id, agentOptions: options, setup })
      : await ctx.agents.create({ sessionId: id, meta: { cwd: config.workdir }, agentOptions: options, setup });
    handles.set(id, handle);
    return handle.agent;
  }
  function resultFrom(events, messageId) {
    const start = events.findIndex(e => e.type === 'user/message' && e.data.id === messageId);
    if (start < 0) return undefined;
    const suffix = events.slice(start);
    const end = suffix.find(e => e.type === 'turn/end');
    if (!end) return undefined;
    const messages = suffix.filter(e => e.type === 'assistant/message' && e.seq < end.seq);
    const last = messages.at(-1)?.data.message;
    return { content: (last?.content ?? []).filter(b => b.type === 'text').map(b => b.text).join(''),
      reasoning: (last?.content ?? []).filter(b => b.type === 'reasoning').map(b => b.text).join(''),
      finish_reason: end.data.reason.kind, events: suffix.filter(e => e.seq <= end.seq), message_id: messageId };
  }
  async function run(input) {
    const path = join(config.receipts, hash(input.operation) + '.json');
    const inputHash = hash(JSON.stringify([input.session, input.phase, input.text, input.system]));
    let record = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : undefined;
    if (record && record.inputHash !== inputHash) throw new Error('OPERATION_CONTENT_MISMATCH');
    if (record?.state === 'DONE') return record.result;
    const agent = await handleSession(input.session, input.system);
    if (record) {
      await agent.whenIdle();
      const recovered = resultFrom(agent.session.snapshotEvents(), record.message.id);
      if (!recovered) throw new Error('UNKNOWN_DELIVERY_REQUIRES_RECONCILIATION');
      await ctx.sessions.flush(agent.session);
      save(path, { ...record, state: 'DONE', result: recovered });
      return recovered;
    }
    const message = createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: input.text }] });
    record = { state: 'INTENT', inputHash, session: input.session, message };
    save(path, record);
    agent.followup(message);
    // followup is delivery, not a completion handle. This bridge serializes one
    // operation per lane and correlates the accepted user message to its turn.
    await agent.whenIdle();
    if (!await ctx.sessions.flush(agent.session)) throw new Error('NO_DURABLE_SESSION_LISTENER');
    const result = resultFrom(agent.session.snapshotEvents(), message.id);
    if (!result) throw new Error('NO_CAUSAL_TURN_RESULT');
    save(path, { ...record, state: 'DONE', result });
    return result;
  }
  const server = createServer(async (req, res) => {
    try {
      if (req.headers.authorization !== 'Bearer ' + process.env.ASUNA_BRIDGE_TOKEN) throw new Error('UNAUTHORIZED');
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
