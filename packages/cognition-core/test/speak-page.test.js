// ADR-129 D5(b): the page asks what one speak call sent; the plugin answers only for a call found, with a result that
// is not an error, in that character session's own events, made in a step of the stage the page names.
import test from 'node:test';
import assert from 'node:assert/strict';
import { AsunaApi, speakCallIn } from '../src/api.js';

let seq = 0;
const ev = (type, data) => ({ type, seq: seq++, data });
function session() {
  seq = 0;
  return [
    ev('asuna/stage', { turn: 3, step: 1, operation: 'ep-a:TURN' }),
    ev('tool/call', { turn: 3, step: 1, callId: 'c-think', name: 'think', arguments: '{}' }),
    ev('tool/result', { turn: 3, step: 1, message: { toolCallId: 'c-think', isError: false } }),
    ev('asuna/stage', { turn: 3, step: 2, operation: 'ep-a:TURN' }),
    ev('tool/call', { turn: 3, step: 2, callId: 'c-speak', name: 'speak', arguments: '{}' }),
    ev('tool/result', { turn: 3, step: 2, message: { toolCallId: 'c-speak', isError: false } }),
    ev('tool/call', { turn: 3, step: 2, callId: 'c-refused', name: 'speak', arguments: '{}' }),
    ev('tool/result', { turn: 3, step: 2, message: { toolCallId: 'c-refused', isError: true } }),
  ];
}

test('only her own speak call with a result, in a step of the stage named, is served', () => {
  const events = session();
  assert.equal(speakCallIn(events, 'c-speak', 'ep-a:TURN'), true);
  assert.equal(speakCallIn(events, 'c-speak', 'ep-b:TURN'), false, 'another turn of hers');
  assert.equal(speakCallIn(events, 'c-think', 'ep-a:TURN'), false, 'not a speak call');
  assert.equal(speakCallIn(events, 'c-refused', 'ep-a:TURN'), false, 'refused: nothing left');
  assert.equal(speakCallIn(events, 'c-elsewhere', 'ep-a:TURN'), false, 'a call of another session');
  assert.equal(speakCallIn(events.slice(0, 5), 'c-speak', 'ep-a:TURN'), false, 'no result yet');
});

test('the worker is asked only for a character session\'s call found in its events', async () => {
  const asked = [];
  const events = session();
  const worker = { call: async (method, args) => {
    asked.push(method);
    if (method === 'session') return { lane: args.session_id === 'role' ? 'character' : 'executor' };
    return { parts: [] };
  } };
  const ctx = { agents: new Map([['role', { session: { snapshotEvents: () => events } }],
    ['action', { session: { snapshotEvents: () => events } }]]) };
  const api = Object.create(AsunaApi.prototype);
  api.core = { ready: async () => {}, worker, ctx };
  assert.deepEqual(await api.speakParts({ session_id: 'role', operation: 'ep-a:TURN', call_id: 'c-speak' }), { parts: [] });
  assert.deepEqual(asked, ['session', 'speak.parts']);
  await assert.rejects(api.speakParts({ session_id: 'action', operation: 'ep-a:TURN', call_id: 'c-speak' }),
    /ROLE_SESSION_REQUIRED/);
  await assert.rejects(api.speakPicture({ session_id: 'role', operation: 'ep-a:TURN', call_id: 'c-refused', index: 0 }),
    /SPEAK_CALL_NOT_FOUND/);
  assert.deepEqual(asked.filter(method => method.startsWith('speak.')), ['speak.parts'], 'nothing else reached the worker');
});
