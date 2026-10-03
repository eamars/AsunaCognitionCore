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
const { stageDefinitions, actionDefinitions, subscribeInputPolicies } = await load(new URL('../src/client.js', import.meta.url));

test('cold composer stays blocked until QQ policy resolves, and stale queries cannot block Local', async () => {
  let state, listener;
  const blocks = new Map(), requests = [];
  const ctx = { sessions: { list: { getSnapshot: () => state, subscribe: fn => { listener = fn; return () => {}; } } },
    conversation: { blocks: { storeFor: id => ({ getSnapshot: () => blocks.get(id) }),
      set: (id, block) => { if (block) blocks.set(id, block); else blocks.delete(id); } } } };
  const select = (...ids) => { state = { byId: Object.fromEntries(ids.map(id => [id, { retainedBy: { mainView: 1 } }])) }; listener?.(); };
  const rpc = (_method, args, signal) => new Promise((resolve, reject) => requests.push({ args, signal, resolve, reject }));
  select('qq');
  const dispose = subscribeInputPolicies(ctx, rpc);
  assert.ok(blocks.has('qq'), 'loading cannot expose an editable QQ composer');
  requests[0].resolve({ qq: 'view-only' }); await Promise.resolve();
  assert.equal(blocks.get('qq').reason, 'view-only');
  select('local'); assert.ok(blocks.has('local'));
  select('qq'); assert.equal(requests[1].signal.aborted, true);
  requests[1].resolve({ local: 'late wrong policy' });
  requests[2].resolve({ qq: 'view-only' }); await Promise.resolve();
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

test('native action ranges retain their source and placement through consultation, reload and prepend', () => {
  const engine = assembler(actionDefinitions());
  const events = [
    entry(1, 'asuna/action-linked', { segment_id: 'first', session_id: 'action', parent_session_id: 'role', after_seq: -1 }),
    entry(2, 'asuna/action-range', { segment_id: 'first', session_id: 'action', through_seq: 12, state: 'paused' }),
    entry(3, 'turn/start', { turn: 1 }), entry(4, 'step/start', { turn: 1, step: 1 }),
    entry(5, 'assistant/message', { turn: 1, step: 1 }),
    entry(6, 'asuna/action-linked', { segment_id: 'second', session_id: 'action', parent_session_id: 'role', after_seq: 12 }),
    entry(7, 'asuna/action-range', { segment_id: 'second', session_id: 'action', through_seq: 24, state: 'completed' }),
  ];
  engine.replaceWindow(events.slice(1), true);
  assert.ok(snapshot(engine).nodes.every(node => node.id !== 'first'), 'a range without its link is not a fabricated source');
  engine.prepend(events.slice(0, 1), false);
  const rows = snapshot(engine).nodes.toSorted((left, right) => left.anchorSeq - right.anchorSeq);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(row => [row.id, row.anchorSeq, row.data.after_seq, row.data.through_seq]),
    [['first', 1, -1, 12], ['second', 6, 12, 24]]);
  assert.ok(rows.every(row => row.location.kind === 'session' && row.data.session_id === 'action'));
  engine.replaceWindow(events, false);
  assert.deepEqual(snapshot(engine).nodes.toSorted((left, right) => left.anchorSeq - right.anchorSeq).map(row => row.data), rows.map(row => row.data));
});

test('legacy phase notices after step start survive cold replay and older-page prepend', () => {
  const events = [entry(0, 'turn/start', { turn: 1 }), entry(1, 'step/start', { turn: 1, step: 1 }),
    entry(2, 'user/message', source('MONOLOGUE')), entry(3, 'assistant/message', { turn: 1, step: 1 }),
    entry(4, 'step/end', { turn: 1, step: 1 }), entry(5, 'turn/end', { turn: 1, reason: { kind: 'completed' } })];
  const engine = assembler();
  engine.replaceWindow(events.slice(3), true);
  assert.equal(snapshot(engine).nodes.length, 0, 'no guessing when attribution is outside the loaded window');
  engine.prepend(events.slice(0, 3), false);
  const restored = snapshot(engine);
  assert.equal(restored.nodes.length, 1);
  assert.equal(restored.nodes[0].data.phase, 'MONOLOGUE');
  assert.equal(restored.nodes[0].location.kind, 'session', 'brain identity stays outside native process folding');
  assert.equal(restored.timeline.turns.get(1).steps[0].data.get('asuna-stage').lane, 'character');
  engine.replaceWindow(events, false);
  assert.deepEqual(snapshot(engine).nodes.map(node => node.data), restored.nodes.map(node => node.data));
  for (const event of [entry(6, 'turn/start', { turn: 2 }), entry(7, 'step/start', { turn: 2, step: 1 }),
    entry(8, 'user/message', { source: { kind: 'user' } }), entry(9, 'assistant/message', { turn: 2, step: 1 })]) engine.append(event);
  assert.equal(snapshot(engine).nodes.length, 1, 'ordinary native turns never inherit a previous Asuna label');
});

test('explicit lane attribution exists before tokens and survives native stream settlement', () => {
  const engine = assembler();
  for (const event of [entry(0, 'turn/start', { turn: 1 }), entry(1, 'step/start', { turn: 1, step: 1 }),
    entry(2, 'asuna/stage', { turn: 1, step: 1, lane: 'executor', phase: 'execution', operation: 'task:0' })]) engine.append(event);
  assert.equal(snapshot(engine).timeline.turns.get(1).steps[0].data.get('asuna-stage').lane, 'executor');
  engine.append(entry(2.1, 'assistant/live-chunk', { turn: 1, step: 1, attemptId: 'attempt',
    chunk: { type: 'reasoning-delta', index: 0, text: 'native private analysis' } }));
  const streamed = snapshot(engine).nodes[0];
  assert.equal(streamed.location.kind, 'session');
  assert.doesNotMatch(JSON.stringify(streamed.data), /private analysis/);
  engine.settleAssistant('attempt', entry(3, 'assistant/message', { turn: 1, step: 1 }));
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
    entry(8, 'assistant/message', { turn: 1, step: 2 }), entry(9, 'step/end', { turn: 1, step: 2 }),
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
