// ADR-009 D-6: Asuna mounts DSH Schedule only when the Host has none and mountSchedule allows it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { CognitionCore } from '../src/index.js';

function fakeHost(existing) {
  const services = existing ? { schedule: existing } : {};
  const mounted = [];
  const ctx = {
    get: name => services[name],
    plugin: async plugin => { mounted.push(plugin); services.schedule = { mountedBy: 'asuna' }; },
    inject: (deps, callback) => callback({ schedule: services.schedule }),
  };
  return { ctx, mounted, services };
}

test('T6.3 mountSchedule=false never mounts Schedule; plans are off', async () => {
  const host = fakeHost();
  const core = new CognitionCore(host.ctx, { mountSchedule: false });
  assert.equal(await core.attachSchedule(), false);
  assert.equal(host.mounted.length, 0);
  assert.equal(host.services.schedule, undefined);
  assert.equal(core.schedules.ctx, host.ctx, 'no schedule context was attached');
});

test('T6.3 mountSchedule=true mounts exactly once when the Host has none, and reuses an installed one', async () => {
  const host = fakeHost();
  const core = new CognitionCore(host.ctx, { mountSchedule: true });
  assert.equal(await core.attachSchedule(), true);
  assert.equal(await core.attachSchedule(), true);
  assert.equal(host.mounted.length, 1);
  assert.equal(core.schedules.ctx.schedule.mountedBy, 'asuna');
  const installed = fakeHost({ installed: true });
  const other = new CognitionCore(installed.ctx, {});
  assert.equal(await other.attachSchedule(), true, 'default is true');
  assert.equal(installed.mounted.length, 0);
  assert.equal(other.schedules.ctx.schedule.installed, true);
});
