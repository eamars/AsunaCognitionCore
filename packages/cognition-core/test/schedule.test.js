// ADR-009 D-5: native schedule_update in place, logged so reconciliation never sees delete + create.
import test from 'node:test';
import assert from 'node:assert/strict';
import { NativeSchedules } from '../src/schedule.js';

function harness() {
  const events = [];
  let record = { id: 'n1', sessionId: 's', prompt: 'ASUNA_PLAN:p1', kind: 'daily', status: 'active',
    daily: { time: '09:00:00', time_zone: 'UTC' }, scheduledAt: '2026-01-02T09:00:00Z' };
  const agent = { session: { id: 's', append: (type, data) => events.push({ type, data, seq: events.length + 1 }),
    snapshotEvents: () => events } };
  const calls = [];
  const ctx = { sessions: { flush: async () => {} }, schedule: {
    catalog: async () => [record],
    update: async request => { calls.push(request); record = { ...record, ...request.change, kind: request.change.kind };
      return { id: record.id, updated: true, record }; },
  } };
  const schedules = new NativeSchedules({ ctx, config: {} });
  schedules.agent = async () => agent;
  events.push({ type: 'asuna/schedule', seq: 1, data: { operation: 'create', schedule: { ...record } } });
  return { schedules, agent, events, calls };
}

test('T5.8 schedule_update changes timing in place and reconciliation keeps one live record', async () => {
  const h = harness();
  const result = await h.schedules.request({ session_id: 's', path: '/schedule/update',
    payload: { id: 'n1', change: { kind: 'daily', daily: { time: '10:15:00', time_zone: 'UTC' } } } });
  assert.equal(result.id, 'n1');
  assert.equal(h.calls[0].expected.id, 'n1');
  await h.schedules.refresh(h.agent);
  const ops = h.events.filter(e => e.type === 'asuna/schedule').map(e => e.data.operation);
  assert.deepEqual(ops, ['create', 'update']);
  assert.equal(h.events.at(-1).data.schedule.daily.time, '10:15:00');
});
