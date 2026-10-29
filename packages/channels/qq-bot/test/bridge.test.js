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
function world({ refuseReply = false, refuseMarkdown = false, refuseInfo = false, names = [], refused = [] } = {}) {
  const calls = [];
  const core = { mode: 'up' };                          // 'up', 'old' (predates the endpoint) or 'down'
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
    if (u.pathname.endsWith('/info')) {
      if (refuseInfo) return json(403, { code: 11253, message: 'no access' });
      return json(200, { group_openid: GROUP, group_name: names.shift() ?? '读书会', group_member_num: 3 });
    }
    if (u.pathname.endsWith('/admission')) {
      if (core.mode === 'old') return json(404, { error: 'UNKNOWN_CHANNEL_ENDPOINT' });
      if (core.mode === 'down') return json(503, { error: 'HOST_RECONFIGURING' });
      const [ask] = body.asks, { type, id } = ask.conversation;
      if (refused.includes(ask.sender_id ?? id)) return json(200, { answers: [{ verdict: 'refused', code: 'CHANNEL_IDENTITY_DENIED',
        scope: 'sender', ttl_seconds: 60 }], epoch: 'e1' });
      return json(200, { answers: [{ verdict: 'admitted', conversation: ask.conversation, known: type === 'dm' && id === USER,
        route_id: type === 'dm' && id === USER ? 'owner-dm' : 'auto-' + type + '-' + id, ttl_seconds: 60 }], epoch: 'e1' });
    }
    if (u.pathname.endsWith('/events')) return json(200, { status: 'accepted' });
    if (u.pathname.endsWith('/receipt')) return json(200, { status: 'recorded' });
    if (u.pathname.endsWith('/attachment')) return new Response(Buffer.from('PNGBYTES'), { status: 200 });
    return json(404, { error: 'unknown ' + u.pathname });
  };
  const endpoint = async () => ({ url: HOST, channelId: 'qqbot', accountId: APP, token: 'x'.repeat(24),
    settings: { account_id: APP, app_secret: 'secret' } });
  return { calls, fetch, endpoint, core, clock: { now: () => now, advance: ms => { now += ms; } } };
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

test('a private message reaches the channel API on the route the core names, with the sender profile and pictures', async () => {
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

test('the state file counts each event type the platform pushes, with its last time and no ids or text', async () => {
  const w = world(), b = await bridge(w);
  await b.dispatch('RESUMED', {});
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'g1', content: '闲聊', group_openid: GROUP, author: { member_openid: MEMBER } });
  w.clock.advance(60000);
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'g2', content: '还是闲聊', group_openid: GROUP, author: { member_openid: MEMBER } });
  const saved = JSON.parse(await fs.readFile(b.statePath, 'utf8'));
  assert.deepEqual(saved.events, { RESUMED: { count: 1, last_at: '2026-10-11T10:00:00Z' },
    GROUP_MESSAGE_CREATE: { count: 2, last_at: '2026-10-11T10:01:00Z' } });
  // An un-addressed group message goes through her usual group wake rules: her AppID is not among its mentions.
  assert.deepEqual(w.calls.filter(call => call.url.endsWith('/events')).map(call => call.body.mentioned_account_ids), [[], []]);
});

test('a group message carries the group name the platform gives, read once a day; none when the lookup is refused', async () => {
  const w = world({ names: ['读书会', '读书分享会'] }), b = await bridge(w);
  const msg = id => b.dispatch('GROUP_AT_MESSAGE_CREATE', { id, content: 'hi', group_openid: GROUP, author: { member_openid: MEMBER } });
  await msg('g1'); await msg('g2');
  const posted = () => w.calls.filter(call => call.url.endsWith('/events')).map(call => call.body.raw.group_name);
  const lookups = () => w.calls.filter(call => call.url.endsWith('/v2/groups/' + GROUP + '/info')).length;
  assert.deepEqual(posted(), ['读书会', '读书会']);
  assert.equal(lookups(), 1);
  w.clock.advance(24 * 3600000);                       // a day later its admins may have renamed it
  await msg('g3');
  assert.equal(posted().at(-1), '读书分享会');
  assert.equal(lookups(), 2);
  const saved = JSON.parse(await fs.readFile(b.statePath, 'utf8'));
  assert.deepEqual(saved.groups[GROUP], { name: '读书分享会', read_at: '2026-10-12T10:00:00Z' });

  const r = world({ refuseInfo: true }), c = await bridge(r);
  await c.dispatch('GROUP_AT_MESSAGE_CREATE', { id: 'g1', content: 'hi', group_openid: GROUP, author: { member_openid: MEMBER } });
  await c.dispatch('GROUP_AT_MESSAGE_CREATE', { id: 'g2', content: 'hi', group_openid: GROUP, author: { member_openid: MEMBER } });
  const events = r.calls.filter(call => call.url.endsWith('/events'));
  assert.equal(events.length, 2);
  assert.ok(events.every(call => !('group_name' in call.body.raw)));
  assert.equal(r.calls.filter(call => call.url.endsWith('/info')).length, 1);   // refused once: not asked again that day
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

test('a message pushed again keeps its reply count, and one replayed after its window is not answered as a reply', async () => {
  const w = world(), b = await bridge(w);
  const host = await b.host();
  const push = (id, timestamp) => b.dispatch('GROUP_AT_MESSAGE_CREATE', { id, content: 'hi', group_openid: GROUP,
    author: { member_openid: MEMBER }, ...(timestamp ? { timestamp } : {}) });
  const item = n => ({ publication_id: 'p' + n, attempt_id: 'a' + n, target: { type: 'group', id: GROUP }, text: '好', reply_to: 'g1' });
  await push('g1');
  await b.deliver(host, item(1));
  await push('g1');                                     // the platform pushes it twice
  await b.deliver(host, item(2));
  const sends = () => w.calls.filter(call => call.url.endsWith('/v2/groups/' + GROUP + '/messages')).map(call => call.body);
  assert.deepEqual(sends().map(body => body.msg_seq), [1, 2]);
  // Sent 10 minutes before it reached this bridge (a resumed session replays it): the group's 5 minutes are over.
  await push('g0', '2026-10-11T17:50:00+08:00');
  await b.deliver(host, { ...item(3), reply_to: 'g0' });
  assert.equal(sends().at(-1).msg_id, 'g1');           // the newest message still open, not the replayed one
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


test('the route comes from the core: asked once for the time it names, never built here', async () => {
  const w = world(), b = await bridge(w);
  const ask = () => w.calls.filter(call => call.url.endsWith('/admission'));
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'g1', content: 'a', group_openid: GROUP, author: { member_openid: MEMBER } });
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'g2', content: 'b', group_openid: GROUP, author: { member_openid: MEMBER } });
  assert.equal(ask().length, 1, 'the second line used the answer kept');
  assert.deepEqual(ask()[0].body, { account_id: APP, asks: [{ conversation: { type: 'group', id: GROUP }, sender_id: MEMBER }] });
  w.clock.advance(61000);
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'g3', content: 'c', group_openid: GROUP, author: { member_openid: MEMBER } });
  assert.equal(ask().length, 2, 'after its time the core is asked again');
  const sent = w.calls.filter(call => call.url.endsWith('/events')).map(call => call.body);
  assert.equal(sent.length, 3);
  assert.ok(sent.every(body => body.route_id === 'auto-group-' + GROUP && body._ask === undefined), 'no note of ours goes on the wire');
});

test('a sender the core does not admit is dropped; a core that does not answer, or predates the endpoint, holds the line', async () => {
  const w = world({ refused: [OTHER] }), b = await bridge(w);
  const posted = () => w.calls.filter(call => call.url.endsWith('/events')).map(call => call.body.event_id);
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'r1', content: 'x', group_openid: GROUP, author: { member_openid: OTHER } });
  assert.deepEqual(posted(), []);
  assert.equal(b.state.pending.length, 0, 'refused: nothing waits');
  w.core.mode = 'old';
  await b.dispatch('GROUP_MESSAGE_CREATE', { id: 'o1', content: 'x', group_openid: GROUP, author: { member_openid: MEMBER } });
  assert.deepEqual(posted(), []);
  assert.equal(b.state.pending.length, 1, 'an old core: the line waits and is not posted wider');
  w.core.mode = 'down';
  await b.flush();
  assert.equal(b.state.pending.length, 1, 'a core that does not answer: still waiting');
  w.core.mode = 'up';
  await b.flush();
  assert.deepEqual(posted(), ['o1']);
  assert.equal(b.state.pending.length, 0);
});
