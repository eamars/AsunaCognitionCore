"""Project a verified QQ peer snapshot into the role context.

Adapted from XiaoMan's ADR-005 development draft (host_wiring/peer_context.py).

宿主侧落点：src/asuna/peer_context.py（新文件，纯标准库）。

两个真实形状，分开读：
  入站事件      event['raw']['asuna_peer']            （Channels.receive 放的那一层）
  持久消息      message['event']['raw']['asuna_peer']  （落库后跟着事件走的那一层）
不是 message['raw']。读不到就返回 None：没有身份块就别让角色以为自己知道什么。
"""
PEER_KEY = "asuna_peer"
ROLE_LABEL = {"owner": "群主", "admin": "管理员", "member": "成员", "unknown": "身份未知"}
RELATION_LABEL = {"friend": "好友", "group": "群临时会话", "other": "临时会话"}
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


def project_peer(peer):
    """身份块 → 一行中文；不是 dict 或缺 person_id 就 None。"""
    if not isinstance(peer, dict):
        return None
    person_id = _clean(peer.get("person_id"), 32)
    if not person_id:
        return None
    nickname = _clean(peer.get("nickname"))
    card = _clean(peer.get("card"))
    display = _clean(peer.get("display")) or card or nickname or "未取到名字"
    scene = _clean(peer.get("scene"), 40)
    parts = [display]
    if scene.startswith("group:"):
        parts.append("本群群名片 %s" % (card or "未设置"))
        parts.append("QQ 昵称 %s" % (nickname or "未取到"))
        role = _clean(peer.get("role"), 16) or "unknown"
        parts.append("本群身份 %s" % ROLE_LABEL.get(role, role))
        title = _clean(peer.get("title"))
        if title:
            parts.append("头衔 %s" % title)
    else:
        if nickname and nickname != display:
            parts.append("昵称 %s" % nickname)
        relation = _clean(peer.get("relation"), 16)
        if relation:
            parts.append(RELATION_LABEL.get(relation, relation))
    profile_at = _clean(peer.get("profile_at"), 40)
    if peer.get("verified") is True:
        parts.append("QQ 平台已核实%s" % ("，时间 %s" % profile_at[:19] if profile_at else ""))
    known = {display, card, nickname} - {""}
    aliases = peer.get("aliases")
    olds = [a for a in (_clean(x) for x in (aliases[:MAX_ALIASES] if isinstance(aliases, list) else []))
            if a and a not in known][:2]
    if olds:
        parts.append("曾用名 %s" % "、".join(olds))
    line = "[对方身份] %s（%s）" % ("；".join(parts), person_id)
    changes = peer.get("changed")
    changed = [f for f in (changes if isinstance(changes, list) else []) if isinstance(f, str)][:3]
    previous = peer.get("previous") if isinstance(peer.get("previous"), dict) else {}
    if changed:
        bits = []
        for field in changed:
            label = CHANGE_LABEL.get(field, _clean(field, 16))
            old = _clean(previous.get(field))
            bits.append("%s（原「%s」）" % (label, old) if old else label)
        line += "[刚改了%s，还是同一个人]" % "、".join(bits)
    if not peer.get("verified"):
        line += "[未核实：平台资料没查到，这只是这条消息自带的]"
    return line


def project_event(event):
    """入站事件 → 一行；校验源是 event['channel']，不是 raw 自称。"""
    peer = peer_from_event(event)
    ok, _ = verify_peer(peer, channel_of(event), event.get("person_id") if isinstance(event, dict) else None)
    return project_peer(peer) if ok else None


def project_message(doc):
    """持久消息 → 一行；校验源是 message['event']['channel']。"""
    peer = peer_from_message(doc)
    ok, _ = verify_peer(peer, channel_of(doc), doc.get("author") if isinstance(doc, dict) else None)
    return project_peer(peer) if ok else None


def apply_peer_context(context, doc, key="sender_identity"):
    """ContextBuilder.prepare 用（在 context 字典造好之后）：校验通过才写。

    只对当前这条写；不通过一个键都不加。返回 (那行或 None, 原因)；原因非空时
    调用方值得记一行日志，别把通道自称的身份静默当成事实。
    """
    peer = peer_from_message(doc)
    ok, reason = verify_peer(peer, channel_of(doc), doc.get("author") if isinstance(doc, dict) else None)
    line = project_peer(peer) if ok else None
    if line and isinstance(context, dict):
        context[key] = line
    return line, reason
