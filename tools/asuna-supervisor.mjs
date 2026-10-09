/**
 * The Host supervisor (ADR-034): the launcher stays as DSH's parent, restarts it when she asks or when it exits on
 * its own, and brings it back down a fallback ladder when a start fails. "Back" means the worker wrote
 * runtime.ready, not that the page answers.
 *
 * Files, in <data>/restart/ (ASUNA_DATA_ROOT, else .runtime):
 *   request.json  written by the worker when her restart is due (asuna/restarts.py); taken and removed here
 *   last.json     the record of the latest restart, written here once she is back; the worker reads it
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
export const READY_SECONDS = 600;               // a start that installs packages takes minutes
export const POLL_MS = 2000;
export const BACKOFF_SECONDS = [60, 300, 900, 1800];
// The ladder: what each start after a failed one changes.
export const RUNGS = [
  'the same packages again',                    // 0: as the owner's start does: sync the checkout, apply selections
  'the previous running version',               // 1: a selection being applied goes back to the one that ran before
  'what is installed, without syncing',         // 2: nothing changes; retried with backoff, never given up
];

export const dataRoot = (env = process.env) => path.resolve(env.ASUNA_DATA_ROOT || path.join(root, '.runtime'));
export const restartFolder = env => path.join(dataRoot(env), 'restart');

/** Whether a worker that started after `since` (ms) has written runtime.ready in its reports folder. */
export async function readySince(reports, since) {
  let names = [];
  try { names = await fs.readdir(reports); } catch { return false; }
  for (const name of names) {
    if (!name.startsWith('native-host-')) continue;
    const folder = path.join(reports, name);
    const stat = await fs.stat(folder).catch(() => null);
    if (!stat || stat.mtimeMs < since - 1000) continue;
    const files = await fs.readdir(folder).catch(() => []);
    for (const file of files) {
      if (!file.endsWith('-runtime.ready.json')) continue;
      const made = await fs.stat(path.join(folder, file)).catch(() => null);
      if (made && made.mtimeMs >= since - 1000) return true;
    }
  }
  return false;
}

/** A selection being applied goes straight back to the one that ran before it (rung 1). Returns notes. */
export function revertSelections(selection, now = new Date().toISOString()) {
  const notes = [];
  for (const [id, selected] of Object.entries(selection.projects ?? {})) {
    if (!['APPLIED', 'HOST_RESTART_REQUIRED'].includes(selected.state) || !selected.previous?.artifact) continue;
    const { previous, boots, ...failed } = selected;
    selection.projects[id] = { ...previous, state: 'HOST_RESTART_REQUIRED', reverted_at: now,
      reverted_from: { candidate: failed.candidate, sha256: failed.sha256, published_at: failed.published_at,
                       starts: boots ?? 0, by: 'supervisor' } };
    notes.push(id + ': returned to the previous running version');
  }
  return notes;
}

export function killTree(child, platform = process.platform) {
  if (!child?.pid || child.exitCode !== null) return;
  if (platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
  else { try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); } }
}

/**
 * The loop. `d` gives the world:
 *   prepare(rung)            sync/selection for that rung (may throw)
 *   spawnHost()              a running DSH child (emits 'exit')
 *   ready(since)             whether the worker is ready since that time
 *   takeRequest()            her due restart request, removed once taken, else null
 *   loaded()                 what actually runs: commit and packages
 *   writeRecord(record)      last.json
 *   note(text)               a line for the console
 *   now(), sleep(ms), stopped(), onStop(fn)
 */
export async function supervise(d) {
  const poll = d.pollMs ?? POLL_MS, readyMs = (d.readySeconds ?? READY_SECONDS) * 1000;
  let record = null, rung = 0, failures = 0, reverted = [];
  const begin = fields => ({ id: 'restart-' + new Date(d.now()).toISOString().replace(/[-:.TZ]/g, '').slice(0, 14),
                             down_at: new Date(d.now()).toISOString(), attempts: [], ...fields });
  while (!d.stopped()) {
    const since = d.now();
    if (record?.drill && !record.drilled) {
      record.drilled = true;
      record.attempts.push({ rung, ok: false, at: new Date(since).toISOString(), reason: 'drill: this start failed on purpose' });
      rung = 1;
      continue;
    }
    let child = null, outcome;
    try {
      reverted.push(...((await d.prepare(rung)) ?? []));
      child = d.spawnHost();
      outcome = await new Promise(resolve => {
        let done = false;
        const finish = value => { if (!done) { done = true; clearInterval(timer); resolve(value); } };
        child.once('exit', code => finish('the Host exited before it was ready (code ' + code + ')'));
        const timer = setInterval(async () => {
          if (d.stopped()) finish('stopped');
          else if (await d.ready(since)) finish('ready');
          else if (d.now() - since > readyMs) finish('not ready within ' + Math.round(readyMs / 60000) + ' minutes');
        }, poll);
      });
    } catch (error) {
      outcome = 'the start could not be prepared: ' + (error?.message ?? error);
    }
    if (d.stopped()) { if (child) killTree(child); break; }
    if (outcome !== 'ready') {
      if (child) killTree(child);
      record ??= begin({ asked: 'nobody', why: 'a start that failed' });
      record.attempts.push({ rung, ok: false, at: new Date(since).toISOString(), reason: outcome });
      d.note('Asuna supervisor: start failed (' + RUNGS[rung] + '): ' + outcome);
      if (rung < RUNGS.length - 1) { rung++; continue; }
      const wait = BACKOFF_SECONDS[Math.min(failures, BACKOFF_SECONDS.length - 1)];
      failures++;
      d.note('Asuna supervisor: trying again in ' + wait + ' s');
      await d.sleep(wait * 1000);
      continue;
    }
    if (record) {
      record.attempts.push({ rung, ok: true, at: new Date(since).toISOString() });
      record.back_at = new Date(d.now()).toISOString();
      // Back on the same packages unless a later rung was needed for a real failure (a drill's planned one is not).
      const real = record.attempts.filter(a => !a.ok && !String(a.reason).startsWith('drill:')).length;
      record.result = real === 0 && !reverted.length ? 'running' : 'fell_back';
      record.rung = RUNGS[rung];
      if (reverted.length) record.reverted = [...reverted];
      record.loaded = await d.loaded();
      await d.writeRecord(record);
      record = null;
    }
    rung = 0; failures = 0; reverted = [];
    const event = await new Promise(resolve => {
      let done = false;
      const finish = value => { if (!done) { done = true; clearInterval(timer); resolve(value); } };
      child.once('exit', code => finish({ kind: 'exit', code }));
      d.onStop(() => finish({ kind: 'stop' }));
      const timer = setInterval(async () => {
        const request = await d.takeRequest();
        if (request) finish({ kind: 'request', request });
      }, poll);
    });
    if (event.kind === 'stop') { child.kill(); break; }
    if (event.kind === 'request') {
      record = begin(event.request);
      d.note('Asuna supervisor: restarting because she asked: ' + (event.request.why ?? ''));
      killTree(child);
      continue;
    }
    if (d.stopped()) break;
    record = begin({ asked: 'nobody', why: 'the Host exited on its own (code ' + event.code + ')' });
    d.note('Asuna supervisor: the Host exited on its own (code ' + event.code + '); starting it again');
  }
}

/** What actually runs after a start: the checkout's commit and each selected package. */
export async function loaded(base, launchFile) {
  const commit = spawnSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root, encoding: 'utf8', windowsHide: true });
  const read = async file => { try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch { return {}; } };
  const selection = await read(path.join(base, 'activation.json'));
  const launch = await read(launchFile);
  return {
    commit: (commit.stdout || '').trim() || null,
    packages: Object.fromEntries(Object.entries(launch.installed ?? {}).map(([name, sha]) => [name, String(sha).slice(0, 12)])),
    selections: Object.fromEntries(Object.entries(selection.projects ?? {}).map(([id, s]) =>
      [id, { state: s.state, candidate: s.candidate ? String(s.candidate).slice(0, 12) : null,
             ...(s.reverted_from ? { reverted_from: String(s.reverted_from.candidate ?? '').slice(0, 12) } : {}) }])),
  };
}

export async function takeRequest(env) {
  const file = path.join(restartFolder(env), 'request.json');
  try {
    const request = JSON.parse(await fs.readFile(file, 'utf8'));
    await fs.rm(file, { force: true });
    return request;
  } catch { return null; }
}

export async function writeRecord(env, record) {
  const folder = restartFolder(env);
  await fs.mkdir(folder, { recursive: true });
  await fs.writeFile(path.join(folder, 'last.json.tmp'), JSON.stringify(record, null, 2));
  await fs.rename(path.join(folder, 'last.json.tmp'), path.join(folder, 'last.json'));
}
