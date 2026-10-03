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
const { stageDefinitions } = await load(new URL('../src/client.js', import.meta.url));
const entry = (seq, type, data) => ({ type: type === 'assistant/live-chunk' ? 'transient' : 'event',
  event: { seq, time: 1000 + seq, type, data, ...(type === 'assistant/message' ? { surfaceOp: 'append' } : {}) } });
const source = (phase, lane) => ({ source: { kind: 'asuna', operation: 'operation-' + phase, phase, ...(lane ? { lane } : {}) },
  content: [{ type: 'text', text: 'original model input' }] });
function assembler() {
  const definitions = stageDefinitions();
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
  assert.equal(restored.nodes[0].location.kind, 'step');
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
  assert.equal(streamed.location.kind, 'step');
  assert.doesNotMatch(JSON.stringify(streamed.data), /private analysis/);
  engine.settleAssistant('attempt', entry(3, 'assistant/message', { turn: 1, step: 1 }));
  const settled = snapshot(engine).nodes;
  assert.equal(settled.length, 1);
  assert.equal(settled[0].key, streamed.key, 'settlement does not duplicate the business marker');
  assert.deepEqual(settled[0].data, streamed.data);
});
