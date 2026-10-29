#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asuna-usage-readout 的读数脚本：只读。先出一张「各行必须加到合计」的对账表（2026-10-21 主人定的口径），
再出六格长句读数（每周三张表的原料，口径见 SKILL.md 第三节）。

对账表（SKILL.md 第二·五节）：
  列：类别｜请求数｜读入提示｜命中｜新读入｜写缓存｜输出｜命中率；读入提示＝input＋cacheRead＋cacheWrite。
  行：角色脑／行动脑·高／行动脑·低／行动脑·未归档／压缩／门／调度／其余／合计／拷贝行（不计入合计）。
  命中率不适用的三类（2026-10-27 主人定的口径）：摘要／门／网页界面会话——这三类的行基本没有 cacheReadTokens 这个键——
  这三类标「不适用命中率」、不进合计的分母（对账表的「门」行与六格②⑤ 都按这个口径；摘要在表里并进「压缩」行、
  网页界面会话按 preset 进「角色脑」行，那两类的摘出只发生在六格②⑤ 那把按目录名前缀认的尺上）。
  行归属按会话首行 agentPreset；行动脑按所配任务 tier.ran（缺则 tier.chosen）分档，分不出进未归档。
  数据源两个根：<data>/adr008/home/sessions 与 <data>/adr008/archive/sessions，去重跨两个根。
  硬断言（不过就报错不出表）：①每行 读入提示＝命中＋新读入＋写缓存；②各行（不含拷贝行）之和＝合计每一列
  （合计另用一遍独立直加核对）；③请求数同样加和相等；④窗口内每条要么进类行要么进拷贝行。

读三处（字段名照 SKILL.md 第二节，不另起一套）：
  1. 盘上会话记录 <root>/<工作区目录>/<会话 id>/session.v4.jsonl.zstd ——zstandard 跨帧解；
     一行 type=="assistant/message" ＝ 一次模型调用；取 data.usage 的 inputTokens／cacheReadTokens／
     cacheWriteTokens／outputTokens／totalTokens；另取首行 agentPreset／createdAt（都是短字段）。
  2. 库 asuna_cognition_core_v2 集合 tasks：tier.chosen／tier.ran／tier.why／tier.fell、state。
  3. 库 audit_events 八处被拒 ＋ episodes.rejections[]。

排法：对账表排最前（断言过了才印）；六格里 ⑥ 窗口放在其余几行前当基准；「选高率」并进 ①。

只读数字、字段名、枚举短码和计数，不读正文：会话记录里只碰 type、time、data.usage 那五个数、
data.message.id（判重键）、原始行字节的 sha256（判重键，不存原文）、目录名和首行的
agentPreset／createdAt（判拷贝用）；不印整行，不取 message／content／text。

跑法（读会话记录按硬规矩 2 用 development_run project=core；sandbox_run 里 asuna 也在，两处都能跑）：
    python3 usage_readout.py                     # 默认窗口＝最近 24 小时
    python3 usage_readout.py --days 7
    python3 usage_readout.py --since "2026-10-20 14:00" --until "2026-10-21 14:00"   # 本地钟点（+5）
    python3 usage_readout.py --no-archive        # 对账表也只扫 home（覆盖面会写明少了归档根）
    python3 usage_readout.py --selfcheck         # 不读盘不连库，只验纯逻辑（给 check_skill.py 跑通用）
退出码 0＝对账表断言全过、六格都出了读数，且盘上那一格有分母（没有解不开的文件、窗口内不是 0 行）；
1＝断言没过、有一格没读到、有解不开的帧、或窗口内 0 行（会说清哪一格、为什么）。
"""
import argparse
import hashlib
import io
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone, tzinfo

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

# 对账表（2026-10-21 主人定的行清单；「调度」是现读盘上发现第五种 preset 后补的一格）
T_ROLE = "角色脑"
T_HIGH = "行动脑·高"
T_LOW = "行动脑·低"
T_UNARCH = "行动脑·未归档"
T_COMPACT = "压缩"
T_GATE = "门"
T_SCHED = "调度"
T_OTHER = "其余"
T_TOTAL = "合计"
T_COPY = "拷贝行（不计入合计）"
TABLE_ROWS = (T_ROLE, T_HIGH, T_LOW, T_UNARCH, T_COMPACT, T_GATE, T_SCHED, T_OTHER)
TABLE_COLS = ("requests", "prompt", "hit", "fresh", "write", "output")
COL_NAMES = {"requests": "请求数", "prompt": "读入提示", "hit": "命中", "fresh": "新读入",
             "write": "写缓存", "output": "输出"}
PRESET_TABLE = {T_ROLE: "asuna-xiaoman", T_COMPACT: "asuna-summary",
                T_GATE: "asuna-attend", T_SCHED: "asuna-scheduler"}
PRESET_BY_NAME = {name: kind for kind, name in PRESET_TABLE.items()}

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

# 「不适用命中率」的三类（2026-10-27 主人定的口径；SKILL.md 硬规矩 10 是判据来源）：
# 这三类整类没有 cacheReadTokens 这个键——单发会话（门／摘要）没有第二步，网页界面会话走的是另一条
# 本地 route，缓存不在它们之间续命；把缺字段按 0 计入，等于把「字段缺失」读成「没命中」。
# 10-17 与 10-19 两次读数各复现一次（那两趟这类报的是 0.00%）。三类照旧报行数与 token 数，只是不打比率。
NA_HIT_RATE = ("摘要", "门", "网页界面会话")
NA_HIT_RATE_WHY = ("这三类的行基本没有 cacheReadTokens 这个键：单发会话没有第二步，那条 route 的缓存不在它们之间续命；"
                   "按 0 计入是把「字段缺失」读成「没命中」——10-17 与 10-19 两次读数各复现一次；"
                   "这一窗每类缺多少行随下一行实测打出来")
# 对账表里只有「门」是单独一行（摘要并进压缩、网页界面会话按 preset 进角色脑），所以表里只能摘出这一格。
TABLE_NA = (T_GATE,)



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


def resolve_data_root():
    try:
        from asuna import config as asuna_config
        data = str(asuna_config.DATA)
    except Exception:                                        # noqa: BLE001
        data = os.environ.get("ASUNA_DATA_ROOT")
    return data or None


def resolve_sessions_root(cli, problems):
    if cli:
        return cli
    data = resolve_data_root()
    if not data:
        problems.append("没找到数据根（asuna.config.DATA 与 ASUNA_DATA_ROOT 都没有）"
                        "——盘上那一格没读，不是没有数据")
        return None
    return os.path.join(data, "adr008", "home", "sessions")


def resolve_archive_root(cli):
    if cli:
        return cli
    data = resolve_data_root()
    if not data:
        return None
    return os.path.join(data, "adr008", "archive", "sessions")


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


def classify_table(row_type, preset, sid, tier_full):
    """对账表的行归属（2026-10-21 主人定）：compaction/summary 行一律进压缩；
    行动脑按所配任务 tier.ran 分档、ran 缺则退回 tier.chosen、两个都分不出进未归档；
    其余按首行 agentPreset 认，preset 缺／不在清单进「其余」。"""
    if row_type == COMPACT_ROW:
        return T_COMPACT
    if preset == "asuna-action":
        ran, chosen = tier_full.get(sid, (None, None))
        for value in (ran, chosen):
            if value == "高":
                return T_HIGH
            if value == "低":
                return T_LOW
        return T_UNARCH
    return PRESET_BY_NAME.get(preset, T_OTHER)


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
    """zstandard 解 → 逐行交回原始字节（原始行 sha256 是对账表判重键之一，解析前就得算）。

    必须跨帧：`stream_reader` 写死 `read_across_frames=True`。session.v4.jsonl.zstd 是多帧文件，
    默认（False）只解第一帧、到帧尾就当读到头——后面的帧静默丢掉：行数少算，且不报错。
    """
    import zstandard
    decompressor = zstandard.ZstdDecompressor()
    with open(path, "rb") as handle:
        # 跨帧解（SKILL.md 第二节「来源」那条）：去掉 read_across_frames=True 就是少算且不报错，别改回默认。
        with decompressor.stream_reader(handle, read_across_frames=True) as stream:
            with io.BufferedReader(stream, buffer_size=1 << 20) as reader:
                for raw in reader:
                    if raw and raw.strip():
                        yield raw


def scan_sessions(root, label, tier_by_session, tier_full, problems, dirs_by_prefix=None, counters=None):
    """一遍扫完：返回（调用行 occurrences，解不开的文件数，扫过的文件数）。
    occurrence 只带数字与判重键，不带原文。

    dirs_by_prefix 给了才计数（六格只数 home 根）；counters 记「有调用行形状但没 usage 键」与
    「time 不是整数」的行数——这些不进 token 列，只在覆盖面里报行数。"""
    occurrences = []
    unreadable = 0
    nfiles = 0
    if counters is None:
        counters = Counter()
    for sid, path in iter_session_files(root, problems):
        nfiles += 1
        prefix = "session-<uuid>" if sid.startswith("session-") else (
            sid.split("-")[0] + "-" + (sid.split("-")[1] + "-" if sid.count("-") > 1 else ""))
        if dirs_by_prefix is not None:
            dirs_by_prefix[prefix] = dirs_by_prefix.get(prefix, 0) + 1
        kind = classify(sid, tier_by_session)
        try:
            rows = []
            for raw in read_rows(path):
                rows.append((raw, json.loads(raw.decode("utf-8"))))
        except Exception as exc:                             # noqa: BLE001 单个文件坏了不拦整次读数
            unreadable += 1
            problems.append("解不开 %s（%s: %s）" % (path, type(exc).__name__, exc))
            continue
        created_ms = None
        preset = None
        for _raw, row in rows:
            if row.get("type") == FIRST_ROW:
                created_ms = parse_created_ms(row.get("createdAt"))
                value = row.get("agentPreset")
                preset = value if isinstance(value, str) and value else None
                break
        for raw, row in rows:
            row_type = row.get("type")
            if row_type not in (CALL_ROW, COMPACT_ROW):
                continue
            moment = row.get("time")
            if not isinstance(moment, int):
                counters["no_time"] += 1
                continue
            data = row.get("data") or {}
            usage = data.get("usage")
            if not isinstance(usage, dict):
                counters["compact_no_usage" if row_type == COMPACT_ROW else "call_no_usage"] += 1
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
                                "tkind": classify_table(row_type, preset, sid, tier_full),
                                "rtype": row_type,
                                "sid": sid, "created": created_ms or 0, "key": key,
                                "ikey": ("id", mid) if mid else None,
                                "ukey": ("usage", moment, numbers["inputTokens"], numbers["outputTokens"],
                                         numbers["totalTokens"], numbers["cacheReadTokens"],
                                         numbers["cacheWriteTokens"]),
                                "raw": hashlib.sha256(raw).hexdigest(),
                                "root": label,
                                "has_cache_read": "cacheReadTokens" in usage,
                                "copied": bool(created_ms and moment < created_ms), **numbers})
    if unreadable:
        problems.append("有 %d 个会话文件解不开，已从这次读数里跳过（不是全量）" % unreadable)
    return occurrences, unreadable, nfiles


def dedupe(occurrences):
    """六格用的旧去重：全局按判重键（id 或启发式）一条只算一次，归首次出现那一次
    （首次＝行内 time 最早，同刻按会话首行 createdAt）。"""
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


def dedupe_table(occurrences):
    """对账表用的并查集去重（2026-10-21 交代）：三把键任一相同即同一次调用——
    原始行字节 sha256（home↔archive 拷贝、播种带去的整行副本）、data.message.id、
    usage 组合（time＋五个 token 数，抓「父会话 compaction 行 ↔ 摘要会话调用行」这种不同形状的同一调用）。
    压缩那批没有 message.id，旧键对它们不生效——这就是必须带原始行 sha256 与 usage 组合的原因。
    归首次出现（time 最早；同刻按 createdAt、再按会话 id、再按根）那一次。返回 {index: 是否入选}。"""
    parent = list(range(len(occurrences)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    first = {}
    for i, item in enumerate(occurrences):
        for key in (item["raw"], item["ikey"], item["ukey"]):
            if key is None:
                continue
            j = first.get(key)
            if j is None:
                first[key] = j = i
            else:
                union(i, j)
    groups = {}
    for i in range(len(occurrences)):
        groups.setdefault(find(i), []).append(i)
    winner = {}
    for members in groups.values():
        best = min(members, key=lambda i: (occurrences[i]["t"], occurrences[i]["created"],
                                           occurrences[i]["sid"], occurrences[i]["root"]))
        for i in members:
            winner[i] = (i == best)
    return winner


def build_recon_table(occurrences, winner, lo_ms, hi_ms):
    """窗口内：入选且非拷贝的行进各自类行，其余（落选的重复行＋行 time 早于本会话 createdAt 的历史）
    全进拷贝行。合计另用一遍独立直加（total_direct），给断言当第二把尺。"""
    rows = {kind: Counter() for kind in TABLE_ROWS}
    copy = Counter()
    total_direct = Counter()
    window_rows = 0
    for i, item in enumerate(occurrences):
        if not lo_ms <= item["t"] < hi_ms:
            continue
        window_rows += 1
        fresh = item["inputTokens"]
        hit = item["cacheReadTokens"]
        write = item["cacheWriteTokens"]
        target = copy if ((not winner[i]) or item["copied"]) else rows[item["tkind"]]
        target["requests"] += 1
        target["prompt"] += fresh + hit + write
        target["hit"] += hit
        target["fresh"] += fresh
        target["write"] += write
        target["output"] += item["outputTokens"]
        if target is not copy:
            total_direct["requests"] += 1
            total_direct["prompt"] += fresh + hit + write
            total_direct["hit"] += hit
            total_direct["fresh"] += fresh
            total_direct["write"] += write
            total_direct["output"] += item["outputTokens"]
    return rows, copy, total_direct, window_rows


def assert_recon_table(rows, copy, total_direct, window_rows):
    """硬断言（写进脚本，不靠人眼）：不过就报错不出表。返回问题列表（空＝全过）。"""
    problems = []
    for kind in TABLE_ROWS:
        r = rows[kind]
        if r["prompt"] != r["hit"] + r["fresh"] + r["write"]:
            problems.append("断言① 行「%s」读入提示 %s ≠ 命中＋新读入＋写缓存 %s"
                            % (kind, r["prompt"], r["hit"] + r["fresh"] + r["write"]))
    for col in TABLE_COLS:
        summed = sum(rows[k][col] for k in TABLE_ROWS)
        if summed != total_direct[col]:
            problems.append("断言②③ 列「%s」各行之和 %s ≠ 独立直加 %s"
                            % (COL_NAMES[col], summed, total_direct[col]))
    counted = sum(rows[k]["requests"] for k in TABLE_ROWS)
    if counted + copy["requests"] != window_rows:
        problems.append("断言④ 窗口内 %s 条 ≠ 类行 %s ＋拷贝行 %s——有行静默丢了"
                        % (window_rows, counted, copy["requests"]))
    return problems


def fmt_int(value):
    """表内一律原始整数＋千分位（1,234,567）——四舍五入成万／亿之后各行加不齐，表就没法对账。"""
    return format(int(value), ",")


def rate_of(hit, prompt):
    return "无分母" if not prompt else "%.2f%%" % (100.0 * hit / prompt)


def offset_label(delta):
    """把一个 utcoffset() 写成 UTC+5 那样的偏移量：符号、小时、非整小时的 :MM 都照它算——不写死。"""
    minutes = delta.days * 1440 + delta.seconds // 60
    hours, extra = divmod(abs(minutes), 60)
    return "UTC%s%d" % ("-" if minutes < 0 else "+", hours) + ((":%02d" % extra) if extra else "")


def window_line(local_bounds, utc_bounds, zone_name, tz):
    """对账表表头那一行「窗口」。偏移量照窗口两端那一刻在 tz 里的真偏移现算——写死一个数，
    换夏令时那一天就会印错；两端相同只印一个，跨切换的那两天各印一个。"""
    labels = [offset_label(datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
                           .replace(tzinfo=timezone.utc).astimezone(tz).utcoffset())
              for text in utc_bounds]
    offset_text = labels[0] if labels[0] == labels[1] else "%s／%s" % (labels[0], labels[1])
    return "窗口：本地 %s → %s（%s，该日 %s）＝UTC %s → %s" % (
        local_bounds[0], local_bounds[1], zone_name, offset_text, utc_bounds[0], utc_bounds[1])


def render_recon_table(occurrences, winner, lo_ms, hi_ms, local_bounds, utc_bounds, zone_name,
                       roots, unreadable, read_at_local, read_at_utc, db_available, counters):
    """对账表整段：表头元信息（一行一条）→ 表 → 口径与子计数。断言不过只回报错行。"""
    rows, copy, total_direct, window_rows = build_recon_table(occurrences, winner, lo_ms, hi_ms)
    problems = assert_recon_table(rows, copy, total_direct, window_rows)
    if problems:
        return ["", "断言失败｜对账表不出（硬断言没过，先修读法再要表）："] + ["   " + p for p in problems], False

    def in_window(items):
        return [it for it in items if lo_ms <= it["t"] < hi_ms]

    comp_all = [it for it in occurrences if it["rtype"] == COMPACT_ROW]
    summ_all = [it for it in occurrences if it["rtype"] == CALL_ROW and it["tkind"] == T_COMPACT]
    raw_comp = {it["raw"] for it in comp_all}
    raw_summ = {it["raw"] for it in summ_all}
    uk_comp = {it["ukey"] for it in comp_all}
    uk_summ = {it["ukey"] for it in summ_all}
    combo_comp = {(it["inputTokens"], it["outputTokens"], it["totalTokens"],
                   it["cacheReadTokens"], it["cacheWriteTokens"]) for it in comp_all}
    combo_summ = {(it["inputTokens"], it["outputTokens"], it["totalTokens"],
                   it["cacheReadTokens"], it["cacheWriteTokens"]) for it in summ_all}
    gate_all = [it for it in occurrences if it["rtype"] == CALL_ROW and it["tkind"] == T_GATE]

    def multi_file(items, key_name):
        where = {}
        for it in items:
            where.setdefault(it[key_name], set()).add((it["root"], it["sid"]))
        return sum(1 for key, spots in where.items() if len(spots) > 1)

    lines = ["", "【对账表】一行一类；各行（不含拷贝行）之和＝合计。硬断言①②③④全过才印这张表。",
             "恒等式：读入提示＝命中＋新读入＋写缓存——每一行都能拿这一句自查。",
             "合计命中率＝总命中／总读入，不是各行命中率的平均；「门」行不报命中率"
             "（这一类的行没有 cacheReadTokens 字段），合计的分母也不含它（2026-10-27 口径）。",
             "命中率不适用的三类在表里只有「门」是单独一行、可摘出；摘要并进「压缩」行、"
             "网页界面会话按 preset 进「角色脑」行——那两类的摘出只在六格②⑤（按目录名前缀认的那把尺）生效。",
             "命中率＝命中／读入提示；分母含写缓存（cacheWrite 算未命中、留在分母里，六格⑤）。",
             window_line(local_bounds, utc_bounds, zone_name, zone_of(zone_name)),
             "一次请求：一条 type==\"assistant/message\" 记一次，按 data.message.id 去重；"
             "压缩行的请求数含 compaction/summary 行（无 id，按原始行 sha256＋usage 组合去重）。",
             "数据源根目录：%s" % "＋".join("%s（%s 个会话文件）" % (r, fmt_int(c)) for r, c in roots),
             "覆盖面：扫 %s 个文件、窗口内调用行 %s 条（去重前、含拷贝，按行 time 切）；解不开 %s 个；"
             "无截断（两根全量扫，未抽样）；无 usage 的记录行：compaction %s 条／assistant %s 条不进 token 列；"
             "time 不是整数的行 %s 条没进表"
             % (fmt_int(sum(c for _r, c in roots)), fmt_int(window_rows), fmt_int(unreadable),
                fmt_int(counters.get("compact_no_usage", 0)), fmt_int(counters.get("call_no_usage", 0)),
                fmt_int(counters.get("no_time", 0))),
             "生成时刻：本地 %s（%s）＝UTC %s" % (read_at_local, zone_name, read_at_utc),
             "口语总量：读入提示约 %.1f 万 token、输出约 %.1f 万 token——表内一律原始整数＋千分位，一种写法。"
             % (total_direct["prompt"] / 10000.0, total_direct["output"] / 10000.0)]
    if not db_available:
        lines.append("注意：库里连不上，行动脑档位没读到——行动脑全进未归档，不是没跑过高档。")
    lines.append("")
    lines.append("类别｜请求数｜读入提示｜命中｜新读入｜写缓存｜输出｜命中率")
    for kind in TABLE_ROWS:
        r = rows[kind]
        lines.append("%s｜%s｜%s｜%s｜%s｜%s｜%s｜%s"
                     % (kind, fmt_int(r["requests"]), fmt_int(r["prompt"]), fmt_int(r["hit"]),
                        fmt_int(r["fresh"]), fmt_int(r["write"]), fmt_int(r["output"]),
                        ("不适用（这一类的行没有 cacheReadTokens 字段）" if kind in TABLE_NA
                         else rate_of(r["hit"], r["prompt"]))))
    lines.append("%s｜%s｜%s｜%s｜%s｜%s｜%s｜%s"
                 % (T_TOTAL, fmt_int(total_direct["requests"]), fmt_int(total_direct["prompt"]),
                    fmt_int(total_direct["hit"]), fmt_int(total_direct["fresh"]),
                    fmt_int(total_direct["write"]), fmt_int(total_direct["output"]),
                    rate_of(total_direct["hit"] - rows[T_GATE]["hit"],
                            total_direct["prompt"] - rows[T_GATE]["prompt"])))
    lines.append("%s｜%s｜%s｜%s｜%s｜%s｜%s｜%s"
                 % (T_COPY, fmt_int(copy["requests"]), fmt_int(copy["prompt"]), fmt_int(copy["hit"]),
                    fmt_int(copy["fresh"]), fmt_int(copy["write"]), fmt_int(copy["output"]),
                    rate_of(copy["hit"], copy["prompt"])))
    lines += ["",
              "拷贝判定：同一次调用只数一次——同一 data.message.id、同一原始行字节 sha256、"
              "同一 usage 组合（time＋input/output/total/cacheRead/cacheWrite 五个数）任一相同即同一次，"
              "归首次出现（time 最早；同刻按会话首行 createdAt、再按会话 id、再按根）那一次；"
              "其余出现、以及行 time 早于本会话首行 createdAt 的行（分叉／播种带进来的历史），"
              "都进「拷贝行」，不计入合计。",
              "行归属：按会话首行 agentPreset 认——asuna-xiaoman→角色脑；asuna-action→按所配任务 tier.ran"
              "（缺则 tier.chosen）分高／低，两个都分不出进未归档；asuna-summary→压缩；asuna-attend→门；"
              "asuna-scheduler→调度；compaction/summary 行一律进压缩；其余 preset／缺 preset→其余。",
              "压缩子计数（2026-10-21 交代：①父会话里的 compaction 行与②摘要会话自己的调用行可能是同一调用记两遍，"
              "先量重合再合并）：①带 usage 的 compaction/summary 行 全史 %s／窗口内 %s；"
              "②asuna-summary 会话调用行 全史 %s／窗口内 %s；"
              "两批重合：原始行 sha256 相同 %s 条、usage 组合（含 time）相同 %s 条、"
              "只看五个 token 数不含 time 相同 %s 条（最后这个只当线索，没拿去重依据）；"
              "去重后进压缩行（窗口内）%s 条。"
              % (fmt_int(len(comp_all)), fmt_int(len(in_window(comp_all))),
                 fmt_int(len(summ_all)), fmt_int(len(in_window(summ_all))),
                 fmt_int(len(raw_comp & raw_summ)), fmt_int(len(uk_comp & uk_summ)),
                 fmt_int(len(combo_comp & combo_summ)), fmt_int(rows[T_COMPACT]["requests"])),
              "门重复检查：门调用行里 usage 组合出现在 2 处以上（跨文件／跨根）的 %s 条、"
              "原始行 sha256 相同的 %s 条（全史）。"
              % (fmt_int(multi_file(gate_all, "ukey")), fmt_int(multi_file(gate_all, "raw"))),
              "断言（写进脚本，不靠人眼）：①每行 读入提示＝命中＋新读入＋写缓存；"
              "②各行（不含拷贝行）之和＝合计每一列（合计另用一遍独立直加核对）；③请求数同样加和相等；"
              "④窗口内每条要么进类行要么进拷贝行。不过就报错不出表。"]
    return lines, True


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


def na_hit_rate(kind):
    """这一类不报命中率（整类缺 cacheReadTokens 字段，按 0 计入会误导）。"""
    return kind in NA_HIT_RATE


def empty_totals():
    """一类什么都没量到时的零值（读数里那一类没出现时也要能报 0／0）。"""
    return {name: 0 for name in TOTALS_KEYS}


def split_na(totals, per_kind):
    """把「不适用命中率」那三类从合计里摘出去：返回（摘出后的合计，这三类之和）。"""
    out = dict(totals)
    na = {name: 0 for name in TOTALS_KEYS}
    for kind in NA_HIT_RATE:
        stats = per_kind.get(kind)
        if not stats:
            continue
        for name in TOTALS_KEYS:
            out[name] -= stats[name]
            na[name] += stats[name]
    return out, na



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
                "同类内重复记 %s；缺 cacheReadTokens %s 行%s）"
                "｜input %s／cacheRead %s／cacheWrite %s｜命中率 %s（仅自有 %s）%s"
                % (stats["rows"], stats["own"], stats["copied"], stats["copied_time"],
                   stats["copied_other"], stats["dup_same"], stats["no_cache_read_field"],
                   "（整类缺该字段，这一类不报命中率）" if na_hit_rate(kind) else "按 0 算",
                   stats["inputTokens"], stats["cacheReadTokens"], stats["cacheWriteTokens"],
                   "不适用（这一类的行没有 cacheReadTokens 字段）" if na_hit_rate(kind)
                   else rate_text(hit_rate(stats)),
                   "不适用" if na_hit_rate(kind) else rate_text(own_rates.get(kind)),
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
    applicable, excluded = split_na(totals, per_kind)
    lines = ["⑤ 命中率｜窗口内调用行 %s 行、全局去重后 %s 行（判重键 data.message.id；"
             "压缩行没有这个字段，退回启发式键 time＋四个 token 数）｜命中率 %s（分母不含「不适用命中率」三类）｜"
             "input %s／cacheRead %s／cacheWrite %s／output %s／total %s｜"
             "缺 cacheReadTokens 字段的行 %s 行（其中「不适用」那三类 %s 行不进命中率；"
             "其余 %s 行按 0 计入，是推断）"
             % (totals["rows"], totals["kept"], rate_text(hit_rate(applicable)),
                applicable["inputTokens"], applicable["cacheReadTokens"],
                applicable["cacheWriteTokens"], applicable["outputTokens"],
                applicable["totalTokens"], totals["no_cache_read_field"],
                excluded["no_cache_read_field"],
                totals["no_cache_read_field"] - excluded["no_cache_read_field"])]
    lines.append("   不适用命中率（单列一行说明）：%s 三类不报命中率，也不进上面那个分母——%s。"
                 % ("／".join(NA_HIT_RATE), NA_HIT_RATE_WHY))
    lines.append("   摘出去的那三类的量：去重后 %s 行／缺 cacheReadTokens 字段 %s 行｜"
                 "input %s／cacheRead %s／cacheWrite %s（照旧报数，只是不打比率）"
                 % (excluded["kept"], excluded["no_cache_read_field"], excluded["inputTokens"],
                    excluded["cacheReadTokens"], excluded["cacheWriteTokens"]))
    lines.append("   这一窗实测（缺该字段的行数／该类去重后行数）：%s"
                 % ("／".join("%s %s／%s" % (kind,
                                (per_kind.get(kind) or empty_totals())["no_cache_read_field"],
                                (per_kind.get(kind) or empty_totals())["kept"])
                         for kind in NA_HIT_RATE)))
    for kind in KIND_ORDER:
        if kind not in per_kind:
            continue
        stats = per_kind[kind]
        lines.append("   %s：去重后 %s 行（自有 %s／拷贝 %s，其中行 time 早于本会话 createdAt %s）｜"
                     "input %s／cacheRead %s／cacheWrite %s｜命中率 %s（仅自有 %s）"
                     % (kind, stats["kept"], stats["own"], stats["copied"], stats["copied_time"],
                        stats["inputTokens"],
                        stats["cacheReadTokens"], stats["cacheWriteTokens"],
                        "不适用（这一类的行没有 cacheReadTokens 字段）" if na_hit_rate(kind)
                        else rate_text(hit_rate(stats)),
                        "不适用" if na_hit_rate(kind) else rate_text(own_rates.get(kind))))
    lines.append("   来源=盘 %s/**/%s 的 type／time／data.usage 五个数／data.message.id＋首行 createdAt"
                 % (root or "（没找到）", SESSION_FILE))
    lines.append("   筛法=命中率＝cacheRead/(input＋cacheRead＋cacheWrite)（写缓存算未命中、留在分母里，六格⑤）；"
                 "token 加权（各类先求和再相除，不是各条比例再平均）；先全局去重再按类求和；窗口按行 time；「不适用命中率」那三类不进这个分母（2026-10-27 口径）")
    return lines, True


# --------------------------------------------------------------------------- 离线自检（不读盘、不连库）

def selfcheck():
    """纯逻辑自检：认法、命中率式子、跨类去重、拷贝判定、窗口切法、对账表三把键与断言。给 check_skill.py 跑通用。"""
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

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
    check("created_ms_is_int_on_disk", parse_created_ms(1_792_193_565_157) == 1_792_193_565_157)
    check("created_ms_parses_both_iso_forms", parse_created_ms("2026-10-16T07:56:38.123456+00:00")
          == parse_created_ms("2026-10-16T07:56:38.123456Z"))
    check("created_ms_rejects_junk", parse_created_ms("不是时间") is None
          and parse_created_ms(None) is None and parse_created_ms(True) is None)
    check("utc_bounds_are_naive_utc", utc_str_to_ms("2026-10-16T05:00:00")
          == int(datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc).timestamp() * 1000))

    # ---- 对账表（2026-10-21 口径）：行归属、三把键去重、拷贝行、断言、数字写法
    tiers = {"a-h": ("高", "高"), "a-l": ("低", "高"), "a-c": (None, "低"), "a-n": (None, None)}
    check("classify_table_role", classify_table(CALL_ROW, "asuna-xiaoman", "s", tiers) == T_ROLE)
    check("classify_table_compaction_row", classify_table(COMPACT_ROW, "asuna-xiaoman", "s", tiers) == T_COMPACT)
    check("classify_table_gate", classify_table(CALL_ROW, "asuna-attend", "s", tiers) == T_GATE)
    check("classify_table_scheduler", classify_table(CALL_ROW, "asuna-scheduler", "s", tiers) == T_SCHED)
    check("classify_table_missing_preset", classify_table(CALL_ROW, None, "s", tiers) == T_OTHER)
    check("classify_table_unknown_preset", classify_table(CALL_ROW, "asuna-whatever", "s", tiers) == T_OTHER)
    check("classify_table_action_ran", classify_table(CALL_ROW, "asuna-action", "a-h", tiers) == T_HIGH)
    check("classify_table_action_ran_beats_chosen", classify_table(CALL_ROW, "asuna-action", "a-l", tiers) == T_LOW)
    check("classify_table_action_chosen_fallback", classify_table(CALL_ROW, "asuna-action", "a-c", tiers) == T_LOW)
    check("classify_table_action_unarchived", classify_table(CALL_ROW, "asuna-action", "a-n", tiers) == T_UNARCH)
    check("classify_table_action_no_task", classify_table(CALL_ROW, "asuna-action", "a-x", tiers) == T_UNARCH)

    def trow(moment, tkind, mid, created, inp, cache_read, cache_write, out, total, sid, raw,
             rtype=CALL_ROW, root="home"):
        return {"t": moment, "kind": tkind, "tkind": tkind, "rtype": rtype, "sid": sid, "created": created,
                "root": root, "key": ("id", mid) if mid else ("heur", moment, inp, out, cache_read, cache_write, total),
                "ikey": ("id", mid) if mid else None,
                "ukey": ("usage", moment, inp, out, total, cache_read, cache_write), "raw": raw,
                "has_cache_read": True, "copied": moment < created, "inputTokens": inp,
                "cacheReadTokens": cache_read, "cacheWriteTokens": cache_write,
                "outputTokens": out, "totalTokens": total}

    # 同一会话在 home 与 archive 各一份：原始行 sha256 相同 → 只数一次
    pair = [trow(100, T_ROLE, "m1", 50, 10, 90, 5, 7, 112, "asuna-role-a", "RA", root="home"),
            trow(100, T_ROLE, "m1", 50, 10, 90, 5, 7, 112, "asuna-role-a", "RA", root="archive")]
    won = dedupe_table(pair)
    check("table_dedup_raw_across_roots", sum(1 for v in won.values() if v) == 1)

    # 父会话 compaction 行（无 id）↔ 摘要会话调用行（有 id）：usage 组合相同 → 同一调用，只数一次、进压缩
    cross = [trow(200, T_COMPACT, None, 50, 20, 80, 4, 6, 110, "asuna-role-a", "RB", rtype=COMPACT_ROW),
             trow(200, T_COMPACT, "s1", 190, 20, 80, 4, 6, 110, "asuna-summary-x", "RC")]
    won = dedupe_table(cross)
    rows_t, copy_t, direct_t, win_rows_t = build_recon_table(cross, won, 0, 1000)
    check("table_dedup_compaction_via_ukey",
          sum(1 for v in won.values() if v) == 1 and rows_t[T_COMPACT]["requests"] == 1
          and copy_t["requests"] == 1)

    # 拷贝行收集落选行与「time 早于 createdAt」的历史行；断言四格各抓各的
    mix = [trow(300, T_ROLE, "m2", 100, 30, 70, 0, 9, 109, "asuna-role-a", "RD"),
           trow(300, T_ROLE, "m2", 150, 30, 70, 0, 9, 109, "asuna-errand-b", "RE"),
           trow(50, T_ROLE, "m3", 100, 1, 1, 0, 1, 3, "asuna-role-a", "RF"),
           trow(900, T_GATE, "m4", 800, 2, 8, 0, 1, 11, "asuna-attend-a", "RG"),
           trow(5000, T_GATE, "m5", 800, 2, 8, 0, 1, 11, "asuna-attend-a", "RH")]
    won = dedupe_table(mix)
    rows_t, copy_t, direct_t, win_rows_t = build_recon_table(mix, won, 0, 1000)
    check("table_copy_row_collects_loser_and_history",
          rows_t[T_ROLE]["requests"] == 1 and copy_t["requests"] == 2 and rows_t[T_GATE]["requests"] == 1)
    check("table_window_cuts_by_row_time", win_rows_t == 4)
    check("table_assert_passes_on_good", assert_recon_table(rows_t, copy_t, direct_t, win_rows_t) == [])
    broken = {k: Counter(v) for k, v in rows_t.items()}
    broken[T_ROLE]["prompt"] += 1
    check("table_assert_catches_bad_identity",
          any("断言①" in p for p in assert_recon_table(broken, copy_t, direct_t, win_rows_t)))
    check("table_assert_catches_bad_total",
          any("断言②③" in p for p in assert_recon_table(rows_t, copy_t, broken[T_ROLE], win_rows_t)))
    check("table_assert_catches_missing_row",
          any("断言④" in p for p in assert_recon_table(rows_t, copy_t, direct_t, win_rows_t + 1)))
    check("table_thousands_separator", fmt_int(1_234_567) == "1,234,567" and fmt_int(0) == "0")
    check("table_rows_list_complete",
          TABLE_ROWS == (T_ROLE, T_HIGH, T_LOW, T_UNARCH, T_COMPACT, T_GATE, T_SCHED, T_OTHER))

    # 2026-10-27 口径：摘要／门／网页界面会话不报命中率，也不进合计的分母
    check("na_hit_rate_list", NA_HIT_RATE == ("摘要", "门", "网页界面会话")
          and all(kind in KIND_ORDER for kind in NA_HIT_RATE) and TABLE_NA == (T_GATE,))
    role = {name: 0 for name in TOTALS_KEYS}
    role.update({"rows": 2, "kept": 2, "own": 2, "inputTokens": 100,
                 "cacheReadTokens": 300, "cacheWriteTokens": 100})
    gate = {name: 0 for name in TOTALS_KEYS}
    gate.update({"rows": 3, "kept": 3, "own": 3, "inputTokens": 500, "no_cache_read_field": 3})
    small = {"rows": 1, "kept": 1, "own": 1, "inputTokens": 50, "no_cache_read_field": 1}
    per = {"我的对话": role, T_GATE: gate, "摘要": dict(gate, **small), "网页界面会话": dict(gate, **small)}
    tot = {name: sum(stats[name] for stats in per.values()) for name in TOTALS_KEYS}
    applicable, excluded = split_na(tot, per)
    check("na_out_of_denominator",
          applicable["inputTokens"] == 100 and excluded["inputTokens"] == 600
          and abs(hit_rate(applicable) - 60.0) < 1e-9)
    check("na_split_keeps_total_identity",
          all(applicable[name] + excluded[name] == tot[name] for name in TOTALS_KEYS))
    head, _head_ok = cell_hit_rate(tot, per, {}, None)
    check("na_line_explains_why",
          any("不适用命中率" in line and "cacheReadTokens" in line and "10-17" in line for line in head))
    check("na_head_rate_excludes_na",
          any("命中率 60.00%（分母不含「不适用命中率」三类）" in line for line in head))
    check("na_per_kind_says_na",
          any(line.strip().startswith(T_GATE + "：") and "命中率 不适用" in line for line in head))
    check("na_other_kind_still_numeric",
          any(line.strip().startswith("我的对话：") and "命中率 60.00%" in line for line in head))
    kind_lines, _kind_ok = cell_kinds(None, per, tot, {}, None, {})
    check("cell_kinds_marks_na",
          any("门（前缀 asuna-attend-）" in line and "命中率 不适用" in line for line in kind_lines)
          and any("我的对话（前缀 asuna-role-）" in line and "命中率 60.00%" in line for line in kind_lines))

    # 钉住「那一行印出来的偏移是那一刻现算的、不是写死的」。时区用夹具（不写这台机器的城市名：
    # personal-scan 的 timezone 类会把那个字面记成一处命中）：一个假时区，按月份切两个固定偏移，
    # 切法是编出来的。样本日期由测试自己给，不取当前时刻、不连库、不联网。
    class FixtureTz(tzinfo):
        """夹具时区（假）：按月份切两个固定偏移——当地月份 4～9 月 +6、10～3 月 +5（切法编造）。"""

        def utcoffset(self, moment):
            return timedelta(hours=5) if (moment.month >= 10 or moment.month <= 3) else timedelta(hours=6)

        def dst(self, moment):
            return timedelta(0) if (moment.month >= 10 or moment.month <= 3) else timedelta(hours=1)

        def tzname(self, moment):
            return "fixture-zone"

    fixture = FixtureTz()
    # 一个样本在 +6 那一侧（UTC 2026-07-15T00:00 → 当地当日 06:00），一个在 +5 那一侧
    # （UTC 2026-10-28T23:00 → 当地次日 04:00）：写死任何一个数都会被其中一条抓到。
    for day, utc_noon, expect in (("2026-07-15", "2026-07-15T00:00:00", "UTC+6"),
                                  ("2026-10-29", "2026-10-28T23:00:00", "UTC+5")):
        printed = window_line((day + " 12:00:00", day + " 12:00:00"),
                              (utc_noon, utc_noon), "fixture-zone", fixture)
        check("window_offset_true_on_" + day, ("（fixture-zone，该日 %s）＝UTC" % expect) in printed,
              "期望印 %s／实得那一行：%s" % (expect, printed))
    # 窗口跨夹具的月份切换（一端 +6、一端 +5）：那一格必须两个标签都印，不许只留一个
    straddle = window_line(("2026-07-15 12:00:00", "2026-10-29 12:00:00"),
                           ("2026-07-15T00:00:00", "2026-10-28T23:00:00"), "fixture-zone", fixture)
    check("window_offset_two_labels_across_switch",
          "（fixture-zone，该日 UTC+6／UTC+5）＝UTC" in straddle,
          "期望两个标签 UTC+6／UTC+5／实得那一行：%s" % straddle)


    failed = [(name, detail) for name, ok, detail in checks if not ok]
    for name, detail in failed:
        print("FAIL selfcheck %s%s" % (name, ("  <- " + detail) if detail else ""))
    print("SELFCHK %d/%d 通过（纯逻辑：种类认法、命中率分母含写缓存、跨类按 id 去重归首次、拷贝判定、"
          "窗口按行切；对账表：preset 行归属、行动脑 ran→chosen 退回与未归档、三把键去重（原始行 sha256／"
          "message.id／usage 组合）、拷贝行、四条硬断言、千分位写法；没读盘、没连库）"
          % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


# --------------------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(description="asuna-usage-readout：对账表＋六格读数（只读）")
    parser.add_argument("--days", type=float, default=1.0, help="窗口长度（天），默认 1＝最近 24 小时")
    parser.add_argument("--since", help="窗口起点，本地钟点 2026-10-16 或 2026-10-16 20:30（给了就不看 --days）")
    parser.add_argument("--until", help="窗口终点，本地钟点；默认＝读的那一刻")
    parser.add_argument("--sessions-root", help="会话记录根目录，默认 <data>/adr008/home/sessions")
    parser.add_argument("--archive-root", help="归档会话根目录，默认 <data>/adr008/archive/sessions")
    parser.add_argument("--no-archive", action="store_true", help="对账表也只扫 home（覆盖面会写明少了归档根）")
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
    read_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    root = resolve_sessions_root(args.sessions_root, problems)
    archive_root = None if args.no_archive else resolve_archive_root(args.archive_root)
    if archive_root and not os.path.isdir(archive_root):
        problems.append("没找到归档根 %s——对账表只扫了 home，覆盖面照实写" % archive_root)
        archive_root = None
    dbread, db_error = (None, "带了 --no-db") if args.no_db else resolve_database()
    if db_error and not args.no_db:
        problems.append("dbread 连不上（%s）——库里那三格没读到，不是没有数据" % db_error)

    tier_by_session = {}
    tier_full_by_session = {}
    if dbread:
        tier_by_task = {row["_id"]: ((row.get("tier") or {}).get("ran"),
                                     (row.get("tier") or {}).get("chosen"))
                        for row in page(dbread, "tasks", {"tier": {"$exists": True}}, ["_id", "tier"])}
        for row in page(dbread, "sessions", {"_id": {"$regex": "^asuna-action-"},
                                             "task_id": {"$exists": True, "$ne": None}}, ["_id", "task_id"]):
            ran, chosen = tier_by_task.get(row.get("task_id"), (None, None))
            if ran:
                tier_by_session[row["_id"]] = ran
            if ran or chosen:
                tier_full_by_session[row["_id"]] = (ran, chosen)

    unreadable = 0
    counters = Counter()
    dirs_by_prefix = {}
    occ_home, occ_all = [], []
    roots = []
    if root:
        found, bad, nfiles = scan_sessions(root, "home", tier_by_session, tier_full_by_session,
                                           problems, dirs_by_prefix, counters)
        occ_home = found
        occ_all += found
        unreadable += bad
        roots.append((root, nfiles))
    else:
        roots.append(("（home 根没找到）", 0))
    if archive_root:
        found, bad, nfiles = scan_sessions(archive_root, "archive", tier_by_session, tier_full_by_session,
                                           problems, None, counters)
        occ_all += found
        unreadable += bad
        roots.append((archive_root, nfiles))
    elif not args.no_archive:
        roots.append(("（归档根没找到）", 0))

    # 对账表：两个根一起、三把键并查集去重（跨根），断言过了才印
    winner = dedupe_table(occ_all)
    table_lines, table_ok = render_recon_table(
        occ_all, winner, lo_ms, hi_ms, local_bounds, utc_bounds, zone_name, roots,
        unreadable, read_at, read_at_utc, bool(dbread), counters)

    # 六格：口径没动，仍只数 home 根（覆盖面在表头写明）
    best = dedupe(occ_home)
    per_kind, totals = aggregate(occ_home, best, lo_ms, hi_ms)
    own_rates = {kind: own_slice(occ_home, best, lo_ms, hi_ms, kind) for kind in per_kind}
    disk_rows = len([1 for item in occ_home if lo_ms <= item["t"] < hi_ms]) if root else None

    # 读数完整性闸门：解不开的东西与「窗口内 0 行」既进 problems，也进退出码。
    # 来路（2026-10-19 交代）：这台机器没装 zstandard 那次跑 --days 7，926 个文件全解不开，
    # 六格照出、退出码还是 0，ModuleNotFoundError 只塞在 stdout 最后一行——跑绿了但什么都没跑出来，
    # 照那样交上去就是一张「我这七天什么都没干」。解不开＝那一格没有分母；0 行＝先怀疑读法。
    gate_problems = []
    if unreadable:
        gate_problems.append("解不开 %d 个会话文件——那一格没有分母，不是没有数据" % unreadable)
    if root and disk_rows == 0:
        gate_problems.append("窗口内一条调用行都没解出来（0 行）——先怀疑解不开／窗口给错，"
                             "别报成「这七天什么都没干」")
    gate_ok = not gate_problems
    problems.extend(gate_problems)

    print("asuna-usage-readout 读数｜脚本 %s｜窗口＝本地 %s → %s（%s）"
          % (os.path.abspath(__file__), local_bounds[0], local_bounds[1], zone_name))
    print("\n".join(table_lines))
    ok = [table_ok]
    print("\n—— 以下六格长句读数（每周三张表的原料，口径见 SKILL.md 第三节；只数 home 根）——")
    for lines, cell_ok in (
            cell_window(dbread, window, local_bounds, disk_rows, zone_name, zone_source, read_at, root),
            cell_tiers(dbread, window),
            cell_kinds(dbread, per_kind, totals, dirs_by_prefix, root, own_rates),
            cell_reflect(dbread, per_kind, dirs_by_prefix, root),
            cell_refusals(dbread, window),
            cell_hit_rate(totals, per_kind, own_rates, root)):
        print("\n".join(lines))
        ok.append(cell_ok)
    # 这一行永远打出来：解不开几个／窗口内几行，摆在明面上，不用去翻最后一行
    print("读数完整性｜解不开 %s 个／窗口内 %s 行（调用行，去重前，home 根）｜%s"
          % (unreadable, "?" if disk_rows is None else disk_rows,
             "过" if gate_ok else "没过（退出码非零）"))
    if problems:
        print("没读到／要留神的：%s" % "；".join(problems))
    print("读法提醒：交回只等于交回；拷贝占比高的那一类要标样本量；"
          "这些数当天就会旧，跨趟对数先对「几点读的」再对数。")
    return 0 if (all(ok) and gate_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
