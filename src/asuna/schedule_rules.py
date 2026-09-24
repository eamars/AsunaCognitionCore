"""ADR-005 P3：把自然语言里的时间换算成 DSH 的那一次钟点——纯换算，不碰网络也不碰 Mongo。

分工照 DELIVERY_PLAN §P3／DECISIONS §6：**不建第二个 scheduler**。计时与唤醒只有 DSH 一个时钟，
本模块只回答三个问题：这条规则下一次是绝对哪一刻、该给原生挂什么载荷、这条计划在场景时区里
怎么用人话说出来。每日／每周把本地钟点存在现有 plans.rule 里，到期后由调用方再挂一次**原生单次**，
这里不起线程、不轮询、不补发历史。

时区口径：场景配置优先，未配置继承 Pacific/Auckland；确认时把用的哪个时区一并交出去。
DST：每日／每周当日遇到不存在的钟点，顺延到该日之后第一个真实存在的本地时刻（就是跳变那一刻）；
重叠的钟点只取较早的一次；单次安排遇到不存在的本地时间**不猜**，抛错让角色问那一句。
换算只用标准库 zoneinfo。宿主环境没有 tz 数据库时退回这个场景里已配的固定偏移
（`utc_offset_minutes`，与 proactive 块同名但各块自己读），
连偏移都没有就用宿主本地时区——三种来源写在 tz_source 里，不假装自己还带着 DST 规则。
"""
from __future__ import annotations

from datetime import datetime, time as wall_time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:                                    # 极老的运行时：没有 zoneinfo 也要能跑
    ZoneInfo, ZoneInfoNotFoundError = None, Exception

DEFAULT_TIMEZONE = 'Pacific/Auckland'
MIN_INTERVAL_SECONDS = 300                            # 上游原生 every 的最小间隔，已核实
MAX_INTERVAL_SECONDS = 366 * 86400
TIMING_KEYS = ('after_seconds', 'every_seconds', 'at', 'clock')
WEEKDAY_NAMES = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def now_utc():
    return datetime.now(timezone.utc)


def _aware(moment):
    """任何进来的时刻都换成 aware UTC：naive 一律按 UTC 读，不当成本地。"""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if not isinstance(moment, datetime):
        raise ValueError('INVALID_MOMENT')
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


# ── 时区：一个场景用哪个钟面，只从现有场景配置里读一处 ─────────────────
def _route_of(config, scene):
    channel = (config or {}).get('channels', {}).get((scene or {}).get('channel_id') or '')
    for route in (channel or {}).get('routes', {}).values():
        if route.get('scene_id') == (scene or {}).get('_id'):
            return route
    return None


def _zone(name, offset_minutes=None):
    """按名字取时区；取不到就退回固定偏移／宿主本地，并把"名字没生效"照实带回去。"""
    if ZoneInfo is not None and isinstance(name, str) and name:
        try:
            return {'tz': ZoneInfo(name), 'zone_unavailable': None}
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    if type(offset_minutes) is int and -840 <= offset_minutes <= 840:
        return {'tz': timezone(timedelta(minutes=offset_minutes)), 'zone_unavailable': name}
    return {'tz': datetime.now().astimezone().tzinfo, 'zone_unavailable': name}


def scene_timezone(config, scene, plan=None):
    """这个场景（或这条计划创建时）用哪个时区。计划上已落库的时区优先，改配置不追改旧计划。"""
    route = _route_of(config, scene)
    block = (route or {}).get('schedule') if isinstance((route or {}).get('schedule'), dict) else {}
    offset = block.get('utc_offset_minutes')
    if type(offset) is not int or not -840 <= offset <= 840:
        offset = None
    for name, source in (((plan or {}).get('timezone'), 'plan'),
                         (block.get('timezone') or (route or {}).get('timezone'), 'route'),
                         ((scene or {}).get('timezone'), 'scene'),
                         ((config or {}).get('timezone'), 'config'),
                         (DEFAULT_TIMEZONE, 'default')):
        if not (isinstance(name, str) and name):
            continue
        zone = _zone(name, offset)
        source = source if zone['zone_unavailable'] is None else 'fixed_offset' if offset else 'host_local'
        return {'name': name, 'requested': name, 'source': source, 'offset_minutes': offset,
                'tz': zone['tz'], 'zone_unavailable': zone['zone_unavailable']}
    raise ValueError('SCHEDULE_TIMEZONE_UNRESOLVED')


def offset_minutes(tz, moment):
    delta = _aware(moment).astimezone(tz).utcoffset()
    return int(delta.total_seconds() // 60) if delta else 0


# ── DST：本地墙钟 ↔ UTC ────────────────────────────────────────
def _offset_at(tz, moment):
    return _aware(moment).astimezone(tz).utcoffset()


def _transition(tz, lo, hi):
    """二分找出 lo..hi 之间那次偏移跳变的第一个瞬间（新偏移生效的那一刻）。"""
    lo, hi = _aware(lo), _aware(hi)
    if _offset_at(tz, lo) == _offset_at(tz, hi):
        return None
    for _ in range(48):
        mid = lo + (hi - lo) / 2
        if mid == lo or mid == hi:
            break
        if _offset_at(tz, mid) == _offset_at(tz, lo):
            lo = mid
        else:
            hi = mid
    return hi


def wall_to_utc(wall, tz):
    """本地墙钟 → UTC 瞬间，并说明这段本地时间是什么情况。

    返回 (utc, kind)：kind='exact' 正常；'ambiguous' 这个钟点出现两次，取较早的一次；
    'gap' 这个钟点根本不存在（春季拨快），返回的是跳变那一刻——顺延到之后第一个真实存在的本地时刻。
    """
    if wall.tzinfo is not None:
        return _aware(wall), 'exact'
    pre = wall.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
    post = wall.replace(tzinfo=tz, fold=1).astimezone(timezone.utc)
    if pre == post:
        return pre, 'exact'
    if pre.astimezone(tz).replace(tzinfo=None) == wall and post.astimezone(tz).replace(tzinfo=None) == wall:
        return min(pre, post), 'ambiguous'            # fold=0 就是较早的那一次
    gap = _transition(tz, min(pre, post) - timedelta(minutes=2), max(pre, post) + timedelta(minutes=2))
    if gap is None:                                   # 理论上到不了：偏移没变就不会走到这支
        return max(pre, post), 'exact'
    return gap, 'gap'


# ── 规则：DECIDE 里的 schedule → plans.rule 的规范形状 ─────────────
def _clock_shape(value):
    if not isinstance(value, dict) or set(value) - {'time', 'weekdays'}:
        raise ValueError('SCHEDULE_CLOCK_SHAPE: 只接受 {time:"HH:MM", weekdays:[0-6]?}')
    parts = str(value.get('time', '')).strip().split(':')
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise ValueError('SCHEDULE_CLOCK_TIME_INVALID: 要给 24 小时制的 HH:MM') from None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError('SCHEDULE_CLOCK_TIME_INVALID: 钟点超出 00:00–23:59')
    rule = {'time': '%02d:%02d' % (hour, minute)}
    if 'weekdays' in value:
        days = value['weekdays']
        if not isinstance(days, list) or not 1 <= len(days) <= 7 or any(type(d) is not int or not 0 <= d <= 6 for d in days):
            raise ValueError('SCHEDULE_CLOCK_WEEKDAYS_INVALID: weekdays 用 0=周一…6=周日的整数数组')
        rule['weekdays'] = sorted(set(days))
    return rule


def _wall_shape(value):
    if not isinstance(value, str) or not 10 <= len(value.strip()) <= 40:
        raise ValueError('SCHEDULE_AT_INVALID: 要给 YYYY-MM-DDTHH:MM（可带偏移）')
    text = value.strip().replace(' ', 'T')
    try:
        moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('SCHEDULE_AT_INVALID: 认不出这个日期时间：%s' % value) from None
    if moment.tzinfo is not None:
        return {'at': moment.astimezone(timezone.utc).isoformat(timespec='minutes'), 'at_utc': True}
    if not 2000 <= moment.year <= 2100:
        raise ValueError('SCHEDULE_AT_OUT_OF_RANGE: 年份在 2000–2100 之外，先确认日期')
    return {'at': moment.isoformat(timespec='minutes')}


def normalize_rule(spec):
    """校验并规范化一条时间安排；只认四种计时，别的都明确拒绝（不静默降级成"大概十分钟"）。"""
    if not isinstance(spec, dict):
        raise ValueError('INVALID_SCHEDULE_SPEC: 要一个对象')
    timing = [key for key in TIMING_KEYS if key in spec]
    if set(spec) - set(TIMING_KEYS) - {'intent'} or len(timing) != 1:
        raise ValueError('INVALID_SCHEDULE_SPEC: intent 之外，after_seconds/every_seconds/at/clock 里恰好给一个')
    key = timing[0]
    value = spec[key]
    if key == 'after_seconds':
        if type(value) is not int or not 1 <= value <= MAX_INTERVAL_SECONDS:
            raise ValueError('INVALID_SCHEDULE_INTERVAL: after_seconds 是 1…%d 的整数秒' % MAX_INTERVAL_SECONDS)
        return {'after_seconds': value}
    if key == 'every_seconds':
        if type(value) is not int or not MIN_INTERVAL_SECONDS <= value <= MAX_INTERVAL_SECONDS:
            raise ValueError('INVALID_SCHEDULE_INTERVAL: 固定间隔最小 %d 秒（原生限制）' % MIN_INTERVAL_SECONDS)
        return {'every_seconds': value}
    if key == 'at':
        return _wall_shape(value)
    return {'clock': _clock_shape(value)}


def rule_kind(rule):
    for key, kind in (('after_seconds', 'after'), ('every_seconds', 'every'), ('at', 'at'), ('clock', 'clock')):
        if isinstance(rule, dict) and key in rule:
            return kind
    raise ValueError('UNKNOWN_SCHEDULE_RULE')


def rearms_after_fire(rule):
    """到期后要不要由宿主再挂一次原生单次：每日／每周要；原生自己重复的 every 不要。"""
    return rule_kind(rule) == 'clock'


def next_fire(rule, tz, moment=None):
    """下一次绝对时刻（aware UTC）。时间已过／本地不存在都抛 ValueError，不静默当成已完成。"""
    moment = _aware(moment)
    kind = rule_kind(rule)
    if kind == 'after':
        return moment + timedelta(seconds=rule['after_seconds'])
    if kind == 'every':
        return moment + timedelta(seconds=rule['every_seconds'])
    if kind == 'at':
        if rule.get('at_utc'):
            fire = _aware(rule['at'])
        else:
            fire, dst = wall_to_utc(datetime.fromisoformat(rule['at']), tz)
            if dst == 'gap':
                raise ValueError('SCHEDULE_LOCAL_TIME_MISSING: %s 在这个时区不存在（拨快跳过），顺延的话是 %s'
                                 % (rule['at'], fire.astimezone(tz).isoformat(timespec='minutes')))
        if fire <= moment:
            raise ValueError('SCHEDULE_TIME_ALREADY_PAST: %s 已经过了（当时是 %s），要定在什么时候？'
                             % (rule['at'], moment.astimezone(tz).isoformat(timespec='minutes')))
        return fire
    clock = rule['clock']
    hour, minute = (int(part) for part in clock['time'].split(':'))
    days = clock.get('weekdays')
    local_now = moment.astimezone(tz)
    for offset in range(0, 9):
        day = (local_now + timedelta(days=offset)).date()
        if days and day.weekday() not in days:
            continue
        fire, _ = wall_to_utc(datetime.combine(day, wall_time(hour, minute)), tz)
        if fire > moment:
            return fire
    raise ValueError('SCHEDULE_CLOCK_NO_UPCOMING: 这条钟点规则算不出下一次')


def native_payload(rule, fire_at, moment=None):
    """给原生 /schedule/create 的载荷：固定间隔交给原生重复，其余一律换算成"多少秒之后"的单次。"""
    kind = rule_kind(rule)
    if kind == 'every':
        return {'every_seconds': rule['every_seconds']}
    seconds = int((_aware(fire_at) - _aware(moment)).total_seconds())
    return {'after_seconds': max(1, seconds)}


# ── 给人看的说法 ───────────────────────────────────────────────
def _local_text(moment, tz):
    return _aware(moment).astimezone(tz).isoformat(timespec='minutes')


def describe(rule, tz):
    kind = rule_kind(rule)
    if kind == 'after':
        seconds = rule['after_seconds']
        human = ('约 %d 天后' % (seconds // 86400)) if seconds >= 86400 else (
            ('约 %d 分钟后' % (seconds // 60)) if seconds >= 60 else '%d 秒后' % seconds)
        return '一次性：%s' % human
    if kind == 'every':
        seconds = rule['every_seconds']
        human = ('每 %d 天' % (seconds // 86400)) if seconds % 86400 == 0 and seconds >= 86400 else (
            ('每 %d 小时' % (seconds // 3600)) if seconds % 3600 == 0 and seconds >= 3600 else '每 %d 分钟' % (seconds // 60))
        return '%s重复（原生自己重复）' % human
    if kind == 'at':
        return '一次性：%s' % rule['at']
    clock = rule['clock']
    days = clock.get('weekdays')
    who = '每天' if not days else '每' + '、'.join(WEEKDAY_NAMES[d] for d in days)
    return '%s %s（本地钟点）' % (who, clock['time'])


def project(plan, zone, moment=None):
    """把一条 plans 行投影成角色上下文里那一行：带人话、带场景时区的下一次，不让她自己换算。"""
    moment = _aware(moment)
    tz = zone['tz']
    row = {'_id': plan['_id'], 'intent': plan.get('intent'), 'status': plan.get('status'),
           'rule': plan.get('rule'), 'plan_version': plan.get('plan_version', 1),
           'timezone': zone['name'], 'tz_source': zone['source'],
           'created_at': plan.get('created_at'), 'updated_at': plan.get('updated_at'),
           'last_outcome': plan.get('last_outcome')}
    if zone['zone_unavailable']:
        row['timezone_note'] = '时区库读不到 %s，按固定偏移算（这一条没有 DST 规则）' % zone['zone_unavailable']
    try:
        row['description'] = describe(plan['rule'], tz)
    except (ValueError, KeyError):
        row['description'] = '规则认不出来：可能是旧版本留下的记录'
        return row
    if plan.get('status') in ('CANCELLED', 'FIRED', 'SUSPENDED'):
        row['local'] = None
        row['next_fire_at'] = plan.get('scheduled_at')
        row['why_no_next'] = {'CANCELLED': '已取消', 'FIRED': '已经到期过（一次性安排）',
                              'SUSPENDED': plan.get('last_outcome') or '已暂停'}[plan['status']]
        return row
    try:
        fire = next_fire(plan['rule'], tz, moment)
    except ValueError as exc:
        row['local'] = None
        row['next_fire_at'] = plan.get('scheduled_at')
        row['why_no_next'] = str(exc)
        return row
    row['next_fire_at'] = fire.isoformat(timespec='seconds')
    row['local'] = _local_text(fire, tz)
    shifted = _shift_note(plan['rule'], fire, tz)
    if shifted:
        row['dst_note'] = shifted
    return row


def _shift_note(rule, fire, tz):
    """规则里写的钟点与真正会响的本地时刻不一致（只有 DST 空档顺延会这样）→ 写成一句人话。"""
    try:
        kind = rule_kind(rule)
    except ValueError:
        return None
    local = fire.astimezone(tz)
    asked = None
    if kind == 'at' and not rule.get('at_utc'):
        asked = rule['at'][:16]
        shown = local.isoformat(timespec='minutes')[:16]
    elif kind == 'clock':
        asked = rule['clock']['time']
        shown = local.strftime('%H:%M')
    else:
        return None
    if asked == shown:
        return None
    return '规则里的 %s 那天不存在（拨快跳过），已顺延到 %s' % (asked, _local_text(fire, tz))


def local_clock(zone, moment=None):
    """给角色的现场钟面：她换算"明天下午三点"要用，不让她猜自己在哪个时区。"""
    moment = _aware(moment)
    tz = zone['tz']
    local = moment.astimezone(tz)
    note = {'route': '这个场景配置的时区', 'plan': '这条计划创建时的时区', 'scene': '这个场景的时区',
            'config': '全局配置的时区', 'default': '没配时区，按约定的默认 %s' % DEFAULT_TIMEZONE,
            'fixed_offset': '时区库读不到，按场景里配的固定偏移', 'host_local': '时区库和偏移都没有，用宿主本地时区'}
    return {'now_local': local.isoformat(timespec='minutes'), 'weekday': WEEKDAY_NAMES[local.weekday()],
            'timezone': zone['name'], 'tz_source': zone['source'],
            'tz_note': note.get(zone['source'], zone['source']),
            'utc_offset_minutes': offset_minutes(tz, moment)}


def control_note(zone, moment=None):
    """给角色的"安排"控制面：现场钟面 + 三个控制字段怎么写。她负责把话换算成这些键，
    本模块负责换算成钟点；她不需要抄 schedule ID，也不需要知道原生怎么挂。"""
    return {**local_clock(zone, moment),
            'min_interval_seconds': MIN_INTERVAL_SECONDS,
            'fields': {
                'schedule': {'intent': '要做什么（给人看的短句）',
                             '计时四选一': {'after_seconds': '整数秒：一次性，N 秒之后',
                                          'every_seconds': '整数秒：固定间隔重复，最小 %d 秒（原生限制）' % MIN_INTERVAL_SECONDS,
                                          'at': 'YYYY-MM-DDTHH:MM：一次性，按下面 timezone 那个钟面读',
                                          'clock': '{"time":"HH:MM","weekdays":[0,2]}：每日/每周本地钟点；'
                                                   'weekdays 用 0=周一…6=周日，省略就是每天'}},
                'update_plan': {'plan_id': 'plans_from_program 里的 _id',
                                'intent': '可选：只改内容就给这个',
                                'schedule': '改时间：与 schedule 一样的四种计时之一'},
                'cancel_plan_id': 'plans_from_program 里的 _id'},
            'rules': ['时间不完整或已经过了：程序会拒绝并把原因写进本轮结果，问一句就好，不用自己猜',
                      '每日/每周按这个时区的本地钟点算；DST 空档顺延到那天第一个真实存在的钟点，'
                      '重叠的钟点只取较早的一次',
                      '到期只是把你叫醒：做不做、怎么做仍由你判断；没做不会让这条安排消失',
                      '改期与取消只对 plans_from_program 里列出的当前有效版本生效；改期不会多出第二个同时有效的版本',
                      '固定间隔（every_seconds）由 DSH 自己重复；每日/每周每次到期后由宿主再挂下一次']}
