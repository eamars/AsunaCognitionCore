"""Lines caught up after a gap: a channel adapter fetched them from the platform's history once it was back.

The adapter marks such a line `raw.asuna_catchup` (channels.kept_raw keeps it). It was said at its
`occurred_at`, not when it arrived, so everything that asks "when was this said" reads `said_at`, and the line
she reads carries its original time with 补读. An @ or a reply to her in a line older than STALE_SECONDS no
longer wakes her by itself: it asks her through the relevance gate (`catchup_mention`, attend.GATED).
"""
from __future__ import annotations

from datetime import datetime, timezone

CATCHUP_KEY = 'asuna_catchup'
STALE_SECONDS = 300
CAUGHT_UP_WORD = '补读'


def mark(raw):
    """The adapter's marker as the host keeps it, or None."""
    block = raw.get(CATCHUP_KEY) if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        return None
    reason = block.get('reason') if block.get('reason') in ('startup', 'reconnect') else 'startup'
    fetched = block.get('fetched_at') if isinstance(block.get('fetched_at'), str) else ''
    return {'reason': reason, 'fetched_at': fetched[:40]}


def is_caught_up(row):
    return bool(((row.get('event') or {}).get('raw') or {}).get(CATCHUP_KEY))


def said_at(row):
    """When a stored line was said: a caught-up line's original time, any other line's arrival."""
    if is_caught_up(row) and (row.get('occurred_at') or (row.get('event') or {}).get('occurred_at')):
        return row.get('occurred_at') or row['event']['occurred_at']
    return row.get('received_at') or row.get('receipt_at')


def stale(raw, occurred_at, now=None):
    """Whether an incoming line is caught up and older than STALE_SECONDS."""
    if not mark(raw) or not isinstance(occurred_at, str):
        return False
    try:
        moment = datetime.fromisoformat(occurred_at.replace('Z', '+00:00'))
    except ValueError:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - moment).total_seconds() > STALE_SECONDS
