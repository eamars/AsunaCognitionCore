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
    list: async ({ sessionId }) => [record].filter(row => row.sessionId === sessionId)
      .map(({ sessionId: _s, status: _st, lastDelivery: _l, ...stored }) => stored),
    update: async request => { calls.push(request);
      record = { ...record, ...(request.change ?? {}), ...(request.change ? { kind: request.change.kind } : {}),
        ...(request.title ? { title: request.title } : {}) };
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
  // The record as stored, never a catalog entry (Schedule refuses one as an invalid record).
  assert.equal('status' in h.calls[0].expected || 'sessionId' in h.calls[0].expected, false);
  await h.schedules.refresh(h.agent);
  const ops = h.events.filter(e => e.type === 'asuna/schedule').map(e => e.data.operation);
  assert.deepEqual(ops, ['create', 'update']);
  assert.equal(h.events.at(-1).data.schedule.daily.time, '10:15:00');
});

test('ADR-012: a task is named as she reads it, and what DSH changes is logged as an update', async () => {
  const h = harness();
  const created = [];
  h.schedules.ctx.schedule.create = async (sessionId, request) => { created.push(request);
    return { id: 'n2', ...request, kind: 'every', everySeconds: request.every_seconds, scheduledAt: '2026-01-02T10:00:00Z' }; };
  await h.schedules.request({ session_id: 's', path: '/schedule/create',
    payload: { plan_id: 'plan-asuna-presence', title: '心跳 · Heartbeat', every_seconds: 3600 } });
  assert.equal(created[0].title, '心跳 · Heartbeat');
  assert.equal(created[0].prompt, 'ASUNA_PLAN:plan-asuna-presence');
  // A title-only update sends no timing change.
  await h.schedules.request({ session_id: 's', path: '/schedule/update', payload: { id: 'n1', title: 'Named' } });
  assert.equal(h.calls.at(-1).title, 'Named');
  assert.equal('change' in h.calls.at(-1), false);
  // DSH moves the next target after a delivery: the next refresh logs the record as it is now, once.
  const before = h.events.length;
  h.schedules.ctx.schedule.catalog = async () => [{ id: 'n1', sessionId: 's', prompt: 'ASUNA_PLAN:p1', kind: 'daily',
    status: 'active', daily: { time: '09:00:00', time_zone: 'UTC' }, scheduledAt: '2026-01-03T09:00:00Z', title: 'Named' }];
  await h.schedules.refresh(h.agent);
  await h.schedules.refresh(h.agent);
  const logged = h.events.slice(before).filter(e => e.data.operation === 'update');
  assert.equal(logged.length, 1);
  assert.equal(logged[0].data.schedule.scheduledAt, '2026-01-03T09:00:00Z');
});

test('an update that changes nothing answers with the record, not a status', async () => {
  // Regression: a wording-only change of a daily plan sent the same timing; DSH answered {updated: false, record}
  // and the worker read the record's fields off that status (KeyError 'scheduledAt').
  const h = harness();
  h.schedules.ctx.schedule.update = async request => { h.calls.push(request);
    return { id: 'n1', updated: false, record: request.expected }; };
  const before = h.events.length;
  const result = await h.schedules.request({ session_id: 's', path: '/schedule/update', payload: { id: 'n1', title: 'Same' } });
  assert.equal(result.id, 'n1');
  assert.equal(result.scheduledAt, '2026-01-02T09:00:00Z');
  assert.equal(h.events.length, before, 'a no-op is not logged as an update');
});

test('reminders queued in the scheduler session are removed once read; one arriving meanwhile stays', async () => {
  // Regression: DSH claims one queued reminder per turn, so reminders that arrived during a turn stayed in the
  // scheduler session's queue for good (the owner saw "4 queued messages"). Delivery reads the log, not the queue.
  const h = harness();
  const reminder = id => ({ id, source: { kind: 'schedule' }, content: [{ type: 'text',
    text: '[SCHEDULE REMINDER BATCH]\nreminders_json: ' + JSON.stringify([{ schedule_id: 'n1', occurrence_at: id }]) }] });
  let queue = [reminder('old-1'), reminder('old-2')];
  for (const message of queue) h.events.push({ type: 'agent/inbox/spliced', seq: h.events.length + 1,
    data: { target: 'next-turn', start: 0, inserted: [message] } });
  h.agent.inbox = { get nextTurn() { return queue; }, remove: id => { queue = queue.filter(m => m.id !== id); return true; } };
  const delivered = [];
  h.schedules.core = { ready: async () => {}, worker: { call: async (method, args) => {
    delivered.push(args.id);
    if (delivered.length === 1) queue = [...queue, reminder('arrived-meanwhile')];
  } } };
  await h.schedules.delivered(h.agent);
  assert.deepEqual(queue.map(m => m.id), ['arrived-meanwhile']);
  assert.ok(delivered.length >= 2, 'both queued reminders were delivered from the log');
});
