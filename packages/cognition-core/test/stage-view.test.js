// A stage's speech is every text she wrote in it; a platform line belongs to the first stage that had it in view.
import test from 'node:test';
import assert from 'node:assert/strict';
import { stageView } from '../src/index.js';

let seq = 0;
const ev = (type, data) => ({ type, seq: seq++, data });
const line = id => ev('user/message', { source: { kind: 'user', channel: 'qq', receipt: id }, content: [] });
const said = (turn, text, call) => ev('assistant/message', { turn, message: { content: [
  ...(text ? [{ type: 'text', text }] : []), ...(call ? [{ type: 'tool-call', name: call }] : [])] } });

test('the turn that had a line in view answers for it, and every text it wrote is said', () => {
  seq = 0;
  const events = [
    line('in-ep-old'), ev('asuna/stage', { operation: 'prev:TURN' }), said(4, '上一回合'),
    line('in-ep-1'), ev('turn/start', { turn: 5 }), ev('asuna/stage', { operation: 'ep-1:TURN' }),
    line('in-ep-x'),                                         // arrived while the first request was out
    ev('asuna/stage', { operation: 'ep-1:TURN' }), said(5, '', 'think'),
    ev('asuna/stage', { operation: 'ep-1:TURN' }),
    line('in-ep-2'),                                         // arrived during step 2: seen by step 3
    said(5, '那必须的，被夸了我会更来劲。', 'feel'),
    ev('asuna/stage', { operation: 'ep-1:TURN' }), said(5, '他教没教我不好说。'),
    line('in-ep-3'),                                         // after her last request: not seen by this turn
  ];
  const view = stageView(events, 'ep-1:TURN', 5);
  assert.deepEqual(view.said, ['那必须的，被夸了我会更来劲。', '他教没教我不好说。']);
  assert.deepEqual(view.seen_inputs, ['in-ep-1', 'in-ep-x', 'in-ep-2']);
});

test('a program note in the same turn is its own stage: only its own text, only lines new to it', () => {
  seq = 0;
  const events = [
    ev('turn/start', { turn: 1 }), ev('asuna/stage', { operation: 'ep:TURN' }), said(1, '{"a":1}'),
    line('in-late'), ev('asuna/stage', { operation: 'ep:TURN:fix-1' }), said(1, '好的，我换个说法。'),
  ];
  assert.deepEqual(stageView(events, 'ep:TURN:fix-1', 1), { said: ['好的，我换个说法。'], seen_inputs: ['in-late'] });
});

test('an answer the model wrote again around reasoning markup is read once, and the stage says so', () => {
  seq = 0;
  const events = [ev('turn/start', { turn: 1 }), ev('asuna/stage', { operation: 'ep:TURN' }),
    said(1, '明天见\n</think>\n\n明天见')];
  assert.deepEqual(stageView(events, 'ep:TURN', 1), { said: ['明天见'], seen_inputs: [], corrected: true });
});
