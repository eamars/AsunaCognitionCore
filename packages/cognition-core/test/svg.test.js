import test from 'node:test';
import assert from 'node:assert/strict';
import { renderSvg } from '../src/svg.js';

const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 40 20">'
  + '<rect width="40" height="20" fill="#ff0000"/></svg>';

test('resvg renders a PNG at the asked width, keeping the aspect', async () => {
  const reply = await renderSvg({ svg, width: 200 });
  assert.equal(reply.width, 200);
  assert.equal(reply.height, 100);
  assert.deepEqual([...Buffer.from(reply.png, 'base64').subarray(1, 4)].map(code => String.fromCharCode(code)).join(''), 'PNG');
});

test('a picture bigger than the pixel limit is refused', async () => {
  await assert.rejects(renderSvg({ svg, width: 2048 }, { timeoutMs: 20_000, maxPixels: 1000 }), /more than 1000; give a smaller width/);
});

test('a render that takes too long is stopped', async () => {
  const heavy = '<svg xmlns="http://www.w3.org/2000/svg" width="2048" height="2048"><filter id="b"><feGaussianBlur stdDeviation="400"/></filter>'
    + Array.from({ length: 200 }, (_, i) => `<circle cx="${i * 10}" cy="${i * 10}" r="900" filter="url(#b)"/>`).join('') + '</svg>';
  await assert.rejects(renderSvg({ svg: heavy }, { timeoutMs: 50, maxPixels: 2048 * 4096 }), /more than 0.05 s/);
});
