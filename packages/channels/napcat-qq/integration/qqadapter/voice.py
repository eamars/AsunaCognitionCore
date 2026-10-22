"""Voice messages, fetched when they arrive (ADR-093): NapCat clears its voice cache, so a voice not fetched soon is
lost.

After the host accepts a line that carries `record` (or `audio`) segments, each one is queued here; the `voice`
thread asks NapCat for it (`get_record` with the segment's `file` and `out_format` mp3, the smaller form) and posts the
bytes to the host's `voice` endpoint for that line and segment. When NapCat gives no audio (it already cleared the
voice: retcode 1200 `file not found`), the refusal is posted instead, so the line says why. Nothing here runs on the
receive path, and only metadata reaches the log.
"""
import base64
import threading
from queue import Empty, Queue

from .inbound import MEDIA_KEY
from .onebot import ApiNotConnected, ApiTimeout, ApiTransportError

VOICE_TYPES = ("record", "audio")
OUT_FORMAT = "mp3"
CONTENT_TYPE = "audio/mpeg"
FETCH_TIMEOUT = 30.0          # NapCat converts the voice before it answers
POST_TRIES = 3                # a host that is briefly unreachable (5xx, transport) gets the same post again
RETRY_WAIT = 2.0
MAX_FILE = 300                # the segment's file reference, as NapCat gave it


def segments(envelope):
    """[(index, file)] for the voices of an accepted line, in order: only a line whose media block went to the host
    (its placeholders are what the host fills in)."""
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
    block = raw.get(MEDIA_KEY) if isinstance(raw.get(MEDIA_KEY), dict) else {}
    if not any(isinstance(item, dict) and item.get("type") in VOICE_TYPES for item in block.get("items") or ()):
        return []
    out = []
    for seg in raw.get("message") if isinstance(raw.get("message"), list) else ():
        if isinstance(seg, dict) and seg.get("type") in VOICE_TYPES:
            data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            ref = data.get("file") or data.get("file_id")
            out.append((len(out), str(ref)[:MAX_FILE] if isinstance(ref, (str, int)) and str(ref) else None))
    return out


def refusal(reason, retcode=None, message=""):
    body = {"reason": reason, "message": " ".join(str(message or "").split())[:160]}
    if isinstance(retcode, int) and not isinstance(retcode, bool):
        body["retcode"] = retcode
    return body


def fetch(onebot, ref, timeout=FETCH_TIMEOUT):
    """(bytes, None) or (None, refusal) for one voice segment's file."""
    if not ref:
        return None, refusal("no_audio", message="the segment names no file")
    try:
        resp = onebot.api_call("get_record", {"file": ref, "out_format": OUT_FORMAT}, timeout=timeout,
                               meta={"voice": True})
    except ApiTimeout:
        return None, refusal("timeout", message="get_record gave no answer in %g s" % timeout)
    except (ApiNotConnected, ApiTransportError) as exc:
        return None, refusal("unreachable", message=type(exc).__name__)
    if not isinstance(resp, dict):
        return None, refusal("no_audio", message="no answer")
    if resp.get("retcode") != 0:
        message = str(resp.get("message") or resp.get("wording") or "")
        gone = "file not found" in message.lower()
        return None, refusal("gone" if gone else "refused", resp.get("retcode"), message)
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    encoded = data.get("base64")
    if not isinstance(encoded, str) or not encoded:
        return None, refusal("no_audio", message="the answer carries no base64")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except ValueError:
        return None, refusal("no_audio", message="the base64 does not decode")
    if not audio:
        return None, refusal("no_audio", message="0 bytes")
    return audio, None


class VoiceFetcher:
    """One queue, one thread: voices are fetched and posted in the order their lines were accepted."""

    def __init__(self, onebot, host, counters, log=print, retry_wait=RETRY_WAIT):
        self.onebot, self.host, self.counters, self.log = onebot, host, counters, log
        self.retry_wait = retry_wait
        self.queue = Queue()
        self.wake = threading.Event()

    def put(self, envelope):
        """Queue the voices of a line the host accepted; returns how many. Never waits."""
        found = segments(envelope)
        for index, ref in found:
            self.queue.put({"route_id": envelope.get("route_id"), "event_id": envelope.get("event_id"),
                            "occurred_at": envelope.get("occurred_at"), "index": index, "file": ref})
        if found:
            self.counters.inc("voice_queued", len(found))
        return len(found)

    def pending(self):
        return self.queue.qsize()

    def loop(self, stop):
        while not stop.is_set():
            try:
                job = self.queue.get(timeout=1.0)
            except Empty:
                continue
            try:
                self.handle(job, stop)
            except Exception as exc:          # noqa: BLE001 one voice never stops the thread
                self.counters.inc("voice_errors")
                self.log("VOICE_ERROR event_id=%s index=%s type=%s" % (job.get("event_id"), job.get("index"),
                                                                       type(exc).__name__))

    def handle(self, job, stop=None):
        audio, refused = fetch(self.onebot, job.get("file"))
        if audio is not None:
            self.counters.inc("voice_fetched")
            post = lambda: self.host.post_voice(job["route_id"], job["event_id"], job["index"], audio, CONTENT_TYPE,
                                                job.get("occurred_at"))
        else:
            self.counters.inc("voice_not_fetched")
            post = lambda: self.host.post_voice_refusal(job["route_id"], job["event_id"], job["index"], refused,
                                                        job.get("occurred_at"))
        res = None
        for attempt in range(POST_TRIES):
            res = post()
            if res.kind != "retry":
                break
            self.counters.inc("voice_post_retries")
            if stop is not None and stop.wait(self.retry_wait * (attempt + 1)):
                break
        what = ("bytes=%d" % len(audio)) if audio is not None else (
            "refused=%s retcode=%s" % (refused["reason"], refused.get("retcode", "-")))
        if res is not None and res.kind in ("accepted", "duplicate"):
            self.counters.inc("voice_posted")
            self.log("VOICE_POSTED event_id=%s route=%s index=%d %s result=%s http=%s"
                     % (job["event_id"], job["route_id"], job["index"], what, res.kind, res.code))
            return res
        self.counters.inc("voice_post_failed")
        error = (res.obj or {}).get("error") if res is not None and isinstance(res.obj, dict) else None
        self.log("VOICE_POST_FAILED event_id=%s route=%s index=%d %s result=%s http=%s error=%s"
                 % (job["event_id"], job["route_id"], job["index"], what, getattr(res, "kind", "-"),
                    getattr(res, "code", "-"), str(error or getattr(res, "error", "") or "-")[:80]))
        return res
