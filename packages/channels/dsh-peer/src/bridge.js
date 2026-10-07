/**
 * The bridge between Asuna's channel API and one session of another DSH Web server (ADR-013).
 *
 * Inbound: it follows the peer session (`session/follow` over `/api/remote.mux`) and posts the peer's final
 * reply of every completed turn to the channel API as a direct message from the peer. Outbound: it claims her
 * words from the channel outbox and prompts the peer session with them (`session/prompt`), labelled with who
 * is speaking, and records the platform receipt. It reads and writes that one session only.
 */
import { randomBytes, randomUUID } from 'node:crypto';
import { promises as fs } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { isIP } from 'node:net';
import path from 'node:path';

const TEXT_LIMIT = 16000;           // the channel API's text limit
const SENT_KEPT = 200;              // request ids of her prompts, to tell her conversation from the owner's

/** Plain HTTP(S) JSON request; LAN services behind their own local CA may skip certificate checks. */
function request(url, { method = 'GET', headers = {}, body, insecure = false, timeoutMs = 30000 } = {}) {
  const target = new URL(url), secure = target.protocol === 'https:';
  const data = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
  return new Promise((resolve, reject) => {
    const req = (secure ? https : http).request(target, {
      method, headers: { ...headers, ...(data ? { 'content-type': 'application/json', 'content-length': data.length } : {}) },
      rejectUnauthorized: !insecure, timeout: timeoutMs }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let json = null;
        try { json = text ? JSON.parse(text) : null; } catch { /* left null */ }
        resolve({ status: res.statusCode, json, text });
      });
    });
    req.on('timeout', () => req.destroy(new Error('TIMEOUT')));
    req.on('error', reject);
    req.end(data);
  });
}

/** A minimal WebSocket client (text frames, ping/pong, close); DSH drops a client that misses two pongs. */
export function connectSocket(url, { insecure = false, onText, onClose }) {
  const target = new URL(url), secure = target.protocol === 'wss:';
  const key = randomBytes(16).toString('base64');
  let socket = null, closed = false, buffer = Buffer.alloc(0), message = [], messageOpcode = 0;
  const finish = reason => { if (!closed) { closed = true; socket?.destroy(); onClose?.(reason); } };
  const frame = (opcode, payload) => {
    const mask = randomBytes(4), length = payload.length;
    const head = length < 126 ? Buffer.from([0x80 | opcode, 0x80 | length])
      : length < 65536 ? Buffer.from([0x80 | opcode, 0x80 | 126, length >> 8, length & 255])
      : Buffer.concat([Buffer.from([0x80 | opcode, 0x80 | 127]), (() => { const b = Buffer.alloc(8); b.writeBigUInt64BE(BigInt(length)); return b; })()]);
    const body = Buffer.from(payload);
    for (let i = 0; i < body.length; i++) body[i] ^= mask[i % 4];
    socket.write(Buffer.concat([head, mask, body]));
  };
  const read = () => {
    for (;;) {
      if (buffer.length < 2) return;
      const fin = buffer[0] & 0x80, opcode = buffer[0] & 0x0f;
      let length = buffer[1] & 0x7f, offset = 2;
      if (length === 126) { if (buffer.length < 4) return; length = buffer.readUInt16BE(2); offset = 4; }
      else if (length === 127) { if (buffer.length < 10) return; length = Number(buffer.readBigUInt64BE(2)); offset = 10; }
      if (buffer[1] & 0x80) offset += 4;                        // a server frame is never masked; tolerate one
      if (buffer.length < offset + length) return;
      const payload = buffer.subarray(offset, offset + length);
      buffer = buffer.subarray(offset + length);
      if (opcode === 9) frame(10, payload);                      // ping: answer at once
      else if (opcode === 8) return finish('closed by peer');
      else if (opcode === 1 || opcode === 2 || opcode === 0) {
        if (opcode) messageOpcode = opcode;
        message.push(Buffer.from(payload));
        if (fin) {
          const whole = Buffer.concat(message); message = [];
          if (messageOpcode === 1) onText(whole.toString('utf8'));
        }
      }
    }
  };
  const handshake = new URL(target.href);
  handshake.protocol = secure ? 'https:' : 'http:';
  const req = (secure ? https : http).request(handshake, {
    headers: { Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Key': key, 'Sec-WebSocket-Version': '13' },
    rejectUnauthorized: !insecure, ...(secure && !isIP(target.hostname) ? { servername: target.hostname } : {}) });
  req.on('upgrade', (_res, upgraded, head) => {
    socket = upgraded;
    buffer = Buffer.from(head ?? []);
    socket.on('data', chunk => { buffer = Buffer.concat([buffer, chunk]); try { read(); } catch (error) { finish(String(error)); } });
    socket.on('close', () => finish('socket closed'));
    socket.on('error', error => finish(String(error)));
    read();
    api.opened?.();
  });
  req.on('response', res => { res.resume(); finish('handshake refused: HTTP ' + res.statusCode); });
  req.on('error', error => finish(String(error)));
  req.end();
  const api = {
    send: text => frame(1, Buffer.from(text, 'utf8')),
    close: () => { if (socket && !closed) { try { frame(8, Buffer.alloc(0)); } catch { /* closing */ } } finish('closed'); },
    opened: null,
  };
  return api;
}

const textOf = content => (content ?? []).filter(block => block?.type === 'text').map(block => block.text).join('').trim();

export class PeerBridge {
  /**
   * @param peer {url, sessionId, routeId, senderId, label, ownerNote, insecureTls, closedUntil}
   *   closedUntil: until this time (ISO) the line is closed: the peer's replies are passed over, not delivered,
   *   and her words wait in the outbox. It reopens by itself.
   * @param endpoint async () => {url, channelId, accountId, token} | null — the channel API (core.channelEndpoint)
   */
  constructor({ peer, endpoint, statePath, log = () => {}, retryMs = 5000 }) {
    this.peer = peer; this.endpoint = endpoint; this.statePath = statePath; this.log = log; this.retryMs = retryMs;
    this.state = { lastSeq: null, sent: [], pending: [] };
    this.turns = new Map();          // turn -> {source, texts}
    this.lastSource = null;
    this.stopped = false;
    this.sleepers = new Set();
    this.socket = null;
    this.status = 'starting';
  }

  async start() {
    try { this.state = { ...this.state, ...JSON.parse(await fs.readFile(this.statePath, 'utf8')) }; } catch { /* first run */ }
    this.follow();
    this.outboundLoop();
    this.flushLoop();
  }

  stop() { this.stopped = true; this.socket?.close(); for (const wake of [...this.sleepers]) wake(); }

  /** A wait that stop() ends at once. */
  sleep(ms) {
    return new Promise(resolve => {
      const done = () => { clearTimeout(timer); this.sleepers.delete(done); resolve(); };
      const timer = setTimeout(done, ms);
      this.sleepers.add(done);
    });
  }

  /** Milliseconds the line stays closed (0 when open). */
  closedFor() {
    const until = Date.parse(this.peer.closedUntil ?? '');
    return Number.isFinite(until) ? Math.max(0, until - Date.now()) : 0;
  }

  async save() {
    await fs.mkdir(path.dirname(this.statePath), { recursive: true });
    const temporary = this.statePath + '.tmp';
    await fs.writeFile(temporary, JSON.stringify(this.state)); await fs.rename(temporary, this.statePath);
  }

  async rpc(method, args) {
    const rpcId = randomUUID();
    const res = await request(new URL('api/' + method, this.peer.url.replace(/\/?$/, '/')).href, {
      method: 'POST', insecure: this.peer.insecureTls, body: { type: 'client-request', rpcId, method, payload: { args } } });
    const result = res.json?.result;
    if (res.status !== 200 || res.json?.rpcId !== rpcId || !result) throw new Error('PEER_RPC_FAILED: HTTP ' + res.status);
    if (!result.ok) throw Object.assign(new Error('PEER_RPC_REFUSED: ' + (result.error?.code ?? 'unknown')), { code: result.error?.code });
    return result.value;
  }

  // ── inbound: the peer's completed turns ───────────────────────────
  follow() {
    if (this.stopped) return;
    const url = new URL('api/remote.mux', this.peer.url.replace(/\/?$/, '/'));
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const streamId = randomUUID();
    const socket = this.socket = connectSocket(url.href, {
      insecure: this.peer.insecureTls,
      onText: text => this.onFrame(streamId, text).catch(error => this.log('inbound: ' + error.message)),
      onClose: reason => {
        this.status = 'reconnecting: ' + reason;
        if (!this.stopped) setTimeout(() => this.follow(), this.retryMs);
      },
    });
    socket.opened = () => {
      this.status = 'following';
      socket.send(JSON.stringify({ type: 'open', streamId, endpoint: 'session/follow',
        payload: { args: { request: { address: { kind: 'session', sessionId: this.peer.sessionId } } } } }));
    };
  }

  async onFrame(streamId, text) {
    const message = JSON.parse(text);
    if (message.streamId !== streamId) return;
    if (message.type === 'error') { this.log('follow refused: ' + (message.error?.code ?? 'unknown')); return; }
    if (message.type !== 'item') return;
    const frame = message.value;
    if (frame?.type === 'snapshot') {
      if (this.state.lastSeq === null) {          // a new bridge starts from now: no history is replayed
        this.state.lastSeq = frame.cursor; await this.save(); return;
      }
      for (const record of frame.records ?? []) await this.onEvent(record.event);
    } else if (frame?.type === 'event') await this.onEvent(frame.event);
  }

  async onEvent(event) {
    if (!event || typeof event.seq !== 'number' || event.seq <= this.state.lastSeq) return;
    const data = event.data ?? {};
    if (event.type === 'user/message') this.lastSource = data.source ?? null;
    else if (event.type === 'turn/start') this.turns.set(data.turn, { source: this.lastSource, texts: [] });
    else if (event.type === 'assistant/message') {
      const turn = this.turns.get(data.turn) ?? this.turns.set(data.turn, { source: this.lastSource, texts: [] }).get(data.turn);
      const said = textOf(data.message?.content);
      if (said) turn.texts.push(said);
    } else if (event.type === 'turn/end') {
      const turn = this.turns.get(data.turn);
      this.turns.delete(data.turn);
      const said = turn?.texts.at(-1);
      if (said && data.reason?.kind === 'completed' && this.closedFor()) this.log('line closed: a reply was passed over');
      else if (said && data.reason?.kind === 'completed') {
        const ours = turn.source?.kind === 'user-rpc' && this.state.sent.includes(turn.source.rpcId);
        const text = ((ours || !this.peer.ownerNote) ? '' : this.peer.ownerNote + '\n') + said;
        this.state.pending.push({ event_id: this.peer.sessionId + ':turn:' + data.turn + ':' + event.seq,
          text: text.length > TEXT_LIMIT ? text.slice(0, TEXT_LIMIT - 1) + '…' : text,
          occurred_at: new Date(event.time ?? Date.now()).toISOString() });
      }
    }
    this.state.lastSeq = event.seq;
    await this.save();
    if (event.type === 'turn/end') await this.flush();
  }

  async flush() {
    if (this.flushing || !this.state.pending.length) return;
    this.flushing = true;
    try {
      const host = await this.endpoint();
      if (!host?.token) return;
      while (this.state.pending.length) {
        const item = this.state.pending[0];
        const res = await request(`${host.url}/v1/channels/${host.channelId}/events`, { method: 'POST',
          headers: { authorization: 'Bearer ' + host.token },
          body: { route_id: this.peer.routeId, account_id: host.accountId, sender_id: this.peer.senderId, ...item } });
        if (res.status >= 500) return;                         // the host is restarting: retry later
        if (res.status >= 400) this.log('inbound refused (' + res.status + '): ' + (res.json?.error ?? res.text).slice(0, 200));
        this.state.pending.shift();
        await this.save();
      }
    } catch (error) { this.log('inbound: ' + error.message); }
    finally { this.flushing = false; }
  }

  async flushLoop() {
    while (!this.stopped) {
      await this.sleep(this.retryMs);
      await this.flush();
    }
  }

  // ── outbound: her words to the peer ───────────────────────────────
  async outboundLoop() {
    while (!this.stopped) {
      try {
        const closed = this.closedFor();
        if (closed) { await this.sleep(Math.min(closed, 60000)); continue; }
        const host = await this.endpoint();
        if (!host?.token) { await this.sleep(this.retryMs); continue; }
        const res = await request(`${host.url}/v1/channels/${host.channelId}/outbox?wait_seconds=25`,
          { headers: { authorization: 'Bearer ' + host.token }, timeoutMs: 45000 });
        if (res.status !== 200 || !Array.isArray(res.json?.items)) {
          await this.sleep(this.retryMs); continue;
        }
        for (const item of res.json.items) await this.deliver(host, item);
      } catch (error) {
        this.log('outbound: ' + error.message);
        await this.sleep(this.retryMs);
      }
    }
  }

  async deliver(host, item) {
    const receipt = (status, response, id) => request(
      `${host.url}/v1/channels/${host.channelId}/outbox/${encodeURIComponent(item.publication_id)}/receipt`,
      { method: 'POST', headers: { authorization: 'Bearer ' + host.token },
        body: { attempt_id: item.attempt_id, status, response, ...(id ? { platform_message_id: id } : {}) } });
    if (typeof item.text !== 'string' || !item.text.trim() || item.action) {
      await receipt('failed', { reason: 'only text reaches a peer session' }); return;
    }
    const requestId = randomUUID();
    this.state.sent = [...this.state.sent, requestId].slice(-SENT_KEPT);
    await this.save();
    try {
      await this.rpc('session/prompt', { request: { requestId, sessionId: this.peer.sessionId, mode: 'queue',
        content: [{ type: 'text', text: (this.peer.label ? this.peer.label + '\n' : '') + item.text }] } });
      await receipt('platform_accepted', { accepted: true }, requestId);
    } catch (error) {
      // A refusal is a definite failure; a transport error may or may not have reached the peer.
      await receipt(error.code ? 'failed' : 'unknown', { error: String(error.message).slice(0, 200) });
    }
  }
}
