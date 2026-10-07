"""Host outbox -> OneBot send_private_msg / send_group_msg -> receipt.

The outbox target decides the platform action: `dm` keeps the 0.1.0 private
shape (one text segment, unchanged), `group` must pass the configured group
allowlist, may carry one leading `reply` segment when the host supplied
`reply_to`, and encodes the host text into text/at segments.

Group encoding: an explicit `@qq:<digits>` marker written in the character's own
public text becomes a real OneBot `at` segment at the position it was written,
so that person is actually notified instead of reading a bare "@qq:123".
Everything else in that text stays text: plain `@昵称`, `@全体`, an email-looking
`someone@qq:123`, `@qq:all`, or a digit run too long to be a QQ account. The
adapter still never invents an at-all segment. Private sends promote nothing.

The platform's own response is the only source of truth.  A send whose result
cannot be verified becomes `unknown` and is never re-sent; a receipt may be
re-reported with the identical attempt_id.

An outbox item may also declare one image attachment (metadata only: the host
says an artifact exists and what its sha256 is).  The bytes are then fetched
from the host channel API for that very publication -- the adapter never reads
a host file path -- and the send carries the image before her words (a group
send keeps its reply segment first).  Which picture may go to a group is the
host's decision, enforced on its attachment endpoint; the adapter only carries
it.  Anything odd about those bytes (unreachable, over the ceiling, wrong
sha256, not an image) is a `failed` receipt with nothing sent: a text-only
send that reports platform_accepted would claim a picture the peer never
received.  Whether NapCat renders a `base64://` image data URI is NOT yet
verified against a real client.

After a send the platform accepted, the adapter reads that one message back
with `get_msg` (0.2.3).  The id queried is always the one this very send
returned, and the answer is checked against the route we sent to.  It is
observation only: it can never change platform_accepted/failed/unknown, never
trigger a re-send, and never widens what we read (no inbound ids, no reply ids,
no history).  It answers "did the platform store the segments we submitted, in
this conversation, as us" -- not "did a client render a mention".
"""
import base64
import re
import time

from . import faces
from .onebot import ApiNotConnected, ApiTimeout, ApiTransportError

RETRY_WAITS = (0, 2, 5)


def platform_send_timed_out(resp):
    """NapCat's retcode 1200 for sendMsg whose own confirmation event never came: the send's outcome is unknown."""
    if not isinstance(resp, dict) or resp.get("retcode") != 1200:
        return False
    text = str(resp.get("message") or "") + str(resp.get("wording") or "")
    return "Timeout" in text and "sendMsg" in text
MAX_SPOOL_TRIES = 20

SEND_ACTIONS = {"dm": "send_private_msg", "group": "send_group_msg"}
# Group admin actions the host may queue (its own checks decide whether she may): mute/unmute/kick a
# member by account, or recall one message by its platform id.  Nothing else is ever called.
ADMIN_KINDS = ("mute", "unmute", "kick", "recall")
MAX_MUTE_SECONDS = 30 * 86400
# a group send may carry these; a private send carries `text`; either may carry
# one `image` before the words when the host attached a picture to this publication
ALLOWED_OUT_SEGMENTS = ("reply", "text", "at", "face")
GROUP_IMAGE_SEGMENTS = ("reply", "image", "text", "at", "face")
PRIVATE_OUT_SEGMENTS = ("text", "face")
PRIVATE_IMAGE_SEGMENTS = ("image", "text", "face")
# 0.6: a sticker goes out alone -- her own or one she kept, as a picture QQ shows as a sticker
# (image + sub_type 1), or a store sticker as itself (mface, no bytes)
STICKER_KEY = "sticker"
STICKER_SEGMENTS = ("image", "mface")
CUSTOM_STICKER_SUMMARY = "[动画表情]"
# get_msg reads a store sticker back as an `image` segment (that is how NapCat delivers one inbound)
STORED_AS = {"mface": "image"}

ATTACHMENT_KEY = "attachment"
MAX_IMAGE_BYTES = 8 * 1024 * 1024          # the adapter's own ceiling for one image
ALLOWED_OUT_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
IMAGE_MAGICS = (("image/png", b"\x89PNG\r\n\x1a\n"), ("image/jpeg", b"\xff\xd8\xff"),
                ("image/gif", b"GIF87a"), ("image/gif", b"GIF89a"))

# 0.2.3 read-back verification: one `get_msg` per accepted send, for the id that
# send returned, after a short settle gap; one retry only when the platform has
# not indexed that id yet.  Observation only -- see the module docstring.
VERIFY_DELAY_SECONDS = 0.8
VERIFY_RETRY_DELAY_SECONDS = 1.5
VERIFY_TIMEOUT_SECONDS = 5.0
VERIFY_COUNTER = {"verified": "verify_verified",
                  "segment_mismatch": "verify_mismatch",
                  "target_mismatch": "verify_mismatch",
                  "not_found": "verify_not_found",
                  "unavailable": "verify_unavailable"}

# `@qq:101030` is the one spelling that means "point at this account".
# An ASCII word char or one of . @ _ - right before the `@` means the `@qq:` is
# part of a longer token (an address, a path); a letter/_/- right after the
# digits means the run is not a bare account id.  Real QQ ids are <= 12 digits,
# so a run longer than 20 is left as text instead of guessed at.
AT_MARKER = re.compile(r"(?<![A-Za-z0-9.@_\-])@qq:([0-9]{1,20})(?![A-Za-z0-9_\-])")


def encode_group_text(text):
    """Split host group text into text/at segments, promoting @qq:<digits>.

    Position is preserved and the marker itself disappears (the platform renders
    the mention).  Empty text pieces are dropped, so a message that is only
    markers yields only `at` segments.
    """
    segments = []
    pos = 0
    for match in AT_MARKER.finditer(text):
        before = text[pos:match.start()]
        if before:
            segments.extend(encode_faces(before))
        segments.append({"type": "at", "data": {"qq": match.group(1)}})
        pos = match.end()
    tail = text[pos:]
    if tail:
        segments.extend(encode_faces(tail))
    return segments


def encode_faces(text):
    """Split text into text/face segments: each `[表情:名字]` whose name is in faces.json becomes a real
    QQ face at that position (0.6); an unknown name stays text."""
    segments = []
    pos = 0
    for match in faces.TOKEN.finditer(text):
        face_id = faces.BY_NAME.get(match.group(1))
        if face_id is None:
            continue
        if match.start() > pos:
            segments.append({"type": "text", "data": {"text": text[pos:match.start()]}})
        segments.append({"type": "face", "data": {"id": face_id}})
        pos = match.end()
    if pos < len(text):
        segments.append({"type": "text", "data": {"text": text[pos:]}})
    return segments


def sticker_plan(item):
    """(sticker, None) when this item is a sticker this build can send, (None, None) when it is not a
    sticker, else (None, reason).  A custom sticker needs its picture attached; a store sticker needs the
    three ids the platform gave when it arrived."""
    raw = item.get(STICKER_KEY)
    if raw is None:
        return None, None
    if not isinstance(raw, dict) or raw.get("kind") not in ("custom", "market"):
        return None, "sticker_descriptor_invalid"
    if raw["kind"] == "custom":
        if item.get(ATTACHMENT_KEY) is None:
            return None, "sticker_picture_missing"
        return {"kind": "custom"}, None
    out = {"kind": "market"}
    for key, limit in (("emoji_id", 64), ("emoji_package_id", 24), ("key", 64)):
        value = str(raw.get(key) or "").strip()
        if not value or len(value) > limit:
            return None, "sticker_market_ids_missing"
        out[key] = value
    summary = str(raw.get("summary") or "").strip()
    out["summary"] = summary[:24] if summary else "[商城表情]"
    return out, None


def build_send_params(target_type, target_id, text, reply_to=None, image_b64=None, sticker=None):
    """Return (action, params) for a host outbox target, or None if unusable.

    Group sends get a `reply` segment only when the host actually provided
    `reply_to`, and their text goes through encode_group_text; private sends are
    byte-for-byte the 0.1.0 shape (one text segment, markers included).  With
    `image_b64` the picture goes before her words: [image, text] in private,
    [reply?, image, text/at...] in a group -- her words are never dropped to
    make room for the picture.  The image uses the OneBot `base64://` data URI,
    which NapCat documents but which has not been verified against a real
    client yet.
    """
    action = SEND_ACTIONS.get(target_type)
    if action is None:
        return None
    key = "group_id" if target_type == "group" else "user_id"
    if sticker is not None:
        # a sticker is its own message: no reply, no words
        if sticker["kind"] == "market":
            segment = {"type": "mface", "data": {k: sticker[k] for k in ("emoji_id", "emoji_package_id", "key", "summary")}}
        elif image_b64:
            segment = {"type": "image", "data": {"file": "base64://" + image_b64, "sub_type": 1,
                                                  "summary": CUSTOM_STICKER_SUMMARY}}
        else:
            return None
        return action, {key: int(target_id), "message": [segment]}
    if target_type == "group":
        segments = []
        rid = str(reply_to).strip() if reply_to is not None else ""
        if rid:
            segments.append({"type": "reply", "data": {"id": rid}})
        if image_b64:
            segments.append({"type": "image", "data": {"file": "base64://" + image_b64}})
        segments.extend(encode_group_text(text))
        allowed = GROUP_IMAGE_SEGMENTS if image_b64 else ALLOWED_OUT_SEGMENTS
    else:
        segments = encode_faces(text)
        allowed = PRIVATE_OUT_SEGMENTS
        if image_b64:
            segments.insert(0, {"type": "image", "data": {"file": "base64://" + image_b64}})
            allowed = PRIVATE_IMAGE_SEGMENTS
    if not segments:
        return None
    for seg in segments:
        if seg["type"] not in allowed:
            return None
    return action, {key: int(target_id), "message": segments}


def sniff_image(data):
    """The media type these bytes really are, by magic number only; None if not a supported image."""
    for media, magic in IMAGE_MAGICS:
        if data.startswith(magic):
            return media
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def attachment_plan(item, target_type, max_bytes=MAX_IMAGE_BYTES):
    """(descriptor, None) when this item's image may be fetched, else (None, reason).

    Everything here is checked before a single byte is requested, so a doomed
    attachment costs no download.  Private and group routes both carry images:
    who may see which picture is the host's answer (in a group, only pictures
    she made herself), checked again when it serves the bytes.
    """
    raw = item.get(ATTACHMENT_KEY)
    if raw is None:
        return None, "no_attachment"
    if not isinstance(raw, dict):
        return None, "attachment_descriptor_invalid"
    if target_type not in SEND_ACTIONS:
        return None, "attachment_target_not_enabled"
    artifact = raw.get("artifact_id")
    if not isinstance(artifact, str) or not artifact or len(artifact) > 200:
        return None, "attachment_artifact_id_missing"
    sha256 = str(raw.get("sha256") or "").strip().lower()
    if not SHA256_HEX.match(sha256):
        return None, "attachment_sha256_missing"
    media = str(raw.get("media_type") or "").strip().lower()
    if media not in ALLOWED_OUT_MEDIA_TYPES:
        return None, "attachment_media_type_unsupported"
    size = raw.get("size")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size <= 0):
        return None, "attachment_size_invalid"
    if size is not None and size > int(max_bytes):
        return None, "attachment_over_limit"
    return {"artifact_id": artifact, "media_type": media, "sha256": sha256, "declared_size": size}, None


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def verify_payload(resp, checked_id, meta):
    """Classify a `get_msg` answer against what this attempt actually sent.

    Total and side-effect free: anything odd is `unavailable`, never an
    exception and never a claim that the send failed -- by now the message is
    already out.  `target_mismatch` is the binding check (the platform says this
    message lives in a different conversation than the route we sent to);
    `segment_mismatch` means the platform stored a different segment shape than
    the one we submitted.
    """
    sent = [STORED_AS.get(str(s), str(s)) for s in ((meta or {}).get("segments") or [])]
    ttype = str((meta or {}).get("target_type") or "")
    tid = str((meta or {}).get("target_id") or "")
    out = {"checked_id": str(checked_id), "sent_segments": sent, "result": "unavailable"}
    if not isinstance(resp, dict):
        out["reason"] = "no_response"
        return out
    retcode = resp.get("retcode")
    out["platform_retcode"] = retcode
    data = resp.get("data")
    if retcode != 0:
        out["result"] = "not_found" if retcode == 1200 else "unavailable"
        out["reason"] = str(resp.get("wording") or resp.get("message") or "retcode_%s" % retcode)[:120]
        return out
    if not isinstance(data, dict) or not isinstance(data.get("message"), list):
        out["reason"] = "unexpected_shape"
        return out
    stored = [str(seg.get("type")) for seg in data["message"] if isinstance(seg, dict)]
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    self_sent = str(sender.get("user_id") or "") == str((meta or {}).get("account_id") or "")
    peer_bound = True
    if ttype == "group":
        target_ok = str(data.get("message_type") or "") == "group" and str(data.get("group_id") or "") == tid
    elif ttype == "dm":
        # NapCat answers get_msg for a private message with user_id = whoever
        # sent it (our own account when reading back our own send), never the
        # peer, so a DM read-back binds "a private conversation this account
        # spoke in" and nothing more.  Comparing that field to the peer id
        # could not ever pass; the first real DM read-back said so.
        target_ok = str(data.get("message_type") or "") == "private" and self_sent
        peer_bound = False
    else:
        target_ok = False
    stored_tid = data.get("group_id") if ttype == "group" else data.get("user_id")
    out.update({"stored_segments": stored, "target_ok": bool(target_ok),
                "stored_target_type": str(data.get("message_type") or ""),
                "stored_target_id": str(stored_tid or ""),
                "sender_is_self": self_sent, "peer_bound": peer_bound,
                "stored_as_self_sent": str(data.get("message_sent_type") or "") == "self"})
    if not target_ok:
        out["result"] = "target_mismatch"
    elif stored != sent:
        out["result"] = "segment_mismatch"
    else:
        out["result"] = "verified"
    return out


def receipt_payload(status, attempt_id, response, platform_message_id=None):
    payload = {"attempt_id": attempt_id, "status": status, "response": response}
    if platform_message_id:
        payload["platform_message_id"] = str(platform_message_id)
    return payload


class Outbound:
    def __init__(self, cfg, host, onebot, journal, counters, log=print, ack_timeout=15.0,
                 verify=True, verify_delay=VERIFY_DELAY_SECONDS,
                 verify_retry_delay=VERIFY_RETRY_DELAY_SECONDS,
                 verify_timeout=VERIFY_TIMEOUT_SECONDS):
        self.cfg = cfg
        self.host = host
        self.onebot = onebot
        self.journal = journal
        self.counters = counters
        self.log = log
        self.ack_timeout = ack_timeout
        self.verify = bool(verify)
        self.verify_delay = float(verify_delay)
        self.verify_retry_delay = float(verify_retry_delay)
        self.verify_timeout = float(verify_timeout)

    # ---- one claimed publication's image attachment ---------------------
    def fetch_attachment(self, pub, attempt, plan):
        """(base64 text, meta, None) when these bytes may be sent, else (None, meta, reason).

        Bytes come only from the host channel API, for this very publication and
        attempt, with the channel token -- never from a host file path.  Nothing
        is written to disk, and nothing is sent when this returns a reason.
        """
        meta = {"artifact_id": plan["artifact_id"], "media_type": plan["media_type"],
                "sha256": plan["sha256"], "declared_size": plan["declared_size"]}
        getter = getattr(self.host, "get_attachment", None)
        if getter is None:
            meta["fetch_error"] = "endpoint_unsupported"
            return None, meta, "attachment_fetch_unsupported"
        res = getter(pub, attempt, artifact_id=plan["artifact_id"], expect_sha256=plan["sha256"],
                     max_bytes=MAX_IMAGE_BYTES)
        obj = res.obj if isinstance(res.obj, dict) else {}
        if res.kind != "ok":
            detail = str(obj.get("error") or res.error or ("http_%s" % res.code))[:80]
            meta["fetch_error"] = " ".join(detail.split())[:120]
            if res.kind == "retry":
                return None, meta, "attachment_fetch_unavailable"
            return None, meta, "attachment_fetch_" + "_".join(detail.split())[:60]
        data = obj.get("data")
        if not isinstance(data, (bytes, bytearray)):
            meta["fetch_error"] = "no_bytes"
            return None, meta, "attachment_fetch_no_bytes"
        sniffed = sniff_image(bytes(data))
        if sniffed is None:
            meta["sniffed_media_type"] = None
            return None, meta, "attachment_not_an_image"
        if sniffed != plan["media_type"]:
            meta["sniffed_media_type"] = sniffed
            return None, meta, "attachment_media_type_mismatch"
        meta.update({"bytes": len(data), "sha256_verified": True, "sniffed_media_type": sniffed,
                     "content_type": obj.get("content_type"), "base64_chars": ((len(data) + 2) // 3) * 4})
        self.counters.inc("attachment_fetched")
        return base64.b64encode(bytes(data)).decode("ascii"), meta, None

    # ---- one claimed group admin action ---------------------------------
    @staticmethod
    def admin_call(item, own_account):
        """(OneBot action, params) for a host-queued admin action, or (None, reason)."""
        admin = item.get("admin") if isinstance(item.get("admin"), dict) else {}
        target = item.get("target") or {}
        group = str(target.get("id") or "")
        kind = admin.get("kind")
        if target.get("type") != "group" or not group.isdigit():
            return None, "admin_needs_a_group"
        if kind not in ADMIN_KINDS:
            return None, "unknown_admin_kind"
        if kind == "recall":
            mid = str(admin.get("message_id") or "")
            if not mid or len(mid) > 40:
                return None, "bad_message_id"
            return "delete_msg", {"message_id": int(mid) if mid.lstrip("-").isdigit() else mid}
        account = str(admin.get("account") or "")
        if not account.isdigit() or account == str(own_account):
            return None, "bad_account"
        if kind == "kick":
            return "set_group_kick", {"group_id": int(group), "user_id": int(account), "reject_add_request": False}
        seconds = 0 if kind == "unmute" else admin.get("seconds")
        if type(seconds) is not int or not 0 <= seconds <= MAX_MUTE_SECONDS or (kind == "mute" and seconds < 60):
            return None, "bad_duration"
        return "set_group_ban", {"group_id": int(group), "user_id": int(account), "duration": seconds}

    def handle_admin(self, item, stopping=False):
        pub = str(item.get("publication_id") or "")
        attempt = str(item.get("attempt_id") or "")
        target = item.get("target") or {}
        self.counters.inc("admin_claims")
        self.log("ADMIN_CLAIMED pub=%s attempt=%s target=%s:%s kind=%s"
                 % (pub, attempt, target.get("type"), target.get("id"), (item.get("admin") or {}).get("kind")))
        if stopping:
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "adapter_stopping_before_send"}), "stopping")
            return
        if not pub or not attempt:
            return
        if self.cfg.route_for_target(str(target.get("type") or ""), str(target.get("id") or "")) is None:
            self.report(pub, receipt_payload("failed", attempt, {"reason": "target_not_authorized"}), "target_not_authorized")
            return
        action, params = self.admin_call(item, self.cfg.napcat["account_id"])
        if action is None:
            self.report(pub, receipt_payload("failed", attempt, {"reason": params}), params)
            return
        meta = {"publication_id": pub, "attempt_id": attempt, "admin": True, "action": action}
        try:
            resp = self.onebot.api_call(action, params, timeout=self.ack_timeout, meta=meta)
        except ApiNotConnected as exc:
            self.report(pub, receipt_payload("failed", attempt, {"reason": "ws_not_connected", "detail": str(exc)[:200]}),
                        "ws_not_connected")
            return
        except (ApiTransportError, ApiTimeout) as exc:
            self.report(pub, receipt_payload("unknown", attempt, {"reason": type(exc).__name__}), "admin_unknown")
            return
        retcode = resp.get("retcode") if isinstance(resp, dict) else None
        status = "platform_accepted" if retcode == 0 else "failed"
        self.log("ADMIN_RESULT pub=%s action=%s status=%s retcode=%s" % (pub, action, status, retcode))
        self.journal.append("admin.jsonl", {"ts": _now(), "publication_id": pub, "attempt_id": attempt,
                                           "action": action, "status": status, "retcode": retcode})
        self.report(pub, receipt_payload(status, attempt, resp if isinstance(resp, dict) else {"unparsed_response": True}),
                    "admin_" + status)

    # ---- one claimed publication ---------------------------------------
    def handle_item(self, item, stopping=False):
        if item.get("admin") is not None:
            return self.handle_admin(item, stopping=stopping)
        pub = str(item.get("publication_id") or "")
        attempt = str(item.get("attempt_id") or "")
        target = item.get("target") or {}
        ttype = str(target.get("type") or "")
        tid = str(target.get("id") or "")
        text = item.get("text")
        self.counters.inc("outbox_claims")
        self.log("OUTBOX_CLAIMED pub=%s attempt=%s target=%s:%s chars=%s reply_to=%s"
                 % (pub, attempt, ttype, tid, len(text) if isinstance(text, str) else "-", item.get("reply_to")))
        if stopping:
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "adapter_stopping_before_send"}), "stopping")
            return
        if not pub or not attempt:
            self.counters.inc("outbox_shape_reject")
            self.log("OUTBOX_SHAPE pub=%s missing publication_id/attempt_id" % pub)
            return
        route = self.cfg.route_for_target(ttype, tid)
        if route is None:
            # covers a group target outside adapter.allowed_group_ids as well as
            # an unknown target.type: nothing is sent, the host gets a real failed
            self.counters.inc("outbox_target_reject")
            self.report(pub, receipt_payload("failed", attempt,
                                            {"reason": "target_not_authorized", "target_type": ttype, "target_id": tid}),
                        "target_not_authorized")
            return
        sticker, reason = sticker_plan(item)
        if reason:
            self.report(pub, receipt_payload("failed", attempt, {"reason": reason, "target_type": ttype}), reason)
            return
        if sticker is None and (not isinstance(text, str) or not text.strip()):
            self.report(pub, receipt_payload("failed", attempt, {"reason": "empty_text"}), "empty_text")
            return
        text = text if isinstance(text, str) else ""
        if sticker is not None and sticker["kind"] == "market" and item.get(ATTACHMENT_KEY) is not None:
            self.report(pub, receipt_payload("failed", attempt, {"reason": "sticker_descriptor_invalid"}),
                        "sticker_descriptor_invalid")
            return
        plan, reason = attachment_plan(item, ttype)
        image_b64, attachment = None, None
        if plan is None and reason != "no_attachment":
            # an attachment this build cannot even ask for: send nothing, and
            # say why -- text alone would report a picture nobody received
            self.counters.inc("attachment_failed")
            self.log("ATTACHMENT pub=%s attempt=%s reject=%s" % (pub, attempt, reason))
            self.report(pub, receipt_payload("failed", attempt,
                                            {"reason": reason, "target_type": ttype}), reason)
            return
        if plan is not None:
            image_b64, attachment, reason = self.fetch_attachment(pub, attempt, plan)
            if image_b64 is None:
                self.counters.inc("attachment_failed")
                self.log("ATTACHMENT pub=%s attempt=%s fail=%s detail=%s"
                         % (pub, attempt, reason, (attachment or {}).get("fetch_error", "-")))
                self.report(pub, receipt_payload("failed", attempt, {"reason": reason, "target_type": ttype,
                                                                     "attachment": attachment or plan}), reason)
                return
            self.log("ATTACHMENT pub=%s attempt=%s fetched=%s bytes=%s sha256=%s"
                     % (pub, attempt, plan["media_type"], attachment.get("bytes"), plan["sha256"][:12]))
        built = build_send_params(ttype, tid, text, item.get("reply_to"), image_b64=image_b64, sticker=sticker)
        if built is None:
            self.counters.inc("outbox_shape_reject")
            self.report(pub, receipt_payload("failed", attempt,
                                            {"reason": "segment_guard", "target_type": ttype}), "segment_guard")
            return
        action, params = built
        meta = {"publication_id": pub, "attempt_id": attempt, "target_type": ttype, "target_id": tid,
                "account_id": self.cfg.napcat["account_id"],
                "chars": len(text), "segments": [seg["type"] for seg in params["message"]]}
        if attachment is not None:
            meta["attachment"] = attachment
        try:
            resp = self.onebot.api_call(action, params, timeout=self.ack_timeout, meta=meta)
        except ApiNotConnected as exc:
            self.counters.inc("send_not_connected")
            self.report(pub, receipt_payload("failed", attempt, {"reason": "ws_not_connected", "detail": str(exc)[:200]}),
                        "ws_not_connected")
            return
        except ApiTransportError as exc:
            self.counters.inc("send_unknown")
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "transport_error", "detail": str(exc)[:200]}),
                        "transport_error")
            return
        except ApiTimeout:
            self.counters.inc("send_unknown")
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "no_response_within_timeout",
                                                                 "timeout_seconds": self.ack_timeout}),
                        "ack_timeout")
            return
        self.settle(pub, attempt, resp, meta, stopping=stopping)

    def settle(self, pub, attempt, resp, meta, stopping=False):
        retcode = resp.get("retcode") if isinstance(resp, dict) else None
        data = resp.get("data") if isinstance(resp, dict) else None
        mid = data.get("message_id") if isinstance(data, dict) else None
        if retcode == 0 and mid is not None:
            self.counters.inc("send_accepted")
            status, pmid, tag = "platform_accepted", str(mid), "platform_accepted"
            response = resp
        elif platform_send_timed_out(resp):
            # NapCat stopped waiting for QQ's own confirmation (a fresh picture's first upload is slow); QQ delivered
            # every such send we have seen (owner 2026-10-06). Not failed: unknown, which is never re-sent.
            self.counters.inc("send_unknown")
            status, pmid, tag = "unknown", None, "platform_send_timeout"
            response = dict(resp, reason="platform_send_timeout")
        else:
            self.counters.inc("send_failed")
            status, pmid, tag = "failed", None, "retcode_%s" % retcode
            response = resp if isinstance(resp, dict) else {"unparsed_response": True}
        if isinstance(meta.get("attachment"), dict):
            # what actually went out, into the response object the host already
            # stores verbatim; like the read-back, it cannot move `status`
            response = dict(response)
            response["attachment"] = meta["attachment"]
        verification = None
        if status == "platform_accepted" and self.verify:
            # the read-back runs before the receipt so the host can keep it in
            # the raw response object it already stores; it cannot move `status`
            verification = self.verify_send(pmid, meta, stopping=stopping)
            response = dict(response)
            response["verification"] = verification
        self.log("SEND_RESULT pub=%s attempt=%s target=%s status=%s retcode=%s platform_message_id=%s chars=%s"
                 " segments=%s attachment=%s"
                 % (pub, attempt, meta.get("target_type"), status, retcode, pmid or "-", meta.get("chars"),
                    ",".join(meta.get("segments") or []),
                    str((meta.get("attachment") or {}).get("sha256") or "-")[:12]))
        if verification is not None:
            self.log("VERIFY pub=%s attempt=%s pmid=%s result=%s sent=%s stored=%s target_ok=%s self_sent=%s%s"
                     % (pub, attempt, pmid, verification.get("result"),
                        ",".join(verification.get("sent_segments") or []) or "-",
                        ",".join(verification.get("stored_segments") or []) or "-",
                        verification.get("target_ok"), verification.get("stored_as_self_sent"),
                        "" if verification.get("result") == "verified" else
                        " detail=%s" % (verification.get("reason") or
                                        "%s/%s" % (verification.get("stored_target_type"),
                                                   verification.get("stored_target_id")))))
        self.report(pub, receipt_payload(status, attempt, response, pmid), tag)
        self.journal.append("sends.jsonl", {"ts": _now(), "publication_id": pub, "attempt_id": attempt,
                                           "status": status, "retcode": retcode,
                                           "platform_message_id": pmid, "chars": meta.get("chars"),
                                           "segments": meta.get("segments"),
                                           "attachment": meta.get("attachment"),
                                           "verification": verification})

    # ---- read-back verification (observation only) ----------------------
    def verify_send(self, pmid, meta, stopping=False):
        """Ask the platform for the message this send just created, by that id.

        The id is never taken from anywhere else, so this cannot turn into a
        general "read any message" path: inbound ids, `reply_to` ids and history
        are not queried here.  A missing or odd answer is `unavailable`, and the
        send keeps the status the platform already gave it.
        """
        ident = str(pmid or "")
        sent = list((meta or {}).get("segments") or [])
        if not ident.isdigit():
            self.counters.inc("verify_unavailable")
            return {"checked_id": ident[:24], "result": "unavailable",
                    "reason": "id_not_numeric", "sent_segments": sent}
        params = {"message_id": int(ident)}
        checked = {"checked_id": ident, "result": "unavailable", "sent_segments": sent}
        if self.verify_delay > 0 and not stopping:
            time.sleep(self.verify_delay)
        for try_no in (1, 2):
            try:
                resp = self.onebot.api_call("get_msg", params, timeout=self.verify_timeout,
                                            meta={"purpose": "outbound_verification",
                                                  "publication_id": str((meta or {}).get("publication_id") or "")})
            except (ApiNotConnected, ApiTimeout, ApiTransportError) as exc:
                checked["reason"] = "api_%s" % type(exc).__name__
                self.counters.inc("verify_unavailable")
                return checked
            checked = verify_payload(resp, ident, meta)
            if checked["result"] != "not_found" or try_no == 2 or stopping:
                break
            if self.verify_retry_delay > 0:
                time.sleep(self.verify_retry_delay)
        self.counters.inc(VERIFY_COUNTER.get(checked.get("result"), "verify_unavailable"))
        return checked

    # ---- receipts -------------------------------------------------------
    def report(self, pub, payload, why):
        for index, wait in enumerate(RETRY_WAITS):
            if wait:
                time.sleep(wait)
            res = self.host.post_receipt(pub, payload)
            if res.kind in ("ok", "accepted", "duplicate"):
                self.counters.inc("receipts_reported")
                self.log("RECEIPT_OK pub=%s status=%s http=%s why=%s" % (pub, payload["status"], res.code, why))
                return True
            if res.kind == "reject":
                self.counters.inc("receipts_rejected")
                self.log("RECEIPT_REJECT pub=%s status=%s http=%s error=%s"
                         % (pub, payload["status"], res.code, (res.obj or {}).get("error") if isinstance(res.obj, dict) else res.error))
                self.journal.append("receipts_rejected.jsonl",
                                    {"ts": _now(), "publication_id": pub, "payload": payload,
                                     "http": res.code, "body": res.obj})
                return False
            self.counters.inc("receipt_retries")
        self.counters.inc("receipts_spooled")
        self.journal.spool_add("receipts", {"publication_id": pub, "payload": payload, "why": why, "tries": 1},
                               key=pub[:40])
        self.log("RECEIPT_SPOOLED pub=%s status=%s why=%s" % (pub, payload["status"], why))
        return False

    def replay_receipts(self):
        for path in self.journal.spool_list("receipts"):
            try:
                blob = self.journal.read_json(path)
            except Exception:
                self.journal.spool_move(path, "receipts_unreadable.jsonl", {"reason": "unreadable"})
                continue
            pub = str(blob.get("publication_id") or "")
            payload = blob.get("payload") or {}
            res = self.host.post_receipt(pub, payload)
            if res.kind in ("ok", "accepted", "duplicate"):
                self.counters.inc("receipts_reported")
                self.journal.append("receipts_reported.jsonl", {"ts": _now(), "publication_id": pub,
                                                               "status": payload.get("status"), "replay": True})
                self.journal.spool_remove(path)
                self.log("RECEIPT_REPLAYED pub=%s status=%s http=%s" % (pub, payload.get("status"), res.code))
            elif res.kind == "reject":
                self.counters.inc("receipts_rejected")
                self.journal.spool_move(path, "receipts_rejected.jsonl",
                                        {"reason": "host_rejected", "http": res.code, "body": res.obj})
                self.log("RECEIPT_REPLAY_REJECT pub=%s http=%s" % (pub, res.code))
            else:
                tries = int(blob.get("tries") or 0) + 1
                if tries > MAX_SPOOL_TRIES:
                    self.journal.spool_move(path, "receipts_abandoned.jsonl", {"reason": "host_unreachable_too_long"})
                    self.log("RECEIPT_ABANDONED pub=%s" % pub)
                else:
                    blob["tries"] = tries
                    self.journal.write_json(path, blob)

    # ---- late platform acks ---------------------------------------------
    def on_late_ack(self, meta, response):
        pub = str((meta or {}).get("publication_id") or "")
        attempt = str((meta or {}).get("attempt_id") or "")
        if not pub or not attempt:
            return
        retcode = response.get("retcode") if isinstance(response, dict) else None
        data = response.get("data") if isinstance(response, dict) else None
        mid = data.get("message_id") if isinstance(data, dict) else None
        if (meta or {}).get("admin"):
            # an admin action has no message of its own: the platform's retcode is the whole answer
            status, pmid = ("platform_accepted" if retcode == 0 else "failed"), None
        elif retcode == 0 and mid is not None:
            status, pmid = "platform_accepted", str(mid)
        else:
            status, pmid = "failed", None
        self.log("LATE_ACK pub=%s attempt=%s retcode=%s -> %s" % (pub, attempt, retcode, status))
        self.journal.append("late_acks.jsonl", {"ts": _now(), "publication_id": pub, "attempt_id": attempt,
                                               "retcode": retcode, "platform_message_id": pmid})
        self.report(pub, receipt_payload(status, attempt, response if isinstance(response, dict) else {"late": True}, pmid),
                    "late_ack")
