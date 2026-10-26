/** The span she was down while the Host ran on (ADR-101). Only this plugin knows why a worker went away (a start that
 * failed, a worker that exited), so it keeps the open span in the profile's data folder, `worker-down.json`:
 * {since, cause, tries, inside, opened}. A file and not the database, because the failure is often the database
 * itself, and a file survives a Host restart and a recreated container (the data folder is the deployment's own).
 * The worker reads it at its start (a lease left behind inside the span is that same outage) and never writes it.
 * A completed start hands the span to the worker (`host.came_back`), which records it once as a `worker_down` row
 * (host_stops.py); then the file goes. A worker without that method (an older core) leaves the file for a later one.
 *
 * Nothing here may make things worse than the outage it records: no function throws, every write is whole or not at
 * all (a temporary file renamed over the old one), and what fails is said in one `Asuna:` line. */
import { readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';

export const FILE = 'worker-down.json';
export const SPAN_BYTES = 65536;
export const KEPT = 'kept';

const CODE = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/;

/** A failed start's cause by name only, as faults.cause takes it: the error code its last line carries, else the
 * exception's class (`AutoReconnect` from "AutoReconnect: <host>:<port>: …"). Never the text: it carries addresses. */
export function startCause(error) {
  const text = String(error?.message ?? error ?? '');
  const last = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).pop() ?? '';
  const code = last.match(CODE);
  const name = (code ? code[0] : last.split(':')[0].trim().split('.').pop()).replace(/[^A-Za-z0-9_]/g, '').slice(0, 60);
  return 'start_failed:' + (/^[A-Za-z]/.test(name) ? name : 'Error');
}

/** A worker's exit by its code (`exited:1`, `exited:none` when it had none), or unknown. */
export function exitCause(error) {
  const found = String(error?.message ?? error ?? '').match(/worker exited \((-?\d+|null)\)/);
  return found ? 'exited:' + (found[1] === 'null' ? 'none' : found[1]) : 'unknown';
}

/** Write the span whole or not at all: a temporary file beside it, renamed over it. False when it could not. */
function save(dataRoot, span, warn) {
  const file = path.join(dataRoot, FILE), next = file + '.' + process.pid + '.tmp';
  try {
    writeFileSync(next, JSON.stringify(span));
    renameSync(next, file);
    return true;
  } catch (error) {
    try { unlinkSync(next); } catch { /* it was never written */ }
    warn('Asuna: ' + FILE + ' was not written (' + (error?.code ?? 'error') + '): this outage may not reach her block');
    return false;
  }
}

/** The open span, or null when there is none or its file cannot be read. A file that is there but is not a span is
 * a span whose start is not known: kept and said, never dropped. */
export function openSpan(dataRoot, warn = () => {}) {
  let text;
  try {
    const file = path.join(dataRoot, FILE);
    // Past SPAN_BYTES it is not a span, on this side as in the worker's (host_stops.SPAN_BYTES): both read it alike.
    text = statSync(file).size > SPAN_BYTES ? null : readFileSync(file, 'utf8');
  } catch (error) {
    if (error?.code !== 'ENOENT') warn('Asuna: ' + FILE + ' could not be read (' + (error?.code ?? 'error') + ')');
    return null;
  }
  try {
    const span = text === null ? null : JSON.parse(text);
    if (span && typeof span === 'object' && typeof span.cause === 'string') return span;
  } catch { /* said below */ }
  warn('Asuna: ' + FILE + ' could not be read; the span it held is kept with its start not known');
  const span = { since: null, cause: 'unknown', tries: 1, inside: 0, opened: new Date().toISOString() };
  save(dataRoot, span, warn);
  return span;
}

/** A worker went down unplanned: open the span, or keep its start and first cause and count one more try. */
export function wentDown(dataRoot, cause, warn = () => {}, at = new Date()) {
  const span = openSpan(dataRoot, warn);
  const next = span ? { ...span, tries: (Number(span.tries) || 1) + 1 }
    : { since: at.toISOString(), cause, tries: 1, inside: 0 };
  save(dataRoot, next, warn);
  return next;
}

/** A Host stop inside the open span (a lease left behind that was not this Host's own exited worker): one more. */
export function stopInside(dataRoot, warn = () => {}) {
  const span = openSpan(dataRoot, warn);
  if (!span) return null;
  const next = { ...span, inside: (Number(span.inside) || 0) + 1 };
  save(dataRoot, next, warn);
  return next;
}

/** A start completed: hand the open span to the worker, then remove it. Returns the worker's answer, null when no
 * span is open, or KEPT when the call failed: the file stays and the caller tries again later (the row's id comes from
 * the span, so it is written once however often it is handed over). */
export async function cameBack(dataRoot, send, warn = () => {}) {
  const span = openSpan(dataRoot, warn);
  if (!span) return null;
  let answer;
  try { answer = await send(span); }
  catch (error) {
    warn('Asuna: the span she was down since ' + (span.since ?? 'an unknown moment') + ' is not recorded yet; '
      + 'it is handed over again: ' + String(error?.message ?? error).split(/\r?\n/)[0].slice(0, 200));
    return KEPT;
  }
  try { unlinkSync(path.join(dataRoot, FILE)); }
  catch (error) {
    if (error?.code !== 'ENOENT') warn('Asuna: the span was recorded, but ' + FILE + ' could not be removed ('
      + (error?.code ?? 'error') + '); the next start hands it over again and writes no second row');
  }
  return answer;
}
