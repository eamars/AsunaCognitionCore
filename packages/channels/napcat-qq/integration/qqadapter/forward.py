"""Merged forwards (合并转发): the messages a forward carried, brought to the host as raw.asuna_forward.

A received forward segment carries an id. Its messages come inline (`data.content`, when NapCat includes them) or
from one bounded `get_forward_msg` call on the submitter thread. Each forward becomes a block
{ref, count, nodes: [{name, user_id, time, text}], source}, a forward inside a forward is read one level deep, and
the line's placeholder becomes `[合并转发｜N 条｜ref]` with the first PREVIEW messages, one short line each. A forward
that cannot be read says so in its place, with one line of why (UNREAD, NESTED_UNREAD), never in the words of an empty
one. Only metadata is logged, never the text.
"""
import hashlib

from . import inbound

FORWARD_KEY = "asuna_forward"
PLACEHOLDER = "[合并转发（未解析）]"
MAX_FORWARDS = 3          # per message
MAX_NODES = 100           # per forward, nested ones included
MAX_NODE_CHARS = 500
MAX_TOTAL_CHARS = 20000   # per forward
PREVIEW = 3
PREVIEW_CHARS = 40
DEPTH = 2
TIMEOUT = 8.0
MAX_FETCHES = 6           # get_forward_msg calls per message, nested ones included: a line's wait has a bound
# A forward that was not read, in its place (her wording, ADR-119 F1): nothing reads it again, its count is unknown
# (its messages never came), and only a forward that was read is kept, so neither has a ref recall could read.
UNREAD = "[合并转发：没读出来（%s；条数不知道，不再重试）；没有可取的把手]"
NESTED_UNREAD = "（这里还套着一条合并转发，没读出来：%s；不再重试，没有可取的把手）"
WHY = {"limit": "这一条消息里要取的转发超过了一次能取的条数", "refused": "QQ 拒绝了这次读取",
       "empty": "返回里没有消息", "no_id": "这条转发既没带内容也没带编号", "deep": "套得太深，只读两层"}
WHY_ELSE = "取不到"


class Unread(ValueError):
    """A forward that cannot be read, and which of WHY it was."""
    def __init__(self, why):
        super().__init__(why)
        self.why = why


def why(exc):
    """One line of why a forward was not read, in her words; never the exception's text."""
    return WHY.get(getattr(exc, "why", None), WHY_ELSE)


def ref_of(forward_id):
    """The short handle she copies to read a forward in full."""
    return "f" + hashlib.sha1(str(forward_id).encode("utf-8")).hexdigest()[:8]


def segments(message):
    """The forward segments' data of one OneBot message, in order, at most MAX_FORWARDS."""
    if not isinstance(message, list):
        return []
    found = [seg.get("data") or {} for seg in message
             if isinstance(seg, dict) and seg.get("type") == "forward" and isinstance(seg.get("data") or {}, dict)]
    return found[:MAX_FORWARDS]


def _raw_nodes(value):
    """The node list from inline content or a get_forward_msg response."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        data = value.get("data") if isinstance(value.get("data"), (dict, list)) else value
        if isinstance(data, list):
            return data
        for key in ("messages", "message", "content"):
            if isinstance(data.get(key), list):
                return data[key]
    return None


def _fields(node):
    """(name, user_id, time, message) of one node, whichever shape it comes in."""
    if not isinstance(node, dict):
        return "", "", None, None
    data = node.get("data") if node.get("type") == "node" and isinstance(node.get("data"), dict) else node
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    name = inbound._clean(sender.get("card") or sender.get("nickname") or data.get("nickname")
                          or data.get("name"), 40)
    user = inbound._clean(data.get("user_id") or sender.get("user_id") or data.get("uin"), 20)
    when = data.get("time")
    message = data.get("message") if "message" in data else data.get("content")
    return name, user, when if isinstance(when, (int, float)) and not isinstance(when, bool) else None, message


def read(data, call, depth=1):
    """(nodes, source) of one forward segment's data; raises when it cannot be read.

    `call(action, params)` is the OneBot API call, or None when no call may be made."""
    content = _raw_nodes(data.get("content"))
    if content:
        raw, source = content, "inline"
    elif call is not None and data.get("id") not in (None, ""):
        response = call("get_forward_msg", {"id": str(data["id"]), "message_id": str(data["id"])})
        if isinstance(response, dict) and response.get("retcode") not in (0, None):
            raise Unread("refused")
        raw, source = _raw_nodes(response), "fetched"
        if raw is None:
            raise Unread("empty")
    else:
        raise Unread("no_id" if data.get("id") in (None, "") else "no_call")     # no_call: 取不到
    nodes, total = [], 0
    for node in raw:
        if len(nodes) >= MAX_NODES or total >= MAX_TOTAL_CHARS:
            break
        name, user, when, message = _fields(node)
        text = inbound.parse_message(message)["text_with_at_media"].strip()[:MAX_NODE_CHARS]
        item = {"name": name, "user_id": user, "time": when, "text": text}
        nodes.append(item)
        total += len(text)
        for inner in segments(message):
            try:
                if depth >= DEPTH:
                    raise Unread("deep")
                nested, _ = read(inner, call, depth + 1)
            except Exception as exc:
                if len(nodes) < MAX_NODES:
                    nodes.append({"name": "↳", "user_id": "", "time": None, "text": NESTED_UNREAD % why(exc)})
                continue
            for sub in nested[:max(MAX_NODES - len(nodes), 0)]:
                nodes.append({**sub, "name": "↳ " + sub["name"]})
                total += len(sub["text"])
    return nodes, source


def preview(block):
    """The text that stands in for the placeholder: count, ref, and the first PREVIEW messages."""
    lines = ["[合并转发｜%d 条｜%s]" % (block["count"], block["ref"])]
    for node in block["nodes"][:PREVIEW]:
        text = " ".join(node["text"].split())
        if len(text) > PREVIEW_CHARS:
            text = text[:PREVIEW_CHARS] + "…"
        lines.append("  %s：%s" % (node["name"] or "某人", text or "（空）"))
    return "\n".join(lines)


def attach(envelope, call, log=None):
    """Read the envelope's forwards into raw.asuna_forward and put their previews in its text.

    Returns the number of forwards read. Never raises: an unreadable forward says so in its place (UNREAD)."""
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else None
    found = segments((raw or {}).get("message"))
    if not found or FORWARD_KEY in raw:
        return 0
    blocks, text = [], envelope.get("text") or ""
    fetched = [0]

    def bounded(action, params):
        # past MAX_FETCHES a forward without its messages inline is not read, and says so in its place
        if fetched[0] >= MAX_FETCHES:
            raise Unread("limit")
        fetched[0] += 1
        return call(action, params)
    for data in found:
        ref = ref_of(data.get("id") or repr(sorted(data)))
        try:
            nodes, source = read(data, bounded if call is not None else None)
        except Exception as exc:
            if log:
                log("FORWARD_UNREAD event_id=%s ref=%s keys=%s reason=%s"
                    % (envelope.get("event_id"), ref, ",".join(sorted(data)) or "-", type(exc).__name__))
            if PLACEHOLDER in text:
                text = text.replace(PLACEHOLDER, UNREAD % why(exc), 1)
            continue
        block = {"ref": ref, "count": len(nodes), "nodes": nodes, "source": source}
        blocks.append(block)
        if PLACEHOLDER in text:
            text = text.replace(PLACEHOLDER, preview(block), 1)
        if log:
            log("FORWARD event_id=%s ref=%s keys=%s source=%s nodes=%d chars=%d"
                % (envelope.get("event_id"), ref, ",".join(sorted(data)) or "-", source, len(nodes),
                   sum(len(n["text"]) for n in nodes)))
    if blocks:
        raw[FORWARD_KEY] = blocks
    if text != (envelope.get("text") or ""):
        envelope["text"] = text[:inbound.MAX_TEXT]
    return len(blocks)
