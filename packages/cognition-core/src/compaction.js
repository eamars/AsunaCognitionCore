/** Character-brain compaction: DSH's basic engine with a Chinese role-play checkpoint.
 *
 * Everything except the summary request is DSH's: thresholds, retained tail,
 * tool pairing, checkpoint framing and the shrink check. `summarize` is the
 * documented subclass hook. It sends the whole conversation, the retained tail
 * included, and then the instruction, which names the tail as kept: the request
 * extends exactly what the server last processed, so it resumes from there (a
 * prefix that stops mid-history finds no saved state to resume from). When the
 * whole conversation would not fit beside the summary cap, or the model refuses
 * it for its window, it sends the replayed span alone, as DSH does. A span too
 * large for one request (the model refuses it for its context window) is
 * summarized in steps: its first half, then that summary followed by the rest,
 * halving again while a part does not fit. `floorTokens` is the size past which
 * a quiet group's conversation is condensed without her mark (ADR-049): half of
 * this engine's own compaction threshold for the conversation's model. The
 * summary request thinks at the conversation's own reasoning level, so it carries that level's thinking budget and
 * the engine still matches it against the conversation's cache (a different level matches nothing); a conversation
 * that names no level uses `summaryReasoningEffort` (a persona preset sets it beside the summary cap), when the model
 * offers it. A summary without every section the instruction asks for, in order, is rejected like an empty one: no
 * checkpoint is written and the next step tries again. Her conversations are compacted at the end of a turn
 * (`compactAtTurnEnd`, ADR-094): once the conversation is at `turnEndRatio` of the window, the Host compacts it while
 * she is idle, keeping her whole last turn as it is (`compactTurnEnd`, DSH's `compactNow` with a keep-from point); the
 * summary request carries the span before that turn alone, and the next turn reads the checkpoint and her last turn,
 * not a long kept tail. Her turn takes precedence: a stage starting in that conversation stops its turn-end compaction,
 * which also stops at a deadline (`TurnEnds`), and a stopped one leaves the conversation as it was. On a DSH whose
 * `compactNow` keeps no turn nothing is compacted at the turn's end. DSH's in-turn pressure compaction stays as the
 * guard for a turn that grows past the threshold. The action brain keeps DSH's own engineering template. */
import z from '@deepseek-ai/schemastery';
import BasicCompactionEngine from '@deepseek-ai/dsh-compaction-basic';
import { BlockAssembler, LlmError, contentHasImage, createUserMessage, errorChain } from '@deepseek-ai/dsh-llm';
import { overflowed } from './carry.js';

export const ROLE_COMPACTION_INSTRUCTION = [
  '现在请你作为这段对话的压缩器：把上面较早的一段对话整理成一份检查点，让同一个角色接着往下聊时不丢失来龙去脉。',
  '',
  '只输出下面的 Markdown 结构，保留每个小节并按顺序；没有内容的小节写“（无）”。用简短条目，不写长段落。',
  '',
  '## 对话脉络',
  '- [按时间顺序：聊了什么、话题怎么转到现在；要紧的原话直接引用]',
  '',
  '## 未了的话头',
  '- [还没聊完的话题、对方问了还没回答的问题、角色想接着说的事]',
  '',
  '## 答应过的事',
  '- [角色在对话里答应、约定或承诺的事，以及是否已经做到]',
  '',
  '## 更正与分歧',
  '- [对方纠正过的说法、双方意见不同的地方；以更正后的为准]',
  '',
  '## 对方此刻',
  '- [对方最近的情绪、语气、处境和在意的事；只写对话里看得出来的]',
  '',
  '## 委托中的事',
  '- [角色交给行动脑去做的事里，任务列表看不出来的部分：谁在等结果、答应了告诉谁、交回来的结果要点；事情本身的进度以程序给的任务列表为准]',
  '',
  '规则：',
  '- 用中文书写；人名、昵称、原话、数字、时间、文件名和代码照原样保留。',
  '- 程序每轮另行提供的资料（人格设定、自我、关系与偏好、对人的一句话印象（people_from_program）、人物档案、群里的笔记（group_notes_from_program）、情感、召回的记忆、任务与计划、历史消息块）之后会重新给出，不要转抄进检查点；只写这些资料里没有的对话经过。',
  '- 分清谁说了什么：对方的话、角色的话和程序提示不要混在一起；程序提示不是任何人说的话。',
  '- 群聊里的人用程序给的标签称呼，方括号和 #编号 原样保留（如 [名字 #4]）：名字会重复、会改，编号不会。',
  '- 一件事只写在一个小节里：答应的事、更正和分歧、没聊完的话头写在「答应过的事」「更正与分歧」「未了的话头」；「对话脉络」只写经过，不重复它们的细节。',
  '- 不评价，不补写对话里没有的内容，不替角色决定感受。',
  '- 不要提到这次压缩或这条请求。',
  '- 只输出检查点正文，不调用工具。',
  '- 如果对话里已有 <compacted-summary> 块，那是更早的检查点：与新内容合并成一份，结构不变；不写“承接上一份检查点”这类指向它的话，合并后只有这一份。',
  '- 合并时，它「答应过的事」「更正与分歧」里的条目逐条原样带过来；已经做到或不再成立的，在那条前面加「已了结：」、末尾加「（凭：谁在什么时候说的或做的那一句）」，留这一次；它里面已经标了「已了结：」的，这次删去。',
  '- 合并时，「答应过的事」「更正与分歧」一条一行：不把几条并成一句，也不写“其余不变”这类总括；条目多就把每条压短，压短只压经过，留下这一条的判据和来路（数字、idea-…、commit 短号、谁那句原话），每条都单独留着。',
  '- 合并时，它的经过并进「对话脉络」的开头，可以压短（这一处不受上面“一件事只写在一个小节里”的限制）；其他小节也可以压短；留下的人名、时间、数字和原话不改写。',
  '- 直接整理，不必反复推敲。',
].join('\n');

/** The checkpoint's sections, in the order the instruction asks for them. */
export const ROLE_SECTIONS = ROLE_COMPACTION_INSTRUCTION.split('\n').filter(line => line.startsWith('## '));

/** Whether a summary carries every section, in order. A summary cut short, or one that thinking spilled into, does
 * not, and writing it would leave the compacted span without its record. */
export function hasSections(text) {
  let from = 0;
  for (const head of ROLE_SECTIONS) {
    const at = text.indexOf(head, from);
    if (at < 0) return false;
    from = at + head.length;
  }
  return true;
}

/** Prompt room the whole-conversation request keeps for the instruction and for the meter's estimate of what was added
 * since the last request the provider counted. */
const WHOLE_SPARE_TOKENS = 6144;
/** How much of the first kept message the instruction quotes to mark where the kept part starts. */
const KEPT_QUOTE_CHARS = 40;
/** Agents in an automatic compaction (step pressure or context overflow). Their summary request carries the compacted
 * span alone: one that also carries the retained tail restates it, however the instruction names the boundary (ADR-085
 * §4c). A commanded compaction keeps its last message only and still sends the whole conversation, which its cache
 * reads. */
const automatic = new WeakSet();
/** Agents in a turn-end compaction (ADR-094): as for an automatic one, the summary request carries the compacted span
 * alone, so the summarizer never sees the turn that stays as it is. */
const turnEnding = new WeakSet();
/** Share of the window at which a conversation is compacted at the end of its turn (ADR-094), when the preset names
 * none: below DSH's in-turn threshold by more than a turn's growth, so the in-turn path stays the exception. */
const TURN_END_RATIO = 0.70;

/** ADR-094: compact one of her conversations at the end of its turn, keeping that whole turn as it is, when it is due.
 * Only her own conversations (`asuna-role-*` on the character lane), only on a DSH that can keep a turn
 * (`keepsTurns`), only at or above the engine's `turnEndTokens`, only while nothing of hers runs or waits there
 * (`idle`); `compact` runs the engine's `compactTurnEnd`. A conversation that is busy is left for its next turn's end.
 * Returns what was decided, for the Host's log line. */
export async function compactAtTurnEnd({ lane, agent, idle, meter, engine, compact }) {
  const id = agent.session.id;
  if (lane !== 'character' || !id.startsWith('asuna-role-')) return { skipped: 'not her conversation' };
  if (!meter || typeof engine?.turnEndTokens !== 'function') return { skipped: 'no meter or engine' };
  if (!engine.keepsTurns?.()) return { skipped: 'dsh keeps no turn' };
  const due = await engine.turnEndTokens(agent);
  if (!due) return { skipped: 'no window' };
  const tokens = meter.measure(agent.session).totalTokens;
  if (tokens < due) return { skipped: 'below', tokens, due };
  if (!idle()) return { skipped: 'busy', tokens, due };
  return { tokens, due, result: await compact() };
}

/** The longest a turn-end compaction runs (ADR-094): past it, it stops and the next turn end tries again. Above the
 * summaries measured (46–69 s median, plus ~20 s when the span is read cold). */
export const TURN_END_DEADLINE_MS = 180_000;

/** ADR-094: this Host's turn-end compactions of her conversations. Her turn takes precedence: a stage starting in a
 * conversation (`begin`) stops its running turn-end compaction and keeps a new one from starting until the stage is
 * handed to DSH; each one also stops at `deadline`. A stopped one leaves the conversation as it was (DSH closes its
 * compaction with an error), so the next turn end tries again; the in-turn guard is DSH's and unchanged. One that did
 * not commit cleanly stops them in its conversation until it is opened again (a new agent); one after which her last
 * turn is not right after the checkpoint stops them for the rest of this run. One log line each. */
export class TurnEnds {
  constructor(ctx, deadline = TURN_END_DEADLINE_MS) {
    this.ctx = ctx;
    this.deadline = deadline;
    /** Session id → the AbortController of its running turn-end compaction. */
    this.running = new Map();
    /** Session id → how many of her stages are being started there. */
    this.starting = new Map();
    /** Agents whose turn-end compaction did not commit cleanly. */
    this.broken = new WeakSet();
    /** Why turn-end compaction is off for this run, once it is. */
    this.off = '';
    this.saidNoTurnKept = false;
  }

  /** Her stage is about to start in this conversation: stop its turn-end compaction, start none until the returned
   * function is called (once the stage is handed to DSH, or refused). */
  begin(id) {
    this.running.get(id)?.abort(new Error('her turn came first'));
    this.starting.set(id, (this.starting.get(id) ?? 0) + 1);
    let ended = false;
    return () => {
      if (ended) return;
      ended = true;
      const left = this.starting.get(id) - 1;
      if (left) this.starting.set(id, left); else this.starting.delete(id);
    };
  }

  /** The end of one of her turns (`compactAtTurnEnd`, with `idle` the Host's own test). Returns what was decided, or
   * undefined when turn-end compaction is off for the conversation or the run. */
  async run({ agent, engine, meter, idle }) {
    const id = agent.session.id;
    if (this.off || this.broken.has(agent)) return undefined;
    const own = new AbortController();
    const done = await compactAtTurnEnd({ lane: 'character', agent, meter, engine,
      idle: () => idle() && !this.starting.has(id),
      compact: () => {
        this.running.set(id, own);
        return engine.compactTurnEnd(agent, AbortSignal.any([own.signal, AbortSignal.timeout(this.deadline)]))
          .finally(() => { if (this.running.get(id) === own) this.running.delete(id); });
      } });
    const logger = this.ctx.logger;
    if (done.skipped === 'dsh keeps no turn') {
      if (!this.saidNoTurnKept) logger.info('Asuna compaction: this DSH keeps no turn at compaction (compactNow has no'
        + ' keepFrom), so her conversations are compacted only in a turn, at the threshold (ADR-094 §8)');
      this.saidNoTurnKept = true;
      return done;
    }
    if (done.skipped && done.skipped !== 'busy') return done;
    const head = 'Asuna compaction: turn end of ' + id + ' at ~' + done.tokens + ' tokens (due at ' + done.due + '): ';
    const result = done.result ?? {};
    if (done.skipped) logger.info(head + 'busy, left for the next turn end');
    else if (result.code === 'aborted') logger.info(head + 'stopped, ' + (result.compacted ? 'after it was written' : 'nothing changed')
      + ' (' + (own.signal.aborted ? own.signal.reason.message : 'over its ' + this.deadline / 1000 + ' s deadline') + ')');
    else if (result.code === 'commit') {
      this.broken.add(agent);
      logger.warn(head + 'did not commit cleanly; none here until the conversation is opened again (' + result.reason + ')');
    } else if (result.code === 'persistence') logger.warn(head + 'compacted, but not yet written to disk (' + result.reason + ')');
    else if (!result.compacted) logger.info(head + 'not compacted (' + (result.code ? result.code + ': ' : '') + result.reason + ')');
    else logger.info(head + 'compacted ' + result.items + ' items (~' + result.tokens + ' tokens)');
    if (result.compacted && result.keptTurn === false) {
      this.off = 'her last turn was not kept';
      logger.warn('Asuna compaction: after the turn-end compaction of ' + id + ' her last turn is not right after the'
        + ' checkpoint, so this DSH does not keep it as asked; turn-end compaction is off until this Host restarts (ADR-094 §8)');
    }
    return done;
  }
}

/** ADR-094 §8: the first surface node of her last turn, by place on the surface: the one after the last node from
 * before the end of her turn before it, so the line that opened her turn stays with it. A turn that left nothing on
 * the surface (rejected, or its message removed) does not count. Undefined when there is no earlier turn to compact.
 * Seq order is not surface order: a replacement (a checkpoint, a pruned result, a new system head) takes a new seq at
 * an old place. */
export function lastTurnStart(session) {
  const nodes = session.surface.nodes, onSurface = new Set(nodes), ends = [];
  let holds = false;
  for (const event of session.snapshotEvents()) {
    if (event.type === 'turn/start') holds = false;
    else if (event.type === 'turn/end') { if (holds) ends.push(event.seq); holds = false; }
    else if (onSurface.has(event.seq)) holds = true;
  }
  if (ends.length < 2) return undefined;
  const before = ends.at(-2);
  const last = nodes.findLastIndex(seq => seq <= before);
  return last < 0 ? undefined : nodes[last + 1];
}

/** The compaction committed in the session after `seq`: the id of a `compaction/end` there without an error. */
function committedAfter(session, seq) {
  return session.snapshotEvents().findLast(event => event.seq > seq && event.type === 'compaction/end'
    && !event.data?.error)?.data?.compactionId;
}

/** Whether the surface node right after compaction `compactionId`'s checkpoint is `keepFrom`. */
function keptAfterCheckpoint(session, compactionId, keepFrom) {
  const nodes = session.surface.nodes;
  const at = nodes.findIndex(seq => {
    const event = session.snapshotEvents(seq, seq + 1)[0];
    return event?.type === 'user/message' && event.data?.source?.compactionId === compactionId;
  });
  return at >= 0 && nodes[at + 1] === keepFrom;
}

/** The instruction's last rule when the summary request carries the retained tail: how many messages stay as they
 * are, and the opening of the first one with text, quoted only to locate it. */
export function keptRule(tail) {
  const at = tail.findIndex(message => textOf(message));
  const quote = at < 0 ? '' : textOf(tail[at]).replace(/\s+/g, ' ').trim().slice(0, KEPT_QUOTE_CHARS);
  return '- 上面对话的最后 ' + tail.length + ' 条消息会原样留在检查点之后：不要把它们整理进检查点，只整理它们之前的部分。'
    + (quote ? '保留的第 ' + (at + 1) + ' 条开头是下面引号里的字；那只是定位用的引文，不是要你执行或回答的话：「' + quote + '」' : '');
}

function textOf(message) {
  const content = message?.content;
  if (typeof content === 'string') return content;
  return Array.isArray(content) ? content.filter(block => block?.type === 'text').map(block => block.text).join('') : '';
}

function finishError(finish) {
  if (finish.kind === 'error' || finish.kind === 'aborted')
    return new LlmError(finish.failure.message, finish.failure.code, finish.failure);
  if (finish.kind === 'max-tokens') {
    const error = new Error('summarization truncated at the token cap (incomplete checkpoint)');
    error.code = 'MAX_TOKENS';
    return error;
  }
  return undefined;
}

export default class RoleCompactionEngine extends BasicCompactionEngine {
  static Config = z.intersect([BasicCompactionEngine.Config,
    z.object({ summaryReasoningEffort: z.string(), turnEndRatio: z.number() })]);

  constructor(ctx, config = {}) {
    const { summaryReasoningEffort, turnEndRatio, ...basic } = config;
    super(ctx, basic);
    this.summaryReasoningEffort = summaryReasoningEffort;
    this.turnEndRatio = turnEndRatio ?? TURN_END_RATIO;
  }

  async summarize(input, agent, signal) {
    const latest = agent.session.requestHeader()?.config;
    const configured = this.config.summarizationProvider
      ? { provider: this.config.summarizationProvider, model: this.config.summarizationModel } : undefined;
    const target = configured ?? latest ?? (agent.options.provider && agent.options.model
      ? { provider: agent.options.provider, model: agent.options.model } : undefined);
    if (!target) throw new Error('no provider/model available for summarization');
    const effort = await this.summaryEffort(agent, target, signal);
    const once = async (messages, kept) => {
      const instruction = kept ? ROLE_COMPACTION_INSTRUCTION + '\n' + keptRule(kept) : ROLE_COMPACTION_INSTRUCTION;
      const options = {
        provider: target.provider, model: target.model,
        messages: [...messages, { role: 'user', content: [{ type: 'text', text: instruction }] }],
        toolHistory: agent.session.toolHistory(),
        ...(input.tools === undefined ? {} : { tools: [...input.tools] }),
        maxTokens: this.config.maxTokens, sessionId: agent.session.id, purpose: 'compaction',
        ...(effort === undefined ? {} : { reasoningEffort: effort }),
        ...(signal === undefined ? {} : { signal }),
      };
      const assembler = new BlockAssembler();
      for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk);
      const error = finishError(assembler.finish);
      if (error) throw error;
      const rawOutput = assembler.blocks();
      if (contentHasImage(rawOutput)) throw new LlmError('compaction summary cannot contain image output', 'UNSUPPORTED_CONTENT');
      const summary = rawOutput.filter(block => block.type === 'text');
      if (!summary.some(block => block.text.trim())) throw new Error('summarization produced no text summary content');
      if (!hasSections(summary.map(block => block.text).join('\n')))
        throw new Error('summary lacks sections of the checkpoint (cut short, or thinking spilled into it)');
      return { summary, rawOutput, llmStreamCall: true, provider: options.provider, model: options.model,
        maxTokens: this.config.maxTokens, ...(assembler.usage === undefined ? {} : { usage: assembler.usage }) };
    };
    const whole = automatic.has(agent) ? { reason: 'automatic' } : turnEnding.has(agent) ? { reason: 'turn end' }
      : await this.wholeConversation(input, agent, target, signal);
    if (whole?.messages) {
      try { return await once(whole.messages, whole.tail); }
      catch (error) { if (!overflowed(error)) throw error; this.spanAlone(agent, 'refused for the window', whole); }
    } else if (whole) this.spanAlone(agent, whole.reason, whole);
    const [head, body] = input.messages[0]?.role === 'system'
      ? [input.messages.slice(0, 1), input.messages.slice(1)] : [[], input.messages];
    return inSteps(head, body, messages => once(messages));
  }

  /** Whether this DSH's `compactNow` takes a keep-from point (its fourth parameter, `options.keepFrom`). Without one it
   * keeps only the last message, which she declined (ADR-094 §8), so the turn end compacts nothing. */
  keepsTurns() {
    return this.compactNow.length >= 4;
  }

  /** ADR-094: her conversation compacted at the end of its turn, her whole last turn kept as it is, the summary
   * request carrying the span alone. Returns { compacted, items, tokens, keptTurn }: `keptTurn` whether her turn's
   * first node is right after the new checkpoint. Or, when it failed or `signal` stopped it, { compacted, code,
   * reason } with DSH's code ('aborted' for `signal`) and the cause chain; `compacted` says whether it committed all
   * the same (an abort during its durability flush, or a failed flush). */
  async compactTurnEnd(agent, signal) {
    const session = agent.session;
    const keepFrom = lastTurnStart(session);
    if (keepFrom === undefined) return { compacted: false, reason: 'no earlier turn' };
    const from = session.snapshotEvents().at(-1)?.seq ?? -1;
    turnEnding.add(agent);
    try {
      const result = await this.compactNow(agent, signal, undefined, { keepFrom });
      return result === null ? { compacted: false, reason: 'nothing to compact' }
        : { compacted: true, items: result.shadowedSeqs.length, tokens: result.shadowedTokenCount,
          keptTurn: keptAfterCheckpoint(session, result.compactionId, keepFrom) };
    } catch (error) {
      const committed = committedAfter(session, from);
      return { compacted: committed !== undefined, ...(committed === undefined ? {}
        : { keptTurn: keptAfterCheckpoint(session, committed, keepFrom) }),
      code: signal?.aborted ? 'aborted' : error?.code, reason: errorChain(signal?.aborted ? signal.reason : error) };
    } finally { turnEnding.delete(agent); }
  }

  /** DSH's automatic compaction, marked for `summarize` while it runs. */
  async compactIfNeeded(agent, trigger, signal) {
    automatic.add(agent);
    try { return await super.compactIfNeeded(agent, trigger, signal); } finally { automatic.delete(agent); }
  }

  /** The whole conversation as the next request would send it, split after the replayed span, when the span is its
   * start and the whole of it fits the window beside the summary cap; otherwise why not (`reason`), or undefined when
   * there is no meter or window to judge by. */
  async wholeConversation(input, agent, target, signal) {
    const session = agent.session;
    const meter = this.ctx.tokenMeter;
    if (!session.surface?.nodes || !meter || !this.ctx.llm.resolveModelInfo) return undefined;
    const info = await this.ctx.llm.resolveModelInfo(target.provider, target.model, signal);
    const window = info?.context?.contextWindow;
    if (!window) return undefined;
    const size = { tokens: meter.measure(session).totalTokens, window };
    if (size.tokens + WHOLE_SPARE_TOKENS + this.config.maxTokens > window) return { ...size, reason: 'too large' };
    const messages = session.surface.nodes.map(seq => session.deriveEventMessage(session.eventAt(seq)))
      .filter(message => message !== null);
    const span = input.messages.length;
    if (messages.length <= span || messages.slice(0, span).some((message, index) =>
      JSON.stringify(message) !== JSON.stringify(input.messages[index]))) return { ...size, reason: 'span is not the start' };
    return { ...size, messages, tail: messages.slice(span) };
  }

  /** The summary request's thinking level: the conversation's own (its latest request's), else the configured one,
   * when the model offers it; otherwise none. One log line says which level and where it came from. */
  async summaryEffort(agent, target, signal) {
    const own = agent.session.requestHeader?.()?.config?.reasoningEffort;
    const level = own ?? this.summaryReasoningEffort;
    const from = own ? "the conversation's" : 'the preset\'s';
    if (!level || !this.ctx.llm.resolveModelInfo) return undefined;
    const info = await this.ctx.llm.resolveModelInfo(target.provider, target.model, signal);
    const offered = info?.reasoning?.efforts?.some(effort => effort.id === level);
    this.ctx.logger?.info?.('Asuna compaction: summary request thinks at ' + (offered
      ? '"' + level + '" (' + from + ')'
      : 'no named level: ' + target.provider + '/' + target.model + ' offers no "' + level + '" (' + from + ')')
      + ' in ' + agent.session.id);
    return offered ? level : undefined;
  }

  /** One log line each time the summary request falls back to the replayed span alone, with the sizes it judged by,
   * so a reading of compactions can tell the two shapes apart. */
  spanAlone(agent, reason, { tokens, window }) {
    this.ctx.logger?.info?.('Asuna compaction: summary request sends the compacted span alone (' + reason + (tokens
      ? '; conversation ~' + tokens + ' tokens, summary cap ' + this.config.maxTokens + ', window ' + window : '')
      + ') in ' + agent.session.id);
  }

  /** This engine's compaction threshold for the conversation's model, as DSH's basic engine resolves it
   * (`resolveCompactSpec`), or undefined when the model declares no window. */
  async pressure(agent) {
    const target = agent.session.requestHeader()?.config
      ?? (agent.options.provider && agent.options.model ? agent.options : undefined);
    if (!target) return undefined;
    const info = await this.ctx.llm.resolveModelInfo(target.provider, target.model);
    const window = info.context?.contextWindow;
    if (!window) return undefined;
    const own = this.config.modelPolicies?.find(policy => policy.provider === target.provider && policy.model === target.model);
    const ratio = own?.thresholdRatio ?? this.config.thresholdRatio;
    const headroom = own?.headroomTokens ?? this.config.headroomTokens ?? 0;
    const budget = window - (agent.session.requestHeader()?.config.maxTokens ?? info.defaultMaxTokens ?? 0);
    return { threshold: Math.floor(Math.min(window * ratio, budget - headroom)) };
  }

  /** Half of this engine's compaction threshold for the conversation's model, in DSH's own measure (ADR-049's size
   * floor), or undefined when the model declares no window. */
  async floorTokens(agent) {
    const spec = await this.pressure(agent);
    return spec && Math.floor(spec.threshold / 2);
  }

  /** The size at which one of her conversations is compacted at the end of its turn (ADR-094): `turnEndRatio` of the
   * conversation's model's window, in DSH's own measure, or undefined when the model declares no window. */
  async turnEndTokens(agent) {
    const target = agent.session.requestHeader()?.config
      ?? (agent.options.provider && agent.options.model ? agent.options : undefined);
    if (!target) return undefined;
    const info = await this.ctx.llm.resolveModelInfo(target.provider, target.model);
    const window = info?.context?.contextWindow;
    return window ? Math.floor(window * this.turnEndRatio) : undefined;
  }
}

/** Summarize `body` after `head` in one request, or, when the model refuses it for its context window, in steps: the
 * first part, then its summary followed by the rest. A part is cut only before a user message, so a tool call and its
 * result stay together. */
export async function inSteps(head, body, once) {
  const cuts = body.map((message, index) => index).filter(index => index > 0 && body[index].role === 'user');
  try { return await once([...head, ...body]); }
  catch (error) { if (!overflowed(error) || !cuts.length) throw error; }
  const middle = Math.floor(body.length / 2);
  const cut = cuts.reduce((best, index) => Math.abs(index - middle) < Math.abs(best - middle) ? index : best);
  const first = await inSteps(head, body.slice(0, cut), once);
  const text = first.summary.map(block => block.text).join('\n');
  return inSteps(head, [createUserMessage({ source: { kind: 'asuna', form: 'notice' },
    content: [{ type: 'text', text: '<compacted-summary>\n' + text + '\n</compacted-summary>' }] }), ...body.slice(cut)], once);
}
