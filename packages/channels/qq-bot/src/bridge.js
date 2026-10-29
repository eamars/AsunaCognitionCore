/**
 * The bridge between Asuna's channel API and the official QQ Bot open platform (ADR-046).
 *
 * Inbound: it keeps one gateway session (WebSocket) and posts every private-chat and group message the platform
 * pushes to the channel API. Outbound: it claims her words from the channel outbox and sends them through the
 * platform's OpenAPI — as a reply to the message she answers while the platform still takes replies to it, else as a
 * message of her own — and records the platform receipt. Message text never reaches its log.
 */
import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';

export const INTENTS = 1 << 25;                 // GROUP_AND_C2C_EVENT: private chats and groups
export const TOKEN_URL = 'https://bots.qq.com/app/getAppAccessToken';
export const API_BASE = 'https://api.sgroup.qq.com';
const TEXT_LIMIT = 16000;                       // the channel API's text limit
const IMAGE_LIMIT = 5 * 1024 * 1024;            // file_data the platform takes in one upload
// How long, and how often, the platform takes replies to one received message (msg_id).
export const REPLY_WINDOW = { dm: { ms: 60 * 60000, replies: 4 }, group: { ms: 5 * 60000, replies: 5 } };
const WINDOW_MARGIN_MS = 15000;                 // a reply sent this close to the end may arrive after it
const KEPT_PER_TARGET = 8;                      // received messages kept per conversation for replies
const SEEN_KEPT = 1000;                         // message ids already posted (the platform may push one twice)
const OPENID = /^[0-9A-Za-z_-]{24,64}$/;
const BACKOFF_MS = [2000, 5000, 10000, 30000, 60000];
const BLOCKED_RETRY_MS = 10 * 60000;            // 4914 / 4915: the platform refuses this bot; try again much later
const SESSION_CLOSES = new Set([4006, 4007, 4009]);   // the session cannot be resumed: identify again
const GROUP_NAME_MS = 24 * 3600000;             // a group's name is read again after a day (its admins may rename it)

/** One of the platform's attachment kinds as the media block the core reads (RUNTIME_API.md, raw.asuna_media). */
function mediaItem(attachment) {
  const type = String(attachment?.content_type ?? '');
  let url = String(attachment?.url ?? '').trim();
  if (url.startsWith('//')) url = 'https:' + url;
  else if (url && !/^https?:\/\//i.test(url)) url = 'https://' + url;
  const name = String(attachment?.filename ?? '').trim().slice(0, 120);
  const item = type.startsWith('image/') ? { type: 'image', placeholder: '[图片（未解析）]' }
    : type.startsWith('video/') ? { type: 'video', placeholder: '[视频（未解析）]' }
    : type === 'voice' || type.startsWith('audio/') ? { type: 'record', placeholder: attachment?.asr_refer_text
      ? '[语音：' + String(attachment.asr_refer_text).trim().slice(0, 200) + ']' : '[语音（未解析）]' }
    : { type: 'file', placeholder: name ? '[文件:' + name.slice(0, 60) + '（未解析）]' : '[文件（未解析）]' };
  if (url && url.length <= 2048) item.url = url;
  if (name) item.file = name;
  if (attachment?.size != null) item.size = String(attachment.size).slice(0, 16);
  return item;
}

/** The platform's mention markup as the core reads a real @ (`@<openid>`), and its faces as a plain placeholder. */
export function inboundText(content) {
  return String(content ?? '')
    .replace(/<qqbot-at-user\s+id="([0-9A-Za-z_-]+)"\s*\/>/g, '@$1')
    .replace(/<@!?([0-9A-Za-z_-]+)>/g, '@$1')
    .replace(/<qqbot-at-everyone\s*\/>/g, '@全体成员')
    .replace(/<faceType=\d+,faceId="[^"]*",ext="[^"]*">/g, '[表情]')
    .trim();
}

// The platform's answers when this bot has no markdown permission (304036, 40034127) or markdown is refused (50056).
const MARKDOWN_REFUSED = new Set([304036, 40034127, 50056]);
const HER_MENTION = /@qqbot:([0-9A-Za-z_-]{24,64})/g;
// Markdown's own characters, escaped so her words read as she wrote them.
const MARKDOWN = /[\\`*_{}[\]()#+\-.!|>~]/g;

/** Her words as the platform's message body. Only a markdown message turns the platform's mention tag into a real @
 * (plain text shows the tag as it is), so a group message that @s someone goes as markdown with her other characters
 * escaped; anything else goes as plain text without the tag (a private chat or a picture has no mentions). */
export function outboundBody(text, scope) {
  const words = String(text ?? '');
  if (scope === 'group' && words.match(HER_MENTION)) {
    const content = words.split(HER_MENTION).map((part, i) => i % 2 ? '<qqbot-at-user id="' + part + '" />'
      : part.replace(MARKDOWN, '\\$&')).join('').trim();
    return { msg_type: 2, markdown: { content } };
  }
  return { msg_type: 0, content: plainText(words) };
}

/** Her words without mention tags, for a body that cannot carry one. */
export function plainText(text) {
  return String(text ?? '').replace(HER_MENTION, '').replace(/[ \t]{2,}/g, ' ').trim();
}

const isoOf = value => {
  const time = Date.parse(String(value ?? ''));
  return Number.isFinite(time) ? new Date(time).toISOString().replace(/\.\d{3}Z$/, 'Z') : null;
};

/** The platform's OpenAPI with an access token kept fresh. */
export class QQBotApi {
  constructor({ appId, secret, apiBase = API_BASE, tokenUrl = TOKEN_URL, fetch = globalThis.fetch, now = Date.now }) {
    this.appId = appId; this.secret = secret; this.apiBase = apiBase.replace(/\/+$/, ''); this.tokenUrl = tokenUrl;
    this.fetch = fetch; this.now = now; this.cached = null;
  }

  /** The current access token. The platform hands out the same one until its last minute, then a new one. */
  async token() {
    if (this.cached && this.cached.expiresAt - this.now() > 55000) return this.cached.value;
    const res = await this.fetch(this.tokenUrl, { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ appId: this.appId, clientSecret: this.secret }), signal: AbortSignal.timeout(15000) });
    const json = await res.json().catch(() => null);
    if (!json?.access_token) {
      throw Object.assign(new Error('QQBOT_TOKEN_REFUSED: ' + (json?.code ?? res.status) + ' ' + (json?.message ?? '')),
        { status: res.status, platform: json });
    }
    this.cached = { value: json.access_token, expiresAt: this.now() + Number(json.expires_in ?? 7200) * 1000 };
    return this.cached.value;
  }

  forget() { this.cached = null; }

  async call(method, route, body, timeoutMs = 30000) {
    const res = await this.fetch(this.apiBase + route, { method, signal: AbortSignal.timeout(timeoutMs),
      headers: { authorization: 'QQBot ' + await this.token(), 'x-union-appid': String(this.appId),
                 ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const text = await res.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* left null */ }
    if (!res.ok || (json && typeof json.code === 'number' && json.code !== 0 && !json.id)) {
      if (res.status === 401) this.forget();
      throw Object.assign(new Error('QQBOT_API_REFUSED: HTTP ' + res.status + ' ' + (json?.code ?? '') + ' '
        + String(json?.message ?? text).slice(0, 160)), { status: res.status, platform: json });
    }
    return json;
  }
}

export class QQBotBridge {
  /**
   * @param endpoint async () => {url, channelId, accountId, token, settings} | null — the channel API and this
   *   channel's settings with credentials resolved (core.channelEndpoint)
   */
  constructor({ endpoint, statePath, log = () => {}, info = () => {}, WebSocket = globalThis.WebSocket,
                fetch = globalThis.fetch, now = Date.now, retryMs = 5000 }) {
    this.endpoint = endpoint; this.statePath = statePath; this.log = log; this.info = info;
    this.WebSocket = WebSocket; this.fetch = fetch; this.now = now; this.retryMs = retryMs;
    this.state = { appId: null, session: null, pending: [], received: {}, seen: [] };
    this.stopped = false;
    this.sleepers = new Set();
    this.socket = null;
    this.api = null;
    this.status = 'starting';
    this.failures = 0;
    this.admissions = new Map();                      // conversation (and sender) -> the core's answer and until when
    this.epoch = null;                                // the core's start those answers belong to
    this.unsupportedSaid = 0;
  }

  async start() {
    try { this.state = { ...this.state, ...JSON.parse(await fs.readFile(this.statePath, 'utf8')) }; } catch { /* first run */ }
    this.gatewayLoop();
    this.outboundLoop();
    this.flushLoop();
  }

  stop() {
    this.stopped = true;
    clearInterval(this.beat);
    try { this.socket?.close(1000); } catch { /* closing */ }
    for (const wake of [...this.sleepers]) wake();
  }

  /** A wait that stop() ends at once. */
  sleep(ms) {
    return new Promise(resolve => {
      const done = () => { clearTimeout(timer); this.sleepers.delete(done); resolve(); };
      const timer = setTimeout(done, ms);
      this.sleepers.add(done);
    });
  }

  async save() {
    await fs.mkdir(path.dirname(this.statePath), { recursive: true });
    const temporary = this.statePath + '.tmp';
    await fs.writeFile(temporary, JSON.stringify(this.state)); await fs.rename(temporary, this.statePath);
  }

  /** The channel API, this bot's credentials and its platform client; null while the channel is not configured. */
  async host() {
    const host = await this.endpoint();
    const settings = host?.settings ?? {};
    if (!host?.token || !host.accountId || typeof settings.app_secret !== 'string' || !settings.app_secret) return null;
    if (this.state.appId !== host.accountId) {            // another bot: nothing of the last one carries over
      this.state = { appId: host.accountId, session: null, pending: [], received: {}, seen: [] };
      await this.save();
    }
    if (!this.api || this.api.appId !== host.accountId || this.api.secret !== settings.app_secret
        || this.api.apiBase !== String(settings.api_base ?? API_BASE).replace(/\/+$/, '')) {
      this.api = new QQBotApi({ appId: host.accountId, secret: settings.app_secret, apiBase: settings.api_base ?? API_BASE,
                                tokenUrl: settings.token_url ?? TOKEN_URL, fetch: this.fetch, now: this.now });
    }
    return host;
  }

  // ── the gateway: one session, resumed after a drop ────────────────
  async gatewayLoop() {
    while (!this.stopped) {
      let wait = this.retryMs;
      try {
        const host = await this.host();
        if (!host) { this.status = 'not configured'; await this.sleep(30000); continue; }
        const { url } = await this.api.call('GET', '/gateway');
        const code = await this.session(url, host);
        wait = code === 4914 || code === 4915 ? BLOCKED_RETRY_MS : BACKOFF_MS[Math.min(this.failures, BACKOFF_MS.length - 1)];
        if (code === 4914 || code === 4915) this.log('the platform refuses this bot\'s connection (close ' + code + '); next try in 10 minutes');
      } catch (error) {
        this.log('gateway: ' + error.message);
        wait = BACKOFF_MS[Math.min(this.failures, BACKOFF_MS.length - 1)];
      }
      this.failures += 1;
      if (!this.stopped) await this.sleep(wait);
    }
  }

  /** One connection, until it closes; resolves with the close code. */
  session(url, host) {
    return new Promise(resolve => {
      const socket = this.socket = new this.WebSocket(url);
      let acked = true;
      const finish = code => { clearInterval(this.beat); this.beat = null; resolve(code); };
      socket.onmessage = event => {
        let payload;
        try { payload = JSON.parse(typeof event.data === 'string' ? event.data : Buffer.from(event.data).toString('utf8')); }
        catch { return; }
        if (typeof payload.s === 'number' && this.state.session) this.state.session.seq = payload.s;
        if (payload.op === 10) {
          clearInterval(this.beat);
          this.beat = setInterval(() => {
            if (!acked) { this.log('gateway: heartbeat not acknowledged; reconnecting'); socket.close(4000); return; }
            acked = false;
            socket.send(JSON.stringify({ op: 1, d: this.state.session?.seq ?? null }));
          }, Number(payload.d?.heartbeat_interval ?? 41250));
          this.api.token().then(token => {
            const session = this.state.session;
            socket.send(JSON.stringify(session?.id
              ? { op: 6, d: { token: 'QQBot ' + token, session_id: session.id, seq: session.seq ?? 0 } }
              : { op: 2, d: { token: 'QQBot ' + token, intents: Number(host.settings.intents ?? INTENTS),
                              shard: [0, 1], properties: {} } }));
          }).catch(error => { this.log('gateway: ' + error.message); socket.close(4000); });
        } else if (payload.op === 11) acked = true;
        else if (payload.op === 1) socket.send(JSON.stringify({ op: 1, d: this.state.session?.seq ?? null }));
        else if (payload.op === 7) socket.close(4000);                    // the platform asks for a reconnect
        else if (payload.op === 9) {                                      // the session is gone: identify again
          if (!payload.d) this.state.session = null;
          socket.close(4000);
        } else if (payload.op === 0) this.dispatch(payload.t, payload.d ?? {}, payload.s).catch(error => this.log('inbound: ' + error.message));
      };
      socket.onclose = event => {
        const code = Number(event?.code ?? 0);
        if (SESSION_CLOSES.has(code) || (code >= 4900 && code <= 4913)) this.state.session = null;
        if (code === 4004) this.api?.forget();
        this.status = 'reconnecting (close ' + code + ')';
        this.save().catch(() => {});
        finish(code);
      };
      socket.onerror = () => { /* onclose follows */ };
    });
  }

  async dispatch(type, d, seq) {
    // Which events the platform pushes, by type: count and last time, no ids or text. The Host log may not be at
    // hand; this file is (`events`), and it tells whether a group sends every message or only those that @ her.
    const count = (this.state.events ??= {})[type] ??= { count: 0 };
    count.count += 1; count.last_at = new Date(this.now()).toISOString().replace(/\.\d{3}Z$/, 'Z');
    if (type === 'READY') {
      this.state.session = { id: d.session_id, seq: seq ?? 0 };
      this.status = 'connected'; this.failures = 0;
      this.info('connected as ' + (d.user?.username ?? 'the bot') + ' (new session)');
      await this.save(); return;
    }
    if (type === 'RESUMED') {
      this.status = 'connected'; this.failures = 0; this.info('connected (session resumed)');
      await this.save(); return;
    }
    if (type === 'C2C_MESSAGE_CREATE') return this.receive('dm', d, false);
    if (type === 'GROUP_AT_MESSAGE_CREATE') return this.receive('group', d, true);
    if (type === 'GROUP_MESSAGE_CREATE') return this.receive('group', d, (d.mentions ?? []).some(m => m?.is_you));
    this.info('event ' + type);
    await this.save();
  }

  // ── inbound: messages pushed by the platform ──────────────────────
  /**
   * What the core says about a sender in a conversation of this bot (POST …/admission): its route, or that it is not
   * admitted, kept for the time the core names (ADR-107). This bridge builds no route id and holds no policy.
   * Resolves 'away' when the core does not answer now and 'unsupported' when it predates the endpoint: the line waits.
   */
  async admission(host, ask, sender) {
    const conversation = ask.type + ':' + ask.id + ':', key = conversation + (ask.type === 'group' ? sender : '');
    const now = this.now();
    for (const name of [conversation, key]) {
      const kept = this.admissions.get(name);
      if (kept && kept.until > now && (name === key || !kept.answer.admitted || ask.type === 'dm')) return kept.answer;
    }
    let res, json;
    try {
      res = await this.fetch(`${host.url}/v1/channels/${host.channelId}/admission`, { method: 'POST',
        headers: { authorization: 'Bearer ' + host.token, 'content-type': 'application/json' },
        body: JSON.stringify({ account_id: host.accountId, asks: [{ conversation: ask,
          ...(ask.type === 'group' && sender ? { sender_id: sender } : {}) }] }), signal: AbortSignal.timeout(5000) });
      json = await res.json().catch(() => null);
    } catch { this.admissions.clear(); return 'away'; }
    if (res.status === 404 && json?.error === 'UNKNOWN_CHANNEL_ENDPOINT') {
      if (this.now() - this.unsupportedSaid > 60000) {
        this.unsupportedSaid = this.now();
        this.log('admission: the core does not know the admission endpoint; inbound lines wait until a core that does is installed');
      }
      return 'unsupported';
    }
    if (res.status >= 500 || (res.status === 403 && json?.error === 'CHANNEL_AUTH_REQUIRED')) { this.admissions.clear(); return 'away'; }
    const answer = json?.answers?.[0];
    if (res.status !== 200 || !['admitted', 'refused', 'blocked'].includes(answer?.verdict)) {
      this.log('admission: the core refused the question (' + res.status + ' ' + (json?.error ?? '') + ')');
      return 'away';
    }
    if (json.epoch !== undefined && json.epoch !== this.epoch) { this.admissions.clear(); this.epoch = json.epoch; }
    const ttl = Number(answer.ttl_seconds);
    const kept = { admitted: answer.verdict === 'admitted', route_id: answer.route_id ?? null };
    if (ttl > 0 && ttl <= 3600) {
      this.admissions.set(!kept.admitted && answer.scope === 'conversation' || ask.type === 'dm' ? conversation : key,
        { answer: kept, until: this.now() + ttl * 1000 });
    }
    return kept;
  }

  async receive(scope, d, mentionsMe) {
    const host = await this.host();
    if (!host) return;
    const author = d.author ?? {};
    const sender = scope === 'dm' ? author.user_openid ?? author.id : author.member_openid ?? author.id;
    const group = scope === 'group' ? d.group_openid ?? d.group_id : null;
    if (!OPENID.test(String(sender ?? '')) || (scope === 'group' && !OPENID.test(String(group ?? ''))) || !d.id) {
      this.log('inbound: a ' + scope + ' message without the ids this bridge needs was passed over'); return;
    }
    const target = scope === 'dm' ? sender : group;
    this.remember(scope + ':' + target, d.id, Date.parse(String(d.timestamp ?? '')));
    const key = scope + ':' + target + ':' + d.id;
    if (this.state.seen.includes(key)) return;
    const media = (Array.isArray(d.attachments) ? d.attachments : []).slice(0, 8).map(mediaItem);
    let text = [inboundText(d.content), ...media.map(item => item.placeholder)].filter(Boolean).join(' ');
    if (!text) text = '[非文字消息（未解析）]';
    if (text.length > TEXT_LIMIT) text = text.slice(0, TEXT_LIMIT - 1) + '…';
    const name = String(author.username ?? '').trim().slice(0, 60);
    const peer = name ? { person_id: 'qqbot:' + sender, account_id: sender, scene: group ? 'group:' + group : 'dm',
      ...(group ? { group_id: group } : {}), display: name, nickname: name, source: 'event_sender', verified: true,
      profile_at: new Date(this.now()).toISOString().replace(/\.\d{3}Z$/, 'Z') } : null;
    const mentions = scope === 'group' ? [...new Set([...(mentionsMe ? [host.accountId] : []),
      ...(d.mentions ?? []).filter(m => !m?.is_you && !m?.bot).map(m => m?.member_openid ?? m?.id).filter(id => OPENID.test(String(id ?? '')))])] : [];
    const occurred = isoOf(d.timestamp);
    const groupName = group ? await this.groupName(group) : null;
    this.state.pending.push({ _ask: { type: scope, id: target }, account_id: host.accountId,
      sender_id: sender, event_id: String(d.id), text, ...(occurred ? { occurred_at: occurred } : {}),
      ...(group ? { group_id: group, mentioned_account_ids: mentions } : {}),
      raw: { ...(peer ? { asuna_peer: peer } : {}), ...(media.length ? { asuna_media: { count: media.length, items: media } } : {}),
             ...(groupName ? { group_name: groupName } : {}) } });
    this.state.seen = [...this.state.seen, key].slice(-SEEN_KEPT);
    await this.save();
    await this.flush();
  }

  /** The group's name as the platform gives it (`/v2/groups/{openid}/info`), read once a day per group and kept with
   * when it was read; null when the platform gives none or refuses this bot the lookup. Never holds a message up long. */
  async groupName(group) {
    const known = (this.state.groups ??= {})[group];
    if (known && this.now() - Date.parse(known.read_at) < GROUP_NAME_MS) return known.name ?? null;
    let name = known?.name ?? null;
    try {
      const info = await this.api.call('GET', '/v2/groups/' + group + '/info', undefined, 5000);
      name = typeof info?.group_name === 'string' && info.group_name.trim() ? info.group_name.trim() : null;
    } catch (error) {
      if (!error.status) return name;                     // the platform did not answer: ask again with the next message
      name = null;                                        // refused (11253 without the platform's access): no name
    }
    this.state.groups[group] = { ...(name ? { name } : {}), read_at: new Date(this.now()).toISOString().replace(/\.\d{3}Z$/, 'Z') };
    return name;
  }

  /** A received message she may answer as a reply while the platform takes replies to it. Its window starts at its
   * platform send time (a message replayed after a gap is old), and a message pushed again keeps its count: a msg_seq
   * used twice is taken as the same message, so her later words would be dropped. */
  remember(conversation, id, sentAt) {
    const list = this.state.received[conversation] ?? [];
    if (list.some(item => item.id === String(id))) return;
    const at = Number.isFinite(sentAt) ? Math.min(sentAt, this.now()) : this.now();
    this.state.received[conversation] = [...list, { id: String(id), at, replies: 0 }].slice(-KEPT_PER_TARGET);
  }

  async flush() {
    if (this.flushing || !this.state.pending.length) return;
    this.flushing = true;
    try {
      const host = await this.endpoint();
      if (!host?.token) return;
      while (this.state.pending.length) {
        const { _ask, ...item } = this.state.pending[0];
        if (!item.route_id) {
          // Not yet judged: the core names the route, or says the sender is not admitted (the line is dropped).
          const answer = await this.admission(host, _ask, item.sender_id);
          if (answer === 'away' || answer === 'unsupported') return;       // the line waits, nothing is dropped
          if (!answer.admitted) { this.state.pending.shift(); await this.save(); continue; }
          item.route_id = answer.route_id;
        }
        const res = await this.fetch(`${host.url}/v1/channels/${host.channelId}/events`, { method: 'POST',
          headers: { authorization: 'Bearer ' + host.token, 'content-type': 'application/json' },
          body: JSON.stringify(item), signal: AbortSignal.timeout(30000) });
        if (res.status >= 500) return;                         // the host is restarting: retry later
        if (res.status >= 400) {
          this.log('inbound refused (' + res.status + '): ' + (await res.text()).slice(0, 200));
          this.admissions.clear();                             // the core did not take what it said it would
        }
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

  // ── outbound: her words to QQ ─────────────────────────────────────
  async outboundLoop() {
    while (!this.stopped) {
      try {
        const host = await this.host();
        if (!host) { await this.sleep(30000); continue; }
        const res = await this.fetch(`${host.url}/v1/channels/${host.channelId}/outbox?wait_seconds=25&supports=image`,
          { headers: { authorization: 'Bearer ' + host.token }, signal: AbortSignal.timeout(45000) });
        const json = await res.json().catch(() => null);
        if (res.status !== 200 || !Array.isArray(json?.items)) { await this.sleep(this.retryMs); continue; }
        for (const item of json.items) await this.deliver(host, item);
      } catch (error) {
        this.log('outbound: ' + error.message);
        await this.sleep(this.retryMs);
      }
    }
  }

  /** The received message to answer as a reply: the one she answers when the platform still takes a reply to it,
   * else the newest such one in that conversation; null when none is left (her words go out as her own message). */
  replyTo(conversation, scope, answered) {
    const window = REPLY_WINDOW[scope];
    const open = (this.state.received[conversation] ?? []).filter(item =>
      this.now() - item.at < window.ms - WINDOW_MARGIN_MS && item.replies < window.replies);
    return open.find(item => item.id === answered) ?? open.at(-1) ?? null;
  }

  async deliver(host, item) {
    const receipt = (status, response, id) => this.fetch(
      `${host.url}/v1/channels/${host.channelId}/outbox/${encodeURIComponent(item.publication_id)}/receipt`,
      { method: 'POST', headers: { authorization: 'Bearer ' + host.token, 'content-type': 'application/json' },
        signal: AbortSignal.timeout(30000),
        body: JSON.stringify({ attempt_id: item.attempt_id, status, response, ...(id ? { platform_message_id: id } : {}) }) });
    const target = item.target ?? {};
    const scope = target.type;
    if (!['dm', 'group'].includes(scope) || !OPENID.test(String(target.id ?? '')) || item.action || item.sticker) {
      await receipt('failed', { reason: 'this bridge sends text and pictures to a private chat or a group' }); return;
    }
    const base = scope === 'dm' ? '/v2/users/' + target.id : '/v2/groups/' + target.id;
    const text = item.attachment ? plainText(item.text) : null;
    let media = null;
    try {
      if (item.attachment) media = await this.upload(host, item, base);
    } catch (error) {
      await receipt(error.status ? 'failed' : 'unknown', { error: String(error.message).slice(0, 300), stage: 'picture' });
      return;
    }
    const body = media ? { msg_type: 7, media: { file_info: media }, ...(text ? { content: text } : {}) }
      : outboundBody(item.text, scope);
    if (!media && !(body.content ?? body.markdown.content)) { await receipt('failed', { reason: 'nothing to send' }); return; }
    const conversation = scope + ':' + target.id;
    const reply = this.replyTo(conversation, scope, item.reply_to);
    const post = async message => {
      if (!reply) return this.api.call('POST', base + '/messages', message);
      reply.replies += 1;                         // a msg_seq is used once, whatever the answer
      await this.save();
      try {
        return await this.api.call('POST', base + '/messages', { ...message, msg_id: reply.id, msg_seq: reply.replies });
      } catch (error) {
        if (!error.status || error.status >= 500 || MARKDOWN_REFUSED.has(Number(error.platform?.code))) throw error;
        // The platform no longer takes a reply to that message: send it as her own message once.
        this.info('a reply was refused (' + (error.platform?.code ?? error.status) + '); sending it as her own message');
        return this.api.call('POST', base + '/messages', message);
      }
    };
    try {
      let sent;
      try {
        sent = await post(body);
      } catch (error) {
        if (body.msg_type !== 2 || !MARKDOWN_REFUSED.has(Number(error.platform?.code))) throw error;
        // This bot may not send markdown: her words go as plain text, without the @.
        this.info('markdown was refused (' + error.platform.code + '); sending her words as plain text');
        sent = await post({ msg_type: 0, content: plainText(item.text) });
      }
      if (!sent?.id) throw Object.assign(new Error('QQBOT_SEND_UNCONFIRMED: no message id in the answer'), { status: 0 });
      await receipt('platform_accepted', { id: sent.id, timestamp: sent.timestamp ?? null,
        as: reply ? 'reply' : 'own message' }, String(sent.id));
    } catch (error) {
      // A refusal is a definite failure; a transport error may or may not have reached the platform.
      await receipt(error.status ? 'failed' : 'unknown', { error: String(error.message).slice(0, 300),
        code: error.platform?.code ?? null });
    }
  }

  /** The picture the item declares: read from the channel API, checked against its digest, uploaded for this
   * conversation; returns the platform's file_info. */
  async upload(host, item, base) {
    const attachment = item.attachment;
    const query = new URLSearchParams({ attempt_id: item.attempt_id, artifact_id: attachment.artifact_id });
    const res = await this.fetch(`${host.url}/v1/channels/${host.channelId}/outbox/${encodeURIComponent(item.publication_id)}/attachment?${query}`,
      { headers: { authorization: 'Bearer ' + host.token }, signal: AbortSignal.timeout(30000) });
    if (res.status !== 200) throw Object.assign(new Error('QQBOT_ATTACHMENT_REFUSED: HTTP ' + res.status), { status: res.status });
    const bytes = Buffer.from(await res.arrayBuffer());
    if (createHash('sha256').update(bytes).digest('hex') !== attachment.sha256) {
      throw Object.assign(new Error('QQBOT_ATTACHMENT_DIGEST_MISMATCH'), { status: 409 });
    }
    if (bytes.length > IMAGE_LIMIT) {
      throw Object.assign(new Error('QQBOT_PICTURE_TOO_LARGE: ' + bytes.length + ' bytes, the platform takes at most ' + IMAGE_LIMIT), { status: 413 });
    }
    const uploaded = await this.api.call('POST', base + '/files',
      { file_type: 1, file_data: bytes.toString('base64'), srv_send_msg: false });
    if (!uploaded?.file_info) throw Object.assign(new Error('QQBOT_UPLOAD_UNCONFIRMED: no file_info'), { status: 0 });
    return uploaded.file_info;
  }
}
