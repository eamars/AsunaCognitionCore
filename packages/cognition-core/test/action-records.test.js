import test from 'node:test';
import assert from 'node:assert/strict';
import { ActionRecords } from '../src/action-records.js';
import { NativeChildren } from '../src/children.js';

function records() {
  const events = [];
  let through = 0;
  const role = { session: { snapshotEvents: () => events,
    append: (type, data) => events.push({ type, data, seq: events.length }) } };
  const source = { session: { snapshotEvents: () => [{ seq: through }] } };
  const core = { states: new Map(), ctx: { agents: { get: id => id === 'role' ? role : source },
    sessions: { flush: async () => {} } } };
  return { records: new ActionRecords(core), events, advance: seq => { through = seq; } };
}
const stage = token => ({ lane: 'executor', token, session_id: 'same-source',
  binding: { role_session_id: 'role', parent_session_id: 'role', task_id: token } });

test('successor tasks get disjoint ranges on the same source; receipt replay adds nothing', async () => {
  const h = records();
  await h.records.link(stage('first')); h.advance(12); await h.records.finish(stage('first'));
  await h.records.link(stage('second')); h.advance(24); await h.records.finish(stage('second'));
  const links = h.events.filter(e => e.type === 'asuna/action-linked');
  assert.deepEqual(links.map(e => [e.data.task_id, e.data.after_seq]), [['first', -1], ['second', 12]]);
  assert.ok(links.every(e => e.data.session_id === 'same-source'));
  const ranges = h.events.filter(e => e.type === 'asuna/action-range');
  assert.deepEqual(ranges.map(e => e.data.through_seq), [12, 24]);
  const count = h.events.length;
  await h.records.link(stage('first'), { completed: true });
  await h.records.finish(stage('first'));
  assert.equal(h.events.length, count, 'an old receipt cannot relink or close the newer task');
});

test('a source cannot admit a second range before the first Turn settles', async () => {
  const h = records(); await h.records.link(stage('first'));
  await assert.rejects(h.records.link(stage('second')), /ASUNA_ACTION_RANGE_STILL_OPEN/);
  assert.equal(h.events.length, 1);
});

test('successor announcement returns during result acknowledgement and waits for source teardown', async () => {
  const calls = [];
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const children = new NativeChildren({ ctx: { logger: { warn: () => {} } }, worker: { call: async () => {} } });
  children.open = async value => {
    calls.push(value.token);
    if (value.token === 'first') {
      await children.start(stage('second')); // The business result acknowledgement can return.
      calls.push('acknowledged');
      await held; calls.push('disposed-first');
    }
  };
  await children.start(stage('first'));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['first', 'acknowledged']);
  release();
  await Promise.all(children.admissions.values());
  assert.deepEqual(calls, ['first', 'acknowledged', 'disposed-first', 'second']);
  assert.equal(children.admissions.size, 0);
});
