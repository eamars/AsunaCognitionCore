// One SVG rendered by resvg in a worker thread (svg.js), so a heavy picture cannot hold up the Host.
import { parentPort, workerData } from 'node:worker_threads';
import { Resvg } from '@resvg/resvg-js';

const { svg, width, background, maxPixels } = workerData;
try {
  const options = { font: { loadSystemFonts: true }, ...(background ? { background } : {}) };
  const probe = new Resvg(svg, options);
  const scale = width ? width / probe.width : 1;
  const out = { width: Math.round(probe.width * scale), height: Math.round(probe.height * scale) };
  if (!(out.width > 0 && out.height > 0)) throw new Error('the SVG has no size (give it width/height or a viewBox)');
  if (out.width * out.height > maxPixels)
    throw new Error(`${out.width}×${out.height} pixels is more than ${maxPixels}; give a smaller width`);
  const resvg = width ? new Resvg(svg, { ...options, fitTo: { mode: 'width', value: width } }) : probe;
  const image = resvg.render();
  parentPort.postMessage({ png: Buffer.from(image.asPng()).toString('base64'), width: image.width, height: image.height });
} catch (error) {
  parentPort.postMessage({ error: String(error?.message ?? error).slice(0, 300) });
}
