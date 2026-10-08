"""Times a model reads are on the local clock (owner 2026-10-08): stored records keep UTC for the program, and
everything handed to a model passes `for_model` first.

Only timestamp fields are converted — a key ending in `_at` (or `at`, `until`, `since`) whose value is a full ISO
date-time, or a datetime — never free text: a sentence the program writes with a time in it formats that time
itself (`stamp`). The result reads `YYYY-MM-DD HH:MM` in the conversation's time zone, the same face as
`clock_from_program`, which names the zone.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

FULL = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
KEYS = ('at', 'until', 'since')


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


def stamp(value, zone):
    """One time on the local clock, `YYYY-MM-DD HH:MM`; the value as it was when it is no time."""
    moment = _moment(value)
    if moment is None:
        return value
    return moment.astimezone(zone['tz']).strftime('%Y-%m-%d %H:%M')


def for_model(node, zone):
    """A copy of a context block or tool result with every timestamp field on the local clock."""
    if isinstance(node, dict):
        return {key: (stamp(value, zone) if is_time_key(key) and _moment(value) is not None else for_model(value, zone))
                for key, value in node.items()}
    if isinstance(node, list):
        return [for_model(value, zone) for value in node]
    if isinstance(node, tuple):
        return tuple(for_model(value, zone) for value in node)
    return node


def zone_of(store, scene_id):
    """The time zone a conversation's times are read in (schedule_rules.scene_timezone)."""
    from .schedule_rules import scene_timezone
    scene = store.db.scenes.find_one({'_id': scene_id}) if scene_id else None
    return scene_timezone(store.config, scene or {'_id': scene_id})
