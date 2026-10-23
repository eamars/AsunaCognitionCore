import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime, { CONTEXT_WINDOW_EXCEEDED_CODE, LlmAdapter, createAssistantMessage, createSystemMessage, createUserMessage }
  from '@deepseek-ai/dsh-llm';
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import TokenMeter from '@deepseek-ai/dsh-token-meter';
import RoleCompactionEngine, { ROLE_COMPACTION_INSTRUCTION, ROLE_SECTIONS, TurnEnds, compactAtTurnEnd, hasSections, inSteps,
  lastTurnStart } from '../src/compaction.js';
import { compactionOpen } from '../src/pairing.js';

const CHECKPOINT = ROLE_SECTIONS.map(head => head + '\n- （无）').join('\n\n');

// The role summary must reuse the replayed prefix byte for byte (provider cache)
// and differ from DSH's request only in the final, Chinese instruction.
test('role compaction keeps the replayed prefix and asks for a Chinese role-play checkpoint', async () => {
  let sent;
  const engine = Object.create(RoleCompactionEngine.prototype);
  engine.config = { summarizationProvider: '', summarizationModel: '', maxTokens: 24576 };
  engine.ctx = { llm: { async *stream(options) {
    sent = options;
    yield { type: 'text-delta', index: 0, text: CHECKPOINT };
    yield { type: 'finish', reason: { kind: 'stop' } };
  } } };
  const prefix = [{ role: 'system', content: [{ type: 'text', text: 'render' }] },
    { role: 'user', content: [{ type: 'text', text: '周末去哪' }] }];
  const agent = { session: { id: 's', requestHeader: () => ({ config: { provider: 'p', model: 'm' } }), toolHistory: () => [] },
    options: {} };
  const result = await engine.summarize({ messages: prefix }, agent);
  assert.deepEqual(sent.messages.slice(0, 2), prefix);
  assert.equal(sent.messages.at(-1).content[0].text, ROLE_COMPACTION_INSTRUCTION);
  assert.doesNotMatch(ROLE_COMPACTION_INSTRUCTION, /coding assistant|English/);
  assert.equal(sent.provider, 'p');
  assert.equal(sent.purpose, 'compaction');
  assert.equal(result.summary[0].text, CHECKPOINT);
  assert.equal(sent.reasoningEffort, undefined, 'no level configured: none named');
  // A merge carries the earlier promises and corrections item by item or marks them closed, and names no earlier
  // checkpoint (ADR-085 §7; her ask): the per-hop reading counts exactly these.
  assert.match(ROLE_COMPACTION_INSTRUCTION, /「答应过的事」「更正与分歧」里的条目逐条原样带过来/);
  assert.match(ROLE_COMPACTION_INSTRUCTION, /前面加「已了结：」、末尾加「（凭：[^」]+）」，留这一次；它里面已经标了「已了结：」的，这次删去/);
  assert.match(ROLE_COMPACTION_INSTRUCTION, /不写“承接上一份检查点”这类指向它的话/);
  // Folded into one line, a dozen corrections were carried once and lost at the next merge (ADR-085 §7, her reading).
  assert.match(ROLE_COMPACTION_INSTRUCTION, /一条一行：不把几条并成一句，也不写“其余不变”这类总括；.*压短只压经过，留下这一条的判据和来路/);
  assert.match(ROLE_COMPACTION_INSTRUCTION, /群里的笔记（group_notes_from_program）/);

  engine.ctx.llm.stream = async function *() { yield { type: 'finish', reason: { kind: 'max-tokens' } }; };
  await assert.rejects(engine.summarize({ messages: prefix }, agent), { code: 'MAX_TOKENS' });
});

// ADR-028/049: a span too large for one summary request (a quiet group's whole conversation) is summarized in steps.
test('a span the model refuses for its window is summarized in steps, cut only before a user message', async () => {
  const user = text => ({ role: 'user', content: [{ type: 'text', text }] });
  const body = [user('a'), { role: 'assistant', content: [{ type: 'tool-call', id: 'c' }] },
    { role: 'tool', content: [{ type: 'text', text: 'r' }] }, user('b'), user('c'), user('d')];
  const tooLong = () => Object.assign(new Error('too long'), { code: CONTEXT_WINDOW_EXCEEDED_CODE });
  const sent = [];
  const once = async messages => {
    sent.push(messages.map(message => message.content[0].text ?? message.role));
    if (messages.length > 5) throw tooLong();
    return { summary: [{ type: 'text', text: 'S' + sent.length }] };
  };
  const result = await inSteps([{ role: 'system', content: [{ type: 'text', text: 'sys' }] }], body, once);
  assert.equal(result.summary[0].text, 'S3');
  assert.deepEqual(sent[1], ['sys', 'a', 'assistant', 'r'], 'the tool call keeps its result');
  assert.deepEqual(sent[2], ['sys', '<compacted-summary>\nS2\n</compacted-summary>', 'b', 'c', 'd']);
  // A single message too large, or any other failure, stays DSH's to handle.
  await assert.rejects(inSteps([], [user('x')], async () => { throw tooLong(); }), /too long/);
  await assert.rejects(inSteps([], body, async () => { throw new Error('refused'); }), /refused/);
});

test('the size floor is half the engine\'s own compaction threshold for the conversation\'s model', async () => {
  const engine = Object.create(RoleCompactionEngine.prototype);
  engine.config = { thresholdRatio: 0.8, headroomTokens: 6144, modelPolicies: [] };
  engine.ctx = { llm: { resolveModelInfo: async () => ({ context: { contextWindow: 262144 }, defaultMaxTokens: 32768 }) } };
  const agent = { session: { requestHeader: () => ({ config: { provider: 'p', model: 'm', maxTokens: 32768 } }) }, options: {} };
  assert.equal(await engine.floorTokens(agent), Math.floor(Math.floor(262144 * 0.8) / 2));
  engine.ctx.llm.resolveModelInfo = async () => ({});
  assert.equal(await engine.floorTokens(agent), undefined, 'no window declared: no floor');
});

// The summary request carries the whole conversation, so it extends what the server last processed and resumes from
// there; the instruction names the kept tail and quotes its start only to locate it.
test('a commanded compaction sends the whole conversation and names the kept tail; an automatic one, or one that would not fit, the span alone', async () => {
  const text = (role, value) => ({ role, content: [{ type: 'text', text: value }] });
  const system = { role: 'system', content: [{ type: 'text', text: 'render' }] };
  const span = [text('user', '周末去哪'), text('assistant', '去海边')];
  const tail = [{ role: 'assistant', content: [{ type: 'tool-call', id: 'c' }] }, text('tool', '晴'),
    text('user', '帮我订\n  两张票，主人说的')];
  const events = [system, ...span, ...tail];
  const sent = [];
  const engine = Object.create(RoleCompactionEngine.prototype);
  engine.config = { summarizationProvider: '', summarizationModel: '', maxTokens: 24576 };
  let measured = 200000, refuse = false;
  const logged = [];
  engine.ctx = {
    logger: { info: line => logged.push(line) },
    tokenMeter: { measure: () => ({ totalTokens: measured }) },
    llm: {
      resolveModelInfo: async () => ({ context: { contextWindow: 262144 } }),
      async *stream(options) {
        sent.push(options.messages);
        if (refuse && options.messages.length > span.length + 2) {
          throw Object.assign(new Error('too long'), { code: CONTEXT_WINDOW_EXCEEDED_CODE });
        }
        yield { type: 'text-delta', index: 0, text: CHECKPOINT };
        yield { type: 'finish', reason: { kind: 'stop' } };
      },
    },
  };
  const session = { id: 's', requestHeader: () => ({ config: { provider: 'p', model: 'm' } }), toolHistory: () => [],
    surface: { nodes: events.map((_, seq) => seq) }, eventAt: seq => seq,
    deriveEventMessage: seq => structuredClone(events[seq]) };
  const agent = { session, options: {} };
  const input = { messages: [system, ...span] };

  await engine.summarize(input, agent);
  assert.deepEqual(sent[0].slice(0, -1), events, 'the whole conversation, in order, before the instruction');
  const instruction = sent[0].at(-1).content[0].text;
  assert.ok(instruction.startsWith(ROLE_COMPACTION_INSTRUCTION));
  assert.match(instruction, /最后 3 条消息会原样留在检查点之后/);
  assert.match(instruction, /保留的第 2 条开头是.*只是定位用的引文，不是要你执行或回答的话：「晴」/);
  assert.deepEqual(logged, [], 'no fallback, no line');

  // Too large beside the summary cap: the replayed span alone, with DSH's instruction unchanged.
  measured = 262144 - 24576 - 6144 + 1;
  sent.length = 0;
  await engine.summarize(input, agent);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].slice(0, -1), input.messages);
  assert.equal(sent[0].at(-1).content[0].text, ROLE_COMPACTION_INSTRUCTION);
  assert.match(logged.at(-1), /span alone \(too large; conversation ~231425 tokens, summary cap 24576, window 262144\) in s$/);

  // Refused for the window anyway: the span alone.
  measured = 200000; refuse = true; sent.length = 0;
  await engine.summarize(input, agent);
  assert.equal(sent.length, 2);
  assert.deepEqual(sent[1].slice(0, -1), input.messages);
  assert.match(logged.at(-1), /refused for the window/);

  // A span that is not the conversation's start: the span alone.
  refuse = false; sent.length = 0;
  await engine.summarize({ messages: [system, text('user', '别的')] }, agent);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].length, 3);
  assert.match(logged.at(-1), /span is not the start/);

  // An automatic compaction (DSH's compactIfNeeded): the span alone, though the whole would fit (ADR-085 §4c).
  const basic = Object.getPrototypeOf(RoleCompactionEngine.prototype);
  const own = basic.compactIfNeeded;
  basic.compactIfNeeded = async function (owner) { return this.summarize(input, owner); };
  try {
    sent.length = 0;
    await engine.compactIfNeeded(agent, 'pressure');
    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0].slice(0, -1), input.messages);
    assert.equal(sent[0].at(-1).content[0].text, ROLE_COMPACTION_INSTRUCTION);
    assert.match(logged.at(-1), /span alone \(automatic\) in s$/);
  } finally { basic.compactIfNeeded = own; }
  // A commanded one after it still sends the whole conversation.
  sent.length = 0;
  await engine.summarize(input, agent);
  assert.deepEqual(sent[0].slice(0, -1), events);
});

// The summary thinks at the conversation's level, else the persona's, when the model offers it; a checkpoint missing
// a section is rejected.
test('the summary request names the conversation\'s thinking level, else the configured one, when the model offers it, and a summary must carry every section', async t => {
  let sent, text = CHECKPOINT;
  const logged = [];
  const plugins = new Context();
  t.after(() => plugins.fiber.dispose());
  const engine = new RoleCompactionEngine(plugins, { maxTokens: 24576, summaryReasoningEffort: 'medium', auto: false });
  assert.equal(engine.summaryReasoningEffort, 'medium', 'its own key, kept apart from the keys DSH checks');
  assert.equal(engine.config.maxTokens, 24576);
  assert.equal(RoleCompactionEngine.Config({ summaryReasoningEffort: 'medium' }).summaryReasoningEffort, 'medium');
  let efforts = ['low', 'medium', 'high'];
  engine.ctx = {
    logger: { info: line => logged.push(line) },
    llm: {
      resolveModelInfo: async () => ({ reasoning: { efforts: efforts.map(id => ({ id, name: id })) } }),
      async *stream(options) {
        sent = options;
        yield { type: 'text-delta', index: 0, text };
        yield { type: 'finish', reason: { kind: 'stop' } };
      },
    },
  };
  const agent = { session: { id: 's', requestHeader: () => ({ config: { provider: 'p', model: 'm' } }), toolHistory: () => [] },
    options: {} };
  const input = { messages: [{ role: 'user', content: [{ type: 'text', text: '周末去哪' }] }] };
  await engine.summarize(input, agent);
  assert.equal(sent.reasoningEffort, 'medium', 'the conversation names no level: the preset\'s');
  assert.match(logged.at(-1), /thinks at "medium" \(the preset's\) in s$/);

  // The conversation's own level wins: a different level would match none of its cache.
  let header = { provider: 'p', model: 'm', reasoningEffort: 'high' };
  agent.session.requestHeader = () => ({ config: header });
  await engine.summarize(input, agent);
  assert.equal(sent.reasoningEffort, 'high');
  assert.match(logged.at(-1), /thinks at "high" \(the conversation's\)/);
  header = { provider: 'p', model: 'm' };

  efforts = ['high'];
  await engine.summarize(input, agent);
  assert.equal(sent.reasoningEffort, undefined, 'a level the model does not offer is not named');
  assert.match(logged.at(-1), /no named level: p\/m offers no "medium" \(the preset's\)/);

  for (const broken of [CHECKPOINT.slice(0, CHECKPOINT.lastIndexOf('##')), ROLE_SECTIONS.slice().reverse().join('\n')]) {
    text = broken;
    await assert.rejects(engine.summarize(input, agent), /lacks sections/);
  }
  assert.ok(hasSections(CHECKPOINT));
  assert.equal(ROLE_SECTIONS.length, 6);
});

// ADR-094: her conversation is compacted at the end of its turn, from the live end, once it is large enough; the
// in-turn path (compactIfNeeded, tested above: the span alone) stays as the guard.
test('a conversation is compacted at the end of its turn at turnEndRatio of the window, only hers, only when idle', async t => {
  const plugins = new Context();
  t.after(() => plugins.fiber.dispose());
  const engine = new RoleCompactionEngine(plugins, { maxTokens: 24576, auto: false });
  assert.equal(engine.turnEndRatio, 0.7, 'the default when the preset names none');
  assert.equal(RoleCompactionEngine.Config({ turnEndRatio: 0.65 }).turnEndRatio, 0.65);
  const other = new Context();
  t.after(() => other.fiber.dispose());
  assert.equal(new RoleCompactionEngine(other, { turnEndRatio: 0.65, auto: false }).turnEndRatio, 0.65);
  engine.ctx = { llm: { resolveModelInfo: async () => ({ context: { contextWindow: 262144 } }) } };
  const agent = { session: { id: 'asuna-role-1', requestHeader: () => ({ config: { provider: 'p', model: 'm' } }) }, options: {} };
  const due = Math.floor(262144 * 0.7);
  assert.equal(await engine.turnEndTokens(agent), due);

  assert.equal(engine.keepsTurns(), false, 'the pinned DSH: compactNow takes no keep-from point');
  let tokens = due, idle = true;
  const compacted = [];
  assert.deepEqual(await compactAtTurnEnd({ lane: 'character', agent, idle: () => true, engine,
    meter: { measure: () => ({ totalTokens: due }) }, compact: async () => assert.fail('never on that DSH') }),
  { skipped: 'dsh keeps no turn' }, 'nothing compacted at a turn end: the last-message-only version never runs');
  engine.keepsTurns = () => true;
  const run = (over = {}) => compactAtTurnEnd({
    lane: 'character', agent, idle: () => idle, engine, meter: { measure: () => ({ totalTokens: tokens }) },
    compact: async () => { compacted.push(tokens); return { compacted: true, items: 9, tokens: 1 }; }, ...over });
  assert.deepEqual(await run(), { tokens: due, due, result: { compacted: true, items: 9, tokens: 1 } }, 'at the ratio: compacted');
  tokens = due - 1;
  assert.deepEqual(await run(), { skipped: 'below', tokens: due - 1, due });
  tokens = due + 5000; idle = false;
  assert.deepEqual(await run(), { skipped: 'busy', tokens: due + 5000, due }, 'a turn running or queued: left alone');
  idle = true;
  assert.equal((await run()).result.compacted, true, 'the next turn end compacts it');
  assert.deepEqual(await run({ lane: 'executor' }), { skipped: 'not her conversation' });
  assert.deepEqual(await run({ agent: { ...agent, session: { ...agent.session, id: 'asuna-errand-1' } } }), { skipped: 'not her conversation' });
  assert.deepEqual(await run({ engine: {} }), { skipped: 'no meter or engine' });
  engine.ctx.llm.resolveModelInfo = async () => ({});
  assert.deepEqual(await run(), { skipped: 'no window' });
  assert.deepEqual(compacted, [due, due + 5000]);
});

test('a turn-end compaction keeps her whole last turn and sends the span before it alone', async () => {
  const text = (role, value) => ({ role, content: [{ type: 'text', text: value }] });
  const system = { role: 'system', content: [{ type: 'text', text: 'render' }] };
  const events = [{ type: 'user/message', seq: 0 }, { type: 'turn/start', seq: 1 }, { type: 'agent/message', seq: 2 },
    { type: 'turn/end', seq: 3 }, { type: 'user/message', seq: 4 }, { type: 'turn/start', seq: 5 },
    { type: 'agent/message', seq: 6 }, { type: 'agent/message', seq: 7 }, { type: 'turn/end', seq: 8 }];
  const surface = { nodes: [0, 2, 4, 6, 7] };
  const session = { id: 's', requestHeader: () => ({ config: { provider: 'p', model: 'm' } }), toolHistory: () => [],
    snapshotEvents: () => events, surface };
  assert.equal(lastTurnStart(session), 4, 'the line that opened her last turn stays with it');
  assert.equal(lastTurnStart({ ...session, snapshotEvents: () => events.slice(0, 4) }), undefined, 'one turn: nothing before it');

  const sent = [], logged = [], calls = [];
  const engine = Object.create(RoleCompactionEngine.prototype);
  engine.config = { summarizationProvider: '', summarizationModel: '', maxTokens: 24576 };
  engine.ctx = { logger: { info: line => logged.push(line) }, llm: {
    resolveModelInfo: async () => ({ context: { contextWindow: 262144 } }),
    async *stream(options) {
      sent.push(options.messages);
      yield { type: 'text-delta', index: 0, text: CHECKPOINT };
      yield { type: 'finish', reason: { kind: 'stop' } };
    } } };
  const agent = { session, options: {} };
  const input = { messages: [system, text('user', '周末去哪'), text('assistant', '去海边')] };
  let answer = { shadowedSeqs: [0, 2], shadowedTokenCount: 50 };
  engine.compactNow = async function (owner, signal, sourceCommandId, options) {
    calls.push({ sourceCommandId, options });
    await this.summarize(input, owner, signal);
    if (answer instanceof Error) throw answer;
    return answer;
  };
  assert.equal(engine.keepsTurns(), true, 'a DSH whose compactNow takes options');
  const done = await engine.compactTurnEnd(agent);
  assert.deepEqual([done.compacted, done.items, done.tokens], [true, 2, 50]);
  assert.deepEqual(calls, [{ sourceCommandId: undefined, options: { keepFrom: 4 } }]);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].slice(0, -1), input.messages, 'the span alone, never the turn that stays');
  assert.equal(sent[0].at(-1).content[0].text, ROLE_COMPACTION_INSTRUCTION);
  assert.match(logged.at(-1), /span alone \(turn end\) in s$/);

  answer = null;
  assert.deepEqual(await engine.compactTurnEnd(agent), { compacted: false, reason: 'nothing to compact' });
  answer = Object.assign(new Error('manual compaction did not commit cleanly', { cause: new Error('append refused') }),
    { code: 'commit' });
  assert.deepEqual(await engine.compactTurnEnd(agent), { compacted: false, code: 'commit',
    reason: 'manual compaction did not commit cleanly: append refused' }, 'the code and the cause chain are kept');
  assert.deepEqual(await engine.compactTurnEnd({ ...agent, session: { ...session, snapshotEvents: () => events.slice(0, 4) } }),
    { compacted: false, reason: 'no earlier turn' });
});

/** A real DSH session: `turns` closed turns of one line and one reply each, after a system head. */
function realSession(turns) {
  const session = Session.create(SessionId('asuna-role-real'));
  session.append('system/message', { turn: 1, step: 1, message: createSystemMessage('render') }, { surfaceOp: 'append' });
  session.append('request/header', { header: { config: { provider: 'm', model: 'm' } }, reason: 'initial' });
  const starts = [];
  for (let turn = 1; turn <= turns; turn++) starts.push(closedTurn(session, turn));
  return { session, starts };
}

/** One closed turn: her line and her reply, or (`reply: false`) a turn rejected before it wrote anything. */
function closedTurn(session, turn, { reply = true } = {}) {
  session.append('turn/start', { turn });
  let line;
  if (reply) {
    line = session.append('user/message', createUserMessage({ content: [{ type: 'text', text: '第' + turn + '句 ' + '话'.repeat(400) }],
      source: { kind: 'user' } }), { surfaceOp: 'append' }).seq;
    session.append('step/start', { turn, step: 1 });
    session.append('assistant/message', { stream: [], turn, step: 1, message: createAssistantMessage({
      content: [{ type: 'text', text: '回' + turn }], source: { provider: 'm', model: 'm' } }) }, { surfaceOp: 'append' });
    session.append('step/end', { turn, step: 1 });
  }
  session.append('turn/end', { turn, reason: { kind: reply ? 'completed' : 'blocked' } });
  return line;
}

test('her last turn is found by surface position, past replaced spans and turns that left nothing on the surface', () => {
  const { session, starts } = realSession(3);
  assert.equal(lastTurnStart(session), starts[2]);
  // A checkpoint written after turn 3's end replaces turns 1-2: its seq is higher than turn 3's, its place earlier.
  const nodes = session.surface.nodes;
  const replaced = session.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'checkpoint' }],
    source: { kind: 'user' } }), { surfaceOp: { op: 'replace', startSeq: nodes[1], endSeq: nodes[4] },
    sourceEventSeqs: nodes.slice(1, 5) }).seq;
  const fourth = closedTurn(session, 4);
  assert.equal(session.surface.nodes[1], replaced);
  assert.ok(replaced > starts[2], 'the surface is not in seq order');
  assert.equal(lastTurnStart(session), fourth, 'not the checkpoint, though its seq is after the turn end before hers');
  // A rejected (or emptied) turn after hers leaves no surface node: hers is still the last turn.
  closedTurn(session, 5, { reply: false });
  assert.equal(lastTurnStart(session), fourth);
  // A system head replaced in her last turn moves to a high seq at place 0; it is not taken for her turn's start.
  const head = session.surface.nodes[0];
  session.append('turn/start', { turn: 6 });
  session.append('system/message', { turn: 6, step: 1, message: createSystemMessage('render 2') },
    { surfaceOp: { op: 'replace', startSeq: head, endSeq: head }, sourceEventSeqs: [head] });
  const sixth = session.append('user/message', createUserMessage({ content: [{ type: 'text', text: '第6句' }],
    source: { kind: 'user' } }), { surfaceOp: 'append' }).seq;
  session.append('turn/end', { turn: 6, reason: { kind: 'completed' } });
  assert.ok(session.surface.nodes[0] > fourth);
  assert.equal(lastTurnStart(session), sixth);
  assert.equal(lastTurnStart(realSession(1).session), undefined, 'one turn: nothing before it');
});

/** RoleCompactionEngine on the installed DSH, its model's stream given by `stream`. */
function realEngine(t, stream) {
  const ctx = new Context();
  new LlmRuntime(ctx); new SessionStore(ctx); new SessionProjectionRegistry(ctx); new TokenMeter(ctx);
  ctx.llm.registerAdapter(['m'], new class extends LlmAdapter {
    resolveModel(provider, id) { return Promise.resolve({ provider, id, name: id, context: { contextWindow: 262144 } }); }
    stream(options) { return stream(options); }
  }());
  ctx.sessions.flush = () => Promise.resolve(false);
  t.after(() => ctx.fiber.dispose());
  return { ctx, engine: new RoleCompactionEngine(ctx, { maxTokens: 24576, auto: false }) };
}

const idleAgent = session => ({ session, options: { provider: 'm', model: 'm' },
  runMaintenance: task => task(new AbortController().signal) });

async function *untilAborted(options) {
  await new Promise((resolve, reject) => {
    if (options.signal.aborted) reject(options.signal.reason);
    options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
  });
  yield { type: 'finish', reason: { kind: 'stop' } };
}

async function *checkpoint() {
  yield { type: 'text-delta', index: 0, text: CHECKPOINT };
  yield { type: 'finish', reason: { kind: 'stop' } };
}

test('an aborted turn-end compaction closes DSH\'s compaction and leaves the conversation as it was', async t => {
  const { engine } = realEngine(t, untilAborted);
  const preempted = () => {
    const own = new AbortController();
    setTimeout(() => own.abort(new Error('her turn')), 5);
    return own.signal;
  };
  for (const signal of [preempted, () => AbortSignal.timeout(5)]) {
    const { session } = realSession(3);
    const surface = [...session.surface.nodes];
    const done = await engine.compactTurnEnd(idleAgent(session), signal());
    assert.equal(done.compacted, false);
    assert.equal(done.code, 'aborted');
    const events = session.snapshotEvents();
    assert.equal(compactionOpen(events), false, 'its compaction/start has its compaction/end');
    assert.equal(events.filter(event => event.type === 'compaction/start').length, 1);
    assert.ok(events.findLast(event => event.type === 'compaction/end').data.error, 'the end says it failed');
    assert.deepEqual(session.surface.nodes, surface, 'nothing replaced: the next turn end tries again');
  }
});

test('a turn-end compaction says whether her turn sits right after the checkpoint, also when the abort came after it committed', async t => {
  const { ctx, engine } = realEngine(t, checkpoint);
  // The installed DSH keeps only the last message (it takes no keepFrom): the check sees her turn was not kept.
  let { session } = realSession(3);
  const done = await engine.compactTurnEnd(idleAgent(session), new AbortController().signal);
  assert.equal(done.compacted, true);
  assert.equal(done.keptTurn, false);
  assert.equal(compactionOpen(session.snapshotEvents()), false);
  // A last turn of one node (her line, the request failed) is its last message, which that DSH keeps: kept.
  ({ session } = realSession(2));
  session.append('turn/start', { turn: 3 });
  session.append('user/message', createUserMessage({ content: [{ type: 'text', text: '第3句' }], source: { kind: 'user' } }),
    { surfaceOp: 'append' });
  session.append('turn/end', { turn: 3, reason: { kind: 'error', error: { message: 'down', code: 'UNKNOWN' } } });
  assert.equal((await engine.compactTurnEnd(idleAgent(session), new AbortController().signal)).keptTurn, true);
  // An abort during the durability flush comes after the commit: it is reported as compacted.
  ({ session } = realSession(3));
  const own = new AbortController();
  ctx.sessions.flush = () => { own.abort(new Error('her turn')); return Promise.resolve(false); };
  const late = await engine.compactTurnEnd(idleAgent(session), own.signal);
  assert.deepEqual([late.compacted, late.code, late.keptTurn], [true, 'aborted', false]);
});

/** A turn-end engine stand-in: due at 100 tokens, keeps turns, its compaction `compact(signal)`. */
function turnEndEngine(compact) {
  return { turnEndTokens: async () => 100, keepsTurns: () => true, compactTurnEnd: (agent, signal) => compact(signal) };
}

const recording = logged => ({ logger: { info: line => logged.push(['info', line]), warn: line => logged.push(['warn', line]) } });

test('her turn takes precedence over a turn-end compaction, which also stops at its deadline', async () => {
  const logged = [];
  const ends = new TurnEnds(recording(logged), 50);
  const agent = { session: { id: 'asuna-role-1' } };
  const meter = { measure: () => ({ totalTokens: 120 }) };
  let seen;
  const waits = turnEndEngine(signal => new Promise(resolve => {
    seen = signal;
    signal.addEventListener('abort', () => resolve({ compacted: false, code: 'aborted', reason: 'x' }), { once: true });
  }));
  const running = ends.run({ agent, engine: waits, meter, idle: () => true });
  await new Promise(resolve => setImmediate(resolve));
  const started = ends.begin('asuna-role-1');
  assert.equal(seen.aborted, true, 'her stage stops the running summary at once');
  await running;
  assert.match(logged.at(-1)[1], /stopped, nothing changed \(her turn came first\)/);
  // While her stage is being started there, no turn-end compaction begins.
  assert.equal((await ends.run({ agent, engine: waits, meter, idle: () => true })).skipped, 'busy');
  started();
  started();
  const timed = await ends.run({ agent, engine: waits, meter, idle: () => true });
  assert.equal(timed.result.code, 'aborted');
  assert.match(logged.at(-1)[1], /stopped, nothing changed \(over its 0\.05 s deadline\)/);
  assert.equal(ends.running.size, 0);
});

test('a turn-end compaction that did not commit cleanly stops them in its conversation; a turn not kept stops them all', async () => {
  const logged = [];
  const ends = new TurnEnds(recording(logged));
  const meter = { measure: () => ({ totalTokens: 120 }) };
  const one = { session: { id: 'asuna-role-1' } }, two = { session: { id: 'asuna-role-2' } };
  let answer = { compacted: false, code: 'commit', reason: 'manual compaction did not commit cleanly: append refused' };
  let calls = 0;
  const engine = turnEndEngine(async () => { calls++; return answer; });
  await ends.run({ agent: one, engine, meter, idle: () => true });
  assert.equal(logged.at(-1)[0], 'warn');
  assert.match(logged.at(-1)[1],
    /did not commit cleanly; none here until the conversation is opened again \(manual compaction did not commit cleanly: append refused\)/);
  assert.equal(await ends.run({ agent: one, engine, meter, idle: () => true }), undefined);
  assert.equal(calls, 1, 'not again in that conversation');
  await ends.run({ agent: { session: { id: 'asuna-role-1' } }, engine, meter, idle: () => true });
  assert.equal(calls, 2, 'opened again (a new agent): compacted again');
  answer = { compacted: true, code: 'persistence', reason: 'manual compaction durability checkpoint failed: disk full', keptTurn: true };
  await ends.run({ agent: two, engine, meter, idle: () => true });
  assert.equal(logged.at(-1)[0], 'warn');
  assert.match(logged.at(-1)[1], /compacted, but not yet written to disk \(manual compaction durability/);
  answer = { compacted: true, items: 9, tokens: 1, keptTurn: false };
  await ends.run({ agent: two, engine, meter, idle: () => true });
  assert.equal(logged.at(-1)[0], 'warn');
  assert.match(logged.at(-1)[1], /her last turn is not right after the checkpoint.*off until this Host restarts/);
  const before = calls;
  assert.equal(await ends.run({ agent: { session: { id: 'asuna-role-3' } }, engine, meter, idle: () => true }), undefined);
  assert.equal(calls, before, 'off for every conversation on this run');
});
