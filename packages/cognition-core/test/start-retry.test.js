import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore, START_RETRY_SECONDS } from '../src/index.js';

// A core whose start fails at its first step, as a database reset during the first minute does.
function failing() {
  const logs = [];
  const core = new CognitionCore({ logger: { warn: (...args) => logs.push(args), info() {} } },
    { persona: 'p', deployment: {} });
  core.personas.set('p', {});
  core.starts = 0;
  core.workerPython = async () => { core.starts++; throw new Error('AutoReconnect: connection reset'); };
  return { core, logs };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('a failed start is reported and tried again, further apart each time', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { core, logs } = failing();
  await assert.rejects(core.ready(), /AutoReconnect/);
  assert.equal(core.lifecycle.state, 'failed');
  assert.equal(core.initializing, null, 'the failure is not kept for the next caller');
  assert.deepEqual(logs.at(-1).slice(1), [1, 'Error: AutoReconnect: connection reset', START_RETRY_SECONDS[0]]);
  assert.match(logs.at(-1)[0], /^Asuna worker could not start/);
  t.mock.timers.tick(START_RETRY_SECONDS[0] * 1000 - 1);
  await settle();
  assert.equal(core.starts, 1);
  t.mock.timers.tick(1);
  await settle();
  assert.equal(core.starts, 2);
  assert.deepEqual(logs.at(-1).slice(1, 2), [2]);
  assert.equal(logs.at(-1)[3], START_RETRY_SECONDS[1]);
  // Past the list, every try waits the last delay.
  core.startFailures = 99;
  core.startAgain(new Error('again'));
  assert.equal(logs.at(-1)[3], START_RETRY_SECONDS.at(-1));
  core.unloaded = true; clearTimeout(core.startTimer);
});

test('a caller after a failed start starts afresh at once', async () => {
  const { core } = failing();
  await assert.rejects(core.ready());
  await assert.rejects(core.ready());
  assert.equal(core.starts, 2);
  core.unloaded = true; clearTimeout(core.startTimer);
});

test('a scheduled try does nothing while a start or restart is under way, or after the plugin is gone', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { core } = failing();
  await assert.rejects(core.ready());
  core.restarting = Promise.resolve();
  t.mock.timers.tick(START_RETRY_SECONDS[0] * 1000);
  await settle();
  assert.equal(core.starts, 1, 'the restart brings it up');
  core.restarting = null;
  core.startAgain(new Error('again'));
  core.initializing = new Promise(() => {});
  t.mock.timers.tick(START_RETRY_SECONDS.at(-1) * 1000);
  await settle();
  assert.equal(core.starts, 1, 'a start already running');
  core.initializing = null;
  core.unloaded = true;
  core.startAgain(new Error('gone'));
  t.mock.timers.tick(START_RETRY_SECONDS.at(-1) * 1000);
  await settle();
  assert.equal(core.starts, 1, 'a disposed plugin schedules nothing');
});

test('a profile waiting for its settings is not retried', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { core, logs } = failing();
  core.personas.clear();
  await assert.rejects(core.ready(), /Select an installed Asuna persona/);
  assert.equal(core.lifecycle.state, 'unconfigured');
  t.mock.timers.tick(START_RETRY_SECONDS.at(-1) * 1000);
  await settle();
  assert.equal(core.starts, 0);
  assert.equal(logs.length, 0);
});

test('a worker that exits is restarted by itself while the plugin is loaded', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const core = new CognitionCore({ logger: { warn() {}, info() {} } }, {});
  const reasons = [];
  core.restart = async reason => { reasons.push(reason); };
  core.lifecycle.restarts = 7;                 // restarts of other kinds (her publications) do not use up its tries
  core.workerFailed(new Error('Asuna business worker exited (1)'));
  t.mock.timers.tick(START_RETRY_SECONDS[0] * 1000 - 1);
  await settle();
  assert.deepEqual(reasons, []);
  t.mock.timers.tick(1);
  await settle();
  assert.deepEqual(reasons, ['worker failed: Error: Asuna business worker exited (1)']);
  core.unloaded = true;
  core.workerFailed(new Error('after unload'));
  t.mock.timers.tick(START_RETRY_SECONDS.at(-1) * 1000);
  await settle();
  assert.equal(reasons.length, 1);
});
