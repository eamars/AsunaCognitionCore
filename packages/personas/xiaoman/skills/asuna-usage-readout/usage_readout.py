#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asuna-usage-readout 的读数脚本：只读，六格各出一行，每行末尾带来源／筛法／读的时刻。

读三处（字段名照 SKILL.md 第二节，不另起一套）：
  1. 盘上会话记录 <data>/adr008/home/sessions/<工作区目录>/<会话 id>/session.v4.jsonl.zstd
     ——zstandard 解；一行 type=="assistant/message" ＝ 一次模型调用；取 data.usage 的
       inputTokens／cacheReadTokens／cacheWriteTokens／outputTokens／totalTokens；种类按目录名前缀认。
  2. 库 asuna_cognition_core_v2 集合 tasks：tier.chosen／tier.ran／tier.why／tier.fell、state。
  3. 库 audit_events 八处被拒 ＋ episodes.rejections[]。

排法：⑥ 窗口放在最前一行当基准（其余几行的数没有基准就没法复核），然后 ①②③④⑤。
「选高率」并进 ①（与落档同源，不另起第七行）；「三张表」是报给人看的排法，这里不印它们的名字。

只读数字、字段名、枚举短码和计数，不读正文：会话记录里只碰 type、time、data.usage 那五个数、
data.message.id（判重键）、目录名和首行的 createdAt（判拷贝用）；不印整行，不取 message／content／text。

跑法（读会话记录按硬规矩 2 用 development_run project=core；sandbox_run 里 asuna 也在，两处都能跑）：
    python3 usage_readout.py                     # 默认窗口＝最近 24 小时
    python3 usage_readout.py --days 7
    python3 usage_readout.py --since 2026-10-16 --until 2026-10-23   # 六格⑥ 那种写死窗口
    python3 usage_readout.py --selfcheck         # 不读盘不连库，只验纯逻辑（给 check_skill.py 跑通用）
退出码 0＝六格都出了读数；1＝有一格没读到（会说清哪一格、为什么）。
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就 UnicodeEncodeError 整段崩。
# 输出字节固定成 UTF-8：那种控制台顶多显示成乱码，不再崩（同 asuna-running-version 的探针）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

SESSION_FILE = "session.v4.jsonl.zstd"
CALL_ROW = "assistant/message"
COMPACT_ROW = "compaction/summary"
FIRST_ROW = "session"
DB_NAME_FALLBACK = "asuna_cognition_core_v2"

# 六格② 的认法表：按目录名前缀认，不按 agentPreset（我的对话／errand／网页界面会话三类 preset 相同）
KINDS = (
    ("asuna-role-", "我的对话"),
    ("asuna-errand-", "差事"),
    ("asuna-action-", "行动脑"),
    ("asuna-summary-", "摘要"),
    ("asuna-attend-", "门"),
    ("asuna-scheduler-", "调度"),
    ("asuna-reflect-", "反思回合"),
    ("session-", "网页界面会话"),
)
COMPACT_KIND = "压缩"                       # 压缩那次调用单独一类，不混进「我的对话」
UNARCHIVED = "行动脑·未归档位"               # 对不上任务 tier 的行动脑会话，不并进任一档
OTHER_KIND = "其他（前缀不在认法表）"
KIND_ORDER = ["我的对话", "行动脑·高档 ran=高", "行动脑·低档 ran=低", UNARCHIVED, "差事",
              "反思回合", COMPACT_KIND, "摘要", "门", "调度", "网页界面会话", OTHER_KIND]

# 六格④ 的八处被拒：主口径是 role_tool 的 payload.refused；note.refused 是它的子集，不相加
REFUSALS = (
    ("role_tool＋payload.refused", "role_tool", True, "主口径；我自己每次工具调用单条进审计"),
    ("turn.rejected", "turn.rejected", False, "回合级、不带工具名；独立一处，不与 role_tool 重复"),
    ("note.refused", "note.refused", False, "是 role_tool 的子集，不能相加"),
    ("phase.rejected", "phase.rejected", False, "只在 10-04~05 出现过"),
    ("execution.rejected", "execution.rejected", False, "行动脑交回的报告被退"),
    ("summary.rejected", "summary.rejected", False, "文档里有、库里一直 0 行"),
    ("tool.failed", "tool.failed", False, "只到 09-25，近期无记录"),
)
TEST_PIECE_MARK = "机制验收"                 # 判据 3：测试件划出选高率分母
TOTALS_KEYS = ("rows", "kept", "own", "copied", "copied_time", "copied_other", "dup_same",
               "no_cache_read_field", "inputTokens", "cacheReadTokens", "cacheWriteTokens",
               "outputTokens", "totalTokens")


# --------------------------------------------------------------------------- 环境与窗口

def resolve_zone():
    """她的本地时区：环境变量 → config/local.json 的 timezone → UTC（退回要写明）。"""
    zone = os.environ.get("ASUNA_TIMEZONE")
    if zone:
        return zone, "环境变量 ASUNA_TIMEZONE"
    try:
        from asuna import config as asuna_config
        zone = asuna_config.load(os.path.join(str(asuna_config.ROOT), "config", "local.json")).get("timezone")
        if zone:
            return zone, "config/local.json 的 timezone"
    except Exception:                                        # noqa: BLE001 拿不到就退回，照实说
        pass
    return "UTC", "没找到时区来源，退回 UTC（这一行的钟点不是她的本地钟）"


def zone_of(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:                                        # noqa: BLE001
        return timezone.utc


def parse_local(text, tz):
    text = str(text).strip().replace("T", " ")
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, shape).replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError("「%s」不是本地钟点：写成 2026-10-16 或 2026-10-16 20:30" % str(text)[:40])


def build_window(args, zone_name):
    """本地窗口 → 不带时区后缀的 UTC 边界（库里 …Z 与 …+00:00 两种存法都比得对，同 dbread.local_window）。"""
    tz = zone_of(zone_name)
    end = parse_local(args.until, tz) if args.until else datetime.now(tz)
    start = parse_local(args.since, tz) if args.since else end - timedelta(days=args.days)
    utc = [moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") for moment in (start, end)]
    local = [moment.strftime("%Y-%m-%d %H:%M:%S") for moment in (start, end)]
    return {"$gte": utc[0], "$lt": utc[1]}, utc, local


def utc_str_to_ms(text):
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)


def resolve_sessions_root(cli, problems):
    if cli:
        return cli
    data = None
    try:
        from asuna import config as asuna_config
        data = str(asuna_config.DATA)
    except Exception:                                        # noqa: BLE001
        data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        problems.append("没找到数据根（asuna.config.DATA 与 ASUNA_DATA_ROOT 都没有）"
                        "——盘上那一格没读，不是没有数据")
        return None
    return os.path.join(data, "adr008", "home", "sessions")


def resolve_database():
    try:
        from asuna import dbread
        return dbread, None
    except Exception as exc:                                 # noqa: BLE001
        return None, "%s: %s" % (type(exc).__name__, exc)


# --------------------------------------------------------------------------- 盘上会话记录

def classify(sid, tier_by_session):
    for prefix, kind in KINDS:
        if sid.startswith(prefix):
            if kind == "行动脑":
                ran = tier_by_session.get(sid)
                if ran == "高":
                    return "行动脑·高档 ran=高"
                if ran == "低":
                    return "行动脑·低档 ran=低"
                return UNARCHIVED
            return kind
    return OTHER_KIND


def parse_created_ms(value):
    """首行 createdAt → 整数毫秒。盘上实测（10-17 现读 822 份会话文件）它是整数毫秒；
    早先记成 ISO 串的那种写法也一并接着（带 Z 或 +00:00 都行），解析不了返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def iter_session_files(root, problems):
    try:
        workspaces = sorted(os.listdir(root))
    except OSError as exc:
        problems.append("读不到目录 %s（%s: %s）——盘上那一格没读，不是没有数据" % (root, type(exc).__name__, exc))
        return
    for workspace in workspaces:
        wdir = os.path.join(root, workspace)
        if not os.path.isdir(wdir):
            continue
        try:
            sids = sorted(os.listdir(wdir))
        except OSError as exc:                               # noqa: BLE001 单个目录读不动，跳过并说
            problems.append("读不到 %s（%s）" % (wdir, type(exc).__name__))
            continue
        for sid in sids:
            path = os.path.join(wdir, sid, SESSION_FILE)
            if os.path.isfile(path):
                yield sid, path


def read_rows(path):
    """zstandard 解 → 逐行 json.loads。只把当次那一行交出去，不留整行。"""
    import zstandard
    decompressor = zstandard.ZstdDecompressor()
    with open(path, "rb") as handle:
        with decompressor.stream_reader(handle) as stream:
            with io.BufferedReader(stream, buffer_size=1 << 20) as reader:
                for raw in reader:
                    if raw and raw.strip():
                        yield json.loads(raw.decode("utf-8"))


def scan_sessions(root, tier_by_session, problems):
    """一遍扫完：返回（每前缀盘上目录数，调用行 occurrences）。occurrence 只带数字与判重键。"""
    dirs_by_prefix = {}
    occurrences = []
    unreadable = 0
    for sid, path in iter_session_files(root, problems):
        prefix = "session-<uuid>" if sid.startswith("session-") else (
            sid.split("-")[0] + "-" + (sid.split("-")[1] + "-" if sid.count("-") > 1 else ""))
        dirs_by_prefix[prefix] = dirs_by_prefix.get(prefix, 0) + 1
        kind = classify(sid, tier_by_session)
        try:
            rows = list(read_rows(path))
        except Exception as exc:                             # noqa: BLE001 单个文件坏了不拦整次读数
            unreadable += 1
            problems.append("解不开 %s（%s: %s）" % (path, type(exc).__name__, exc))
            continue
        created_ms = None
        for row in rows:
            if row.get("type") == FIRST_ROW:
                created_ms = parse_created_ms(row.get("createdAt"))
                break
        for row in rows:
            row_type = row.get("type")
            if row_type not in (CALL_ROW, COMPACT_ROW):
                continue
            moment = row.get("time")
            if not isinstance(moment, int):
                continue
            data = row.get("data") or {}
            usage = data.get("usage")
            if not isinstance(usage, dict):
                continue
            message = data.get("message")
            mid = message.get("id") if isinstance(message, dict) else None
            numbers = {name: (usage.get(name) if isinstance(usage.get(name), int) else 0)
                       for name in ("inputTokens", "outputTokens", "totalTokens",
                                    "cacheReadTokens", "cacheWriteTokens")}
            key = (("id", mid) if mid else
                   ("heur", moment, numbers["inputTokens"], numbers["outputTokens"],
                    numbers["cacheReadTokens"], numbers["cacheWriteTokens"], numbers["totalTokens"]))
            occurrences.append({"t": moment, "kind": COMPACT_KIND if row_type == COMPACT_ROW else kind,
                                "sid": sid, "created": created_ms or 0, "key": key,
                                "has_cache_read": "cacheReadTokens" in usage,
                                "copied": bool(created_ms and moment < created_ms), **numbers})
    if unreadable:
        problems.append("有 %d 个会话文件解不开，已从这次读数里跳过（不是全量）" % unreadable)
    return dirs_by_prefix, occurrences


def dedupe(occurrences):
    """全局按判重键去重：一条只算一次，归首次出现那一次（首次＝行内 time 最早，同刻按会话首行 createdAt）。"""
    best = {}
    for index, item in enumerate(occurrences):
        current = best.get(item["key"])
        if current is None:
            best[item["key"]] = index
            continue
        rival = occurrences[current]
        if (item["t"], item["created"], item["sid"]) < (rival["t"], rival["created"], rival["sid"]):
            best[item["key"]] = index
    return best


def aggregate(occurrences, best, lo_ms, hi_ms):
    per_kind = {}
    totals = {name: 0 for name in TOTALS_KEYS}

    def slot(kind):
        if kind not in per_kind:
            per_kind[kind] = {name: 0 for name in TOTALS_KEYS}
        return per_kind[kind]

    for index, item in enumerate(occurrences):
        if not lo_ms <= item["t"] < hi_ms:
            continue
        stats = slot(item["kind"])
        totals["rows"] += 1
        stats["rows"] += 1
        owner = occurrences[best[item["key"]]]
        if best[item["key"]] != index:
            # 同一次调用在别处首次出现过：本类这一行不再进求和（口径：一条 id 只算一次）
            if owner["kind"] == item["kind"]:
                totals["dup_same"] += 1
                stats["dup_same"] += 1
            else:
                totals["copied_other"] += 1
                stats["copied_other"] += 1
                totals["copied"] += 1
                stats["copied"] += 1
            continue
        totals["kept"] += 1
        stats["kept"] += 1
        if item["copied"]:                      # 行 time 早于本会话首行 createdAt＝分叉／播种带进来的历史
            totals["copied_time"] += 1
            stats["copied_time"] += 1
            totals["copied"] += 1
            stats["copied"] += 1
        else:
            totals["own"] += 1
            stats["own"] += 1
        if not item["has_cache_read"]:
            totals["no_cache_read_field"] += 1
            stats["no_cache_read_field"] += 1
        for name in ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens", "totalTokens"):
            totals[name] += item[name]
            stats[name] += item[name]
    return per_kind, totals


def hit_rate(stats):
    """命中率＝cacheRead／(input＋cacheRead＋cacheWrite)——写缓存算未命中，留在分母里（六格⑤）。"""
    denominator = stats["inputTokens"] + stats["cacheReadTokens"] + stats["cacheWriteTokens"]
    return (100.0 * stats["cacheReadTokens"] / denominator) if denominator else None


def own_slice(occurrences, best, lo_ms, hi_ms, kind):
    """只按自有行（time 不早于本会话首行 createdAt）再算一份命中率。"""
    sums = {"inputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0}
    for index, item in enumerate(occurrences):
        if not lo_ms <= item["t"] < hi_ms or item["kind"] != kind or item["copied"]:
            continue
        if best[item["key"]] != index:
            continue
        for name in sums:
            sums[name] += item[name]
    return hit_rate(sums)


def rate_text(value):
    return "无分母" if value is None else "%.2f%%" % value


# --------------------------------------------------------------------------- 库里

def page(dbread, collection, query, fields, size=500):
    """按 _id 稳定翻页取回全部命中行（dbread.find 一页最多 500）。只取点名的字段。"""
    rows, skip = [], 0
    while True:
        answer = dbread.find(collection, query, fields=fields, sort=[("_id", 1)], limit=size, skip=skip)
        rows.extend(answer["rows"])
        if not answer.get("more"):
            return rows
        skip += size


def db_count(dbread, collection, query):
    return dbread.count(collection, query)["found"]


def db_group(dbread, collection, pipeline):
    """$group 出来的 (_id, n) 列表。_id 可能是字典（多字段分组），所以不塞进 dict。"""
    return [(row["_id"], row["n"]) for row in dbread.aggregate(collection, pipeline, limit=200)["rows"]]


def utc_show(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- 六格

def cell_window(dbread, window, local_bounds, disk_rows, zone_name, zone_source, read_at, root):
    audit = tasks = None
    if dbread:
        audit = db_count(dbread, "audit_events", {"occurred_at": window})
        tasks = db_count(dbread, "tasks", {"created_at": window})
    lines = ["⑥ 窗口｜起 %s → 止 %s（本地 %s，%s；换成的 UTC 区间 %s ～ %s）｜读于 %s｜"
             "窗口内行数：会话调用行 %s（去重前，盘上按行 time 切）／audit_events %s 行／tasks %s 件"
             % (local_bounds[0], local_bounds[1], zone_name, zone_source, utc_show(window["$gte"]),
                utc_show(window["$lt"]), read_at, "?" if disk_rows is None else disk_rows,
                "?" if audit is None else audit, "?" if tasks is None else tasks),
             "   来源=盘 %s/**/%s 每行 time（整数毫秒）＋库 %s 的 audit_events.occurred_at、tasks.created_at"
             % (root or "（没找到）", SESSION_FILE, DB_NAME_FALLBACK),
             "   筛法=行级 time ∈ [起,止)，不按整文件切；库按本地钟点换出的 UTC 区间比 *_at；"
             "字段有无一律 $exists 计数，不拿 dbread.fields() 的采样当结论"]
    return lines, disk_rows is not None and audit is not None


def cell_tiers(dbread, window):
    if not dbread:
        return ["① 落档／选高｜没读到：dbread 连不上"], False
    total = db_count(dbread, "tasks", None)
    with_tier = db_count(dbread, "tasks", {"tier": {"$exists": True}})
    with_tier_window = db_count(dbread, "tasks", {"tier": {"$exists": True}, "created_at": window})
    chosen_high = db_count(dbread, "tasks", {"tier.chosen": "高"})
    ran_high = db_count(dbread, "tasks", {"tier.ran": "高"})
    fell_field = db_count(dbread, "tasks", {"tier.fell": {"$exists": True}})
    mismatch = db_count(dbread, "tasks", {"tier": {"$exists": True},
                                          "$expr": {"$ne": ["$tier.ran", "$tier.chosen"]}})
    test_pieces = db_count(dbread, "tasks", {"tier": {"$exists": True},
                                             "$or": [{"title": {"$regex": TEST_PIECE_MARK}},
                                                     {"tier.why": {"$regex": TEST_PIECE_MARK}}]})
    reasons = db_group(dbread, "tasks", [{"$match": {"tier.fell": {"$exists": True}}},
                                         {"$group": {"_id": "$tier.fell.reason", "n": {"$sum": 1}}}])
    audit_fell = db_count(dbread, "audit_events", {"type": "tier.fell"})
    audit_rest = db_count(dbread, "audit_events", {"type": "tier.rest"})
    share_tier = "%.1f%%" % (100.0 * chosen_high / with_tier) if with_tier else "无分母"
    share_all = "%.1f%%" % (100.0 * chosen_high / total) if total else "无分母"
    lines = ["① 落档／选高｜任务 %s 件，带 tier %s 件（窗口内新建 %s 件）；选高（tier.chosen=高）%s 件"
             "＝占有 tier 的 %s／占全部任务的 %s；测试件划出 %s 件（tier.why 或标题写着「%s」，不进选高率分母）；"
             "实跑高档（tier.ran=高）%s 件；落档（tier.ran≠tier.chosen）%s 件、tier.fell 字段 %s 件"
             "（件数只从字段数，reason 分布 %s）；审计 tier.fell %s 行／tier.rest %s 行"
             "（两来源不相加、也不能互查——「开工即落档」在审计面看不见）"
             % (total, with_tier, with_tier_window, chosen_high, share_tier, share_all, test_pieces,
                TEST_PIECE_MARK, ran_high, mismatch, fell_field,
                "、".join("%s %s 件" % (key, n) for key, n in reasons) if reasons else "无一件落档",
                audit_fell, audit_rest)]
    states = db_group(dbread, "tasks", [{"$match": {"tier": {"$exists": True}}},
                                        {"$group": {"_id": {"chosen": "$tier.chosen", "ran": "$tier.ran",
                                                            "state": "$state"}, "n": {"$sum": 1}}}])
    no_tier_states = db_group(dbread, "tasks", [{"$match": {"tier": {"$exists": False}}},
                                                {"$group": {"_id": "$state", "n": {"$sum": 1}}}])
    parts = ["%s→%s %s %s 件" % (key.get("chosen"), key.get("ran"), key.get("state"), n)
             for key, n in sorted(states, key=lambda pair: (str(pair[0].get("ran")), str(pair[0].get("state"))))]
    lines.append("   状态（交回只等于交回）：带 tier 的 " + ("；".join(parts) if parts else "无")
                 + "｜无 tier 的 " + "、".join("%s %s 件" % (key, n)
                                            for key, n in sorted(no_tier_states, key=lambda pair: str(pair[0]))))
    lines.append("   来源=库 %s 集合 tasks 字段 tier.chosen／tier.ran／tier.fell／tier.why／state"
                 "＋audit_events.type｜筛法=$exists 与等值计数、$expr 比 ran≠chosen、窗口按 created_at；"
                 "落档件数只从 tier.fell 字段数" % DB_NAME_FALLBACK)
    return lines, True


def cell_kinds(dbread, per_kind, totals, dirs_by_prefix, root, own_rates):
    """② 会话种类：盘上目录数、库里 sessions 行数、窗口内调用行（自有／拷贝两格，不合并）。"""
    disk_total = sum(dirs_by_prefix.values()) if dirs_by_prefix else 0
    db_total = db_count(dbread, "sessions", None) if dbread else None
    lines = ["② 会话种类｜盘上有 %s 的会话目录 %s 个／库里 sessions %s 行／窗口内调用行 %s 行"
             "（全局去重后 %s 行，其中自有 %s／拷贝 %s，两格不合并）"
             % (SESSION_FILE, disk_total, "?" if db_total is None else db_total,
                totals["rows"], totals["kept"], totals["own"], totals["copied"])]

    def numbers(kind, stats):
        return ("窗口内 %s 行（自有 %s／拷贝 %s：行 time 早于本会话 createdAt %s、同 id 归别类 %s；"
                "同类内重复记 %s；缺 cacheReadTokens %s 行按 0 算）"
                "｜input %s／cacheRead %s／cacheWrite %s｜命中率 %s（仅自有 %s）%s"
                % (stats["rows"], stats["own"], stats["copied"], stats["copied_time"],
                   stats["copied_other"], stats["dup_same"], stats["no_cache_read_field"],
                   stats["inputTokens"], stats["cacheReadTokens"], stats["cacheWriteTokens"],
                   rate_text(hit_rate(stats)), rate_text(own_rates.get(kind)),
                   "｜拷贝比自有还多，样本量只有 %s——这一类的命中率其实是别人的调用算出来的" % stats["own"]
                   if stats["own"] and stats["own"] < stats["copied"] else ""))

    def db_rows(prefix):
        found = db_count(dbread, "sessions", {"_id": {"$regex": "^" + prefix}}) if dbread else None
        return "?" if found is None else found

    def disk_dirs(prefix):
        return dirs_by_prefix.get("session-<uuid>" if prefix == "session-" else prefix, 0)

    empty = {name: 0 for name in TOTALS_KEYS}
    for prefix, kind in KINDS:
        if kind == "行动脑":
            continue
        lines.append("   %s（前缀 %s）：盘 %s 个／库 %s 行｜%s"
                     % (kind, prefix, disk_dirs(prefix), db_rows(prefix),
                        numbers(kind, per_kind.get(kind, empty))))
    lines.append("   行动脑（前缀 asuna-action-）：盘 %s 个／库 %s 行｜按 sessions.task_id→tasks.tier.ran 归档，"
                 "对不上的进未归档位（不并进任一档）" % (disk_dirs("asuna-action-"), db_rows("asuna-action-")))
    for tier_kind in ("行动脑·高档 ran=高", "行动脑·低档 ran=低", UNARCHIVED):
        lines.append("     └ %s：%s" % (tier_kind, numbers(tier_kind, per_kind.get(tier_kind, empty))))
    lines.append("   %s（compaction/summary 行，不是一种会话）：盘 —／库 —｜%s"
                 % (COMPACT_KIND, numbers(COMPACT_KIND, per_kind.get(COMPACT_KIND, empty))))
    if OTHER_KIND in per_kind:
        lines.append("   %s：%s" % (OTHER_KIND, numbers(OTHER_KIND, per_kind[OTHER_KIND])))
    lines.append("   来源=盘 %s（种类按目录名前缀认，不按 agentPreset）＋库 %s 集合 sessions 的 _id 前缀计数"
                 % (root or "（没找到）", DB_NAME_FALLBACK))
    lines.append("   筛法=窗口内按行 time；拷贝两条判据分开数：同一次调用（data.message.id）首次出现在别的种类、"
                 "或行 time 早于本会话首行 createdAt；盘上目录数与库里行数是两把尺，不互校（对不上的原因未查）")
    return lines, bool(dirs_by_prefix)


def cell_reflect(dbread, per_kind, dirs_by_prefix, root):
    stats = per_kind.get("反思回合", {name: 0 for name in TOTALS_KEYS})
    db_rows = db_count(dbread, "sessions", {"_id": {"$regex": "^asuna-reflect-"}}) if dbread else None
    lines = ["③ 反思回合｜盘上 asuna-reflect- 目录 %s 个／库里 sessions %s 行／"
             "窗口内调用行 %s 行（去重后 %s，自有 %s／拷贝 %s）——它不背拷贝来的历史（六格③）"
             % (dirs_by_prefix.get("asuna-reflect-", 0), "?" if db_rows is None else db_rows,
                stats["rows"], stats["kept"], stats["own"], stats["copied"]),
             "   来源=盘 %s 下前缀 asuna-reflect- 的目录＋库 %s 集合 sessions 的 _id 前缀计数"
             % (root or "（没找到）", DB_NAME_FALLBACK),
             "   筛法=目录名前缀；窗口内按行 time；拷贝两条判据：同 id 首次出现在别的种类、"
             "或行 time 早于本会话首行 createdAt"]
    return lines, True


def cell_refusals(dbread, window):
    if not dbread:
        return ["④ 被拒八处｜没读到：dbread 连不上"], False
    lines = []
    total = 0
    for label, event_type, is_main, note in REFUSALS:
        query = {"type": event_type}
        if is_main:
            query["payload.refused"] = {"$exists": True}
        in_window = db_count(dbread, "audit_events", dict(query, occurred_at=window))
        all_time = db_count(dbread, "audit_events", query)
        total += all_time
        extra = ""
        if event_type in ("tool.failed", "phase.rejected"):
            last = dbread.find("audit_events", query, fields=["occurred_at"],
                               sort=[("occurred_at", -1)], limit=1)["rows"]
            extra = "，最近一条 %s" % (last[0].get("occurred_at") if last else "无")
        if is_main:
            coded = db_count(dbread, "audit_events", {"type": event_type,
                                                      "payload.refused": {"$exists": True},
                                                      "payload.code": {"$exists": True}})
            codes = dbread.distinct("audit_events", "payload.code",
                                    {"type": event_type, "payload.refused": {"$exists": True}})["rows"]
            extra = "；带 payload.code 的 %s 行，code 取值 %s（其余只有自由文本，只数条数不引原文）" % (
                coded, sorted(codes))
        lines.append("   %s：窗口内 %s 行／全库 %s 行%s｜%s" % (label, in_window, all_time, extra, note))
    episodes = db_count(dbread, "episodes", {"rejections.0": {"$exists": True}})
    total += episodes
    lines.append("   episodes.rejections[]：非空回合 %s 个（全库；未按窗口切——episodes 行没有顶层时间字段，未核）"
                 % episodes)
    lines.insert(0, "④ 被拒八处｜八处合计 %s（只当规模参考：八处不相加，note.refused 是 role_tool 的子集；"
                    "主口径是 role_tool 的 payload.refused）" % total)
    lines.append("   来源=库 %s 集合 audit_events 的 type／payload.refused／payload.code／occurred_at"
                 "＋episodes.rejections[]" % DB_NAME_FALLBACK)
    lines.append("   筛法=type 等值＋payload.refused 的 $exists；窗口按 occurred_at；"
                 "成因只按 payload.code 分（schema 必填所致不归我，挑错 op 才归我，分不出就写分不出）")
    return lines, True


def cell_hit_rate(totals, per_kind, own_rates, root):
    lines = ["⑤ 命中率｜窗口内调用行 %s 行、全局去重后 %s 行（判重键 data.message.id；"
             "压缩行没有这个字段，退回启发式键 time＋四个 token 数）｜全局命中率 %s｜"
             "input %s／cacheRead %s／cacheWrite %s／output %s／total %s｜"
             "缺 cacheReadTokens 字段的行 %s 行按 0 计入（推断）"
             % (totals["rows"], totals["kept"], rate_text(hit_rate(totals)), totals["inputTokens"],
                totals["cacheReadTokens"], totals["cacheWriteTokens"], totals["outputTokens"],
                totals["totalTokens"], totals["no_cache_read_field"])]
    for kind in KIND_ORDER:
        if kind not in per_kind:
            continue
        stats = per_kind[kind]
        lines.append("   %s：去重后 %s 行（自有 %s／拷贝 %s，其中行 time 早于本会话 createdAt %s）｜"
                     "input %s／cacheRead %s／cacheWrite %s｜命中率 %s（仅自有 %s）"
                     % (kind, stats["kept"], stats["own"], stats["copied"], stats["copied_time"],
                        stats["inputTokens"],
                        stats["cacheReadTokens"], stats["cacheWriteTokens"], rate_text(hit_rate(stats)),
                        rate_text(own_rates.get(kind))))
    lines.append("   来源=盘 %s/**/%s 的 type／time／data.usage 五个数／data.message.id＋首行 createdAt"
                 % (root or "（没找到）", SESSION_FILE))
    lines.append("   筛法=命中率＝cacheRead/(input＋cacheRead＋cacheWrite)（写缓存算未命中、留在分母里，六格⑤）；"
                 "token 加权（各类先求和再相除，不是各条比例再平均）；先全局去重再按类求和；窗口按行 time")
    return lines, True


# --------------------------------------------------------------------------- 离线自检（不读盘、不连库）

def selfcheck():
    """纯逻辑自检：认法、命中率式子、跨类去重、拷贝判定、窗口切法。给 check_skill.py 跑通用。"""
    checks = []

    def check(name, ok):
        checks.append((name, bool(ok)))

    tier_map = {"asuna-action-aaa": "高", "asuna-action-bbb": "低"}
    check("classify_role", classify("asuna-role-x", tier_map) == "我的对话")
    check("classify_action_high", classify("asuna-action-aaa", tier_map) == "行动脑·高档 ran=高")
    check("classify_action_unarchived", classify("asuna-action-zzz", tier_map) == UNARCHIVED)
    check("classify_webui", classify("session-1541fa2e-d56d-4c52", tier_map) == "网页界面会话")
    check("classify_reflect", classify("asuna-reflect-8609", tier_map) == "反思回合")
    check("classify_unknown", classify("whatever-1", tier_map) == OTHER_KIND)
    check("hit_rate_keeps_write_in_denominator",
          abs(hit_rate({"inputTokens": 100, "cacheReadTokens": 300, "cacheWriteTokens": 100}) - 60.0) < 1e-9)
    check("hit_rate_no_denominator",
          hit_rate({"inputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0}) is None)

    def row(moment, kind, mid, created, inp, cache_read, cache_write, sid):
        return {"t": moment, "kind": kind, "sid": sid, "created": created, "key": ("id", mid),
                "has_cache_read": True, "copied": moment < created, "inputTokens": inp,
                "cacheReadTokens": cache_read, "cacheWriteTokens": cache_write,
                "outputTokens": 0, "totalTokens": 0}

    # 同一条 id 出现在两个种类里：行内 time 相同就按会话首行 createdAt，归早的那一类
    items = [row(1000, "差事", "m1", 500, 10, 90, 0, "asuna-errand-a"),
             row(1000, "我的对话", "m1", 100, 10, 90, 0, "asuna-role-b"),
             row(2000, "我的对话", "m2", 100, 5, 5, 0, "asuna-role-b"),
             row(10, "我的对话", "m3", 100, 7, 7, 0, "asuna-role-b")]
    best = dedupe(items)
    check("dedup_same_time_uses_created_at", best[("id", "m1")] == 1)
    kinds, totals = aggregate(items, best, 0, 3000)
    check("dedup_counts_once", totals["kept"] == 3 and totals["copied_other"] == 1)
    check("copied_row_lands_in_its_class",
          kinds["差事"]["rows"] == 1 and kinds["差事"]["copied"] == 1 and kinds["差事"]["own"] == 0)
    check("own_and_copy_two_cells", kinds["我的对话"]["own"] == 2 and kinds["我的对话"]["copied_time"] == 1)
    twice = [row(1000, "我的对话", "m9", 100, 1, 1, 0, "asuna-role-b"),
             row(1000, "我的对话", "m9", 120, 1, 1, 0, "asuna-role-c")]
    check("same_class_repeat_counted_separately",
          aggregate(twice, dedupe(twice), 0, 3000)[1]["dup_same"] == 1)
    windowed, _ = aggregate(items, best, 1000, 3000)
    check("window_cuts_by_row_time", windowed["我的对话"]["rows"] == 2)
    heuristic = [{"t": 5, "kind": COMPACT_KIND, "sid": "s", "created": 0, "key": ("heur", 5, 1, 2, 3, 4, 10),
                  "has_cache_read": False, "copied": False, "inputTokens": 1, "cacheReadTokens": 2,
                  "cacheWriteTokens": 3, "outputTokens": 4, "totalTokens": 10},
                 {"t": 5, "kind": "网页界面会话", "sid": "s2", "created": 0,
                  "key": ("heur", 5, 1, 2, 3, 4, 10), "has_cache_read": False, "copied": False,
                  "inputTokens": 1, "cacheReadTokens": 2, "cacheWriteTokens": 3, "outputTokens": 4,
                  "totalTokens": 10}]
    check("heuristic_key_dedups_compaction",
          aggregate(heuristic, dedupe(heuristic), 0, 10)[1]["kept"] == 1)
    check("created_ms_is_int_on_disk", parse_created_ms(1792193565157) == 1792193565157)
    check("created_ms_parses_both_iso_forms", parse_created_ms("2026-10-16T07:56:38.123456+00:00")
          == parse_created_ms("2026-10-16T07:56:38.123456Z"))
    check("created_ms_rejects_junk", parse_created_ms("不是时间") is None
          and parse_created_ms(None) is None and parse_created_ms(True) is None)
    check("utc_bounds_are_naive_utc", utc_str_to_ms("2026-10-16T05:00:00")
          == int(datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc).timestamp() * 1000))

    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print("FAIL selfcheck %s" % name)
    print("SELFCHK %d/%d 通过（纯逻辑：种类认法、命中率分母含写缓存、跨类按 id 去重归首次、"
          "拷贝判定、窗口按行切；没读盘、没连库）" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


# --------------------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(description="asuna-usage-readout 的六格读数（只读）")
    parser.add_argument("--days", type=float, default=1.0, help="窗口长度（天），默认 1＝最近 24 小时")
    parser.add_argument("--since", help="窗口起点，本地钟点 2026-10-16 或 2026-10-16 20:30（给了就不看 --days）")
    parser.add_argument("--until", help="窗口终点，本地钟点；默认＝读的那一刻")
    parser.add_argument("--sessions-root", help="会话记录根目录，默认 <data>/adr008/home/sessions")
    parser.add_argument("--no-db", action="store_true", help="只读盘，不连库（库里那三格会说没读到）")
    parser.add_argument("--selfcheck", action="store_true", help="不读盘不连库，只验纯逻辑")
    args = parser.parse_args()
    if args.selfcheck:
        return selfcheck()

    problems = []
    zone_name, zone_source = resolve_zone()
    os.environ.setdefault("ASUNA_TIMEZONE", zone_name)
    window, utc_bounds, local_bounds = build_window(args, zone_name)
    lo_ms, hi_ms = utc_str_to_ms(utc_bounds[0]), utc_str_to_ms(utc_bounds[1])
    read_at = datetime.now(zone_of(zone_name)).strftime("%Y-%m-%d %H:%M:%S")
    root = resolve_sessions_root(args.sessions_root, problems)
    dbread, db_error = (None, "带了 --no-db") if args.no_db else resolve_database()
    if db_error and not args.no_db:
        problems.append("dbread 连不上（%s）——库里那三格没读到，不是没有数据" % db_error)

    tier_by_session = {}
    if dbread:
        tier_by_task = {row["_id"]: (row.get("tier") or {}).get("ran")
                        for row in page(dbread, "tasks", {"tier": {"$exists": True}}, ["_id", "tier"])}
        for row in page(dbread, "sessions", {"_id": {"$regex": "^asuna-action-"},
                                             "task_id": {"$exists": True, "$ne": None}}, ["_id", "task_id"]):
            ran = tier_by_task.get(row.get("task_id"))
            if ran:
                tier_by_session[row["_id"]] = ran

    if root:
        dirs_by_prefix, occurrences = scan_sessions(root, tier_by_session, problems)
        best = dedupe(occurrences)
        per_kind, totals = aggregate(occurrences, best, lo_ms, hi_ms)
    else:
        dirs_by_prefix, occurrences, best, per_kind = {}, [], {}, {}
        totals = {name: 0 for name in TOTALS_KEYS}
    own_rates = {kind: own_slice(occurrences, best, lo_ms, hi_ms, kind) for kind in per_kind}
    disk_rows = len([1 for item in occurrences if lo_ms <= item["t"] < hi_ms]) if root else None

    print("asuna-usage-readout 读数｜脚本 %s｜窗口＝最近 %s 天（--days／--since／--until 可改）"
          % (os.path.abspath(__file__), args.days))
    ok = []
    for lines, cell_ok in (
            cell_window(dbread, window, local_bounds, disk_rows, zone_name, zone_source, read_at, root),
            cell_tiers(dbread, window),
            cell_kinds(dbread, per_kind, totals, dirs_by_prefix, root, own_rates),
            cell_reflect(dbread, per_kind, dirs_by_prefix, root),
            cell_refusals(dbread, window),
            cell_hit_rate(totals, per_kind, own_rates, root)):
        print("\n".join(lines))
        ok.append(cell_ok)
    if problems:
        print("没读到／要留神的：%s" % "；".join(problems))
    print("读法提醒：交回只等于交回；拷贝占比高的那一类要标样本量；"
          "这些数当天就会旧，跨趟对数先对「几点读的」再对数。")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
