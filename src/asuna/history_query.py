"""查宿主保存的授权消息（P1-b）：字面检索覆盖完整 messages，原文整条回读。

宿主侧落点：src/asuna/history_query.py。身份解析只有一条顶层导入：宿主 peer_context.py 已经
提供的那三个公开函数（peer_from_message / verify_peer / channel_of），缺就整体降级、不抛。
宿主那份里**没有** _group_token、_norm_person，这两个纯字符串解析在本模块内最小实现
（_group_token_local / _norm_person_local）。没有注入入口、没有惰性重接：2026-09-24 宿主侧
只读组合导入证实当前那份三项齐全，多出来的协议没有需求方。

时间不是一个字段（这是上一版静默漏查的原因）：
  - 入站行由 ingress.py 写 occurred_at；
  - QQ 已送达出站由 channels.py 回执时写 receipt_at（coordinator 刚写出时只有 delivery_state=READY，
    没有 occurred_at 也没有 receipt_at）；
  - 本机 Web 出站的送达写在宿主已有的 sink_receipts 那张表里：出站行只带一条指向该回执的 receipt，
    行内没有 receipt_at。这种行现在按 receipt 去 sink_receipts 取 received_at 当有效时间，命中里带
    time_source=sink_receipts.received_at 说清来源——那是本机送达回执，不是平台 ack。

优先级写死：行内 receipt_at（QQ 平台回执）＞ 关联出来的 sink_receipts.received_at ＞ 没时间戳。
同一条行两支都命中时留 receipt_at 那一支，但两个游标位置一起推进，所以续页既不重也不漏。

所以查询是**三支各自带自己的时间条件**，结果按各自时间戳归并排序，游标也是三支各一份。
第三支的有效时间不在 messages 行里，就在 sink_receipts 那一行上，所以它的游标直接开在那张表上：
按 (received_at, 回执 _id) 倒序 keyset 翻页，时间窗下沉进查询，每页捞一批回执再回 messages 联
本场景那几条。没有「扫满就停」这回事——单页预算只决定这一页干多少活，没翻到底体现在
fallback.exhausted=false，而它一定 more=true。上一版按 scene_seq 只捞前 FALLBACK_SCAN=400 条候选，
扫满就 truncated=true 却照样 more=false，最早那条静默消失（2026-09-24 隔离样本 401 条实测复现，
见 fallback_paging_probe.py）。不能用一个字段名探来探去：选错那支会静默少查，不报错。

其余契约：
  - 范围 = 当前这一个授权场景，外加配置里给它挂了的**只读联动场景**（scene['readable_scenes']，
    由 scene_links 现算自 config.context_links；没配就一个都不多读）。scene['scope_key'] /
    scene['policy_epoch'] 交给 Retrieval；正文 text，纪元 policy_epoch。联动场景只在配置里存在，
    工具参数换不了它。
  - 跨场景之后 scene_seq 不再是全序（两个场景各有 seq=24），所以游标决胜位是
    (时间, scene_seq, scene_id) 三位；少一位就会在同一秒两条上重一条或漏一条。
  - 只纳入该场景的 inbound，和 phase='SPEAK' 且 delivery_state='DELIVERED' 的出站。
  - 默认近 7 天、每页 50、最多 200；字面匹配默认大小写敏感。
  - 原文整条回读，保留用户原始空白，不截短（只有 render 显示时截，并标明）。
  - 续页 keyset：每支按（自己那一支的时间, scene_seq）降序；不用 _id 做决胜位（可能是 ObjectId，
    走 JSON 游标比不回来）。

Retrieval.search 只挑 memory_units 候选、不覆盖完整 messages，所以字面那一趟是主干，
语义候选是附加：拿得到就并进来，拿不到照实说，不影响字面结果。
"""
import base64
import json
import re
from datetime import datetime, timedelta

# ── 身份解析：宿主 peer_context.py 已提供这三个公开函数，顶层直接导入 ──────────
# 2026-09-24 宿主侧只读组合导入实测：当前 src/asuna/peer_context.py 三项齐全
# （identity_complete=True、identity_source=peer_context），所以这里就是一条直接导入。
# 上一版另加过注入入口与 sys.modules 惰性采纳，为的是“宿主可能晚导入 peer_context”；
# 那个前提在真宿主上不成立，协议没有需求方，已按 ADR-005 薄接线撤掉。
# 宿主那份没有 _group_token / _norm_person，两个纯字符串解析在本模块内自带。
try:                                  # 宿主按 src.asuna.history_query 加载时走这条
    from .peer_context import peer_from_message, verify_peer, channel_of
except Exception:                     # 同目录平铺加载（离线自检）也认
    try:
        from peer_context import peer_from_message, verify_peer, channel_of
    except Exception:                 # 更旧的宿主连这三个都没有：降级，不带崩查询主干
        peer_from_message = verify_peer = channel_of = None

IDENTITY_CONTRACT = ("peer_from_message(doc) -> dict|None；channel_of(doc) -> dict|None；"
                     "verify_peer(peer, channel) -> (bool, reason)")
IDENTITY_NAMES = ("peer_from_message", "verify_peer", "channel_of")


def identity_status():
    """身份解析接上了没有、缺哪些名字——降级要看得见，不能静默少信息。

    状态直接从模块名字读，不另存一份内部副本：少一个可漂移的状态，就少一处
    “导入其实成功了但状态说没接上”的假象。
    """
    have = [name for name in IDENTITY_NAMES if callable(globals().get(name))]
    return {"resolver": sorted(have), "complete": len(have) == len(IDENTITY_NAMES),
            "missing": [name for name in IDENTITY_NAMES if name not in have],
            "source": ("peer_context" if len(have) == len(IDENTITY_NAMES)
                       else ("peer_context_partial" if have else "none")),
            "contract": IDENTITY_CONTRACT}


def _identity_of(doc):
    """(peer, ok, reason)。三个函数没齐就 (None, False, "identity_unavailable")。"""
    if not (callable(peer_from_message) and callable(verify_peer) and callable(channel_of)):
        return None, False, "identity_unavailable"
    try:
        peer = peer_from_message(doc)
        ok, reason = verify_peer(peer, channel_of(doc))
    except Exception as exc:
        return None, False, "identity_error:%s" % type(exc).__name__
    return peer, bool(ok), reason or ""


def _group_token_local(value):
    """qq:<bot>:group:<群号> / group:<群号> → 群号；跟 peer_context._group_token 同语义。"""
    parts = [x for x in _text(value, 60).lower().split(":") if x]
    for i, token in enumerate(parts):
        if token == "group" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _norm_person_local(value):
    """归一成 person_id；已带 `qq:` 这类前缀的不再拼第二次（否则 qq:qq: 把合法行判成不匹配）。"""
    text = _text(value, 40)
    if not text:
        return ""
    head, sep, rest = text.partition(":")
    if sep and head and len(head) <= 12 and re.match(r"^[a-z][a-z0-9_]*$", head):
        return text.lower()
    return "qq:%s" % text.lower()


TEXT_FIELD = "text"
EPOCH_FIELD = "policy_epoch"
DIRECTION_FIELD = "direction"        # ingress.py / coordinator.py 都写这个，取值如下
INBOUND = "inbound"
OUTBOUND = "outbound"
SIDE_INBOUND = "对方说"        # 入站：场景里那个人亲口说的
SIDE_OUTBOUND = "我说"        # 出站：我自己说过的（不是对方原话）
INBOUND_TIME_FIELD = "occurred_at"    # ingress.py
OUTBOUND_TIME_FIELD = "receipt_at"    # channels.py 回执（QQ 平台 ack），出站时间的第一优先
RECEIPT_REF_FIELD = "receipt"         # 出站行上指向 sink_receipts 那一行的引用
SINK_COLLECTION = "sink_receipts"     # 宿主已有的送达回执表（本机 Web 出站写在这里）
SINK_TIME_FIELD = "received_at"       # 那条回执的送达时间
OUTBOUND_VIA_RECEIPT = "outbound_via_receipt"     # 第三支的游标键
PHASE_FIELD = "phase"
PHASE_SPEAK = "SPEAK"
DELIVERY_FIELD = "delivery_state"
DELIVERED = "DELIVERED"
SORT_FIELD = "scene_seq"
DEFAULT_WINDOW_DAYS = 7
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

try:                                  # 宿主内：联动场景与 canonical person 都现算自配置
    from . import scene_links
except Exception:                     # 同目录平铺加载（离线自检）也认
    try:
        import scene_links
    except Exception:                 # 更薄的环境里没有：照实不联动，不猜范围
        scene_links = None

MAX_LINKED_SCENES = getattr(scene_links, 'MAX_LINKS', 8)
RENDER_SNIPPET = 200
ID_FIELD = "_id"
# 第三支的单页预算：每轮最多看这么多条送达回执、一页最多这么多轮。它只限制「这一页干多少活」，
# 不决定「能不能翻到底」——底是游标说了算（fallback.exhausted）。旧常量 FALLBACK_SCAN=400 是硬截断，
# 候选超过它就静默丢行，已整条拆掉。
FALLBACK_BATCH_MIN = 200
FALLBACK_ROUNDS_MAX = 8
SINK_GROUP = "sink"                   # 归并切页时的成组标记：同一秒的回执条目同进同出
OWN_GROUP = "own"                     # 行内时间那两支：每条自成一组，切在哪儿都不影响正确性

# 时间来源：命中里要能看出这个时间是从哪一行、哪个字段来的，不能只给一个裸时间戳。
TIME_SOURCE_INBOUND = "messages.occurred_at"
TIME_SOURCE_RECEIPT_AT = "messages.receipt_at"            # QQ 平台回执，优先
TIME_SOURCE_SINK = "sink_receipts.received_at"            # 经 receipt 关联出来的本机送达时间
TIME_SOURCE_NONE = ""
TIME_SOURCES = {INBOUND_TIME_FIELD: TIME_SOURCE_INBOUND, OUTBOUND_TIME_FIELD: TIME_SOURCE_RECEIPT_AT,
                SINK_TIME_FIELD: TIME_SOURCE_SINK}
STREAM_KEYS = (INBOUND, OUTBOUND, OUTBOUND_VIA_RECEIPT)


def _text(value, limit=60):
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(value):
    """时间戳取成可比对的字符串：datetime 归一成 ISO-Z，字符串原样（跟现有行里存的一致）。"""
    if isinstance(value, datetime):
        return _iso(value)
    return _text(value, 32)


def _parse(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return None


def _scene_parts(scene):
    """scene 必须是带 scene_id / scope_key / policy_epoch 的那个场景字典。

    两个可选的派生键由调用方（HistoryQueryService / DiscussionDigestService）从配置算好带进来：
      readable_scenes  这一轮还能只读哪些场景（配置里没有就不带，查询条件保持原单值形状）；
      person_classes   {person_id: [同一个人的全部 person_id]}，按人过滤与「谁说的」标注都用它。
    """
    if not isinstance(scene, dict):
        return None
    scene_id = _text(scene.get("scene_id"), 80)
    scope_key = _text(scene.get("scope_key"), 80)
    if not scene_id or not scope_key:
        return None
    try:
        epoch = int(scene.get(EPOCH_FIELD))
    except (TypeError, ValueError):
        return None
    readable = scene.get("readable_scenes")
    extra = list(dict.fromkeys([item for item in (_text(value, 80) for value in
                                (readable if isinstance(readable, (list, tuple)) else []))
                                if item and item != scene_id]))[:MAX_LINKED_SCENES]
    classes = scene.get("person_classes") if isinstance(scene.get("person_classes"), dict) else {}
    raw_aliases = scene.get("person_aliases")
    raw_aliases = raw_aliases if isinstance(raw_aliases, (list, tuple)) else []
    own_person = _text(scene.get("person"), 60)
    aliases = [item for item in (_text(value, 60) for value in raw_aliases)
               if item and item != own_person]
    return {"scene_id": scene_id, "scope_key": scope_key, "epoch": epoch,
            "group_id": _group_token_local(scene_id),
            "scene_ids": [scene_id] + extra, "linked_scenes": extra,
            "person_classes": classes, "person_aliases": aliases}


def scene_id_clause(parts):
    """场景过滤条件：没联动时保持原来的单值形状（条件一行都不多写），联动了才换成 $in。"""
    ids = list(dict.fromkeys([scene for scene in (parts.get("scene_ids") or [parts["scene_id"]])
                              if scene]))
    if not ids:
        return {}
    return {"scene_id": ids[0]} if len(ids) == 1 else {"scene_id": {"$in": ids}}


def _receipt_ref(doc):
    """出站行上那条 receipt 引用（sink_receipts 的 _id）。只认标量；字典就取它自带的 id 键。

    取不到引用就当“没有送达回执可关联”，不猜时间；引用原样带在命中的 time_ref 里，便于核对。
    """
    value = doc.get(RECEIPT_REF_FIELD)
    if isinstance(value, dict):
        value = value.get("_id") or value.get("receipt_id") or value.get("id")
    if isinstance(value, (dict, list)):
        return ""
    return _text(value, 60)


def _sink_times(store, refs):
    """一次批量把 sink_receipts 的 received_at 取回来：{引用: 时间}。取不到就照实说，不猜。

    只发一条 $in 查询，不按行轮询；表不在（更旧的宿主没这张表）就说 no_sink_receipts，
    那一支整体不试，两支主查询照跑。
    """
    column = getattr(getattr(store, "db", None), SINK_COLLECTION, None)
    if column is None:
        return {}, "no_%s" % SINK_COLLECTION
    if not refs:
        return {}, ""
    try:
        rows = list(column.find({"_id": {"$in": sorted(refs)}}) or [])
    except Exception as exc:
        return {}, "sink_lookup_failed:%s" % type(exc).__name__
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = _stamp(row.get(SINK_TIME_FIELD))
        if stamp:
            out[_text(row.get("_id"), 60)] = stamp
    return out, ""


def _outbound_time(doc, sink_times=None):
    """已送达出站的有效时间：行内 receipt_at 优先，缺了才经 receipt 关联 sink_receipts。

    返回 (时间, time_field, time_source, 引用, 原因)。两个来源都没有 → 时间为空 + 原因，
    调用方据此判定“不算在窗口内”，不拿写入时间或 scene_seq 冒充送达时间。
    """
    at = _stamp(doc.get(OUTBOUND_TIME_FIELD))
    if at:
        return at, OUTBOUND_TIME_FIELD, TIME_SOURCE_RECEIPT_AT, "", ""
    ref = _receipt_ref(doc)
    if not ref:
        return "", "", TIME_SOURCE_NONE, "", "no_receipt_ref"
    stamp = _stamp((sink_times or {}).get(ref))
    if not stamp:
        return "", SINK_TIME_FIELD, TIME_SOURCE_NONE, ref, "receipt_unresolved"
    return stamp, SINK_TIME_FIELD, TIME_SOURCE_SINK, ref, ""


def _time_source_of(time_field, at):
    return TIME_SOURCES.get(time_field, TIME_SOURCE_NONE) if at else TIME_SOURCE_NONE


def _row_allowed(doc, parts, window, sink_times=None):
    """语义候选回读后按同一套范围规则再过一遍，不给它走后门进来。

    时间条件按方向看各自那个字段：入站看 occurred_at；已送达出站先看行内 receipt_at，
    缺了才认 receipt 关联出来的 sink_receipts.received_at（跟字面那一支同一套优先级）。
    两个时间戳都没有的行不算在窗口内（没时间戳就不能声称“近 N 天”）。
    """
    if not isinstance(doc, dict):
        return False
    if _text(doc.get("scene_id"), 80) not in set(parts.get("scene_ids") or [parts["scene_id"]]):
        return False
    try:
        if int(doc.get(EPOCH_FIELD)) != parts["epoch"]:
            return False
    except (TypeError, ValueError):
        return False
    direction = _text(doc.get(DIRECTION_FIELD), 16)
    if direction == INBOUND:
        at = _stamp(doc.get(INBOUND_TIME_FIELD))
    elif direction == OUTBOUND and _text(doc.get(PHASE_FIELD), 16) == PHASE_SPEAK \
            and _text(doc.get(DELIVERY_FIELD), 16) == DELIVERED:
        at = _outbound_time(doc, sink_times)[0]
    else:
        return False
    if not at or (window and not (window[0] <= at <= window[1])):
        return False
    return True


def _cursors(cursor):
    """游标是三支各一份：{inbound: [时间, scene_seq], outbound: 同上, outbound_via_receipt: 同上}。"""
    if not cursor:
        return dict((key, None) for key in STREAM_KEYS)
    try:
        raw = json.loads(base64.urlsafe_b64decode(str(cursor).encode("ascii")).decode("utf-8"))
    except Exception:
        return dict((key, None) for key in STREAM_KEYS)
    out = {}
    for key in STREAM_KEYS:
        pair = raw.get(key) if isinstance(raw, dict) else None
        out[key] = pair if isinstance(pair, list) and len(pair) in (2, 3) else None
    return out


def _cursor_of(doc, time_field):
    """游标位置：(时间, scene_seq, scene_id)。第三位是跨场景之后补的决胜位。"""
    return [doc.get(time_field), doc.get(SORT_FIELD), doc.get("scene_id")]


def _after_clause(pair, time_field):
    """游标之后才要（降序）：时间更早；同一时刻看 scene_seq；scene_seq 也相同再看 scene_id。

    只带两位的游标（改动之前发的、以及没联动时的本页）不加第三位条件，翻页序列照旧。
    """
    if not pair:
        return None
    at, seq = pair[0], pair[1]
    clauses = [{time_field: {"$lt": at}}, {time_field: at, SORT_FIELD: {"$lt": seq}}]
    if len(pair) > 2:
        clauses.append({time_field: at, SORT_FIELD: seq, "scene_id": {"$lt": pair[2]}})
    return {"$or": clauses}


def _after_sink_pair(pair, stamp, ref):
    """游标之后的回执才要（降序）：时间更早，或同一秒里回执 id 排在游标那条后面。

    第二位是 None 表示「那一秒整组已消费」：同秒的一律跳过，从更早的秒接着翻。
    """
    if not pair:
        return True
    cursor_at, marker = pair
    mine, theirs = _text(stamp, 32), _text(cursor_at, 32)
    if mine != theirs:
        return mine < theirs
    if marker is None:
        return False
    return _text(ref, 60) < _text(marker, 60)


def sink_time_filter(window=None, pair=None):
    """送达回执那一侧的范围：时间窗下沉 + 游标下推（决胜位不下推，见下）。

    游标第二位是回执 _id，宿主那边可能是 ObjectId，走 JSON 游标比不回来，所以下推只到时间：
    `$lte` 会把游标那一秒整组重新捞一遍，由 _after_sink_pair 逐条跳过已消费的。第二位是 None
    表示那一秒整组已消费完，这时才能下 `$lt`。
    """
    bounds = {}
    if window:
        if window[0]:
            bounds["$gte"] = window[0]
        if window[1]:
            bounds["$lte"] = window[1]
    if pair:
        bounds["$lte" if pair[1] is not None else "$lt"] = pair[0]
    return {SINK_TIME_FIELD: bounds} if bounds else {}


def _group_safe_cut(merged, cut):
    """第三支同一时间戳的条目要么整组进这一页，要么整组留给下一页。

    回退那一支的游标决胜位是回执 id，归并排序的决胜位是 scene_seq：同一秒里两条的先后顺序两边
    可能不一致，页边界正好切在那一组中间就会漏一条。整组同进同出就对不齐不了。行内时间那两支
    每条自成一组（OWN_GROUP + 消息 id），所以这个规则不会让它们少吐。
    """
    if cut <= 0 or cut >= len(merged):
        return cut
    group = merged[cut - 1].get("group")
    if not group or group[0] != SINK_GROUP or merged[cut].get("group") != group:
        return cut
    inside = [i for i, item in enumerate(merged) if item.get("group") == group]
    if inside[0] == 0:
        return inside[-1] + 1           # 整组比一页还大：至少把这组吐完，别原地不动
    return inside[0]


def _encode_cursors(pairs):
    return base64.urlsafe_b64encode(json.dumps(pairs).encode("utf-8")).decode("ascii")


PEER_DOC_PREFIX = "event.raw.asuna_peer"      # 身份块在消息文档里的位置
PERSON_KEYS = ("author", PEER_DOC_PREFIX + ".person_id", PEER_DOC_PREFIX + ".card",
               PEER_DOC_PREFIX + ".nickname", PEER_DOC_PREFIX + ".display",
               PEER_DOC_PREFIX + ".aliases")


def person_clause(person, aliases=()):
    """按人过滤要下沉到查询里（不能等分页后再筛，否则首页会被无关行占满）。

    认已认证 author（就是 person_id），也认身份块里的名片/昵称/显示名/曾用名；
    两者都匹不到就不算这个人说的。aliases 是配置里认定「同一个人」的其他 person_id
    （canonical person）：带上之后，在 local-dm 里按 local-user 过滤也能捞到他从 QQ 那个
    入口说的话——历史行上的 author 一个都不改写，只是过滤条件多认几个等价 id。
    """
    text = _text(person, 60)
    if not text:
        return None
    values = {text.lower()}
    normalized = _norm_person_local(text)
    if normalized:
        values.add(normalized)
    for alias in aliases or ():
        alias = _text(alias, 60)
        if not alias:
            continue
        values.add(alias.lower())
        normalized_alias = _norm_person_local(alias)
        if normalized_alias:
            values.add(normalized_alias)
    ors = []
    for key in PERSON_KEYS:
        for value in sorted(values):
            ors.append({key: value})
    return {"$or": ors}


def _text_pattern(query, case_sensitive):
    if not query:
        return None
    pattern = {"$regex": re.escape(query)}
    if not case_sensitive:
        pattern["$options"] = "i"
    return pattern


def message_filters(parts, query="", *, author=None, window=None, case_sensitive=True,
                    text_field=TEXT_FIELD, person=None):
    """两支行内时间的查询：入站用 occurred_at 夹时间，已送达 SPEAK 出站用 receipt_at 夹时间。

    没给窗口就**不加时间键**：`{field: {}}` 在 Mongo 里是空字典等值，什么都匹不到。
    缺 receipt_at 的出站不在这里夹时间（它的时间不在本行），走 outbound_fallback_filter。
    """
    base = dict(scene_id_clause(parts))
    base[EPOCH_FIELD] = parts["epoch"]
    if author:
        base["author"] = author
    bounds = {}
    if window:
        if window[0]:
            bounds["$gte"] = window[0]
        if window[1]:
            bounds["$lte"] = window[1]
    pattern = _text_pattern(query, case_sensitive)
    inbound = dict(base, **{DIRECTION_FIELD: INBOUND})
    outbound = dict(base, **{DIRECTION_FIELD: OUTBOUND, PHASE_FIELD: PHASE_SPEAK,
                             DELIVERY_FIELD: DELIVERED})
    if bounds:
        inbound[INBOUND_TIME_FIELD] = dict(bounds)
        outbound[OUTBOUND_TIME_FIELD] = dict(bounds)
    if pattern is not None:
        inbound[text_field] = dict(pattern)
        outbound[text_field] = dict(pattern)
    clause = person_clause(person, parts.get("person_aliases") or ())
    if clause:
        inbound["$and"] = [dict(clause)]
        outbound["$and"] = [dict(clause)]
    return [(INBOUND, INBOUND_TIME_FIELD, inbound), (OUTBOUND, OUTBOUND_TIME_FIELD, outbound)]


def outbound_fallback_filter(parts, query="", *, author=None, case_sensitive=True,
                             text_field=TEXT_FIELD, person=None, refs=None):
    """第三支的过滤：已送达 SPEAK 出站、行内没有 receipt_at、但带着指向 sink_receipts 的 receipt。

    有效时间不在本行，时间条件下沉不了（窗口在内存里夹）；但回执 id 能下沉：给了 refs 就按
    `$in` 只圈这一批（分页时就是这么联行的），没给就只要求「有引用」。`$exists` 只是让 Mongo
    少捞行；优先级由 _outbound_time 在内存里再钉一遍，不靠它。
    """
    flt = dict(scene_id_clause(parts))
    flt.update({EPOCH_FIELD: parts["epoch"], DIRECTION_FIELD: OUTBOUND,
           PHASE_FIELD: PHASE_SPEAK, DELIVERY_FIELD: DELIVERED,
           RECEIPT_REF_FIELD: ({"$in": sorted(refs)} if refs is not None
                              else {"$exists": True, "$ne": None}),
           OUTBOUND_TIME_FIELD: {"$exists": False}})
    if author:
        flt["author"] = author
    pattern = _text_pattern(query, case_sensitive)
    if pattern is not None:
        flt[text_field] = dict(pattern)
    clause = person_clause(person, parts.get("person_aliases") or ())
    if clause:
        flt["$and"] = [dict(clause)]
    return flt


def _hit(doc, parts, text_field, time_field, at=None, time_ref=""):
    body = doc.get(text_field)
    full = body if isinstance(body, str) else ""      # 原样，不动空白
    peer, ok, reason = _identity_of(doc)
    author = _text(doc.get("author"), 40)
    stamp = _stamp(doc.get(time_field)) if at is None else _text(at, 32)
    classes = (parts or {}).get("person_classes") or {}
    same_person = {member.lower() for key in (author,) for member in classes.get(key, [])}
    base = {"message_id": str(doc.get("_id") or ""), "scene_id": _text(doc.get("scene_id"), 80),
            "scene_seq": doc.get(SORT_FIELD), "at": stamp, "time_field": time_field,
            "time_source": _time_source_of(time_field, stamp), "time_ref": _text(time_ref, 60),
            "author": author,
            "direction": _text(doc.get(DIRECTION_FIELD), 16),
            "side": SIDE_OUTBOUND if _text(doc.get(DIRECTION_FIELD), 16) == OUTBOUND else SIDE_INBOUND,
            "speaker": author,          # 发言者只认记录里的 author，不拿身份块自称顶替
            "text": full, "chars": len(full), "verbatim": bool(full)}
    if not ok:
        # 身份块不可信、或身份解析根本没接上，都得说清是谁说的：退回已认证 author。
        note = ("身份解析没接上，缺 %s" % "/".join(identity_status()["missing"])
                if reason == "identity_unavailable" else "身份块没通过校验：%s" % reason)
        return dict(base, who="记录作者 %s（%s）" % (author or "?", note),
                    person_id="", names=sorted(({author.lower()} if author else set()) | same_person))
    card, nickname = _text(peer.get("card"), 60), _text(peer.get("nickname"), 60)
    display = _text(peer.get("display"), 60) or card or nickname or "未取到名字"
    bits = [display]
    bits.append("本群群名片" if card and display == card else
                ("本群群名片 %s" % card if card else "本群没设群名片"))
    if nickname and nickname != display:
        bits.append("昵称 %s" % nickname)
    role = _text(peer.get("role"), 16)
    if role:
        bits.append({"owner": "群主", "admin": "管理员", "member": "成员"}.get(role, role))
    if not peer.get("verified"):
        bits.append("未核实")
    person_id = _text(peer.get("person_id"), 40)
    names = set([person_id.lower(), display.lower(), author.lower()])
    names |= same_person | {member.lower() for member in classes.get(person_id, [])}
    for value in (card, nickname):
        if value:
            names.add(value.lower())
    for alias in (peer.get("aliases") or []):
        if _text(alias, 60):
            names.add(_text(alias, 60).lower())
    return dict(base, who="%s（%s）" % ("；".join(bits), person_id), person_id=person_id,
                names=sorted(names))


def _fallback_state():
    """第三支的自查表：扫了多少回执、联上多少行、这一支翻到底没有。

    没有 truncated 这个字段了。上一版扫满 400 条候选就停，把「没扫完」写成 truncated=true
    却照样 more=false，最早那条就这么丢了。现在只有 exhausted 一个口径：false 就一定 more=true，
    下一页接着翻；capped 说这一页是被单页预算拦下的（不是查完了）；scan_pos 是已经逐条核对过的位置。
    """
    return {"attempted": False, "why": "", "scanned": 0, "joined": 0, "dated": 0,
            "out_of_window": 0, "no_time": 0, "skipped_ties": 0, "rounds": 0, "batch": 0,
            "queries": 0, "exhausted": False, "capped": False, "scan_pos": None}


def _receipt_fallback_items(store, parts, query, author, window, case_sensitive, text_field,
                            person, pairs, page):
    """缺 receipt_at 的已送达出站：有效时间取 sink_receipts.received_at，游标开在那张表上。

    行内已有 receipt_at 的行不参与（QQ 平台回执优先，第二支已经把它算过了）。
    每轮：按 (received_at, 回执 _id) 倒序捞一批回执 → 拿这批 id 回 messages 联本场景的行 →
    夹窗口、比游标 → 攒够一页就收手，剩下的留给下一页。时间窗在回执那一侧下沉，所以旧回执
    根本不用捞；单页预算只拦工作量，翻没到底写在 exhausted 里，由调用方换成 more。
    回执表不存在就整支不试：两支主查询照跑，attempted/why 说清为什么这些行仍没时间。
    """
    fb = _fallback_state()
    column = getattr(getattr(store, "db", None), SINK_COLLECTION, None)
    if column is None:
        fb["why"] = "no_%s" % SINK_COLLECTION
        fb["exhausted"] = True          # 整支不试，没有「还没扫完」的悬念
        return fb, []
    fb["attempted"] = True
    fb["batch"] = max(int(page) * 2, FALLBACK_BATCH_MIN)
    pos = pairs.get(OUTBOUND_VIA_RECEIPT)
    items, exhausted = [], False
    while fb["rounds"] < FALLBACK_ROUNDS_MAX:
        fb["rounds"] += 1
        try:
            rows = list(column.find(sink_time_filter(window, pos),
                                    sort=[(SINK_TIME_FIELD, -1), (ID_FIELD, -1)],
                                    limit=fb["batch"]) or [])
        except Exception as exc:
            fb["why"] = "sink_scan_failed:%s" % type(exc).__name__
            fb["capped"] = True
            break
        fb["queries"] += 1
        fb["scanned"] += len(rows)
        if len(rows) < fb["batch"]:
            exhausted = True            # 这一批没捞满：后面真没有了，more=false 才敢出现
        seen, after, receipts = [], [], {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref, stamp = _text(row.get(ID_FIELD), 60), _stamp(row.get(SINK_TIME_FIELD))
            if not ref:
                continue
            if not stamp:
                fb["no_time"] += 1      # 回执行没送达时间：不拿写入时间冒充，也不给它推进游标
                continue
            seen.append([stamp, ref])
            if _after_sink_pair(pos, stamp, ref):
                after.append([stamp, ref])
                receipts[ref] = stamp
        if not after:
            if exhausted or not pos:
                break
            fb["skipped_ties"] += len(seen)     # 同一秒的回执比单轮预算还多：整秒跳过，别原地打转
            pos = [pos[0], None]
            continue
        try:
            found = list(store.db.messages.find(
                outbound_fallback_filter(parts, query, author=author, case_sensitive=case_sensitive,
                                         text_field=text_field, person=person, refs=set(receipts)),
                sort=[(SORT_FIELD, -1), ("scene_id", -1)]) or [])
        except Exception as exc:
            fb["why"] = "fallback_search_failed:%s" % type(exc).__name__
            fb["capped"] = True
            break
        fb["queries"] += 1
        fb["joined"] += len([d for d in found if isinstance(d, dict)])
        for doc in found:
            if not isinstance(doc, dict):
                continue
            ref = _receipt_ref(doc)
            at = receipts.get(ref)
            if not at or _stamp(doc.get(OUTBOUND_TIME_FIELD)):
                continue                        # 有平台回执的归第二支，优先级更高
            if window and not (window[0] <= at <= window[1]):
                fb["out_of_window"] += 1
                continue
            seq = doc.get(SORT_FIELD)
            fb["dated"] += 1
            items.append({"eff": at, "seq": seq if isinstance(seq, int) else -1, "doc": doc,
                          "sid": _text(doc.get("scene_id"), 80),
                          "hit": _hit(doc, parts, text_field, SINK_TIME_FIELD, at=at, time_ref=ref),
                          "positions": [(OUTBOUND_VIA_RECEIPT, [at, ref])],
                          "group": (SINK_GROUP, at), "rank": 2})
        before, pos = pos, (seen[-1] if seen else pos)
        fb["scan_pos"] = pos                    # 到这儿为止逐条核对过的位置
        if len(items) >= page:
            break                               # 这一页干完了，剩下的下一页从游标接着翻
        if pos == before and not exhausted:
            fb["why"] = "sink_scan_no_progress"  # 尾巴那批回执没有可用时间，翻页也翻不动
            exhausted = True
            break
    # 游标一步没动又说「还有更多」，调用方就会拿着同一个游标空转：这种时候只能照实说到底。
    if not exhausted and not items and fb["scan_pos"] in (None, pairs.get(OUTBOUND_VIA_RECEIPT)):
        fb["why"] = fb["why"] or "sink_scan_no_progress"
        exhausted = True
    fb["exhausted"] = exhausted
    fb["capped"] = (not exhausted) or fb["capped"]
    return fb, items


def search_messages(store, scene, query="", *, author=None, window=None, limit=DEFAULT_LIMIT,
                    cursor=None, case_sensitive=True, text_field=TEXT_FIELD, person=None,
                    receipt_fallback=True):
    """行内时间两支各查一次（各自 keyset），关联那一支在内存里比，再按时间归并。"""
    parts = _scene_parts(scene)
    if parts is None:
        return {"hits": [], "degraded": True, "why": "no_scope", "next_cursor": None,
                "more": False, "parts": None, "queries": 0, "fallback": _fallback_state()}
    page = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    pairs = _cursors(cursor)
    streams, items = [], []
    for key, field, flt in message_filters(parts, query, author=author, window=window,
                                          case_sensitive=case_sensitive, text_field=text_field,
                                          person=person):
        after = _after_clause(pairs.get(key), field)
        if after:
            flt.setdefault("$and", []).append(after)   # 不盖掉按人过滤那一支
        try:
            found = list(store.db.messages.find(flt, sort=[(field, -1), (SORT_FIELD, -1),
                                                           ("scene_id", -1)],
                                               limit=page + 1) or [])
        except Exception as exc:
            return {"hits": [], "degraded": True,
                    "why": "messages_search_failed:%s" % type(exc).__name__,
                    "next_cursor": None, "more": False, "parts": parts,
                    "queries": len(streams), "fallback": _fallback_state()}
        stream = {"key": key, "field": field, "cursor": pairs.get(key),
                  "rows": [d for d in found if isinstance(d, dict)]}
        streams.append(stream)
        for doc in stream["rows"]:
            seq = doc.get(SORT_FIELD)
            at = _stamp(doc.get(field))
            items.append({"eff": at, "seq": seq if isinstance(seq, int) else -1,
                          "sid": _text(doc.get("scene_id"), 80),
                          "doc": doc, "hit": _hit(doc, parts, text_field, field),
                          "positions": [(key, _cursor_of(doc, field))],
                          "group": (OWN_GROUP, str(doc.get(ID_FIELD) or "")),
                          "rank": 3 if at else 1})
    fallback, extra = (_fallback_state(), []) if not receipt_fallback else _receipt_fallback_items(
        store, parts, query, author, window, case_sensitive, text_field, person, pairs, page)
    items.extend(extra)
    # 同一条行可能两支都命中（没给窗口时，缺回执时间的出站会同时出现在两支里）：
    # 留优先级最高的那份（receipt_at ＞ sink 回执 ＞ 没时间戳），但两边的游标位置都记下来，
    # 翻页时一起推进，否则下一页会把同一条再吐一遍。
    merged, index = [], {}
    for item in items:
        mid = item["hit"]["message_id"]
        kept = index.get(mid) if mid else None
        if kept is None:
            kept = {"eff": item["eff"], "seq": item["seq"], "doc": item["doc"],
                    "sid": item.get("sid", ""), "hit": item["hit"], "rank": item["rank"],
                    "positions": list(item["positions"]),
                    "group": item.get("group") or (OWN_GROUP, mid)}
            if mid:
                index[mid] = kept
            merged.append(kept)
            continue
        kept["positions"].extend(item["positions"])
        if item["rank"] > kept["rank"]:
            kept.update(eff=item["eff"], seq=item["seq"], doc=item["doc"], hit=item["hit"],
                        rank=item["rank"])
    # 归并决胜位三位一起：时间 → scene_seq → scene_id。跨场景后前两位可能两条完全相同，
    # 少第三位就会在同一秒两条上重一条或漏一条（V7）。
    merged.sort(key=lambda item: (item["eff"], item["seq"], item.get("sid", "")), reverse=True)
    cut = _group_safe_cut(merged, min(page, len(merged)))
    page_items = merged[:cut]
    consumed = dict((stream["key"], stream["cursor"]) for stream in streams)
    if fallback["attempted"]:
        consumed.setdefault(OUTBOUND_VIA_RECEIPT, pairs.get(OUTBOUND_VIA_RECEIPT))
    for item in page_items:
        for key, pair in item["positions"]:
            consumed[key] = pair            # 页内最后一条（最旧）胜出：游标就停在那儿
    # 第三支扫过但没消费完的条目不能从游标里跳过：那种情况只推进到已消费的位置，下一轮把那一截
    # 重新扫一遍（同一个游标，重扫不重发）。整支扫到底了才把扫描位写进游标，省掉下一轮重复劳动。
    pending = [item for item in merged[cut:]
               if any(key == OUTBOUND_VIA_RECEIPT for key, _pair in item["positions"])]
    if fallback["attempted"] and not pending and fallback.get("scan_pos"):
        consumed[OUTBOUND_VIA_RECEIPT] = fallback["scan_pos"]
    # more 只有两个来源：这一页没吐完，或者第三支还没翻到底。截断不再是「查完了」的理由。
    more = bool(cut < len(merged)) or (bool(fallback["attempted"])
                                       and not fallback["exhausted"])
    return {"hits": [item["hit"] for item in page_items], "degraded": False, "why": "",
            "parts": parts, "queries": len(streams) + int(fallback.get("queries") or 0),
            "fallback": fallback,
            "next_cursor": _encode_cursors(consumed) if more else None, "more": more}


def query_history(retrieval, store, scene, query="", *, person=None, author=None,
                  window_days=DEFAULT_WINDOW_DAYS, since=None, until=None, now=None,
                  limit=DEFAULT_LIMIT, cursor=None, case_sensitive=True,
                  text_field=TEXT_FIELD, exclude_sources=(), require_vector=False,
                  receipt_fallback=True):
    """字面为主、语义为辅；两者都不碰 QQ 平台。场景不完整就拒查，不退化成无范围扫描。"""
    parts = _scene_parts(scene)
    if parts is None:
        return {"hits": [], "degraded": True, "why": "no_scope", "next_cursor": None,
                "more": False, "semantic": {"ok": False, "why": "not_attempted", "candidates": 0,
                                            "manifest": None}, "dropped": {},
                "fallback": _fallback_state()}
    ref = _parse(now) or datetime.utcnow()
    low = since or _iso(ref - timedelta(days=max(int(window_days), 1)))
    window = (low, until or "9999-12-31T23:59:59Z")
    page = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    literal = search_messages(store, scene, query, author=author, window=window, limit=page,
                              cursor=cursor, case_sensitive=case_sensitive, text_field=text_field,
                              person=person, receipt_fallback=receipt_fallback)
    semantic = {"ok": False, "why": "not_attempted", "candidates": 0, "manifest": None}
    if literal["degraded"]:
        return {"hits": [], "degraded": True, "why": literal["why"], "next_cursor": None,
                "more": False, "semantic": semantic, "dropped": {}, "window": list(window),
                "fallback": literal["fallback"]}
    merged = [("literal", hit) for hit in literal["hits"]]
    if retrieval is not None:
        try:
            selected, manifest = retrieval.search(parts["scope_key"], parts["epoch"], query,
                                                 exclude_sources=exclude_sources,
                                                 require_vector=require_vector)
            selected = list(selected or [])
            semantic = {"ok": True, "why": "", "candidates": len(selected), "manifest": manifest}
        except Exception as exc:
            selected, semantic = [], {"ok": False, "why": "retrieval_failed:%s" % type(exc).__name__,
                                      "candidates": 0, "manifest": None}
        have = set(hit["message_id"] for _, hit in merged)
        pending, seen = [], set()
        for unit in selected:
            ids = (unit or {}).get("source_event_ids") if isinstance(unit, dict) else None
            for mid in (ids or []):
                if not isinstance(mid, str) or mid in have or mid in seen:
                    continue
                seen.add(mid)
                try:
                    doc = store.db.messages.find_one({"_id": mid})
                except Exception:
                    doc = None
                pending.append((mid, doc))
        refs = set()
        for _mid, doc in pending:
            if isinstance(doc, dict) and _text(doc.get(DIRECTION_FIELD), 16) == OUTBOUND \
                    and not _stamp(doc.get(OUTBOUND_TIME_FIELD)):
                link = _receipt_ref(doc)
                if link:
                    refs.add(link)
        sink_times, _sink_why = _sink_times(store, refs)
        for mid, doc in pending:
            if not _row_allowed(doc, parts, window, sink_times):
                continue
            if _text(doc.get(DIRECTION_FIELD), 16) == OUTBOUND:
                at, field, _source, time_ref, _why = _outbound_time(doc, sink_times)
            else:
                at, field, time_ref = _stamp(doc.get(INBOUND_TIME_FIELD)), INBOUND_TIME_FIELD, ""
            hit = _hit(doc, parts, text_field, field, at=at, time_ref=time_ref)
            hit["via"] = "semantic"
            merged.append(("semantic", hit))
            have.add(mid)
    dropped = {"wrong_person": 0}
    want = person.lower().strip() if isinstance(person, str) and person.strip() else None
    hits = []
    for source, hit in merged:
        if want and want not in hit.get("names", []):
            dropped["wrong_person"] += 1
            continue
        hit = dict(hit)
        hit["via"] = hit.get("via") or source
        hits.append(hit)
    # 字面那一趟已经按游标消费完了，不能再拿 page 切它一刀（同一秒成组那条可能让这一页溢出，
    # 切掉就是游标已经翻页、条目却没吐出去）。语义候选是附加的，挤不下就下一页再说。
    room = max(page, len(literal["hits"]))
    return {"hits": hits[:room], "degraded": False, "why": "", "next_cursor": literal["next_cursor"],
            "more": literal["more"], "semantic": semantic, "dropped": dropped,
            "window": list(window), "limit": page, "queries": literal["queries"],
            "fallback": literal["fallback"],
            "time_fields": {INBOUND: INBOUND_TIME_FIELD, OUTBOUND: OUTBOUND_TIME_FIELD,
                            OUTBOUND_VIA_RECEIPT: SINK_TIME_FIELD},
            "identity": identity_status(),
            "scope": {"scene_id": parts["scene_id"], "scope_key": parts["scope_key"],
                      "group_id": parts["group_id"], EPOCH_FIELD: parts["epoch"],
                      "linked_scenes": parts["linked_scenes"],
                      "same_person_ids": sorted({member for members in
                                                 (parts.get("person_classes") or {}).values()
                                                 for member in members})}}


def render(result, header="查到的授权历史", snippet=RENDER_SNIPPET):
    """行首时间，然后场景#序号、谁说的（我说／对方说）、身份、原文片段。"""
    """给角色读的几行。数据里的 text 是整条原文；这里只显示片段并标明截断。"""
    if result.get("degraded"):
        why = result.get("why") or "unknown"
        if why == "no_scope":
            return "[%s] 场景范围不完整，没查（不扫全部消息）" % header
        return "[%s] 没查成（%s），这条回答没用到历史" % (header, why)
    hits = result.get("hits") or []
    notes = []
    ident = result.get("identity") or {}
    if ident and not ident.get("complete"):
        notes.append("身份解析没接上（缺 %s），只按记录作者标注" % "/".join(ident.get("missing") or []))
    semantic = result.get("semantic") or {}
    if not semantic.get("ok") and semantic.get("why") != "not_attempted":
        notes.append("语义检索没成（%s），只按字面查了 messages" % semantic.get("why"))
    scope = result.get("scope") or {}
    linked = [scene for scene in (scope.get("linked_scenes") or []) if scene]
    if linked:
        others = len([hit for hit in hits if hit.get("scene_id") and
                      hit.get("scene_id") != scope.get("scene_id")])
        notes.append("本次范围按配置联动了 %d 个只读场景（%s）：行首的场景号就是这句话是在哪儿说的，"
                     "联动场景里的行不是这个场景的新输入；跨场景命中 %d 条" % (
                         len(linked), "、".join(linked), others))
    fb = result.get("fallback") or {}
    if fb.get("why"):        # 表不在（更旧的宿主）也要说清：不是没送达，是没有可比对的回执时间
        notes.append("本机出站的送达时间没关联上（%s）：缺 receipt_at 的已送达出站仍按没时间戳处理"
                     % fb["why"])
    if fb.get("attempted") and not fb.get("exhausted"):
        notes.append("本机出站的送达回执这一页翻了 %d 条还没翻到底（预算 %d 轮×%d 条），"
                     "剩下的在续页里" % (fb.get("scanned", 0), fb.get("rounds", 0),
                                        fb.get("batch", 0)))
    if fb.get("skipped_ties"):
        notes.append("有 %d 条同一秒的送达回执超出单轮预算被整秒跳过，没逐条核对"
                     % fb["skipped_ties"])
    if not hits:
        return "[%s] 没查到（近 %s 起，授权场景内没有匹配；不代表对方没说过别的）%s" % (
            header, (result.get("window") or ["?"])[0], "；" + "，".join(notes) if notes else "")
    lines = ["[%s %d 条%s]" % (header, len(hits), "；" + "，".join(notes) if notes else "")]
    for hit in hits:
        body = hit["text"] or "（空）"
        if len(body) > snippet:
            body = "%s…〔显示截断，全文 %d 字在 text〕" % (body[:snippet], hit["chars"])
        stamp = hit["at"][:16].replace("T", " ") if hit["at"] else "无时间戳"
        if hit.get("time_source") == TIME_SOURCE_SINK:
            stamp += "⟨本机送达回执⟩"          # 不是平台 ack，行首就说清
        lines.append("- %s %s#%s｜%s｜%s：%s%s" % (
            stamp, hit["scene_id"], hit.get("scene_seq"), hit.get("side") or hit["direction"],
            hit["who"], body, "" if hit["verbatim"] else "〔原文没回读到〕"))
    if result.get("next_cursor"):
        lines.append("（还有更多，续页 cursor=%s）" % result["next_cursor"])
    return "\n".join(lines)


# ── P1-b 宿主接线：现有 ToolBroker 内的受信只读入口 ────────────────────────────
# 上面的查询函数不认识任务；这一层把「当前任务绑定的场景与授权」翻译成一次固定调用：
# 场景、纪元、范围键都从任务绑定记录里读，不从工具参数来；参数只收领域字段
# （字面词、人物、时间窗、页大小、游标、大小写、是否带语义候选），不透传集合名、
# Mongo pipeline 或连接串。查不到（hits 空）、没接上（degraded）、语义检索失败
# （semantic.ok=false 但字面照返）是三种不同状态，分开返回，不合并成一个错误串。
# 2026-09-24 隔离探针后补的三件事：dropped 计数透传；传输预算裁掉的命中用回退游标
# 续页（不静默消费）；游标带筛选指纹信封，中途换 person/词/窗口明确拒绝。
import hashlib
import json as _json
import re as _re


try:                                  # 宿主内：复用已有的 Denied 语义（409 失败回执走原路径）
    from .state import Denied
except Exception:                     # 同目录平铺加载（离线自检）也认
    try:
        from state import Denied
    except Exception:                 # 更薄的环境里自带同型异常，不改变调用方的分支写法
        class Denied(PermissionError):
            pass

HISTORY_TOOL_NAME = "query_authorized_history"
HISTORY_TOOL = {
    "name": HISTORY_TOOL_NAME,
    "description": ("只读查询当前任务授权场景里保存的原话：字面检索覆盖完整 messages（不只是记忆候选），"
                    "返回原文、实际作者、场景、时间及其来源（平台回执／本机送达回执／入站时间），按 cursor 续页。"
                    "场景由任务绑定，外加配置给它挂的只读联动场景（同一人的另一个入口）；参数不能换"
                    "查询范围，也不接受 Mongo 表达式。跨场景命中行首带各自的场景号。"
                    "回执时间回退会标明是送达回执，不伪称原始发送时刻；more=true 时必须带 cursor 续查，不能宣称查完。"),
    "parameters": {
        "query": {"type": "string"},
        "person": {"type": "string"},
        "since": {"type": "string"},
        "until": {"type": "string"},
        "window_days": {"type": "integer"},
        "limit": {"type": "integer"},
        "cursor": {"type": "string"},
        "case_sensitive": {"type": "boolean"},
        "include_semantic": {"type": "boolean"},
    },
}

_STAMP_SHAPE = _re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9:.+Z-]{0,24})?$")
HISTORY_ARGUMENTS = set(HISTORY_TOOL["parameters"])
HISTORY_RESULT_BUDGET = 48 * 1024     # hits 原文整条回读；预算只裁页尾最旧命中，被裁的走续页重发
_STREAM_BY_FIELD = {INBOUND_TIME_FIELD: INBOUND, OUTBOUND_TIME_FIELD: OUTBOUND,
                    SINK_TIME_FIELD: OUTBOUND_VIA_RECEIPT}


def _bounded_text(value, limit, name):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 4 * limit:
        raise ValueError("INVALID_HISTORY_" + name)
    return value


def _bounded_int(value, low, high, name):
    if value is None:
        return None
    if type(value) is not int or not low <= value <= high:
        raise ValueError("INVALID_HISTORY_" + name)
    return value


def _fingerprint(scene, query, person, since, until, window_days, case_sensitive, include_semantic):
    """筛选与范围指纹：游标必须延续发放它的那次筛选（ADR-005 §3），换任何一项都算换页序列。"""
    basis = _json.dumps([scene["scene_id"], scene["policy_epoch"],
                         list(scene.get("readable_scenes") or []),
                         sorted(scene.get("person_aliases") or []),
                         query, person, since, until,
                         window_days, bool(case_sensitive), bool(include_semantic)], ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _wrap_cursor(inner, fingerprint):
    return base64.urlsafe_b64encode(
        _json.dumps({"i": inner, "f": fingerprint}, ensure_ascii=False).encode("utf-8")).decode("ascii")


def _unwrap_cursor(value):
    """只认本服务发放的游标信封；解不开就报错，不静默当第一页重跑，也不让裸位置游标换筛选。"""
    if value is None or value == "":
        return None, None
    try:
        raw = _json.loads(base64.urlsafe_b64decode(str(value).encode("ascii")).decode("utf-8"))
    except Exception:
        raise ValueError("HISTORY_CURSOR_INVALID")
    if not isinstance(raw, dict) or "f" not in raw:
        raise ValueError("HISTORY_CURSOR_INVALID")
    return raw.get("i"), _text(raw.get("f"), 64)


def _cursor_after_delivered(delivered, inner_cursor):
    """传输预算裁剪后的游标：只推进到最后一条已交付命中，被裁的留给下一页原样重发。

    游标只是三支各自的 (时间, 序/回执引用) 位置，筛选每次由任务与参数重建，所以按已交付
    命中重建位置与模块自身翻页等价；命中必带有效时间戳（无时间戳的行进不了时间窗），位置总是可用。"""
    pairs = _cursors(inner_cursor)
    for hit in reversed(delivered):            # 页为倒序：最后一条是最旧交付
        key = _STREAM_BY_FIELD.get(hit.get("time_field"))
        if not key or not hit.get("at"):
            continue
        pairs[key] = [hit["at"], hit.get("time_ref") if key == OUTBOUND_VIA_RECEIPT else hit.get("scene_seq"),
                      hit.get("scene_id")]
    return _encode_cursors(pairs)


def _link_fields(store, scene_doc, person=""):
    """把配置派生的联动范围装进 scene_doc：scene_links 不在就照实不联动。"""
    if scene_links is None:
        return {}
    db = getattr(store, "db", None)
    fields = {"readable_scenes": scene_links.readable_scenes(getattr(store, "config", None),
                                                             scene_doc["scene_id"])}
    try:
        fields["person_classes"] = scene_links.person_classes(getattr(store, "config", None), db)
        fields["person_aliases"] = scene_links.extra_person_values(getattr(store, "config", None),
                                                                   db, person)
        fields["person_canonical"] = dict(
            (member, scene_links.canonical_person_id(getattr(store, "config", None), db, member))
            for member in fields["person_classes"])
    except Exception:
        fields["person_classes"] = fields["person_aliases"] = fields["person_canonical"] = {}
    return fields


class HistoryQueryService:
    """Application/Host 装配用：复用宿主已有的 Store 与 Retrieval，不新开连接、不另起服务。

    ToolBroker 以 query_for_task(task, args) 调用：授权场景来自任务绑定记录，参数只回答
    「查什么词、查谁、哪段时间、一页多少条」。游标延续原筛选与范围——信封里带发放时的
    筛选指纹，换 person/词/时间窗会被明确拒绝；场景绑定由任务记录兜底，游标借不出去。
    """

    def __init__(self, store, retrieval=None):
        self.store, self.retrieval = store, retrieval

    def query_for_task(self, task, args):
        args = args if isinstance(args, dict) else {}
        unknown = set(args) - HISTORY_ARGUMENTS
        if unknown:
            raise ValueError("HISTORY_ARGUMENT_DENIED:" + ",".join(sorted(unknown)))
        scene = self.store.db.scenes.find_one({"_id": task["scene_id"]})
        if (not isinstance(scene, dict) or scene.get("scope_key") != task["scope_key"]
                or scene.get("policy_epoch") != task["policy_epoch"]):
            raise Denied("HISTORY_SCENE_FENCE_MISMATCH")   # 场景与任务不同步就拒查，不猜
        query = _bounded_text(args.get("query"), 300, "QUERY")
        person = _bounded_text(args.get("person"), 60, "PERSON")
        since = _bounded_text(args.get("since"), 40, "SINCE")
        until = _bounded_text(args.get("until"), 40, "UNTIL")
        for name, value in (("SINCE", since), ("UNTIL", until)):
            if value and not _STAMP_SHAPE.match(value):
                raise ValueError("INVALID_HISTORY_" + name)
        window_days = _bounded_int(args.get("window_days"), 1, 90, "WINDOW_DAYS")
        limit = _bounded_int(args.get("limit"), 1, MAX_LIMIT, "LIMIT")
        cursor = _bounded_text(args.get("cursor"), 1024, "CURSOR")
        case_sensitive = args.get("case_sensitive", True)
        if not isinstance(case_sensitive, bool):
            raise ValueError("INVALID_HISTORY_CASE_SENSITIVE")
        include_semantic = args.get("include_semantic", True)
        if not isinstance(include_semantic, bool):
            raise ValueError("INVALID_HISTORY_INCLUDE_SEMANTIC")
        # 围栏比对的是「任务场景 + 它按配置能只读的那些场景」：联动集合现算自配置（不是工具参数），
        # 所以工具既不能把范围换宽，也不能把游标借到另一条边上去。
        scene_doc = {"scene_id": scene["_id"], "scope_key": scene["scope_key"],
                     "policy_epoch": scene["policy_epoch"], "person": person}
        scene_doc.update(_link_fields(self.store, scene_doc, person))
        mark = _fingerprint(scene_doc, query, person, since, until,
                            window_days or DEFAULT_WINDOW_DAYS, case_sensitive, include_semantic)
        inner, stored = _unwrap_cursor(cursor or None)
        if cursor and stored != mark:
            # 游标绑定发放它的筛选：换筛选或指纹对不上就拒查，不给「看似连续」的错页。
            raise ValueError("HISTORY_CURSOR_FILTER_MISMATCH")
        result = query_history(
            self.retrieval if include_semantic else None, self.store, scene_doc,
            query, person=person, window_days=window_days or DEFAULT_WINDOW_DAYS,
            since=since or None, until=until or None, limit=limit or DEFAULT_LIMIT,
            cursor=inner, case_sensitive=case_sensitive)
        return self._payload(result, inner, mark)

    @staticmethod
    def _payload(result, inner_cursor, mark):
        hits = list(result.get("hits") or [])
        trimmed = 0
        while len(hits) > 1 and len(_json.dumps(hits, ensure_ascii=False).encode("utf-8")) > HISTORY_RESULT_BUDGET:
            hits.pop()                # 命中按时间倒序：从尾部（最旧）裁，每页至少留一条完整原文
            trimmed += 1
        more = bool(result.get("more"))
        raw = result.get("next_cursor")
        if trimmed:
            # 被裁命中不能被静默消费：游标回退到最后一条已交付命中，续页原样重发它们。
            more = True
            raw_next = _cursor_after_delivered(hits, inner_cursor)
        else:
            raw_next = raw
        wrapped = _wrap_cursor(raw_next, mark) if more else None
        text = render(result)
        if raw and wrapped:
            # 渲染行里呈现的 cursor 必须与结构化 next_cursor 同值：行动脑照哪个续查都一样。
            text = text.replace(str(raw), str(wrapped))
        if trimmed:
            text += "\n（本页有 %d 条命中因传输预算转入续页：cursor=%s 再查一次即可取回完整原文）" % (trimmed, wrapped)
        semantic = result.get("semantic") or {}
        return {"degraded": bool(result.get("degraded")), "why": result.get("why") or "",
                "text": text, "hits": hits, "hits_trimmed": trimmed,
                "more": more, "next_cursor": wrapped,
                "window": result.get("window"), "limit": result.get("limit"),
                "scope": result.get("scope"), "identity": result.get("identity"),
                "dropped": result.get("dropped") or {},
                "semantic": {key: semantic.get(key) for key in ("ok", "why", "candidates")},
                "fallback": result.get("fallback"), "time_fields": result.get("time_fields")}
