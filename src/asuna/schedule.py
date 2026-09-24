"""Business ownership for native DSH reminders; no host time wheel.

ADR-005 P3 起，这里同时是"自然语言安排"的落点：角色在 DECIDE 里给出 intent + 计时，
本模块把它换算成 plans 行与**原生那一次钟点**；每日/每周到期后由本模块再挂一次原生单次。
计时与唤醒仍然只有 DSH 一个时钟——这里没有线程、没有轮询、没有第二个 scheduler。
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .channels import route_for_scene, route_members
from .dsh_lane import DshLane
from .integration import event_granted
from .state import Conflict, Denied, now

try:                                  # 宿主按包加载
    from . import schedule_rules
except Exception:                     # 同目录平铺加载（离线自检）也认
    import schedule_rules


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
            self.ensure_self_development()
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

    def _grouped(self, events):
        """原生事件日志分三份：建过哪些、派发过哪些、删过哪些——认领与版本护栏只看这三样。"""
        creates = {e['data']['schedule']['id']: e['data']['schedule'] for e in events
                   if e['data'].get('operation') == 'create'}
        dispatched = {e['data'].get('id') for e in events if e['data'].get('operation') == 'dispatch'}
        deleted = {e['data'].get('id') for e in events if e['data'].get('operation') == 'delete'}
        return creates, dispatched, deleted

    def _live(self, plan_id, creates, dispatched, deleted, exclude=None):
        """这个计划名下还活着（建过、没派发、没删）的原生记录，按事件顺序从旧到新。"""
        return [row for native_id, row in creates.items()
                if native_id not in dispatched and native_id not in deleted and native_id != exclude
                and row.get('prompt') == 'ASUNA_PLAN:' + plan_id]

    def _created(self, plan_id, events):
        matches = [e['data']['schedule'] for e in events
                   if e['data'].get('operation') == 'create'
                   and e['data'].get('schedule', {}).get('prompt') == 'ASUNA_PLAN:' + plan_id]
        if len(matches) > 1:
            raise ValueError('DUPLICATE_NATIVE_PLAN')
        return matches[0] if matches else None

    def zone_of(self, scene, plan=None):
        """这个场景/这条计划用哪个钟面。计划上已落库的时区优先：改配置不追改旧安排。"""
        return schedule_rules.scene_timezone(self.app.config, scene or {}, plan)

    def ensure_self_development(self):
        """Register one native recurring opportunity, with no second host clock."""
        settings = self.app.config.get('self_development', {})
        if not settings.get('enabled'):
            return
        interval = settings.get('every_seconds', 86400)
        if type(interval) is not int or not schedule_rules.MIN_INTERVAL_SECONDS <= interval <= schedule_rules.MAX_INTERVAL_SECONDS:
            raise ValueError('SELF_DEVELOPMENT_INTERVAL_INVALID')
        scene_id, person_id = self.controller.settings['scene_id'], self.controller.settings['person_id']
        scene = self.store.authorize(scene_id, person_id)
        plan_id = 'plan-asuna-self-development'
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if plan and (plan.get('kind') != 'self_development' or plan['scene_id'] != scene_id
                     or plan['person_id'] != person_id or plan['policy_epoch'] != scene['policy_epoch']):
            raise Denied('SELF_DEVELOPMENT_PLAN_BINDING_CHANGED')
        if not plan:
            plan = self.store.put('plans', {'_id': plan_id, 'kind': 'self_development',
                'scene_id': scene_id, 'person_id': person_id, 'scope_key': scene['scope_key'],
                'policy_epoch': scene['policy_epoch'], 'status': 'CREATING',
                'intent': '回顾近期经历，自主决定是否继续自我开发',
                'rule': {'every_seconds': interval}, 'plan_version': 1,
                'created_at': now()}, stream=plan_id)
        events=self._native_events()
        creates, _, deleted=self._grouped(events)
        if plan.get('schedule_id') in creates and plan['schedule_id'] not in deleted:
            return
        native = (self._created(plan_id,events) if not plan.get('schedule_id') else None) or self.lane.schedule(
            '/schedule/create', {'plan_id': plan_id, 'every_seconds': plan['rule']['every_seconds']})
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SELF_DEVELOPMENT_CREATE_INCOMPLETE')
        current = self.store.db.plans.find_one({'_id': plan_id})
        self.store.put('plans', {**current, 'schedule_id': native['id'],
            'scheduled_at': native['scheduledAt'], 'status': 'ACTIVE'},
            expected=current['revision'], stream=plan_id)

    def create(self, ep, spec):
        intent = spec.get('intent') if isinstance(spec, dict) else None
        if not isinstance(intent, str) or not 1 <= len(intent.strip()) <= 1000:
            raise ValueError('INVALID_SCHEDULE_SPEC')
        rule = schedule_rules.normalize_rule(spec)          # 形状/间隔/钟点先判完，不碰库
        scene = self.store.authorize(ep['scene_id'], ep['person_id'])
        if scene['policy_epoch'] != ep['policy_epoch']:
            raise Denied('SCHEDULE_SOURCE_STALE')
        zone = self.zone_of(scene)
        fire_at = schedule_rules.next_fire(rule, zone['tz'], now())   # 已过/本地不存在都明确抛回
        plan_id = 'plan-' + ep['_id'][3:]
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if not plan:
            source = self.store.db.messages.find_one({'_id': 'in-' + ep['_id']})
            plan = self.store.put('plans', {'_id': plan_id, 'scene_id': ep['scene_id'],
                'person_id': ep['person_id'], 'scope_key': ep['scope_key'],
                'policy_epoch': ep['policy_epoch'], 'source_episode_id': ep['_id'],
                'intent': intent.strip(), 'rule': rule,
                'timezone': zone['name'], 'tz_source': zone['source'],
                'next_fire_at': fire_at.isoformat(timespec='seconds'), 'plan_version': 1,
                'integration_profile': 'owner' if event_granted(self.app.config, (source or {}).get('event', {})) else None,
                'status': 'CREATING', 'created_at': now()}, stream=plan_id)
        elif plan['source_episode_id'] != ep['_id'] or plan['intent'] != intent.strip() or plan['rule'] != rule:
            raise Denied('SCHEDULE_PLAN_CONTENT_CHANGED')
        if plan.get('schedule_id'):
            return plan
        existing = self._created(plan_id, self._native_events())
        native = existing or self.lane.schedule('/schedule/create',
            {'plan_id': plan_id, **schedule_rules.native_payload(rule, fire_at, now())})
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        current = self.store.db.plans.find_one({'_id': plan_id})
        return self.store.put('plans', {**current, 'schedule_id': native['id'],
            'scheduled_at': native['scheduledAt'], 'status': current['status']
                if current['status'] in ('FIRED','CANCELLED') else 'ACTIVE'},
            expected=current['revision'], stream=plan_id)

    def update(self, ep, plan_id, spec):
        """改期/改内容：在**同一条 plans** 下换掉底层原生提醒，只有当前版本会产生行动。

        先建新、再删旧：建新失败时旧的那一条还挂着，什么都没丢；删旧失败时多出来的那一条
        会被版本护栏挡住（派发时 schedule_id 对不上就不行动），不会多出两个同时有效的版本。
        """
        if not isinstance(spec, dict) or set(spec) - {'plan_id', 'intent', 'schedule'}:
            raise ValueError('INVALID_SCHEDULE_UPDATE')
        plan = self.store.db.plans.find_one({'_id': plan_id, 'scene_id': ep['scene_id'],
            'person_id': ep['person_id'], 'policy_epoch': ep['policy_epoch']})
        if not plan:
            raise Denied('SCHEDULE_PLAN_NOT_IN_SCOPE')
        if plan['status'] not in ('CREATING', 'ACTIVE'):
            raise Denied('SCHEDULE_PLAN_NOT_ACTIVE')
        scene = self.store.authorize(ep['scene_id'], ep['person_id'])
        if scene['policy_epoch'] != ep['policy_epoch']:
            raise Denied('SCHEDULE_SOURCE_STALE')
        zone = self.zone_of(scene, plan)
        timing = spec.get('schedule') if isinstance(spec.get('schedule'), dict) else \
            {key: value for key, value in spec.items() if key != 'plan_id'}
        rule = schedule_rules.normalize_rule(timing)
        intent = (spec.get('intent') or plan['intent']).strip()
        if not 1 <= len(intent) <= 1000:
            raise ValueError('INVALID_SCHEDULE_SPEC')
        fire_at = schedule_rules.next_fire(rule, zone['tz'], now())
        current = self.store.db.plans.find_one({'_id': plan_id})
        if current['rule'] == rule and current['intent'] == intent:
            return current                                  # 什么都没变就别动原生记录
        native = self.lane.schedule('/schedule/create',
            {'plan_id': plan_id, **schedule_rules.native_payload(rule, fire_at, now())})
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        stale, note = current.get('schedule_id'), None
        if stale and stale != native['id']:
            try:
                self.lane.schedule('/schedule/delete', {'id': stale})
            except BaseException as exc:                     # 旧的那条没删掉也不会重复行动
                note = 'STALE_NATIVE_DELETE_FAILED: ' + str(exc)
        updated = self.store.put('plans', {**current, 'rule': rule, 'intent': intent,
            'schedule_id': native['id'], 'scheduled_at': native['scheduledAt'],
            'next_fire_at': fire_at.isoformat(timespec='seconds'), 'timezone': zone['name'],
            'tz_source': zone['source'], 'plan_version': current.get('plan_version', 1) + 1,
            'updated_at': now(), 'status': 'ACTIVE',
            'last_update': {'from_rule': current['rule'], 'from_schedule_id': stale, 'note': note}},
            expected=current['revision'], stream=plan_id)
        self.store.audit(plan_id, 'schedule.updated', {'from_rule': current['rule'], 'to_rule': rule,
            'from_schedule_id': stale, 'native_schedule_id': native['id'], 'note': note,
            'plan_version': updated['plan_version'], 'next_fire_at': updated['next_fire_at']},
            plan['scope_key'])
        return updated

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
        cancelled = self.store.put('plans', {**current, 'status': 'CANCELLED', 'cancelled_at': now(),
            'next_fire_at': None}, expected=current['revision'], stream=plan_id)
        self.store.audit(plan_id, 'schedule.cancelled', {'native_schedule_id': plan.get('schedule_id'),
            'was_status': plan['status']}, plan['scope_key'])
        return cancelled

    def _rearm(self, plan_id, floor=None):
        """每日/每周到期后只再挂一次原生单次：错过的不补发，下一次永远只算未来。

        floor 是刚到期那一次的钟点：回调比宿主时钟早到几秒时，不拿它当"还没到"原地重挂，
        否则同一天会连响两次。
        """
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if not plan or plan['status'] in ('CANCELLED', 'FIRED', 'SUSPENDED'):
            return
        zone = self.zone_of(self.store.db.scenes.find_one({'_id': plan['scene_id']}), plan)
        moment = schedule_rules._aware(now()) if not floor else \
            max(schedule_rules._aware(now()), schedule_rules._aware(floor))   # 比时刻，不比字符串
        try:
            fire_at = schedule_rules.next_fire(plan['rule'], zone['tz'], moment)
        except ValueError as exc:
            current = self.store.db.plans.find_one({'_id': plan_id})
            self.store.put('plans', {**current, 'status': 'SUSPENDED', 'last_outcome': str(exc),
                'schedule_id': None, 'next_fire_at': None}, expected=current['revision'], stream=plan_id)
            self.store.audit(plan_id, 'schedule.suspended', {'reason': str(exc)}, plan['scope_key'])
            return
        creates, dispatched, deleted = self._grouped(self._native_events())
        live = self._live(plan_id, creates, dispatched, deleted, exclude=plan.get('schedule_id'))
        # 上次崩在"原生已建、plans 还没落库"之间时先认领那一条，不建第二份。
        native = live[-1] if live else self.lane.schedule('/schedule/create',
            {'plan_id': plan_id, **schedule_rules.native_payload(plan['rule'], fire_at, now())})
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        for _ in range(2):
            current = self.store.db.plans.find_one({'_id': plan_id})
            if current['status'] in ('CANCELLED', 'FIRED'):
                # 到期与取消撞在一起：刚挂的这条不属于任何有效版本，删掉，不留给后台复活。
                if not live:
                    try:
                        self.lane.schedule('/schedule/delete', {'id': native['id']})
                    except BaseException:
                        pass
                return
            try:
                self.store.put('plans', {**current, 'schedule_id': native['id'],
                    'scheduled_at': native['scheduledAt'],
                    'next_fire_at': fire_at.isoformat(timespec='seconds'),
                    'fire_count': current.get('fire_count', 0) + 1, 'status': 'ACTIVE'},
                    expected=current['revision'], stream=plan_id)
                break
            except Conflict:
                continue
        self.store.audit(plan_id, 'schedule.rearmed', {'native_schedule_id': native['id'],
            'next_fire_at': fire_at.isoformat(timespec='seconds'), 'adopted': bool(live),
            'extra_live_native': max(0, len(live) - 1)}, plan['scope_key'])

    def reconcile(self):
        events = self._native_events()
        creates, dispatched, deleted = self._grouped(events)
        # 先补做派发，再认领/重挂：反过来会把停机期间到期的那一次当成"旧版本"吞掉。
        for event in events:
            if event['data'].get('operation') == 'dispatch':
                self._deliver(event['seq'], event['data']['id'], creates)
        # 补做派发时可能已经顺手挂好了下一次：重新读一遍原生日志再判断谁还缺底层记录，
        # 不然拿旧快照会把刚挂上的那一条当成"不存在"，又挂一份出来。
        creates, dispatched, deleted = self._grouped(self._native_events())
        for native in creates.values():
            prompt = native.get('prompt', '')
            if not prompt.startswith('ASUNA_PLAN:'):
                continue
            plan_id = prompt.removeprefix('ASUNA_PLAN:')
            plan = self.store.db.plans.find_one({'_id': plan_id})
            if not plan or plan['status'] in ('CANCELLED', 'SUSPENDED'):
                continue
            if not plan.get('schedule_id'):
                self.store.put('plans', {**plan, 'schedule_id': native['id'],
                    'scheduled_at': native['scheduledAt'], 'status': plan['status']
                        if plan['status'] in ('FIRED','CANCELLED') else 'ACTIVE'},
                    expected=plan['revision'], stream=plan_id)
                continue
            if plan['status'] == 'ACTIVE' and (plan['schedule_id'] not in creates
                    or plan['schedule_id'] in dispatched or plan['schedule_id'] in deleted):
                # 底层记录已经不在了（改期或重建时断在中间）：先认领还活着的那一条，
                # 没有可认领的再按规则重挂下一次——不让一条 ACTIVE 挂着空指针等重启。
                live = self._live(plan_id, creates, dispatched, deleted, exclude=plan['schedule_id'])
                if live:
                    newest = live[-1]
                    self.store.put('plans', {**plan, 'schedule_id': newest['id'],
                        'scheduled_at': newest['scheduledAt']}, expected=plan['revision'], stream=plan_id)
                elif schedule_rules.rearms_after_fire(plan['rule']):
                    self._rearm(plan_id)

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
            action = self._deliver_locked(seq, schedule_id, creates)
        if action and action.get('rearm'):
            # 锁外挂下一次：不在原生调用上持锁。floor=刚到期那一次，回调早到也不原地重挂。
            self._rearm(action['plan_id'], action.get('fired_at'))

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
            return None
        if plan.get('schedule_id') and plan['schedule_id'] != schedule_id:
            # 改期换掉了底层提醒：旧版本那一次不再产生行动，只把序号记下来。
            current = self.store.db.plans.find_one({'_id': plan_id})
            self.store.put('plans', {**current, 'last_dispatch_seq': max(seq, current.get('last_dispatch_seq', -1)),
                'last_outcome': 'STALE_PLAN_VERSION'}, expected=current['revision'], stream=plan_id)
            self.store.audit(plan_id, 'schedule.stale_dispatch', {'occurrence': occurrence,
                'native_schedule_id': schedule_id, 'current_schedule_id': plan['schedule_id']},
                plan['scope_key'])
            return None
        try:
            scene = self.store.authorize(plan['scene_id'], plan['person_id'])
            if scene['policy_epoch'] != plan['policy_epoch']:
                raise Denied('SCHEDULE_POLICY_STALE')
            if plan.get('kind') == 'self_development':
                self.controller.offer_self_development('self-development:' + occurrence)
                outcome = 'ENQUEUED'
            else:
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
        except Exception as exc:
            # 一次到期没排进去，只记在这一条计划上：下一次登记、这个场景的聊天都不跟着消失。
            outcome = str(exc) or type(exc).__name__
        current = self.store.db.plans.find_one({'_id': plan_id})
        repeating = schedule_rules.rearms_after_fire(current['rule'])
        status = current['status']
        if status != 'CANCELLED':
            status = 'ACTIVE' if repeating else ('FIRED' if native['kind'] != 'every' else status)
        self.store.put('plans', {**current, 'last_occurrence_id': occurrence,
            'last_dispatch_seq': seq, 'last_occurrence_at': now(), 'last_outcome': outcome,
            'next_fire_at': None if status == 'FIRED' else current.get('next_fire_at'),
            'status': status}, expected=current['revision'], stream=plan_id)
        self.store.audit(plan_id, 'schedule.dispatched', {'occurrence': occurrence,
            'native_schedule_id': schedule_id, 'outcome': outcome, 'rearm': repeating}, plan['scope_key'])
        return {'plan_id': plan_id, 'rearm': repeating and status == 'ACTIVE',
            'fired_at': native.get('scheduledAt')}
