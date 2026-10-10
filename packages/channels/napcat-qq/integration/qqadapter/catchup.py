"""Catch-up after a gap: the messages she missed while this adapter or its event socket was down.

QQ does not replay events, and NapCat has no catch-up endpoint.  What it has is history:
`get_group_msg_history` / `get_friend_msg_history`, whose rows have the same fields as a pushed message
event.  So a caught-up row goes through the same inbound path as a push (authorization gate, spool,
identity lookups, host), marked `asuna_catchup` so the host knows it is an old line and the time it shows
is the original one.

- When: once the adapter is READY, and whenever the event socket comes back after a drop.
- Where: only the routes `adapter.catchup.routes` names (route ids, `auto-group-<id>` / `auto-dm-<id>` under
  automatic admission), or "all": the configured routes and every admitted route with a cursor; none by
  default.
- From: a cursor per route, the time (and platform seq) of the newest message seen there, push or caught
  up, kept in `<data>/catchup/cursors.json`.  The cursor is a time, not a message number: message ids are
  not monotonic.  The cursor comes first, however old; only a route without one looks back
  `lookback_hours` (at most 24).
- How: from the cursor's seq forward (a page includes its anchor and goes newer), at most MAX_PAGES pages;
  when those run out the newest page is taken as well, so a long gap loses lines in its middle, never the
  ones just before now.  Without a seq, the newest page.  Rows are fed oldest first, so a reply finds the
  line it quotes.
  `disable_get_url` is always on: an old picture's link has expired anyway.  Her own lines are dropped.
- Duplicates: a row already seen in this process is dropped by the local LRU; one seen before a restart
  has the same message id and send time (`occurred_at`), which the host answers as a duplicate.

The log carries counts and ids only, never text.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

CATCHUP_KEY = "asuna_catchup"
PAGE = 100
MAX_PAGES = 5
MAX_LOOKBACK_HOURS = 24
FLUSH_SECONDS = 30
ROUTE_PAUSE = 0.5


def utc_iso(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Catchup:
    def __init__(self, cfg, data_dir, onebot, on_event, counters, log=print, clock=time.time):
        self.cfg, self.onebot, self.on_event, self.counters, self.log, self.clock = \
            cfg, onebot, on_event, counters, log, clock
        self.routes = cfg.catchup_routes                     # the route ids catch-up runs for (empty: off)
        self.every = getattr(cfg, "catchup_every", False)    # "all": also every route with a cursor
        self.lookback = min(cfg.catchup_lookback_hours, MAX_LOOKBACK_HOURS) * 3600
        self.path = os.path.join(data_dir, "catchup", "cursors.json")
        self._lock = threading.Lock()
        self._cursors = self._load()
        self._dirty_since = None
        self._due = threading.Event()
        self._reason = None

    # ---- cursors ---------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                blob = json.load(handle)
            routes = blob.get("routes") if isinstance(blob, dict) else None
            return {key: value for key, value in (routes or {}).items() if isinstance(value, dict)}
        except (OSError, ValueError):
            return {}

    def flush(self, force=False):
        with self._lock:
            if self._dirty_since is None or not force and self.clock() - self._dirty_since < FLUSH_SECONDS:
                return False
            blob = {"version": 1, "updated_at": utc_iso(self.clock()), "routes": dict(self._cursors)}
            self._dirty_since = None
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(blob, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        return True

    def note(self, route_id, event):
        """A message accepted on this route, pushed or caught up: the cursor moves to it if it is newer."""
        moment = _int(event.get("time"))
        if moment is None:
            return
        seq = _int(event.get("message_seq")) or _int(event.get("message_id"))
        with self._lock:
            cursor = self._cursors.get(route_id) or {}
            if moment < (_int(cursor.get("time")) or 0):
                return
            self._cursors[route_id] = {"time": moment, "seq": seq, "at": utc_iso(moment)}
            if self._dirty_since is None:
                self._dirty_since = self.clock()
        self.flush()

    def cursor(self, route_id):
        with self._lock:
            return dict(self._cursors.get(route_id) or {})

    # ---- triggers ---------------------------------------------------------
    def request(self, reason):
        """Ask for one run (coalesced): 'startup' or 'reconnect'."""
        if not self.routes and not self.every:
            return
        self._reason = self._reason or reason
        self._due.set()

    def loop(self, stop):
        while not stop.is_set():
            if not self._due.wait(2.0):
                self.flush()
                continue
            self._due.clear()
            reason, self._reason = self._reason or "startup", None
            try:
                self.run(reason)
            except Exception as exc:
                self.counters.inc("catchup_error")
                self.log("CATCHUP_ERROR type=%s" % type(exc).__name__)
        self.flush(force=True)

    # ---- one run ----------------------------------------------------------
    def run(self, reason):
        started = self.clock()
        totals = {"routes": 0, "rows": 0, "fed": 0}
        with self._lock:
            seen = set(self._cursors) if self.every else set()
        for route_id in sorted(set(self.routes) | seen):
            route = self.cfg.route_by_id(route_id)
            if route is None:
                self.log("CATCHUP_ROUTE_SKIPPED route=%s (blocked, or no longer admitted)" % route_id)
                continue
            totals["routes"] += 1
            rows, truncated = self._missed(route, started)
            for row in rows:
                row[CATCHUP_KEY] = {"reason": reason, "fetched_at": utc_iso(started),
                                    "age_seconds": max(0, int(started) - _int(row.get("time")))}
                self.on_event(row)
            totals["rows"] += len(rows)
            self.counters.inc("catchup_rows", len(rows))
            if truncated:
                self.counters.inc("catchup_truncated")
            cursor = self.cursor(route.route_id)
            self.log("CATCHUP route=%s reason=%s rows=%d truncated=%s cursor=%s"
                     % (route.route_id, reason, len(rows), truncated, cursor.get("at", "-")))
            time.sleep(ROUTE_PAUSE)
        self.counters.inc("catchup_runs")
        self.counters.set("catchup_last_run_at", round(started, 3))
        self.log("CATCHUP_DONE reason=%s routes=%d rows=%d seconds=%.1f"
                 % (reason, totals["routes"], totals["rows"], self.clock() - started))
        self.flush(force=True)
        return totals

    def _missed(self, route, now):
        """(rows from the route's cursor on, or inside the look-back window without one, oldest first; truncated)."""
        account = self.cfg.napcat["account_id"]
        cursor = self.cursor(route.route_id)
        since = _int(cursor.get("time"))
        floor = since if since is not None else now - self.lookback
        anchor = _int(cursor.get("seq")) if since is not None else None
        found, truncated, pages = {}, False, 0

        def take(row):
            if not isinstance(row, dict) or row.get("post_type") != "message":
                return
            sender = (row.get("sender") or {}).get("user_id") if isinstance(row.get("sender"), dict) else None
            if account in (str(row.get("user_id")), str(sender)):
                return                             # her own line (a DM's history has both sides)
            moment = _int(row.get("time"))
            if moment is not None and moment >= floor:
                found[str(row.get("message_id"))] = row
        while pages < MAX_PAGES:
            page = self._page(route, anchor)
            pages += 1
            if page is None:
                if anchor is not None and pages == 1:
                    anchor = None                  # the anchor is unknown to the platform: take the newest page
                    continue
                break
            for row in page:
                take(row)
            if anchor is None:
                # the newest page only: it may not reach back to the floor
                oldest = min((_int(r.get("time")) or 0 for r in page if isinstance(r, dict)), default=0)
                truncated = len(page) >= PAGE and oldest > floor
                break
            newest = page[-1] if page and isinstance(page[-1], dict) else {}
            next_anchor = _int(newest.get("message_seq")) or _int(newest.get("message_id"))
            if len(page) < PAGE or next_anchor in (None, anchor) or (_int(newest.get("time")) or 0) >= now:
                break
            anchor = next_anchor
        else:
            truncated = True
            for row in self._page(route, None) or []:     # the lines just before now are kept, the middle is lost
                take(row)
        rows = sorted(found.values(), key=lambda r: (_int(r.get("time")) or 0, _int(r.get("message_seq")) or 0))
        return rows, truncated

    def _page(self, route, anchor):
        if route.message_type == "group":
            action, params = "get_group_msg_history", {"group_id": _int(route.target_id) or route.target_id}
        else:
            action, params = "get_friend_msg_history", {"user_id": _int(route.target_id) or route.target_id}
        params.update(count=PAGE, disable_get_url=True)
        if anchor is not None:
            params["message_seq"] = anchor
        try:
            resp = self.onebot.api_call(action, params, timeout=20, meta={"catchup": route.route_id})
        except Exception as exc:
            self.counters.inc("catchup_api_error")
            self.log("CATCHUP_API_ERROR route=%s action=%s type=%s" % (route.route_id, action, type(exc).__name__))
            return None
        data = resp.get("data") if isinstance(resp, dict) else None
        messages = data.get("messages") if isinstance(data, dict) else None
        if resp.get("retcode") != 0 or not isinstance(messages, list):
            self.counters.inc("catchup_api_refused")
            self.log("CATCHUP_API_REFUSED route=%s action=%s retcode=%s"
                     % (route.route_id, action, resp.get("retcode") if isinstance(resp, dict) else "-"))
            return None
        return messages
