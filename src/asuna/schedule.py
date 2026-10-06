"""Business ownership for native DSH reminders; no host time wheel.

ADR-005 P3 起，这里同时是"自然语言安排"的落点：角色在 DECIDE 里给出 intent + 计时，
本模块把它换算成 plans 行与**原生那一次钟点**；每日/每周到期后由本模块再挂一次原生单次。
计时与唤醒仍然只有 DSH 一个时钟——这里没有线程、没有轮询、没有第二个 scheduler。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import threading

from .channels import route_for_scene, route_members
from .integration import event_granted
from .state import Conflict, Denied, now

try:                                  # 宿主按包加载
    from . import schedule_rules
except Exception:                     # 同目录平铺加载（离线自检）也认
    import schedule_rules

# Her rhythm plans belong to the program (ADR-012 §4.3): she never sees them in her plan list, so she cannot
# cancel or retime them there; she sets the heartbeat's pace through her policy keys.
RHYTHM_KINDS = ('presence', 'settlement', 'self_development')
PRESENCE_PLAN = 'plan-asuna-presence'
HEARTBEAT_BEATS_PER_DAY = 24          # beats that reach the model, per local day
HEARTBEAT_GRACE_SECONDS = 300         # a heartbeat silent for two beats and this long is rebuilt
# How her reminders are named in DSH's own task page (ADR-012 §8), where the owner sees each one's next run
# and delivery records. Her own plans are named by what she wrote; her rhythms by what they are.
RHYTHM_TITLES = {'presence': '心跳 · Heartbeat', 'settlement': '夜间沉淀 · Nightly settlement',
                 'self_development': '自我改进 · Self-improvement'}
TITLE_CHARS = 60
LEGACY_TITLE = 'Asuna · '
# An in-place timing change names DSH's own timing kind (its `every` carries every_seconds).
NATIVE_KIND = {'every_seconds': 'every'}


def plan_title(plan):
    if plan.get('kind') in RHYTHM_TITLES:
        return RHYTHM_TITLES[plan['kind']]
    line = ' '.join(str(plan.get('intent') or '').split())
    return (line[:TITLE_CHARS] + '…' if len(line) > TITLE_CHARS else line) or LEGACY_TITLE + plan.get('_id', '')


def _matches(native, timing):
    """Whether the native record still runs at this pace (the owner may have edited it in the task page)."""
    key, value = next(iter(timing.items()))
    if key == 'every_seconds':
        return native.get('kind') == 'every' and native.get('everySeconds') == value
    return True


class ScheduleService:
    def __init__(self, app, controller, *, lane=None):
        self.app, self.controller, self.store = app, controller, app.store
        self.deliver_lock = threading.RLock()
        self.rhythm_lock = threading.RLock()
        self.server = self.thread = None
        self.lane = lane
        if lane is None:
            raise ValueError('NATIVE_HOST_SCHEDULE_REQUIRED')
        self._migrate_native_links()
        self.reconcile()
        self.ensure_self_development()
        for ensure in (self.ensure_presence, self.ensure_settlement):
            try:
                ensure()
            except Exception as exc:          # a refused heartbeat/settlement plan never blocks the host
                self.store.audit('rhythm-plans', 'rhythm.plan_refused', {'plan': ensure.__name__, 'error': str(exc)[:300]})

    def close(self):
        if self.lane:
            self.lane.close()

    def _native_events(self):
        events = self.lane.schedule('/schedule/events')
        if not isinstance(events, list):
            raise ValueError('INVALID_NATIVE_SCHEDULE_LOG')
        return events

    def _migrate_native_links(self):
        """One explicit cutover; retain old IDs and never replay old deliveries."""
        events = self._native_events()
        creates, _, _ = self._grouped(events)
        for plan in self.store.db.plans.find({'status': {'$in': ['ACTIVE', 'CREATING']}}):
            if plan.get('native_scheduler_session') == self.lane.scheduler_session:
                continue
            native = creates.get(plan.get('schedule_id'))
            if not native:
                live = [row for row in creates.values() if row.get('prompt') == 'ASUNA_PLAN:' + plan['_id']]
                native = live[-1] if live else None
            if not native:
                rule = plan['rule']
                scene = self.store.authorize(plan['scene_id'], plan['person_id'])
                moment = datetime.now(timezone.utc)
                if 'every_seconds' in rule:
                    timing = {'every_seconds': rule['every_seconds']}
                elif 'clock' in rule:
                    timing = schedule_rules.native_payload(rule,
                        schedule_rules.next_fire(rule, self.zone_of(scene, plan)['tz'], moment), moment)
                else:
                    due = datetime.fromisoformat(plan['scheduled_at'].replace('Z', '+00:00'))
                    if due <= moment:
                        self.store.put('plans', {**plan, 'status': 'SUSPENDED',
                            'migration_note': 'Legacy one-shot is overdue; no delivery replay. Replan explicitly.'},
                            expected=plan['revision'], stream=plan['_id'])
                        continue
                    timing = {'after_seconds': max(1, int((due - moment).total_seconds()))}
                native = self._create_native(plan['_id'], timing)
            legacy = {k: plan[k] for k in ('schedule_id', 'scheduled_at', 'last_dispatch_seq',
                                           'native_scheduler_session') if k in plan}
            self.store.put('plans', {**plan, 'legacy_schedule_binding': legacy,
                'schedule_id': native['id'], 'native_scheduler_session': self.lane.scheduler_session, 'scheduled_at': native['scheduledAt'],
                'native_scheduler_session': self.lane.scheduler_session, 'last_dispatch_seq': -1,
                'migration_note': 'Native Host owns future occurrences; legacy history remains read-only.'},
                expected=plan['revision'], stream=plan['_id'])
            self.store.audit(plan['_id'], 'schedule.native_migrated', {
                'previous': legacy, 'native_schedule_id': native['id'],
                'native_session_id': self.lane.scheduler_session, 'replayed_deliveries': 0}, plan['scope_key'])

    def _grouped(self, events):
        """原生事件日志分三份：建过哪些、派发过哪些、删过哪些——认领与版本护栏只看这三样。"""
        creates = {e['data']['schedule']['id']: e['data']['schedule'] for e in events
                   if e['data'].get('operation') == 'create'}
        for e in events:
            # An in-place update keeps the id; it is neither a delete nor a second create.
            if e['data'].get('operation') == 'update' and e['data'].get('schedule', {}).get('id') in creates:
                creates[e['data']['schedule']['id']] = e['data']['schedule']
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

    def _create_native(self, plan_id, timing):
        plan = self.store.db.plans.find_one({'_id': plan_id}) or {'_id': plan_id}
        return self.lane.schedule('/schedule/create', {'plan_id': plan_id, 'title': plan_title(plan), **timing})

    def zone_of(self, scene, plan=None):
        """这个场景/这条计划用哪个钟面。计划上已落库的时区优先：改配置不追改旧安排。"""
        return schedule_rules.scene_timezone(self.app.config, scene or {}, plan)

    def ensure_self_development(self):
        """Register one native recurring opportunity, with no second host clock."""
        settings = self.app.config.get('self_development', {})
        if not settings.get('enabled'):
            return
        # ADR-009 §10.3: policy > existing local every_seconds (until P7) > persona model > 1440 min.
        from .persona_model import self_development_minutes
        from .render import model_and_policy
        minutes, _ = self_development_minutes(*model_and_policy(self.store, self.controller.settings['persona']), self.app.config)
        interval = int(minutes) * 60
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
        native = (self._created(plan_id,events) if not plan.get('schedule_id') else None) or self._create_native(
            plan_id, {'every_seconds': plan['rule']['every_seconds']})
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SELF_DEVELOPMENT_CREATE_INCOMPLETE')
        current = self.store.db.plans.find_one({'_id': plan_id})
        self.store.put('plans', {**current, 'schedule_id': native['id'], 'native_scheduler_session': self.lane.scheduler_session,
            'scheduled_at': native['scheduledAt'], 'status': 'ACTIVE'},
            expected=current['revision'], stream=plan_id)

    # ── ADR-009 §10: heartbeat (presence) and nightly settlement ─────
    def _persona(self):
        from .render import model_and_policy
        persona = self.controller.settings['persona']
        return persona, *model_and_policy(self.store, persona)

    def _owner_private_target(self, scene_id, label):
        from . import visibility
        scene = self.store.db.scenes.find_one({'_id': scene_id})
        if not scene:
            raise Denied(label + '_TARGET_UNKNOWN')
        person = self.app.config['chat']['person_id'] if scene_id == self.app.config['chat']['scene_id'] else scene['members'][0]
        if visibility.session_class(self.app.config, self.store.db, scene, person) != visibility.OWNER_PRIVATE:
            raise Denied(label + '_TARGET_NOT_OWNER_PRIVATE')
        return scene, person

    def _rhythm_plan(self, plan_id, kind, scene, person, rule, timing, extra=None):
        """Create the plan and its native rule, or retime it in place with schedule_update."""
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if plan and (plan['scene_id'] != scene['_id'] or plan.get('kind') != kind):
            self.cancel(plan_id, plan['scene_id'], plan['person_id'], plan['policy_epoch'])
            plan = None
        if plan and plan['status'] == 'CANCELLED':
            self.store.put('plans', {**plan, 'status': 'CREATING', 'schedule_id': None, 'rule': rule, **(extra or {})},
                           expected=plan['revision'], stream=plan_id)
            plan = self.store.db.plans.find_one({'_id': plan_id})
        if not plan:
            plan = self.store.put('plans', {'_id': plan_id, 'kind': kind, 'scene_id': scene['_id'], 'person_id': person,
                'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch'], 'status': 'CREATING',
                'intent': {'presence': '在场机会（心跳）', 'settlement': '夜间沉淀'}[kind], 'rule': rule,
                'plan_version': 1, 'created_at': now(), **(extra or {})}, stream=plan_id)
        creates, _, deleted = self._grouped(self._native_events())
        live = plan.get('schedule_id') in creates and plan['schedule_id'] not in deleted
        native = creates.get(plan.get('schedule_id')) or {}
        title = RHYTHM_TITLES[kind]
        if live and plan['rule'] == rule and _matches(native, timing):
            if native.get('title') != title:
                named = self.lane.schedule('/schedule/update', {'id': plan['schedule_id'], 'title': title})
                if isinstance(named, dict) and named.get('id') == plan['schedule_id'] and named.get('scheduledAt'):
                    native = named
                else:                         # a refused rename is said, not taken for done
                    self.store.audit(plan_id, 'rhythm.rename_refused', {'result': named}, plan['scope_key'])
            if native.get('scheduledAt') and native['scheduledAt'] != plan.get('next_fire_at'):
                current = self.store.db.plans.find_one({'_id': plan_id})
                plan = self.store.put('plans', {**current, 'next_fire_at': native['scheduledAt']},
                                      expected=current['revision'], stream=plan_id)
            return plan
        if live:
            key = next(iter(timing))
            native = self.lane.schedule('/schedule/update', {'id': plan['schedule_id'], 'title': title,
                                                             'change': {'kind': NATIVE_KIND.get(key, key), **timing}})
            if not isinstance(native, dict) or native.get('id') != plan['schedule_id']:
                raise ValueError('NATIVE_SCHEDULE_UPDATE_FAILED')
            # Her pace changed, or the record drifted from it (edited in the task page): her pace holds.
            self.store.audit(plan_id, 'rhythm.retimed', {'from': plan['rule'], 'to': rule,
                                                         'drift': plan['rule'] == rule}, plan['scope_key'])
        else:
            native = self._create_native(plan_id, timing)
            if not isinstance(native, dict) or not native.get('id'):
                raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        current = self.store.db.plans.find_one({'_id': plan_id})
        return self.store.put('plans', {**current, 'rule': rule, 'schedule_id': native['id'], 'status': 'ACTIVE',
            'native_scheduler_session': self.lane.scheduler_session, 'scheduled_at': native.get('scheduledAt'),
            'next_fire_at': native.get('scheduledAt'), 'native_recurring': True, **(extra or {})},
            expected=current['revision'], stream=plan_id)

    def _retire(self, plan_id, reason):
        plan = self.store.db.plans.find_one({'_id': plan_id})
        if plan and plan['status'] not in ('CANCELLED',):
            self.cancel(plan_id, plan['scene_id'], plan['person_id'], plan['policy_epoch'])
            self.store.audit(plan_id, 'rhythm.disabled', {'reason': reason}, plan['scope_key'])

    def ensure_presence(self):
        """Heartbeat needs the persona model (heartbeat.enabled) and the owner's local target scene."""
        from .persona_data import persona_runtime
        from .persona_model import HEARTBEAT_EVERY_MIN, effective
        persona, model, policy = self._persona()
        target = persona_runtime(self.app.config, persona).get('heartbeat_target')
        if not (effective(model, 'heartbeat.enabled', policy) and target):
            self._retire('plan-asuna-presence', 'heartbeat disabled or no heartbeat_target')
            return None
        scene, person = self._owner_private_target(target, 'PRESENCE')
        low, high = HEARTBEAT_EVERY_MIN
        every = min(high, max(low, int(effective(model, 'heartbeat.every_min', policy) or 60))) * 60
        with self.rhythm_lock:
            return self._rhythm_plan(PRESENCE_PLAN, 'presence', scene, person, {'every_seconds': every},
                                     {'every_seconds': every})

    def pause_presence(self, minutes):
        """Her heartbeat.pause_min: beats keep ticking but skip until then, and resume by themselves."""
        plan = self.store.db.plans.find_one({'_id': PRESENCE_PLAN})
        if not plan or plan['status'] != 'ACTIVE':
            return None
        until = schedule_rules.minutes_later(minutes, now()) if minutes else None
        self.store.put('plans', {**plan, 'paused_until': until}, expected=plan['revision'], stream=plan['_id'])
        self.store.audit(plan['_id'], 'rhythm.paused' if until else 'rhythm.resumed', {'until': until}, plan['scope_key'])
        return until

    def watch_rhythm(self, deep=False):
        """Watchdog (ADR-012 §4.3): a heartbeat that went quiet for two beats is rebuilt, and she is told.
        Called after every turn and at every other rhythm dispatch (a database read), and with deep=True from
        the host's existing watch thread, which also recreates a deleted native record, restores her pace on
        one edited elsewhere and keeps the shown next run current. It never raises into its caller."""
        try:
            with self.rhythm_lock:
                if deep:
                    self.ensure_presence()
                return self._watch_presence()
        except Exception as exc:
            self.store.audit('rhythm-plans', 'rhythm.watch_failed', {'error': str(exc)[:300]})
            return None

    def _watch_presence(self):
        plan = self.store.db.plans.find_one({'_id': PRESENCE_PLAN})
        if not plan or plan.get('status') != 'ACTIVE' or not plan.get('schedule_id'):
            return None
        every = int((plan.get('rule') or {}).get('every_seconds') or 0)
        since = plan.get('last_occurrence_at') or plan.get('scheduled_at')
        if not every or not since:
            return None
        moment = schedule_rules._aware(now())
        limit = 2 * every + HEARTBEAT_GRACE_SECONDS
        if (moment - schedule_rules._aware(since)).total_seconds() <= limit:
            return None
        if plan.get('missed_at') and (moment - schedule_rules._aware(plan['missed_at'])).total_seconds() <= limit:
            return None                       # already rebuilt for this silence; try again after another two beats
        self.store.audit(plan['_id'], 'rhythm.heartbeat_missed', {'since': since, 'every_seconds': every,
            'native_schedule_id': plan['schedule_id']}, plan['scope_key'])
        try:                                  # the record may look alive and still not fire: replace it
            self.lane.schedule('/schedule/delete', {'id': plan['schedule_id']})
        except Exception:
            pass
        rebuilt = self.ensure_presence()
        current = self.store.db.plans.find_one({'_id': PRESENCE_PLAN})
        self.store.put('plans', {**current, 'missed_at': now(), 'reconnected_at': now()},
                       expected=current['revision'], stream=PRESENCE_PLAN)
        self.store.audit(PRESENCE_PLAN, 'rhythm.heartbeat_rebuilt',
                         {'native_schedule_id': (rebuilt or {}).get('schedule_id')}, plan['scope_key'])
        return 'REBUILT'

    def ensure_settlement(self):
        """Nightly settlement: native daily at rhythm.settle_at in an explicit IANA zone; once per local date."""
        from .persona_data import persona_runtime
        from .persona_model import effective, timezone as persona_timezone
        persona, model, policy = self._persona()
        settle_at = effective(model, 'rhythm.settle_at', policy)
        zone, source = persona_timezone(model, policy, self.app.config)
        if not settle_at or source == 'unset' or not schedule_rules.is_iana(zone):
            self._retire('plan-asuna-settlement', 'no settle_at or no IANA time zone')
            return None
        target = persona_runtime(self.app.config, persona).get('internal_scene') or self.app.config['chat']['scene_id']
        scene, person = self._owner_private_target(target, 'SETTLEMENT')
        rule = {'clock': {'time': settle_at}, 'settlement_zone': zone}
        return self._rhythm_plan('plan-asuna-settlement', 'settlement', scene, person, rule,
                                 {'daily': {'time': settle_at + ':00', 'time_zone': zone}}, {'timezone': zone})

    def next_beat(self):
        """When DSH will next deliver her heartbeat (its own record), or None."""
        plan = self.store.db.plans.find_one({'_id': PRESENCE_PLAN})
        if not plan or plan.get('status') != 'ACTIVE':
            return None
        creates, _, deleted = self._grouped(self._native_events())
        return None if plan.get('schedule_id') in deleted else (creates.get(plan.get('schedule_id')) or {}).get('scheduledAt')

    def beat_now(self):
        """The owner's /heartbeat (ADR-012 §8): one beat now through the same path, without the gates."""
        plan = self.store.db.plans.find_one({'_id': PRESENCE_PLAN})
        if not plan or plan.get('status') != 'ACTIVE':
            return {'state': 'OFF'}
        occurrence = 'owner-' + schedule_rules._aware(now()).strftime('%Y%m%dT%H%M%S%f')
        with self.deliver_lock:
            outcome = self._presence(plan, occurrence, forced=True)
        return {'state': outcome, 'next_at': self.next_beat()}

    def visit(self, ep, place, intent, topic, artifact_id):
        """Her visit (ADR-012 §4.2): checked against the same rules her places view shows, then a public turn
        in that group. Only the category, her short topic and an optional picture of her own cross over."""
        from . import outbound_media, places
        from .persona_model import effective
        persona, model, policy = self._persona()
        if not effective(model, 'heartbeat.visits', policy):
            raise ValueError('VISIT_OFF')
        found = places.find(self.app.config, place)
        scene = found and self.store.db.scenes.find_one({'_id': found[0]})
        if not scene:
            raise ValueError('VISIT_PLACE_UNKNOWN: ' + place)
        _, route, channel = found
        if not scene.get('channel_id'):
            raise ValueError('VISIT_PLACE_UNKNOWN: ' + place)
        moment = schedule_rules._aware(now())
        date = places.local_date(self.app.config, model, policy, moment)
        plan = self.store.db.plans.find_one({'_id': PRESENCE_PLAN}) or {}
        can, why = places.eligibility(self.store, scene, plan, places.settings(model, policy), moment, date,
                                      intent=intent)
        if not can:
            raise ValueError('VISIT_NOT_NOW: ' + why)
        if artifact_id and artifact_id not in {item['artifact_id'] for item in outbound_media.produced_images(self.store, limit=50)}:
            raise ValueError('VISIT_PICTURE_NOT_HERS')
        person = places.visitor(route, channel)
        if not person:
            raise ValueError('VISIT_NOT_NOW: 这个群里没有可以接待你的成员授权')
        event_id = 'visit:%s:%s' % (scene['_id'], ep['source_event_id'])
        # Her own moment in the group, not a platform input: no channel envelope (that would be shown in the
        # group's session as a member's message). It wakes as a scene tick; publishing targets the group's route.
        self.controller.offer_internal('visit', event_id, scene['_id'], person, places.visit_text(intent, topic),
            scene_tick=True,
            group_context={'wake_reason': places.WAKE_REASON, 'topic_id': event_id, 'reply_to': None,
                           'reply_message_id': None, 'mentioned_account_ids': []},
            visit={'intent': intent, 'topic': topic, 'artifact_id': artifact_id, 'from': ep['_id']})
        if plan:
            current = self.store.db.plans.find_one({'_id': PRESENCE_PLAN})
            self.store.put('plans', {**current, **places.record(current, scene['_id'], event_id, intent, moment, date)},
                           expected=current['revision'], stream=PRESENCE_PLAN)
        self.store.audit(PRESENCE_PLAN, 'visit.offered', {'scene_id': scene['_id'], 'event_id': event_id,
                                                          'intent': intent, 'from': ep['_id']}, scene['scope_key'])
        from .people import People
        return {'going_to': People(self.store, persona).scene_title(scene), 'for': places.INTENTS[intent],
                'note': '程序会在那个群里给你开一个回合；你在那儿看了现场再决定说不说、说什么。结果下次心跳带回来。'}

    def errand(self, ep, place, request, exactly):
        """An errand the owner gave her at home (ADR-017): a turn in that chat sees only that chat and the owner's
        words. No visit limits (the owner asked), a daily cap; what comes home is the program's status only."""
        from . import places
        found = places.find_errand(self.app.config, place)
        scene = found and self.store.db.scenes.find_one({'_id': found[0]})
        if not scene or not scene.get('channel_id'):
            raise ValueError('ERRAND_PLACE_UNKNOWN: ' + place)
        _, route, channel = found
        if places.errands_lately(self.store, datetime.now(timezone.utc)) >= places.ERRANDS_PER_DAY:
            raise ValueError('ERRAND_LIMIT: %d a day' % places.ERRANDS_PER_DAY)
        person = places.visitor(route, channel)
        if not person:
            raise ValueError('ERRAND_PLACE_UNKNOWN: 那边没有可以接待你的成员授权')
        event_id = 'visit:errand:%s:%s' % (scene['_id'], ep['source_event_id'])
        topic = 'errand:' + event_id
        self.controller.offer_internal('visit', event_id, scene['_id'], person, places.errand_text(exactly),
            scene_tick=True,
            group_context={'wake_reason': places.WAKE_REASON, 'topic_id': topic, 'reply_to': None,
                           'reply_message_id': None, 'mentioned_account_ids': []},
            visit={'intent': 'errand', 'topic': None, 'artifact_id': None, 'request': request,
                   'exactly': bool(exactly), 'from': ep['_id']})
        self.store.audit(ep['_id'], 'errand.offered', {'scene_id': scene['_id'], 'event_id': event_id,
                                                       'exactly': bool(exactly), 'chars': len(request)},
                         scene['scope_key'])
        from .people import People
        persona, _, _ = self._persona()
        return {'going_to': People(self.store, persona).scene_title(scene),
                'note': '程序会在那边开一轮，那一轮只看得到那边和主人的原话；办没办成，下次在家会看到。'}

    def _last_home_beat(self, plan):
        """Her last internal turn at home: a heartbeat, or a settlement or self-improvement turn."""
        times = [plan.get('last_presence_at')]
        times += [row.get('last_occurrence_at') for row in self.store.db.plans.find(
            {'kind': {'$in': ['settlement', 'self_development']}, 'scene_id': plan['scene_id'], 'last_outcome': 'ENQUEUED'},
            {'last_occurrence_at': 1})]
        times = [moment for moment in times if moment]
        return max(times, key=schedule_rules._aware) if times else None

    def _news_since(self, home, since):
        """Something for her since then: anyone who reached her (home, a DM, or a group that woke her),
        or one of her tasks that finished. Group talk that did not wake her is not news; P5 has that."""
        scenes = {home}
        for channel in self.app.config.get('channels', {}).values():
            scenes.update(route['scene_id'] for route in channel.get('routes', {}).values())
        reached = self.store.db.messages.find_one({'scene_id': {'$in': sorted(scenes)}, 'direction': 'inbound',
            'received_at': {'$gt': since}, 'processing_outcome': {'$ne': 'RECORDED_NO_WAKE'}}, {'_id': 1})
        return bool(reached or self.store.db.tasks.find_one({'finished_at': {'$gt': since}}, {'_id': 1}))

    def _presence(self, plan, occurrence, forced=False):
        """Deterministic pre-gates; a skip calls no model and leaves one counting audit. forced (the owner's
        /heartbeat) skips the gates; the beat still counts toward the day."""
        from .config import ago
        from .persona_model import effective, timezone as persona_timezone
        from .rhythm import HEARTBEAT_EARLY, HEARTBEAT_RECONNECTED, HEARTBEAT_TEXT, heartbeat_rest_gate
        persona, model, policy = self._persona()
        moment = schedule_rules._aware(now())
        zone, _ = persona_timezone(model, policy, self.app.config)
        today = schedule_rules.local_moment(zone if schedule_rules.is_iana(zone) else 'UTC', moment).date().isoformat()
        beats = plan['beats'] if (plan.get('beats') or {}).get('date') == today else {'date': today, 'count': 0}
        reason = None
        with self.controller.pending.mutex:
            queued = bool(self.controller.pending.queue.queues.get(plan['scene_id']))
        # A role turn running or waiting at home makes her busy; the action brain working on a task does not.
        if queued or self.controller.active is not None:
            reason = 'BUSY'
        if not reason and plan.get('paused_until') and schedule_rules._aware(plan['paused_until']) > moment:
            reason = 'PAUSED'
        last = self._last_home_beat(plan)
        if not reason and last:
            gap = (moment - schedule_rules._aware(last)).total_seconds() / 60
            if gap < float(effective(model, 'heartbeat.min_gap_min', policy) or 0) \
                    and not self._news_since(plan['scene_id'], last):
                reason = 'MIN_GAP'
        if not reason and heartbeat_rest_gate(model, policy, self.app.config):
            reason = 'REST_WINDOW'
        if not reason and beats['count'] >= HEARTBEAT_BEATS_PER_DAY:
            reason = 'DAILY_BUDGET'
        if forced:
            self.store.audit(plan['_id'], 'presence.forced', {'occurrence': occurrence, 'gate': reason}, plan['scope_key'])
            reason = None
        if reason:
            self.store.audit(plan['_id'], 'presence.skipped', {'reason': reason, 'occurrence': occurrence}, plan['scope_key'])
            return 'SKIPPED:' + reason
        text = HEARTBEAT_TEXT + (HEARTBEAT_EARLY if forced else '')
        reconnected = plan.get('reconnected_at')
        if reconnected and reconnected != plan.get('reconnect_told_at'):
            hours = max(0.0, (moment - schedule_rules._aware(reconnected)).total_seconds() / 3600)
            text += HEARTBEAT_RECONNECTED % ago(hours)
        self.controller.offer_internal('presence', 'presence:' + occurrence, plan['scene_id'], plan['person_id'], text)
        current = self.store.db.plans.find_one({'_id': plan['_id']})
        self.store.put('plans', {**current, 'last_presence_at': now(), 'beats': {**beats, 'count': beats['count'] + 1},
                                 **({'reconnect_told_at': reconnected} if reconnected else {})},
                       expected=current['revision'], stream=plan['_id'])
        return 'ENQUEUED'

    def _settlement(self, plan, occurrence):
        local_date = schedule_rules.local_moment(plan['rule']['settlement_zone'], now()).date().isoformat()
        if plan.get('last_settled_date') == local_date:
            self.store.audit(plan['_id'], 'settlement.skipped', {'reason': 'ALREADY_SETTLED', 'date': local_date}, plan['scope_key'])
            return 'SKIPPED:ALREADY_SETTLED'
        self.controller.offer_internal('settlement', 'settlement:' + local_date, plan['scene_id'], plan['person_id'],
            '这是今天的夜间沉淀机会，不是用户消息。看看挂着的情绪、待决的提案、活账和晋升候选，'
            '决定哪些了结（close）、哪些作废（void，要写理由）、哪些值得晋升成长期记忆（promote），也可以什么都不做。')
        current = self.store.db.plans.find_one({'_id': plan['_id']})
        self.store.put('plans', {**current, 'last_settled_date': local_date}, expected=current['revision'], stream=plan['_id'])
        return 'ENQUEUED'

    def create(self, ep, spec, plan_id=None):
        intent = spec.get('intent') if isinstance(spec, dict) else None
        if not isinstance(intent, str) or not 1 <= len(intent.strip()) <= 1000:
            raise ValueError('INVALID_SCHEDULE_SPEC')
        rule = schedule_rules.normalize_rule(spec)          # 形状/间隔/钟点先判完，不碰库
        scene = self.store.authorize(ep['scene_id'], ep['person_id'])
        if scene['policy_epoch'] != ep['policy_epoch']:
            raise Denied('SCHEDULE_SOURCE_STALE')
        zone = self.zone_of(scene)
        fire_at = schedule_rules.next_fire(rule, zone['tz'], now())   # 已过/本地不存在都明确抛回
        # One turn may make several plans: each of her plan calls names its own (role_tools).
        plan_id = plan_id or 'plan-' + ep['_id'][3:]
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
        recurring = schedule_rules.native_recurring(rule, zone['name'])
        native = existing or self._create_native(plan_id,
            recurring or schedule_rules.native_payload(rule, fire_at, now()))
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        current = self.store.db.plans.find_one({'_id': plan_id})
        return self.store.put('plans', {**current, 'schedule_id': native['id'], 'native_scheduler_session': self.lane.scheduler_session,
            'scheduled_at': native['scheduledAt'], 'native_recurring': native.get('kind') in ('daily', 'weekly'),
            'status': current['status'] if current['status'] in ('FIRED','CANCELLED') else 'ACTIVE'},
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
            {key: value for key, value in spec.items() if key not in ('plan_id', 'intent')}
        # Only new wording: the plan keeps its timing (her plan tool, op=update with an intent alone).
        rule = schedule_rules.normalize_rule(timing) if timing else plan['rule']
        intent = (spec.get('intent') or plan['intent']).strip()
        if not 1 <= len(intent) <= 1000:
            raise ValueError('INVALID_SCHEDULE_SPEC')
        fire_at = schedule_rules.next_fire(rule, zone['tz'], now())
        current = self.store.db.plans.find_one({'_id': plan_id})
        if current['rule'] == rule and current['intent'] == intent:
            return current                                  # 什么都没变就别动原生记录
        recurring = schedule_rules.native_recurring(rule, zone['name'])
        change = recurring and {'kind': next(iter(recurring)), **recurring} or (
            {'kind': 'every', 'every_seconds': rule['every_seconds']} if 'every_seconds' in rule else None)
        native = None
        if change and current.get('schedule_id') and (current.get('native_recurring') or 'every_seconds' in current['rule']):
            # ADR-009 D-5: change a native recurring rule in place (schedule_update), no delete + create.
            updated_native = self.lane.schedule('/schedule/update', {'id': current['schedule_id'], 'change': change})
            if isinstance(updated_native, dict) and updated_native.get('id') == current['schedule_id']:
                native = updated_native
        native = native or self._create_native(plan_id,
            recurring or schedule_rules.native_payload(rule, fire_at, now()))
        if not isinstance(native, dict) or not native.get('id'):
            raise ValueError('NATIVE_SCHEDULE_CREATE_INCOMPLETE')
        stale, note = current.get('schedule_id'), None
        if stale and stale != native['id']:
            try:
                self.lane.schedule('/schedule/delete', {'id': stale})
            except BaseException as exc:                     # 旧的那条没删掉也不会重复行动
                note = 'STALE_NATIVE_DELETE_FAILED: ' + str(exc)
        updated = self.store.put('plans', {**current, 'rule': rule, 'intent': intent,
            'schedule_id': native['id'], 'native_scheduler_session': self.lane.scheduler_session, 'scheduled_at': native['scheduledAt'],
            'next_fire_at': fire_at.isoformat(timespec='seconds'), 'timezone': zone['name'],
            'native_recurring': native.get('kind') in ('daily', 'weekly'),
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
        native = live[-1] if live else self._create_native(plan_id,
            schedule_rules.native_payload(plan['rule'], fire_at, now()))
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
                self.store.put('plans', {**current, 'schedule_id': native['id'], 'native_scheduler_session': self.lane.scheduler_session,
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
            if (native.get('title') or '').startswith(LEGACY_TITLE) and native['id'] == plan.get('schedule_id') \
                    and native['id'] not in deleted and plan['status'] == 'ACTIVE':
                try:                          # the task page names it by what it is (ADR-012 §8)
                    named = self.lane.schedule('/schedule/update', {'id': native['id'], 'title': plan_title(plan)})
                    if not (isinstance(named, dict) and named.get('id') == native['id'] and named.get('scheduledAt')):
                        self.store.audit(plan_id, 'schedule.rename_refused', {'result': named}, plan['scope_key'])
                except Exception as exc:
                    self.store.audit(plan_id, 'schedule.rename_refused', {'error': str(exc)[:300]}, plan['scope_key'])
            if not plan.get('schedule_id'):
                self.store.put('plans', {**plan, 'schedule_id': native['id'], 'native_scheduler_session': self.lane.scheduler_session,
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
                    self.store.put('plans', {**plan, 'schedule_id': newest['id'], 'native_scheduler_session': self.lane.scheduler_session,
                        'scheduled_at': newest['scheduledAt']}, expected=plan['revision'], stream=plan_id)
                elif schedule_rules.rearms_after_fire(plan['rule']) and not plan.get('native_recurring'):
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
        self._deliver(payload['seq'], payload['id'], self._grouped(events)[0])

    def _deliver(self, seq, schedule_id, creates):
        # Startup reconciliation and a live native callback can see the same
        # durable dispatch. Serialize only the short host state transition;
        # never hold this lock across DSH, model, or tool execution.
        with self.deliver_lock:
            action = self._deliver_locked(seq, schedule_id, creates)
        if action and action.get('kind') in ('settlement', 'self_development'):
            self.watch_rhythm()               # her other rhythms look after the heartbeat too
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
            elif plan.get('kind') == 'presence':
                outcome = self._presence(plan, occurrence)
            elif plan.get('kind') == 'settlement':
                outcome = self._settlement(plan, occurrence)
            else:
                # A due plan is a core notice, not a platform input: it carries no channel envelope (that would
                # be re-checked as a member's message and shown as one in the conversation). It wakes as a
                # scene tick; what she says goes out on the conversation's own route (publish.py).
                if scene.get('channel_id'):
                    route = route_for_scene(self.app.config, scene['channel_id'], scene['_id'])
                    if plan['person_id'] not in {m['person_id'] for m in route_members(route).values()}:
                        raise Denied('SCHEDULE_ROUTE_REVOKED')
                event = {'event_id': 'schedule:' + occurrence, 'scene_id': plan['scene_id'],
                         'person_id': plan['person_id'], 'adapter_id': 'scheduler',
                         'episode_kind': 'scheduled', 'scheduled_plan_id': plan_id,
                         'scene_tick': True,
                         'text': '你之前安排的计划「' + plan['intent'] + '」现在到期了。请重新判断是否继续；到期本身不是新授权或已完成的行动。'}
                if scene.get('channel_id') and scene['kind'] == 'group':
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
        repeating = schedule_rules.rearms_after_fire(current['rule']) and not current.get('native_recurring')
        status = current['status']
        if status != 'CANCELLED':
            status = 'ACTIVE' if repeating else ('FIRED' if native['kind'] in ('after', 'at') else status)
        next_fire_at = None if status == 'FIRED' else current.get('next_fire_at')
        extra = {}
        if current.get('native_recurring') and status == 'ACTIVE':
            # The native rule repeats by itself; only the displayed next occurrence moves on.
            zone = self.zone_of(self.store.db.scenes.find_one({'_id': current['scene_id']}), current)
            moment = max(schedule_rules._aware(now()), schedule_rules._aware(native.get('scheduledAt') or now()))
            # DSH's own next target when it has already moved on; otherwise computed from the rule.
            next_fire_at = native['scheduledAt'] if native.get('scheduledAt') and \
                schedule_rules._aware(native['scheduledAt']) > schedule_rules._aware(now()) else \
                schedule_rules.next_fire(current['rule'], zone['tz'], moment).isoformat(timespec='seconds')
            extra = {'fire_count': current.get('fire_count', 0) + 1}
        self.store.put('plans', {**current, 'last_occurrence_id': occurrence,
            'last_dispatch_seq': seq, 'last_occurrence_at': now(), 'last_outcome': outcome,
            'next_fire_at': next_fire_at, 'status': status, **extra}, expected=current['revision'], stream=plan_id)
        self.store.audit(plan_id, 'schedule.dispatched', {'occurrence': occurrence,
            'native_schedule_id': schedule_id, 'outcome': outcome, 'rearm': repeating}, plan['scope_key'])
        return {'plan_id': plan_id, 'kind': plan.get('kind'), 'rearm': repeating and status == 'ACTIVE',
            'fired_at': native.get('scheduledAt')}
