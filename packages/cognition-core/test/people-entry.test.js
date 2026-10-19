import test from 'node:test';
import assert from 'node:assert/strict';
import { composeContext, visibleCarried } from '../src/context-delivery.js';
import { ROLE_COMPACTION_INSTRUCTION } from '../src/compaction.js';

// ADR-082: a group turn's people_from_program (the person who started it and the queued addressers) is a list block
// like any other: an entry the session still shows is folded, a changed one is sent again, a compaction brings it back.
function surface(events) {
  return { surface: { nodes: events.map((_, index) => index) }, eventAt: seq => events[seq],
    deriveEventMessage: event => ({ content: event.data.content }) };
}
const notice = (composed, episode) => ({ type: 'user/message', data: {
  content: [{ type: 'text', text: JSON.stringify(composed.context) }],
  source: { kind: 'asuna', carried: { ...composed.carried, episode } } } });
const NOTE = '叫你的人：……';
const people = (...items) => ({ scene: '一个群', people_from_program: { items, note: NOTE }, event: { text: '@她 在吗' } });
const a = { who: '[甲 #1]', familiarity: '熟人', stance: '随意些', short: '说话直接', written_at: '2026-10-19T01:00:00+00:00' };
const b = { who: '[乙 #2]', familiarity: '不熟', stance: '先客气' };

test('a person\'s entry is folded while the session shows it and sent again when it changes', () => {
  const first = composeContext(people(a), visibleCarried(surface([])));
  assert.deepEqual(first.context.people_from_program, { items: [a], note: NOTE }, 'first turn: the whole entry');
  const events = [notice(first, 'ep-1')];

  // A starts another turn with B queued behind him: only B is new.
  const second = composeContext(people(a, b), visibleCarried(surface(events)));
  assert.deepEqual(second.context.people_from_program.items, [b]);
  assert.ok(second.context.people_from_program.same_as_before, 'says that the rest is as before');
  assert.equal(second.context.people_from_program.note, NOTE);
  assert.equal(second.omitted.items, 1);

  // The same people again, all still visible: nothing of the block is sent.
  const third = composeContext(people(a), visibleCarried(surface([...events, notice(second, 'ep-2')])));
  assert.equal(third.context.people_from_program, undefined);
  assert.ok(third.context.unchanged_from_program.includes('people_from_program'));

  // Her write changed A's short, his tier or his label: a new digest, sent again.
  for (const changed of [{ ...a, short: '说话直接，肯听人说完' }, { ...a, familiarity: '常来往' }, { ...a, who: '[甲改名 #1]' }]) {
    const again = composeContext(people(changed), visibleCarried(surface([...events, notice(second, 'ep-2')])));
    assert.deepEqual(again.context.people_from_program.items, [changed]);
  }

  // After a compaction took the notices off the surface, the entry comes with that person's next turn.
  const checkpoint = { type: 'user/message', data: { content: [{ type: 'text', text: '<compacted-summary>…' }],
    source: { kind: 'compact-checkpoint' } } };
  const after = composeContext(people(a), visibleCarried(surface([checkpoint])));
  assert.deepEqual(after.context.people_from_program, { items: [a], note: NOTE });
});

test('the checkpoint instruction names the entry among the program data it must not copy', () => {
  const rule = ROLE_COMPACTION_INSTRUCTION.split('\n').find(line => line.includes('不要转抄进检查点'));
  assert.ok(rule && rule.includes('people_from_program'), rule);
});
