import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { promises as fs } from 'node:fs';
import { PeerBridge } from '../src/bridge.js';

const SESSION = 'session-peer';

/** A fake peer DSH: session/follow over a real WebSocket (handshake, masking, ping), session/prompt over HTTP. */
async function fakePeer() {
  const peer = { prompts: [], pongs: 0, socket: null, streamId: null, refuse: false };
  const frame = (opcode, payload) => {
    const body = Buffer.from(payload);
    const head = body.length < 126 ? Buffer.from([0x80 | opcode, body.length])
      : Buffer.from([0x80 | opcode, 126, body.length >> 8, body.length & 255]);
    return Buffer.concat([head, body]);
  };
  peer.send = value => peer.socket.write(frame(1, JSON.stringify({ type: 'item', streamId: peer.streamId, value })));
  peer.ping = () => peer.socket.write(frame(9, 'hi'));
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', chunk => { body += chunk; }).on('end', () => {
      const message = JSON.parse(body);
      const request = message.payload.args.request;
      peer.prompts.push(request);
      const result = peer.refuse ? { ok: false, error: { code: 'session/busy', message: 'busy' } } : { ok: true, value: { accepted: true } };
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ type: 'server-response', rpcId: message.rpcId, result }));
    });
  });
  server.on('upgrade', (req, socket) => {
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n');
    peer.socket = socket;
    let buffer = Buffer.alloc(0);
    socket.on('data', chunk => {
      buffer = Buffer.concat([buffer, chunk]);
      while (buffer.length >= 6) {
        const opcode = buffer[0] & 0x0f;
        let length = buffer[1] & 0x7f, offset = 2;
        if (length === 126) { length = buffer.readUInt16BE(2); offset = 4; }
        if (buffer.length < offset + 4 + length) return;
        const mask = buffer.subarray(offset, offset + 4), payload = Buffer.from(buffer.subarray(offset + 4, offset + 4 + length));
        for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
        buffer = buffer.subarray(offset + 4 + length);
        if (opcode === 10) peer.pongs++;
        if (opcode === 1) {
          const open = JSON.parse(payload.toString());
          assert.equal(open.endpoint, 'session/follow');
          assert.deepEqual(open.payload.args.request.address, { kind: 'session', sessionId: SESSION });
          peer.streamId = open.streamId;
          peer.send({ type: 'snapshot', cursor: 10, records: [], hasMore: false });
        }
      }
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  peer.url = 'http://127.0.0.1:' + server.address().port;
  peer.close = () => { peer.socket?.destroy(); server.closeAllConnections(); server.close(); };
  return peer;
}

/** A fake channel API: records events and receipts, hands out queued outbox items. */
async function fakeHost() {
  const host = { events: [], receipts: [], outbox: [] };
  const server = http.createServer((req, res) => {
    assert.equal(req.headers.authorization, 'Bearer channel-token');
    let body = '';
    req.on('data', chunk => { body += chunk; }).on('end', () => {
      res.setHeader('content-type', 'application/json');
      if (req.url.endsWith('/events')) { host.events.push(JSON.parse(body)); return res.end('{"status":"accepted"}'); }
      if (req.url.includes('/receipt')) { host.receipts.push(JSON.parse(body)); return res.end('{}'); }
      if (req.url.includes('/outbox?')) {
        const items = host.outbox.splice(0);
        return setTimeout(() => res.end(JSON.stringify({ items })), items.length ? 0 : 50);
      }
      res.statusCode = 404; res.end('{}');
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  host.endpoint = async () => ({ url: 'http://127.0.0.1:' + server.address().port, channelId: 'dsh', accountId: 'home', token: 'channel-token' });
  host.close = () => { server.closeAllConnections(); server.close(); };
  return host;
}

const until = async (check, ms = 3000) => {
  const deadline = Date.now() + ms;
  while (!check()) { if (Date.now() > deadline) throw new Error('timed out'); await new Promise(r => setTimeout(r, 20)); }
};

const turn = (seq, number, source, said, reason = 'completed') => [
  { type: 'user/message', seq, time: 1, data: { id: 'm' + seq, role: 'user', content: [{ type: 'text', text: 'q' }], source } },
  { type: 'turn/start', seq: seq + 1, time: 1, data: { turn: number } },
  { type: 'assistant/message', seq: seq + 2, time: 1, data: { turn: number, step: 1, message: { content: [
    { type: 'reasoning', text: 'thinking' }, { type: 'text', text: said }] } } },
  { type: 'turn/end', seq: seq + 3, time: 2, data: { turn: number, reason: { kind: reason } } },
];

async function setup() {
  const peer = await fakePeer(), host = await fakeHost();
  const statePath = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'dsh-peer-')), 'state.json');
  const bridge = new PeerBridge({ peer: { url: peer.url, sessionId: SESSION, routeId: 'peer-dm', senderId: 'peer',
    label: '[from home]', ownerNote: '(not to you)' }, endpoint: host.endpoint, statePath, retryMs: 50 });
  await bridge.start();
  await until(() => peer.streamId);
  return { peer, host, bridge, done: () => { bridge.stop(); peer.close(); host.close(); } };
}

test('a new bridge starts from the present and forwards a completed reply as a message from the peer', async () => {
  const { peer, host, bridge, done } = await setup();
  try {
    await until(() => bridge.state.lastSeq === 10);
    for (const event of turn(11, 4, { kind: 'user' }, 'hello there')) peer.send({ type: 'event', event });
    await until(() => host.events.length === 1);
    assert.deepEqual({ ...host.events[0], occurred_at: undefined }, { route_id: 'peer-dm', account_id: 'home', sender_id: 'peer',
      event_id: SESSION + ':turn:4:14', text: '(not to you)\nhello there', occurred_at: undefined });
    for (const event of turn(15, 5, { kind: 'user' }, 'cut off', 'aborted')) peer.send({ type: 'event', event });
    await new Promise(r => setTimeout(r, 150));
    assert.equal(host.events.length, 1);                       // an unfinished turn is not a reply
  } finally { done(); }
});

test('her words reach the peer labelled, are receipted, and the answer to them comes back without the note', async () => {
  const { peer, host, done } = await setup();
  try {
    host.outbox.push({ publication_id: 'pub-1', attempt_id: 'att-1', text: 'hi, it is me', target: {} });
    await until(() => host.receipts.length === 1);
    const prompt = peer.prompts[0];
    assert.equal(prompt.sessionId, SESSION);
    assert.equal(prompt.mode, 'queue');
    assert.deepEqual(prompt.content, [{ type: 'text', text: '[from home]\nhi, it is me' }]);
    assert.deepEqual(host.receipts[0], { attempt_id: 'att-1', status: 'platform_accepted', response: { accepted: true },
      platform_message_id: prompt.requestId });
    for (const event of turn(11, 6, { kind: 'user-rpc', rpcId: prompt.requestId }, 'welcome')) peer.send({ type: 'event', event });
    await until(() => host.events.length === 1);
    assert.equal(host.events[0].text, 'welcome');
  } finally { done(); }
});

test('a refused prompt is a failed receipt, and pings are answered', async () => {
  const { peer, host, done } = await setup();
  try {
    peer.ping();
    await until(() => peer.pongs === 1);
    peer.refuse = true;
    host.outbox.push({ publication_id: 'pub-2', attempt_id: 'att-2', text: 'are you there', target: {} });
    await until(() => host.receipts.length === 1);
    assert.equal(host.receipts[0].status, 'failed');
    assert.match(host.receipts[0].response.error, /session\/busy/);
  } finally { done(); }
});

test('while the line is closed nothing crosses: replies are passed over and her words wait', async () => {
  const { peer, host, bridge, done } = await setup();
  try {
    bridge.peer.closedUntil = new Date(Date.now() + 60000).toISOString();
    host.outbox.push({ publication_id: 'pub-3', attempt_id: 'att-3', text: 'still awake?', target: {} });
    for (const event of turn(11, 7, { kind: 'user' }, 'night bell')) peer.send({ type: 'event', event });
    await until(() => bridge.state.lastSeq === 14);
    await new Promise(r => setTimeout(r, 200));
    assert.equal(host.events.length, 0);
    assert.equal(bridge.state.pending.length, 0);
    assert.equal(host.outbox.length, 1);                       // not claimed while closed
    assert.equal(peer.prompts.length, 0);
  } finally { done(); }
});
