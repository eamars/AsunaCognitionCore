// Every cleanup a plugin registers runs when its scope is disposed. Cordis emits no `dispose` event, so a cleanup
// registered with ctx.on('dispose', ...) never ran: an unloaded core left its worker running, and an unloaded
// persona or channel package kept its registration, so loading it again threw "Duplicate". Cleanups are effects.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import { CognitionCore, apply as applyCore } from '../src/index.js';
import * as Persona from '../../../tests/fixtures/personas/demo/src/index.js';
import * as Channel from '../../channels/agent-line/src/index.js';

test('disposing the core plugin runs its teardown', async () => {
  const ctx = new Context();
  ctx.provide('asunaFloor', { dataRoot: '/unused' });
  let core;
  const fiber = await ctx.plugin({ name: 'core-under-test', apply(scope) {
    applyCore(scope, {});
    core = scope.asuna;
  } });
  assert.equal(typeof ctx.asunaFloor.activateRecovery, 'function');
  let disposed = 0;
  core.dispose = async () => { disposed++; };
  await fiber.dispose();
  assert.equal(disposed, 1, 'core.dispose() ran: the worker and its sessions stop with the plugin');
  assert.equal(ctx.asunaFloor.activateRecovery, undefined);
  await ctx.fiber.dispose();
});

test('a persona or channel package unregisters when disposed and loads again', async () => {
  const ctx = new Context();
  const core = new CognitionCore(ctx, {});
  ctx.provide('asuna', core);
  for (const [plugin, registered] of [[Persona, () => core.personas.has('demo')], [Channel, () => core.channels.has('agent')]]) {
    const first = await ctx.plugin(plugin);
    assert.ok(registered(), plugin.name + ' registered');
    await first.dispose();
    assert.ok(!registered(), plugin.name + ' unregistered on dispose');
    const again = await ctx.plugin(plugin);       // a reload: no "Duplicate" from a registration left behind
    assert.ok(registered(), plugin.name + ' registered again');
    await again.dispose();
  }
  await ctx.fiber.dispose();
});
