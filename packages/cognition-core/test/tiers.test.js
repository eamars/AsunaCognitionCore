import test from 'node:test';
import assert from 'node:assert/strict';
import { failureClass, restFor, resting } from '../src/tiers.js';

test('ADR-075: what a failure on 高 was decides whether the job falls and whether 高 rests', () => {
  // a stop and a context DSH compacts are not failures of 高
  assert.equal(failureClass('ABORTED'), null);
  assert.equal(failureClass('CONTEXT_WINDOW_EXCEEDED'), null);
  for (const code of ['SERVER', 'TIMEOUT', 'TRANSPORT', 'STREAM_CLOSED']) assert.equal(failureClass(code), 'down');
  assert.equal(failureClass('RATE_LIMIT'), 'busy');
  for (const code of ['AUTH', 'QUOTA', 'ACCOUNT_QUOTA', 'INVALID_CREDENTIAL', 'MISSING_CREDENTIAL']) assert.equal(failureClass(code), 'owner');
  // a provider's refusal arrives as an error end without a code of its own: anything else that ended the request
  for (const code of ['PI_AI_ERROR', 'EMPTY_RESPONSE', 'INVALID_REQUEST', undefined]) assert.equal(failureClass(code), 'refused');
});

test('ADR-075: a line failure rests 高 for its idle minutes, one waiting on the owner has no clock, a refusal none', () => {
  const now = Date.parse('2026-10-16T08:00:00Z');
  assert.equal(restFor('refused', 30, now), null);
  assert.deepEqual(restFor('down', 45, now), { reason: 'down', until: '2026-10-16T08:45:00.000Z' });
  assert.deepEqual(restFor('busy', undefined, now), { reason: 'busy', until: '2026-10-16T08:30:00.000Z' });
  assert.deepEqual(restFor('owner', 45, now), { reason: 'owner', until: null });
  assert.equal(resting(restFor('down', 45, now), now + 44 * 60000), true);
  assert.equal(resting(restFor('down', 45, now), now + 45 * 60000), false);
  assert.equal(resting(restFor('owner', 45, now), now + 999 * 60000), true);
  assert.equal(resting(null), false);
});

test('ADR-075: a job sent to 高 runs on its route until it falls, and 高 resting sends it 低 before its first request', async () => {
  const { CognitionCore } = await import('../src/index.js');
  const local = { provider: 'local', model: 'l' }, strong = { provider: 'remote', model: 'r', idleMinutes: 20 };
  const calls = [];
  const core = new CognitionCore({ get: () => undefined, logger: { warn() {} } }, { routes: { action: local, actionHigh: strong }, deployment: {} });
  core.worker = { call: async (method, args) => { calls.push([method, args]); return {}; } };
  const agent = (id, events = []) => ({ session: { id, snapshotEvents: () => events } });
  const high = { task: { _id: 'task-1', tier: 'high' } };
  assert.deepEqual(core.tierStatus(), { configured: true });
  assert.equal(core.tierRoute(agent('s1'), { task: { _id: 'task-0', tier: 'low' } }), undefined);
  assert.deepEqual(core.tierRoute(agent('s1'), high), strong);
  assert.equal(core.state('s1').onHigh, true);
  // a fall mid-run: recorded once, and the job stays 低
  core.fall(agent('s1', [{ type: 'assistant/message' }]), high.task, 'refused', 'PI_AI_ERROR');
  core.fall(agent('s1', [{ type: 'assistant/message' }]), high.task, 'down');
  assert.deepEqual(calls, [['tier.fell', { task_id: 'task-1', reason: 'refused', mid_run: true, code: 'PI_AI_ERROR' }]]);
  assert.equal(core.tierRoute(agent('s1'), high), undefined);
  // 高 resting: a new 高 job falls before its first request, not mid-run, and the card shows the rest
  core.restHigh({ reason: 'owner', until: null }, 'AUTH');
  assert.deepEqual(calls.at(-1), ['tier.rest', { reason: 'owner', until: null, code: 'AUTH' }]);
  assert.equal(core.tierRoute(agent('s2'), { task: { _id: 'task-2', tier: 'high' } }), undefined);
  assert.deepEqual(calls.at(-1), ['tier.fell', { task_id: 'task-2', reason: 'owner', mid_run: false }]);
  assert.deepEqual(core.tierStatus(), { configured: true, rest: { reason: 'owner', until: null } });
  // no 高 configured: nothing to route, nothing offered
  const plain = new CognitionCore({ get: () => undefined }, { routes: { action: local }, deployment: {} });
  assert.equal(plain.tierRoute(agent('s3'), high), undefined);
  assert.deepEqual(plain.tierStatus(), { configured: false });
  assert.equal(plain.routeFor('actionHigh'), undefined, 'no DSH default for 高');
});
