"""Times a model reads are on her one clock (owner 2026-10-08; one clock in every conversation, ADR-106): stored
records keep UTC for the program, and everything handed to a model passes `for_model` first.

Only timestamp fields are converted — a key ending in `_at` (or `at`, `until`, `since`) whose value is a full ISO
date-time, or a datetime — never free text: a sentence the program writes with a time in it formats that time
itself (`face`). Every time reads the same: `10/14 14:28` on her clock, with the year in front
(`2025/9/27 14:00`) when it is another year or more than 90 days from the moment it is written. A written line stays
in her conversation for months, so whether the year may be left out is judged when it is written, and only a date
that is then near reads without one. `clock_from_program` always carries the year and the weekday, never a zone name.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from . import clock

FULL = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
KEYS = ('at', 'until', 'since')
NEAR = timedelta(days=90)              # a date this close to the moment it is written reads without its year


def is_time_key(key):
    key = str(key)
    return key in KEYS or key.endswith('_at') or key.endswith('_until')


def _moment(value):
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and FULL.match(value):
        try:
            moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)       # stored naive times are UTC


def face(moment, tz, now=None, year=False):
    """An aware moment on the clock face she reads: `10/14 14:28`, or `2025/9/27 14:00` when `year` is asked, when it
    is another year, or when it is more than 90 days from now."""
    local = moment.astimezone(tz)
    current = (now or clock.now()).astimezone(tz)
    shown = '%d/%d %02d:%02d' % (local.month, local.day, local.hour, local.minute)
    if year or local.year != current.year or abs(local - current) > NEAR:
        return '%d/%s' % (local.year, shown)
    return shown


def stamp(value, zone, now=None):
    """One time on the local clock face (`face`); the value as it was when it is no time."""
    moment = _moment(value)
    if moment is None:
        return value
    return face(moment, zone['tz'], now)


def for_model(node, zone, now=None):
    """A copy of a context block or tool result with every timestamp field on the local clock."""
    if isinstance(node, dict):
        return {key: (stamp(value, zone, now) if is_time_key(key) and _moment(value) is not None
                      else for_model(value, zone, now)) for key, value in node.items()}
    if isinstance(node, list):
        return [for_model(value, zone, now) for value in node]
    if isinstance(node, tuple):
        return tuple(for_model(value, zone, now) for value in node)
    return node


def her_zone(store):
    """Her one clock (schedule_rules.her_zone): the same in every conversation."""
    from .schedule_rules import her_zone as resolve
    return resolve(store.config)
