import test from 'node:test';
import assert from 'node:assert/strict';
import { thinkingOf, firstThinking } from '../src/index.js';

// ADR-099: in thinking mode the plugin hands the model's own thinking with her first call of a stage.
const message = (blocks, replay) => ({ content: blocks, source: { replayState: { blocks: replay } } });
const call = id => ({ type: 'tool-call', id, name: 'speak', arguments: '{}' });

test('thinking is the reasoning blocks that are neither redacted nor empty', () => {
  const kept = message([{ type: 'reasoning', text: ' 先想想 ' }, { type: 'reasoning', text: '[Reasoning redacted]' },
    { type: 'reasoning', text: '  ' }, { type: 'text', text: '好' }],
  [{ type: 'reasoning' }, { type: 'reasoning', redacted: true }, { type: 'reasoning' }, { type: 'text' }]);
  assert.deepEqual(thinkingOf(kept), { text: '先想想', redacted: true });
  assert.deepEqual(thinkingOf(undefined), { text: '', redacted: false });
});

test('only the first call of a stage without think, not a repair, carries it', () => {
  const events = [{ type: 'assistant/message', data: { message: message([{ type: 'reasoning', text: '想' }, call('a'), call('b')],
    [{ type: 'reasoning' }, { type: 'tool-call' }, { type: 'tool-call' }]) } }];
  const session = { snapshotEvents: () => events };
  const state = { current: { tools: ['recall', 'speak'] } };
  assert.deepEqual(firstThinking(session, state, 'ep:TURN', 'a'), { text: '想', redacted: false });
  assert.equal(firstThinking(session, state, 'ep:TURN', 'b'), undefined, 'once a stage');
  assert.deepEqual(firstThinking(session, state, 'ep:TURN:resume:1', 'b'), { text: '想', redacted: false });
  assert.equal(firstThinking(session, { current: { tools: ['recall'] } }, 'ep:TURN:fix-1', 'a'), undefined, 'a repair');
  assert.equal(firstThinking(session, { current: { tools: ['think', 'recall'] } }, 'ep:TURN', 'a'), undefined, 'tool mode');
});
