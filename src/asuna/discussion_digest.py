"""ADR-005 P1-c：按需整理当前授权群里指定时间／主题的讨论（同一来源、同一授权）。

宿主侧落点：src/asuna/discussion_digest.py。读原文这一趟完全复用 P1-b 的 history_query：
同一套三支时间（messages.occurred_at / messages.receipt_at / sink_receipts.received_at）、
同一个场景围栏、同一套三支 keyset 游标。本模块不新开集合、不新建总结服务、不调模型、
不碰 QQ 平台（不发送任何东西，测试不需要群里有人回话）。

这一片要回答的是「整理刚才／今天关于某事的讨论」，交付的是**结构化事实**，不是模型摘要：

  - 参与者：按已校验身份归并（身份块没通过校验就退回已认证 author 并标明降级），
    每人条数、首末时间、说的是「对方说」还是「我说」、群身份；
  - 后续更正：带真实 reply 链（入站 event.group_context.reply_message_id、出站 reply_to）
    或文本自称（「上面那条说错了」）的更正，分开标 high／medium／low；更正对象取不到就
    照实说取不到，不猜哪条被推翻；
  - 个人意见：按字面线索标出的主观表态（看法／偏好／反对），每条带命中的线索词；
    机械标注不等于结论，引用哪条由角色看原文决定；
  - 未决事项：提问与「待定」类表述。只有在**同一批读到的行里**有真实 reply 链指回它，
    才算被回答；没有 reply 链的后续表态不自动当答案（那是猜），仍留在未决里；
  - 实际覆盖范围：请求窗口 vs 真正读到的时间跨度、时间来源分布、被排除的行（未送达出站、
    非 SPEAK 出站、没时间戳的行、别的场景）、身份降级条数、语义候选数、还有没有未读。
    「窗口内没匹配」和「没讨论过」是两件事，渲染里写死这句。

来源回读：每条都带 message_id / scene_seq / at / time_source，全文按 P1-b 的
query_authorized_history 回读（readback 里给了能直接照抄的参数）；本模块只带显示片段，
片段一律标明截断，不冒充全文。

续页：游标信封带筛选指纹与 kind='digest'，换 topic／人／时间窗或拿 P1-b 的游标来都会被拒；
more=true 时覆盖范围一定是 partial，说「整段讨论整理完了」就是越界。
"""
import base64
import hashlib
import json
import re
from datetime import timedelta

try:                                  # 宿主内：按包加载
    from .history_query import (DEFAULT_LIMIT, DEFAULT_WINDOW_DAYS, MAX_LIMIT, HISTORY_TOOL_NAME,
                                TIME_SOURCE_INBOUND, TIME_SOURCE_RECEIPT_AT, TIME_SOURCE_SINK,
                                query_history, _parse as _parse_stamp, _text as _norm,
                                _scene_parts, _row_allowed, _outbound_time, _sink_times,
                                _stamp, _hit as _history_hit, person_clause)
except Exception:                     # 同目录平铺加载（离线自检）也认
    try:
        from history_query import (DEFAULT_LIMIT, DEFAULT_WINDOW_DAYS, MAX_LIMIT,
                                   HISTORY_TOOL_NAME, TIME_SOURCE_INBOUND, TIME_SOURCE_RECEIPT_AT,
                                   TIME_SOURCE_SINK, query_history, _parse as _parse_stamp,
                                   _text as _norm, _scene_parts, _row_allowed, _outbound_time,
                                   _sink_times, _stamp, _hit as _history_hit, person_clause)
    except Exception as exc:
        raise ImportError("discussion_digest needs the P1-b history_query module: %s" % exc)

try:
    from .peer_context import peer_from_message, verify_peer, channel_of
except Exception:
    try:
        from peer_context import peer_from_message, verify_peer, channel_of
    except Exception:
        peer_from_message = verify_peer = channel_of = None

try:
    from .state import Denied
except Exception:
    try:
        from state import Denied
    except Exception:
        class Denied(PermissionError):
            pass

IDENTITY_NAMES = ("peer_from_message", "verify_peer", "channel_of")


def identity_status():
    """本模块自己的身份解析状态：不替 P1-b 那份说话，也不另存一份会漂移的副本。"""
    have = [name for name in IDENTITY_NAMES if callable(globals().get(name))]
    return {"resolver": sorted(have), "complete": len(have) == len(IDENTITY_NAMES),
            "missing": [name for name in IDENTITY_NAMES if name not in have],
            "source": ("peer_context" if len(have) == len(IDENTITY_NAMES)
                       else ("peer_context_partial" if have else "none"))}


# ── 字面线索：标注看得见依据，不假装理解语义 ──────────────────────────────
CORRECTION_CUES = ("更正", "纠正", "说错", "说反了", "口误", "打错", "笔误", "写错", "记错",
                   "搞错", "弄错", "应该是", "应是", "改成", "改一下", "撤回", "划掉",
                   "我错了", "我的错", "重新说", "作废", "不算数", "其实不是", "其实应该",
                   "刚才说错")
SELF_REFERENCE_CUES = ("上面那条", "上面那一条", "上面说的", "刚才那条", "刚才那句", "刚才说的",
                       "前面那条", "前面那句", "上一条", "前一条", "刚说的", "这条之前")
DISSENT_CUES = ("反对", "不同意", "不赞同", "不认同", "不太认同", "不赞成", "不接受", "不看好",
                "不太对", "有问题")
PREFERENCE_CUES = ("喜欢", "偏好", "更想", "倾向", "无所谓", "都行", "我站", "更愿意")
OPINION_CUES = ("我觉得", "我认为", "我想", "我建议", "建议", "我猜", "我感觉", "感觉",
                "看起来", "估计", "大概", "也许", "可能是", "我的看法", "个人觉得",
                "个人的看法", "我担心", "不太放心", "依我看", "我这边看")
UNDECIDED_CUES = ("待定", "还没定", "尚未", "未定", "再看", "再看看", "回头", "到时候", "先不",
                  "暂时", "没结论", "没有结论", "待确认", "需要确认", "再议", "商量", "讨论下",
                  "讨论一下", "以后再说", "下次再", "看情况", "不确定", "悬")
QUESTION_CUES = ("怎么", "什么时候", "几点", "谁去", "谁来", "要不要", "行不行", "好不好",
                 "能不能", "有没有", "怎么办", "多少", "是不是", "对吗", "对不")
QUESTION_MARKS = ("？", "?")
CONFIRM_CUES = ("定了", "就这么", "就这样", "我来", "我去", "已经", "搞定", "确认", "好的",
                "可以", "没问题", "同意", "赞成", "那就这样", "约好", "通知", "发出去", "弄好",
                "OK", "ok", "Ok")
ROLE_LABEL = {"owner": "群主", "admin": "管理员", "member": "成员"}
SUBTYPE_LABEL = {"dissent": "反对", "preference": "偏好", "opinion": "看法"}

SNIPPET = 200
MAX_ITEMS_PER_KIND = 40
DIGEST_RESULT_BUDGET = 48 * 1024
DIGEST_TOOL_NAME = "digest_authorized_discussion"


def _first_cue(text, cues):
    for cue in cues:
        if cue and cue in text:
            return cue
    return ""


def _clip(text, limit=SNIPPET):
    body = text if isinstance(text, str) else ""
    return {"text": body[:limit], "chars": len(body), "truncated": len(body) > limit}


def _flat(text, limit=SNIPPET):
    """渲染用：换行压成 ⏎，别把一行拆成多行；截断照实标。"""
    body = " ".join(str(text or "").replace("\x00", " ").replace("\n", "⏎").split())
    return body if len(body) <= limit else "%s…〔截断，全文 %d 字〕" % (body[:limit], len(body))


def _shift(stamp, seconds):
    """把 ISO 时间挪几秒，给来源回读圈一个能命中该条的小窗口；解析不了就空。"""
    moment = _parse_stamp(stamp)
    if moment is None:
        return ""
    return (moment + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _group_id_of(scene_id):
    parts = _norm(scene_id, 80).lower().split(":")
    for i, token in enumerate(parts):
        if token == "group" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


# ── 一次批量读：reply 链 + 身份块（不逐行轮询，不猜） ──────────────────
LINKAGE_PROJECTION = {"_id": 1, "reply_to": 1, "author": 1, "direction": 1,
                      "event.group_context": 1, "event.raw.asuna_peer": 1, "event.channel": 1}


def read_linkage(store, message_ids, scene=None):
    """{message_id: 文档片段}。读不到就说 digest_linkage_unavailable，不静默少信息。

    reply 链在真实宿主里是两个形状，分开读：入站在 event.group_context.reply_message_id
    （channels.group_context 已经把平台 reply 段绑到本场景真实记录上），出站 SPEAK 行在
    reply_to（coordinator 写的是发起它的入站记录 id）。身份块仍只读 adapter 那一层。
    """
    ids = [mid for mid in message_ids if isinstance(mid, str) and mid]
    if not ids:
        return {}, ""
    column = getattr(getattr(store, "db", None), "messages", None)
    if column is None:
        return {}, "no_messages_collection"
    try:
        flt = {"_id": {"$in": sorted(set(ids))}}
        if isinstance(scene, dict):      # 同一道围栏：链与身份块也只读本场景、本策略周期
            flt["scene_id"] = scene["scene_id"]
            flt["policy_epoch"] = scene["policy_epoch"]
        rows = list(column.find(flt, projection=LINKAGE_PROJECTION) or [])
    except Exception as exc:
        return {}, "digest_linkage_unavailable:%s" % type(exc).__name__
    out = {}
    for row in rows:
        if isinstance(row, dict) and row.get("_id"):
            out[str(row["_id"])] = row
    return out, ""


def reply_target_of(doc):
    """这一行真实回复了哪条（宿主记录 id）；没有就空字符串。"""
    if not isinstance(doc, dict):
        return ""
    if _norm(doc.get("direction"), 16) == "outbound":
        return _norm(doc.get("reply_to"), 80)
    event = doc.get("event") if isinstance(doc.get("event"), dict) else {}
    group = event.get("group_context") if isinstance(event.get("group_context"), dict) else None
    return _norm((group or {}).get("reply_message_id"), 80)


THREAD_PROJECTION = {"_id": 1, "text": 1, "author": 1, "direction": 1, "phase": 1,
                     "delivery_state": 1, "occurred_at": 1, "receipt_at": 1, "receipt": 1,
                     "scene_seq": 1, "scene_id": 1, "policy_epoch": 1, "reply_to": 1,
                     "event.group_context": 1, "event.raw.asuna_peer": 1, "event.channel": 1}
REPLY_TARGET_KEYS = ("event.group_context.reply_message_id", "reply_to")   # 入站／出站两个形状
MAX_THREAD_ROWS = 60            # 一条讨论流最多带这么多链内后续，超了照实说没展开完
MAX_THREAD_ROUNDS = 8           # 每轮一条查询（找谁的回复＋找被回复的那条），不按行轮询
MAX_THREAD_CARRY = 64           # 跨页去重集合随游标往下带的上限（cursor 有 1024 字上限）
MAX_THREAD_PENDING = 64         # 随游标带下去的待走环节上限：超了照实说丢了分支


def _lookup_doc(doc, key):
    value = doc
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return False, None
    return True, value


def _topic_match(doc, topic, case_sensitive):
    body = doc.get("text")
    text = body if isinstance(body, str) else ""
    if not topic or not text:
        return False
    return (topic in text) if case_sensitive else (topic.lower() in text.lower())


def _person_match(doc, person):
    """这条发言是不是这个人说的：直接复用 P1-b 的 person_clause，不另写一份「谁说的」口径。"""
    if not person:
        return False
    for sub in (person_clause(person) or {}).get("$or") or []:
        for key, value in sub.items():
            found, got = _lookup_doc(doc, key)
            if not found:
                continue
            values = got if isinstance(got, list) else [got]
            if any(isinstance(item, str) and item.lower() == _norm(value, 60).lower()
                   for item in values):
                return True
    return False


def _seed_eligible(doc, topic, person, case_sensitive):
    """这一行本身就会被字面筛选读到吗？会的话它总会在某一页作为命中项出现，不该再当链内后续送一遍。

    这是跨页不重复的关键：一行要么作为命中项被它所在那一页送（keyset 游标保证不重不漏），
    要么作为链内后续被链到它的那一页送，两边不会都送。
    """
    return _topic_match(doc, topic, case_sensitive) or _person_match(doc, person)


def _thread_hit(doc, parts, sink_times):
    """给链内后续行算出与 P1-b 完全同一口径的时间，再拼成一条命中。"""
    if _norm(doc.get("direction"), 16) == "outbound":
        at, field, _source, ref, _why = _outbound_time(doc, sink_times)
    else:
        at, field, ref = _stamp(doc.get("occurred_at")), "occurred_at", ""
    if not at:
        return None
    return _history_hit(doc, parts, "text", field, at=at, time_ref=ref)


def read_thread_continuations(store, scene, seed_ids, window, known, seed_docs=None,
                              carried=(), topic="", person="", case_sensitive=True, resume=None):
    """沿真实 reply 链把同一讨论流补齐：命中项的回复、被它回复的那条，以及它们后续的链。

    按主题整理时，后续更常几乎不再重复主题词（“更正一下：是一米五，不是两米”）。只按字面
    匹配就会把这条更正连同它的对象一起丢掉，覆盖范围也跟着说谎。所以这里只认 reply 链，
    不认时间邻近：交错在中间、没跟命中项连成链的别的话题不会被拉进来，不会冒充这条主题的
    结论。范围规则仍走 P1-b 那一套：同场景、同策略周期、同一时间窗，入站看 occurred_at，
    已送达出站看 receipt_at／sink_receipts.received_at，没时间戳的行不进覆盖范围。

    四条不静默的规则：本身就会被字面筛选读到的行不当链内后续送（它由自己那一页送，跨页不
    重复）；上一页送过的链内后续随游标带下来跳过（同一行不送两遍）；轮数或条数上限到了还有
    下一环就标 truncated 并把待走环节交给游标（`pending`／`pending_wanted`），下一页沿同一筛选
    继续走；链上带进来的发言按 `_person_match` 标 `person_match`，别人说的不冒充 person 指定的人。
    """
    stats = {"extra": 0, "out_of_window": 0, "rounds": 0, "truncated": False, "why": "",
             "sink_why": "", "skipped_seed_eligible": 0, "skipped_carried": 0,
             "delivered": [], "carry_truncated": False, "pending": [], "pending_wanted": [],
             "pending_truncated": False, "resumed": False}
    column = getattr(getattr(store, "db", None), "messages", None)
    parts = _scene_parts(scene)
    seeds = [mid for mid in seed_ids if isinstance(mid, str) and mid]
    resume = resume if isinstance(resume, dict) else {}
    pending = [mid for mid in resume.get("frontier") or [] if isinstance(mid, str) and mid]
    if column is None or parts is None or (not seeds and not pending):
        return {}, {}, stats
    if resume.get("literal_done"):
        stats["resumed"] = True
        if resume.get("window"):
            window = list(resume["window"])     # 续读沿用发放游标那一页的时间窗，不随「现在」漂
    pair = tuple(window) if window and len(window) == 2 else None
    docs, hits = {}, {}
    delivered = set(_norm(mid, 80) for mid in carried if mid)
    # 已送过的环节不再按 id 重取（只需沿它们往下走），否则续读会把整条链倒着再走一遗
    fetched = set(seeds) | set(_norm(mid, 80) for mid in (known or set()) if mid) | delivered
    # seen 只记本次调用里算过的行：上一页送过的要走到 skipped_carried，不能默默消失
    seen = set(seeds) | set(_norm(mid, 80) for mid in (known or set()) if mid)
    frontier = list(dict.fromkeys(seeds + pending))   # 要找“谁回复了这些”（含上一页没走完的环节）
    wanted = set(mid for mid in resume.get("wanted") or [] if isinstance(mid, str) and mid)
    stats["pending_truncated"] = bool(resume.get("lost"))   # 上一页因上限丢了分支：这一页仍算不完整
    for doc in (seed_docs or {}).values():
        target = reply_target_of(doc)
        if target and target not in fetched:
            wanted.add(target)
    queried = set()
    remaining = list(frontier)
    for _round in range(MAX_THREAD_ROUNDS):
        if not frontier and not wanted:
            remaining = []
            break
        stats["rounds"] += 1
        queried.update(frontier)
        branches = [{key: {"$in": sorted(set(frontier))}} for key in REPLY_TARGET_KEYS]
        if wanted:
            branches.append({"_id": {"$in": sorted(wanted)}})
        flt = {"scene_id": parts["scene_id"], "policy_epoch": parts["epoch"], "$or": branches}
        try:
            found = list(column.find(flt, projection=THREAD_PROJECTION) or [])
        except Exception as exc:
            stats["why"] = "digest_thread_unavailable:%s" % type(exc).__name__
            break
        refs = set()
        for doc in found:
            if _norm(doc.get("direction"), 16) == "outbound" and not _stamp(doc.get("receipt_at")):
                ref = doc.get("receipt")
                if isinstance(ref, str) and ref:
                    refs.add(ref)
        sink_times, why = _sink_times(store, refs)
        if why:
            stats["sink_why"] = why    # 送达回执那一支接不上：只影响出站时间，不算链没展开
        nxt, wanted_next = [], set()
        for doc in found:
            mid = str(doc.get("_id") or "")
            if not mid:
                continue
            fetched.add(mid)                             # 这一环的文档已经拿过，不必再按 id 取
            target = reply_target_of(doc)
            if target and target not in fetched:
                wanted_next.add(target)        # 它回复的那条也在这条链上
            nxt.append(mid)                    # 它的回复下一轮再找
            if mid in seen:
                continue
            seen.add(mid)
            if _seed_eligible(doc, topic, person, case_sensitive):
                stats["skipped_seed_eligible"] += 1
                continue                       # 它由自己那一页作为命中项送，不在这里重复
            if mid in delivered:
                stats["skipped_carried"] += 1
                continue                       # 上一页已经作为链内后续送过
            if not _row_allowed(doc, parts, pair, sink_times):
                stats["out_of_window"] += 1     # 在链上，但窗口外或没时间戳：不假装读到了
                continue
            hit = _thread_hit(doc, parts, sink_times)
            if hit is None:
                stats["out_of_window"] += 1
                continue
            hit["thread"] = True
            hit["person_match"] = not person or _person_match(doc, person)
            docs[mid], hits[mid] = doc, hit
            if len(docs) >= MAX_THREAD_ROWS:
                stats["truncated"] = True
                stats["why"] = "thread_row_cap"
                break
        fetched |= wanted
        wanted = wanted_next - fetched
        remaining = [mid for mid in dict.fromkeys(nxt) if mid not in queried] + sorted(wanted)
        frontier = remaining
        if stats["truncated"]:
            break
    leftover = sorted(set(remaining) | wanted)
    stats["pending"] = sorted(set(remaining))[:MAX_THREAD_PENDING]
    stats["pending_wanted"] = sorted(wanted)[:MAX_THREAD_PENDING]
    if len(leftover) > MAX_THREAD_PENDING:
        stats["pending_truncated"] = True       # 待走环节带不下：丢掉的分支照实说，不假装走完了
    if leftover or stats["pending_truncated"]:
        stats["truncated"] = True               # 还有环节没走：不能说整条链读完了
        if not stats["why"]:                    # 链查询自己失败了就保留那个原因
            stats["why"] = "thread_rounds_exhausted"
    stats["extra"] = len(docs)
    stats["delivered"] = sorted(docs)
    return docs, hits, stats


def _peer_of(doc):
    """(person_id, display, role, verified, identity)；身份块不可用就退回记录作者。"""
    if not (callable(peer_from_message) and callable(verify_peer) and callable(channel_of)):
        return "", "", "", False, "author"
    try:
        peer = peer_from_message(doc)
        ok, _reason = verify_peer(peer, channel_of(doc))
    except Exception:
        return "", "", "", False, "author"
    if not ok or not isinstance(peer, dict):
        return "", "", "", False, "author"
    display = (_norm(peer.get("card"), 60) or _norm(peer.get("nickname"), 60)
               or _norm(peer.get("display"), 60))
    return (_norm(peer.get("person_id"), 40), display or "未取到名字",
            _norm(peer.get("role"), 16), bool(peer.get("verified")), "peer")


# ── 整理主干 ───────────────────────────────────────────────────
def _row(hit, doc):
    peer_id, display, role, verified, identity = _peer_of(doc)
    author = _norm(hit.get("author"), 40)
    body = hit.get("text") if isinstance(hit.get("text"), str) else ""
    seq = hit.get("scene_seq")
    doc = doc if isinstance(doc, dict) else {}
    if not doc:
        doc = {"author": author, "direction": hit.get("direction")}
    return {"id": _norm(hit.get("message_id"), 80), "seq": seq if isinstance(seq, int) else -1,
            "at": _norm(hit.get("at"), 32), "time_source": _norm(hit.get("time_source"), 40),
            "direction": _norm(hit.get("direction"), 16), "side": _norm(hit.get("side"), 16),
            "author": author, "person_id": peer_id, "display": display or author or "?",
            "role": role, "verified": verified, "identity": identity,
            "text": body, "reply_to": reply_target_of(doc), "via": _norm(hit.get("via"), 16),
            "thread": bool(hit.get("thread")),
            "person_match": bool(hit.get("person_match", True))}


def _key(row):
    """已校验身份按 person_id 归并；同一个人改名不会拆成两个人（person_id 不变）。

    身份块不可用就只能按记录作者归并，并在参与者条目里标明降级，不假装认得。
    """
    return row["person_id"] if row["identity"] == "peer" and row["person_id"] \
        else ("author:" + row["author"])


def build_digest(hits, docs, meta, *, snippet=SNIPPET):
    """把 P1-b 命中整理成参与者／更正／意见／未决／覆盖范围。

    处理按时间正序（讨论是往前发生的），渲染另说。meta 带查询侧事实（窗口、more、fallback、
    semantic、dropped、excluded、topic、person），覆盖范围只从这些真实计数拼出来。
    """
    rows = sorted([_row(hit, docs.get(_norm(hit.get("message_id"), 80))) for hit in hits],
                  key=lambda row: (row["at"], row["seq"]))
    index = dict((row["id"], row) for row in rows if row["id"])
    participants, corrections, opinions, open_items, replies = {}, [], [], [], []
    undated = 0
    for row in rows:
        key = _key(row)
        person = participants.get(key)
        if person is None:
            person = {"key": key, "person_id": row["person_id"], "display": row["display"],
                      "role": ROLE_LABEL.get(row["role"], row["role"]), "side": row["side"],
                      "identity": row["identity"], "messages": 0, "inbound": 0, "outbound": 0,
                      "first_at": row["at"], "last_at": row["at"], "corrections": 0,
                      "opinions": 0, "questions": 0, "open_items": 0, "replies": 0,
                      "outside_person": 0}
            participants[key] = person
        person["messages"] += 1
        if not row["person_match"]:
            person["outside_person"] += 1
        person["inbound" if row["direction"] != "outbound" else "outbound"] += 1
        person["first_at"] = min(person["first_at"], row["at"])
        person["last_at"] = max(person["last_at"], row["at"])
        if not row["at"]:
            undated += 1
        if row["reply_to"]:
            person["replies"] += 1
            replies.append({"message_id": row["id"], "at": row["at"], "who": row["display"],
                            "in_reply_to": row["reply_to"],
                            "target_in_scope": row["reply_to"] in index})
        text = row["text"]
        correction = _first_cue(text, CORRECTION_CUES)
        if correction:
            target = row["reply_to"] if row["reply_to"] in index else ""
            if target:
                basis, confidence = "reply_link", "high"
            elif row["reply_to"]:
                basis, confidence = "reply_link_out_of_scope", "medium"
            elif _first_cue(text, SELF_REFERENCE_CUES):
                basis, confidence = "self_reference", "medium"
            else:
                basis, confidence = "cue_only", "low"
            target_row = index.get(target)
            person["corrections"] += 1
            corrections.append(dict(_clip(text, snippet), message_id=row["id"], at=row["at"],
                                    who=row["display"], person_id=row["person_id"], cue=correction,
                                    basis=basis, confidence=confidence,
                                    corrects=target or _norm(row["reply_to"], 80),
                                    target_author=(target_row or {}).get("display", ""),
                                    target_in_scope=bool(target_row),
                                    self_correction=bool(target_row) and _key(target_row) == key,
                                    later_than_target=bool(target_row) and (target_row["at"],
                                                                            target_row["seq"])
                                    < (row["at"], row["seq"]),
                                    time_source=row["time_source"]))
        dissent, preference = _first_cue(text, DISSENT_CUES), _first_cue(text, PREFERENCE_CUES)
        opinion = dissent or preference or _first_cue(text, OPINION_CUES)
        if opinion and not correction:
            person["opinions"] += 1
            subtype = "dissent" if dissent else ("preference" if preference else "opinion")
            opinions.append(dict(_clip(text, snippet), message_id=row["id"], at=row["at"],
                                 who=row["display"], person_id=row["person_id"], subtype=subtype,
                                 cue=opinion, replies_to=_norm(row["reply_to"], 80),
                                 target_in_scope=bool(row["reply_to"]) and row["reply_to"] in index,
                                 time_source=row["time_source"]))
        asked = any(mark in text for mark in QUESTION_MARKS) or bool(_first_cue(text, QUESTION_CUES))
        undecided = _first_cue(text, UNDECIDED_CUES)
        if asked:
            person["questions"] += 1
        if asked or undecided:
            person["open_items"] += 1
            item = {"message_id": row["id"], "at": row["at"], "who": row["display"],
                    "person_id": row["person_id"],
                    "kind": ("question" if asked and not undecided else
                             ("undecided" if undecided and not asked else "question_or_undecided")),
                    "cue": _first_cue(text, QUESTION_CUES) or undecided or "？",
                    "undecided_cue": undecided, "status": "open", "answered_by": "",
                    "answer_confirms": False, "note": "", "time_source": row["time_source"]}
            item.update(_clip(text, snippet))
            open_items.append(item)
    # 回答只按真实 reply 链判定：同一批里有更晚的一行回复它，才算被回应。
    answered = {}
    for row in rows:
        target = index.get(row["reply_to"])
        if target and (target["at"], target["seq"]) < (row["at"], row["seq"]):
            answered.setdefault(row["reply_to"], []).append(row)
    resolved = []
    for item in open_items:
        for reply in answered.get(item["message_id"], []):
            item["answered_by"] = reply["id"]
            item["answer_confirms"] = bool(_first_cue(reply["text"], CONFIRM_CUES))
            item["note"] = "有真实 reply 链指回本条（%s 回应）" % reply["display"]
            break
        if item["answered_by"]:
            item["status"] = "answered"
            resolved.append(item)
        else:
            item["note"] = "读到的范围里没有 reply 链指回本条；可能被口头回应过，但这里不能当已决"
    open_items = [item for item in open_items if item["status"] == "open"]
    meta["person_context_rows"] = len([row for row in rows if not row["person_match"]])
    for bucket in (corrections, opinions, open_items, resolved, replies):
        for item in bucket:
            origin = index.get(item["message_id"])
            item["thread"] = bool(origin and origin["thread"])
            item["person_match"] = True if origin is None else bool(origin.get("person_match", True))
    notes = _notes(meta, participants, undated)
    coverage = _coverage(rows, meta, undated)
    trimmed = 0
    for bucket in (corrections, opinions, open_items, resolved, replies):
        if len(bucket) > MAX_ITEMS_PER_KIND:
            trimmed += len(bucket) - MAX_ITEMS_PER_KIND
            del bucket[MAX_ITEMS_PER_KIND:]
    if trimmed:
        coverage["budget_trimmed"] = trimmed
        notes.append("整理项超出单类上限 %d 条，裁掉 %d 条（原文 id 仍在 source_ids）："
                     "缩小时间窗或加 topic 重查" % (MAX_ITEMS_PER_KIND, trimmed))
    return {"coverage": coverage, "participants": list(participants.values()),
            "corrections": corrections, "opinions": opinions, "open_items": open_items,
            "resolved": resolved, "replies": replies, "notes": notes,
            "source_ids": [row["id"] for row in rows]}


def _coverage(rows, meta, undated):
    """覆盖范围只从真实计数拼：请求窗口≠实际读到的跨度，未读≠没有。"""
    dated = [row for row in rows if row["at"]]
    fallback = meta.get("fallback") or {}
    sources = {}
    for row in rows:
        label = row["time_source"] or "无来源标注"
        sources[label] = sources.get(label, 0) + 1
    return {"scene_id": meta["scene_id"], "group_id": meta.get("group_id", ""),
            "policy_epoch": meta.get("policy_epoch"), "topic": meta.get("topic", ""),
            "person": meta.get("person", ""), "window": list(meta.get("window") or []),
            "covered_from": dated[0]["at"] if dated else "",
            "covered_to": dated[-1]["at"] if dated else "",
            "read": len(rows), "inbound": len([r for r in rows if r["direction"] != "outbound"]),
            "outbound": len([r for r in rows if r["direction"] == "outbound"]),
            "undated": undated, "time_sources": sources,
            "matched": len([r for r in rows if not r["thread"]]),
            "thread_extra": len([r for r in rows if r["thread"]]),
            "person_scope": "seed" if meta.get("person") else "",
            "person_context_rows": meta.get("person_context_rows", 0),
            "thread": dict(meta.get("thread") or {}),
            "excluded": meta.get("excluded") or {}, "excluded_why": meta.get("excluded_why", ""),
            "dropped": meta.get("dropped") or {},
            "identity_fallback": len([r for r in rows if r["identity"] != "peer"]),
            "semantic_candidates": (meta.get("semantic") or {}).get("candidates", 0),
            "fallback_scanned": fallback.get("scanned", 0),
            "fallback_exhausted": bool(fallback.get("exhausted", True)),
            "budget_trimmed": 0, "cursor": "",
            "more": bool(meta.get("more")),
            "complete": (not meta.get("more")) and not (meta.get("thread") or {}).get("truncated")
                        and (not fallback.get("attempted")
                             or bool(fallback.get("exhausted", True)))}


def _notes(meta, participants, undated):
    notes = []
    ident = meta.get("identity") or {}
    if ident and not ident.get("complete"):
        notes.append("身份解析没接上（缺 %s），参与者只按记录作者归并"
                     % "/".join(ident.get("missing") or []))
    degraded = [person for person in participants.values() if person["identity"] != "peer"]
    if degraded and ident.get("complete", True):
        notes.append("%d 位发言人没有身份块或身份块没通过校验，按已认证记录作者标注" % len(degraded))
    semantic = meta.get("semantic") or {}
    if not semantic.get("ok") and semantic.get("why") != "not_attempted":
        notes.append("语义候选没成（%s），整理只基于字面读到的 messages" % semantic.get("why"))
    if semantic.get("candidates"):
        notes.append("另有 %d 条语义候选并入：语义候选不等于全部原话" % semantic["candidates"])
    fallback = meta.get("fallback") or {}
    if fallback.get("why"):
        notes.append("本机出站的送达时间没关联上（%s）：这些行按没时间戳处理，不进覆盖范围"
                     % fallback["why"])
    if fallback.get("attempted") and not fallback.get("exhausted"):
        notes.append("本机送达回执这一页翻了 %d 条还没翻到底，剩下的在续页"
                     % fallback.get("scanned", 0))
    if undated:
        notes.append("%d 行没有可用时间戳，没算进覆盖范围（没时间戳就不能声称在某段时间内）" % undated)
    excluded = meta.get("excluded") or {}
    if excluded:
        notes.append("本场景内另有 %s 条未送达出站、%s 条非 SPEAK 出站没算进讨论（这两项不按时间窗）"
                     % (excluded.get("undelivered_outbound", "?"),
                        excluded.get("non_speak_outbound", "?")))
    if meta.get("linkage_why"):
        notes.append("reply 链没读到（%s）：更正只能按文本自称标注，对象不猜" % meta["linkage_why"])
    thread = meta.get("thread") or {}
    if thread.get("extra"):
        notes.append("带上 %d 条不含主题词的同一 reply 链后续（只认 reply 链，不按时间邻近拉别的"
                     "话题）：它们计入覆盖范围，但不算主题匹配" % thread["extra"])
    if thread.get("out_of_window"):
        notes.append("另有 %d 条同链后续落在请求窗口外或没有可用时间戳，没算进覆盖范围"
                     % thread["out_of_window"])
    if meta.get("person") and meta.get("person_context_rows"):
        notes.append("person 只限定主题命中项是谁说的（%s）：另有 %d 条是按 reply 链带进来的"
                     "上下文发言，来自别人，条目标 person_match=false／thread_context，"
                     "不算那个人自己说的" % (meta["person"], meta["person_context_rows"]))
    if thread.get("resumed"):
        notes.append("本页是上一页讨论流的续读（字面命中已读完，只沿 reply 链接着走）："
                     "时间窗沿用发放游标那一页，不随现在漂")
    if thread.get("pending_truncated"):
        notes.append("待走环节超出随游标携带的上限 %d 条：丢掉的分支这一页没读到，"
                     "覆盖范围仍算部分完成" % MAX_THREAD_PENDING)
    if thread.get("truncated") or thread.get("why"):
        notes.append("讨论流没完全展开（%s）：覆盖范围算部分完成，这条主题可能还有别的行%s"
                     % ("%s／上限 %d 条 %d 轮" % (thread.get("why") or "到上限",
                                                MAX_THREAD_ROWS, MAX_THREAD_ROUNDS),
                        "；带 cursor 续页会沿同一筛选接着读剩下的环节"
                        if (thread.get("pending") or thread.get("pending_wanted")) else ""))
    if thread.get("skipped_seed_eligible"):
        notes.append("%d 条链上环节本身就是主题命中项，由它所在那一页作为原文送，"
                     "不在这里重复计入" % thread["skipped_seed_eligible"])
    if thread.get("skipped_carried"):
        notes.append("%d 条链上环节在前一页已经作为链内后续送过，本页不重复送"
                     % thread["skipped_carried"])
    if thread.get("carry_truncated"):
        notes.append("跨页去重集合超出 %d 条上限：后面的页有可能重复送某条链内后续"
                     % MAX_THREAD_CARRY)
    if meta.get("more"):
        notes.append("还有更早的没读（more=true）：本次只覆盖上面的时间跨度，"
                     "续页前不能说「整段讨论整理完了」")
    if meta.get("topic"):
        notes.append("topic 是字面匹配：窗口内没匹配不等于没讨论过这件事")
    notes.append("分类是按字面线索的机械标注（每条带 cue 与依据），不是结论；"
                 "引用原文以 message_id 回读为准")
    return notes


# ── 渲染：给行动脑读的几行；结构化字段在 payload 里另有一份 ───────────
def _bucket(title, items, line):
    if not items:
        return []
    def mark(item):
        if not item.get("thread"):
            return ""
        return "〔线程内后续，不含主题词%s〕" % (
            "；非 person 指定" if item.get("person_match") is False else "")
    return ["%s %d 条：" % (title, len(items))] + [
        "  - " + line(item) + mark(item) for item in items]


def _correction_line(item):
    target = item["corrects"] or "未取到"
    if not item["corrects"]:
        tail = "〔依据「%s」／%s／没指明对象〕" % (item["cue"], item["confidence"])
    elif not item["target_in_scope"]:
        tail = "〔依据「%s」／%s／对象 %s 不在本次读到的范围〕" % (item["cue"], item["confidence"], target)
    else:
        tail = "〔依据「%s」／%s／对象 %s（%s）%s〕" % (
            item["cue"], item["confidence"], target, item["target_author"],
            "；自我更正" if item["self_correction"] else "")
    return "%s %s：%s%s" % (item["at"][11:16], item["who"], _flat(item["text"]), tail)


def render(digest, header="群讨论整理"):
    cov = digest["coverage"]
    stamp = lambda value: (value or "?")[:16].replace("T", " ")
    window = " → ".join([stamp(v) for v in cov["window"]]) or "?"
    if cov["complete"]:
        state = "覆盖完整"
    elif (cov.get("thread") or {}).get("truncated"):
        state = "部分覆盖（讨论流没走完）"      # 与「还有未读原文」不同：这一支只能沿 cursor 接着走
    else:
        state = "部分覆盖（还有未读）"
    if cov.get("thread_extra"):
        state += "｜主题匹配 %d／链内后续 %d" % (cov.get("matched", 0), cov["thread_extra"])
    lines = ["[%s｜场景 %s｜请求窗口 %s｜实际读到 %s → %s｜%d 条（对方 %d／我说 %d）｜参与者 %d 人｜%s]" % (
        header, cov["scene_id"], window, stamp(cov["covered_from"]), stamp(cov["covered_to"]),
        cov["read"], cov["inbound"], cov["outbound"], len(digest["participants"]), state)]
    if digest["participants"]:
        bits = []
        for person in sorted(digest["participants"], key=lambda p: -p["messages"]):
            extra = "；".join([x for x in (
                person["role"], person["side"],
                "身份未校验" if person["identity"] != "peer" else "",
                "thread_context（非 person 指定）" if person.get("outside_person")
                and person["outside_person"] == person["messages"] else "") if x])
            bits.append("%s（%s；%d 条，%s–%s）" % (
                person["display"], extra, person["messages"],
                person["first_at"][11:16] or "?", person["last_at"][11:16] or "?"))
        lines.append("参与者：" + "；".join(bits))
    else:
        lines.append("参与者：这一页没读到任何发言")
    lines.extend(_bucket("后续更正", digest["corrections"], _correction_line))
    lines.extend(_bucket("个人意见", digest["opinions"], lambda item: "%s %s（%s，线索「%s」）：%s" % (
        item["at"][11:16], item["who"], SUBTYPE_LABEL[item["subtype"]], item["cue"],
        _flat(item["text"]))))
    lines.extend(_bucket("未决事项", digest["open_items"], lambda item: "%s %s：%s〔%s，线索「%s」；%s〕" % (
        item["at"][11:16], item["who"], _flat(item["text"]), item["kind"], item["cue"], item["note"])))
    lines.extend(_bucket("已被回应", digest["resolved"], lambda item: "%s %s：%s〔被 %s 回应%s〕" % (
        item["at"][11:16], item["who"], _flat(item["text"]), item["answered_by"],
        "，回复里带确认措辞" if item["answer_confirms"] else "")))
    for note in digest["notes"]:
        lines.append("· " + note)
    if cov.get("cursor"):
        lines.append("（续页 cursor=%s）" % cov["cursor"])
    lines.append("（每条原文按 message_id 回读：%s；片段是显示截断，不冒充全文）" % HISTORY_TOOL_NAME)
    return "\n".join(lines)


# ── 宿主接线：现有 ToolBroker 内的受信只读入口 ──────────────────────
DIGEST_TOOL = {
    "name": DIGEST_TOOL_NAME,
    "description": ("按需整理当前授权群指定时间／主题的讨论（只读，不发 QQ 消息）：与历史查询同一来源，"
                    "分开返回参与者、后续更正、个人意见、未决事项与实际覆盖范围；每条带 message_id、"
                    "时间及其来源，可按 query_authorized_history 回读原文。分类是按字面线索的机械标注，"
                    "不是结论；more=true 表示只覆盖了部分（还有未读原文，或同一 reply 链的讨论流没走完），"
                    "必须带 cursor 续页后才能说整理完整。person 只限定主题命中项是谁说的：同一 reply 链"
                    "带进来的上下文发言可能来自别人，条目带 person_match=false、参与者标 thread_context。"),
    "parameters": {
        "topic": {"type": "string"},
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
DIGEST_ARGUMENTS = set(DIGEST_TOOL["parameters"])
_STAMP_SHAPE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9:.+Z-]{0,24})?$")


def _bounded_text(value, limit, name):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 4 * limit:
        raise ValueError("INVALID_DIGEST_" + name)
    return value


def _bounded_int(value, low, high, name):
    if value is None:
        return None
    if type(value) is not int or not low <= value <= high:
        raise ValueError("INVALID_DIGEST_" + name)
    return value


def _fingerprint(scene, topic, person, since, until, window_days, case_sensitive, include_semantic):
    """筛选与范围指纹：游标必须延续发放它的那次筛选，换任何一项都算换页序列。"""
    basis = json.dumps(["digest", scene["scene_id"], scene["policy_epoch"], topic, person, since,
                        until, window_days, bool(case_sensitive), bool(include_semantic)],
                       ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _wrap_cursor(inner, fingerprint, delivered=(), state=None):
    """游标信封：筛选指纹＋“已作为链内后续送过”的 id＋讨论流待走环节。三样都装在既有
    cursor 参数里，不开新接口；待走环节是截断后的续页入口，不能丢。"""
    body = {"k": "digest", "i": inner, "f": fingerprint}
    if delivered:
        body["d"] = list(delivered)[:MAX_THREAD_CARRY]
    if state:
        body["t"] = state
    return base64.urlsafe_b64encode(json.dumps(body, ensure_ascii=False)
                                    .encode("utf-8")).decode("ascii")


def _unwrap_cursor(value):
    """只认本服务发放的信封；P1-b 的游标、裸位置游标、乱写的都拒，不当第一页重跑。"""
    if value is None or value == "":
        return None, None, [], {}
    try:
        raw = json.loads(base64.urlsafe_b64decode(str(value).encode("ascii")).decode("utf-8"))
    except Exception:
        raise ValueError("DIGEST_CURSOR_INVALID")
    if not isinstance(raw, dict) or raw.get("k") != "digest" or "f" not in raw:
        raise ValueError("DIGEST_CURSOR_INVALID")
    delivered = raw.get("d") or []
    state = raw.get("t") or {}
    if not isinstance(delivered, list) or not isinstance(state, dict):
        raise ValueError("DIGEST_CURSOR_INVALID")
    for key in ("frontier", "wanted", "window"):
        if key in state and not isinstance(state[key], list):
            raise ValueError("DIGEST_CURSOR_INVALID")
    return (raw.get("i"), _norm(raw.get("f"), 64),
            [_norm(mid, 80) for mid in delivered if mid], state)


def _excluded_counts(store, scene_doc):
    """被规则排除的出站行计数：读不到就照实说读不到，不给「没有排除项」的假安心。"""
    column = getattr(getattr(store, "db", None), "messages", None)
    if column is None:
        return {}, "no_messages_collection"
    base = {"scene_id": scene_doc["scene_id"], "policy_epoch": scene_doc["policy_epoch"],
            "direction": "outbound"}
    wanted = {"undelivered_outbound": dict(base, phase="SPEAK",
                                          delivery_state={"$ne": "DELIVERED"}),
              "non_speak_outbound": dict(base, phase={"$ne": "SPEAK"})}
    out = {}
    for name, flt in wanted.items():
        try:
            counter = getattr(column, "count_documents", None)
            out[name] = int(counter(flt)) if callable(counter) else len(list(column.find(flt) or []))
        except Exception as exc:
            return out, "excluded_count_failed:%s" % type(exc).__name__
    return out, ""


class DiscussionDigestService:
    """Application/Host 装配用：复用宿主已有的 Store 与 Retrieval，不新开连接、不另起服务。

    ToolBroker 以 digest_for_task(task, args) 调用：授权场景来自任务绑定记录；参数只回答
    「整理哪个主题、哪段时间、看谁的、一页读多少条原文」。游标延续发放它时的筛选，并带
    kind='digest'：拿 P1-b 的游标或换筛选复用都会被明确拒，不给「看似连续」的错页。
    """

    def __init__(self, store, retrieval=None):
        self.store, self.retrieval = store, retrieval

    def digest_for_task(self, task, args):
        args = args if isinstance(args, dict) else {}
        unknown = set(args) - DIGEST_ARGUMENTS
        if unknown:
            raise ValueError("DIGEST_ARGUMENT_DENIED:" + ",".join(sorted(unknown)))
        scene = self.store.db.scenes.find_one({"_id": task["scene_id"]})
        if (not isinstance(scene, dict) or scene.get("scope_key") != task["scope_key"]
                or scene.get("policy_epoch") != task["policy_epoch"]):
            raise Denied("DIGEST_SCENE_FENCE_MISMATCH")     # 场景与任务不同步就拒查，不猜
        topic_arg, query_arg = args.get("topic"), args.get("query")
        if topic_arg is not None and query_arg is not None and topic_arg != query_arg:
            raise ValueError("DIGEST_ARGUMENT_CONFLICT:topic/query")
        topic = _bounded_text(topic_arg if topic_arg is not None else query_arg, 300, "TOPIC")
        person = _bounded_text(args.get("person"), 60, "PERSON")
        since = _bounded_text(args.get("since"), 40, "SINCE")
        until = _bounded_text(args.get("until"), 40, "UNTIL")
        for name, value in (("SINCE", since), ("UNTIL", until)):
            if value and not _STAMP_SHAPE.match(value):
                raise ValueError("INVALID_DIGEST_" + name)
        window_days = _bounded_int(args.get("window_days"), 1, 90, "WINDOW_DAYS")
        limit = _bounded_int(args.get("limit"), 1, MAX_LIMIT, "LIMIT")
        cursor = _bounded_text(args.get("cursor"), 1024, "CURSOR")
        case_sensitive = args.get("case_sensitive", True)
        if not isinstance(case_sensitive, bool):
            raise ValueError("INVALID_DIGEST_CASE_SENSITIVE")
        include_semantic = args.get("include_semantic", True)
        if not isinstance(include_semantic, bool):
            raise ValueError("INVALID_DIGEST_INCLUDE_SEMANTIC")
        scene_doc = {"scene_id": scene["_id"], "scope_key": scene["scope_key"],
                     "policy_epoch": scene["policy_epoch"]}
        mark = _fingerprint(scene_doc, topic, person, since, until,
                            window_days or DEFAULT_WINDOW_DAYS, case_sensitive, include_semantic)
        inner, stored, carried, state = _unwrap_cursor(cursor or None)
        if cursor and stored != mark:
            raise ValueError("DIGEST_CURSOR_FILTER_MISMATCH")
        if state.get("literal_done"):
            # 上一页已把字面那一支读完，游标里只剩讨论流待走环节：这一页不重跑字面查询（重跑会
            # 从第一页把命中项再送一遍），时间窗沿用发放游标那一页，其余计数照实为空。
            result = {"hits": [], "more": False, "degraded": False, "why": "", "next_cursor": None,
                      "window": list(state.get("window") or []), "limit": limit or DEFAULT_LIMIT,
                      "queries": 0, "fallback": {}, "dropped": {},
                      "semantic": {"ok": False, "why": "not_attempted", "candidates": 0,
                                   "manifest": None},
                      "scope": {"scene_id": scene_doc["scene_id"],
                                "scope_key": scene_doc["scope_key"],
                                "policy_epoch": scene_doc["policy_epoch"]}}
        else:
            result = query_history(self.retrieval if include_semantic else None, self.store,
                                   scene_doc, topic, person=person,
                                   window_days=window_days or DEFAULT_WINDOW_DAYS,
                                   since=since or None, until=until or None,
                                   limit=limit or DEFAULT_LIMIT, cursor=inner,
                                   case_sensitive=case_sensitive)
        if result.get("degraded"):
            return {"degraded": True, "why": result.get("why") or "unknown",
                    "text": "[群讨论整理] 没查成（%s），这次整理没用到历史"
                            % (result.get("why") or "unknown"),
                    "coverage": {}, "participants": [], "corrections": [], "opinions": [],
                    "open_items": [], "resolved": [], "replies": [], "notes": [],
                    "source_ids": [], "more": False, "next_cursor": None}
        page_hits = list(result.get("hits") or [])
        docs, linkage_why = read_linkage(self.store, [hit.get("message_id") for hit in page_hits],
                                         scene_doc)
        # 按主题或按人整理时先把同一讨论流补齐：后续更正几乎不会重复主题词（“更正一下：
        # 是一米五”），只按字面读会把这条更正连同它的对象一起丢掉，覆盖范围也跟着说谎。
        thread = {"extra": 0, "out_of_window": 0, "rounds": 0, "truncated": False, "why": "",
                  "sink_why": "", "skipped_seed_eligible": 0, "skipped_carried": 0,
                  "delivered": [], "carry_truncated": False, "pending": [], "pending_wanted": [],
                  "pending_truncated": False, "resumed": False}
        if topic or person:
            bounds = list(result.get("window") or [])
            tdocs, thits, thread = read_thread_continuations(
                self.store, scene_doc, [hit.get("message_id") for hit in page_hits],
                (bounds[0], bounds[1]) if len(bounds) == 2 else None,
                set(hit.get("message_id") for hit in page_hits if hit.get("message_id")),
                docs, carried, topic, person, case_sensitive, state)
            docs.update(tdocs)
            page_hits += [thits[mid] for mid in sorted(thits)]
        # 还有未读原文，或同一 reply 链还有没走完的环节，都算部分覆盖：两者都靠 cursor 续
        more = bool(result.get("more")) or bool(thread.get("pending") or thread.get("pending_wanted"))
        excluded, excluded_why = _excluded_counts(self.store, scene_doc)
        meta = {"scene_id": scene_doc["scene_id"], "group_id": _group_id_of(scene_doc["scene_id"]),
                "policy_epoch": scene_doc["policy_epoch"], "topic": topic, "person": person,
                "window": result.get("window") or [], "more": more,
                "fallback": result.get("fallback") or {}, "semantic": result.get("semantic") or {},
                "dropped": result.get("dropped") or {}, "identity": identity_status(),
                "excluded": excluded, "excluded_why": excluded_why,
                "linkage_why": linkage_why or excluded_why, "thread": thread}
        digest = build_digest(page_hits, docs, meta)
        # 跨页去重集合随游标累加：上一页送过的链内后续不在下一页再送一遍
        carry = list(carried) + list(thread.get("delivered") or [])
        if len(carry) > MAX_THREAD_CARRY:
            carry = carry[-MAX_THREAD_CARRY:]
            thread["carry_truncated"] = True
        wrapped = None
        if more:
            next_state = {"frontier": list(thread.get("pending") or []),
                          "wanted": list(thread.get("pending_wanted") or [])}
            if thread.get("pending_truncated"):
                next_state["lost"] = True
            if not result.get("more"):
                next_state["literal_done"] = True
                next_state["window"] = list(result.get("window") or [])
            while True:
                wrapped = _wrap_cursor(result.get("next_cursor"), mark, carry, next_state)
                if len(wrapped) <= 1024 or not carry:
                    break
                carry = carry[:max(len(carry) // 2, 1)]   # 去重集合先让位：宁可重送一条也不能丢续页入口
                thread["carry_truncated"] = True
        digest["coverage"]["cursor"] = wrapped or ""
        payload = {"degraded": False, "why": "", "text": render(digest),
                   "coverage": digest["coverage"], "participants": digest["participants"],
                   "corrections": digest["corrections"], "opinions": digest["opinions"],
                   "open_items": digest["open_items"], "resolved": digest["resolved"],
                   "replies": digest["replies"], "notes": digest["notes"],
                   "source_ids": digest["source_ids"], "more": more,
                   "next_cursor": wrapped, "window": result.get("window"),
                   "limit": result.get("limit"), "scope": result.get("scope"),
                   "identity": identity_status(),
                   "semantic": {key: (result.get("semantic") or {}).get(key)
                                for key in ("ok", "why", "candidates")},
                   "dropped": result.get("dropped") or {}, "fallback": result.get("fallback"),
                   "readback": _readback(topic, digest)}
        return _fit_budget(payload)


def _readback(topic, digest):
    """来源回读的入口：按 message_id 认，参数能照抄（时间窗圈该条前后两秒）。

    example_args 故意不带 topic：同一讨论流里的后续更正常常不再重复主题词，带上 topic 会让
    query_authorized_history 又把它筛掉，回读就退回本次整理漏掉它的那个口径。主题词另放在
    topic 字段里供人看；只有这条本身确实含主题词时才把 topic 带进参数。链内后续的 id 单独
    列在 thread_source_ids，便于核对“为什么这条没主题词却出现在整理里”。
    """
    row = next(iter(digest["corrections"] + digest["open_items"] + digest["opinions"]
                    + digest["resolved"]), None)
    example = {}
    if row:
        example = {"person": row["person_id"] or row["who"], "since": _shift(row["at"], -2),
                   "until": _shift(row["at"], 2)}
        if topic and topic.lower() in (row.get("text") or "").lower():
            example["query"] = topic
    omitted = bool(topic) and "query" not in example
    return {"tool": HISTORY_TOOL_NAME,
            "first_source": digest["source_ids"][0] if digest["source_ids"] else "",
            "example_args": example, "topic": topic, "topic_omitted": omitted,
            "thread_source_ids": [item["message_id"]
                                  for bucket in ("corrections", "opinions", "open_items",
                                                 "resolved")
                                  for item in digest[bucket] if item.get("thread")],
            "note": "原文整条回读以查询结果为准；本整理只带显示片段"
                    + ("；这条后续不含主题词，所以回读参数不带 topic（带了就会被筛掉）"
                       if omitted else "")}


def _fit_budget(payload):
    """超预算先压片段再丢片段：id 与计数都留着，不静默丢事实。"""
    def size():
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size() <= DIGEST_RESULT_BUDGET:
        return payload
    buckets = ("corrections", "opinions", "open_items", "resolved", "replies")
    for bucket in buckets:
        for item in payload[bucket]:
            if len(item.get("text", "")) > 60:
                item["text"] = item["text"][:60]
                item["truncated"] = True
    if size() <= DIGEST_RESULT_BUDGET:
        payload["notes"].append("整理项片段因传输预算压到 60 字：全文按 message_id 回读")
        return payload
    payload["notes"].append("整理文本超出传输预算：保留 id 与计数，片段已丢弃，全文按 message_id 回读")
    for bucket in buckets:
        for item in payload[bucket]:
            item.pop("text", None)
    return payload
