/** The worker restarts she is told about afterwards (ADR-113), kept until the worker each one brought up records it.
 * Only this plugin replaces a worker in place while the Host runs on, so it keeps each restart in the profile's data
 * folder, `restarts-to-tell.json`: a list of {at, cause, held, held_sent, back}. `at` is when the restart began,
 * `cause` its kind from a closed list (`causeOf`), `held` what held it before it was asked for, as the stopping worker
 * sent it (null when nothing held it), `held_sent` false when the request carried no `held` at all (an older worker),
 * and `back` when the start it ran completed. A completed start hands each entry with a `back` to the worker
 * (`host.restarted`), which records it once as a `worker_restart` row (host_stops.py); then it leaves the file.
 *
 * A restart whose start failed is not kept: that is the outage `worker-down.json` records (outage.js). An entry left
 * without a `back` by a Host stopped mid-restart goes at the next completed start: that stop is the Host's own row.
 * A worker that failed and is started again (`worker failed: …`) is never written here: it is the outage's.
 *
 * As in outage.js: no function throws, every write is whole or not at all (a temporary file renamed over the old one),
 * and what fails is said in one `Asuna:` line. `worker-restarts.jsonl` beside it is the owner's log (`appendLog`). */
import { appendFile } from 'node:fs/promises';
import { readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { KEPT, startCause } from './outage.js';

export const FILE = 'restarts-to-tell.json';
export const KEPT_ENTRIES = 50;
export const LOG = 'worker-restarts.jsonl';
export const LOG_BYTES = 256 * 1024;
export const LOG_KEPT_BYTES = 128 * 1024;

const PROJECT = /^[a-z][a-z0-9-]{0,39}$/;

/** A restart's reason as one kind of the closed list her words key on: `published`, `settings`,
 * `settings_restored`, `recovery:<project>`, `again`, `unknown`; null for a worker that failed (not told here). */
export function causeOf(reason) {
  const text = String(reason ?? '');
  if (text.startsWith('worker failed:')) return null;
  if (text === 'worker asked: published-worker') return 'published';
  if (text === 'settings applied') return 'settings';
  if (text === 'settings restored after a failed apply') return 'settings_restored';
  if (text === 'a restart requested during the last one') return 'again';
  const recovery = text.match(/^recovery activated (.*)$/);
  if (recovery && PROJECT.test(recovery[1])) return 'recovery:' + recovery[1];
  return 'unknown';
}

/** Write the list whole or not at all. False when it could not. */
function save(dataRoot, entries, warn) {
  const file = path.join(dataRoot, FILE), next = file + '.' + process.pid + '.tmp';
  try {
    writeFileSync(next, JSON.stringify(entries));
    renameSync(next, file);
    return true;
  } catch (error) {
    try { unlinkSync(next); } catch { /* it was never written */ }
    warn('Asuna: ' + FILE + ' was not written (' + (error?.code ?? 'error') + '): a worker restart may not reach her block');
    return false;
  }
}

/** The restarts to tell, oldest first; empty when there are none. A file that is torn or not a list of entries is
 * read as empty and replaced, said in one line. */
export function entries(dataRoot, warn = () => {}) {
  let text;
  try { text = readFileSync(path.join(dataRoot, FILE), 'utf8'); }
  catch (error) {
    if (error?.code !== 'ENOENT') warn('Asuna: ' + FILE + ' could not be read (' + (error?.code ?? 'error') + ')');
    return [];
  }
  try {
    const list = JSON.parse(text);
    if (Array.isArray(list) && list.every(entry => entry && typeof entry === 'object' && typeof entry.at === 'string'))
      return list;
  } catch { /* said below */ }
  warn('Asuna: ' + FILE + ' could not be read; the restarts it held are not told');
  save(dataRoot, [], warn);
  return [];
}

/** A restart began: keep it to tell. At most KEPT_ENTRIES: the oldest beyond that goes, said in one line. */
export function asked(dataRoot, entry, warn = () => {}) {
  const list = [...entries(dataRoot, warn), entry];
  while (list.length > KEPT_ENTRIES) {
    const dropped = list.shift();
    warn('Asuna: ' + FILE + ' keeps ' + KEPT_ENTRIES + ' restarts; the one at ' + dropped.at
      + ' was dropped and does not reach her block');
  }
  return save(dataRoot, list, warn);
}

/** A start completed: the restart that ran it (`at`, null when no restart did) is stamped `back`, and every other
 * entry still without one goes (left by a Host stopped mid-restart; the Host's stop is its own row). */
export function cameUp(dataRoot, at, warn = () => {}, moment = new Date()) {
  const list = entries(dataRoot, warn);
  const kept = list.filter(entry => entry.back || entry.at === at)
    .map(entry => entry.at === at && !entry.back ? { ...entry, back: moment.toISOString() } : entry);
  if (kept.length !== list.length || kept.some((entry, i) => entry !== list[i])) save(dataRoot, kept, warn);
}

/** The start a restart ran failed: the entry goes (the outage records it). */
export function startFailed(dataRoot, at, warn = () => {}) {
  const list = entries(dataRoot, warn);
  const kept = list.filter(entry => entry.at !== at);
  if (kept.length !== list.length) save(dataRoot, kept, warn);
}

/** Hand every entry with a `back` to the worker; those it answers it recorded leave the file. Returns the answer,
 * null when there is nothing to hand over, or KEPT when the call failed: the entries stay for a later try (a row's id
 * comes from its `at`, so handing one over again writes nothing new). */
export async function tell(dataRoot, send, warn = () => {}) {
  const ready = entries(dataRoot, warn).filter(entry => entry.back);
  if (!ready.length) return null;
  let answer;
  try { answer = await send({ restarts: ready }); }
  catch (error) {
    // Said once per kind of failure, as outage.js's cameBack keys it: the error's name, never its text.
    const line = String(error?.message ?? error).split(/\r?\n/)[0].slice(0, 200);
    const name = startCause(error).slice('start_failed:'.length);
    warn('Asuna: ' + ready.length + ' worker restart(s) are not recorded yet; they are handed over again: ' + line,
      'restarts ' + (name === 'Error' ? 'text ' + line : name));
    return KEPT;
  }
  const recorded = new Set(Array.isArray(answer?.recorded) ? answer.recorded : []);
  // Read again: a restart may have begun while the call ran (each read and write here runs whole, never interleaved).
  const list = entries(dataRoot, warn);
  const kept = list.filter(entry => !recorded.has(entry.at));
  if (kept.length !== list.length) save(dataRoot, kept, warn);
  return answer;
}

/** The owner's log of every restart, read by nothing: one line each; past LOG_BYTES its newest LOG_KEPT_BYTES are
 * kept, cut at a line. */
export async function appendLog(dataRoot, entry, warn = () => {}) {
  const file = path.join(dataRoot, LOG);
  try { await appendFile(file, JSON.stringify(entry) + '\n'); }
  catch (error) { warn('Asuna: restart not logged: ' + String(error)); return; }
  try {
    if (statSync(file).size <= LOG_BYTES) return;
    const bytes = readFileSync(file);
    const tail = bytes.subarray(bytes.length - LOG_KEPT_BYTES);
    const cut = tail.indexOf(10);
    const next = file + '.' + process.pid + '.tmp';
    writeFileSync(next, tail.subarray(cut + 1));
    renameSync(next, file);
  } catch (error) {
    warn('Asuna: ' + LOG + ' was not shortened (' + (error?.code ?? 'error') + ')');
  }
}
