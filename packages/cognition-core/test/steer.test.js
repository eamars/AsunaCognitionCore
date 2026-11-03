import test from 'node:test';
import assert from 'node:assert/strict';
import { holdSteeredInput } from '../src/steer.js';

function agent(items, status = 'running') {
  const lists = { 'next-step': [...items], 'next-turn': [] };
  return { lists, status, inbox: {
    get nextStep() { return lists['next-step']; },
    remove(id) { for (const list of Object.values(lists)) { const i = list.findIndex(m => m.id === id); if (i >= 0) list.splice(i, 1); } },
    append(target, message) { lists[target].push(message); },
  } };
}

test('a person steering into her running turn waits as the next turn; her own notes and idle turns are left alone', () => {
  const person = { id: 'u1', source: { kind: 'user' } };
  const a = agent([person]);
  assert.equal(holdSteeredInput(a, person), true);
  assert.deepEqual(a.lists, { 'next-step': [], 'next-turn': [person] });
  const note = { id: 'n1', source: { kind: 'asuna' } };
  const b = agent([note]);
  assert.equal(holdSteeredInput(b, note), false);                  // the program's own stage note steers as before
  const line = { id: 'p1', source: { kind: 'user', channel: 'dsh' } };
  assert.equal(holdSteeredInput(agent([line]), line), false);      // platform lines keep their delivery
  assert.equal(holdSteeredInput(agent([person], 'idle'), person), false); // no turn running: it starts one
});
