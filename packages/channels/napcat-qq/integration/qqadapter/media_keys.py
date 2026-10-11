"""The current picture-link signatures for the host (ADR-035).

A QQ picture link is signed (`rkey`) for minutes; the picture stays. Every EVERY_SECONDS the adapter asks NapCat for
its current download keys and posts them to the host (`POST /v1/channels/<id>/media_keys`) as `qq-group` and
`qq-private`, each with the seconds it still lasts; the host signs a stored link again with them before fetching it.
`get_rkey` answers a list of {type, rkey, created_at, ttl}; a NapCat without it is asked `nc_get_rkey` (the raw
form, type 10 private, 20 group) and then `get_rkey_server` ({private_rkey, group_rkey, expired_time}).

The keys are session secrets: never logged, never written to disk. The log carries which names were posted, how
long they last and which action answered. A failed round is tried again after RETRY_SECONDS.
"""
import time

EVERY_SECONDS = 240
RETRY_SECONDS = 60
ACTIONS = ("get_rkey", "nc_get_rkey", "get_rkey_server")
NAMES = {"group": "qq-group", "private": "qq-private", "20": "qq-group", "10": "qq-private"}
DEFAULT_SECONDS = 600            # when NapCat does not say how long a key lasts
MIN_SECONDS, MAX_SECONDS = 60, 86400


def _key(value):
    """A key as it goes into a link: NapCat may give it as `&rkey=...`."""
    text = str(value or "").strip()
    for prefix in ("&rkey=", "rkey="):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text if text and "&" not in text and text.isprintable() else None


def _seconds(left):
    return max(MIN_SECONDS, min(MAX_SECONDS, int(left))) if left is not None else DEFAULT_SECONDS


def parse(data, now):
    """[{'name', 'key', 'seconds'}] from any of the three answers; keys whose time is up are left out."""
    rows = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = NAMES.get(str(item.get("type")))
            key = _key(item.get("rkey") or item.get("key"))
            try:
                created = float(item.get("created_at", item.get("time")))
                left = created + float(item.get("ttl")) - now
            except (TypeError, ValueError):
                left = None
            if name and key and (left is None or left > MIN_SECONDS):
                rows.append({"name": name, "key": key, "seconds": _seconds(left)})
    elif isinstance(data, dict):
        try:
            left = float(data.get("expired_time")) - now
        except (TypeError, ValueError):
            left = None
        for field, name in (("group_rkey", "qq-group"), ("private_rkey", "qq-private")):
            key = _key(data.get(field))
            if key and (left is None or left > MIN_SECONDS):
                rows.append({"name": name, "key": key, "seconds": _seconds(left)})
    seen, out = set(), []
    for row in rows:                      # one key per name: the first NapCat gave
        if row["name"] not in seen:
            seen.add(row["name"])
            out.append(row)
    return out


class MediaKeys:
    def __init__(self, onebot, host, counters, log=print, clock=time.time):
        self.onebot, self.host, self.counters, self.log, self.clock = onebot, host, counters, log, clock

    def loop(self, stop):
        while not stop.is_set():
            try:
                ok = self.run()
            except Exception as exc:
                ok = False
                self.counters.inc("media_keys_error")
                self.log("MEDIA_KEYS_ERROR type=%s" % type(exc).__name__)
            stop.wait(EVERY_SECONDS if ok else RETRY_SECONDS)

    def fetch(self):
        """(action, rows) from the first action that answers with keys; (None, []) when none does."""
        for action in ACTIONS:
            resp = self.onebot.api_call(action, {}, timeout=15, meta={"media_keys": action})
            if isinstance(resp, dict) and resp.get("retcode") == 0:
                rows = parse(resp.get("data"), self.clock())
                if rows:
                    return action, rows
            self.log("MEDIA_KEYS_ACTION_REFUSED action=%s retcode=%s"
                     % (action, resp.get("retcode") if isinstance(resp, dict) else "-"))
        return None, []

    def run(self):
        action, rows = self.fetch()
        if not rows:
            self.counters.inc("media_keys_none")
            return False
        res = self.host.post_media_keys({"keys": rows})
        if res.kind != "accepted":
            self.counters.inc("media_keys_post_failed")
            self.log("MEDIA_KEYS_POST_FAILED http=%s error=%s"
                     % (res.code, str((res.obj or {}).get("error", "") if isinstance(res.obj, dict) else "")[:160]))
            return False
        self.counters.inc("media_keys_posted")
        self.log("MEDIA_KEYS posted=%s action=%s seconds=%s"
                 % (",".join(row["name"] for row in rows), action, ",".join(str(row["seconds"]) for row in rows)))
        return True
