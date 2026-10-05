// Pictures the owner attaches in her local chat are read back for the program's record, bounded; a failed read is
// reported, never skipped.
import test from 'node:test';
import assert from 'node:assert/strict';
import { imagesOf } from '../src/index.js';

test('attached pictures are read for the record; text-only messages carry none', async () => {
  const ref = id => ({ attachmentId: 'sha256:' + id, mediaType: 'image/png', bytes: 3, width: 8, height: 6, name: id + '.png' });
  const attachments = { async readImage(r) {
    if (r.attachmentId === 'sha256:gone') throw Object.assign(new Error('missing'), { code: 'ATTACHMENT_NOT_FOUND' });
    return { ref: r, data: new Uint8Array([1, 2, 3]) };
  } };
  const messages = [
    { content: [{ type: 'image', attachment: ref('a') }, { type: 'image', attachment: ref('gone') }, { type: 'text', text: '看看' }] },
    ...Array.from({ length: 9 }, (_, i) => ({ content: [{ type: 'image', attachment: ref('n' + i) }] })),
  ];
  const images = await imagesOf(attachments, messages);
  assert.equal(images.length, 8, 'at most 8');
  assert.deepEqual(images[0], { data: 'AQID', media_type: 'image/png', name: 'a.png', width: 8, height: 6,
    attachment_id: 'sha256:a' });
  assert.deepEqual(images[1], { name: 'gone.png', error: 'ATTACHMENT_NOT_FOUND' });
  assert.deepEqual(await imagesOf(attachments, [{ content: [{ type: 'text', text: '只有字' }] }]), []);
});
