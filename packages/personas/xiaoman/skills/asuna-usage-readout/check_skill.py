#!/usr/bin/env python3
"""asuna-usage-readout 的零依赖离线自检（只查文件本身，不读会话记录、不连库）。

查四件事：文件结构（frontmatter、章节、LF 换行、脚本能编译）；八条口径判据与来源／口径字面都在；
三张表与硬规矩都在；不带个人信息（私密名单命中只报类别与行号，名单配不上记红）。

用法：python3 skills/asuna-usage-readout/check_skill.py [SKILL.md 路径]
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import py_compile
import re
import shutil
import sys
import time

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = os.path.basename(HERE)

SECTIONS = [
    "## 一、硬规矩", "## 二、来源和口径", "### 来源", "### 口径",
    "### 八条口径判据", "## 三、三张表怎么读", "### ① 缓存命中率", "### ② 选高率",
    "### ③ 成败与拒", "## 四、每周怎么跑", "## 版本", "## 试用记录",
]

# 来源与口径：每条查一个只有写全了才会出现的字面
FACTS = [
    ("src_path", ".runtime/adr008/home/sessions/"),
    ("src_file", "session.v4.jsonl.zstd"),
    ("src_zstandard", "zstandard"),
    ("src_development_run", "development_run"),
    ("src_project_core", "project=core"),
    ("src_message_row", "assistant/message"),
    ("src_input", "inputTokens"),
    ("src_cache_read", "cacheReadTokens"),
    ("src_cache_write", "cacheWriteTokens"),
    ("src_output", "outputTokens"),
    ("src_total", "totalTokens"),
    ("src_unit", "单位都是 token 数"),
    ("src_compaction", "compaction/summary"),
    ("src_presets", "asuna-attend"),
    ("src_subagent", "origin: subagent"),
    ("src_tier_fields", "tier.chosen"),
    ("src_tier_ran", "tier.ran"),
    ("src_tasks_state", "tasks.state"),
    ("src_states", "NEEDS_CHARACTER_DECISION"),
    ("src_note_refused", "note.refused"),
    ("src_note_code", "NOTE_MODE_NOT_ALLOWED"),
    ("src_turn_rejected", "turn.rejected"),
    ("src_free_text", "自由文本"),
    ("src_tool_failed", "tool.failed"),
    ("src_episodes", "episodes.rejections[]"),
    ("rule_hit_formula", "cacheRead / (cacheRead + input)"),
    ("rule_missing_is_inference", "缺字段按 0 算是推断"),
    ("rule_sample_counts", "2534"),
    ("rule_landed", "tier.ran != tier.chosen"),
    ("rule_why_not_cause", "不许拿它当降档原因报"),
    ("rule_compaction_separate", "单独列一类，不混进"),
    ("probe_task", "task-f83b69fb5d8b9c905060b7d71fa95ba1"),
]

# 八条判据：各查一句只有原样抄进来才会出现的字面
CRITERIA = [
    ("c1_counters", "**两个不是一回事**，报数必须写用的是哪个"),
    ("c2_returned", "`RETURNED` 只等于交回，不等于做成"),
    ("c2_unsplittable", "分不出「交回但没做成」就照实写分不出"),
    ("c3_test_pieces", "测试件划出去并写明为什么"),
    ("c3_example", "task-530b59fa6e310b995b990a78363bacea"),
    ("c4_refused_by_cause", "schema 必填所致**不归我**，我自己挑错 op 才归我"),
    ("c5_shape", "654 件任务里 651 件根本没有 `tier` 字段"),
    ("c5_not_preference", "不能算成我的偏好"),
    ("c6_hard", "**硬约束：只读数字、字段名、枚举短码和计数，不读正文**"),
    ("c6_not_hint", "这条写成硬规矩，不是提示"),
    ("c7_source_time", "每个数带来源＋读的时刻"),
    ("c8_unverified_cover", "没验过的覆盖率要标出来"),
    ("c8_934", "不是全部 934 个"),
    ("c8_tiers_location", "`action_brain.tiers` 在库里的存储位置没找到"),
]

TABLES = [
    ("table1_kinds", "我自己的对话"),
    ("table1_tiers_split", "低档、高档分开"),
    ("table2_rate", "选高几次"),
    ("table2_landed", "落档几件"),
    ("table3_states", "交回／卡住／取消／暂停"),
    ("table3_cause", "被拒按成因分"),
    ("hard_no_body", "不许 print 整行"),
    ("hard_sandbox", "`sandbox_run` 看不到那个目录"),
]

PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")
LITERAL_ID = re.compile(r"#\d")
LINE_ANCHOR = re.compile(r"`(?:[\w./-]+\.(?:py|mjs|js|json|md|yml)|):\d+(?:-\d+)?`")
PERSONAL_TOKENS = ["姐姐", "交流群", "旧居"]


def private_list():
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as c
            data = str(c.DATA)
        except Exception:                                    # noqa: BLE001
            data = None
    cands = []
    if named:
        cands.append(named)
    if data:
        cands.append(os.path.join(data, "private", "personal-words.txt"))
    here = HERE
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        cands.append(os.path.join(here, ".runtime", "private", "personal-words.txt"))
    for p in cands:
        if p and os.path.isfile(p):
            out = []
            with open(p, encoding="utf-8") as h:
                for n, line in enumerate(h, 1):
                    parts = line.strip().split("|", 2)
                    if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                        out.append((n, parts[0].strip(), parts[1].strip()))
            return p, out
    return (cands[-1] if cands else None), None


def listed_hits(entries, text):
    hits = []
    for n, cat, word in entries:
        if all(ch.isascii() for ch in word):
            ok = re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.I)
        else:
            ok = word in text
        if ok:
            hits.append("%s（名单第 %d 行）" % (cat, n))
    return hits


def frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    fields = {}
    for line in text[3:end].strip("\n").splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields, text[end + 4:]


def probe_dir():
    for base in (HERE, os.getcwd()):
        d = os.path.join(base, "_compile-probe-%d" % int(time.time() * 1000))
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except OSError:
            continue
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SKILL.md")
    results, notes = [], []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    exists = os.path.isfile(path)
    check("skill_file_exists", exists, path)
    raw = b""
    text = ""
    if exists:
        with open(path, "rb") as h:
            raw = h.read()
        text = raw.decode("utf-8")
    fields, body = frontmatter(text)
    check("frontmatter_parses", fields is not None)
    check("name_matches_directory", bool(fields and fields.get("name") == NAME),
          "name=%s dir=%s" % ((fields or {}).get("name"), NAME))
    check("description_specific_enough", len((fields or {}).get("description", "")) >= 120)
    for i, s in enumerate(SECTIONS):
        check("section_%d" % i, ("\n" + s) in ("\n" + body), s)
    for name, tok in FACTS + CRITERIA + TABLES:
        check(name, tok in body, tok)
    check("no_line_anchors", not LINE_ANCHOR.search(body), "正文里有行号锚点")
    check("criteria_numbered_1_to_8",
          all(re.search(r"^%d\. \*\*" % n, body, re.M) for n in range(1, 9)), "八条判据编号 1-8")

    p, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False, "私密名单没配上（试过 %s）：没真查——不是跑过了" % (p or "都没有"))
        leak = ""
    else:
        found = listed_hits(entries, text)
        check("no_listed_words", not found, "、".join(found))
        leak = "，泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries)
    personal = [t for t in PERSONAL_TOKENS if t in body]
    check("no_personal_info", not personal, ",".join(personal))
    check("no_literal_ids", not LITERAL_ID.search(body))
    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 1500, "body_chars=%d" % len(body))
    check("selfcheck_documented", "check_skill.py" in body)

    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    cr = []
    for t in [path] + [os.path.join(HERE, s) for s in scripts]:
        try:
            with open(t, "rb") as h:
                n = h.read().count(b"\r")
            if n:
                cr.append("%s（%d 个 CR 字节）" % (os.path.basename(t), n))
        except OSError as e:                                  # noqa: BLE001
            cr.append("%s（读不了：%s）" % (os.path.basename(t), e))
    check("line_endings_are_lf", not cr, "、".join(cr))
    tmp = probe_dir()
    check("compile_probe_writable", tmp is not None, "临时目录不可写")
    try:
        for s in (scripts if tmp else []):
            try:
                py_compile.compile(os.path.join(HERE, s), cfile=os.path.join(tmp, s + "c"), doraise=True)
                check("compiles_" + s, True)
            except Exception as e:                            # noqa: BLE001
                check("compiles_" + s, False, "%s: %s" % (type(e).__name__, e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    if "__pycache__" in os.listdir(HERE):
        notes.append("NOTE 技能目录里有 __pycache__，发布前清掉")

    total = len(results)
    failed = [n for n, ok, _ in results if not ok]
    for n, ok, d in results:
        if not ok and d:
            print("FAIL %s  <- %s" % (n, d))
    for line in notes:
        print(line)
    if failed:
        print("%d/%d 通过，失败：%s" % (total - len(failed), total, ", ".join(failed)))
        return 1
    print("%d/%d 通过：来源口径、八条判据、三张表、硬规矩都在%s。（只查文件本身，没读过会话记录和库。）" % (total, total, leak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
