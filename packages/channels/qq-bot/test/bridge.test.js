// The QQ Bot bridge (ADR-046) against a fake platform (gateway + OpenAPI) and a fake channel API.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { QQBotBridge, INTENTS, inboundText, outboundBody, plainText } from '../src/bridge.js';

const APP = '1000000001';
const USER = 'A'.repeat(32), GROUP = 'B'.repeat(32), MEMBER = 'C'.repeat(32), OTHER = 'D'.repeat(32);
const HOST = 'http://127.0.0.1:8766';

/** A fake platform and channel API: records every request, answers by route. */
function world({ refuseReply = false, refuseMarkdown = false } = {}) {
  const calls = [];
  let now = Date.parse('2026-10-11T10:00:00Z');
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: String(url), method: init.method ?? 'GET', body, headers: init.headers ?? {} });
    const u = new URL(url);
    if (u.pathname === '/app/getAppAccessToken') return json(200, { access_token: 'tok', expires_in: '7200' });
    if (u.pathname === '/gateway') return json(200, { url: 'wss://gateway.invalid/websocket' });
    if (u.pathname.endsWith('/files')) return json(200, { file_uuid: 'u1', file_info: 'INFO', ttl: 0 });
    if (u.pathname.endsWith('/messages')) {
      if (refuseReply && body.msg_id) return json(400, { code: 40034024, message: 'reply window closed' });
      if (refuseMarkdown && body.msg_type === 2) return json(400, { code: 304036, message: 'no markdown permission' });
      return json(200, { id: 'sent-' + calls.length, timestamp: '2026-10-11T18:00:01+08:00' });
    }
    if (u.pathname.endsWith('/events')) return json(200, { status: 'accepted' });
    if (u.pathname.endsWith('/receipt')) return json(200, { status: 'recorded' });
    if (u.pathname.endsWith('/attachment')) return new Response(Buffer.from('PNGBYTES'), { status: 200 });
    return json(404, { error: 'unknown ' + u.pathname });
  };
  const endpoint = async () => ({ url: HOST, channelId: 'qqbot', accountId: APP, token: 'x'.repeat(24),
    settings: { account_id: APP, app_secret: 'secret', routes: { 'owner-dm': { target: { type: 'dm', id: USER } } } } });
  return { calls, fetch, endpoint, clock: { now: () => now, advance: ms => { now += ms; } } };
}

class FakeSocket {
  static last = null;
  constructor(url) { this.url = url; this.sent = []; FakeSocket.last = this; }
  send(text) { this.sent.push(JSON.parse(text)); }
  close(code = 1000) { this.onclose?.({ code }); }
  push(payload) { this.onmessage?.({ data: JSON.stringify(payload) }); }
}

async function bridge(w) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'qqbot-'));
  const b = new QQBotBridge({ endpoint: w.endpoint, statePath: path.join(dir, 'qqbot.json'), fetch: w.fetch,
    WebSocket: FakeSocket, now: w.clock.now });
  await b.host();
  return b;
}

const settle = () => new Promise(resolve => setTimeout(resolve, 20));

test('the gateway: hello is answered by identify with the group and private-chat intent, then resume after a drop', async () => {
  const w = world(), b = await bridge(w);
  const host = await b.host();
  const closed = b.session('wss://gateway.invalid/websocket', host);
  const socket = FakeSocket.last;
  socket.push({ op: 10, d: { heartbeat_interval: 60000 } });
  await settle();
  assert.deepEqual(socket.sent[0], { op: 2, d: { token: 'QQBot tok', intents: INTENTS, shard: [0, 1], properties: {} } });
  socket.push({ op: 0, t: 'READY', s: 1, d: { session_id: 'sess', user: { username: 'bot' } } });
  await settle();
  assert.deepEqual(b.state.session, { id: 'sess', seq: 1 });
  socket.push({ op: 0, t: 'FRIEND_ADD', s: 5, d: {} });
  socket.close(4000);
  assert.equal(await closed, 4000);
  b.session('wss://gateway.invalid/websocket', host);
  FakeSocket.last.push({ op: 10, d: { heartbeat_interval: 60000 } });
  await settle();
  assert.deepEqual(FakeSocket.last.sent[0], { op: 6, d: { token: 'QQBot tok', session_id: 'sess', seq: 5 } });
  FakeSocket.last.close(4009);                        // cannot be resumed: the next connection identifies again
  assert.equal(b.state.session, null);
  b.stop();
});

test('a private message reaches the channel API on its configured route, with the sender profile and pictures', async () => {
  const w = world(), b = await bridge(w);
  await b.dispatch('C2C_MESSAGE_CREATE', { id: 'm1', content: ' 你好 ', timestamp: '2026-10-11T18:00:00+08:00',
    author: { user_openid: USER, username: '主人' },
    attachments: [{ content_type: 'image/png', url: 'multimedia.nt.qq.com.cn/download?x=1', filename: 'a.png', size: 12 }] });
  const posted = w.calls.find(call => call.url.endsWith('/v1/channels/qqbot/events'));
  assert.equal(posted.body.route_id, 'owner-dm');
  assert.equal(posted.body.sender_id, USER);
  assert.equal(posted.body.account_id, APP);
  assert.equal(posted.body.event_id, 'm1');
  assert.equal(posted.body.occurred_at, '2026-10-11T10:00:00Z');
  assert.equal(posted.body.text, '你好 [图片（未解析）]');
  assert.equal(posted.body.group_id, undefined);
  assert.equal(posted.body.raw.asuna_peer.person_id, 'qqbot:' + USER);
  assert.equal(posted.body.raw.asuna_peer.scene, 'dm');
  assert.deepEqual(posted.body.raw.asuna_media.items[0],
    { type: 'image', placeholder: '[图片（未解析）]', url: 'https://multimedia.nt.qq.com.cn/download?x=1', file: 'a.png', size: '12' });
  // The platform may push one message twice: it is posted once.
  await b.dispatch('C2C_MESSAGE_CREATE', { id: 'm1', content: '你好', author: { user_openid: USER } });
  assert.equal(w.calls.filter(call => call.url.endsWith('/events')).length, 1);
});

test('a group @ wakes her: the AppID is among the mentions; other mentions read as @<openid>', async () => {
  const w = world(), b = await bridge(w);
  await b.dispatch('GROUP_AT_MESSAGE_CREATE', { id: 'g1', content: ' 问问 <@!' + OTHER + '> 呢', group_openid: GROUP,
    timestamp: '2026-10-11T18:00:00+08:00', author: { member_openid: MEMBER, username: '群友' },
    mentions: [{ member_openid: OTHER, username: '另一位' }] });
  const posted = w.calls.find(call => call.url.endsWith('/events')).body;
  assert.equal(posted.route_id, 'auto-group-' + GROUP);
  assert.equal(posted.group_id, GROUP);
  assert.deepEqual(posted.mentioned_account_ids, [APP, OTHER]);
  assert.equal(posted.text, '问问 @' + OTHER + ' 呢');
  assert.equal(posted.raw.asuna_peer.scene, 'group:' + GROUP);
  assert.equal(posted.raw.asuna_peer.group_id, GROUP);
});

test('her words go out as a reply to the message she answers while the platform takes replies, then as her own', async () => {
  const w = world(), b = await bridge(w);
  const host = await b.host();
  await b.dispatch('GROUP_AT_MESSAGE_CREATE', { id: 'g1', content: 'hi', group_openid: GROUP, author: { member_openid: MEMBER } });
  const item = n => ({ publication_id: 'p' + n, attempt_id: 'a' + n, target: { type: 'group', id: GROUP },
    text: '好呀 @qqbot:' + MEMBER, reply_to: 'g1' });
  await b.deliver(host, item(1));
  await b.deliver(host, item(2));
  const sends = w.calls.filter(call => call.url.endsWith('/v2/groups/' + GROUP + '/messages'));
  assert.deepEqual(sends[0].body, { msg_type: 2, markdown: { content: '好呀 <qqbot-at-user id="' + MEMBER + '" />' },
    msg_id: 'g1', msg_seq: 1 });
  assert.equal(sends[1].body.msg_seq, 2);
  assert.equal(sends[0].headers.authorization, 'QQBot tok');
  const receipt = w.calls.find(call => call.url.endsWith('/outbox/p1/receipt')).body;
  assert.equal(receipt.status, 'platform_accepted');
  assert.equal(receipt.attempt_id, 'a1');
  assert.ok(receipt.platform_message_id);
  w.clock.advance(5 * 60000);                          // the group's reply window has passed
  await b.deliver(host, item(3));
  const last = w.calls.filter(call => call.url.endsWith('/messages')).at(-1).body;
  assert.equal(last.msg_id, undefined);
});

test('a refused reply is sent once as her own message', async () => {
  const w = world({ refuseReply: true }), b = await bridge(w);
  const host = await b.host();
  await b.dispatch('C2C_MESSAGE_CREATE', { id: 'm1', content: 'hi', author: { user_openid: USER } });
  await b.deliver(host, { publication_id: 'p1', attempt_id: 'a1', target: { type: 'dm', id: USER }, text: '在的' });
  const sends = w.calls.filter(call => call.url.endsWith('/v2/users/' + USER + '/messages'));
  assert.equal(sends.length, 2);
  assert.equal(sends[0].body.msg_id, 'm1');
  assert.equal(sends[1].body.msg_id, undefined);
  assert.equal(w.calls.find(call => call.url.endsWith('/receipt')).body.status, 'platform_accepted');
});

test('a picture is read from the channel API, checked, uploaded for that conversation and sent with her words', async () => {
  const w = world(), b = await bridge(w);
  const host = await b.host();
  const sha256 = createHash('sha256').update('PNGBYTES').digest('hex');
  await b.deliver(host, { publication_id: 'p1', attempt_id: 'a1', target: { type: 'dm', id: USER }, text: '看',
    attachment: { artifact_id: 'art', media_type: 'image/png', sha256, size: 8 } });
  const upload = w.calls.find(call => call.url.endsWith('/v2/users/' + USER + '/files'));
  assert.deepEqual(upload.body, { file_type: 1, file_data: Buffer.from('PNGBYTES').toString('base64'), srv_send_msg: false });
  const sent = w.calls.find(call => call.url.endsWith('/messages')).body;
  assert.deepEqual(sent, { msg_type: 7, media: { file_info: 'INFO' }, content: '看' });
  // A picture whose bytes do not match the claim's digest is not sent.
  await b.deliver(host, { publication_id: 'p2', attempt_id: 'a2', target: { type: 'dm', id: USER }, text: '看',
    attachment: { artifact_id: 'art', media_type: 'image/png', sha256: '0'.repeat(64), size: 8 } });
  assert.equal(w.calls.find(call => call.url.endsWith('/outbox/p2/receipt')).body.status, 'failed');
});

test('the platform markup reads as the core reads mentions; her @ in a group goes as markdown, her words escaped', () => {
  assert.equal(inboundText('<qqbot-at-user id="' + OTHER + '" /> 嗨 <faceType=1,faceId="13",ext="eA==">'), '@' + OTHER + ' 嗨 [表情]');
  // Plain text shows the mention tag as it is; only markdown makes it a real @ (checked on the platform).
  assert.deepEqual(outboundBody('@qqbot:' + OTHER + ' 嗨 *这样* 1. a_b', 'group'),
    { msg_type: 2, markdown: { content: '<qqbot-at-user id="' + OTHER + '" /> 嗨 \\*这样\\* 1\\. a\\_b' } });
  assert.deepEqual(outboundBody('没有 @ 的 *话*', 'group'), { msg_type: 0, content: '没有 @ 的 *话*' });
  assert.deepEqual(outboundBody('@qqbot:' + OTHER + ' 嗨', 'dm'), { msg_type: 0, content: '嗨' });
  assert.equal(plainText('看 @qqbot:' + OTHER + ' 这张'), '看 这张');
});

test('a bot that may not send markdown sends her words as plain text, without the @', async () => {
  const w = world({ refuseMarkdown: true }), b = await bridge(w);
  const host = await b.host();
  await b.dispatch('GROUP_AT_MESSAGE_CREATE', { id: 'g1', content: 'hi', group_openid: GROUP, author: { member_openid: MEMBER } });
  await b.deliver(host, { publication_id: 'p1', attempt_id: 'a1', target: { type: 'group', id: GROUP },
    text: '好呀 @qqbot:' + MEMBER + ' 来了', reply_to: 'g1' });
  const sends = w.calls.filter(call => call.url.endsWith('/v2/groups/' + GROUP + '/messages')).map(call => call.body);
  assert.equal(sends.length, 2);
  assert.equal(sends[0].msg_type, 2);
  assert.deepEqual(sends[1], { msg_type: 0, content: '好呀 来了', msg_id: 'g1', msg_seq: 2 });
  assert.equal(w.calls.find(call => call.url.endsWith('/receipt')).body.status, 'platform_accepted');
});
