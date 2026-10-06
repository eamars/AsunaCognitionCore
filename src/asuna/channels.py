"""Authenticated transport-neutral adapter seam. Platform protocol belongs to the adapter."""
import json
import secrets
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

from .evidence import canonical, sha
from .config import redact_text, character_id
from .queue import database_effects_lock
from .state import Denied, now
from .people import People

try:                                  # 出站图片附件：元数据、字节端点的围栏都在 outbound_media
    from . import outbound_media
except Exception:                     # 同目录平铺加载（离线自检）也认
    import outbound_media


def route_for_scene(config, channel_id, scene_id):
    channel = config.get('channels', {}).get(channel_id)
    if channel:
        for route in channel['routes'].values():
            if route['scene_id'] == scene_id:
                return route
    raise Denied('CHANNEL_ROUTE_NOT_AUTHORIZED')


def route_members(route):
    if route['target']['type'] == 'dm':
        return {route['sender_id']: route}
    if route['target']['type'] == 'group':
        return route.get('members', {})
    raise Denied('CHANNEL_TARGET_TYPE_DENIED')


def kept_raw(event, raw):
    """What of the adapter's raw event the host keeps: the sender profile verified against this
    authenticated sender and group, the normalized media block, and the group's name. The platform
    event itself (and anything else an adapter puts there) is never stored."""
    from .peer_context import snapshot_event
    from .vision import MEDIA_KEY
    raw = raw if isinstance(raw, dict) else {}
    kept = {}
    peer = snapshot_event({**event, 'raw': raw})
    if peer:
        kept['asuna_peer'] = peer
    if isinstance(raw.get(MEDIA_KEY), dict):
        kept[MEDIA_KEY] = raw[MEDIA_KEY]
    if isinstance(raw.get('group_name'), str) and raw['group_name'].strip():
        kept['group_name'] = ' '.join(raw['group_name'].split())[:60]
    own = raw.get('asuna_self')
    if (event.get('channel') or {}).get('target', {}).get('type') == 'group' and isinstance(own, dict) \
            and own.get('role') in ('owner', 'admin', 'member'):
        kept['asuna_self'] = {'role': own['role']}            # her own role in this group (group_admin.py)
    return kept


def called_by_name(store, text):
    """Whether a message says one of her names (her display name and the persona's other names, 2+ characters)."""
    text = ' '.join(str(text or '').split())
    return any(len(name) >= 2 and name in text for name in People(store).self_names)


# A line of hers that waits for an answer (role_tools.await_answer): the asked person's next unaddressed line
# within this long gets her one look. Human answers in her groups: median 40 s, 90% within ~3 min (2026-10-06).
AWAIT_SECONDS = 180


def awaited_answer(store, scene, person_id, mentions, reply):
    """Whether this unaddressed line may be the answer her last line here waits for: her newest delivered line
    in this group asked for one, it was under AWAIT_SECONDS ago, this is the person it answered (anyone, when her
    line answered nobody), the line @s or quotes no one else, and that line has not had its look yet."""
    if mentions or reply:
        return False                   # addressed to someone: an @ or quote of her is already its own wake
    mine = store.db.messages.find_one({'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
                                       'direction': 'outbound', 'delivery_state': 'DELIVERED',
                                       'author': character_id(store.config)}, sort=[('scene_seq', -1)])
    if not mine or not mine.get('receipt_at'):
        return False
    try:
        since = datetime.now(timezone.utc) - datetime.fromisoformat(str(mine['receipt_at']).replace('Z', '+00:00'))
    except ValueError:
        return False
    if since.total_seconds() > AWAIT_SECONDS:
        return False
    ep = store.db.episodes.find_one({'_id': mine.get('episode_id')}, {'await_answer': 1}) or {}
    if not ep.get('await_answer'):
        return False
    asked = (store.db.messages.find_one({'_id': mine.get('reply_to')}, {'author': 1, 'direction': 1}) or {})
    if asked.get('direction') == 'inbound' and asked.get('author') and asked['author'] != person_id:
        return False
    return not store.db.messages.find_one({'scene_id': scene['_id'], 'scene_seq': {'$gt': mine.get('scene_seq', 0)},
                                           'event.group_context.wake_reason': 'awaited_answer'}, {'_id': 1})


def group_context(store, route, body, event_id, person_id=None):
    """Bind a normalized reply to an actual record in this group and epoch."""
    mentions = body.get('mentioned_account_ids', [])
    if not isinstance(mentions, list) or len(mentions) > 100 or any(not isinstance(v, str) for v in mentions):
        raise ValueError('INVALID_MENTIONS')
    reply = body.get('reply_to')
    if reply is not None and (not isinstance(reply, str) or not 1 <= len(reply) <= 200):
        raise ValueError('INVALID_REPLY_ID')
    scene = store.db.scenes.find_one({'_id': route['scene_id']})
    parent = None
    if reply:
        parent = store.db.messages.find_one({'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
            '$or': [{'direction': 'inbound', 'event.channel.platform_event_id': reply},
                    {'direction': 'outbound', 'platform_message_id': reply, 'delivery_state': 'DELIVERED', 'author': character_id(store.config)}]})
    reason = 'mentioned_account' if body['account_id'] in mentions else None
    topic = topic_via = None
    if parent:
        previous = parent.get('event', {}).get('group_context', {})
        recent = parent.get('received_at', parent.get('receipt_at', '')) >= (datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat()
        if parent['direction'] == 'outbound':
            reason = reason or 'reply_to_character'
            origin = store.db.messages.find_one({'_id': 'in-'+parent['episode_id']})
            topic = (origin or {}).get('event', {}).get('group_context', {}).get('topic_id')
            topic_via = 'reply_to_character'
        elif previous.get('wake_reason') and recent:
            # 唤醒口径不变：父行本身被唤醒过（或她回过我）才算"活跃话题里的接话"。
            reason = reason or 'reply_in_active_topic'
            topic, topic_via = previous.get('topic_id'), 'reply_in_active_topic'
        elif previous.get('topic_id'):
            # P5：旁听来的那条线也认得出属于哪个话题，只是不因此唤醒她。
            topic, topic_via = previous['topic_id'], 'reply_chain'
    if not reason and called_by_name(store, body.get('text')):
        # Her name without an @: the relevance gate decides whether that was meant for her (attend.py).
        reason = 'name_called'
    if not reason and person_id and awaited_answer(store, scene, person_id, mentions, reply):
        reason = 'awaited_answer'          # one look, through the relevance gate (attend.py)
    if topic is None:
        topic, topic_via = event_id, (topic_via or ('mentioned' if reason else 'new'))
    return {'wake_reason': reason, 'topic_id': topic, 'topic_via': topic_via,
            'reply_to': reply, 'reply_message_id': parent['_id'] if parent else None,
            'mentioned_account_ids': mentions}


class Channels:
    def __init__(self, controller):
        self.controller = controller
        self.store = controller.app.store

    def authenticate(self, channel_id, authorization):
        channel = self.store.config.get('channels', {}).get(channel_id)
        if not channel or not secrets.compare_digest(authorization, 'Bearer ' + channel['token']):
            raise Denied('CHANNEL_AUTH_REQUIRED')
        return channel

    def receive(self, channel_id, body):
        # Admission and input persistence share the controller's existing fence.
        with self.controller.ingress_lock:
            if self.controller.reconfiguring or self.controller.stopping.is_set():
                raise RuntimeError('HOST_RECONFIGURING')
            return self._receive(channel_id, body)

    def _receive(self, channel_id, body):
        allowed = {'route_id', 'account_id', 'sender_id', 'event_id', 'text', 'raw', 'occurred_at', 'mentioned_account_ids', 'reply_to', 'group_id'}
        if set(body) - allowed:
            raise Denied('CHANNEL_ENVELOPE_FIELD_DENIED')
        # Reject malformed payloads before any automatic enrollment writes.
        if not isinstance(body.get('event_id'), str) or not 1 <= len(body['event_id']) <= 200:
            raise ValueError('INVALID_PLATFORM_EVENT_ID')
        if not isinstance(body.get('text'), str) or not 1 <= len(body['text']) <= 16000:
            raise ValueError('INVALID_MESSAGE_TEXT')
        if 'occurred_at' in body and not isinstance(body['occurred_at'], str):
            raise ValueError('INVALID_OCCURRED_AT')
        if body.get('group_id') is None and any(k in body for k in ('group_id', 'mentioned_account_ids', 'reply_to')):
            raise Denied('DM_GROUP_FIELDS_DENIED')
        mentions, reply = body.get('mentioned_account_ids', []), body.get('reply_to')
        if not isinstance(mentions, list) or len(mentions) > 100 or any(not isinstance(v, str) for v in mentions):
            raise ValueError('INVALID_MENTIONS')
        if reply is not None and (not isinstance(reply, str) or not 1 <= len(reply) <= 200):
            raise ValueError('INVALID_REPLY_ID')
        channel = self.store.config['channels'][channel_id]
        if channel.get('admission') == 'automatic' or channel.get('blocked_senders') or channel.get('blocked_groups'):
            from .channel_admission import admit
            admit(self.controller, channel_id, body)
        route = channel['routes'].get(body.get('route_id'))
        member = route_members(route).get(body.get('sender_id')) if route else None
        if not member or body.get('account_id') != channel['account_id']:
            raise Denied('CHANNEL_IDENTITY_DENIED')
        if route['target']['type'] == 'group' and body.get('group_id') != route['target']['id']:
            raise Denied('CHANNEL_GROUP_DENIED')
        if route['target']['type'] == 'dm' and any(k in body for k in ('group_id', 'mentioned_account_ids', 'reply_to')):
            raise Denied('DM_GROUP_FIELDS_DENIED')
        if not isinstance(body.get('event_id'), str) or not 1 <= len(body['event_id']) <= 200:
            raise ValueError('INVALID_PLATFORM_EVENT_ID')
        if not isinstance(body.get('text'), str) or not 1 <= len(body['text']) <= 16000:
            raise ValueError('INVALID_MESSAGE_TEXT')
        if 'occurred_at' in body and not isinstance(body['occurred_at'], str):
            raise ValueError('INVALID_OCCURRED_AT')
        # Namespaced by connection/account/scene; same text/time is not deduplication.
        event_id = 'channel-' + sha(canonical([channel_id, channel['account_id'], route['scene_id'], body['event_id']]))
        event = {'event_id': event_id, 'scene_id': route['scene_id'], 'person_id': member['person_id'],
                 'adapter_id': channel_id, 'text': body['text'],
                 'channel': {'id': channel_id, 'account_id': channel['account_id'],
                             'platform_event_id': body['event_id'], 'target': route['target'], 'sender_id': body['sender_id']}}
        event['raw'] = kept_raw(event, body.get('raw'))
        if route['target']['type'] == 'group':
            event['group_context'] = group_context(self.store, route, body, event_id, member['person_id'])
        if 'occurred_at' in body:
            event['occurred_at'] = body['occurred_at']
        from . import lines
        if lines.is_closed(self.store, route['scene_id']):
            return {'status': 'line_closed'}           # she closed this peer line: passed over, never replayed
        return self.controller.receive(event)

    def _valid_publication(self, message, channel_id):
        if not message or message.get('channel_id') != channel_id:
            raise Denied('PUBLICATION_NOT_FOUND')
        route = route_for_scene(self.store.config, channel_id, message['scene_id'])
        episode = self.store.db.episodes.find_one({'_id': message['episode_id']})
        channel = self.store.config['channels'][channel_id]
        allowed = {grant['person_id'] for sender, grant in route_members(route).items()
                   if sender not in channel.get('blocked_senders', [])}
        if route['target']['type'] == 'group' and route['target']['id'] in channel.get('blocked_groups', []):
            allowed.clear()
        if not episode or episode['person_id'] not in allowed:
            raise Denied('PUBLICATION_MEMBER_REVOKED')
        scene = self.store.authorize(message['scene_id'], episode['person_id'])
        if (message['policy_epoch'] != scene['policy_epoch'] or message['scope_key'] != scene['scope_key']
                or message['target'] != route['target']
                or message['channel_account_id'] != self.store.config['channels'][channel_id]['account_id']):
            raise Denied('PUBLICATION_CONTEXT_STALE')
        if not episode or episode['state'] not in ('SPEAK_ACCEPTED', 'WAITING_TASK', 'COMMITTED'):
            raise Denied('PUBLICATION_EPISODE_STALE')
        if episode.get('task_id'):
            task = self.store.db.tasks.find_one({'_id': episode['task_id']})
            if not task or task['intent_revision'] != episode['intent_revision'] or task['state'] in ('CANCELLED', 'STALE'):
                raise Denied('PUBLICATION_INTENT_STALE')

    def claim(self, channel_id, wait_seconds=0, supports=None):
        # supports 是领取方声明的能力（napcat-qq 0.5.0 起带 supports=image）。没声明就只给文字，并把
        # 「这条本来带图、图没跟着出去」记在行上：只发文字却报平台已送达，等于声称对方收到一张没到的图。
        from . import group_admin
        deadline = time.monotonic() + min(25, max(0, wait_seconds))
        while not self.controller.stopping.is_set():
            if self.controller.reconfiguring:
                return {'items': []}
            with database_effects_lock(self.store.name):
                action = group_admin.claim(self.store, channel_id)       # an admin action goes before her words
                if action:
                    return {'items': [action]}
                row = self.store.db.messages.find_one({'channel_id': channel_id, 'delivery_state': 'QUEUED_EXTERNAL'}, sort=[('scene_seq', 1)])
                # A paced segment holds the line until its time and until earlier segments are delivered,
                # so later messages never overtake it (ADR-009 §11.1).
                if row and row.get('not_before') and row['not_before'] > now():
                    row = None
                if row and row.get('segment_index') and self.store.db.messages.find_one({'episode_id': row['episode_id'],
                        'phase': 'SPEAK', 'segment_index': {'$lt': row['segment_index']}, 'delivery_state': {'$ne': 'DELIVERED'}}):
                    row = None
                if row:
                    try:
                        self._valid_publication(row, channel_id)
                    except Denied as exc:
                        failed = self.store.put('messages', {**row, 'delivery_state': 'FAILED', 'failure': str(exc)},
                                                expected=row['revision'], stream=row['episode_id'])
                        from .publish import PublishService
                        PublishService(self.store).cancel_after(failed)
                        continue
                    sticker = row.get('sticker') if isinstance(row.get('sticker'), dict) else None
                    if sticker and 'sticker' not in (supports or ()):
                        # A sticker is the whole message: one this adapter cannot send is not sent at all (ADR-016).
                        failed = self.store.put('messages', {**row, 'delivery_state': 'FAILED',
                                                'failure': 'CHANNEL_DOES_NOT_DECLARE_STICKER'},
                                                expected=row['revision'], stream=row['episode_id'])
                        from .publish import PublishService
                        PublishService(self.store).cancel_after(failed)
                        continue
                    attempt = uuid.uuid4().hex
                    declared = outbound_media.descriptor(row)
                    carries = bool(declared) and outbound_media.supports_image(supports)
                    changes = {**row, 'delivery_state': 'SENDING', 'attempt_id': attempt, 'claimed_at': now()}
                    if declared and not carries:
                        changes[outbound_media.SKIPPED_KEY] = outbound_media.NO_CAPABILITY
                    elif carries:
                        # 这次真把图带出去：上一次留下的「没带出去」不能接着算（重投的行会带着旧标记回来）
                        changes.pop(outbound_media.SKIPPED_KEY, None)
                    self.store.put('messages', changes, expected=row['revision'], stream=row['episode_id'])
                    # Her @[label] becomes the adapter's @qq:<account> here, at the edge (people.py).
                    scene = self.store.db.scenes.find_one({'_id': row['scene_id']})
                    text = People(self.store).outbound(scene, row['text']) if scene else row['text']
                    item = {'publication_id': row['_id'], 'attempt_id': attempt,
                            'target': row['target'], 'text': text,
                            'reply_to': row['platform_reply_to']}
                    if carries:
                        item[outbound_media.ATTACHMENT_KEY] = declared      # 只有元数据，不带 base64；字节走下面的 GET
                    if sticker:
                        # her row keeps the [表情包:名字] she wrote; the platform gets the sticker alone
                        item['text'] = ''
                        item['sticker'] = {k: v for k, v in sticker.items() if k != 'name'}
                    return {'items': [item]}
            if time.monotonic() >= deadline:
                break
            self.controller.stopping.wait(min(.2, max(0, deadline - time.monotonic())))
        return {'items': []}

    def attachment(self, channel_id, publication_id, query=None):
        """字节端点：GET /v1/channels/<id>/outbox/<pub>/attachment?attempt_id=…&artifact_id=…

        同一个 Bearer token（HTTP 层已经验过）。只允许这条 publication 自己声明的那份 artifact；
        attempt_id 必须属于这条且它正在 SENDING；字节从 BlobStore 读，按行内 sha 复核
        （围栏都在 outbound_media.serve）。行上记着 ``attachment_skipped``（那次领取没声明能收图）
        也算「没声明」：元数据还留在行上只为历史，字节一律 403 ATTACHMENT_NOT_DECLARED。
        返回 ``(data, media_type)``。
        """
        query = query or {}
        attempt_id = (query.get('attempt_id') or [''])[0]
        wanted = (query.get('artifact_id') or [''])[0]
        with database_effects_lock(self.store.name):
            row = self.store.db.messages.find_one({'_id': publication_id})
            if not row or row.get('channel_id') != channel_id:
                raise Denied('PUBLICATION_NOT_FOUND')
            if row.get('delivery_state') != 'SENDING' or not row.get('attempt_id') \
                    or row['attempt_id'] != attempt_id:
                raise Denied('PUBLICATION_ATTEMPT_MISMATCH')
            declared = outbound_media.declared(row)      # 元数据在 ≠ 声明了：skipped 的行一律拒
            if not declared:
                raise Denied('ATTACHMENT_NOT_DECLARED')
            if wanted and wanted != declared['artifact_id']:
                raise Denied('ATTACHMENT_ARTIFACT_DENIED')       # 只发这条自己声明的那张，别人给不了
            from .blobs import BlobStore
            return outbound_media.serve(self.store, BlobStore(self.store), row, declared)

    def receipt(self, channel_id, publication_id, body):
        if set(body) - {'attempt_id', 'status', 'platform_message_id', 'response'}:
            raise Denied('RECEIPT_FIELD_DENIED')
        status = body.get('status')
        if status not in ('platform_accepted', 'failed', 'unknown') or not isinstance(body.get('response'), dict):
            raise ValueError('INVALID_PLATFORM_RECEIPT')
        if status == 'platform_accepted' and (not isinstance(body.get('platform_message_id'), str) or not body['platform_message_id'].strip()):
            raise ValueError('PLATFORM_MESSAGE_ID_REQUIRED')
        if publication_id.startswith('ga-'):
            from . import group_admin
            with database_effects_lock(self.store.name):
                return group_admin.receipt(self.store, channel_id, publication_id, body)
        with database_effects_lock(self.store.name):
            row = self.store.db.messages.find_one({'_id': publication_id})
            # An already claimed send may have happened before revocation. Preserve
            # the factual receipt without authorizing a new send or target change.
            if not row or row.get('channel_id') != channel_id:
                raise Denied('PUBLICATION_NOT_FOUND')
            if not row.get('attempt_id') or body.get('attempt_id') != row['attempt_id']:
                raise Denied('PUBLICATION_ATTEMPT_MISMATCH')
            if row.get('platform_receipt') == body:
                return {'status': row['delivery_state']}
            if row['delivery_state'] not in ('SENDING', 'UNKNOWN'):
                raise Denied('PUBLICATION_RECEIPT_CONFLICT')
            state = {'platform_accepted': 'DELIVERED', 'failed': 'FAILED', 'unknown': 'UNKNOWN'}[status]
            self.store.put('messages', {**row, 'delivery_state': state, 'platform_receipt': body,
                           'platform_message_id': body.get('platform_message_id'), 'receipt_at': now(),
                           'delivery_basis': 'platform_ack' if state == 'DELIVERED' else status},
                           expected=row['revision'], stream=row['episode_id'])
            if state != 'DELIVERED':
                from .publish import PublishService
                PublishService(self.store).cancel_after({**row, 'delivery_state': state})
            return {'status': state}

    def recover_sending(self):
        # A lost HTTP response may hide an actual send. Never reclaim automatically.
        from .publish import PublishService
        from . import group_admin
        group_admin.recover_sending(self.store)
        for row in self.store.db.messages.find({'channel_id': {'$exists': True}, 'delivery_state': 'SENDING'}):
            unknown = self.store.put('messages', {**row, 'delivery_state': 'UNKNOWN', 'recovery_reason': 'adapter_attempt_interrupted'},
                                     expected=row['revision'], stream=row['episode_id'])
            PublishService(self.store).cancel_after(unknown)


class ChannelServer:
    def __init__(self, channels, port=0):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                status = 200
                raw = None                      # (bytes, content_type)：只有附件端点走这一条
                try:
                    url = urlsplit(self.path)
                    parts = [unquote(part) for part in url.path.strip('/').split('/')]
                    if len(parts) < 4 or parts[:2] != ['v1', 'channels']:
                        raise ValueError('UNKNOWN_CHANNEL_ENDPOINT')
                    channel_id = parts[2]
                    channels.authenticate(channel_id, self.headers.get('Authorization', ''))
                    body = {}
                    if self.command == 'POST':
                        size = int(self.headers.get('Content-Length', '0'))
                        if not 0 < size <= 262144:
                            raise ValueError('INVALID_BODY_SIZE')
                        body = json.loads(self.rfile.read(size))
                        if not isinstance(body, dict):
                            raise ValueError('INVALID_BODY')
                    if self.command == 'POST' and parts[3:] == ['events']:
                        value = channels.receive(channel_id, body)
                    elif self.command == 'GET' and parts[3:] == ['outbox']:
                        query = parse_qs(url.query)
                        value = channels.claim(channel_id, int(query.get('wait_seconds', ['0'])[0]),
                                               supports=outbound_media.parse_supports(query))
                    elif self.command == 'GET' and len(parts) == 6 and parts[3] == 'outbox' and parts[5] == 'attachment':
                        payload = channels.attachment(channel_id, parts[4], parse_qs(url.query))
                        raw = payload if isinstance(payload, tuple) else None
                        value = {} if raw is not None else payload
                    elif self.command == 'POST' and len(parts) == 6 and parts[3] == 'outbox' and parts[5] == 'receipt':
                        value = channels.receipt(channel_id, parts[4], body)
                    else:
                        status, value = 404, {'error': 'UNKNOWN_CHANNEL_ENDPOINT'}
                except PermissionError as exc:
                    status, value = 403, {'error': str(exc)}
                except (ValueError, TypeError) as exc:
                    status, value = 400, {'error': str(exc)}
                except Exception:
                    # Database addresses/credentials never cross the adapter boundary.
                    error = redact_text(traceback.format_exc(), channels.store.config)
                    channels.controller.app.evidence.record('host.channel_error', {'traceback': error})
                    channels.controller.emit('[系统] 通道接口未完成：\n' + error)
                    status, value = 503, {'error': 'HOST_TEMPORARILY_UNAVAILABLE'}
                if raw is not None and status == 200:
                    data, media_type = raw
                    self.send_response(200)
                    self.send_header('Content-Type', media_type)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = handle_request
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
