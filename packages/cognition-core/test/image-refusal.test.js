import test from 'node:test';
import assert from 'node:assert/strict';
import { imageRefusalListener, offloadAllImages } from '../src/image-refusal.js';

const image = (offloaded) => ({ type: 'image', attachment: { attachmentId: 'a' }, ...(offloaded ? { offloaded: true } : {}) });

function session(id, messages) {
  const events = messages.map((content, seq) => ({ seq, type: content === null ? 'assistant/message' : 'tool/result', content }));
  const appended = [];
  return {
    id, appended,
    surface: { nodes: events.map(event => event.seq) },
    eventAt: seq => events[seq],
    deriveEventMessage: event => ({ content: event.content }),
    append: (type, payload) => appended.push({ type, payload }),
  };
}

test('a refused request with pictures omits every retained picture once and retries; nothing left goes on as before', async () => {
  const s = session('asuna-role-1', [
    [{ type: 'tool-result', content: [image(), { type: 'text', text: 'x' }] }],
    null,                                                            // her own words carry no input pictures
    [image(true), image(), { type: 'text', text: 'y' }],             // index 0 was omitted earlier, index 1 still sent
  ]);
  const logged = [];
  const listener = imageRefusalListener(text => logged.push(text));
  const next = () => Promise.resolve('next');
  const refusal = { code: 'INVALID_REQUEST', message: '400: this image format needs Pillow' };
  assert.deepEqual(await listener({ agent: { session: s }, failure: refusal }, next), { kind: 'retry' });
  assert.deepEqual(s.appended, [{ type: 'image/offload', payload: { targets: [{ seq: 0, imageIndexes: [0] }, { seq: 2, imageIndexes: [1] }] } }]);
  assert.match(logged[0], /2 picture\(s\) in asuna-role-1/);
  // The same request refused again: every picture is already a placeholder, so the error goes on unchanged.
  const done = session('asuna-role-1', [[image(true)]]);
  assert.equal(offloadAllImages(done), 0);
  assert.equal(await listener({ agent: { session: done }, failure: refusal }, next), 'next');
  assert.deepEqual(done.appended, []);
  // Other errors, and sessions that are not Asuna's, are left to the rest of the waterfall.
  const other = session('asuna-role-2', [[image()]]);
  assert.equal(await listener({ agent: { session: other }, failure: { code: 'RATE_LIMIT' } }, next), 'next');
  assert.equal(await listener({ agent: { session: session('chat-1', [[image()]]) }, failure: refusal }, next), 'next');
  assert.deepEqual(other.appended, []);
});
