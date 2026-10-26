/** No local root of this computer reaches her character brain (ADR-098). The worker builds the root table at its start
 * (local_roots.py) and hands it over with its `initialize` answer; every request of her lanes (her persona preset,
 * the relevance gate, the appraiser, the background summaries; never the action brain) is rewritten with it at
 * DSH's `llm/stream` waterfall, the one place every request passes: turn steps, compaction summaries, one-shot
 * sessions. Text blocks (the system message included), reasoning and earlier tool calls' arguments are contracted;
 * storage stays raw. Without a table her lanes' requests are refused with a coded fault, never sent raw. The same
 * shared case file (tests/fixtures/path_placeholders.json) runs here and in pytest.
 *
 * One path is written after the waterfall: the note DSH's DeepSeek adapter puts beside each image names the
 * attachment's copy by a path it asks DSH's fs service for (`processPathFromHostPath`), while it builds the request.
 * Her requests therefore run in a scope (`HERS`), and that one mapping answers with the path contracted inside it;
 * everywhere else (the action brain, DSH's own UI and session controller) it answers as it always did. */
import { AsyncLocalStorage } from 'node:async_hooks';
import { isAgentLoopRequest, markAgentLoopRequest } from '@deepseek-ai/dsh-llm';

/** Her lanes (index.js laneOf): whatever the model reads there is hers. */
export const HER_LANES = new Set(['character', 'attend', 'appraiser', 'summary']);
export const MISSING = 'ASUNA_ROOT_TABLE_MISSING';
const MISSING_TEXT = MISSING + ': 程序没有拿到本机路径表，这一回合没有发给模型（不是你的错）；已经报给开发者了，'
  + '重试也一样，等程序修好';
const DONE = Symbol('asuna.roots');
const WRAPPED = Symbol('asuna.roots.fs');
/** The table of the request of hers being built now; undefined outside one. */
const HERS = new AsyncLocalStorage();
const FLUSH_MS = 60_000;

/** The worker's wire table, compiled; null for none. */
export function compile(wire) {
  if (!wire || typeof wire.source !== 'string' || !Array.isArray(wire.groups)) return null;
  return { pattern: new RegExp(wire.source, 'g'), groups: wire.groups, roots: wire.roots ?? 0, cache: new WeakMap() };
}

function nameOf(name, text) {
  if (name !== 'DRIVE_') return name;
  const lower = text.toLowerCase();
  return 'DRIVE_' + (lower.startsWith('/') || lower.startsWith('%2f') ? text.at(-1) : text[0]).toUpperCase();
}

/** { text with every root written as its placeholder, how many were replaced }. */
export function contract(table, text) {
  let count = 0;
  const n = table.groups.length;
  const out = text.replace(table.pattern, (...args) => {
    for (let i = 0; i < n; i++) {
      const group = args[1 + i];
      if (group !== undefined) { count++; return '${ASUNA_' + nameOf(table.groups[i], group) + '}'; }
    }
    return args[0];
  });
  return { text: count ? out : text, count };
}

function block(table, item) {
  if ((item?.type === 'text' || item?.type === 'reasoning') && typeof item.text === 'string') {
    const { text, count } = contract(table, item.text);
    return count ? [{ ...item, text }, count] : [item, 0];
  }
  if (item?.type === 'tool-call' && typeof item.arguments === 'string') {
    const { text, count } = contract(table, item.arguments);
    return count ? [{ ...item, arguments: text }, count] : [item, 0];
  }
  return [item, 0];
}

/** One message contracted (the same object when nothing changed); cached by message, since DSH reuses its frozen
 * history from request to request and the rewrite of each is the same every time. */
function message(table, item) {
  const known = table.cache.get(item);
  if (known) return known;
  let count = 0;
  const content = Array.isArray(item?.content) ? item.content.map(part => {
    const [next, n] = block(table, part); count += n; return next;
  }) : item?.content;
  const value = [count ? Object.freeze({ ...item, content: Object.freeze(content) }) : item, count];
  if (item && typeof item === 'object') table.cache.set(item, value);
  return value;
}

/** { request, count }: the request with every root contracted; the same request object when there was none. */
export function rewriteRequest(table, options) {
  let count = 0;
  const messages = (options.messages ?? []).map(item => { const [next, n] = message(table, item); count += n; return next; });
  let system = options.system;
  if (typeof system === 'string') { const out = contract(table, system); system = out.text; count += out.count; }
  if (!count) return { request: options, count };
  const request = { ...options, messages, ...(system !== undefined ? { system } : {}), [DONE]: true };
  if (isAgentLoopRequest(options)) markAgentLoopRequest(request);
  return { request, count };
}

/** The table, its counts and the refusals, kept on the core (`core.roots`). */
export class Roots {
  constructor(core) {
    this.core = core;
    this.table = null;
    this.refused = null;            // why the worker built none, when it said so
    this.sessions = new Map();      // session id -> { lane, requests, rewritten } since the plugin started
    this.unsent = new Map();        // the same, not yet handed to the worker
    this.reported = false;          // the missing table's one audit event
    this.timer = null;
  }

  /** The worker's answer at its start: a table, or why there is none. */
  take(wire, refused) {
    this.table = compile(wire);
    this.refused = this.table ? null : (refused || 'the worker sent no table');
    if (this.table) this.reported = false;
  }

  count(sessionId, lane, replaced) {
    for (const map of [this.sessions, this.unsent]) {
      const row = map.get(sessionId) ?? { lane, requests: 0, rewritten: 0 };
      row.requests++; if (replaced) row.rewritten++;
      map.set(sessionId, row);
    }
    this.timer ??= setTimeout(() => this.flush(), FLUSH_MS);
    this.timer.unref?.();
  }

  /** The counts since the last flush reach the worker, which keeps them for her weekly reading. */
  flush() {
    clearTimeout(this.timer); this.timer = null;
    if (!this.unsent.size || !this.core.worker) return;
    const sessions = [...this.unsent].map(([session_id, row]) => ({ session_id, ...row }));
    this.unsent = new Map();
    this.core.worker.call('roots.tally', { sessions })
      .catch(error => this.core.ctx.logger.warn('Asuna roots: counts not kept: ' + String(error?.message ?? error)));
  }

  refuse(lane) {
    if (!this.reported) {
      this.reported = true;
      this.core.ctx.logger.warn('Asuna roots: no root table (' + this.refused + '): requests of her lanes are refused');
      this.core.worker?.call('roots.refused', { lane, reason: String(this.refused ?? 'no table') })
        .catch(error => this.core.ctx.logger.warn('Asuna roots: refusal not recorded: ' + String(error?.message ?? error)));
    }
    return Object.assign(new Error(MISSING_TEXT), { code: MISSING });
  }

  /** For the settings card: the table's size, or why there is none; requests rewritten per session since start. */
  status() {
    const rows = [...this.sessions.values()];
    return { roots: this.table?.roots ?? 0, refused: this.table ? null : this.refused, sessions: this.sessions.size,
      requests: rows.reduce((sum, row) => sum + row.requests, 0),
      rewritten: rows.reduce((sum, row) => sum + row.rewritten, 0),
      by_session: Object.fromEntries([...this.sessions].map(([id, row]) => [id, { ...row }])) };
  }
}

/** A session's preset as it stands now: DSH's `agentPreset` projection (a preset chosen after the session was made
 * moves it), else its header's. */
function presetOf(ctx, agent) {
  try {
    const now = agent && ctx.sessionProjections?.stateOf?.(agent.session, 'agentPreset');
    if (typeof now === 'string') return now;
  } catch { /* a session without the projection keeps its header's preset */ }
  return agent?.session?.header?.agentPreset;
}

/** DSH's fs service, its host-path mapping wrapped once: inside one of her requests the mapped path comes back
 * contracted. Read again on every request of hers, so a service provided anew is wrapped too. */
export function wrapHostPaths(ctx) {
  let fs;
  try { fs = ctx.get('fs'); } catch { return false; }
  if (!fs || typeof fs.processPathFromHostPath !== 'function') return false;
  if (fs[WRAPPED]) return true;
  const original = fs.processPathFromHostPath;
  fs.processPathFromHostPath = function (hostPath) {
    const mapped = original.call(this, hostPath);
    const table = HERS.getStore();
    return table && typeof mapped === 'string' ? contract(table, mapped).text : mapped;
  };
  fs[WRAPPED] = true;
  return true;
}

/** A stream made and read inside her scope: the adapter builds the request while it is read, after its own
 * awaits, so every step of it runs in the scope. */
function inHerScope(table, make) {
  return (async function* () {
    const it = HERS.run(table, make)[Symbol.asyncIterator]();
    let finished = false;
    try {
      for (;;) {
        const step = await HERS.run(table, () => it.next());
        if (step.done) { finished = true; return step.value; }
        yield step.value;
      }
    } finally {
      if (!finished) await HERS.run(table, () => it.return?.());
    }
  })();
}

/** The listener: her lanes' requests rewritten, or refused without a table; every other request passes as it is. */
export function rootsAtTheModel(core) {
  const { ctx } = core;
  ctx.on('llm/stream', (options, next) => {
    if (options?.[DONE] || !options?.sessionId) return next();
    const agent = ctx.agents?.get(options.sessionId);
    const lane = agent && core.laneOf({ session: { header: { agentPreset: presetOf(ctx, agent) } } });
    if (!HER_LANES.has(lane)) return next();
    const roots = core.roots;
    if (!roots.table) {
      const error = roots.refuse(lane);
      return (async function* () { throw error; })();
    }
    const { request, count } = rewriteRequest(roots.table, options);
    roots.count(options.sessionId, lane, count > 0);
    wrapHostPaths(ctx);
    // Always in her scope, rewritten or not: a picture's note can be the only path in a request.
    return inHerScope(roots.table, () => request === options ? next() : ctx.llm.stream(request));
  }, { global: true });
}
