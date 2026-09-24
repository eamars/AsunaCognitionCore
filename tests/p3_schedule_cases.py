"""ADR-005 P3 离线用例：假集合＋假原生 lane 真算，不需要 Mongo、不需要 pytest、不碰网络。

跑法：python3 tests/p3_schedule_cases.py     （或 python3 tools/p3_offline_check.py）

被测的是**真文件**：把 src/asuna/schedule.py 与 schedule_rules.py 复制进一个临时包，
外面垫四个小替身（state/channels/integration/dsh_lane），于是 ScheduleService 的真 create /
update / cancel / deliver / reconcile / _rearm 全部真跑一遍，只是底下没有 Mongo 也没有 DSH。
时、日期、原生事件日志都是真算的：DST 用 Pacific/Auckland 的真规则，不拿 86400 秒冒充每日。
真 Mongo 那一层（真 CAS、真集合）由操作员跑 tests/test_p3_schedule.py。
"""
import os
import shutil
import sys
import tempfile
import threading
import types
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get('ASUNA_P3_SRC') or os.path.join(ROOT, 'src', 'asuna')
                                                # 反证时把被测面指向改动前的副本

T0 = datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)      # 2026-09-24 17:00 Auckland（周四）
DST_START = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)   # 当地 09-27 02:00→03:00
DST_END = datetime(2026, 4, 4, 14, 0, tzinfo=timezone.utc)      # 当地 04-05 03:00→02:00

STUB_STATE = '''from datetime import datetime, timezone
class Conflict(RuntimeError):
    pass
class Denied(PermissionError):
    pass
class Store:
    pass
CLOCK = [datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc)]
def now():
    return CLOCK[0].isoformat()
'''

STUB_CHANNELS = '''class Denied(PermissionError):
    pass
def route_for_scene(config, channel_id, scene_id):
    channel = config.get('channels', {}).get(channel_id) or {}
    for route in channel.get('routes', {}).values():
        if route.get('scene_id') == scene_id:
            return route
    raise Denied('CHANNEL_ROUTE_NOT_AUTHORIZED')
def route_members(route):
    if route['target']['type'] == 'dm':
        return {route['sender_id']: route}
    return route.get('members', {})
'''

STUB_INTEGRATION = 'def event_granted(config, event):\n    return False\n'
STUB_LANE = 'class DshLane:\n    pass\n'


_PACKAGES = {}


def load_package():
    """把两份真文件装进一个临时包，外面垫替身；返回 (schedule, schedule_rules, state)。

    整个进程只装一次：用例之间靠新建假集合/假 lane 隔离，假时钟由 setup() 重置。
    """
    if 'p3pkg' in _PACKAGES:
        return _PACKAGES['p3pkg']
    root = tempfile.mkdtemp(prefix='p3pkg-')
    package = os.path.join(root, 'p3pkg')
    os.makedirs(package)
    open(os.path.join(package, '__init__.py'), 'w').close()
    for name in ('schedule.py', 'schedule_rules.py'):
        src = os.path.join(SRC, name)
        if not os.path.exists(src):            # 反证用：对着改动前的副本跑，那时还没有换算模块
            continue
        shutil.copyfile(src, os.path.join(package, name))
    for name, body in (('state.py', STUB_STATE), ('channels.py', STUB_CHANNELS),
                       ('integration.py', STUB_INTEGRATION), ('dsh_lane.py', STUB_LANE)):
        open(os.path.join(package, name), 'w', encoding='utf-8').write(body)
    sys.path.insert(0, root)
    for name in ('p3pkg.schedule', 'p3pkg.schedule_rules', 'p3pkg.state'):
        sys.modules.pop(name, None)
    module = __import__('p3pkg.schedule', fromlist=['ScheduleService'])
    # 换算模块单独取：反证那一跑里，旧 schedule.py 根本不 import 它，用例仍要能拿到它。
    rules = sys.modules.get('p3pkg.schedule_rules') or \
        __import__('p3pkg.schedule_rules', fromlist=['scene_timezone'])
    loaded = (module, rules, sys.modules['p3pkg.state'])
    _PACKAGES['p3pkg'] = loaded
    return loaded


# ── 假集合：只实现这批用例真会用到的那一小块查询语言 ──────────────
def _match(row, spec):
    for key, want in (spec or {}).items():
        have = row.get(key)
        if isinstance(want, dict):
            if '$in' in want and have not in want['$in']:
                return False
            if '$ne' in want and have == want['$ne']:
                return False
        elif have != want:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction=-1):
        self.rows.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class Collection:
    def __init__(self):
        self.rows = {}

    def find_one(self, spec=None, projection=None):
        for row in self.rows.values():
            if _match(row, spec):
                return dict(row)
        return None

    def find(self, spec=None, projection=None):
        return Cursor([dict(row) for row in self.rows.values() if _match(row, spec)])


class Store:
    def __init__(self, config):
        self.config = config
        self.audits = []
        self.db = types.SimpleNamespace(plans=Collection(), scenes=Collection(),
                                        messages=Collection(), audit_events=Collection(),
                                        episodes=Collection(), tasks=Collection(),
                                        memory_units=Collection(), state_heads=Collection(),
                                        state_revisions=Collection())

    def put(self, collection, document, *, expected=None, stream='state'):
        coll = getattr(self.db, collection)
        doc = dict(document)
        doc['schema_version'] = 1
        current = coll.rows.get(doc['_id'])
        if expected is None:
            if current:
                raise sys.modules['p3pkg.state'].Conflict('DUPLICATE_ID')
            doc['revision'] = 1
        else:
            if not current or current['revision'] != expected:
                raise sys.modules['p3pkg.state'].Conflict('STALE_REVISION')
            doc['revision'] = expected + 1
        coll.rows[doc['_id']] = dict(doc)
        return dict(doc)

    def audit(self, stream, kind, payload, scope='operator'):
        self.audits.append({'stream': stream, 'type': kind, 'payload': payload})
        return {}

    def authorize(self, scene_id, person_id):
        scene = self.db.scenes.find_one({'_id': scene_id})
        if not scene or person_id not in scene['members']:
            raise sys.modules['p3pkg.state'].Denied('SCENE_MEMBERSHIP_DENIED')
        return scene

    def head(self, entity, scope):
        row = self.db.state_heads.find_one({'_id': entity + '|' + scope})
        if not row:
            return None
        return row, self.db.state_revisions.find_one({'_id': row['revision_id']})

    def kinds(self, stream=None):
        return [row['type'] for row in self.audits if stream is None or row['stream'] == stream]


class Lane:
    """原生定时替身：只认 /schedule/events|create|delete 三个口，事件日志按真顺序追加。"""
    scheduler_session = 's-fake'

    def __init__(self, fail=()):
        self.events = []
        self.calls = []
        self.fail = set(fail)
        self.created = 0
        self.seq = 0

    def _next_seq(self):
        self.seq += 1
        return self.seq

    def schedule(self, path, payload=None):
        self.calls.append((path, payload))
        if path in self.fail:
            raise RuntimeError('NATIVE_DOWN:' + path)
        if path == '/schedule/events':
            return [dict(event) for event in self.events]
        if path == '/schedule/create':
            self.created += 1
            rule = {key: value for key, value in payload.items() if key != 'plan_id'}
            at = sys.modules['p3pkg.state'].CLOCK[0]
            step = rule.get('after_seconds', rule.get('every_seconds'))
            native_id = 'native-%d' % self.created
            scheduled = (at + timedelta(seconds=step)).isoformat()
            self.events.append({'seq': self._next_seq(), 'data': {'operation': 'create',
                'schedule': dict({'id': native_id, 'prompt': 'ASUNA_PLAN:' + payload['plan_id'],
                                  'kind': 'every' if 'every_seconds' in rule else 'after',
                                  'scheduledAt': scheduled}, **rule)}})
            return {'id': native_id, 'scheduledAt': scheduled}
        if path == '/schedule/delete':
            self.events.append({'seq': self._next_seq(),
                                'data': {'operation': 'delete', 'id': payload['id']}})
            return {'deleted': True}
        raise AssertionError('UNEXPECTED_NATIVE_CALL:' + path)

    def fire(self, native_id):
        """原生派发一次：先落 dispatch 事件，再由调用方走 deliver()。"""
        event = {'seq': self._next_seq(), 'data': {'operation': 'dispatch', 'id': native_id}}
        self.events.append(event)
        return event

    def live(self, plan_id):
        dispatched = {e['data']['id'] for e in self.events if e['data'].get('operation') == 'dispatch'}
        deleted = {e['data']['id'] for e in self.events if e['data'].get('operation') == 'delete'}
        return [e['data']['schedule'] for e in self.events
                if e['data'].get('operation') == 'create'
                and e['data']['schedule']['prompt'] == 'ASUNA_PLAN:' + plan_id
                and e['data']['schedule']['id'] not in dispatched
                and e['data']['schedule']['id'] not in deleted]


# ── 场景夹具 ────────────────────────────────────────────────
SCENE_ID = 'qq:bot:group:905'
PERSON = 'qq:1'


def config_with(block=None, top=None):
    route = {'scene_id': SCENE_ID, 'target': {'type': 'group', 'id': '905'},
             'members': {PERSON: {'person_id': PERSON}}}
    if block is not None:
        route['schedule'] = block
    config = {'channels': {'napcat': {'account_id': 'bot', 'routes': {'g': route}}}}
    if top:
        config.update(top)
    return config


SCENE = {'_id': SCENE_ID, 'scene_id': SCENE_ID, 'kind': 'group', 'members': [PERSON],
         'scope_key': 'scene:' + SCENE_ID, 'policy_epoch': 7, 'channel_id': 'napcat',
         'channel_account_id': 'bot'}
EP = {'_id': 'ep-3001', 'scene_id': SCENE_ID, 'person_id': PERSON,
      'scope_key': 'scene:' + SCENE_ID, 'policy_epoch': 7}


class Controller:
    def __init__(self, fail=None):
        self.received = []
        self.fail = fail

    def receive(self, event):
        if self.fail:
            raise self.fail
        self.received.append(event)


class Evidence:
    def record(self, kind, payload):
        return {}


def setup(clock=T0, config=None, lane=None, controller=None):
    schedule, rules, state = load_package()
    store = Store(config or config_with({'timezone': 'Pacific/Auckland'}))
    store.db.scenes.rows.update({SCENE['_id']: dict(SCENE, revision=1)})
    state.CLOCK[0] = clock
    lane = lane or Lane()
    controller = controller or Controller()
    service = schedule.ScheduleService.__new__(schedule.ScheduleService)
    service.store, service.lane, service.controller = store, lane, controller
    service.deliver_lock = threading.RLock()
    service.app = types.SimpleNamespace(config=store.config, evidence=Evidence())
    return {'schedule': schedule, 'rules': rules, 'state': state, 'store': store, 'lane': lane,
            'controller': controller, 'service': service}


def fire(env, native_id):
    event = env['lane'].fire(native_id)
    env['service'].deliver({'session': 's-fake', 'seq': event['seq'], 'id': native_id})
    return event


def at(moment):
    return moment.isoformat()


CASES = []


def case(function):
    CASES.append(function)
    return function


# ── 纯换算：时区、DST、四种计时 ─────────────────────────────
@case
def after_and_interval(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    fire = rules.next_fire(rules.normalize_rule({'intent': 'x', 'after_seconds': 600}), zone['tz'], env['state'].CLOCK[0])
    payload = rules.native_payload({'after_seconds': 600}, fire, env['state'].CLOCK[0])
    return fire == env['state'].CLOCK[0] + timedelta(seconds=600) and payload == {'after_seconds': 600}, payload


@case
def interval_below_native_minimum(env):
    rules = env['rules']
    try:
        rules.normalize_rule({'intent': 'x', 'every_seconds': 120})
        return False, '120 秒被接受了'
    except ValueError as exc:
        return 'INVALID_SCHEDULE_INTERVAL' in str(exc), str(exc)


@case
def every_uses_native_repeat(env):
    rules = env['rules']
    rule = rules.normalize_rule({'intent': 'x', 'every_seconds': 1800})
    fire = rules.next_fire(rule, env['rules'].scene_timezone(config_with(), SCENE)['tz'], env['state'].CLOCK[0])
    return (rule == {'every_seconds': 1800}
            and rules.native_payload(rule, fire, env['state'].CLOCK[0]) == {'every_seconds': 1800}
            and rules.rearms_after_fire(rule) is False), rule


@case
def past_absolute_time_is_refused(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'at': '2026-09-23T09:00'})
    try:
        rules.next_fire(rule, zone['tz'], env['state'].CLOCK[0])
        return False, '过去了还当能安排'
    except ValueError as exc:
        return 'SCHEDULE_TIME_ALREADY_PAST' in str(exc), str(exc)


@case
def absolute_with_offset_is_exact_instant(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'at': '2026-09-25T02:00:00Z'})
    fire = rules.next_fire(rule, zone['tz'], env['state'].CLOCK[0])
    return rule.get('at_utc') is True and fire == datetime(2026, 9, 25, 2, tzinfo=timezone.utc), fire.isoformat()


@case
def gap_absolute_time_asks_instead_of_guessing(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'at': '2026-09-27T02:30'})   # 那天 02:00→03:00
    try:
        rules.next_fire(rule, zone['tz'], env['state'].CLOCK[0])
        return False, '不存在的钟点被默默接受了'
    except ValueError as exc:
        return 'SCHEDULE_LOCAL_TIME_MISSING' in str(exc) and '03:00' in str(exc), str(exc)


@case
def daily_uses_local_clock_not_86400(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    first = rules.next_fire(rule, zone['tz'], env['state'].CLOCK[0])
    second = rules.next_fire(rule, zone['tz'], first + timedelta(seconds=1))
    return (first == datetime.fromisoformat('2026-09-24T21:00:00+00:00')
            and second == datetime.fromisoformat('2026-09-25T21:00:00+00:00')
            and (second - first) == timedelta(hours=24)), [first.isoformat(), second.isoformat()]


@case
def daily_across_dst_start_shifts_by_one_hour(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    before = rules.next_fire(rule, zone['tz'], datetime(2026, 9, 25, 3, tzinfo=timezone.utc))
    after = rules.next_fire(rule, zone['tz'], before + timedelta(seconds=1))
    return ((after - before) == timedelta(hours=23)
            and before.astimezone(zone['tz']).strftime('%H:%M') == '09:00'
            and after.astimezone(zone['tz']).strftime('%H:%M') == '09:00'), \
        [before.isoformat(), after.isoformat()]


@case
def daily_across_dst_end_stays_local(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '09:00'}})
    before = rules.next_fire(rule, zone['tz'], datetime(2026, 4, 3, 3, tzinfo=timezone.utc))
    after = rules.next_fire(rule, zone['tz'], before + timedelta(seconds=1))
    return ((after - before) == timedelta(hours=25)
            and after.astimezone(zone['tz']).strftime('%H:%M') == '09:00'), \
        [before.isoformat(), after.isoformat()]


@case
def weekly_only_named_weekdays(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '21:30', 'weekdays': [0, 2]}})
    fire = rules.next_fire(rule, zone['tz'], env['state'].CLOCK[0])
    local = fire.astimezone(zone['tz'])
    return local.weekday() in (0, 2) and local.strftime('%H:%M') == '21:30', local.isoformat()


@case
def clock_on_gap_day_moves_to_first_valid_moment(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rule = rules.normalize_rule({'intent': 'x', 'clock': {'time': '02:30', 'weekdays': [6]}})
    fire = rules.next_fire(rule, zone['tz'], env['state'].CLOCK[0])
    row = rules.project({'_id': 'p', 'intent': 'x', 'status': 'ACTIVE', 'rule': rule}, zone,
                        env['state'].CLOCK[0])
    return (fire == DST_START and 'dst_note' in row and '02:30' in row['dst_note']), row.get('dst_note')


@case
def ambiguous_clock_takes_the_earlier_one(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    utc, kind = rules.wall_to_utc(datetime(2026, 4, 5, 2, 30), zone['tz'])
    return kind == 'ambiguous' and utc == datetime(2026, 4, 4, 13, 30, tzinfo=timezone.utc), utc.isoformat()


@case
def timezone_precedence_and_plan_override(env):
    rules = env['rules']
    scene = dict(SCENE, timezone='Asia/Tokyo')
    route_zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), scene)
    scene_zone = rules.scene_timezone(config_with(None), scene)
    config_zone = rules.scene_timezone(config_with(None, {'timezone': 'Asia/Tokyo'}), SCENE)
    default_zone = rules.scene_timezone(config_with(None), SCENE)
    plan_zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), scene,
                                     {'timezone': 'Asia/Tokyo'})
    return (route_zone['name'] == 'Pacific/Auckland' and route_zone['source'] == 'route'
            and scene_zone['name'] == 'Asia/Tokyo' and scene_zone['source'] == 'scene'
            and config_zone['source'] == 'config'
            and default_zone['name'] == 'Pacific/Auckland' and default_zone['source'] == 'default'
            and plan_zone['name'] == 'Asia/Tokyo'), [z['source'] for z in (route_zone, scene_zone, config_zone, default_zone, plan_zone)]


@case
def missing_tz_database_says_so(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Mars/Olympus', 'utc_offset_minutes': 720}), SCENE)
    plain = rules.scene_timezone(config_with({'timezone': 'Mars/Olympus'}), SCENE)
    row = rules.project({'_id': 'p', 'intent': 'x', 'status': 'ACTIVE',
                         'rule': {'clock': {'time': '09:00'}}}, zone, env['state'].CLOCK[0])
    return (zone['source'] == 'fixed_offset' and zone['zone_unavailable'] == 'Mars/Olympus'
            and plain['source'] == 'host_local' and 'timezone_note' in row), [zone['source'], plain['source']]


# ── 驱动层：真 create / update / cancel / deliver / reconcile ────────
DAILY = {'intent': '每天提醒我喝水', 'clock': {'time': '09:00'}}
ONCE = {'intent': '十分钟后看下锅', 'after_seconds': 600}
INTERVAL = {'intent': '每半小时报一次', 'every_seconds': 1800}


@case
def create_daily_registers_one_native_single_shot(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, DAILY)
    creates = [e['data']['schedule'] for e in lane.events if e['data'].get('operation') == 'create']
    return (plan['status'] == 'ACTIVE' and plan['rule'] == {'clock': {'time': '09:00'}}
            and plan['timezone'] == 'Pacific/Auckland' and len(creates) == 1
            and 'after_seconds' in creates[0] and 'every_seconds' not in creates[0]
            and plan['next_fire_at'] == '2026-09-24T21:00:00+00:00'), creates


@case
def create_rejects_past_time_and_leaves_nothing(env):
    service, store = env['service'], env['store']
    try:
        service.create(EP, {'intent': '昨天那件事', 'at': '2026-09-23T09:00'})
        return False, '没报错'
    except ValueError as exc:
        return ('SCHEDULE_TIME_ALREADY_PAST' in str(exc)
                and not store.db.plans.rows and not env['lane'].events), str(exc)


@case
def create_is_idempotent_for_the_same_episode(env):
    service, lane = env['service'], env['lane']
    first = service.create(EP, DAILY)
    second = service.create(EP, DAILY)
    creates = [e for e in lane.events if e['data'].get('operation') == 'create']
    return first['_id'] == second['_id'] and len(creates) == 1, len(creates)


@case
def fired_daily_stays_active_and_arms_next_day(env):
    service, store, lane, controller = env['service'], env['store'], env['lane'], env['controller']
    plan = service.create(EP, DAILY)
    fire(env, plan['schedule_id'])
    after = store.db.plans.find_one({'_id': plan['_id']})
    return (after['status'] == 'ACTIVE' and len(controller.received) == 1
            and after['next_fire_at'] == '2026-09-25T21:00:00+00:00'
            and len(lane.live(plan['_id'])) == 1 and after['fire_count'] == 1), \
        {'status': after['status'], 'next': after['next_fire_at'], 'live': len(lane.live(plan['_id']))}


@case
def replayed_dispatch_does_not_act_twice(env):
    service, store, lane, controller = env['service'], env['store'], env['lane'], env['controller']
    plan = service.create(EP, DAILY)
    event = fire(env, plan['schedule_id'])
    service.deliver({'session': 's-fake', 'seq': event['seq'], 'id': plan['schedule_id']})
    service.reconcile()
    return len(controller.received) == 1, len(controller.received)


@case
def fired_one_shot_is_fired_and_not_rearmed(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, ONCE)
    fire(env, plan['schedule_id'])
    after = store.db.plans.find_one({'_id': plan['_id']})
    return after['status'] == 'FIRED' and not lane.live(plan['_id']) and after['next_fire_at'] is None, \
        after['status']


@case
def fired_interval_leaves_repeat_to_native(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, INTERVAL)
    before = lane.created
    fire(env, plan['schedule_id'])
    after = store.db.plans.find_one({'_id': plan['_id']})
    return after['status'] == 'ACTIVE' and lane.created == before, {'status': after['status']}


@case
def enqueue_failure_keeps_next_registration(env):
    service, store, lane = env['service'], env['store'], env['lane']
    env['controller'].fail = RuntimeError('QUEUE_FULL')
    plan = service.create(EP, DAILY)
    fire(env, plan['schedule_id'])            # deliver() 不该把这异常抛出去
    after = store.db.plans.find_one({'_id': plan['_id']})
    return (after['status'] == 'ACTIVE' and after['last_outcome'] == 'QUEUE_FULL'
            and len(lane.live(plan['_id'])) == 1), {'outcome': after['last_outcome'], 'status': after['status']}


@case
def update_keeps_one_plan_and_one_live_native(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, DAILY)
    old = plan['schedule_id']
    updated = service.update(EP, plan['_id'], {'plan_id': plan['_id'],
                                               'schedule': {'clock': {'time': '21:30', 'weekdays': [0, 2, 4]}}})
    deleted = [e['data']['id'] for e in lane.events if e['data'].get('operation') == 'delete']
    live = lane.live(plan['_id'])
    return (updated['_id'] == plan['_id'] and updated['plan_version'] == 2
            and updated['rule'] == {'clock': {'time': '21:30', 'weekdays': [0, 2, 4]}}
            and deleted == [old] and len(live) == 1 and live[0]['id'] == updated['schedule_id']), \
        {'version': updated['plan_version'], 'deleted': deleted, 'live': len(live)}


@case
def stale_dispatch_after_update_does_not_act(env):
    service, store, lane, controller = env['service'], env['store'], env['lane'], env['controller']
    plan = service.create(EP, DAILY)
    old = plan['schedule_id']
    service.update(EP, plan['_id'], {'plan_id': plan['_id'], 'intent': '改成提醒我写周报',
                                     'schedule': {'after_seconds': 3600}})
    controller.received.clear()
    fire(env, old)                             # 旧版本那一次迟到了
    after = store.db.plans.find_one({'_id': plan['_id']})
    return not controller.received and after['last_outcome'] == 'STALE_PLAN_VERSION', after['last_outcome']


@case
def update_with_same_rule_touches_nothing(env):
    service, lane = env['service'], env['lane']
    plan = service.create(EP, DAILY)
    created = lane.created
    same = service.update(EP, plan['_id'], {'plan_id': plan['_id'], 'schedule': {'clock': {'time': '09:00'}}})
    return same['plan_version'] == 1 and lane.created == created, lane.created


@case
def cancel_removes_native_and_reconcile_does_not_resurrect(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, DAILY)
    service.cancel(plan['_id'], SCENE_ID, PERSON, 7)
    service.reconcile()
    after = store.db.plans.find_one({'_id': plan['_id']})
    return (after['status'] == 'CANCELLED' and not lane.live(plan['_id'])
            and 'schedule.cancelled' in store.kinds(plan['_id'])), after['status']


@case
def cancel_during_fire_wins_over_rearm(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, DAILY)
    row = store.db.plans.find_one({'_id': plan['_id']})

    def receive_then_cancel(event):
        current = store.db.plans.find_one({'_id': plan['_id']})
        store.put('plans', {**current, 'status': 'CANCELLED',
                            'cancelled_at': at(env['state'].CLOCK[0])},
                expected=current['revision'], stream=plan['_id'])
    env['controller'].receive = receive_then_cancel
    fire(env, plan['schedule_id'])
    after = store.db.plans.find_one({'_id': plan['_id']})
    return after['status'] == 'CANCELLED' and not lane.live(plan['_id']), \
        {'status': after['status'], 'live': len(lane.live(plan['_id']))}


@case
def reconcile_adopts_native_created_before_crash(env):
    service, store, lane = env['service'], env['store'], env['lane']
    plan = service.create(EP, DAILY)
    # 模拟：原生已经建好下一条，plans 还没落库就断了——把计划退回"指向一条已消失的记录"。
    row = store.db.plans.find_one({'_id': plan['_id']})
    lane.fire(plan['schedule_id'])                                  # 原来那条已派发
    service._rearm(plan['_id'])                                     # 建好下一次（原生有记录）
    live_id = lane.live(plan['_id'])[0]['id']
    stale = store.db.plans.find_one({'_id': plan['_id']})
    store.put('plans', {**stale, 'schedule_id': 'native-lost'}, expected=stale['revision'], stream=plan['_id'])
    service.reconcile()
    after = store.db.plans.find_one({'_id': plan['_id']})
    return after['schedule_id'] == live_id and after['status'] == 'ACTIVE', \
        {'linked': after['schedule_id'], 'want': live_id}


@case
def outage_acts_once_and_arms_the_future(env):
    service, store, lane, controller = env['service'], env['store'], env['lane'], env['controller']
    plan = service.create(EP, DAILY)
    lane.fire(plan['schedule_id'])                                  # 宿主停机时原生派发过一次
    env['state'].CLOCK[0] = T0 + timedelta(days=3, hours=5)          # 三天后才回来
    service.reconcile()
    after = store.db.plans.find_one({'_id': plan['_id']})
    fire_at = datetime.fromisoformat(after['next_fire_at'])
    local = fire_at.astimezone(env['rules'].ZoneInfo('Pacific/Auckland'))
    return (len(controller.received) == 1 and after['status'] == 'ACTIVE'
            and fire_at > env['state'].CLOCK[0] and local.strftime('%H:%M') == '09:00'
            and after.get('fire_count') == 1), {'acts': len(controller.received),
                                                'next': after['next_fire_at']}


# ── DECIDE 形状与控制字段：连 coordinator.py 的真 schema 一起验 ────────
STUB_EXTRA = {
    'config.py': 'from pathlib import Path\nimport os\nBUNDLE=Path(os.environ["ASUNA_BUNDLE"])\n'
                 'def prompt_path(config, name):\n    return BUNDLE/"prompts"/name\n'
                 'def redact_text(text, config):\n    return text\n',
    'evidence.py': 'import json, hashlib\ndef canonical(value):\n    return json.dumps(value, sort_keys=True).encode()\n'
                   'def sha(raw):\n    return hashlib.sha256(raw).hexdigest()\n',
    'lanes.py': 'class Lane:\n    pass\n',
    'publish.py': 'class PublishService:\n    def __init__(self, *a, **k):\n        pass\n',
    'peer_context.py': 'def apply_peer_context(context, source):\n    return context\n',
    'ingress.py': 'def episode_id(event):\n    return \"ep-\" + str(event[\"event_id\"])\n',
}


def load_coordinator():
    if 'p3coord' in _PACKAGES:
        return _PACKAGES['p3coord']
    import json
    os.environ['ASUNA_BUNDLE'] = os.path.join(ROOT, 'docs', 'development_plans',
                                              'ADR-001-asuna_v2_v1_handoff')
    root = tempfile.mkdtemp(prefix='p3coord-')
    package = os.path.join(root, 'p3coord')
    os.makedirs(package)
    open(os.path.join(package, '__init__.py'), 'w').close()
    # coordinator 与 context 都装真的：投影那条路不能只等宿主验（coordinator 就 import 这个 context）
    for name in ('coordinator.py', 'context.py', 'schedule_rules.py'):
        shutil.copyfile(os.path.join(SRC, name), os.path.join(package, name))
    bodies = dict(STUB_EXTRA, **{'state.py': STUB_STATE, 'channels.py': STUB_CHANNELS,
                                 'integration.py': STUB_INTEGRATION, 'dsh_lane.py': STUB_LANE})
    for name, body in bodies.items():
        open(os.path.join(package, name), 'w', encoding='utf-8').write(body)
    sys.path.insert(0, root)
    for name in ('p3coord.coordinator', 'p3coord.context', 'p3coord.schedule_rules'):
        sys.modules.pop(name, None)
    module = __import__('p3coord.coordinator', fromlist=['WORKSPACE_DECISION_SCHEMA'])
    _PACKAGES['p3coord'] = (module, json)
    return module, json


@case
def decide_schema_accepts_the_four_timings(env):
    import jsonschema
    module, _ = load_coordinator()
    schema = module.WORKSPACE_DECISION_SCHEMA
    base = {'next': 'speak', 'goal': 'g', 'constraints': [], 'recall_query': '',
            'speak_before_action': False}
    samples = [dict(base, schedule={'intent': 'x', 'after_seconds': 600}),
               dict(base, schedule={'intent': 'x', 'every_seconds': 900}),
               dict(base, schedule={'intent': 'x', 'at': '2026-10-01T15:00'}),
               dict(base, schedule={'intent': 'x', 'clock': {'time': '09:00', 'weekdays': [0, 4]}}),
               dict(base, update_plan={'plan_id': 'plan-1', 'schedule': {'clock': {'time': '21:30'}}}),
               dict(base, update_plan={'plan_id': 'plan-1', 'intent': '换个说法'})]
    for sample in samples:
        jsonschema.validate(sample, schema)
    return True, '%d 份 DECIDE 都过' % len(samples)


@case
def decide_schema_still_rejects_bad_shapes(env):
    import jsonschema
    module, _ = load_coordinator()
    schema = module.WORKSPACE_DECISION_SCHEMA
    base = {'next': 'speak', 'goal': 'g', 'constraints': [], 'recall_query': '',
            'speak_before_action': False}
    bad = [dict(base, schedule={'intent': 'x'}),
           dict(base, schedule={'intent': 'x', 'at': '2026-10-01T15:00', 'every_seconds': 900}),
           dict(base, schedule={'intent': 'x', 'clock': {'hour': 9}}),
           dict(base, schedule={'intent': 'x', 'cron': '0 9 * * *'}),
           dict(base, update_plan={'schedule': {'after_seconds': 60}})]
    rejected = 0
    for sample in bad:
        try:
            jsonschema.validate(sample, schema)
        except jsonschema.ValidationError:
            rejected += 1
    return rejected == len(bad), '%d/%d 被拒' % (rejected, len(bad))


@case
def rejected_time_does_not_kill_the_turn(env):
    module, _ = load_coordinator()
    store = Store(config_with({'timezone': 'Pacific/Auckland'}))
    episode = {'_id': 'ep-9', 'revision': 3, 'scope_key': 'scene:' + SCENE_ID}
    store.db.episodes.rows['ep-9'] = dict(episode)          # 这条回合已经在库里躺着了
    coordinator = module.Coordinator(store, None, context=object(), publisher=object())
    coordinator.scheduler = object()             # 只验控制字段怎么记，不验它底下接的是谁

    def boom():
        raise ValueError('SCHEDULE_TIME_ALREADY_PAST: 2026-09-23T09:00 已经过了')
    assert coordinator._plan_row({'context': {'plans_from_program': [{'_id': 'plan-1'}]}},
                                 'plan-1') == {'_id': 'plan-1'}
    assert coordinator._plan_row({'context': {'plans_from_program': []}}, 'plan-9') is None
    updated = coordinator._plan_control(episode, 'plan_result', boom)
    return (updated['plan_result']['accepted'] is False
            and 'SCHEDULE_TIME_ALREADY_PAST' in updated['plan_result']['error']
            and 'schedule.control_rejected' in store.kinds('ep-9')), updated['plan_result']


@case
def driver_keeps_all_date_math_out_of_itself(env):
    source = open(os.path.join(SRC, 'schedule.py'), encoding='utf-8').read()
    banned = ['timedelta', 'zoneinfo', 'Timer', 'sleep', 'cron', 'APScheduler', 'asyncio']
    hits = [word for word in banned if word in source]
    return not hits, hits


@case
def hooks_are_wired_in_context_and_coordinator(env):
    context = open(os.path.join(SRC, 'context.py'), encoding='utf-8').read()
    coordinator = open(os.path.join(SRC, 'coordinator.py'), encoding='utf-8').read()
    need = [('context 投影走 schedule_rules.project', "schedule_rules.project(row" in context),
            ('context 给出控制面与钟面', "schedule_control_from_program':schedule_rules.control_note" in context),
            ('context 也列已暂停的计划', "'ACTIVE','SUSPENDED'" in context),
            ('DECIDE 有 update_plan', "['properties']['update_plan']" in coordinator),
            ('DECIDE 走 _plan_control', coordinator.count('self._plan_control(') >= 3),
            ('改期结果进本轮记录', "'plan_update_result'" in coordinator),
            ('改期撞已取消时不打死这轮', 'SCHEDULE_PLAN_NOT_ACTIVE' in coordinator)]
    return all(flag for _, flag in need), [name for name, flag in need if not flag]


@case
def projection_explains_active_cancelled_and_suspended(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    rows = [rules.project({'_id': 'a', 'intent': '每天喝水', 'status': 'ACTIVE',
                           'rule': {'clock': {'time': '09:00'}}}, zone, env['state'].CLOCK[0]),
            rules.project({'_id': 'b', 'intent': '旧的一次性', 'status': 'CANCELLED',
                           'rule': {'after_seconds': 60}}, zone, env['state'].CLOCK[0]),
            rules.project({'_id': 'c', 'intent': '挂着的每周', 'status': 'SUSPENDED',
                           'rule': {'clock': {'time': '09:00'}}, 'last_outcome': 'SCHEDULE_CLOCK_NO_UPCOMING'},
                          zone, env['state'].CLOCK[0])]
    return (rows[0]['local'].startswith('2026-09-25T09:00') and rows[0]['timezone'] == 'Pacific/Auckland'
            and rows[1]['why_no_next'] == '已取消' and 'SCHEDULE_CLOCK_NO_UPCOMING' in rows[2]['why_no_next']), \
        [row.get('local') or row.get('why_no_next') for row in rows]


@case
def control_note_carries_the_local_clock(env):
    rules = env['rules']
    zone = rules.scene_timezone(config_with({'timezone': 'Pacific/Auckland'}), SCENE)
    note = rules.control_note(zone, env['state'].CLOCK[0])
    return (note['now_local'] == '2026-09-24T17:00+12:00' and note['weekday'] == '周四'
            and set(note['fields']) == {'schedule', 'update_plan', 'cancel_plan_id'}
            and note['min_interval_seconds'] == 300), note['now_local']


@case
def context_projection_runs_end_to_end(env):
    """真 context.py 的 prepare 跑一遍：她拿到的计划行得是这个场景的钟面，不是 UTC 裸时刻。"""
    module, _ = load_coordinator()
    store = Store(config_with({'timezone': 'Pacific/Auckland'}))
    store.db.scenes.rows.update({SCENE['_id']: dict(SCENE, revision=1)})
    store.db.state_revisions.rows['rev-persona'] = {
        '_id': 'rev-persona', 'entity_key': 'persona:P1|global-safe', 'scope_key': 'global-safe',
        'revision': 1, 'content': {'body': '沈小满，24 岁。' + '说话清淡直接。' * 12},
        'source_ids': [], 'parent_revision_id': None}
    store.db.state_heads.rows['persona:P1|global-safe'] = {
        '_id': 'persona:P1|global-safe', 'scope_key': 'global-safe', 'revision_id': 'rev-persona',
        'revision': 1}
    store.db.plans.rows['plan-7'] = {'_id': 'plan-7', 'scene_id': SCENE_ID, 'person_id': PERSON,
                                     'scope_key': 'scene:' + SCENE_ID, 'policy_epoch': 7,
                                     'intent': '每天提醒我喝水', 'rule': {'clock': {'time': '09:00'}},
                                     'status': 'ACTIVE', 'timezone': 'Pacific/Auckland',
                                     'tz_source': 'route', 'plan_version': 1, 'revision': 1,
                                     'created_at': '2026-09-24T04:00:00+00:00'}
    _system, context, _manifest = module.ContextBuilder(store, retrieval=None).prepare(
        {'event_id': 'evt-1', 'scene_id': SCENE_ID, 'person_id': PERSON, 'text': '我有哪些安排'})
    rows = context['plans_from_program']
    note = context['schedule_control_from_program']
    # 这一条走的是真 now（不是假时钟），所以断言"形状与口径"而不是钉死某个日期：
    # 下一次必须落在本地 09:00、带这个场景的偏移、并且晚于她看到的现场钟面。
    fire = datetime.fromisoformat(rows[0]['local'])
    return (len(rows) == 1 and rows[0]['timezone'] == 'Pacific/Auckland'
            and '每天' in rows[0]['description'] and rows[0]['local'][11:16] == '09:00'
            and rows[0]['local'].endswith(('+12:00', '+13:00'))
            and fire > datetime.fromisoformat(note['now_local'])
            and note['timezone'] == 'Pacific/Auckland'
            and set(note['fields']) == {'schedule', 'update_plan', 'cancel_plan_id'}),         [rows[0].get('local'), note.get('now_local')]


# ── 跑法 ────────────────────────────────────────────────────
def run_all():
    rows = []
    for function in CASES:
        try:
            ok, detail = function(setup())
        except Exception as exc:                       # 用例自己崩了也算红
            ok, detail = False, '%s: %s' % (type(exc).__name__, exc)
        rows.append((function.__name__, bool(ok), detail))
    return rows


if __name__ == '__main__':
    results = run_all()
    for name, ok, detail in results:
        print('%s %s %s' % ('PASS' if ok else 'FAIL', name, '' if ok else '→ ' + str(detail)[:200]))
    bad = [name for name, ok, _ in results if not ok]
    print('P3 离线用例：%d/%d 通过%s' % (len(results) - len(bad), len(results),
                                      '' if not bad else '，失败：' + ', '.join(bad)))
    sys.exit(1 if bad else 0)
