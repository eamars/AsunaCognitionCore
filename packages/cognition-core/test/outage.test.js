import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { FILE, KEPT, cameBack, exitCause, openSpan, startCause, stopInside, wentDown } from '../src/outage.js';

function folder(t) {
  const dir = mkdtempSync(path.join(tmpdir(), 'asuna-outage-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}
const read = dir => JSON.parse(readFileSync(path.join(dir, FILE), 'utf8'));

test('a cause is a kind and a name, never the error text', () => {
  assert.equal(startCause(new Error('AutoReconnect: 192.0.2.10:27017: [WinError 10054] reset')), 'start_failed:AutoReconnect');
  assert.equal(startCause(new Error('Traceback ...\nValueError: DATABASE_IN_USE: other on host')), 'start_failed:DATABASE_IN_USE');
  assert.equal(startCause(new Error('   ')), 'start_failed:Error');
  assert.equal(exitCause(new Error('Asuna business worker exited (1): MemoryError')), 'exited:1');
  assert.equal(exitCause(new Error('Asuna business worker exited (null)')), 'exited:none');
  assert.equal(exitCause(new Error('spawn ENOENT')), 'unknown');
});

test('a span opens at the first failure and keeps its start and cause while more follow', t => {
  const dir = folder(t);
  assert.equal(openSpan(dir), null);
  wentDown(dir, 'start_failed:AutoReconnect', undefined, new Date('2026-10-27T06:29:45Z'));
  wentDown(dir, 'exited:1', undefined, new Date('2026-10-27T08:44:22Z'));
  assert.deepEqual(read(dir), { since: '2026-10-27T06:29:45.000Z', cause: 'start_failed:AutoReconnect', tries: 2, inside: 0 });
  stopInside(dir);
  assert.equal(read(dir).inside, 1);
});

test('a completed start hands the span over and removes it; a failed hand-over keeps it for the next', async t => {
  const dir = folder(t);
  const warned = [];
  wentDown(dir, 'exited:1');
  assert.equal(await cameBack(dir, async () => { throw new Error('AutoReconnect: reset'); }, text => warned.push(text)), KEPT);
  assert.ok(existsSync(path.join(dir, FILE)), 'kept: the next completed start hands it over');
  assert.match(warned[0], /^Asuna: the span she was down since .* is not recorded yet; it is handed over again/);
  const sent = [];
  assert.deepEqual(await cameBack(dir, async span => { sent.push(span); return { stop_id: 'down-x' }; }), { stop_id: 'down-x' });
  assert.equal(sent[0].cause, 'exited:1');
  assert.ok(!existsSync(path.join(dir, FILE)));
  assert.equal(await cameBack(dir, async () => assert.fail('no span, no call')), null);
});

test('a file that cannot be read is a span whose start is not known, said, not dropped', t => {
  const dir = folder(t);
  writeFileSync(path.join(dir, FILE), '{not json');
  const warned = [];
  const span = openSpan(dir, text => warned.push(text));
  assert.equal(span.since, null);
  assert.equal(span.cause, 'unknown');
  assert.ok(span.opened);
  assert.match(warned[0], /^Asuna: worker-down\.json could not be read/);
  wentDown(dir, 'exited:1');
  assert.deepEqual([read(dir).since, read(dir).cause, read(dir).tries], [null, 'unknown', 2]);
});

test('the core opens the span on a failed start and counts a worker exit as a try of the same span', async t => {
  const dir = folder(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { CognitionCore } = await import('../src/index.js');
  const core = new CognitionCore({ logger: { warn() {}, info() {} }, asunaFloor: { dataRoot: dir } },
    { persona: 'p', deployment: {} });
  core.personas.set('p', {});
  core.workerPython = async () => { throw new Error('AutoReconnect: 192.0.2.10:27017: reset'); };
  await assert.rejects(core.ready());
  assert.deepEqual([read(dir).cause, read(dir).tries], ['start_failed:AutoReconnect', 1]);
  assert.doesNotMatch(readFileSync(path.join(dir, FILE), 'utf8'), /192\.0\.2/, 'no address in the file either');
  core.restart = async () => {};
  core.workerFailed(new Error('Asuna business worker exited (1)'));
  assert.deepEqual([read(dir).cause, read(dir).tries, core.workerExited], ['start_failed:AutoReconnect', 2, true]);
  core.unloaded = true; clearTimeout(core.startTimer); clearTimeout(core.restartTimer);
});

test('a data folder it cannot write to costs the record, never the start: nothing throws, and it says so', t => {
  const dir = path.join(folder(t), 'gone');                      // a folder that is not there (read-only, unmounted)
  const warned = [];
  assert.doesNotThrow(() => wentDown(dir, 'exited:1', text => warned.push(text)));
  assert.doesNotThrow(() => stopInside(dir, text => warned.push(text)));
  assert.equal(openSpan(dir), null);
  assert.match(warned[0], /^Asuna: worker-down\.json was not written \(ENOENT\)/);
});

test('every write is whole: no temporary file is left beside the span', async t => {
  const dir = folder(t);
  wentDown(dir, 'exited:1'); wentDown(dir, 'exited:2'); stopInside(dir);
  const { readdirSync } = await import('node:fs');
  assert.deepEqual(readdirSync(dir), [FILE]);
  assert.deepEqual([read(dir).cause, read(dir).tries, read(dir).inside], ['exited:1', 2, 1]);
});

test('a worker without host.came_back (an older core) leaves the span for a newer one', async t => {
  const dir = folder(t);
  wentDown(dir, 'start_failed:AutoReconnect');
  const older = async () => { throw new Error('UNKNOWN_BUSINESS_METHOD'); };
  assert.equal(await cameBack(dir, older), KEPT);
  assert.equal(read(dir).cause, 'start_failed:AutoReconnect');
});

test('a hand-over that failed is tried again while that worker runs, never holding up its start', async t => {
  const dir = folder(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { CognitionCore, HANDOVER_SECONDS } = await import('../src/index.js');
  const core = new CognitionCore({ logger: { warn() {}, info() {} }, asunaFloor: { dataRoot: dir } }, {});
  wentDown(dir, 'start_failed:AutoReconnect');
  const calls = [];
  core.worker = { closed: false, call: async (method, span) => {
    calls.push(method);
    if (calls.length === 1) throw new Error('AutoReconnect: reset');
    return { stop_id: 'down-x' };
  } };
  core.handOver();
  const settle = () => new Promise(resolve => setImmediate(resolve));
  await settle();
  assert.deepEqual(calls, ['host.came_back']);
  assert.ok(existsSync(path.join(dir, FILE)), 'kept after the failed hand-over');
  t.mock.timers.tick(HANDOVER_SECONDS * 1000);
  await settle();
  assert.deepEqual(calls, ['host.came_back', 'host.came_back']);
  assert.ok(!existsSync(path.join(dir, FILE)), 'recorded the second time, and removed');
  // A worker replaced or closed meanwhile gets no further tries; the next start hands it over.
  wentDown(dir, 'exited:1');
  let old = 0;
  core.worker = { closed: false, call: async () => { old++; throw new Error('reset'); } };
  core.handOver();
  await settle();
  core.worker = { closed: false, call: async () => assert.fail('the timer hands over to the worker it began with') };
  t.mock.timers.tick(HANDOVER_SECONDS * 1000);
  await settle();
  assert.equal(old, 1, 'the replaced worker is not called again');
  core.unloaded = true; clearTimeout(core.handOverTimer);
});

test('a span file past the size cap is a span whose start is not known, as the worker reads it', async t => {
  const dir = folder(t);
  const { SPAN_BYTES } = await import('../src/outage.js');
  writeFileSync(path.join(dir, FILE), JSON.stringify({ since: '2026-10-27T06:29:45Z', cause: 'exited:1', pad: 'x'.repeat(SPAN_BYTES) }));
  const span = openSpan(dir);
  assert.deepEqual([span.since, span.cause], [null, 'unknown'], 'the same as host_stops.open_span past SPAN_BYTES');
  assert.ok(readFileSync(path.join(dir, FILE)).length < 200, 'replaced by the small span both sides read alike');
});

test('a recorded span whose file cannot be removed says it was recorded, not that it was not', async t => {
  const dir = folder(t);
  const { mkdirSync } = await import('node:fs');
  wentDown(dir, 'exited:1');
  const warned = [];
  const answer = await cameBack(dir, async () => {
    rmSync(path.join(dir, FILE)); mkdirSync(path.join(dir, FILE));       // a folder there now: unlink cannot remove it
    return { stop_id: 'down-x' };
  }, text => warned.push(text));
  assert.deepEqual(answer, { stop_id: 'down-x' });
  assert.match(warned[0], /^Asuna: the span was recorded, but worker-down\.json could not be removed \(\w+\); the next start hands it over again and writes no second row$/);
});

test('the hand-over runs beside a start: it returns at once, and ready() does not wait for it', async t => {
  const dir = folder(t);
  const { CognitionCore } = await import('../src/index.js');
  const core = new CognitionCore({ logger: { warn() {}, info() {} }, asunaFloor: { dataRoot: dir } }, {});
  wentDown(dir, 'exited:1');
  core.worker = { closed: false, call: () => new Promise(() => {}) };       // a database that never answers
  assert.equal(core.handOver(), undefined, 'not a promise anyone could wait on');
  const source = readFileSync(new URL('../src/index.js', import.meta.url), 'utf8');
  assert.match(source, /await this\.worker\.call\('navigation\.ready'\);\n\s+this\.startFailures = 0;\n(\s+\/\/[^\n]*\n)*\s+this\.handOver\(\);/,
    'ready() calls it after navigation.ready without await');
  core.unloaded = true;
});

test('a failure said once: the same span failing the same way is one line however its text changes', async t => {
  const dir = folder(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { CognitionCore, HANDOVER_SECONDS } = await import('../src/index.js');
  const warned = [];
  const core = new CognitionCore({ logger: { warn: text => warned.push(text), info() {} }, asunaFloor: { dataRoot: dir } }, {});
  wentDown(dir, 'exited:1');
  // A database error as it really comes: its id, time and port change at every try (her review: a fixed text would
  // prove only that a fixed text is said once).
  let tries = 0;
  const failing = () => async () => {
    tries++;
    throw new Error('ServerSelectionTimeoutError: 192.0.2.10:' + (27017 + tries) + ': timed out after ' + (5000 + tries)
      + 'ms, Topology Description: <TopologyDescription id: 6531a0f' + tries + 'c2e, topology_type: Unknown>');
  };
  core.worker = { closed: false, call: failing() };
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const said = () => warned.filter(text => text.startsWith('Asuna: the span she was down since'));
  core.handOver();
  for (let i = 0; i < 3; i++) { await settle(); t.mock.timers.tick(HANDOVER_SECONDS * 1000); }
  await settle();
  assert.equal(tries, 4);
  assert.equal(said().length, 1, 'four different texts of one failure: one line');
  // Another kind of failure on the same span is said again: a new cause is never silenced.
  core.worker.call = async () => { throw new Error('UNKNOWN_BUSINESS_METHOD'); };
  t.mock.timers.tick(HANDOVER_SECONDS * 1000);
  await settle(); t.mock.timers.tick(HANDOVER_SECONDS * 1000); await settle();
  assert.equal(said().length, 2);
  assert.match(said()[1], /UNKNOWN_BUSINESS_METHOD$/);
  assert.ok(existsSync(path.join(dir, FILE)), 'still kept for a newer worker');
  core.unloaded = true; clearTimeout(core.handOverTimer);
});

test('a planned in-place restart opens no span', async t => {
  const dir = folder(t);
  const { CognitionCore } = await import('../src/index.js');
  const core = new CognitionCore({ logger: { warn() {}, info() {} }, asunaFloor: { dataRoot: dir } }, {});
  core.worker = { onFailure: null, dispose: async () => {} };
  core.ready = async () => {};
  for (const reason of ['worker asked: published-worker', 'settings applied', 'recovery activated core'])
    await core.restart(reason);
  assert.equal(openSpan(dir), null);
});
