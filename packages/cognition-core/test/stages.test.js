// Use the installed DSH assembler. React/DOM rendering is exercised separately
// in native Web; only unused visual imports are stubbed in this Node test.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import * as cordis from '@deepseek-ai/cordis';
const require = createRequire(import.meta.url);
const modules = {
  react: { memo: fn => fn, forwardRef: fn => fn, createContext: () => ({}), Component: class {} },
  'react/jsx-runtime': {}, 'react-dom': {}, '@deepseek-ai/cordis': cordis,
  '@deepseek-ai/dsh-client-ui-primitives': {}, '@deepseek-ai/dsh-client-ui-slots': {},
  '@deepseek-ai/dsh-client-store': { notifySubscribers: listeners => { for (const fn of listeners) fn(); } },
};
async function load(path) {
  let result;
  new Function('window', await fs.readFile(path, 'utf8'))({ __ModuleLoader__: {
    load: ({ factory }) => { result = factory(name => {
      assert.ok(name in modules, 'Unexpected dependency: ' + name); return modules[name];
    }); },
  } });
  return result;
}
const { ConversationNodeAssembler } = await load(require.resolve('@deepseek-ai/dsh-client-ui-conversation/client'));
const { stageDefinitions, collabDefinitions, repairDefinitions, threadOf, subscribeInputPolicies, DICTIONARY } = await load(new URL('../src/client.js', import.meta.url));
const words = (key, params = {}) => DICTIONARY.en[key].replace(/\{(\w+)\}/g, (_, name) => params[name]);

test('cold composer stays blocked until QQ policy resolves, and stale queries cannot block Local', async () => {
  let state, listener;
  const blocks = new Map(), requests = [];
  const ctx = { sessions: { list: { getSnapshot: () => state, subscribe: fn => { listener = fn; return () => {}; } } },
    conversation: { blocks: { storeFor: id => ({ getSnapshot: () => blocks.get(id) }),
      set: (id, block) => { if (block) blocks.set(id, block); else blocks.delete(id); } } } };
  const select = (...ids) => { state = { byId: Object.fromEntries(ids.map(id => [id, { retainedBy: { mainView: 1 } }])) }; listener?.(); };
  const rpc = (_method, args, signal) => new Promise((resolve, reject) => requests.push({ args, signal, resolve, reject }));
  select('qq');
  const dispose = subscribeInputPolicies(ctx, rpc, words);
  assert.ok(blocks.has('qq'), 'loading cannot expose an editable QQ composer');
  assert.equal(blocks.get('qq').reason, words('input.checking'), 'its reason follows the viewer language');
  requests[0].resolve({ qq: { key: 'read_only', platform: 'QQ' } }); await Promise.resolve();
  assert.equal(blocks.get('qq').reason, 'QQ conversations are read-only here; reply in QQ.');
  select('local'); assert.ok(blocks.has('local'));
  select('qq'); assert.equal(requests[1].signal.aborted, true);
  requests[1].resolve({ local: { key: 'internal' } });
  requests[2].resolve({ qq: { key: 'read_only', platform: 'QQ' } }); await Promise.resolve();
  assert.equal(blocks.has('local'), false);
  select('local'); requests[3].resolve({}); await Promise.resolve();
  assert.equal(blocks.has('local'), false, 'ordinary native input resumes after policy resolution');
  select('recovery'); select('recovery', 'another');
  requests.at(-1).reject(new Error('business worker unavailable')); await Promise.resolve(); await Promise.resolve();
  assert.equal(blocks.has('recovery'), false, 'an aborted temporary block cannot strand independent recovery');
  assert.equal(blocks.has('another'), false);
  blocks.set('recovery', { reason: 'another native owner' }); dispose();
  assert.equal(blocks.get('recovery').reason, 'another native owner');
});
const entry = (seq, type, data) => ({ type: type === 'assistant/live-chunk' ? 'transient' : 'event',
  event: { seq, time: 1000 + seq, type, data, ...(type === 'assistant/message' ? { surfaceOp: 'append' } : {}) } });
const source = (phase, lane) => ({ source: { kind: 'asuna', operation: 'operation-' + phase, phase, ...(lane ? { lane } : {}) },
  content: [{ type: 'text', text: 'original model input' }] });
function assembler(definitions = stageDefinitions()) {
  const engine = new ConversationNodeAssembler({ entries: () => definitions, fallbackEntry: () => undefined }, {
    entries: () => [{ target: 'chat', create: () => {
      let nodes = new Map();
      return { empty: { nodes: [], timeline: { turns: new Map() } },
        replace: input => { nodes = new Map(input.nodes.map(node => [node.key, node])); return { ...input, nodes: [...nodes.values()] }; },
        apply: input => { for (const node of input.upserts) nodes.set(node.key, node); return { timeline: input.timeline, nodes: [...nodes.values()] }; },
      };
    } }],
  });
  engine.activateTarget('chat');
  return engine;
}
const snapshot = engine => { engine.flush(); return engine.get('chat'); };

test('a task thread is one node anchored at its first entry, through reload and prepend; replays add nothing', () => {
  const engine = assembler(collabDefinitions());
  const at = '2026-10-05T10:00:00Z';
  const events = [
    entry(1, 'asuna/collab', { id: 'brief:t1', thread: 't1', task_id: 't1', kind: 'message', from: 'character', text: 'check the weather', title: 'weather', at }),
    entry(2, 'turn/start', { turn: 1 }),
    entry(3, 'asuna/collab', { id: 'open:t1', thread: 't1', task_id: 't1', kind: 'open', child_session_id: 'action', parent_session_id: 'role', at }),
    entry(4, 'asuna/collab', { id: 'q:1', thread: 't1', task_id: 't1', kind: 'question', from: 'action', text: 'which city?', at }),
    entry(5, 'asuna/collab', { id: 'brief:t2', thread: 't2', task_id: 't2', kind: 'message', from: 'character', text: 'another', at }),
    entry(6, 'asuna/collab', { id: 'q:1', thread: 't1', task_id: 't1', kind: 'question', from: 'action', text: 'which city?', at }),
  ];
  engine.replaceWindow(events.slice(2), true);
  const partial = snapshot(engine).nodes.find(node => node.id === 't1');
  assert.equal(partial.anchorSeq, 3, 'a partially loaded thread starts at its first loaded entry');
  engine.prepend(events.slice(0, 2), false);
  const rows = snapshot(engine).nodes.toSorted((left, right) => left.anchorSeq - right.anchorSeq);
  assert.deepEqual(rows.map(row => [row.id, row.anchorSeq, row.location.kind]), [['t1', 1, 'session'], ['t2', 5, 'session']]);
  assert.deepEqual(rows[0].data.entries.map(entry => entry.kind), ['message', 'open', 'question'], 'a replayed entry is not shown twice');
  assert.equal(threadOf(rows[0].data.entries).state, 'waiting', 'an unanswered question waits for her');
  assert.equal(threadOf(rows[0].data.entries).title, 'weather');
  assert.equal(threadOf(rows[1].data.entries).state, 'queued');
  const done = [...rows[0].data.entries, { id: 'a:1', kind: 'answer', from: 'character', text: 'here', at },
    { id: 'status:t1:finished', kind: 'status', state: 'done', at }];
  assert.equal(threadOf(done).state, 'done');
  assert.equal(threadOf([...done, { id: 'brief:t1b', kind: 'message', from: 'character', text: 'and tomorrow?', at }]).state, 'queued',
    'her follow-up to a finished task queues it again');
});

test('each block of a thread is its own node where it happened; an earlier one reads as continued below', () => {
  const engine = assembler(collabDefinitions());
  const at = '2026-10-05T10:00:00Z', later = '2026-10-05T10:05:00Z';
  const c = (seq, data) => entry(seq, 'asuna/collab', { thread: 't1', task_id: 't1', at, ...data });
  engine.replaceWindow([
    c(1, { id: 'brief:t1', block: 'block:brief:t1', kind: 'message', from: 'character', text: 'clean up', title: 'skills' }),
    c(2, { id: 'open:t1:0', block: 'block:brief:t1', kind: 'open', child_session_id: 'action', after_seq: 0 }),
    entry(3, 'turn/start', { turn: 2 }),
    c(4, { id: 'continued:block:brief:t1:block:m1', block: 'block:brief:t1', kind: 'continued', next: 'block:m1' }),
    c(5, { id: 'open:block:m1', block: 'block:m1', kind: 'open', child_session_id: 'action', after_seq: 0, title: 'skills' }),
    c(6, { id: 'work:t1:9', block: 'block:m1', kind: 'work', child_session_id: 'action', after_seq: 0, through_seq: 9,
      tool_calls: 4, at: later }),
    c(7, { id: 'm1', block: 'block:m1', kind: 'message', from: 'character', text: 'and the adapter docs', title: 'skills' }),
  ], false);
  const rows = snapshot(engine).nodes.toSorted((left, right) => left.anchorSeq - right.anchorSeq);
  assert.deepEqual(rows.map(row => [row.id, row.anchorSeq]), [['block:brief:t1', 1], ['block:m1', 5]]);
  const [earlier, current] = rows.map(row => threadOf(row.data.entries));
  assert.equal(earlier.state, 'continued');
  assert.equal(earlier.live, null, 'the work goes on below, not here');
  assert.equal(current.state, 'running');
  assert.deepEqual(current.live, { child: 'action', after: 9, since: Date.parse(later) }, 'live after the last work row');
  assert.equal(current.title, 'skills');
  assert.equal(threadOf([...rows[1].data.entries, { id: 's', kind: 'status', state: 'done', at }]).live, null);
  assert.equal(words('collab.state.continued'), 'Continued below');
});

test('the program sending her final text back shows between the draft and the rewrite, never folded away', () => {
  const note = { source: { kind: 'asuna', operation: 'ep:TURN:fix-1', lane: 'character', phase: 'REPAIR' },
    content: [{ type: 'text', text: 'what you wrote last is sent as is; it mentioned the program' }] };
  const events = [entry(0, 'turn/start', { turn: 1 }), entry(1, 'user/message', source('TURN', 'character')),
    entry(2, 'step/start', { turn: 1, step: 1 }), entry(3, 'assistant/message', { turn: 1, step: 1 }),
    entry(4, 'step/end', { turn: 1, step: 1 }), entry(5, 'user/message', note),
    entry(6, 'step/start', { turn: 1, step: 2 }), entry(7, 'assistant/message', { turn: 1, step: 2 }),
    entry(8, 'step/end', { turn: 1, step: 2 }), entry(9, 'turn/end', { turn: 1, reason: { kind: 'completed' } })];
  const engine = assembler(repairDefinitions());
  engine.replaceWindow(events, false);
  const rows = snapshot(engine).nodes;
  assert.equal(rows.length, 1, 'only the note that sends a draft back is drawn, not the turn notice');
  assert.equal(rows[0].kind, 'asuna-repair');
  assert.equal(rows[0].anchorSeq, 5, 'between the rejected draft (3) and the rewrite (7)');
  assert.equal(rows[0].location.kind, 'session', 'DSH would group a Turn row into the next reasoning and hide it');
  assert.equal(rows[0].data.text, 'what you wrote last is sent as is; it mentioned the program');
  engine.replaceWindow(events, false);
  assert.equal(snapshot(engine).nodes.length, 1, 'a reload draws it once');
});

const said = text => ({ role: 'assistant', content: [{ type: 'text', text }] });
const called = name => ({ role: 'assistant', content: [{ type: 'tool-call', id: name, name, arguments: '{}' }] });

test('a Turn that ends in a tool shows no brain label: its folded process stands alone', () => {
  const engine = assembler();
  engine.replaceWindow([entry(0, 'turn/start', { turn: 1 }), entry(1, 'step/start', { turn: 1, step: 1 }),
    entry(2, 'asuna/stage', { turn: 1, step: 1, lane: 'character', phase: 'CONSULT' }),
    entry(3, 'assistant/message', { turn: 1, step: 1, message: called('think') }),
    entry(4, 'assistant/message', { turn: 1, step: 2, message: called('answer_action') }),
    entry(5, 'turn/end', { turn: 1, reason: { kind: 'completed' } })], false);
  assert.equal(snapshot(engine).nodes.length, 0, 'her answer to the action brain shows in the thread, not as an empty label');
});

test('explicit lane attribution exists before tokens and survives native stream settlement', () => {
  const engine = assembler();
  for (const event of [entry(0, 'turn/start', { turn: 1 }), entry(1, 'step/start', { turn: 1, step: 1 }),
    entry(2, 'asuna/stage', { turn: 1, step: 1, lane: 'executor', phase: 'execution', operation: 'task:0' })]) engine.append(event);
  assert.equal(snapshot(engine).timeline.turns.get(1).steps[0].data.get('asuna-stage').lane, 'executor');
  engine.append(entry(2.1, 'assistant/live-chunk', { turn: 1, step: 1, attemptId: 'attempt',
    chunk: { type: 'reasoning-delta', index: 0, text: 'native private analysis' } }));
  assert.equal(snapshot(engine).nodes.length, 0, 'thinking alone shows no brain label yet');
  engine.append(entry(2.2, 'assistant/live-chunk', { turn: 1, step: 1, attemptId: 'attempt',
    chunk: { type: 'text-delta', index: 1, text: 'report' } }));
  const streamed = snapshot(engine).nodes[0];
  assert.equal(streamed.location.kind, 'session');
  assert.doesNotMatch(JSON.stringify(streamed.data), /private analysis/);
  engine.settleAssistant('attempt', entry(3, 'assistant/message', { turn: 1, step: 1, message: said('report') }));
  const settled = snapshot(engine).nodes;
  assert.equal(settled.length, 1);
  assert.equal(settled[0].key, streamed.key, 'settlement does not duplicate the business marker');
  assert.deepEqual(settled[0].data, streamed.data);
});

test('one visible brain identity survives multiple phases and a partial native Turn', () => {
  const events = [entry(0, 'turn/start', { turn: 1 }), entry(1, 'step/start', { turn: 1, step: 1 }),
    entry(2, 'asuna/stage', { turn: 1, step: 1, lane: 'character', phase: 'MONOLOGUE' }),
    entry(3, 'user/message', source('MONOLOGUE', 'character')),
    entry(4, 'assistant/message', { turn: 1, step: 1 }), entry(5, 'step/end', { turn: 1, step: 1 }),
    entry(6, 'step/start', { turn: 1, step: 2 }),
    entry(7, 'asuna/stage', { turn: 1, step: 2, lane: 'character', phase: 'DECIDE' }),
    entry(8, 'assistant/message', { turn: 1, step: 2, message: said('hello') }), entry(9, 'step/end', { turn: 1, step: 2 }),
    entry(10, 'turn/end', { turn: 1, reason: { kind: 'completed' } })];
  const engine = assembler();
  engine.replaceWindow(events, false);
  const full = snapshot(engine);
  assert.equal(full.nodes.length, 1, 'phases/tool followups never repeat the existing Pill');
  assert.equal(full.nodes[0].location.kind, 'session', 'native folding must not hide identity');
  assert.ok(full.nodes[0].anchorSeq > 3 && full.nodes[0].anchorSeq < 4, 'identity follows input and precedes response');
  assert.deepEqual(full.timeline.turns.get(1).steps.map(step => step.data.get('asuna-stage').phase), ['MONOLOGUE', 'DECIDE']);
  engine.replaceWindow(events.slice(6), true);
  assert.equal(snapshot(engine).nodes.length, 1, 'loaded explicit attribution works without step one');
  assert.equal(snapshot(engine).nodes[0].data.lane, 'character');
  engine.prepend(events.slice(0, 6), false);
  assert.deepEqual(snapshot(engine).nodes.map(node => [node.key, node.anchorSeq, node.data]),
    full.nodes.map(node => [node.key, node.anchorSeq, node.data]), 'loading earlier records relocates one identity, without a copy');
});

test('a Turn whose cut-off stage was retried and finished records that its last stage finished', () => {
  const result = (seq, step, finish) => entry(seq, 'asuna/stage-result', { turn: 1, step, lane: 'character',
    phase: 'DECIDE', operation: 'decide', finish_reason: finish });
  const events = [entry(0, 'turn/start', { turn: 1 }), entry(1, 'step/start', { turn: 1, step: 1 }),
    entry(2, 'asuna/stage', { turn: 1, step: 1, lane: 'character', phase: 'DECIDE' }),
    entry(3, 'assistant/message', { turn: 1, step: 1 }), entry(4, 'step/end', { turn: 1, step: 1 }),
    result(5, 1, 'length'), entry(6, 'step/start', { turn: 1, step: 2 }),
    entry(7, 'asuna/stage', { turn: 1, step: 2, lane: 'character', phase: 'DECIDE' }),
    entry(8, 'assistant/message', { turn: 1, step: 2 }), entry(9, 'step/end', { turn: 1, step: 2 })];
  const engine = assembler();
  engine.replaceWindow(events, false);
  assert.equal(snapshot(engine).timeline.turns.get(1).data.get('asuna-stage-finish'), 'length',
    'until the retry finishes the Turn really is cut off');
  engine.append(result(10, 2, 'stop'));
  engine.append(entry(11, 'turn/end', { turn: 1, reason: { kind: 'max-tokens' } }));
  assert.equal(snapshot(engine).timeline.turns.get(1).data.get('asuna-stage-finish'), 'stop',
    'DSH still ends the Turn at max-tokens; the retried stage finished');
});

test('a finished run reads where its result stands: handing, taken by her, or never reached her', () => {
  const at = '2026-10-09T00:00:00Z';
  const run = [{ id: 'brief', kind: 'message', from: 'character', text: 'look it up', title: 'lookup', at },
    { id: 'open', kind: 'open', child_session_id: 'action', after_seq: 0, at },
    { id: 'done', kind: 'status', state: 'done', at }];
  const hb = (state, extra = {}) => ({ id: 'handback:' + state, kind: 'handback', state, at, ...extra });
  assert.equal(threadOf(run).handback, null, 'no hand-back entry: the run reads as before');
  assert.equal(threadOf([...run, hb('handing')]).handback.state, 'handing');
  assert.equal(threadOf([...run, hb('handing'), hb('taken')]).handback.state, 'taken');
  const missed = threadOf([...run, hb('handing'), hb('missed', { cause: 'report', error: 'TypeError' })]);
  assert.equal(missed.handback.cause, 'report');
  assert.equal(missed.outcome, 'done');
  const paused = threadOf([...run, { id: 'paused', kind: 'status', state: 'paused', at }, hb('missed', { cause: 'restart' })]);
  assert.equal(paused.handback.cause, 'restart', 'a finished run paused at a restart is waiting only on its hand-back');
  assert.equal(threadOf([...run, hb('taken'), { id: 'more', kind: 'message', from: 'character', text: 'and more', at }]).handback,
    null, 'her follow-up queues the thread again');
  assert.equal(words('collab.handback.missed', { outcome: words('collab.outcome.done') }), 'Done · Never reached her');
  // Her conversation moved to a new session after the run: the hand-back stands in a block of its own.
  const alone = threadOf([hb('handing', { outcome: 'done' }), hb('taken', { outcome: 'done' })]);
  assert.equal(alone.state, 'done', 'not queued: the run had finished');
  assert.equal(alone.handback.state, 'taken');
  assert.equal(alone.elapsed, null, 'no run time: the run is not in this block');
  assert.equal(threadOf([hb('taken', { outcome: 'failed' })]).outcome, 'failed');
});

test('every UI language has the same words with the same placeholders', () => {
  const shape = table => Object.fromEntries(Object.entries(table).map(([key, text]) =>
    [key, [...String(text).matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort().join(',')]));
  const [first, ...others] = Object.keys(DICTIONARY);
  for (const language of others) assert.deepEqual(shape(DICTIONARY[language]), shape(DICTIONARY[first]), language + ' vs ' + first);
});
