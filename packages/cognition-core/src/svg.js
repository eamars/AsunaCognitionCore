/** The Host side of render_svg (ADR-027): resvg renders an SVG the worker has already made safe (no links to
 * pictures outside it), in a worker thread with a time and pixel limit. */
import { Worker } from 'node:worker_threads';

export const SVG_LIMITS = { timeoutMs: 20_000, maxPixels: 2048 * 4096 };

export function renderSvg({ svg, width, background }, limits = SVG_LIMITS) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./svg-worker.js', import.meta.url),
      { workerData: { svg, width, background, maxPixels: limits.maxPixels } });
    const timer = setTimeout(() => { worker.terminate(); reject(new Error(`rendering took more than ${limits.timeoutMs / 1000} s`)); },
      limits.timeoutMs);
    worker.once('message', reply => { clearTimeout(timer); worker.terminate();
      if (reply.error) reject(new Error(reply.error)); else resolve(reply); });
    worker.once('error', error => { clearTimeout(timer); reject(error); });
  });
}
