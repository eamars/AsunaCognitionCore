"""OneBot message event -> host envelope, with the authorization gate.

Private behaviour is unchanged from 0.1.0 for text-only messages.  Group
support adds a second gate: account -> group allowlist -> that group's member
snapshot -> self echo -> content -> local dedup.  Real `at` segments become
`mentioned_account_ids` (list of account id strings) and a real `reply` segment
becomes an optional `reply_to`.  In group text each real `at` is additionally
rendered in place as `@<account>` so the sentence keeps its shape: "at 示例角色 +
你刚刚回复 + at 101030 + 了么？" stays "@101354你刚刚回复 @101030了么？"
instead of collapsing into "你刚刚回复  了么？".  That rendering is a readable
representation of position only - wake permission still comes from the segment
list alone, and an "@" typed in plain text never becomes a mention.  `reply`
never enters the text.

Media (0.4.0): a message is not only its text segments.  Every segment that is
neither text/at/reply (image, face, record, video, file, json, xml, forward,
location, poke, ...) is now parsed into a bounded `media` list and rendered in
place in the submitted text as an honest placeholder - `[图片（未解析）]`,
`[表情:微笑]`, `[文件:x.pdf（未解析）]`.  A placeholder claims that one of these
was here, at this position; it never claims the content was understood, and the
original segments stay in the raw event.  The normalized block travels to the
host inside `raw` under `asuna_media`, because the host envelope is a strict
allowlist (an extra top-level field is answered with
CHANNEL_ENVELOPE_FIELD_DENIED) and the host does not parse OneBot raw.

`media_mode` (config `adapter.media_mode`, CLI `--media-mode`) bounds that:
  full      media-only messages are submitted too, and a text-less message that
            carries a real reply segment or @s this account is submitted too
  annotate  only messages that already have text get placeholders and the block
  off       exactly the 0.3.0 behaviour: media counted, never rendered, every
            text-less message dropped as `no_text`

Dedup is scoped by route: the same platform message_id seen in two different
scenes (private vs a group, or two groups) is two different events.

Only metadata ever leaves this module for the logs; message text stays in the
spool file and in the host.
"""
import json
import re
import threading
from datetime import datetime, timezone

from . import faces

MAX_TEXT = 16000
MEDIA_KEY = "asuna_media"
MEDIA_MODES = ("full", "annotate", "off")
MAX_MEDIA_ITEMS = 8
MAX_URL = 420
MAX_LABEL = 60

PRIVATE_ENVELOPE_KEYS = {"route_id", "account_id", "sender_id", "event_id", "text", "occurred_at", "raw"}
GROUP_ENVELOPE_KEYS = PRIVATE_ENVELOPE_KEYS | {"group_id", "mentioned_account_ids", "reply_to"}

# segment type -> (中文标签, 标签本身是否已说明内容)。自描述的标签不加
# （未解析），因为它已经把内容说出来了；其余的都明说正文没读过。
MEDIA_TYPES = {
    "image": ("图片", False),
    "face": ("表情", True),
    "record": ("语音", False),
    "audio": ("语音", False),
    "video": ("视频", False),
    "file": ("文件", False),
    "json": ("卡片消息", False),
    "xml": ("卡片消息", False),
    "share": ("分享", False),
    "miniapp": ("小程序", False),
    "music": ("音乐", False),
    "forward": ("合并转发", False),
    "node": ("转发消息", False),
    "location": ("位置", True),
    "poke": ("戳一戳", True),
    "contact": ("名片", True),
    "qrheat": ("二维码", False),
    "album": ("相册", False),
}

TITLE_RE = re.compile(r"<title[^>]*>(.{1,200}?)</title>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


class SeenLRU:
    """Cheap guard against re-submitting the same platform message in the same
    scene.  Keys must carry the route, never the bare message id."""

    def __init__(self, capacity=512):
        self.capacity = capacity
        self._lock = threading.Lock()
        self._order = []
        self._set = set()

    def add_if_new(self, key):
        with self._lock:
            if key in self._set:
                return False
            self._set.add(key)
            self._order.append(key)
            while len(self._order) > self.capacity:
                self._set.discard(self._order.pop(0))
            return True

    def __len__(self):
        with self._lock:
            return len(self._set)


def _clean(value, limit):
    """One bounded single-line string, or empty.  Never raises."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)[:limit]
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _card_hint(data):
    """Title/prompt of a json or xml card, best effort; None when unreadable."""
    blob = data.get("data")
    if not isinstance(blob, str) or not blob:
        return None
    blob = blob.replace("<![CDATA[", " ").replace("]]>", " ")
    if len(blob) <= 8192:
        try:
            node = json.loads(blob)
        except ValueError:
            node = None
        if isinstance(node, dict):
            for key in ("prompt", "title", "desc", "brief"):
                hint = _clean(node.get(key), MAX_LABEL)
                if hint:
                    return hint
    match = TITLE_RE.search(blob[:8192])
    if match:
        hint = _clean(TAG_RE.sub(" ", match.group(1)), MAX_LABEL)
        if hint:
            return hint
    return None


def _media_item(stype, data):
    """One non-text segment -> {type, placeholder, bounded metadata}.

    The placeholder is what the submitted text shows; the metadata is what a
    later vision/OCR step would need.  Both are bounded, so one event cannot
    smuggle an unbounded blob into the host.
    """
    known = MEDIA_TYPES.get(stype) if isinstance(stype, str) else None
    if known is None:
        tag = (re.sub(r"[^a-z0-9_-]", "", stype.lower())[:16] if isinstance(stype, str) else "") or "unknown"
        label, self_describing = "%s消息" % tag, False
    else:
        label, self_describing = known
    name = ""
    sticker = sticker_kind(data) if stype == "image" else None
    if sticker:
        # A sticker is a picture sent as a sticker (0.6): `[表情包]`, or `[表情包:臭]` when the platform
        # named it (a store sticker, or a small named one like [赞]).  The generic "[动画表情]" names nothing.
        label, self_describing = "表情包", True
        name = _clean(data.get("summary"), MAX_LABEL).strip("[]【】 ")
        if name in ("动画表情", "图片"):
            name = ""
    elif stype == "image":
        # a plain photo has no summary, and then the placeholder says nothing more
        # than "there was a picture here"
        name = _clean(data.get("summary"), MAX_LABEL).strip("[]【】 ")
    elif stype == "face":
        # NapCat names a face in raw.faceText ('/汪汪'); classic faces carry no
        # name there, and then the id is looked up in faces.json (0.6)
        name = faces.name_of(data)
    elif stype == "location":
        name = _clean(data.get("name") or data.get("address"), MAX_LABEL)
    elif stype == "poke":
        name = _clean(data.get("name"), 24)
    elif stype == "file":
        name = _clean(data.get("file_name") or data.get("file"), MAX_LABEL)
    elif stype in ("json", "xml", "share", "miniapp", "music"):
        name = _card_hint(data) or ""
    if name:
        placeholder = "[%s:%s%s]" % (label, name, "" if self_describing else "（未解析）")
    else:
        placeholder = "[%s%s]" % (label, "" if self_describing else "（未解析）")
    item = {"type": stype if isinstance(stype, str) else "unknown", "placeholder": placeholder}
    for src, dst, limit in (("file", "file", 120), ("file_id", "file_id", 120),
                            ("url", "url", MAX_URL), ("file_size", "size", 16),
                            ("summary", "summary", 80)):
        if src in data:
            val = _clean(data.get(src), limit)
            if val:
                item[dst] = val
    if "sub_type" in data:
        val = _clean(data.get("sub_type"), 12)
        if val:
            item["sub_type"] = val
    if sticker:
        item["sticker"] = sticker
        if sticker == "market":
            # what sending this very store sticker back takes (an `mface` segment)
            for key, limit in (("emoji_id", 64), ("emoji_package_id", 24), ("key", 64)):
                val = _clean(data.get(key), limit)
                if val:
                    item[key] = val
    if stype == "face":
        val = _clean(data.get("id"), 8)
        if val.isdigit():
            item["face_id"] = val
    return item


STICKER_SUB_TYPES = ("1", "7")          # a custom sticker (still or animated), a small named sticker
MARKET_HOST = "gxh.vip.qq.com"          # store stickers come from QQ's sticker shop host


def sticker_kind(data):
    """'market' for a store sticker, 'custom' for a picture sent as a sticker, None for a photo.

    NapCat delivers both as `image`: a store sticker carries emoji ids (or comes from the shop host), a
    custom sticker carries sub_type 1 (or 7 for the small named ones); a photo is sub_type 0.  The file
    format says nothing -- custom stickers are jpg and png as often as gif."""
    if data.get("emoji_id") or ("//%s/" % MARKET_HOST) in str(data.get("url") or ""):
        return "market"
    if _clean(data.get("sub_type"), 12) in STICKER_SUB_TYPES:
        return "custom"
    return None


def parse_message(message):
    """Normalise a OneBot v11 message into text / real at / real reply / media.

      text                 `text` segments only; what the "is there text" gate
                           reads (a plain-string message is taken literally)
      text_with_at         same, with every real `at` rendered in place as
                           `@<account>` (`@全体` for at-all), keeping position -
                           what group envelopes have submitted since 0.2.1
      text_with_media      `text` plus a media placeholder in place (private)
      text_with_at_media   `text_with_at` plus a media placeholder in place
                           (group); both media renderings stay byte-identical
                           to 0.3.0 for messages that carry no media
      at_ids               ordered unique digit account ids from real `at` segments
      at_all               number of `at` segments targeting `all` (@全体)
      at_other             `at` segments whose target is neither a digit nor all
      reply_to             platform message id of the first real `reply` segment
      reply_extra          number of further `reply` segments
      other_segments       segments that are neither text/at/reply (unchanged)
      media                at most MAX_MEDIA_ITEMS normalized items, in order
      media_extra          media items beyond that cap (counted, not carried)
    """
    out = {"text": "", "text_with_at": "", "text_with_media": "", "text_with_at_media": "",
           "at_ids": [], "at_all": 0, "at_other": 0, "reply_to": None, "reply_extra": 0,
           "other_segments": 0, "media": [], "media_extra": 0}
    if isinstance(message, str):
        out["text"] = message
        out["text_with_at"] = message
        out["text_with_media"] = message
        out["text_with_at_media"] = message
        return out
    if not isinstance(message, list):
        return out
    parts, shown, pmedia, gmedia = [], [], [], []
    for seg in message:
        if not isinstance(seg, dict):
            out["other_segments"] += 1
            continue
        stype = seg.get("type")
        data = seg.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if stype == "text":
            val = data.get("text")
            if isinstance(val, str):
                parts.append(val)
                shown.append(val)
                pmedia.append(val)
                gmedia.append(val)
        elif stype == "at":
            target = data.get("qq")
            if target is None:
                target = data.get("user_id", data.get("uid"))
            sval = str(target).strip() if target is not None else ""
            if sval.isdigit():
                if sval not in out["at_ids"]:
                    out["at_ids"].append(sval)
                shown.append("@" + sval)
                gmedia.append("@" + sval)
            elif sval.lower() == "all":
                out["at_all"] += 1
                shown.append("@全体")
                gmedia.append("@全体")
            else:
                # unrecognised target shape: counted, but no invented text
                out["at_other"] += 1
        elif stype == "reply":
            val = data.get("id")
            if val is None:
                val = data.get("message_id")
            sval = str(val).strip() if val is not None else ""
            if sval and out["reply_to"] is None:
                out["reply_to"] = sval
            elif sval:
                out["reply_extra"] += 1
        else:
            out["other_segments"] += 1
            item = _media_item(stype, data)
            if len(out["media"]) < MAX_MEDIA_ITEMS:
                out["media"].append(item)
            else:
                out["media_extra"] += 1
            pmedia.append(item["placeholder"])
            gmedia.append(item["placeholder"])
    out["text"] = "".join(parts)
    out["text_with_at"] = "".join(shown)
    out["text_with_media"] = "".join(pmedia)
    out["text_with_at_media"] = "".join(gmedia)
    return out


def media_mode_of(cfg):
    """Config-bound, with the 0.4.0 default; a bad value never disables media."""
    mode = getattr(cfg, "media_mode", "full")
    return mode if mode in MEDIA_MODES else "full"


def media_block(parsed):
    """The normalized block that travels inside `raw`, or None."""
    items = parsed.get("media") or []
    if not items:
        return None
    block = {"count": len(items) + int(parsed.get("media_extra") or 0),
             "items": [dict(item) for item in items]}
    if parsed.get("media_extra"):
        block["truncated"] = True
    return block


def strip_media(envelope):
    """Drop the injected media block (used if a host ever refuses it)."""
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else None
    if raw is not None and MEDIA_KEY in raw:
        del raw[MEDIA_KEY]
        return True
    return False


def _attach_media(envelope, parsed, mode):
    if mode == "off":
        return 0
    block = media_block(parsed)
    if block and isinstance(envelope.get("raw"), dict):
        envelope["raw"][MEDIA_KEY] = block
        return block["count"]
    return 0


REPLY_ONLY_FALLBACK = "[回复消息（无文字）]"
NO_TEXT_FALLBACK = "[非文字消息（未解析）]"


def report_text(parsed, group, mode, account_id):
    """What the host should receive for one authorized message, or None.

    None means `no_text`: the gate stays exactly where it was, it only got a
    wider definition of "carries something".  A text-less message counts as
    carrying something when it holds a media segment, a real reply segment, or
    an `at` of this very account - a picture, a sticker and a bare reply into a
    thread are turns, not silence.  A bare `at` of somebody else still is.
    """
    if mode == "off":
        base = parsed["text_with_at"] if group else parsed["text"]
        return base if base.strip() else None
    base = parsed["text_with_at_media"] if group else parsed["text_with_media"]
    if parsed["text"].strip():
        return base
    if mode == "annotate":
        return None
    if parsed["media"]:
        return base
    if parsed["reply_to"] is not None or account_id in parsed["at_ids"]:
        if base.strip():
            return base
        return REPLY_ONLY_FALLBACK if parsed["reply_to"] is not None else NO_TEXT_FALLBACK
    return None


def fit_host_limit(parsed, text, group):
    """Keep a placeholder from pushing a long message past the host's limit.

    The host takes 1-16000 characters.  A message that 0.3.0 would have
    submitted is submitted as-is rather than rejected now because nine extra
    characters of annotation tipped it over; the media block in `raw` still
    says what was there.
    """
    if len(text) <= MAX_TEXT:
        return text, False
    plain = parsed["text_with_at"] if group else parsed["text"]
    if plain.strip() and len(plain) <= MAX_TEXT:
        return plain, True
    return text, False


def _iso(ts):
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _base_envelope(event, user_id, event_id, text, route):
    envelope = {
        "route_id": route.route_id,
        "account_id": str(event.get("self_id")),
        "sender_id": user_id,
        "event_id": event_id,
        "text": text,
        "raw": event,
    }
    occurred = _iso(event.get("time"))
    if occurred:
        envelope["occurred_at"] = occurred
    return envelope


def _media_meta(parsed):
    return {
        "media_segments": len(parsed["media"]) + int(parsed.get("media_extra") or 0),
        "media_types": ",".join(sorted({item["type"] for item in parsed["media"]})) or "-",
        "media_only": not parsed["text"].strip(),
    }


def classify(event, cfg, seen):
    """Return ((envelope, meta) or None, reason).

    `reason` is a short machine tag; it is what shows up in logs and counters.
    """
    if not isinstance(event, dict):
        return None, "bad_shape"
    if event.get("post_type") != "message":
        return None, "nonmessage"
    message_type = event.get("message_type")
    if message_type == "group":
        return _classify_group(event, cfg, seen)
    if message_type == "private":
        return _classify_private(event, cfg, seen)
    return None, "unsupported_message_type"


def _classify_private(event, cfg, seen):
    self_id = str(event.get("self_id")) if event.get("self_id") is not None else ""
    if self_id != cfg.napcat["account_id"]:
        return None, "wrong_self"
    user_id = str(event.get("user_id")) if event.get("user_id") is not None else ""
    if not user_id:
        return None, "bad_shape"
    if user_id == cfg.napcat["account_id"]:
        # our own outgoing message echoed back: never treat it as an inbound turn
        return None, "self_echo"
    route = cfg.route_for_sender(user_id)
    if route is None:
        return None, "unauthorized_sender"
    message_id = event.get("message_id")
    if message_id is None:
        return None, "bad_shape"
    event_id = str(message_id)
    mode = media_mode_of(cfg)
    parsed = parse_message(event.get("message"))
    text = report_text(parsed, False, mode, cfg.napcat["account_id"])
    if text is None:
        # nothing a text-only host can be told about; the caller journals the
        # reason, never the content
        return None, "no_text"
    if not seen.add_if_new("private:%s:%s" % (route.route_id, event_id)):
        return None, "duplicate_local"
    text, shrunk = fit_host_limit(parsed, text, False)
    envelope = _base_envelope(event, user_id, event_id, text, route)
    _attach_media(envelope, parsed, mode)
    meta = {
        "route_id": route.route_id,
        "scene": "private",
        "chars": len(text),
        "non_text_segments": parsed["other_segments"],
        "over_host_limit": len(text) > MAX_TEXT,
    }
    meta.update(_media_meta(parsed))
    if shrunk:
        meta["media_shrunk_for_limit"] = True
    return (envelope, meta), "accepted"


def _classify_group(event, cfg, seen):
    self_id = str(event.get("self_id")) if event.get("self_id") is not None else ""
    if self_id != cfg.napcat["account_id"]:
        return None, "wrong_self"
    group_id = str(event.get("group_id")).strip() if event.get("group_id") is not None else ""
    if not group_id or not group_id.isdigit():
        return None, "bad_shape"
    route = cfg.route_for_group(group_id)
    if route is None:
        return None, ("group_not_allowed" if group_id not in cfg.allowed_groups else "group_route_missing")
    user_id = str(event.get("user_id")) if event.get("user_id") is not None else ""
    if not user_id:
        return None, "bad_shape"
    if user_id == cfg.napcat["account_id"]:
        return None, "self_echo"
    if (user_id in cfg.blocked_senders or not user_id.isascii() or not user_id.isdigit()
            or not 4 <= len(user_id) <= 20
            or cfg.admission != 'automatic' and not route.accepts_sender(user_id)):
        # not in this group's authorized member snapshot (being a member of
        # another authorized group does not count)
        return None, "unauthorized_group_member"
    message_id = event.get("message_id")
    if message_id is None:
        return None, "bad_shape"
    event_id = str(message_id)
    mode = media_mode_of(cfg)
    parsed = parse_message(event.get("message"))
    text = report_text(parsed, True, mode, cfg.napcat["account_id"])
    if text is None:
        # the gate is still here, in the same place, after every authorization
        # check: an unauthorized sender never gets their content looked at
        return None, "no_text"
    if not seen.add_if_new("group:%s:%s" % (route.route_id, event_id)):
        return None, "duplicate_local"
    text, shrunk = fit_host_limit(parsed, text, True)
    envelope = _base_envelope(event, user_id, event_id, text, route)
    envelope["group_id"] = group_id
    envelope["mentioned_account_ids"] = list(parsed["at_ids"])
    if parsed["reply_to"]:
        envelope["reply_to"] = parsed["reply_to"]
    _attach_media(envelope, parsed, mode)
    meta = {
        "route_id": route.route_id,
        "scene": "group",
        "group_id": group_id,
        "chars": len(text),
        "non_text_segments": parsed["other_segments"],
        "over_host_limit": len(text) > MAX_TEXT,
        "mentions": len(parsed["at_ids"]),
        "at_all_segments": parsed["at_all"],
        "at_other_segments": parsed["at_other"],
        "has_reply": bool(parsed["reply_to"]),
        "reply_extra": parsed["reply_extra"],
    }
    meta.update(_media_meta(parsed))
    if shrunk:
        meta["media_shrunk_for_limit"] = True
    return (envelope, meta), "accepted"
