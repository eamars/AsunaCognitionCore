"""Rhythm block and recent-phrasing hint (ADR-009 §10.1, §11.2).

Both are deterministic inputs to DECIDE, never gates: a reply is never held back
by the program because of a sleep window, and repeated phrasing is pointed out,
not forbidden. Public sessions get no rhythm block unless ``rhythm.public_clock``
is set, because local time and habits reveal the owner's time zone and routine.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re

from .persona_model import effective, timezone as persona_timezone
from . import visibility

try:
    from zoneinfo import ZoneInfo
except Exception:                                   # pragma: no cover
    ZoneInfo = None


def in_window(local: datetime, window: str | None) -> bool:
    """HH:MM-HH:MM, including windows that cross midnight; empty → False."""
    if not window:
        return False
    match = re.fullmatch(r'([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)', window)
    if not match:
        raise ValueError('RHYTHM_SLEEP_WINDOW_INVALID')
    start = int(match[1]) * 60 + int(match[2])
    end = int(match[3]) * 60 + int(match[4])
    minute = local.hour * 60 + local.minute
    return start <= minute < end if start <= end else (minute >= start or minute < end)


def rhythm_block(store, model, policy, cls, *, moment=None, owner_last_at=None):
    moment = moment or datetime.now(timezone.utc)
    zone, source = persona_timezone(model, policy, store.config)
    local = moment.astimezone(ZoneInfo(zone)) if ZoneInfo else moment
    if cls != visibility.OWNER_PRIVATE:
        if not effective(model, 'rhythm.public_clock', policy):
            return None
        return {'local_time': local.isoformat(timespec='minutes')}
    block = {'local_time': local.isoformat(timespec='minutes'), 'timezone': zone,
             'in_sleep_window': in_window(local, effective(model, 'rhythm.sleep_window', policy))}
    if source == 'unset':
        block['note'] = '未设置时区，以 UTC 显示'
    if owner_last_at:
        last = datetime.fromisoformat(str(owner_last_at).replace('Z', '+00:00'))
        block['since_owner_message_min'] = max(0, int((moment - last).total_seconds() // 60))
    return block


def _grams(text: str):
    """4-grams: CJK by character, other scripts by word."""
    tokens = []
    for piece in re.findall(r'[㐀-鿿]|[A-Za-z0-9_]+', text):
        tokens.append(piece.lower())
    return [''.join(tokens[i:i + 4]) if all(len(t) == 1 for t in tokens[i:i + 4]) else ' '.join(tokens[i:i + 4])
            for i in range(len(tokens) - 3)]


def recent_phrasing(texts, *, minimum=3, limit=5):
    """4-grams that appear ≥ ``minimum`` times across the given own messages; ≤ ``limit`` items."""
    counts = Counter()
    for text in texts:
        counts.update(set(_grams(text or '')))
    repeated = [(gram, n) for gram, n in counts.items() if n >= minimum]
    repeated.sort(key=lambda item: (-item[1], item[0]))
    return [gram for gram, _ in repeated[:limit]]
