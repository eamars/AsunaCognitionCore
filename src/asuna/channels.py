"""Authenticated transport-neutral adapter seam. Platform protocol belongs to the adapter."""
import json
import secrets
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

from .evidence import canonical, sha
from .config import redact_text
from .queue import database_effects_lock
from .state import Denied, now


def route_for_scene(config, channel_id, scene_id):
    channel = config.get('channels', {}).get(channel_id)
    if channel:
        for route in channel['routes'].values():
            if route['scene_id'] == scene_id:
                return route
    raise Denied('CHANNEL_ROUTE_NOT_AUTHORIZED')


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
        allowed = {'route_id', 'account_id', 'sender_id', 'event_id', 'text', 'raw', 'occurred_at'}
        if set(body) - allowed:
            raise Denied('CHANNEL_ENVELOPE_FIELD_DENIED')
        channel = self.store.config['channels'][channel_id]
        route = channel['routes'].get(body.get('route_id'))
        if not route or body.get('account_id') != channel['account_id'] or body.get('sender_id') != route['sender_id']:
            raise Denied('CHANNEL_IDENTITY_DENIED')
        if not isinstance(body.get('event_id'), str) or not 1 <= len(body['event_id']) <= 200:
            raise ValueError('INVALID_PLATFORM_EVENT_ID')
        if not isinstance(body.get('text'), str) or not 1 <= len(body['text']) <= 16000:
            raise ValueError('INVALID_MESSAGE_TEXT')
        if 'occurred_at' in body and not isinstance(body['occurred_at'], str):
            raise ValueError('INVALID_OCCURRED_AT')
        # Namespaced by connection/account/scene; same text/time is not deduplication.
        event_id = 'channel-' + sha(canonical([channel_id, channel['account_id'], route['scene_id'], body['event_id']]))
        event = {'event_id': event_id, 'scene_id': route['scene_id'], 'person_id': route['person_id'],
                 'adapter_id': channel_id, 'text': body['text'],
                 'channel': {'id': channel_id, 'account_id': channel['account_id'],
                             'platform_event_id': body['event_id'], 'target': route['target']},
                 'raw': body.get('raw')}
        if 'occurred_at' in body:
            event['occurred_at'] = body['occurred_at']
        return self.controller.receive(event)

    def _valid_publication(self, message, channel_id):
        if not message or message.get('channel_id') != channel_id:
            raise Denied('PUBLICATION_NOT_FOUND')
        route = route_for_scene(self.store.config, channel_id, message['scene_id'])
        scene = self.store.authorize(message['scene_id'], route['person_id'])
        if (message['policy_epoch'] != scene['policy_epoch'] or message['scope_key'] != scene['scope_key']
                or message['target'] != route['target']
                or message['channel_account_id'] != self.store.config['channels'][channel_id]['account_id']):
            raise Denied('PUBLICATION_CONTEXT_STALE')
        episode = self.store.db.episodes.find_one({'_id': message['episode_id']})
        if not episode or episode['state'] not in ('SPEAK_ACCEPTED', 'WAITING_TASK', 'COMMITTED'):
            raise Denied('PUBLICATION_EPISODE_STALE')
        if episode.get('task_id'):
            task = self.store.db.tasks.find_one({'_id': episode['task_id']})
            if not task or task['intent_revision'] != episode['intent_revision'] or task['state'] in ('CANCELLED', 'STALE', 'UNKNOWN'):
                raise Denied('PUBLICATION_INTENT_STALE')

    def claim(self, channel_id, wait_seconds=0):
        deadline = time.monotonic() + min(25, max(0, wait_seconds))
        while not self.controller.stopping.is_set():
            with database_effects_lock(self.store.name):
                row = self.store.db.messages.find_one({'channel_id': channel_id, 'delivery_state': 'QUEUED_EXTERNAL'}, sort=[('scene_seq', 1)])
                if row:
                    try:
                        self._valid_publication(row, channel_id)
                    except Denied as exc:
                        self.store.put('messages', {**row, 'delivery_state': 'FAILED', 'failure': str(exc)},
                                       expected=row['revision'], stream=row['episode_id'])
                        continue
                    attempt = uuid.uuid4().hex
                    self.store.put('messages', {**row, 'delivery_state': 'SENDING',
                                   'attempt_id': attempt, 'claimed_at': now()}, expected=row['revision'], stream=row['episode_id'])
                    return {'items': [{'publication_id': row['_id'], 'attempt_id': attempt,
                                       'target': row['target'], 'text': row['text'],
                                       'reply_to': row['platform_reply_to']}]}
            if time.monotonic() >= deadline:
                break
            self.controller.stopping.wait(min(.2, max(0, deadline - time.monotonic())))
        return {'items': []}

    def receipt(self, channel_id, publication_id, body):
        if set(body) - {'attempt_id', 'status', 'platform_message_id', 'response'}:
            raise Denied('RECEIPT_FIELD_DENIED')
        status = body.get('status')
        if status not in ('platform_accepted', 'failed', 'unknown') or not isinstance(body.get('response'), dict):
            raise ValueError('INVALID_PLATFORM_RECEIPT')
        if status == 'platform_accepted' and (not isinstance(body.get('platform_message_id'), str) or not body['platform_message_id'].strip()):
            raise ValueError('PLATFORM_MESSAGE_ID_REQUIRED')
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
            return {'status': state}

    def recover_sending(self):
        # A lost HTTP response may hide an actual send. Never reclaim automatically.
        for row in self.store.db.messages.find({'channel_id': {'$exists': True}, 'delivery_state': 'SENDING'}):
            self.store.put('messages', {**row, 'delivery_state': 'UNKNOWN', 'recovery_reason': 'adapter_attempt_interrupted'},
                           expected=row['revision'], stream=row['episode_id'])


class ChannelServer:
    def __init__(self, channels, port=0):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                status = 200
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
                        value = channels.claim(channel_id, int(parse_qs(url.query).get('wait_seconds', ['0'])[0]))
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
