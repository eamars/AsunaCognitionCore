"""Bind and store the verified QQ peer snapshot; people.py turns it into what she reads.

Adapted from the persona's ADR-005 development draft (host_wiring/peer_context.py).

宿主侧落点：src/asuna/peer_context.py（新文件，纯标准库）。

两个真实形状，分开读：
  入站事件      event['raw']['asuna_peer']            （Channels.receive 放的那一层）
  持久消息      message['event']['raw']['asuna_peer']  （落库后跟着事件走的那一层）
不是 message['raw']。读不到就返回 None：没有身份块就别让角色以为自己知道什么。
"""
PEER_KEY = "asuna_peer"
CHANGE_LABEL = {"nickname": "昵称", "card": "群名片", "role": "身份", "title": "头衔"}
MAX_NAME = 60
MAX_ALIASES = 4


def _clean(value, limit=MAX_NAME):
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split())[:limit]


def peer_from_event(event):
    """Read only the adapter-owned profile slot, never nested raw input."""
    if not isinstance(event, dict):
        return None
    raw = event.get("raw")
    peer = raw.get(PEER_KEY) if isinstance(raw, dict) else None
    return peer if isinstance(peer, dict) else None


def peer_from_message(doc):
    """Read the profile saved with the authenticated channel event."""
    if not isinstance(doc, dict):
        return None
    return peer_from_event(doc.get("event"))


def channel_of(obj):
    """已认证路由信息：入站事件在 event['channel']，落库后在 message['event']['channel']。"""
    if not isinstance(obj, dict):
        return None
    for candidate in (obj.get("channel"), (obj.get("event") or {}).get("channel")
                      if isinstance(obj.get("event"), dict) else None):
        if isinstance(candidate, dict):
            return candidate
    return None


def verify_peer(peer, channel, expected_person_id=None):
    """Bind adapter data to the host-authenticated sender and route."""
    if not isinstance(peer, dict):
        return False, "no_block"
    if not isinstance(channel, dict):
        return False, "no_channel"
    sender = _clean(channel.get("sender_id"), 32)
    if not sender:
        return False, "no_sender"
    person_id = expected_person_id or "qq:%s" % sender
    if _clean(peer.get("person_id"), 40) != person_id or person_id != "qq:%s" % sender:
        return False, "person_mismatch"
    if _clean(peer.get("account_id"), 32) != sender:
        return False, "account_mismatch"
    target = channel.get("target")
    if not isinstance(target, dict):
        return False, "no_target"
    kind = target.get("type")
    if kind == "group":
        group = _clean(target.get("id"), 20)
        if not group or _clean(peer.get("group_id"), 20) != group or _clean(peer.get("scene"), 40) != "group:%s" % group:
            return False, "scene_mismatch"
    elif kind == "dm":
        if _clean(peer.get("scene"), 40) != "dm" or _clean(peer.get("group_id"), 20):
            return False, "scene_mismatch"
    else:
        return False, "no_target"
    return True, ""


def snapshot_event(event):
    """Return a bounded profile suitable for durable storage after host auth."""
    peer = peer_from_event(event)
    ok, _ = verify_peer(peer, channel_of(event), event.get("person_id") if isinstance(event, dict) else None)
    if not ok:
        return None
    fields = ("person_id", "account_id", "scene", "group_id", "display", "nickname", "card",
              "role", "title", "relation", "known_since", "source", "profile_at")
    profile = {key: _clean(peer.get(key), 80 if key in ("known_since", "profile_at") else MAX_NAME)
               for key in fields if peer.get(key) is not None}
    profile["verified"] = peer.get("verified") is True
    aliases = peer.get("aliases")
    if isinstance(aliases, list):
        profile["aliases"] = [_clean(name) for name in aliases[-MAX_ALIASES:] if _clean(name)]
    seen = peer.get("seen_messages")
    if isinstance(seen, int) and 0 <= seen <= 1000000:
        profile["seen_messages"] = seen
    changed = peer.get("changed")
    if isinstance(changed, list):
        profile["changed"] = [_clean(name, 16) for name in changed[:3] if _clean(name, 16)]
    previous = peer.get("previous")
    if isinstance(previous, dict):
        profile["previous"] = {key: _clean(previous.get(key)) for key in CHANGE_LABEL if previous.get(key)}
    return profile


def speaker_name(config, person_id, row=None, db=None):
    """Readable name for a stored author: a saved identity name, the character, the local user, or the QQ profile saved with the row."""
    chat = config.get("chat", {})
    identity = db.identities.find_one({"_id": person_id}, {"display_name": 1}) if db is not None and person_id else None
    if identity and _clean(identity.get("display_name")):
        return _clean(identity["display_name"])
    if person_id == (config.get("character_id") or chat.get("persona")):
        return chat.get("display_name") or person_id
    if person_id == chat.get("person_id"):
        return "本机用户"
    peer = peer_from_message(row) or {}
    name = _clean(peer.get("display")) or _clean(peer.get("card")) or _clean(peer.get("nickname"))
    return name or str(person_id or "").replace("qq:", "QQ · ", 1)
