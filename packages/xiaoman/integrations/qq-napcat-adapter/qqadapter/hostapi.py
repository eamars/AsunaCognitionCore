"""HTTP client for the runtime host channel API (stdlib only).

Every call returns a Result whose `kind` is one of:
  ok / accepted / duplicate  -> the host took it
  empty                      -> outbox had nothing
  retry                      -> 5xx or transport failure, same payload may be retried
  reject                     -> 4xx, retrying the same payload will not help
"""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request


class Result:
    __slots__ = ("kind", "code", "obj", "error")

    def __init__(self, kind, code=None, obj=None, error=None):
        self.kind = kind
        self.code = code
        self.obj = obj
        self.error = error

    def __repr__(self):
        return "Result(kind=%r, code=%r, error=%r)" % (self.kind, self.code, self.error)


def _summarise(obj, keys):
    if not isinstance(obj, dict):
        return None
    return {k: obj.get(k) for k in keys if k in obj}


class HostApi:
    def __init__(self, host_cfg, timeout=10):
        self.base = host_cfg["base_url"]
        self.token = host_cfg["token"]
        self.channel_id = host_cfg["channel_id"]
        self.timeout = timeout

    # ---- plumbing -------------------------------------------------------
    def _request(self, method, path, body=None, timeout=None):
        url = self.base + path
        data = None
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req.add_header("Content-Type", "application/json")
            req.add_header("Content-Length", str(len(data)))
        try:
            with urllib.request.urlopen(req, data=data, timeout=timeout or self.timeout) as resp:
                raw = resp.read(262144)
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                raw = exc.read(65536)
            except Exception:
                raw = b""
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            return Result("retry", code=None, error=type(exc).__name__)
        obj = None
        if raw:
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                obj = {"unparsed_body_bytes": len(raw)}
        if 500 <= code < 600:
            return Result("retry", code, obj)
        if 400 <= code < 500:
            return Result("reject", code, obj)
        return Result("ok", code, obj)

    # ---- endpoints ------------------------------------------------------
    def post_event(self, envelope):
        res = self._request("POST", "/v1/channels/%s/events" % self.channel_id, envelope, timeout=12)
        if res.kind == "ok" and isinstance(res.obj, dict):
            status = res.obj.get("status")
            if status == "duplicate":
                res = Result("duplicate", res.code, res.obj)
            elif status == "accepted":
                res = Result("accepted", res.code, res.obj)
        return res

    def claim_outbox(self, wait_seconds=25, timeout=None):
        path = "/v1/channels/%s/outbox?wait_seconds=%d" % (self.channel_id, int(wait_seconds))
        res = self._request("GET", path, None, timeout=timeout or (wait_seconds + 20))
        if res.kind == "ok":
            items = res.obj.get("items") if isinstance(res.obj, dict) else None
            if isinstance(items, list) and items:
                res = Result("items", res.code, res.obj)
            elif isinstance(items, list):
                res = Result("empty", res.code, res.obj)
            else:
                res = Result("retry", res.code, res.obj, error="unexpected_outbox_shape")
        return res

    def post_receipt(self, publication_id, payload):
        path = "/v1/channels/%s/outbox/%s/receipt" % (self.channel_id, urllib.parse.quote(publication_id, safe=""))
        return self._request("POST", path, payload, timeout=12)

    def probe_auth(self):
        """Reachability check that cannot consume a real publication."""
        saved = self.token
        try:
            self.token = "probe-invalid-token-0000000000"
            res = self._request("GET", "/v1/channels/%s/outbox?wait_seconds=0" % self.channel_id, None, timeout=8)
        finally:
            self.token = saved
        reachable = res.code in (401, 403) or res.kind in ("ok", "reject")
        return reachable, res.code, res.error
