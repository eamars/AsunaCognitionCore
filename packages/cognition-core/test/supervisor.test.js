import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { hostLog, loaded, readySince, revertSelections, supervise, writeRecord, RUNGS } from '../../../tools/asuna-supervisor.mjs';

/**
 * A fake DSH world. `starts` scripts each start: 'ready', 'exit' (dies before ready), 'never' (no ready), or
 * 'prepare' (the prepare step throws). After the scripted starts are used up, every start is 'ready'.
 * `events` scripts what happens to a running Host: {request}, {crash}, or {stop}; when they run out, it stops.
 */
function world({ starts = [], events = [], reverts = {}, checkout = null } = {}) {
  let stopped = false, readyAt = null, current = null;
  const stops = [], records = [], interim = [], notes = [], prepared = [], slept = [], forwarded = [];
  let pendingRequest = null;
  const next = () => {
    const event = events.shift() ?? { stop: true };
    setTimeout(() => {
      if (event.request) pendingRequest = event.request;
      else if (event.crash) current.emit('exit', 1);
      else { stopped = true; for (const fn of stops.splice(0)) fn(); }
    }, 5);
  };
  const d = {
    pollMs: 2, readySeconds: 0.05,
    prepare: async (rung, { fastForward = false } = {}) => {
      prepared.push(rung); forwarded.push(fastForward);
      if (starts[0] === 'prepare') { starts.shift(); throw new Error('packing failed'); }
      return fastForward && checkout ? { notes: reverts[rung] ?? [], checkout } : reverts[rung] ?? [];
    },
    spawnHost: () => {
      const child = new EventEmitter();
      child.pid = null; child.exitCode = null; child.kill = () => { child.killed = true; };
      const how = starts.shift() ?? 'ready';
      current = child;
      readyAt = null;
      if (how === 'ready') { readyAt = d.now(); setTimeout(next, 5); }
      if (how === 'exit') setTimeout(() => child.emit('exit', 3), 2);
      return child;
    },
    ready: async since => readyAt !== null && readyAt >= since,
    takeRequest: async () => { const r = pendingRequest; pendingRequest = null; return r; },
    loaded: async () => ({ commit: 'abc1234', packages: {} }),
    // Finished restarts only (back_at); a failed start's interim write goes to `interim`.
    writeRecord: async record => { (record.back_at ? records : interim).push(structuredClone(record)); },
    note: text => notes.push(text),
    sleep: async ms => { slept.push(ms); },
    stopped: () => stopped,
    onStop: fn => stops.push(fn),
  };
  // the clock is real time, so "not ready within" can elapse
  const started = Date.now();
  d.now = () => Date.now() - started + 1;
  return { d, records, interim, notes, prepared, slept, forwarded };
}

test('her restart comes back on the same packages and the record says what loaded', async () => {
  const w = world({ events: [{ request: { asked: 'self', why: 'a JS change', interrupted: ['nothing'] } }] });
  await supervise(w.d);
  assert.equal(w.records.length, 1);
  const [record] = w.records;
  assert.equal(record.asked, 'self'); assert.equal(record.why, 'a JS change');
  assert.equal(record.result, 'running'); assert.equal(record.rung, RUNGS[0]);
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, true]]);
  assert.equal(record.loaded.commit, 'abc1234');
  assert.ok(record.down_at && record.back_at);
});

test('ADR-065: only the first start of a restart she asked for brings origin/main in; its result is its own field', async () => {
  const reason = { state: 'changed_files', detail: '1 file(s), first README.md' };
  const w = world({ starts: ['ready', 'ready', 'exit'], checkout: reason,
                    events: [{ request: { asked: 'home', why: 'her change is on origin' } }, { crash: true }, { stop: true }] });
  await supervise(w.d);
  // The owner's start, her restart, then a crash's start, which fails once and goes a rung down.
  assert.deepEqual(w.forwarded, [false, true, false, false]);
  const [hers, crash] = w.records;
  assert.deepEqual(hers.checkout, reason);
  assert.equal(hers.result, 'running', 'a checkout left as it was is not a fallback');
  assert.equal(hers.reverted, undefined);
  assert.equal(crash.asked, 'nobody'); assert.equal(crash.checkout, undefined);
});

test('a start that fails goes one rung down and the record says she fell back and why', async () => {
  const w = world({ starts: ['ready', 'exit'], events: [{ request: { asked: 'self', why: 'publish' } }],
                    reverts: { 1: ['core: returned to the previous running version'] } });
  await supervise(w.d);
  const [record] = w.records;
  assert.equal(record.result, 'fell_back');
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, false], [1, true]]);
  assert.match(record.attempts[0].reason, /exited before it was ready/);
  assert.deepEqual(record.reverted, ['core: returned to the previous running version']);
  // The failed start was on disk before it came back, with its exit code as a field.
  assert.equal(w.interim.length, 1);
  assert.equal(w.interim[0].result, 'not_back'); assert.equal(w.interim[0].attempts[0].code, 3);
});

test('the ladder ends on what is installed and keeps trying with a backoff; it never gives up', async () => {
  const w = world({ starts: ['ready', 'prepare', 'never', 'exit', 'exit'], events: [{ request: { asked: 'self', why: 'x' } }] });
  await supervise(w.d);
  const [record] = w.records;
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, false], [1, false], [2, false], [2, false], [2, true]]);
  assert.match(record.attempts[0].reason, /could not be prepared: packing failed/);
  assert.match(record.attempts[1].reason, /not ready within/);
  assert.deepEqual(w.slept, [60000, 300000]);
  assert.equal(record.result, 'fell_back');
});

test('a drill fails its first start on purpose and is back on the same packages', async () => {
  const w = world({ events: [{ request: { asked: 'self', why: 'drill', drill: true } }] });
  await supervise(w.d);
  const [record] = w.records;
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, false], [1, true]]);
  assert.match(record.attempts[0].reason, /^drill:/);
  assert.equal(record.result, 'running');
  assert.deepEqual(w.prepared, [0, 1]);                   // the drill's failed start never touched anything
});

test('a Host that exits on its own is started again, asked by nobody; a stop ends it all', async () => {
  const w = world({ events: [{ crash: true }] });
  await supervise(w.d);
  assert.equal(w.records.length, 1);
  assert.equal(w.records[0].asked, 'nobody');
  assert.match(w.records[0].why, /exited on its own/);
  assert.deepEqual(w.prepared, [0, 0]);
});

test('ready means a worker started after this start wrote runtime.ready', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-ready-'));
  try {
    const since = Date.now();
    assert.equal(await readySince(dir, since), false);
    const host = path.join(dir, 'native-host-abc');
    await fs.mkdir(host);
    await fs.writeFile(path.join(host, '00010-host.channels.ready.json'), '{}');
    assert.equal(await readySince(dir, since), false);
    await fs.writeFile(path.join(host, '00011-runtime.ready.json'), '{}');
    assert.equal(await readySince(dir, since), true);
    assert.equal(await readySince(dir, Date.now() + 60_000), false);       // an older start's ready does not count
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('rung 1 returns a selection being applied to the one that ran before', () => {
  const selection = { projects: {
    core: { state: 'APPLIED', candidate: 'new', previous: { artifact: 'old.tgz', candidate: 'old', state: 'ACTIVE' }, boots: 1 },
    persona: { state: 'ACTIVE', candidate: 'p' } } };
  const notes = revertSelections(selection, '2026-10-10T00:00:00Z');
  assert.deepEqual(notes, ['core: returned to the previous running version']);
  assert.equal(selection.projects.core.candidate, 'old');
  assert.equal(selection.projects.core.state, 'HOST_RESTART_REQUIRED');
  assert.equal(selection.projects.core.reverted_from.candidate, 'new');
  assert.equal(selection.projects.persona.candidate, 'p');
});

test('a finished restart is also kept in history.jsonl, so a later one does not wipe its failures', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-history-'));
  try {
    const env = { ASUNA_DATA_ROOT: dir };
    await writeRecord(env, { why: 'one', result: 'not_back', attempts: [{ ok: false, code: 3 }] });
    await writeRecord(env, { why: 'one', result: 'fell_back', back_at: 't1', attempts: [{ ok: false, code: 3 }, { ok: true }] });
    await writeRecord(env, { why: 'two', result: 'running', back_at: 't2', attempts: [{ ok: true }] });
    const history = (await fs.readFile(path.join(dir, 'restart', 'history.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
    assert.deepEqual(history.map(r => [r.why, r.result]), [['one', 'fell_back'], ['two', 'running']]);
    assert.equal(JSON.parse(await fs.readFile(path.join(dir, 'restart', 'last.json'), 'utf8')).why, 'two');
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('the Host log keeps its newest lines: past the limit the file becomes host.log.1 and a new one starts', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-hostlog-'));
  try {
    const file = path.join(dir, 'restart', 'host.log');
    const keep = hostLog(file, 10);
    keep(Buffer.from('aaaaaa')); keep(Buffer.from('bbbbbb'));             // the second would pass 10 bytes
    keep(Buffer.from('cc'));
    assert.equal(await fs.readFile(file + '.1', 'utf8'), 'aaaaaa');
    assert.equal(await fs.readFile(file, 'utf8'), 'bbbbbbcc');
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('the record says what runs: a selection that fell back reports the package it runs and the one it returned from', async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-loaded-'));
  try {
    await fs.writeFile(path.join(base, 'launch.json'), JSON.stringify({ installed: {
      '@asuna/cognition-core': '59273e56719b8c09', '@deepseek-ai/dsh-client-ui-chat': 'cd35f89fef652bf4' } }));
    await fs.writeFile(path.join(base, 'activation.json'), JSON.stringify({ projects: { core: {
      state: 'ACTIVE', sha256: 'fb763b01ca4c4725', packageRoot: path.join('profiles', 'node_modules', '@asuna', 'cognition-core'),
      reverted_from: { sha256: '59273e56719b8c09', starts: 1, by: 'supervisor' } } } }));
    const record = await loaded(base, path.join(base, 'launch.json'), () => 'abc1234\n');
    assert.equal(record.commit, 'abc1234');
    assert.equal(record.packages['@asuna/cognition-core'], 'fb763b01ca4c', 'the running selection, not the last install');
    assert.equal(record.packages['@deepseek-ai/dsh-client-ui-chat'], 'cd35f89fef65');
    assert.deepEqual(record.selections.core, { state: 'ACTIVE', candidate: null, reverted_from: '59273e56719b' });
  } finally {
    await fs.rm(base, { recursive: true, force: true });
  }
});
