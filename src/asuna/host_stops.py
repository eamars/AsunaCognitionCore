"""When the Host was taken away from outside, she should not have to infer from a gap in
the logs whether she was away. A clean stop deletes the database lease (host_lease); a Host killed from outside
leaves its own lease behind. The next start finds it, records one row in `host_stops` — about when the old Host was
last alive (the lease's expiry less its length, within one renewal) and when the new one came up — and her home
turns for the next day carry it in words. Nothing about the process tree or who stopped it: only that it did not
stop by itself, and for how long nothing ran. A stop marked beforehand as a planned restart
(`python -m asuna.host_stops planned`, before a deploy kills the Host) is recorded as `planned` and not shown.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

SHOWN_HOURS = 24
WHAT = '宿主上次是被外部终止的（不是正常停下）'
# Looks in a group the relevance gate could not decide (her ask, 2026-10-14): the program's failure, never her 不理.
MISSED = '过去一天里，群里有该让你判断接不接话的时候，程序没判出来（出错了，不是你选的不理），那几句你没看到：%s'
NOTE = ('这段时间宿主没在运行：你没有收到、也没有处理任何东西。之后补进来的消息不代表你当时在场；'
        '这一条是程序按记录写的，不用回复，也不用为它做什么。')


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def record(store, alive_until, back_at=None, planned=False):
    """One stop that left the lease behind, found at startup: alive_until is the old Host's last known moment."""
    from .state import now
    back_at = back_at or now()
    row = {'_id': 'stop-' + uuid.uuid4().hex[:16], 'how': 'planned' if planned else 'killed', 'alive_until': _aware(alive_until).isoformat(),
           'back_at': back_at, 'scope_key': 'operator'}
    store.put('host_stops', row, stream=row['_id'])
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
    store.db.missed_looks.update_one({'_id': ep['_id']}, {'$set': {'scene_id': ep['scene_id'], 'at': now(),
                                                                    'cause': cause}}, upsert=True)


def missed_looks(store, persona, since):
    """'某群 3 次、某群 1 次' for the gate's failed looks since then, or None."""
    old = (datetime.fromisoformat(since) - timedelta(days=MISSED_KEPT_DAYS)).isoformat()
    store.db.missed_looks.delete_many({'at': {'$lt': old}})
    counts, causes = {}, {}
    for row in store.db.missed_looks.find({'at': {'$gte': since}}, {'scene_id': 1, 'cause': 1}):
        counts[row['scene_id']] = counts.get(row['scene_id'], 0) + 1
        why = causes.setdefault(row['scene_id'], {})
        cause = row.get('cause') or 'error'
        why[cause] = why.get(cause, 0) + 1
    if not counts:
        return None
    from .people import People
    people = People(store, persona)
    return '、'.join('%s %d 次（%s）' % (people.scene_title(store.db.scenes.find_one({'_id': scene_id}) or {'_id': scene_id}), n,
                                       '，'.join('%s %d' % (MISSED_CAUSES.get(c, MISSED_CAUSES['error']), k)
                                                for c, k in sorted(causes[scene_id].items(), key=lambda kv: -kv[1])))
                    for scene_id, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def block(store, zone, moment=None, persona=None):
    """host_from_program for a home turn: the latest external termination of the last day and the gate's failed
    looks of the last day, or None."""
    from .schedule_rules import line_stamp
    moment = moment or datetime.now(timezone.utc)
    since = (moment - timedelta(hours=SHOWN_HOURS)).isoformat()
    out = {}
    row = store.db.host_stops.find_one({'how': 'killed', 'back_at': {'$gte': since}}, sort=[('back_at', -1)])
    if row:
        gone = (datetime.fromisoformat(row['back_at']) - datetime.fromisoformat(row['alive_until'])).total_seconds()
        out = {'what': WHAT,
               'when': '最后确认还在运行约是 %s，重新起来是 %s，中间约 %s宿主没有运行'
                       % (line_stamp(zone, row['alive_until']), line_stamp(zone, row['back_at']), _span(gone)),
               'note': NOTE}
    missed = missed_looks(store, persona, since)
    if missed:
        out['missed_looks'] = MISSED % missed
    return out or None


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
