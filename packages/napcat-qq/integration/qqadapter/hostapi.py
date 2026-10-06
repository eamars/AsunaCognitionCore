"""HTTP client for the runtime host channel API (stdlib only).

Every call returns a Result whose `kind` is one of:
  ok / accepted / duplicate  -> the host took it
  empty                      -> outbox had nothing
  retry                      -> 5xx or transport failure, same payload may be retried
  reject                     -> 4xx, retrying the same payload will not help

`get_attachment` is the only call that returns bytes, and it deliberately does
not share `_request`: that JSON path caps what it reads at 256 KiB, which would
silently truncate an image into an unparsable body -- by then the publication is
already claimed (SENDING), so a host restart would call it UNKNOWN.  The byte
path reads in chunks against its own ceiling and says which check failed.
"""
import hashlib
import json
import socket
import urllib.error
import urllib.parse
import urllib.request


# What this build can actually deliver, declared on every claim so the host
# never queues a publication this adapter could only half-send.  An older host
# ignores an unknown query parameter (the channel server reads only
# `wait_seconds`), so declaring is safe before the host learns about it.
CAPABILITIES = ("image", "sticker")

# One attachment's bytes.  QQ photos are commonly 1-6 MiB; this is the
# adapter's own ceiling, not the host's, and it is enforced while reading.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
ATTACHMENT_CHUNK = 65536
# A JSON body on this path means the host answered an error object, not bytes.
ATTACHMENT_CONTENT_TYPES = ("application/octet-stream", "image/png", "image/jpeg",
                            "image/webp", "image/gif")


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

    def claim_outbox(self, wait_seconds=25, timeout=None, supports=CAPABILITIES):
        path = "/v1/channels/%s/outbox?wait_seconds=%d" % (self.channel_id, int(wait_seconds))
        caps = [str(c) for c in (supports or ()) if c]
        if caps:
            path += "&supports=" + urllib.parse.quote(",".join(caps), safe="")
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

    def get_attachment(self, publication_id, attempt_id, artifact_id=None,
                       expect_sha256=None, max_bytes=MAX_ATTACHMENT_BYTES, timeout=30.0):
        """Fetch the bytes one claimed publication declared, over this same API.

        GET /v1/channels/{channel}/outbox/{publication}/attachment?attempt_id=..&artifact_id=..
        The adapter never reads a host file path: the claim says an artifact
        exists, this asks the host for those bytes with the channel token.

        Result kinds: `ok` (obj carries `data` bytes, `bytes`, `sha256`,
        `content_type`), `retry` (5xx or transport: the same bytes may arrive
        next time), `reject` (4xx, a content type that is not bytes, an empty
        body, more than the ceiling, or a sha256 that is not what the claim
        said -- retrying cannot help).  Nothing is written to disk: the caller
        either sends these bytes or reports `failed`, and the host keeps the
        artifact either way.
        """
        query = {"attempt_id": str(attempt_id)}
        if artifact_id:
            query["artifact_id"] = str(artifact_id)
        path = "/v1/channels/%s/outbox/%s/attachment?%s" % (
            self.channel_id, urllib.parse.quote(str(publication_id), safe=""),
            urllib.parse.urlencode(query))
        req = urllib.request.Request(self.base + path, method="GET")
        req.add_header("Authorization", "Bearer " + self.token)
        limit = int(max_bytes)
        total = 0
        body = b""
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = resp.status
                ctype = str(resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                declared = str(resp.headers.get("Content-Length") or "").strip()
                if declared.isdigit() and int(declared) > limit:
                    return Result("reject", code, {"error": "over_limit", "content_length": int(declared),
                                                   "max_bytes": limit})
                chunks = []
                while total <= limit:
                    part = resp.read(min(ATTACHMENT_CHUNK, limit + 1 - total))
                    if not part:
                        break
                    total += len(part)
                    chunks.append(part)
                body = b"".join(chunks)
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                excerpt = exc.read(2048).decode("utf-8", "replace")
            except Exception:
                excerpt = ""
            return Result("retry" if 500 <= code < 600 else "reject", code,
                          {"error": "http_%s" % code, "excerpt": " ".join(excerpt.split())[:200]})
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            return Result("retry", code=None, error=type(exc).__name__)
        if total > limit:
            return Result("reject", code, {"error": "over_limit", "read_bytes": total, "max_bytes": limit})
        if ctype not in ATTACHMENT_CONTENT_TYPES:
            return Result("reject", code, {"error": "unexpected_content_type", "content_type": ctype[:80]})
        if not body:
            return Result("reject", code, {"error": "empty_body", "content_type": ctype[:80]})
        digest = hashlib.sha256(body).hexdigest()
        if expect_sha256 and digest != str(expect_sha256).strip().lower():
            return Result("reject", code, {"error": "sha256_mismatch", "expected": str(expect_sha256)[:64],
                                           "observed": digest})
        return Result("ok", code, {"data": body, "bytes": len(body), "sha256": digest, "content_type": ctype})

    def post_receipt(self, publication_id, payload):
        path = "/v1/channels/%s/outbox/%s/receipt" % (self.channel_id, urllib.parse.quote(publication_id, safe=""))
        return self._request("POST", path, payload, timeout=12)

    def probe_auth(self):
        """Reachability check that cannot consume a real publication."""
        saved = self.token
        try:
            self.token = "probe-invalid-token-xxxxxxxxxx"
            res = self._request("GET", "/v1/channels/%s/outbox?wait_seconds=0" % self.channel_id, None, timeout=8)
        finally:
            self.token = saved
        reachable = res.code in (401, 403) or res.kind in ("ok", "reject")
        return reachable, res.code, res.error
