"""Business ownership for native DSH reminders; no host time wheel."""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .channels import route_for_scene, route_members
from .dsh_lane import DshLane
from .integration import event_granted
from .state import Denied, now


class ScheduleService:
    def __init__(self, app, controller):
        self.app, self.controller, self.store = app, controller, app.store
        self.deliver_lock = threading.RLock()
        self.token = secrets.token_hex(32)
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    if self.path != '/due' or not secrets.compare_digest(
                            self.headers.get('Authorization', ''), 'Bearer ' + service.token):
                        raise Denied('SCHEDULE_CALLBACK_DENIED')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 4096:
                        raise ValueError('INVALID_SCHEDULE_CALLBACK_SIZE')
                    service.deliver(json.loads(self.rfile.read(size)))
                    status, value = 200, {'accepted': True}
                except (Denied, ValueError, TypeError) as exc:
                    status, value = 400, {'error': str(exc)}
                except Exception as exc:
                    service.app.evidence.record('schedule.callback_error', {'reason': str(exc)})
                    status, value = 503, {'error': str(exc)}
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.lane = None
        try:
            self.lane = DshLane(app.config, self.store, app.evidence, 'scheduler',
                schedule_callback={'url': f'http://127.0.0.1:{self.server.server_port}/due', 'token': self.token})
            self.reconcile()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lane:
            self.lane.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _native_events(self):
        events = self.lane.schedule('/schedule/events')
        if not isinstance(events, list):
            raise ValueError('INVALID_NATIVE_SCHEDULE_LOG')
        return events

    def _created(self, plan_id, events):
        matches = [e['data']['schedule'] for e in events
                   if e['data'].get('operation') == 'create'
                   and e['data'].get('schedule', {}).get('prompt') == 'ASUNA_PLAN:' + plan_id]
        if len(matches) > 1:
            raise ValueError('DUPLICATE_NATIVE_PLAN')
        return matches[0] if matches else None

    def create(self, ep, spec):
        if not isinstance(spec, dict) or set(spec) != {'intent', 'after_seconds'} and set(spec) != {'intent', 'every_seconds'}:
            raise ValueError('INVALID_SCHEDULE_SPEC')
        intent = spec['intent']
        interval = spec.get('after_seconds', spec.get('every_seconds'))
        if not isinstance(intent, str) or not 1 <= len(intent.strip()) <= 1000 or type(interval) is not int:
            raise ValueError('INVALID_SCHEDULE_SPEC')
        if interval <= 0 or ('every_seconds' in spec and interval < 300):
            raise ValueError('INVALID_SCHEDULE_INTERVAL')
        scene = self.store.authorize(ep['scene_id'], ep['person_id'])
        if scene['policy_epoch'] != ep['policy_epoch']:
            raise Denied('SCHEDULE_SOURCE_STALE')
        plan_id = 'plan-' + ep['_id'][3:]
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if not plan:
            source = self.store.db.messages.find_one({'_id': 'in-' + ep['_id']})
            plan = self.store.put('plans', {'_id': plan_id, 'scene_id': ep['scene_id'],
                'person_id': ep['person_id'], 'scope_key': ep['scope_key'],
                'policy_epoch': ep['policy_epoch'], 'source_episode_id': ep['_id'],
                'intent': intent.strip(), 'rule': {k: v for k, v in spec.items() if k != 'intent'},
                'integration_profile': 'owner' if event_granted(self.app.config, (source or {}).get('event', {})) else None,
                'status': 'CREATING', 'created_at': now()}, stream=plan_id)
        elif plan['source_episode_id'] != ep['_id'] or plan['intent'] != intent.strip() or plan['rule'] != {k: v for k, v in spec.items() if k != 'intent'}:
            raise Denied('SCHEDULE_PLAN_CONTENT_CHANGED')
        if plan.get('schedule_id'):
            return plan
        existing = self._created(plan_id, self._native_events())
        native = existing or self.lane.schedule('/schedule/create', {'plan_id': plan_id, **plan['rule']})
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        current = self.store.db.plans.find_one({'_id': plan_id})
        return self.store.put('plans', {**current, 'schedule_id': native['id'],
            'scheduled_at': native['scheduledAt'], 'status': current['status']
                if current['status'] in ('FIRED','CANCELLED') else 'ACTIVE'},
            expected=current['revision'], stream=plan_id)

    def cancel(self, plan_id, scene_id, person_id, policy_epoch):
        plan = self.store.db.plans.find_one({'_id': plan_id, 'scene_id': scene_id,
            'person_id': person_id, 'policy_epoch': policy_epoch})
        if not plan:
            raise Denied('SCHEDULE_PLAN_NOT_IN_SCOPE')
        if plan['status'] == 'CANCELLED':
            return plan
        if plan.get('schedule_id'):
            self.lane.schedule('/schedule/delete', {'id': plan['schedule_id']})
        current = self.store.db.plans.find_one({'_id': plan_id})
        return self.store.put('plans', {**current, 'status': 'CANCELLED', 'cancelled_at': now()},
            expected=current['revision'], stream=plan_id)

    def reconcile(self):
        events = self._native_events()
        creates = {e['data']['schedule']['id']: e['data']['schedule'] for e in events
                   if e['data'].get('operation') == 'create'}
        for native in creates.values():
            prompt = native.get('prompt', '')
            if not prompt.startswith('ASUNA_PLAN:'):
                continue
            plan = self.store.db.plans.find_one({'_id': prompt.removeprefix('ASUNA_PLAN:')})
            if plan and not plan.get('schedule_id'):
                self.store.put('plans', {**plan, 'schedule_id': native['id'],
                    'scheduled_at': native['scheduledAt'], 'status': plan['status']
                        if plan['status'] in ('FIRED','CANCELLED') else 'ACTIVE'},
                    expected=plan['revision'], stream=plan['_id'])
        for event in events:
            if event['data'].get('operation') == 'dispatch':
                self._deliver(event['seq'], event['data']['id'], creates)

    def deliver(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'session', 'seq', 'id'}:
            raise ValueError('INVALID_SCHEDULE_CALLBACK')
        if payload['session'] != self.lane.scheduler_session or type(payload['seq']) is not int or not isinstance(payload['id'], str):
            raise Denied('SCHEDULE_CALLBACK_SOURCE_MISMATCH')
        events = self._native_events()
        dispatch = next((e for e in events if e['seq'] == payload['seq']
                         and e['data'].get('operation') == 'dispatch'
                         and e['data'].get('id') == payload['id']), None)
        if not dispatch:
            raise Denied('SCHEDULE_DISPATCH_NOT_FOUND')
        creates = {e['data']['schedule']['id']: e['data']['schedule'] for e in events
                   if e['data'].get('operation') == 'create'}
        self._deliver(payload['seq'], payload['id'], creates)

    def _deliver(self, seq, schedule_id, creates):
        # Startup reconciliation and a live native callback can see the same
        # durable dispatch. Serialize only the short host state transition;
        # never hold this lock across DSH, model, or tool execution.
        with self.deliver_lock:
            return self._deliver_locked(seq, schedule_id, creates)

    def _deliver_locked(self, seq, schedule_id, creates):
        native = creates.get(schedule_id)
        if not native or not native.get('prompt', '').startswith('ASUNA_PLAN:'):
            raise Denied('SCHEDULE_PLAN_LINK_MISSING')
        plan_id = native['prompt'].removeprefix('ASUNA_PLAN:')
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if not plan:
            raise Denied('SCHEDULE_PLAN_MISSING')
        occurrence = f'{self.lane.scheduler_session}:{seq}'
        if seq <= plan.get('last_dispatch_seq', -1) or plan['status'] in ('CANCELLED', 'FIRED'):
            return
        try:
            scene = self.store.authorize(plan['scene_id'], plan['person_id'])
            if scene['policy_epoch'] != plan['policy_epoch']:
                raise Denied('SCHEDULE_POLICY_STALE')
            channel = None
            if scene.get('channel_id'):
                route = route_for_scene(self.app.config, scene['channel_id'], scene['_id'])
                if plan['person_id'] not in {m['person_id'] for m in route_members(route).values()}:
                    raise Denied('SCHEDULE_ROUTE_REVOKED')
                channel = {'id': scene['channel_id'], 'account_id': scene['channel_account_id'],
                           'target': route['target'], 'sender_id': 'scheduler', 'platform_event_id': None}
            event = {'event_id': 'schedule:' + occurrence, 'scene_id': plan['scene_id'],
                     'person_id': plan['person_id'], 'adapter_id': 'scheduler',
                     'episode_kind': 'scheduled', 'scheduled_plan_id': plan_id,
                     'scene_tick': True,
                     'text': '你之前安排的计划「' + plan['intent'] + '」现在到期了。请重新判断是否继续；到期本身不是新授权或已完成的行动。'}
            if channel:
                event['channel'] = channel
                if scene['kind'] == 'group':
                    event['group_context'] = {'wake_reason': 'scheduled_plan',
                        'topic_id': event['event_id'], 'reply_to': None,
                        'reply_message_id': None, 'mentioned_account_ids': []}
            if plan.get('integration_profile') == 'owner' and event_granted(self.app.config,
                    {**event, 'integration_profile': 'owner'}):
                event['integration_profile'] = 'owner'
            self.controller.receive(event)
            outcome = 'ENQUEUED'
        except Denied as exc:
            outcome = str(exc)
        current = self.store.db.plans.find_one({'_id': plan_id})
        self.store.put('plans', {**current, 'last_occurrence_id': occurrence,
            'last_dispatch_seq': seq, 'last_occurrence_at': now(), 'last_outcome': outcome,
            'status': 'FIRED' if native['kind'] != 'every' else current['status']},
            expected=current['revision'], stream=plan_id)
        self.store.audit(plan_id, 'schedule.dispatched', {'occurrence': occurrence,
            'native_schedule_id': schedule_id, 'outcome': outcome}, plan['scope_key'])
