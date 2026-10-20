import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import { CONTEXT_WINDOW_EXCEEDED_CODE } from '@deepseek-ai/dsh-llm';
import RoleCompactionEngine, { ROLE_COMPACTION_INSTRUCTION, ROLE_SECTIONS, hasSections, inSteps } from '../src/compaction.js';

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
test('role compaction sends the whole conversation and names the kept tail, or the span alone when it would not fit', async () => {
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
