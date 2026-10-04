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
from .config import ago

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
        block['owner_last_message'] = ago(max(0.0, (moment - last).total_seconds() / 3600))
    return block


def heartbeat_rest_gate(model, policy, config, moment=None) -> bool:
    """True only when the persona chose heartbeat.skip_in_sleep and the local time is in her sleep window."""
    if not effective(model, 'heartbeat.skip_in_sleep', policy):
        return False
    zone, _ = persona_timezone(model, policy, config)
    local = (moment or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone)) if ZoneInfo else moment
    return in_window(local, effective(model, 'rhythm.sleep_window', policy))


def episode_dates(store, episode_ids, zone):
    """{episode id: local date} from the audited context preparation of each episode."""
    from zoneinfo import ZoneInfo
    out = {}
    for row in store.db.audit_events.find({'type': 'context.prepared', 'stream_id': {'$in': list(episode_ids)}},
                                          {'stream_id': 1, 'occurred_at': 1}):
        moment = datetime.fromisoformat(row['occurred_at'].replace('Z', '+00:00')).astimezone(ZoneInfo(zone))
        out[row['stream_id']] = moment.date().isoformat()
    return out


def selections(store, window_days, *, moment=None):
    """{memory id: [episode ids]} for memories actually selected into turns within the window."""
    from datetime import timedelta
    moment = moment or datetime.now(timezone.utc)
    since = (moment - timedelta(days=float(window_days or 7))).isoformat()
    out = {}
    for row in store.db.audit_events.find({'type': 'context.prepared', 'occurred_at': {'$gte': since}},
                                          {'stream_id': 1, 'payload.manifest.selected': 1}):
        for memory_id in ((row.get('payload') or {}).get('manifest') or {}).get('selected') or []:
            out.setdefault(memory_id, [])
            if row['stream_id'] not in out[memory_id]:
                out[memory_id].append(row['stream_id'])
    return out


def promotion_candidates(store, model, policy, *, limit=20):
    """Deterministic: units or monologues referenced by ≥ 2 different turns within promotion.window_days."""
    window = effective(model, 'promotion.window_days', policy) or effective(model, 'memory.promotion.window_days', policy) or 7
    picked = [(memory_id, episodes) for memory_id, episodes in selections(store, window).items() if len(episodes) >= 2]
    rows = {row['_id']: row for row in store.db.memory_units.find({'_id': {'$in': [m for m, _ in picked]}, 'status': 'active'},
                                                                 {'body_markdown': 1, 'kind': 1, 'scope_key': 1})}
    return [{'memory_id': m, 'kind': rows[m].get('kind'), 'excerpt': rows[m].get('body_markdown', '')[:300], 'episodes': e}
            for m, e in sorted(picked, key=lambda item: (-len(item[1]), item[0])) if m in rows][:limit]


def split_speech(text, marker='---split---', max_messages=1):
    """SPEAK → ≤ max_messages segments on lines equal to the marker; extra pieces stay in the last one.

    With max_messages == 1 the text is returned untouched (behaviour before ADR-009).
    """
    if int(max_messages or 1) <= 1:
        return [text]
    pieces = [part.strip('\n') for part in re.split(r'(?m)^\s*' + re.escape(marker) + r'\s*$', text)]
    pieces = [part for part in pieces if part.strip()]
    if not pieces:
        return [text]
    head, tail = pieces[:int(max_messages) - 1], pieces[int(max_messages) - 1:]
    return head + (['\n'.join(tail)] if tail else [])


def pacing(segments, start, chars_per_second=12, min_gap_s=1, max_gap_s=5):
    """not_before for each segment: previous not_before + clamp(len / cps, min_gap, max_gap)."""
    from datetime import timedelta
    out, moment = [], start
    for index, segment in enumerate(segments):
        if index:
            gap = min(float(max_gap_s), max(float(min_gap_s), len(segments[index - 1]) / float(chars_per_second or 12)))
            moment = moment + timedelta(seconds=gap)
        out.append(moment)
    return out


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
