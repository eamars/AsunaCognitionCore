"""What the segments of an accepted message look like, counted by shape and never by content (ADR-103).

The platform event is not stored anywhere once its line is delivered, so what NapCat sends for a face, a dice, a
sticker or a type nobody has named yet cannot be read back. This counts it, with no text and no ids: for each
segment of an accepted message except `text`, `at` and `reply`, by UTC day, the segment's type, the sorted keys of its
`data` (and of `data.raw` when that is an object), and the value of the few keys whose value is a small number the
platform picks (`VALUE_KEYS`: a dice result, a chain count, a face type), only when it is one to four digits.

Kept in `<data>/media/shapes.json` across restarts, at most SHAPES_PER_DAY shapes a day and DAYS_KEPT days; the last
seven days are in `health.json` (`media_shapes`). Failures here never hold, drop or delay a line.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

SKIPPED = frozenset({"text", "at", "reply"})        # these carry words and people, and nothing to learn
VALUE_KEYS = frozenset({"result", "resultId", "chainCount", "faceType"})
VALUE = re.compile(r"^[0-9]{1,4}$")
TYPE = re.compile(r"^[a-z0-9_-]{1,16}$")
KEY = re.compile(r"^[A-Za-z0-9_]{1,24}$")
MAX_KEYS = 40
SHAPES_PER_DAY = 200
OVERFLOW = "_overflow"
DAYS_KEPT = 7
SAVE_EVERY = 60.0
SHOWN = 30                                           # shapes in `health.json`, the most seen first


def _keys(node):
    """The sorted, bounded key names of an object: names that are not plain identifiers are left out."""
    if not isinstance(node, dict):
        return []
    return sorted(key for key in node if isinstance(key, str) and KEY.fullmatch(key))[:MAX_KEYS]


def _values(node):
    """`key=value` for the value keys of an object whose value is one to four digits."""
    if not isinstance(node, dict):
        return []
    found = []
    for key in sorted(VALUE_KEYS):
        value = node.get(key)
        text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
        if isinstance(text, str) and VALUE.fullmatch(text):
            found.append("%s=%s" % (key, text))
    return found


def shape_of(segment):
    """One segment's shape as text, or None when it is not counted."""
    if not isinstance(segment, dict):
        return None
    kind = segment.get("type")
    if not isinstance(kind, str) or kind in SKIPPED:
        return None
    kind = kind if TYPE.fullmatch(kind) else "other"
    data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else None
    parts = [kind, "data:" + ",".join(_keys(data))]
    if raw is not None:
        parts.append("raw:" + ",".join(_keys(raw)))
    values = _values(data) + ["raw." + found for found in _values(raw)]
    if values:
        parts.append("values:" + ",".join(values))
    return "|".join(parts)


class Shapes:
    """The counts of segment shapes by UTC day; kept across restarts."""

    def __init__(self, data_dir, clock=time.time):
        self.path = os.path.join(data_dir, "media", "shapes.json")
        self.clock = clock
        self._lock = threading.Lock()
        self._saved = 0.0
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                self.days = {str(day): {str(shape): int(count) for shape, count in counts.items()}
                             for day, counts in (json.load(handle).get("days") or {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            self.days = {}

    def _day(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")

    def add_event(self, event):
        """Count the segments of one accepted message event. Never raises."""
        try:
            message = event.get("message") if isinstance(event, dict) else None
            shapes = [shape for shape in map(shape_of, message if isinstance(message, list) else []) if shape]
            if not shapes:
                return
            with self._lock:
                day = self.days.setdefault(self._day(), {})
                for shape in shapes:
                    if shape not in day and len(day) >= SHAPES_PER_DAY + (OVERFLOW in day):
                        shape = OVERFLOW
                    day[shape] = day.get(shape, 0) + 1
                for old in sorted(self.days)[:-DAYS_KEPT]:
                    del self.days[old]
                due = self.clock() - self._saved >= SAVE_EVERY
            if due:
                self.save()
        except Exception:
            return

    def save(self):
        """Write the counts; a failure keeps them in memory."""
        try:
            with self._lock:
                self._saved = self.clock()
                body = json.dumps({"version": 1, "days": self.days}, sort_keys=True)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(body + "\n")
            os.replace(tmp, self.path)
        except OSError:
            return

    def summary(self):
        with self._lock:
            week = {}
            for day in sorted(self.days)[-DAYS_KEPT:]:
                for shape, count in self.days[day].items():
                    week[shape] = week.get(shape, 0) + count
        top = sorted(week.items(), key=lambda item: (-item[1], item[0]))
        return {"last_7_days": dict(top[:SHOWN]), "shapes": len(week)}
