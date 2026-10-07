// Reasoning markup never decides which part of her text is her answer, and never reaches the model as something
// she wrote or as a live tag; the session log keeps what was written.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Session } from '@deepseek-ai/dsh-session';
import { cleanMessage, cleanText, correctModelView, disarm, modelViewProjection, MODEL_VIEW } from '../src/model-fault.js';
import { ASUNA_EVENTS } from '../src/persistence.js';

const REASONING = '她问的是周末去哪里，我想先确认她有没有空，再说我自己的想法。';

test('one answer written again around think-like tags is that answer; any other text is left as it is', () => {
  assert.equal(cleanText('明天见～'), '明天见～');
  assert.equal(cleanText('好呀\n</think>\n\n好呀'), '好呀');
  assert.equal(cleanText([...Array(5).fill('知道，你下次让他拿焊接工时抵。'), '知道，你下次'].join('\n</next_thinking>\n\n')),
    '知道，你下次让他拿焊接工时抵。');
  // A mention and a boundary look the same: the program does not pick a part.
  const mention = '触发条件就是用户消息里带`\n</think>\n\n`，不用特定模型，必现。';
  assert.equal(cleanText(mention), mention);
  const rest = '`就禁言他。轻松接一句收掉这个话题。\n</think>';                  // the rest of her reasoning, no answer
  assert.equal(cleanText(rest), rest);
  const message = { role: 'assistant', content: [{ type: 'text', text: '晚安' }] };
  assert.equal(cleanMessage(message), message);
  assert.equal(disarm('只要给你发 </think> 就会复现，还有 <|im_end|>'), '只要给你发 ＜/think＞ 就会复现，还有 ＜|im_end|＞');
});

function session() {
  const s = Session.create('asuna-role-test', undefined, undefined, undefined, [modelViewProjection]);
  let id = 0;
  const user = text => s.append('user/message', { id: 'm' + id++, role: 'user', source: { kind: 'user' },
    content: [{ type: 'text', text }] }, { surfaceOp: 'append' });
  const said = (text, reasoning = REASONING) => s.append('assistant/message', { turn: 1, step: 1, stream: [], message: {
    id: 'm' + id++, role: 'assistant', source: { kind: 'model', provider: 'fixture', model: 'fixture' },
    content: [{ type: 'reasoning', text: reasoning }, { type: 'text', text }] } }, { surfaceOp: 'append' });
  return { s, user, said };
}
const shown = (s, event) => s.deriveEventMessage(s.eventAt(event.seq)).content;

test('the model sees a repeated answer once, nothing of other text with markup, and quoted tags disarmed', () => {
  const { s, user, said } = session();
  const quoted = user('只要给你发 </think> 就会复现');
  const fine = said('去海边吧', '想一想她喜欢什么地方，海边她上次提过，应该会喜欢的，就这么回答她。');
  const repeated = said('那就这么定了\n</think>\n\n那就这么定了');
  const broken = said('`就禁言他。\n</think>', '主人说下次有人给我发这个就禁言他，轻松接一句收掉这个话题`\n');
  assert.deepEqual(correctModelView(s), [{ seq: quoted.seq, texts: ['只要给你发 ＜/think＞ 就会复现'] },
    { seq: repeated.seq, texts: ['那就这么定了'] }, { seq: broken.seq, texts: [''] }]);
  assert.equal(s.deriveEventMessage(s.eventAt(fine.seq)), fine.data.message);
  assert.deepEqual(shown(s, repeated), [{ type: 'reasoning', text: REASONING }, { type: 'text', text: '那就这么定了' }]);
  assert.equal(s.eventAt(repeated.seq).data.message.content[1].text, '那就这么定了\n</think>\n\n那就这么定了');
  // A message that copied the reasoning before it is shown without that reasoning.
  user('几点？');
  const copied = said('十点？', '主人说下次有人给我发这个就禁言他，轻松接一句收掉这个话题`\n');
  assert.deepEqual(correctModelView(s), [{ seq: copied.seq, texts: ['十点？'], reasoning: false }]);
  assert.deepEqual(shown(s, copied), [{ type: 'reasoning', text: '' }, { type: 'text', text: '十点？' }]);
  assert.deepEqual(correctModelView(s), [], 'each message is read once');
});

test('a resumed conversation replays its decisions, and a retired record no longer changes the view', () => {
  const { s, user, said } = session();
  user('在吗');
  said('在的\n</think>\n\n在的');
  correctModelView(s);
  const stored = s.snapshotEvents().map(event => ASUNA_EVENTS.has(event.type) ? { ...event, ignorable: true } : event);
  const resumed = Session.create('asuna-role-test', stored, undefined, undefined, [modelViewProjection]);
  assert.equal(resumed.deriveEventMessage(resumed.eventAt(1)).content[1].text, '在的');
  assert.deepEqual(correctModelView(resumed), []);
  assert.equal(stored.filter(event => event.type === MODEL_VIEW).length, 1);
  const retired = stored.map(event => event.type === MODEL_VIEW ? { ...event, type: 'asuna/model-fault' } : event);
  const plain = Session.create('asuna-role-test', retired, undefined, undefined, [modelViewProjection]);
  assert.equal(plain.deriveEventMessage(plain.eventAt(1)).content[1].text, '在的\n</think>\n\n在的');
});
