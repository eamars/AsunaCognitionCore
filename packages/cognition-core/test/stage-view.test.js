// A stage's speech is every text she wrote in it; a platform line belongs to the first stage that had it in view.
import test from 'node:test';
import assert from 'node:assert/strict';
import { stageView, writtenSoFar } from '../src/index.js';

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

test('silence says what the turn has written so far, the message holding the stay_silent call included', () => {
  seq = 0;
  const session = events => ({ snapshotEvents: () => events });
  const start = [ev('turn/start', { turn: 2 }), ev('asuna/stage', { operation: 'ep:TURN' }), said(2, '', 'think')];
  assert.equal(writtenSoFar(session([...start, said(2, '', 'stay_silent')]), 'ep:TURN'),
    '这一回合正文里一个字都没写，什么都不会发出去。');
  assert.equal(writtenSoFar(session([...start, said(2, '加油哦', 'plan'), said(2, '晚点再来', 'stay_silent')]), 'ep:TURN'),
    '这一回合正文里写了 2 段话，回合结束时照常发出。');
});

test('ADR-119 F11: silence after a body the check sent back says that body is unsent, never "nothing written"', () => {
  seq = 0;
  const session = events => ({ snapshotEvents: () => events });
  const refused = '我先回你一句：今天这件可以装，窗口就是现在，别等我了好吗，我手上没有在跑的件，二十三点那本账随时能挪。';
  const events = [ev('turn/start', { turn: 3 }), ev('asuna/stage', { operation: 'ep:TURN' }), said(3, refused),
    ev('asuna/stage', { operation: 'ep:TURN:fix-1' }), said(3, '', 'think'), said(3, '', 'stay_silent')];
  const words = writtenSoFar(session(events), 'ep:TURN:fix-1');
  assert.ok(words.startsWith('这一步正文里没写字。这一回合前面那段被打回了、还没发出去'), words);
  assert.ok(words.includes('「' + refused.slice(0, 40) + '…」'), words);
  // Written again in the repair stage: that goes out, and it is counted.
  assert.equal(writtenSoFar(session([...events.slice(0, 4), said(3, '重写的这段'), said(3, '', 'stay_silent')]), 'ep:TURN:fix-1'),
    '这一回合正文里写了 1 段话，回合结束时照常发出。');
});
