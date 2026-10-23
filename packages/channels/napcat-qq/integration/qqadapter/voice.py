"""Voice messages, settled before their line goes to the host (ADR-093): NapCat clears its voice cache, so a voice not
fetched soon is lost, and a line that reaches her should already carry its words.

On the submit path, before a line with `record` (or `audio`) segments is posted, each voice is fetched from NapCat
(`get_record` with the segment's `file` and `out_format` mp3, FETCH_TIMEOUT) and its bytes are posted to the host's
`voice` endpoint, which transcribes it within the request (keyed by the line's event id and the segment's index). When
there is no outcome -- NapCat refused (retcode 1200 `file not found` is `gone`), timed out or answered no audio, or the
host call failed -- the reason goes on that voice's media item (`voice_refused`), so the line says why. The line is
posted either way, after its voices, so lines keep their order. Only metadata reaches the log.

Lines are submitted one at a time, so a voice holds up its line and the lines queued behind it, in any conversation:
at most FETCH_TIMEOUT + POST_TIMEOUT (40 s) per voice, which is the bound per line for QQ, whose voice message carries
one voice; a few seconds in the usual case (NapCat's conversion, then 0.1-1.5 s of transcription).
"""
import base64

from .inbound import MEDIA_KEY

VOICE_TYPES = ("record", "audio")
REFUSED_KEY = "voice_refused"
OUT_FORMAT = "mp3"
CONTENT_TYPE = "audio/mpeg"
FETCH_TIMEOUT = 10.0          # NapCat converts the voice before it answers
POST_TIMEOUT = 30.0           # the host transcribes within the request: a minute of speech is about 1.5 s
MAX_FILE = 300                # the segment's file reference, as NapCat gave it


def _voice_items(envelope):
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
    block = raw.get(MEDIA_KEY) if isinstance(raw.get(MEDIA_KEY), dict) else {}
    return [item for item in block.get("items") or () if isinstance(item, dict) and item.get("type") in VOICE_TYPES]


def segments(envelope):
    """[(index, file)] for the voices of a line, in order: only a line whose media block goes to the host (its
    placeholders are what the host fills in)."""
    if not _voice_items(envelope):
        return []
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
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
    from .onebot import ApiNotConnected, ApiTimeout, ApiTransportError
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


def settle(envelope, onebot, host, counters, log=print, fetch_timeout=FETCH_TIMEOUT, post_timeout=POST_TIMEOUT):
    """Fetch and post each voice of this line before the line is posted; a voice without an outcome gets its reason
    on its media item. Returns [(index, state or reason)] for the log."""
    found = segments(envelope)
    items = _voice_items(envelope)
    done = []
    for index, ref in found:
        audio, refused = fetch(onebot, ref, fetch_timeout)
        if audio is not None:
            res = host.post_voice(envelope.get("route_id"), envelope.get("event_id"), index, audio, CONTENT_TYPE,
                                  envelope.get("occurred_at"), timeout=post_timeout)
            obj = res.obj if isinstance(res.obj, dict) else {}
            if res.kind in ("accepted", "duplicate"):
                counters.inc("voice_settled")
                done.append((index, obj.get("state")))
                log("VOICE_SETTLED event_id=%s route=%s index=%d bytes=%d state=%s result=%s http=%s"
                    % (envelope.get("event_id"), envelope.get("route_id"), index, len(audio), obj.get("state"),
                       res.kind, res.code))
                continue
            code = str(obj.get("error") or "").split(":")[0][:60]
            refused = refusal("host", None, " ".join(str(part) for part in (res.code or res.error or "-", code) if part))
        counters.inc("voice_not_settled")
        if index < len(items):
            items[index][REFUSED_KEY] = refused
        done.append((index, refused["reason"]))
        log("VOICE_NOT_SETTLED event_id=%s route=%s index=%d reason=%s retcode=%s"
            % (envelope.get("event_id"), envelope.get("route_id"), index, refused["reason"],
               refused.get("retcode", "-")))
    return done
