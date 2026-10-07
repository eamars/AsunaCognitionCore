"""Forward WebSocket client: one read-only /event connection, one /api call
connection, with echo correlation and late-ack tolerance.

The /event reader thread never performs HTTP or model calls: it hands the parsed
event to `on_event`, which only spools it to disk.
"""
import json
import threading
import time
import uuid

from websocket import WebSocketApp, WebSocketConnectionClosedException

BACKOFF = (1, 2, 5, 10, 20, 30)


class ApiNotConnected(Exception):
    pass


class ApiTransportError(Exception):
    pass


class ApiTimeout(Exception):
    pass


def echo_key(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


class _Pending:
    __slots__ = ("event", "meta", "response", "timed_out", "deadline", "sent_at")

    def __init__(self, meta, timeout, late_ttl):
        self.event = threading.Event()
        self.meta = meta
        self.response = None
        self.timed_out = False
        self.sent_at = time.monotonic()
        self.deadline = self.sent_at + timeout + late_ttl


class OneBot:
    def __init__(self, napcfg, counters, on_event, on_late_ack=None, log=print, late_ttl=300):
        self.url = napcfg["url"]
        self.header = ["Authorization: Bearer %s" % napcfg["token"]]
        self.counters = counters
        self.on_event = on_event
        self.on_late_ack = on_late_ack
        self.log = log
        self.late_ttl = late_ttl
        self._pending = {}
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._apps = {}
        self._threads = []
        self._stop = threading.Event()
        self._up = {"/event": False, "/api": False}
        self._down_since = {"/event": None, "/api": None}
        self._backoff = {"/event": 0, "/api": 0}

    # ---- lifecycle ------------------------------------------------------
    def start(self):
        for path in ("/event", "/api"):
            thread = threading.Thread(target=self._run_conn, args=(path,), name="ws" + path.replace("/", "-"), daemon=True)
            thread.start()
            self._threads.append(thread)

    def wait_up(self, path, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._up.get(path):
                return True
            self._stop.wait(0.2)
        return bool(self._up.get(path))

    def stop(self):
        self._stop.set()
        for app in list(self._apps.values()):
            try:
                app.close()
            except Exception:
                pass

    @property
    def event_up(self):
        return self._up["/event"]

    @property
    def api_up(self):
        return self._up["/api"]

    # ---- connection loop ------------------------------------------------
    def _run_conn(self, path):
        while not self._stop.is_set():
            app = WebSocketApp(
                self.url + path,
                header=self.header,
                on_open=lambda _app, p=path: self._on_up(p),
                on_message=lambda _app, raw, p=path: self._on_frame(p, raw),
                on_error=lambda _app, exc, p=path: self._on_ws_error(p, exc),
                on_close=lambda _app, code, reason, p=path: self._on_down(p, code),
            )
            self._apps[path] = app
            try:
                app.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                self.counters.inc("ws_run_error")
                self.log("WS_RUN_ERROR path=%s type=%s" % (path, type(exc).__name__))
            self._on_down(path, None)
            if self._stop.is_set():
                break
            idx = self._backoff[path]
            delay = BACKOFF[min(idx, len(BACKOFF) - 1)]
            self._backoff[path] = idx + 1
            self.log("WS_RETRY path=%s in=%ds" % (path, delay))
            self._stop.wait(delay)

    def _on_up(self, path):
        self._backoff[path] = 0
        gap = None
        if self._down_since[path] is not None:
            gap = round(time.time() - self._down_since[path], 1)
            self._down_since[path] = None
        self._up[path] = True
        self.counters.set("ws_%s_up" % path.strip("/"), 1)
        self.counters.inc("ws_%s_reconnects" % path.strip("/"))
        self.log("WS_UP path=%s gap_seconds=%s" % (path, gap if gap is not None else "first"))

    def _on_down(self, path, code):
        if self._up[path]:
            self._down_since[path] = time.time()
            self.counters.inc("ws_%s_drops" % path.strip("/"))
        self._up[path] = False
        self.counters.set("ws_%s_up" % path.strip("/"), 0)
        if code is not None:
            self.log("WS_CLOSED path=%s code=%s" % (path, code))

    def _on_ws_error(self, path, exc):
        self.counters.inc("ws_%s_errors" % path.strip("/"))
        self.log("WS_ERROR path=%s type=%s" % (path, type(exc).__name__))

    # ---- frame demux ----------------------------------------------------
    def _on_frame(self, path, raw):
        self.counters.inc("frames_%s" % ("event" if path == "/event" else "api"))
        try:
            obj = json.loads(raw)
        except ValueError:
            self.counters.inc("frame_unparsed")
            return
        if not isinstance(obj, dict):
            self.counters.inc("frame_unrecognised")
            return
        if "post_type" in obj:
            try:
                self.on_event(obj)
            except Exception as exc:
                self.counters.inc("on_event_error")
                self.log("ON_EVENT_ERROR type=%s" % type(exc).__name__)
        elif "retcode" in obj or "echo" in obj:
            self._resolve(obj)
        else:
            self.counters.inc("frame_unrecognised")

    def _resolve(self, obj):
        key = echo_key(obj.get("echo")) if "echo" in obj else None
        with self._lock:
            pend = self._pending.pop(key, None) if key else None
        if pend is None:
            self.counters.inc("resp_unmatched")
            return
        if pend.timed_out:
            self.counters.inc("resp_late")
            if self.on_late_ack:
                try:
                    self.on_late_ack(pend.meta, obj)
                except Exception as exc:
                    self.counters.inc("late_ack_handler_error")
                    self.log("LATE_ACK_ERROR type=%s" % type(exc).__name__)
            return
        pend.response = obj
        pend.event.set()

    def prune(self):
        now = time.monotonic()
        expired = []
        with self._lock:
            for key, pend in list(self._pending.items()):
                if pend.timed_out and pend.deadline <= now:
                    expired.append(key)
                    self._pending.pop(key, None)
        if expired:
            self.counters.inc("late_ack_expired", len(expired))

    # ---- calls ----------------------------------------------------------
    def api_call(self, action, params=None, timeout=15.0, meta=None):
        app = self._apps.get("/api")
        if app is None or not self.api_up:
            raise ApiNotConnected("api websocket is not connected")
        echo = "asuna-" + uuid.uuid4().hex
        key = echo_key(echo)
        pend = _Pending(meta or {}, timeout, self.late_ttl)
        with self._lock:
            self._pending[key] = pend
        payload = json.dumps({"action": action, "params": params or {}, "echo": echo}, ensure_ascii=False)
        try:
            with self._send_lock:
                app.send(payload)
        except WebSocketConnectionClosedException:
            self._discard(key)
            raise ApiNotConnected("api websocket closed before the write completed")
        except Exception as exc:
            self._discard(key)
            raise ApiTransportError("%s while writing the request" % type(exc).__name__)
        self.counters.inc("api_calls_sent")
        if pend.event.wait(timeout):
            self._discard(key)
            return pend.response or {}
        pend.timed_out = True
        raise ApiTimeout(json.dumps(pend.meta, ensure_ascii=False, default=str)[:200])

    def _discard(self, key):
        with self._lock:
            self._pending.pop(key, None)

    def pending_count(self):
        with self._lock:
            return len(self._pending)
