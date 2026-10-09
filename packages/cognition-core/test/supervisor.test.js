import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { readySince, revertSelections, supervise, RUNGS } from '../../../tools/asuna-supervisor.mjs';

/**
 * A fake DSH world. `starts` scripts each start: 'ready', 'exit' (dies before ready), 'never' (no ready), or
 * 'prepare' (the prepare step throws). After the scripted starts are used up, every start is 'ready'.
 * `events` scripts what happens to a running Host: {request}, {crash}, or {stop}; when they run out, it stops.
 */
function world({ starts = [], events = [], reverts = {} } = {}) {
  let stopped = false, readyAt = null, current = null;
  const stops = [], records = [], notes = [], prepared = [], slept = [];
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
    prepare: async rung => {
      prepared.push(rung);
      if (starts[0] === 'prepare') { starts.shift(); throw new Error('packing failed'); }
      return reverts[rung] ?? [];
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
    writeRecord: async record => { records.push(structuredClone(record)); },
    note: text => notes.push(text),
    sleep: async ms => { slept.push(ms); },
    stopped: () => stopped,
    onStop: fn => stops.push(fn),
  };
  // the clock is real time, so "not ready within" can elapse
  const started = Date.now();
  d.now = () => Date.now() - started + 1;
  return { d, records, notes, prepared, slept };
}

test('her restart comes back on the same packages and the record says what loaded', async () => {
  const w = world({ events: [{ request: { asked: 'xiaoman', why: 'a JS change', interrupted: ['nothing'] } }] });
  await supervise(w.d);
  assert.equal(w.records.length, 1);
  const [record] = w.records;
  assert.equal(record.asked, 'xiaoman'); assert.equal(record.why, 'a JS change');
  assert.equal(record.result, 'running'); assert.equal(record.rung, RUNGS[0]);
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, true]]);
  assert.equal(record.loaded.commit, 'abc1234');
  assert.ok(record.down_at && record.back_at);
});

test('a start that fails goes one rung down and the record says she fell back and why', async () => {
  const w = world({ starts: ['ready', 'exit'], events: [{ request: { asked: 'xiaoman', why: 'publish' } }],
                    reverts: { 1: ['core: returned to the previous running version'] } });
  await supervise(w.d);
  const [record] = w.records;
  assert.equal(record.result, 'fell_back');
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, false], [1, true]]);
  assert.match(record.attempts[0].reason, /exited before it was ready/);
  assert.deepEqual(record.reverted, ['core: returned to the previous running version']);
});

test('the ladder ends on what is installed and keeps trying with a backoff; it never gives up', async () => {
  const w = world({ starts: ['ready', 'prepare', 'never', 'exit', 'exit'], events: [{ request: { asked: 'xiaoman', why: 'x' } }] });
  await supervise(w.d);
  const [record] = w.records;
  assert.deepEqual(record.attempts.map(a => [a.rung, a.ok]), [[0, false], [1, false], [2, false], [2, false], [2, true]]);
  assert.match(record.attempts[0].reason, /could not be prepared: packing failed/);
  assert.match(record.attempts[1].reason, /not ready within/);
  assert.deepEqual(w.slept, [60000, 300000]);
  assert.equal(record.result, 'fell_back');
});

test('a drill fails its first start on purpose and is back on the same packages', async () => {
  const w = world({ events: [{ request: { asked: 'xiaoman', why: 'drill', drill: true } }] });
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
