"""The core's one clock: the time now, in UTC, never the same twice in this process.

The system clock can move in steps of a millisecond or more (Windows), so two writes in one step would carry the same
time, and whatever decides by the latest or the oldest would then decide by a tie. Here a reading that is not later
than the last one given out is the last one plus a microsecond. Every stamp and every "now" in the worker reads this
clock; a decision that must hold across processes, or among rows stamped with one moment, needs an order of its own.
Stdlib only."""
import threading
from datetime import datetime, timedelta, timezone

STEP = timedelta(microseconds=1)
_lock = threading.Lock()
_last = None


def now():
    """An aware UTC datetime later than every one this process was given before."""
    global _last
    with _lock:
        value = datetime.now(timezone.utc)
        if _last is not None and value <= _last:
            value = _last + STEP
        _last = value
    return value


def stamp():
    """now() as the ISO text records keep, always with its microseconds, so that text order is time order."""
    return now().isoformat(timespec='microseconds')
