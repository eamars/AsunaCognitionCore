"""When the Host was taken away from outside, she should not have to infer from a gap in
the logs whether she was away. A clean stop deletes the database lease (host_lease); a Host killed from outside
leaves its own lease behind. The next start finds it, records one row in `host_stops` — about when the old Host was
last alive (the lease's expiry less its length, within one renewal) and when the new one came up — and her home
turns for the next day carry it in words. Nothing about the process tree or who stopped it: only that it did not
stop by itself, and for how long nothing ran. A stop marked beforehand as a planned restart
(`python -m asuna.host_stops planned`, before a deploy kills the Host) is recorded as `planned` and not shown. A Host
that exited on its own is recorded as `crashed` with its exit code: the supervisor writes that exit to its restart
record before it starts the next Host (restarts.last), and the next start reads it.

A worker that was down while the Host ran on (ADR-101) is one `worker_down` row: the Host plugin keeps the open span
(<data>/worker-down.json) from its first failed start or exit until a start completes, then hands it over
(`worker_down`). While a span is open, a lease left behind is part of that outage: no second row. Each row is one
outage. A stop stays in her home turns until a turn that showed it has committed (`shown_at`), and at least a day.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from .records import scenes as scene_records
from .records.view import View, is_text, pinned
from .store.words import And, AnyOf, IsNull, Or, Range, Set
from . import clock

SHOWN_HOURS = 24
LISTED = 3                    # stops listed at most; the count says how many there were
OUTAGES = ('killed', 'crashed', 'worker_down')      # the rows that are outages (planned ones are not)
WHAT = '宿主上次是被外部终止的（不是正常停下）'
CRASHED = '宿主上次是自己崩掉退出的（不是被谁停的，也不是正常停下）'
WORKER_DOWN = '宿主一直在运行，但替你处理一切的那部分程序停了，没有马上起来'
# A cause is a kind and a name (ADR-101's closed list), never an error's text: that carries a host address.
CAUSE = re.compile(r'^(start_failed:[A-Za-z][A-Za-z0-9_.]{0,59}|exited:(-?\d{1,12}|none)|unknown)$')
CAUSE_WORDS = {'start_failed': '启动时出错（%s），程序隔一阵自己重试，第 %d 次起来了',
               'exited': '它自己退出了（%s），程序把它重新拉起来',
               'unknown': '为什么停的没记下来'}
COUNT = '过去一天里停了 %d 次'
NOT_LISTED = '更早的 %d 次没有列出'
UNREADABLE = '其中 %d 次的记录读坏了，说不清是什么、在什么时候'
INSIDE = '这段时间里宿主也停过 %d 次'
SINCE_UNKNOWN = '这一段从什么时候开始不知道（记录读坏了），重新起来是 %s'
# Looks in a group the relevance gate could not decide (her ask, 2026-10-14): the program's failure, never her 不理.
MISSED = '过去一天里，群里有该让你判断接不接话的时候，程序没判出来（出错了，不是你选的不理），那几句你没看到：%s'
NOTE = ('这些时段里你没有在运行：你没有收到、也没有处理任何东西。之后补进来的消息不代表你当时在场；'
        '这一条是程序按记录写的，不用回复，也不用为它做什么。')


# ── the owner of `host_stops` and `missed_looks` ──
# Read and written only through these: a stop or a missed look as stored. None follows the store's rule (ADR-104
# section 4): an id given None, or a value not of its kind, finds nothing without a read; a time bound given None
# finds nothing.
COLLECTION, MISSED_LOOKS = 'host_stops', 'missed_looks'


def get(store, stop_id):
    """The stop with this id, or None."""
    return store.collection(COLLECTION).get(stop_id) if is_text(stop_id) else None


def unshown(store, hows, since):
    """View: the stops of these kinds that came back since `since` (ISO text), or that no committed turn showed yet
    (`shown_at` null), by when they came back."""
    if not is_text(since):
        return View(store, COLLECTION, None)
    where = And({'how': AnyOf(list(hows))}, Or({'back_at': Range(gte=since)}, {'shown_at': IsNull()}))
    return View(store, COLLECTION, where, (('back_at', 1),))


def last_back(store, how, since):
    """The newest stop of this kind back at or after `since` (ISO text), or None."""
    where = {'how': how, 'back_at': Range(gte=since)} if is_text(how) and is_text(since) else None
    return View(store, COLLECTION, where, (('back_at', 1),)).first(newest_first=True)


def mark_shown(store, ids, moment):
    """Stamp `shown_at` on each of these stops where it is still null or missing."""
    ids = [stop_id for stop_id in ids if is_text(stop_id)]
    if ids:
        store.collection(COLLECTION).update(pinned({'_id': AnyOf(ids)}, {'shown_at': (None, is_text)}),
                                            Set({'shown_at': moment}), many=True)


def save(store, row, **kwargs):
    """The revisioned write of a stop (`Store.put`: `stream`)."""
    return store.put(COLLECTION, row, **kwargs)


def note_missed(store, turn_id, scene_id, at, cause):
    """One look the gate could not decide (by its turn's id, written again when it comes again)."""
    if is_text(turn_id):
        store.collection(MISSED_LOOKS).update({'_id': turn_id}, Set({'scene_id': scene_id, 'at': at, 'cause': cause}),
                                              create=True)


def forget_missed(store, before):
    """The missed looks from before `before` (ISO text) go."""
    if is_text(before):
        store.collection(MISSED_LOOKS).delete({'at': Range(lt=before)}, many=True)


def missed(store, since):
    """View: the missed looks since `since` (ISO text)."""
    return View(store, MISSED_LOOKS, {'at': Range(gte=since)} if is_text(since) else None)


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def crash_code(alive_until, root=None):
    """The exit code of a Host that exited on its own, when the supervisor's record of this start says so: a restart
    nobody asked for, not back yet, that went down within one planned-stop window of the lease's last renewal."""
    from .host_lease import PLANNED_SECONDS
    from .restarts import last
    record = last(root) or {}
    code = record.get('exit_code')
    if record.get('asked') != 'nobody' or record.get('back_at') or not isinstance(code, int) or not record.get('down_at'):
        return None
    down = datetime.fromisoformat(str(record['down_at']).replace('Z', '+00:00'))
    return code if abs((down - _aware(alive_until)).total_seconds()) <= PLANNED_SECONDS else None


def record(store, alive_until, back_at=None, planned=False, exit_code=None, by=None):
    """One stop that left the lease behind, found at startup: alive_until is the old Host's last known moment. A
    planned one keeps who marked it (`by`, None when the mark did not say)."""
    from .state import now
    back_at = back_at or now()
    how = 'planned' if planned else 'crashed' if exit_code is not None else 'killed'
    row = {'_id': 'stop-' + uuid.uuid4().hex[:16], 'how': how, 'alive_until': _aware(alive_until).isoformat(),
           'back_at': back_at, 'scope_key': 'operator', 'shown_at': None,
           **({'exit_code': exit_code} if how == 'crashed' else {}), **({'by': by} if how == 'planned' else {})}
    save(store, row, stream=row['_id'])
    return row


SPAN_FILE = 'worker-down.json'
SPAN_BYTES = 65536


def open_span(root=None):
    """The Host plugin's open span (outage.js), read from the data folder and never written here: a dict, or None when
    there is none or it cannot be read. A file that is there but is not a span is a span whose start is not known, as
    the plugin reads it."""
    import json
    from pathlib import Path
    from .config import DATA
    try:
        with open(Path(root or DATA) / SPAN_FILE, 'rb') as f:
            raw = f.read(SPAN_BYTES + 1)
    except OSError:
        return None
    try:
        value = json.loads(raw.decode('utf-8')) if len(raw) <= SPAN_BYTES else None
    except ValueError:
        value = None
    return value if isinstance(value, dict) and isinstance(value.get('cause'), str) else {'since': None, 'cause': 'unknown'}


def left_behind(store, lease, down=None):
    """A start found the lease the last Host left behind: record the stop, or, while the plugin's span is open
    (`down`), fold an unplanned one into that same outage (ADR-101) and write nothing. True when it was folded. A
    planned stop is recorded either way: it is not an outage, and the restart block names who marked it."""
    if down and not lease.planned:
        return True
    record(store, lease.left_behind, planned=lease.planned, by=lease.planned_by,
           exit_code=None if lease.planned else crash_code(lease.left_behind))
    return False


def span_of(value):
    """An open span as the Host plugin hands it over, checked: {since (ISO or None), cause (the closed list, else
    unknown), tries (at least 1), inside (Host stops folded into it), opened (ISO, when since is not known)}."""
    value = value if isinstance(value, dict) else {}
    def moment(text):
        try:
            return _aware(datetime.fromisoformat(str(text).replace('Z', '+00:00'))).isoformat()
        except ValueError:
            return None
    def count(key, least):
        number = value.get(key)
        return max(least, min(int(number), 100000)) if isinstance(number, int) and not isinstance(number, bool) else least
    cause = str(value.get('cause') or '')
    return {'since': moment(value['since']) if value.get('since') else None,
            'cause': cause if CAUSE.match(cause) else 'unknown', 'tries': count('tries', 1),
            'inside': count('inside', 0), 'opened': moment(value['opened']) if value.get('opened') else None}


def worker_down(store, value, back_at=None):
    """The span a completed start hands over (ADR-101): one `worker_down` row, its id from the span (its `since`, or
    when that is not known the moment the span was opened), so handing the same span over again writes no second
    row. Returns the row."""
    from .state import now
    span = span_of(value)
    key = span['since'] or 'unknown-' + (span['opened'] or 'none')
    row_id = 'down-' + re.sub(r'[^0-9A-Za-z]', '', key)[:40]
    found = get(store, row_id)
    if found:
        return found
    row = {'_id': row_id, 'how': 'worker_down', 'alive_until': span['since'], 'back_at': back_at or now(),
           'cause': span['cause'], 'tries': span['tries'], 'inside': span['inside'], 'scope_key': 'operator',
           'shown_at': None}
    save(store, row, stream=row_id)
    return row


def _span(seconds):
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return '%d 分钟' % minutes
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return '%d 小时' % hours + (' %d 分钟' % minutes if minutes else '')
    return '%d 天' % round(hours / 24)


MISSED_KEPT_DAYS = 7
# Why a look was not decided, in words (her ask, 2026-10-15): every one is the program's, never her choice.
MISSED_CAUSES = {'clash': '撞车（同一段对话同时被两处打开）', 'timeout': '等太久', 'unanswered': '模型没按 接话／不理 答',
                 'cut': '模型没答完', 'error': '程序出错'}


def missed_cause(error=None, finish_reason=None, unanswered=False):
    """The cause code of a look the gate could not decide."""
    text = str(error or '')
    if 'already owned' in text or 'SessionAlreadyOwned' in text:
        return 'clash'
    if 'TIMEOUT' in text.upper() or isinstance(error, TimeoutError):
        return 'timeout'
    if unanswered:
        return 'unanswered'
    return 'cut' if finish_reason and not error else 'error'


def missed_look(store, ep, cause='error'):
    """One look the gate could not decide, in its own small collection (the home turn counts them)."""
    from .state import now
    note_missed(store, ep['_id'], ep['scene_id'], now(), cause)


def missed_looks(store, persona, since):
    """'某群 3 次、某群 1 次' for the gate's failed looks since then, or None."""
    old = (datetime.fromisoformat(since) - timedelta(days=MISSED_KEPT_DAYS)).isoformat()
    forget_missed(store, old)
    counts, causes = {}, {}
    for row in missed(store, since).each(fields=['scene_id', 'cause']):
        counts[row['scene_id']] = counts.get(row['scene_id'], 0) + 1
        why = causes.setdefault(row['scene_id'], {})
        cause = row.get('cause') or 'error'
        why[cause] = why.get(cause, 0) + 1
    if not counts:
        return None
    from .people import People
    people = People(store, persona)
    return '、'.join('%s %d 次（%s）' % (people.scene_title(scene_records.get(store, scene_id) or {'_id': scene_id}), n,
                                       '，'.join('%s %d' % (MISSED_CAUSES.get(c, MISSED_CAUSES['error']), k)
                                                for c, k in sorted(causes[scene_id].items(), key=lambda kv: -kv[1])))
                    for scene_id, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def listed(store, moment=None):
    """The outages her home turn shows: each that came back within the last day, and each not yet shown in a turn
    that committed (`shown_at` None, however old), newest first. Rows from before ADR-101 carry no `shown_at` and keep
    the day alone."""
    moment = moment or clock.now()
    since = (moment - timedelta(hours=SHOWN_HOURS)).isoformat()
    return unshown(store, OUTAGES, since).rows(newest_first=True)


def cause_words(row):
    """A worker_down row's cause in words, by its kind (the part before `:`)."""
    kind, _, name = str(row.get('cause') or 'unknown').partition(':')
    if kind == 'start_failed':
        return CAUSE_WORDS[kind] % (name, int(row.get('tries') or 1) + 1)
    if kind == 'exited':
        said = CAUSE_WORDS[kind] % ('没有退出码' if name == 'none' else '退出码 ' + name)
        tries = int(row.get('tries') or 1)
        return said + ('，之后又有 %d 次没起来' % (tries - 1) if tries > 1 else '')
    return CAUSE_WORDS['unknown']


EARLIER = '再往前一次'           # an older stop of the list: 「上次」 is only the newest (her reading, 10-27)


def stop_words(row, zone, newest=True):
    """One outage in words, what and when; only the newest of a list is 「上次」, an older one 「再往前一次」."""
    from .schedule_rules import line_stamp
    back = line_stamp(zone, row['back_at'])
    if row['how'] == 'worker_down':
        what = WORKER_DOWN + '：' + cause_words(row)
        if row.get('inside'):
            what += '；' + INSIDE % row['inside']
        if not row.get('alive_until'):
            return {'what': what, 'when': SINCE_UNKNOWN % back}
    else:
        what = CRASHED if row['how'] == 'crashed' else WHAT
        if not newest:
            what = what.replace('上次', EARLIER, 1)
    gone = (datetime.fromisoformat(row['back_at']) - datetime.fromisoformat(row['alive_until'])).total_seconds()
    who = '你' if row['how'] == 'worker_down' else '宿主'         # the Host ran on while her worker was down
    if gone < 0:                        # the clock moved between the two moments: how long is not known
        return {'what': what, 'when': '最后确认还在运行约是 %s，重新起来是 %s，中间多久不知道（时钟对不上）'
                % (line_stamp(zone, row['alive_until']), back)}
    return {'what': what, 'when': '最后确认还在运行约是 %s，重新起来是 %s，中间约 %s%s没有运行'
            % (line_stamp(zone, row['alive_until']), back, _span(gone), who)}


def block(store, zone, moment=None, persona=None, rows=None):
    """host_from_program for a home turn: the outages of the last day and those not yet shown (`listed`; killed from
    outside, crashed, or her worker down while the Host ran on), newest first, at most LISTED with how many there
    were, and the gate's failed looks of the last day, or None. `rows`: the outages already listed for this turn."""
    moment = moment or clock.now()
    since = (moment - timedelta(hours=SHOWN_HOURS)).isoformat()
    rows = listed(store, moment) if rows is None else rows
    out = {}
    if rows:
        stops, unreadable = [], 0
        for i, row in enumerate(rows[:LISTED]):
            try:
                stops.append(stop_words(row, zone, i == 0))
            except Exception:           # noqa: BLE001 one broken row is counted, never takes her home turn with it
                unreadable += 1
        out = {'count': COUNT % len(rows), 'stops': stops, 'note': NOTE}
        if unreadable:
            out['unreadable'] = UNREADABLE % unreadable
        if len(rows) > LISTED:
            out['not_listed'] = NOT_LISTED % (len(rows) - LISTED)
    missed = missed_looks(store, persona, since)
    if missed:
        out['missed_looks'] = MISSED % missed
    return out or None


def shown(store, ids, moment=None):
    """A turn that showed these outages committed: each is stamped `shown_at` once. The stamp says only that the stop
    was rendered in front of her in a committed turn, never that she took it in (ADR-101)."""
    from .state import now
    if ids:
        mark_shown(store, ids, moment or now())


def main(argv=None):
    """`python -m asuna.host_stops planned [--by NAME]`: mark the running Host's coming stop as a planned restart."""
    import argparse
    from .config import load
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('action', choices=['planned'])
    parser.add_argument('--by', default='developer')
    args = parser.parse_args(argv)
    from .host_lease import mark_planned
    marked = mark_planned(load(), args.by)
    print('marked' if marked else 'HOST_NOT_RUNNING: 没有正在运行的宿主持有租约；不用标记')
    return 0 if marked else 1


if __name__ == '__main__':
    raise SystemExit(main())
