// A model's reasoning markup in her text, or a copied reasoning, is corrected in what she says and in what the
// model sees afterwards; the session log keeps what the model wrote.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Session } from '@deepseek-ai/dsh-session';
import { cleanMessage, cleanText, correctModelFaults, modelFaultProjection, MODEL_FAULT } from '../src/model-fault.js';
import { ASUNA_EVENTS } from '../src/persistence.js';

const REASONING = '她问的是周末去哪里，我想先确认她有没有空，再说我自己的想法。';

test('her text is the last segment between think-like tags; a closed think block is dropped', () => {
  assert.equal(cleanText('明天见～'), '明天见～');
  assert.equal(cleanText('明天见～\n</think>'), '明天见～');
  assert.equal(cleanText('好呀\n</think>\n\n好呀'), '好呀');
  assert.equal(cleanText(Array(6).fill('嗯嗯').join('\n</next_thinking>\n')), '嗯嗯');
  assert.equal(cleanText('先想想她的意思……</think>那就周六吧'), '那就周六吧');
  assert.equal(cleanText('<think>她在开玩笑</think>\n哈哈，被你发现了'), '哈哈，被你发现了');
  assert.equal(cleanText('<think>只有思考</think>'), '');
  const message = { role: 'assistant', content: [{ type: 'text', text: '晚安' }] };
  assert.equal(cleanMessage(message), message);
});

function session() {
  const s = Session.create('asuna-role-test', undefined, undefined, undefined, [modelFaultProjection]);
  let id = 0;
  const user = text => s.append('user/message', { id: 'm' + id++, role: 'user', source: { kind: 'user' },
    content: [{ type: 'text', text }] }, { surfaceOp: 'append' });
  const said = (text, reasoning = REASONING) => s.append('assistant/message', { turn: 1, step: 1, stream: [], message: {
    id: 'm' + id++, role: 'assistant', source: { kind: 'model', provider: 'fixture', model: 'fixture' },
    content: [{ type: 'reasoning', text: reasoning }, { type: 'text', text }] } }, { surfaceOp: 'append' });
  return { s, user, said };
}

test('a faulty message reaches the model corrected from the next request on; the log keeps it', () => {
  const { s, user, said } = session();
  user('周末去哪？');
  const fine = said('去海边吧', '想一想她喜欢什么地方，海边她上次提过，应该会喜欢的，就这么回答她。');
  user('好呀');
  const leaked = said('那就这么定了\n</think>\n\n那就这么定了');
  const corrected = correctModelFaults(s);
  assert.deepEqual(corrected, [{ seq: leaked.seq, texts: ['那就这么定了'] }]);
  assert.equal(s.deriveEventMessage(s.eventAt(fine.seq)), fine.data.message);
  assert.deepEqual(s.deriveEventMessage(s.eventAt(leaked.seq)).content,
    [{ type: 'reasoning', text: REASONING }, { type: 'text', text: '那就这么定了' }]);
  assert.equal(s.eventAt(leaked.seq).data.message.content[1].text, '那就这么定了\n</think>\n\n那就这么定了');
  // The next message copied the reasoning before it: the model sees it without that reasoning.
  user('几点？');
  const copied = said('十点？', REASONING);
  assert.deepEqual(correctModelFaults(s), [{ seq: copied.seq, texts: ['十点？'], reasoning: false }]);
  assert.deepEqual(s.deriveEventMessage(s.eventAt(copied.seq)).content,
    [{ type: 'reasoning', text: '' }, { type: 'text', text: '十点？' }]);
  assert.deepEqual(correctModelFaults(s), [], 'each message is read once');
});

test('a resumed conversation replays its corrections and is not corrected again', () => {
  const { s, user, said } = session();
  user('在吗');
  said('在的\n</think>');
  correctModelFaults(s);
  const stored = s.snapshotEvents().map(event => ASUNA_EVENTS.has(event.type) ? { ...event, ignorable: true } : event);
  const resumed = Session.create('asuna-role-test', stored, undefined, undefined, [modelFaultProjection]);
  assert.equal(resumed.deriveEventMessage(resumed.eventAt(1)).content[1].text, '在的');
  assert.deepEqual(correctModelFaults(resumed), []);
  assert.equal(stored.filter(event => event.type === MODEL_FAULT).length, 1);
});
