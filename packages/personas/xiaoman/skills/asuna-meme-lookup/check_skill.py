#!/usr/bin/env python3
"""asuna-meme-lookup 的零依赖离线自检。

查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、scene_kinds 覆盖 home／group／dm、
   章节齐、脚本能编译、换行是 LF（读字节数 CR，文本模式那把尺看不见 CR）；
2. 内容要点：路线 a 的实测形状字面（URL、web_fetch 不通的结论、archive、单帖结构、探针、收录边界）、
   路线 b 三问、输出格式四字段与排序、委托与约束的字面要点（逐条判，不合并）；
3. 不带别人的个人信息：禁词表与字面编号（#数字）不该出现在正文；这台机器的私密名单可达就真扫
   （命中只报类别与名单行号，词本身不打印）；配不上、或名单在却解析出 0 条有效词，都记一条红
   `leak_scan_ran`——「没跑」不许长得像「过了」；
4. 没有占位符残留。

不联网、不碰数据库、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-meme-lookup/check_skill.py   # 候选根目录
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import re
import sys

# 宿主普通 Windows 控制台默认码页可能不是 UTF-8：中文一 print 就整段崩。输出字节固定成 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 什么时候值得查",
    "## 谁执行查询：出门那一轮 delegate 一趟",
    "## 行动脑查询路线",
    "### 路线 a：梗指南频道（新梗优先）",
    "### 路线 b：web_search 现查（老梗与频道空白）",
    "## 输出格式（按能不能直接现挂排序）",
    "## 用法约束",
    "## 版本",
]

# 路线 a：2026-10-26 实测形状的字面锚点。少哪条，红的就是哪条。
ROUTE_A = [
    ("route_a_channel_url", "https://neodrop.ai/channel/YZNqEhR2owd"),
    ("route_a_webfetch_dead", "此路不通"),
    ("route_a_webfetch_shell", "导航空壳"),
    ("route_a_raw_get", "剥掉标签"),
    ("route_a_archive", "/archive/1"),
    ("route_a_post_shape", "/post/<id>"),
    ("route_a_probe", "meme_channel_probe.py"),
    ("route_a_coverage_floor", "2026-08-15"),
    ("route_a_no_force_match", "别硬配"),
]

# 路线 b：三问与「当没查到」
ROUTE_B = [
    ("route_b_what", "梗本体是什么"),
    ("route_b_usage", "常见用法"),
    ("route_b_when", "大约什么时候火起来"),
    ("route_b_not_found", "当没查到"),
]

# 输出格式：排序 + 四字段 + 三种标注
OUT = [
    ("out_sort_by_usable", "现挂好到难"),
    ("out_field_body", "梗的一句话本体"),
    ("out_field_context", "适用语境"),
    ("out_field_time", "火的大致时间段"),
    ("out_flag_stale", "可能已凉"),
    ("out_flag_unverified", "时间未核实"),
    ("out_flag_risk", "风险标注"),
    ("out_risk_no_blank", "未见明确争议"),
]

# 出门轮委托与用法约束
RULES = [
    ("rule_delegate", "delegate 行动脑一趟"),
    ("rule_delegate_low", "低档"),
    ("rule_note_beat_no_delegate", "被便条／差事叫起的那一拍 delegate 用不了"),
    ("rule_no_memory_hang", "凭印象编梗义硬挂"),
    ("rule_cold_topic_notes", "别为挂而挂"),
    ("rule_brief_verbatim", "原词／原句照抄"),
    ("rule_brief_four_fields", "四字段照抄进 brief"),
    ("rule_no_invent", "不许编梗义"),
    ("rule_context_mine", "场合由我判断"),
    ("rule_skill_not_decide", "技能不替我决定说不说"),
    ("rule_conflict_both", "两说并存"),
]

# 别人的个人信息不进技能：称呼与场景词，出现即红。具体人名群名不写进这张表——仓库是公开的，
# 表里的字本身就会把人带出去；字面编号由 LITERAL_ID 查。
PERSONAL_TOKENS = [
    "主人", "旧居", "交流群", "姐姐",
]

# 具体的人和地方由这台机器的私密名单拦（private_words 工具维护；永远不进仓库）：
# ASUNA_PRIVATE_WORDS 指的文件，否则 <数据目录>/private/personal-words.txt。一行一条 category|word|why。
# 纯字母数字的词按整词、不分大小写；别的按出现即中。命中只报类别和名单第几行，不打印词本身。
def private_list():
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as asuna_config
            data = str(asuna_config.DATA)
        except Exception:                                   # noqa: BLE001 没装 asuna 也要能跑
            data = None
    candidates = []
    if named:
        candidates.append(named)
    if data:
        candidates.append(os.path.join(data, "private", "personal-words.txt"))
    # 兜底：环境变量都没设、asuna 又不在 sys.path 上时，从脚本往上找 <部署根>/.runtime/private/。
    # 三条都不中才算没配上，那时调用方记一条红，不许 print 一行 NOTE 算过。
    here = HERE
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        candidates.append(os.path.join(here, ".runtime", "private", "personal-words.txt"))
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        entries = []
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                parts = line.strip().split("|", 2)
                if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                    entries.append((number, parts[0].strip(), parts[1].strip()))
        return path, entries
    return [c for c in candidates if c] or None, None


def listed_hits(entries, text):
    hits = []
    for number, category, word in entries:
        if all(ch.isascii() for ch in word):
            found = re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE)
        else:
            found = word in text
        if found:
            hits.append("%s（名单第 %d 行）" % (category, number))
    return hits


# 字面编号（#12 这种）是具体坐标，规则里只该出现占位的「#编号」
LITERAL_ID = re.compile(r"#\d")

PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")


def read_frontmatter(text):
    """返回 (fields, body)；frontmatter 不合法就返回 (None, text)。"""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    head = text[3:end].strip("\n")
    body = text[end + 4:]
    fields = {}
    for line in head.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields, body


def cr_bytes(paths):
    """字节级数 CR。文本模式读会把 CR 吃掉，查换行永远绿——只有读字节才看得见。"""
    bad = []
    for target in paths:
        try:
            with open(target, "rb") as handle:
                count = handle.read().count(b"\r")
        except OSError as exc:                           # noqa: BLE001 读不了也要报出来
            bad.append("%s（读不了：%s）" % (os.path.basename(target), exc))
            continue
        if count:
            bad.append("%s（%d 个 CR 字节）" % (os.path.basename(target), count))
    return bad


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SKILL.md")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    exists = os.path.isfile(path)
    check("skill_file_exists", exists, path)
    text = ""
    if exists:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()

    fields, body = read_frontmatter(text)
    check("frontmatter_parses", fields is not None)
    check("frontmatter_name_present", bool(fields and fields.get("name")))
    check("name_matches_directory",
          bool(fields and fields.get("name") == EXPECTED_NAME),
          "name=%s dir=%s" % ((fields or {}).get("name"), EXPECTED_NAME))
    desc = (fields or {}).get("description", "")
    check("description_specific_enough", len(desc) >= 100, "len=%d" % len(desc))

    # 这份技能两半都要人读到：出门拍（group／dm）看前半，行动脑（home）看后半，掉哪个场合都瘸。
    kinds_raw = (fields or {}).get("scene_kinds", "")
    kinds = re.findall(r"[a-z]+", kinds_raw)
    check("scene_kinds_cover_home_group_dm",
          all(kind in kinds for kind in ("home", "group", "dm")),
          "scene_kinds=%s" % (kinds_raw or "没写"))

    for i, section in enumerate(SECTIONS):
        check("section_" + str(i), ("\n" + section) in ("\n" + body), section)

    for group in (ROUTE_A, ROUTE_B, OUT, RULES):
        for name, token in group:
            check(name, token in body, token)

    # 个人信息扫描：只扫 SKILL.md 正文（本脚本的禁词表是检查器自己的，不算）
    hits = [tok for tok in PERSONAL_TOKENS if tok in body]
    check("no_personal_info", not hits, ",".join(hits))
    check("no_literal_ids", not LITERAL_ID.search(body),
          "出现字面编号：" + ",".join(LITERAL_ID.findall(body)[:5]))

    listed_path, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False,
              "私密名单没配上（试过 %s）：真人名／群名这一项没真查——不是跑过了"
              % ("、".join(listed_path) if listed_path else "都没有"))
        leak_note = ""
    elif not entries:
        check("leak_scan_ran", False,
              "名单 0 条（%s）——没真查，不是跑过了" % listed_path)
        leak_note = ""
    else:
        found = listed_hits(entries, text)
        check("no_listed_words", not found, "、".join(found))
        leak_note = "，泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries)

    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 800, "body_chars=%d" % len(body))
    check("selfcheck_documented", "check_skill.py" in body)

    # 同目录脚本：必须存在且语法能编译（内存 compile，不落文件——沙箱里技能目录可能不让写）。
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    for script in scripts:
        try:
            with open(os.path.join(HERE, script), "rb") as handle:
                source = handle.read()
            compile(source, os.path.join(HERE, script), "exec")
            check("compiles_" + script, True)
        except Exception as exc:  # noqa: BLE001 编译失败要原样报出来
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

    cr_files = cr_bytes([path] + [os.path.join(HERE, script) for script in scripts])
    check("line_endings_are_lf", not cr_files,
          "有 CR（仓库守卫会红）：" + "、".join(cr_files))

    stray = [d for d in os.listdir(HERE) if d == "__pycache__"]
    notes = []
    if stray:
        notes.append("NOTE 技能目录里有 __pycache__，发布前清掉："
                     "find skills -name '__pycache__' -type d -prune -exec rm -rf {} +")

    total = len(results)
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, detail in results:
        if not ok and detail:
            print("FAIL %s  <- %s" % (name, detail))
    for line in notes:
        print(line)
    if failed:
        print("%d/%d 通过，失败：%s" % (total - len(failed), total, ", ".join(failed)))
        return 1
    print("%d/%d 通过：两半要点齐全，没夹个人信息%s。" % (total, total, leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
