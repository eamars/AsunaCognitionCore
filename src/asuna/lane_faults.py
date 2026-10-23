"""Faults of the channel lanes, counted by signature and hour (ADR-095 §5.6, step 1).

A signature is what failed, never the message: the channel, the lane (`inbound`, `chat`, `bulk`, `receipts`, and
the Host's own as later steps add them), the stage, and the error class. Lane, stage and error are names, not words:
only CLASS_CHARS, so no text of a line or of an answer can come in, and one fault class stays one signature. An
adapter keeps its counts and posts them every few minutes (`POST /v1/channels/<id>/faults`, `receive`); the Host's own
faults are counted where they happen (`record`). Each is one document per channel, signature and hour in
`lane_faults`, its count raised with `$inc`; `hour_at` is the hour's start, and the collection keeps
KEEP_DAYS of them (a TTL index, state.py). Counts are at least once: a post re-sent after its answer was lost counts
again in the same hour. Nothing here interprets them: telling a persistent fault from a burst is a later step's
(§5.6).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne

LANES = ('inbound', 'chat', 'bulk', 'receipts', 'transcriber', 'watchdog')
CLASS_CHARS = re.compile(r'[A-Za-z0-9_.:-]{1,80}')
MAX_ROWS = 200
MAX_COUNT = 100000
HOUR_FORMAT = '%Y-%m-%dT%H'
KEEP_DAYS = 30
FUTURE = timedelta(hours=1)


def hour_of(moment=None):
    """The UTC hour a fault is counted in, as `YYYY-MM-DDTHH`."""
    return (moment or datetime.now(timezone.utc)).strftime(HOUR_FORMAT)


def _name(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not CLASS_CHARS.fullmatch(value):
        raise ValueError('FAULTS_FIELD_INVALID: %s 是名字，不是文字：1–80 个 A–Z a–z 0–9 _ . : -' % field)
    return value


def _hour(row, now):
    value = row.get('hour')
    try:
        start = datetime.strptime(value, HOUR_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ValueError('FAULTS_HOUR_INVALID: hour 是 UTC 的 YYYY-MM-DDTHH') from None
    if start.strftime(HOUR_FORMAT) != value or not now - timedelta(days=KEEP_DAYS) <= start <= now + FUTURE:
        raise ValueError('FAULTS_HOUR_INVALID: hour 是最近 %d 天里的一个 UTC 小时，写成 YYYY-MM-DDTHH' % KEEP_DAYS)
    return value, start


def receive(store, channel_id, body):
    """An adapter's counts: {'counts': [{'lane', 'stage', 'error', 'hour', 'count'}]}, at most MAX_ROWS rows; all of
    them or none are counted."""
    rows = body.get('counts') if isinstance(body, dict) else None
    if set(body or {}) - {'counts'} or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError('FAULTS_INVALID: counts 要是 1–%d 条的列表' % MAX_ROWS)
    now = datetime.now(timezone.utc)
    checked = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'lane', 'stage', 'error', 'hour', 'count'}:
            raise ValueError('FAULTS_ROW_INVALID: 每条只有 lane、stage、error、hour、count')
        lane = _name(row, 'lane')
        if lane not in LANES:
            raise ValueError('FAULTS_LANE_UNKNOWN: lane 是 %s 之一' % '、'.join(LANES))
        count = row.get('count')
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
            raise ValueError('FAULTS_COUNT_INVALID: count 是 1–%d 的整数' % MAX_COUNT)
        hour, start = _hour(row, now)
        checked.append((lane, _name(row, 'stage'), _name(row, 'error'), hour, start, count))
    store.db.lane_faults.bulk_write([_upsert(channel_id, *row, now) for row in checked], ordered=False)
    return {'status': 'recorded', 'rows': len(checked)}


def record(store, channel_id, lane, stage, error, moment=None, count=1):
    """Count `count` faults of one signature in its hour (the current one unless `moment` is given)."""
    now = datetime.now(timezone.utc)
    start = (moment or now).replace(minute=0, second=0, microsecond=0)
    row = (lane, stage, error, start.strftime(HOUR_FORMAT), start, int(count))
    for name in row[:3]:
        if not CLASS_CHARS.fullmatch(name):
            raise ValueError('FAULTS_FIELD_INVALID: %r is not a class name' % name)
    store.db.lane_faults.bulk_write([_upsert(channel_id, *row, now)])


def _upsert(channel_id, lane, stage, error, hour, start, count, now):
    return UpdateOne(
        {'_id': '|'.join((channel_id, lane, stage, error, hour))},
        {'$inc': {'count': count}, '$set': {'last_posted_at': now},
         '$setOnInsert': {'schema_version': 1, 'channel_id': channel_id, 'lane': lane, 'stage': stage, 'error': error,
                          'hour': hour, 'hour_at': start, 'first_posted_at': now}},
        upsert=True)
