// ADR-009 D-5: native schedule_update in place, logged so reconciliation never sees delete + create.
import test from 'node:test';
import assert from 'node:assert/strict';
import { NativeSchedules } from '../src/schedule.js';

function harness() {
  const events = [];
  // DSH 0.2.2's Schedule: Host-wide tasks with a delivery target; changes go through edit, checked by revision.
  let record = { id: 'n1', target: { kind: 'session', sessionId: 's' }, prompt: 'ASUNA_PLAN:p1', kind: 'daily',
    status: 'active', time: '09:00:00', timeZone: 'UTC', scheduledAt: '2026-01-02T09:00:00Z',
    updatedAt: '2026-01-01T00:00:00.000Z' };
  const agent = { session: { id: 's', append: (type, data) => events.push({ type, data, seq: events.length + 1 }),
    snapshotEvents: () => events } };
  const calls = [];
  const ctx = { sessions: { flush: async () => {} }, schedule: {
    catalog: async () => [record],
    view: async ({ id }) => (id === record.id ? record : { id, code: 'schedule_not_found' }),
    edit: async (request, actor) => { calls.push({ request, actor });
      if (request.expectedUpdatedAt !== undefined && request.expectedUpdatedAt !== record.updatedAt)
        return { id: request.id, code: 'schedule_conflict' };
      if (request.action === 'delete') return { id: request.id, deleted: true };
      const timing = request.patch.timing;
      // DSH stores a daily or weekly timing flat (time, timeZone, weekdays) on the record.
      const clock = timing?.daily ?? timing?.weekly;
      record = { ...record, ...(timing ? { kind: timing.kind } : {}), ...(clock ? { time: clock.time, timeZone: clock.time_zone } : {}),
        ...(request.patch.title ? { title: request.patch.title } : {}), updatedAt: '2026-01-01T00:00:01.000Z' };
      return record; },
  } };
  const schedules = new NativeSchedules({ ctx, config: {} });
  schedules.agent = async () => agent;
  events.push({ type: 'asuna/schedule', seq: 1, data: { operation: 'create', schedule: { ...record } } });
  return { schedules, agent, events, calls };
}

test('T5.8 schedule_update changes timing in place, as her own session, and reconciliation keeps one live record', async () => {
  const h = harness();
  const result = await h.schedules.request({ session_id: 's', path: '/schedule/update',
    payload: { id: 'n1', change: { kind: 'daily', daily: { time: '10:15:00', time_zone: 'UTC' } } } });
  assert.equal(result.id, 'n1');
  assert.deepEqual(h.calls[0].request.patch, { timing: { kind: 'daily', daily: { time: '10:15:00', time_zone: 'UTC' } } });
  assert.equal(h.calls[0].request.expectedUpdatedAt, '2026-01-01T00:00:00.000Z', 'checked against the revision just read');
  assert.equal(h.calls[0].actor, 's', 'made as her scheduler session: DSH sends it no change notice');
  await h.schedules.refresh(h.agent);
  const ops = h.events.filter(e => e.type === 'asuna/schedule').map(e => e.data.operation);
  assert.deepEqual(ops, ['create', 'update']);
  assert.equal(h.events.at(-1).data.schedule.time, '10:15:00');
});

test('ADR-012: a task is named as she reads it, and what DSH changes is logged as an update', async () => {
  const h = harness();
  const created = [];
  h.schedules.ctx.schedule.create = async (request, actor) => { created.push({ request, actor });
    return { id: 'n2', ...request, kind: 'every', everySeconds: request.timing.every_seconds, scheduledAt: '2026-01-02T10:00:00Z' }; };
  await h.schedules.request({ session_id: 's', path: '/schedule/create',
    payload: { plan_id: 'plan-asuna-presence', title: '心跳 · Heartbeat', every_seconds: 3600 } });
  assert.equal(created[0].request.title, '心跳 · Heartbeat');
  assert.equal(created[0].request.prompt, 'ASUNA_PLAN:plan-asuna-presence');
  assert.deepEqual(created[0].request.timing, { kind: 'every', every_seconds: 3600 });
  assert.deepEqual(created[0].request.target, { kind: 'session', sessionId: 's' });
  assert.equal(created[0].actor, 's');
  // A title-only update sends no timing change.
  await h.schedules.request({ session_id: 's', path: '/schedule/update', payload: { id: 'n1', title: 'Named' } });
  assert.deepEqual(h.calls.at(-1).request.patch, { title: 'Named' });
  // DSH moves the next target after a delivery: the next refresh logs the record as it is now, once.
  const before = h.events.length;
  h.schedules.ctx.schedule.catalog = async () => [{ id: 'n1', target: { kind: 'session', sessionId: 's' }, prompt: 'ASUNA_PLAN:p1',
    kind: 'daily', status: 'active', time: '09:00:00', timeZone: 'UTC', scheduledAt: '2026-01-03T09:00:00Z', title: 'Named' }];
  await h.schedules.refresh(h.agent);
  await h.schedules.refresh(h.agent);
  const logged = h.events.slice(before).filter(e => e.data.operation === 'update');
  assert.equal(logged.length, 1);
  assert.equal(logged[0].data.schedule.scheduledAt, '2026-01-03T09:00:00Z');
});

test('an update that changes nothing answers with the record, and is not logged', async () => {
  // Regression: a wording-only change of a daily plan sent the same timing; the worker read the record's fields off
  // a status (KeyError 'scheduledAt'). DSH 0.2.2 answers every edit with the record.
  const h = harness();
  const before = h.events.length;
  const result = await h.schedules.request({ session_id: 's', path: '/schedule/update',
    payload: { id: 'n1', change: { kind: 'daily', daily: { time: '09:00:00', time_zone: 'UTC' } } } });
  assert.equal(result.id, 'n1');
  assert.equal(result.scheduledAt, '2026-01-02T09:00:00Z');
  assert.equal(h.events.length, before, 'a no-op is not logged as an update');
});

test('a change notice from DSH is never read as a firing; a finished one-shot leaves her log', async () => {
  const h = harness();
  const change = { id: 'notice', source: { kind: 'schedule' }, content: [{ type: 'text',
    text: '[SCHEDULE CHANGE]\nchange: updated\nschedule_id_json: "n1"\nschedule_title_json: "x"' }] };
  const firing = { id: 'fire', source: { kind: 'schedule' }, content: [{ type: 'text',
    text: '[SCHEDULE REMINDER]\nschedule_id_json: "n1"\noccurrence_at: 2026-01-02T09:00:00Z' }] };
  for (const message of [change, firing]) h.events.push({ type: 'agent/inbox/spliced', seq: h.events.length + 1,
    data: { target: 'next-turn', start: 0, inserted: [message] } });
  await h.schedules.refresh(h.agent);
  const dispatches = h.events.filter(e => e.data?.operation === 'dispatch');
  assert.deepEqual(dispatches.map(e => e.data.message_id), ['fire']);
  h.schedules.ctx.schedule.catalog = async () => [{ id: 'n1', target: { kind: 'session', sessionId: 's' }, prompt: 'ASUNA_PLAN:p1',
    kind: 'daily', status: 'ended', time: '09:00:00', timeZone: 'UTC', scheduledAt: '2026-01-02T09:00:00Z' }];
  await h.schedules.refresh(h.agent);
  assert.ok(h.events.some(e => e.data?.operation === 'delete' && e.data.id === 'n1'), 'an ended task leaves her log');
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
    delivered.push(...args.dispatches.map(d => d.id));
    if (delivered.length) queue = [...queue, reminder('arrived-meanwhile')];
  } } };
  await h.schedules.delivered(h.agent);
  assert.deepEqual(queue.map(m => m.id), ['arrived-meanwhile']);
  assert.ok(delivered.length >= 2, 'both queued reminders were delivered from the log');
});

test('each reading sends only the dispatches the worker has not had, in one call', async () => {
  // Regression: every reminder re-sent the whole dispatch history one call at a time, and the worker re-read the
  // native log for each; with 2,127 dispatches a reminder reached her ~100 s late, one arriving meanwhile later still.
  const h = harness();
  const reminder = (id, at) => ({ id, source: { kind: 'schedule' }, content: [{ type: 'text',
    text: '[SCHEDULE REMINDER BATCH]\nreminders_json: ' + JSON.stringify([{ schedule_id: 'n1', occurrence_at: at }]) }] });
  const arrive = (id, at) => h.events.push({ type: 'agent/inbox/spliced', seq: h.events.length + 1,
    data: { target: 'next-turn', start: 0, inserted: [reminder(id, at)] } });
  h.agent.inbox = { nextTurn: [], remove: () => true };
  const calls = [];
  h.schedules.core = { ready: async () => {}, worker: { call: async (method, args) => calls.push(args.dispatches) } };
  arrive('m1', '09:00'); arrive('m2', '09:05');
  await h.schedules.delivered(h.agent);
  arrive('m3', '09:10');
  await h.schedules.delivered(h.agent);
  await h.schedules.delivered(h.agent);
  assert.deepEqual(calls.map(batch => batch.length), [2, 1]);
  assert.ok(calls[1][0].seq > calls[0][1].seq);
});

test('the schedule session is read-only: it only delivers her plans and alarms', async () => {
  const { AsunaApi } = await import('../src/api.js');
  const headers = { 'asuna-scheduler-1': { cwd: '/data', agentPreset: 'asuna-scheduler' }, chat: { cwd: '/data' } };
  const sent = [];
  const core = { ready: async () => {},
    ctx: { sessions: { get: id => ({ header: headers[id] }) }, sessionPersistence: { stat: async () => null } },
    worker: { call: async (method, args) => { sent.push(args); return { chat: { key: 'internal' } }; } } };
  const policies = await AsunaApi.prototype.inputPolicies.call({ core }, ['asuna-scheduler-1', 'chat']);
  assert.deepEqual(policies, { 'asuna-scheduler-1': { key: 'schedules' }, chat: { key: 'internal' } });
  assert.deepEqual(sent[0].sessions, [{ id: 'asuna-scheduler-1', cwd: '/data' }, { id: 'chat', cwd: '/data' }]);
});
