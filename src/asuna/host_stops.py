"""When the Host was taken away from outside (小满's ask, 2026-10-08): she should not have to infer from a gap in
the logs whether she was away. A clean stop deletes the database lease (host_lease); a Host killed from outside
leaves its own lease behind. The next start finds it, records one row in `host_stops` — about when the old Host was
last alive (the lease's expiry less its length, within one renewal) and when the new one came up — and her home
turns for the next day carry it in words. Nothing about the process tree or who stopped it: only that it did not
stop by itself, and for how long nothing ran.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

SHOWN_HOURS = 24
WHAT = '宿主上次是被外部终止的（不是正常停下）'
NOTE = ('这段时间宿主没在运行：你没有收到、也没有处理任何东西。之后补进来的消息不代表你当时在场；'
        '这一条是程序按记录写的，不用回复，也不用为它做什么。')


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def record(store, alive_until, back_at=None):
    """One external termination, found at startup: alive_until is the old Host's last known moment."""
    from .state import now
    back_at = back_at or now()
    row = {'_id': 'stop-' + uuid.uuid4().hex[:16], 'how': 'killed', 'alive_until': _aware(alive_until).isoformat(),
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


def block(store, zone, moment=None):
    """host_from_program for a home turn: the latest external termination of the last day, or None."""
    from .schedule_rules import line_stamp
    moment = moment or datetime.now(timezone.utc)
    since = (moment - timedelta(hours=SHOWN_HOURS)).isoformat()
    row = store.db.host_stops.find_one({'how': 'killed', 'back_at': {'$gte': since}}, sort=[('back_at', -1)])
    if not row:
        return None
    gone = (datetime.fromisoformat(row['back_at']) - datetime.fromisoformat(row['alive_until'])).total_seconds()
    return {'what': WHAT,
            'when': '最后确认还在运行约是 %s，重新起来是 %s，中间约 %s宿主没有运行'
                    % (line_stamp(zone, row['alive_until']), line_stamp(zone, row['back_at']), _span(gone)),
            'note': NOTE}
