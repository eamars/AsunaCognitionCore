import test from 'node:test';
import assert from 'node:assert/strict';
import { replaceAtSameSeat, observerNotice } from './settlement-example.mjs';

const key = 'source-character/request-a/attempt-1';
const live = { key, state: 'running', text: '我先' };

test('full live snapshots grow at one seat without concatenating duplicates', () => {
  let rows = replaceAtSameSeat([], live);
  rows = replaceAtSameSeat(rows, { key, state: 'running', text: '我先看看。' });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].text, '我先看看。');
});

test('settlement replaces the same seat and retains neighbouring rows', () => {
  const user = { key: 'source-user/message-1', text: '回来了' };
  const following = { key: 'source-action/request-b/attempt-1', text: '读取中' };
  const done = { key, state: 'ended', text: '我先看看。', delivery: 'pending' };
  const rows = replaceAtSameSeat([user, live, following], done);
  assert.deepEqual(rows.map(row => row.key), [user.key, key, following.key]);
  assert.equal(rows[0], user);
  assert.equal(rows[2], following);
  assert.equal(rows[1].delivery, 'pending'); // generation end is NOT platform delivery
});

test('a different attempt with identical text is not deduplicated by text', () => {
  const retry = { ...live, key: 'source-character/request-a/attempt-2' };
  const rows = replaceAtSameSeat([live], retry);
  assert.equal(rows.length, 2);
});

test('same attempt from history replaces live instead of replaying typing', () => {
  const history = { key, state: 'ended', text: '我先看看。', fromHistory: true };
  let rows = replaceAtSameSeat([live], history);
  rows = replaceAtSameSeat(rows, history);
  assert.equal(rows.length, 1);
  assert.equal(rows[0], history);
});

test('failure keeps partial content and original reason', () => {
  const failure = { key, state: 'truncated', text: '我先', reason: 'max-tokens' };
  const rows = replaceAtSameSeat([live], failure);
  assert.equal(rows[0].text, '我先');
  assert.equal(rows[0].reason, 'max-tokens');
  assert.equal(rows[0].state, 'truncated');
});

test('diagnostic metadata does not repeat readable monologue', () => {
  const diagnostic = { wire_format: 'sse', frame_count: 1, response_bytes: 58 };
  const rows = replaceAtSameSeat([live], { ...live, providerDiagnostic: diagnostic });
  assert.equal(rows[0].text, '我先');
  assert.equal(rows[0].providerDiagnostic, diagnostic);
  assert.equal(JSON.stringify(diagnostic).includes('我先'), false);
});

test('idle observer has no activity notice; disconnection is not cancellation', () => {
  assert.equal(observerNotice('connected'), null);
  assert.equal(observerNotice('disconnected'), '观察连接中断；后台状态暂未同步');
  assert.equal(live.state, 'running');
});
