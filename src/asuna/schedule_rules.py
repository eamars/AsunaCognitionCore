"""ADR-005 P3：把自然语言里的时间换算成 DSH 的那一次钟点——纯换算，不碰网络也不碰 Mongo。

分工照 DELIVERY_PLAN §P3／DECISIONS §6：**不建第二个 scheduler**。计时与唤醒只有 DSH 一个时钟，
本模块只回答三个问题：这条规则下一次是绝对哪一刻、该给原生挂什么载荷、这条计划在场景时区里
怎么用人话说出来。每日／每周把本地钟点存在现有 plans.rule 里，到期后由调用方再挂一次**原生单次**，
这里不起线程、不轮询、不补发历史。

时区口径：她只有一个钟面（`her_zone`）——部署设置里的 `timezone`；没设就用宿主报来的本机时区；都没有按 UTC。
核心不带任何人的默认时区，场景、路由、群都不再有自己的钟。一条计划若自己存着另一个钟面（旧的每日／每周安排），
`plan_zone` 把它按那个钟面算，读它的话里说明比她的钟快或慢多少。
DST：每日／每周当日遇到不存在的钟点，顺延到该日之后第一个真实存在的本地时刻（就是跳变那一刻）；
重叠的钟点只取较早的一次；单次安排遇到不存在的本地时间**不猜**，抛错让角色问那一句。
换算只用标准库 zoneinfo（`tzdata` 是固定依赖，合法的名字一定读得到）。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, time as wall_time, timedelta, timezone
from . import clock

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:                                    # 极老的运行时：没有 zoneinfo 也要能跑
    ZoneInfo, ZoneInfoNotFoundError = None, Exception

# The only definition of the floor: DSH 0.2 MIN_EVERY_INTERVAL_SECONDS (verified in the pinned package).
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 366 * 86400
TIMING_KEYS = ('after_seconds', 'every_seconds', 'at', 'clock')
WEEKDAY_NAMES = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def now_utc():
    return clock.now()


def _aware(moment):
    """任何进来的时刻都换成 aware UTC：naive 一律按 UTC 读，不当成本地。"""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if not isinstance(moment, datetime):
        raise ValueError('INVALID_MOMENT')
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


# ── 时区：她只有一个钟面 ───────────────────────────────────────────────
HOST_ZONE_ENV = 'ASUNA_HOST_TIMEZONE'        # the Host gives the worker the machine's IANA zone (worker.js)


def _load(name):
    """The zone database's zone of this name, or None."""
    if ZoneInfo is None or not isinstance(name, str) or not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def machine_zone_name():
    """The machine's own zone as an IANA name: what the Host reported, else `TZ`; None when neither loads."""
    for name in (os.environ.get(HOST_ZONE_ENV), os.environ.get('TZ')):
        if _load(name):
            return name
    return None


def her_zone(config):
    """The one clock everything she reads is on: the deployment's `timezone` setting; when it is not set (or does not
    load, `setting_unreadable`) the machine's zone; else UTC. `source` is setting, machine or unset."""
    given = (config or {}).get('timezone')
    tz = _load(given)
    if tz:
        return {'name': given, 'tz': tz, 'source': 'setting', 'setting_unreadable': False}
    unreadable = bool(given)
    name = machine_zone_name()
    if name:
        return {'name': name, 'tz': _load(name), 'source': 'machine', 'setting_unreadable': unreadable}
    return {'name': 'UTC', 'tz': timezone.utc, 'source': 'unset', 'setting_unreadable': unreadable}


def has_wall_zone(rule):
    """Whether a rule's meaning depends on a zone: a daily or weekly clock, or an `at` written without an offset."""
    return isinstance(rule, dict) and ('clock' in rule or ('at' in rule and not rule.get('at_utc')))


def plan_zone(plan, her):
    """The zone a plan's rule is written in: the one it stored when the rule has a wall zone and it loads, else hers.
    `unreadable` is true when the plan stored a zone that does not load (it then reads on her clock)."""
    name = plan.get('timezone')
    if not has_wall_zone(plan.get('rule')) or not name or name == her['name']:
        return {**her, 'unreadable': False}
    tz = _load(name)
    if tz is None:
        return {**her, 'unreadable': True}
    return {'name': name, 'tz': tz, 'source': 'plan', 'setting_unreadable': False, 'unreadable': False}


def moved_from(plan, her, timing_given):
    """The name of the zone a plan is moved off when a call gives it a timing: its rule has a wall zone and was written
    on a clock that is not hers. None for a call that gives no timing (new wording keeps the plan as it is) and for a
    plan that is already on her clock."""
    if not timing_given or not has_wall_zone(plan.get('rule')):
        return None
    name = plan_zone(plan, her)['name']
    return name if name != her['name'] else None


def pin_at(rule, fire_at):
    """An `at` written without an offset becomes the moment it names, so an appointment never depends on a zone;
    every other rule as it is."""
    if isinstance(rule, dict) and 'at' in rule and not rule.get('at_utc'):
        return {'at': _aware(fire_at).isoformat(timespec='minutes'), 'at_utc': True}
    return rule


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
        raise ValueError('SCHEDULE_CLOCK_SHAPE: clock 只接受 {time:"HH:MM", weekdays:[0-6]（可省）}%s'
                         % ('，多了 ' + '、'.join(sorted(map(str, set(value) - {'time', 'weekdays'})))
                            if isinstance(value, dict) else '，给的不是对象'))
    parts = str(value.get('time', '')).strip().split(':')
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise ValueError('SCHEDULE_CLOCK_TIME_INVALID: time「%s」不对，要给 24 小时制的 HH:MM，如 08:30'
                         % value.get('time', '')) from None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError('SCHEDULE_CLOCK_TIME_INVALID: time「%s」超出 00:00–23:59' % value.get('time'))
    rule = {'time': '%02d:%02d' % (hour, minute)}
    if 'weekdays' in value:
        days = value['weekdays']
        if not isinstance(days, list) or not 1 <= len(days) <= 7 or any(type(d) is not int or not 0 <= d <= 6 for d in days):
            raise ValueError('SCHEDULE_CLOCK_WEEKDAYS_INVALID: weekdays 给的是 %s；要 1–7 个 0=周一…6=周日的整数，'
                             '每天就不写' % json.dumps(days, ensure_ascii=False)[:80])
        rule['weekdays'] = sorted(set(days))
    return rule


# The clock face she reads (local_time.face): 10/19 21:05, or 2026/10/19 21:05. What she reads she may write back.
FACE = re.compile(r'^(?:(\d{4})/)?(\d{1,2})/(\d{1,2})[ T](\d{1,2}):(\d{2})$')


def _face_to_iso(value):
    """A time written on her clock face as ISO; without a year, the next such date (this year, or next once it passed)."""
    found = FACE.match(value.strip()) if isinstance(value, str) else None
    if not found:
        return value
    year, month, day, hour, minute = found.groups()
    today = clock.now()
    if year is None:
        year = today.year
        try:
            if datetime(year, int(month), int(day), tzinfo=timezone.utc) < today - timedelta(days=1):
                year += 1
        except ValueError:
            return value
    return '%04d-%02d-%02dT%02d:%s' % (int(year), int(month), int(day), int(hour), minute)


def _wall_shape(value):
    value = _face_to_iso(value)
    if not isinstance(value, str) or not 10 <= len(value.strip()) <= 40:
        raise ValueError('SCHEDULE_AT_INVALID: at 给的是 %s；要给 YYYY-MM-DDTHH:MM（可带偏移）'
                         % json.dumps(value, ensure_ascii=False)[:60])
    text = value.strip().replace(' ', 'T')
    try:
        moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('SCHEDULE_AT_INVALID: 认不出这个日期时间：%s；要给 YYYY-MM-DDTHH:MM' % value) from None
    if moment.tzinfo is not None:
        return {'at': moment.astimezone(timezone.utc).isoformat(timespec='minutes'), 'at_utc': True}
    if not 2000 <= moment.year <= 2100:
        raise ValueError('SCHEDULE_AT_OUT_OF_RANGE: 年份 %d 在 2000–2100 之外；对一下 clock_from_program 里今天的日期'
                         % moment.year)
    return {'at': moment.isoformat(timespec='minutes')}


def normalize_rule(spec):
    """校验并规范化一条时间安排；只认四种计时，别的都明确拒绝（不静默降级成"大概十分钟"）。"""
    if not isinstance(spec, dict):
        raise ValueError('INVALID_SCHEDULE_SPEC: 要一个对象')
    timing = [key for key in TIMING_KEYS if key in spec]
    extra = sorted(map(str, set(spec) - set(TIMING_KEYS) - {'intent'}))
    if extra or len(timing) != 1:
        given = ('多了 ' + '、'.join(extra) if extra else '给了 ' + '、'.join(timing) if timing else '一种计时都没给')
        raise ValueError('INVALID_SCHEDULE_SPEC: %s；intent 之外，after_seconds/every_seconds/at/clock 里恰好给一个' % given)
    key = timing[0]
    value = spec[key]
    if key == 'after_seconds':
        if type(value) is not int or not 1 <= value <= MAX_INTERVAL_SECONDS:
            raise ValueError('INVALID_SCHEDULE_INTERVAL: after_seconds 给的是 %s；要 1…%d 的整数秒'
                             % (json.dumps(value, ensure_ascii=False)[:40], MAX_INTERVAL_SECONDS))
        return {'after_seconds': value}
    if key == 'every_seconds':
        if type(value) is not int or not MIN_INTERVAL_SECONDS <= value <= MAX_INTERVAL_SECONDS:
            raise ValueError('INVALID_SCHEDULE_INTERVAL: every_seconds 给的是 %s；要 %d…%d 的整数秒（最小 %d 秒是原生限制）'
                             % (json.dumps(value, ensure_ascii=False)[:40], MIN_INTERVAL_SECONDS,
                                MAX_INTERVAL_SECONDS, MIN_INTERVAL_SECONDS))
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
                                 % (rule['at'], _local_text(fire, tz)))
        if fire <= moment:
            raise ValueError('SCHEDULE_TIME_ALREADY_PAST: %s 已经过了（当时是 %s）；改成之后的时刻'
                             % (rule['at'], _local_text(moment, tz)))
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


def local_moment(zone, moment=None):
    """The moment on the wall clock of a zone, given as an IANA name or as a tzinfo (rhythm, settlement dates)."""
    return _aware(moment or now_utc()).astimezone(ZoneInfo(zone) if isinstance(zone, str) else zone)


def minutes_later(minutes, moment=None):
    """An ISO moment some minutes after now (her heartbeat pause)."""
    return (_aware(moment or now_utc()) + timedelta(minutes=int(minutes))).isoformat(timespec='seconds')


def is_iana(zone_name) -> bool:
    """An explicit IANA Area/Location zone (or UTC) that the native daily/weekly rules accept."""
    if not isinstance(zone_name, str) or not (zone_name == 'UTC' or '/' in zone_name) or ZoneInfo is None:
        return False
    try:
        ZoneInfo(zone_name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def native_recurring(rule, zone_name):
    """Clock rules in an IANA zone map to native daily/weekly (weekday 0…6 → ISO 1…7); else None.

    A fixed-offset zone keeps the one-shot re-arm path.
    """
    if rule_kind(rule) != 'clock' or not is_iana(zone_name):
        return None
    clock = rule['clock']
    time_text = clock['time'] if len(clock['time']) > 5 else clock['time'] + ':00'
    if clock.get('weekdays'):
        return {'weekly': {'time': time_text, 'time_zone': zone_name,
                           'weekdays': sorted({int(day) + 1 for day in clock['weekdays']})}}
    return {'daily': {'time': time_text, 'time_zone': zone_name}}


def native_payload(rule, fire_at, moment=None):
    """给原生 /schedule/create 的载荷：固定间隔交给原生重复，其余一律换算成"多少秒之后"的单次。"""
    kind = rule_kind(rule)
    if kind == 'every':
        return {'every_seconds': rule['every_seconds']}
    seconds = int((_aware(fire_at) - _aware(moment)).total_seconds())
    return {'after_seconds': max(1, seconds)}


# ── 给人看的说法 ───────────────────────────────────────────────
def _local_text(moment, tz):
    from .local_time import face
    return face(_aware(moment), tz)


def _wall_text(at, tz):
    """A plan's `at` as written (a local wall time, or UTC when marked) on her clock face."""
    try:
        moment = datetime.fromisoformat(str(at).replace('Z', '+00:00'))
    except ValueError:
        return str(at)
    return _local_text(moment if moment.tzinfo else moment.replace(tzinfo=tz), tz)


def describe(rule, tz, her_tz=None):
    """A rule in words. `tz` is the zone its wall time is written in; a moment (`at_utc`) is worded on `her_tz`."""
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
        return '一次性：%s' % (_wall_text(rule['at'], (her_tz or tz) if rule.get('at_utc') else tz))
    clock = rule['clock']
    days = clock.get('weekdays')
    who = '每天' if not days else '每' + '、'.join(WEEKDAY_NAMES[d] for d in days)
    return '%s %s（本地钟点）' % (who, clock['time'])


def gap_words(minutes):
    """How one clock stands to another, in words that change only with a zone or a daylight-saving switch."""
    hours, rest = divmod(abs(minutes), 60)
    span = ' '.join(part for part in ('%d 小时' % hours if hours else '', '%d 分钟' % rest if rest else '') if part)
    return '%s %s' % ('快' if minutes > 0 else '慢', span)


def project(plan, her, moment=None):
    """把一条 plans 行投影成角色上下文里那一行：带人话、带她那个钟面上的下一次，不让她自己换算。"""
    moment = _aware(moment)
    zone = plan_zone(plan, her)                    # the zone the rule's wall time is written in
    tz, her_tz = zone['tz'], her['tz']
    # What she reads (her review 2026-10-14): the plan in words and the moment the program will fire it, to check one
    # against the other; the rule's own fields, versions and bookkeeping stay the program's.
    row = {'_id': plan['_id'], 'intent': plan.get('intent')}
    if zone['unreadable']:
        row['timezone_note'] = '这条计划存的时区这台机器读不到，按你的钟读（这一条没有 DST 规则）'
    try:
        row['description'] = describe(plan['rule'], tz, her_tz)
    except (ValueError, KeyError):
        row['description'] = '规则认不出来：可能是旧版本留下的记录'
        return row
    if plan.get('status') in ('CANCELLED', 'FIRED', 'SUSPENDED'):
        row['next_fire_at'] = plan.get('scheduled_at')
        row['why_no_next'] = {'CANCELLED': '已取消', 'FIRED': '已经到期过（一次性安排）',
                              'SUSPENDED': plan.get('last_outcome') or '已暂停'}[plan['status']]
        return row
    try:
        # The time set when it was armed (kept in step with the native scheduler), not recomputed: "N seconds
        # after" counted from now would move later at every read.
        stored = plan.get('next_fire_at')
        fire = (_aware(datetime.fromisoformat(str(stored).replace('Z', '+00:00'))) if stored
                else next_fire(plan['rule'], tz, moment))
    except ValueError as exc:
        row['next_fire_at'] = plan.get('scheduled_at')
        row['why_no_next'] = str(exc)
        return row
    row['next_fire_at'] = fire.isoformat(timespec='seconds')
    shifted = _shift_note(plan['rule'], fire, tz, her_tz)
    if shifted:
        row['dst_note'] = shifted
    gap = offset_minutes(tz, fire) - offset_minutes(her_tz, fire)       # zero unless the rule has its own wall zone
    if gap:
        row['clock_note'] = clock_note(gap)
    return row


def clock_note(gap):
    """A plan whose rule is written on another clock than hers (`gap`: its clock minus hers, in minutes)."""
    return '这条的钟点写在另一个钟面上，比你的钟%s；到点以 next_fire_at 为准' % gap_words(gap)


def moved_note(plan, her):
    """What an update that has just put a plan written on another clock onto hers tells her (None when it did not)."""
    name = (plan.get('last_update') or {}).get('from_timezone')
    if not name:
        return None
    tz = _load(name)
    if tz is None:
        return '这条原来写在另一个钟面上，现在按你的钟'
    fire = _aware(plan['next_fire_at'])
    gap = offset_minutes(tz, fire) - offset_minutes(her['tz'], fire)
    return '这条原来写在另一个钟面上%s，现在按你的钟' % ('（比你的钟%s）' % gap_words(gap) if gap else '')


BRIEF = ('intent', 'description', 'next_fire_at', 'clock_note')


def plan_brief(plan, her, moment=None):
    """`project` cut to what a view of another place's plan, or the plan that has just come due, shows her."""
    return {key: value for key, value in project(plan, her, moment).items() if key in BRIEF}


def _shift_note(rule, fire, tz, her_tz=None):
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
    return '规则里的 %s 那天不存在（拨快跳过），已顺延到 %s' % (asked, _local_text(fire, her_tz or tz))


def local_clock(zone, moment=None):
    """给角色的现场钟面：她换算"明天下午三点"要用。只有钟面和星期，不报时区名。"""
    moment = _aware(moment)
    tz = zone['tz']
    local = moment.astimezone(tz)
    from .local_time import face
    return {'now_local': face(local, tz, year=True), 'weekday': WEEKDAY_NAMES[local.weekday()]}


def line_stamp(zone, value):
    """When one stored line was said, on her clock face (local_time.face); '' when unknown."""
    if not value:
        return ''
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return ''
    from .local_time import face
    return face(_aware(moment), zone['tz'])
