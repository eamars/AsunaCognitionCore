import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { FILE, LOG, LOG_BYTES, LOG_KEPT_BYTES, appendLog, asked, cameUp, causeOf, entries } from '../src/restart-tell.js';

function folder(t) {
  const dir = mkdtempSync(path.join(tmpdir(), 'asuna-restarts-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}
const read = dir => JSON.parse(readFileSync(path.join(dir, FILE), 'utf8'));
const settle = () => new Promise(resolve => setImmediate(resolve));
const HELD = { since: '2026-10-30T10:25:00.000Z', steps: [{ by: ['task'], since: '2026-10-30T10:25:00.000Z', task_id: 't1' }],
  changes: 1 };

async function core(t, dir) {
  const { CognitionCore } = await import('../src/index.js');
  const warned = [];
  const made = new CognitionCore({ logger: { warn: text => warned.push(text), info() {} }, asunaFloor: { dataRoot: dir } }, {});
  made.warned = warned;
  made.starts = [];
  made.ready = async at => { made.starts.push(at); };       // a real start would run a worker; ready()'s part is below
  t.after(() => { made.unloaded = true; clearTimeout(made.handOverTimer); });
  return made;
}

test('a cause is a kind of the closed list; a worker that failed is not told', () => {
  assert.equal(causeOf('worker asked: published-worker'), 'published');
  assert.equal(causeOf('settings applied'), 'settings');
  assert.equal(causeOf('settings restored after a failed apply'), 'settings_restored');
  assert.equal(causeOf('recovery activated core'), 'recovery:core');
  assert.equal(causeOf('recovery activated Core/../x'), 'unknown');
  assert.equal(causeOf('a restart requested during the last one'), 'again');
  assert.equal(causeOf('worker asked: unspecified'), 'unknown');
  assert.equal(causeOf('worker failed: Error: Asuna business worker exited (1)'), null);
});

test('a worker-asked restart writes its entry with what held it, and an older worker\'s with held_sent false', async t => {
  const dir = folder(t);
  const made = await core(t, dir);
  await made.onEvent({ kind: 'restart_requested', reason: 'published-worker', held: HELD });
  await made.onEvent({ kind: 'restart_requested', reason: 'published-worker' });          // an older worker: no `held`
  await made.restart('settings applied');
  await made.restart('worker failed: Error: Asuna business worker exited (1)');
  const list = read(dir);
  assert.deepEqual(list.map(entry => [entry.cause, entry.held, entry.held_sent]),
    [['published', HELD, true], ['published', null, false], ['settings', null, true]]);
  assert.deepEqual(made.starts, [list[0].at, list[1].at, list[2].at, null], 'each start knows the restart it runs');
});

test('a completed restart stamps back and hands it over; the worker\'s answer removes it', async t => {
  const dir = folder(t);
  const made = await core(t, dir);
  await made.onEvent({ kind: 'restart_requested', reason: 'published-worker', held: HELD });
  const [at] = made.starts;
  // What ready() does when the start it runs completes (the source check below holds it there, before handOver).
  cameUp(dir, at, made.warnLine);
  assert.ok(read(dir)[0].back);
  const source = readFileSync(new URL('../src/index.js', import.meta.url), 'utf8');
  assert.match(source, /ready\(restartAt = null\)[\s\S]*?await this\.worker\.call\('navigation\.ready'\);[\s\S]*?this\.tellFile\(dataRoot => cameUp\(dataRoot, restartAt, this\.warnLine\)\);\n\s+this\.handOverSaid = new Set\(\);\n\s+this\.handOver\(\);/);
  assert.match(source, /await this\.ready\(kept \? entry\.at : null\);/);
  const sent = [];
  made.worker = { closed: false, call: async (method, args) => {
    sent.push([method, args]);
    return method === 'host.restarted' ? { recorded: args.restarts.map(entry => entry.at) } : null;
  } };
  made.handOver();
  await settle(); await settle();
  assert.deepEqual(sent.map(([method]) => method), ['host.restarted'], 'no span open: only the restarts');
  assert.deepEqual(sent[0][1].restarts.map(entry => [entry.at, entry.cause, entry.held_sent]), [[at, 'published', true]]);
  assert.deepEqual(read(dir), []);
});

test('a hand-over that failed keeps the entries, is tried again, and is said once', async t => {
  const dir = folder(t);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { HANDOVER_SECONDS } = await import('../src/index.js');
  const made = await core(t, dir);
  await made.restart('settings applied');
  cameUp(dir, made.starts[0]);
  let tries = 0;
  made.worker = { closed: false, call: async () => { tries++; throw new Error('UNKNOWN_BUSINESS_METHOD'); } };
  made.handOver();
  for (let i = 0; i < 3; i++) { await settle(); await settle(); t.mock.timers.tick(HANDOVER_SECONDS * 1000); }
  await settle(); await settle();
  assert.equal(tries, 4);
  assert.equal(made.warned.filter(text => text.includes('worker restart(s) are not recorded yet')).length, 1);
  assert.equal(read(dir).length, 1, 'kept for a newer worker');
});

test('a failed start removes its entry: the outage says it', async t => {
  const dir = folder(t);
  const made = await core(t, dir);
  made.ready = async () => { throw new Error('AutoReconnect: reset'); };
  await assert.rejects(made.restart('settings applied'), /AutoReconnect/);
  assert.deepEqual(read(dir), []);
  assert.equal(made.restarting, null);
});

test('an entry left without back by an earlier Host goes at a completed start', t => {
  const dir = folder(t);
  writeFileSync(path.join(dir, FILE), JSON.stringify([
    { at: '2026-10-30T10:37:06.295Z', cause: 'published', held: null, held_sent: true },          // Host stopped mid-way
    { at: '2026-10-30T10:39:59.338Z', cause: 'published', held: null, held_sent: true, back: '2026-10-30T10:40:30.000Z' },
  ]));
  cameUp(dir, null);                                                                  // a start no restart ran
  assert.deepEqual(read(dir).map(entry => entry.at), ['2026-10-30T10:39:59.338Z']);
});

test('a queued request keeps its reason and held, and a throw leaves no flag behind', async t => {
  const dir = folder(t);
  const made = await core(t, dir);
  // A start that waits until released, and says when it has begun (the restart is then under way).
  const holding = (fail = false) => {
    let release, begun;
    const started = new Promise(resolve => { begun = resolve; });
    made.ready = async at => {
      made.starts.push(at); begun();
      await new Promise(resolve => { release = resolve; });
      made.ready = async next => { made.starts.push(next); };
      if (fail) throw new Error('AutoReconnect: reset');
    };
    return { started, release: () => release() };
  };
  let gate = holding();
  const first = made.restart('settings applied');
  await gate.started;
  await made.onEvent({ kind: 'restart_requested', reason: 'published-worker', held: HELD });      // during the restart
  gate.release(); await first;
  assert.deepEqual(read(dir).map(entry => [entry.cause, entry.held]), [['settings', null], ['published', HELD]]);
  // One queued with no reason of its own is `again`.
  gate = holding();
  const second = made.restart('settings applied');
  await gate.started;
  await made.onEvent({ kind: 'restart_requested', held: null });
  gate.release(); await second;
  assert.equal(read(dir).at(-1).cause, 'again');
  // A restart that throws consumes what was queued: a later, unrelated one is not followed by a false `again`.
  gate = holding(true);
  const failing = made.restart('settings applied');
  await gate.started;
  await made.onEvent({ kind: 'restart_requested', reason: 'published-worker', held: HELD });
  gate.release();
  await assert.rejects(failing);
  assert.equal(made.restartAgain, null);
  const before = read(dir).length;
  await made.restart('settings applied');
  assert.deepEqual(read(dir).slice(before).map(entry => entry.cause), ['settings'], 'no `again` after it');
});

test('two restart() calls at once run one restart', async t => {
  const dir = folder(t);
  const made = await core(t, dir);
  const one = made.restart('settings applied'), two = made.restart('worker asked: published-worker');
  await Promise.all([one, two]);
  assert.equal(made.starts.length, 1);
  assert.equal(read(dir).length, 1);
});

test('the file keeps at most 50 restarts, saying the one dropped; a torn file is read as empty and replaced', t => {
  const dir = folder(t);
  const warned = [];
  for (let i = 0; i < 51; i++) asked(dir, { at: 'at-' + i, cause: 'published', held: null, held_sent: true }, text => warned.push(text));
  assert.equal(read(dir).length, 50);
  assert.equal(read(dir)[0].at, 'at-1');
  assert.match(warned[0], /^Asuna: restarts-to-tell\.json keeps 50 restarts; the one at at-0 was dropped/);
  writeFileSync(path.join(dir, FILE), '[{"at": "x"');
  warned.length = 0;
  assert.deepEqual(entries(dir, text => warned.push(text)), []);
  assert.equal(warned.length, 1);
  assert.deepEqual(read(dir), []);
});

test('the owner\'s log past 256 KB keeps its newest 128 KB, cut at a line', async t => {
  const dir = folder(t);
  const line = JSON.stringify({ at: '2026-10-30T10:37:06.295Z', reason: 'worker asked: published-worker' }) + '\n';
  writeFileSync(path.join(dir, LOG), line.repeat(Math.ceil(LOG_BYTES / line.length)));
  await appendLog(dir, { at: '2026-10-30T11:08:09.125Z', reason: 'last' });
  const kept = readFileSync(path.join(dir, LOG), 'utf8');
  assert.ok(statSync(path.join(dir, LOG)).size <= LOG_KEPT_BYTES);
  assert.ok(kept.length > LOG_KEPT_BYTES - line.length);
  assert.ok(kept.split('\n').filter(Boolean).every(text => JSON.parse(text)), 'every line whole');
  assert.equal(JSON.parse(kept.trim().split('\n').at(-1)).reason, 'last');
  assert.ok(!existsSync(path.join(dir, LOG + '.' + process.pid + '.tmp')));
});
