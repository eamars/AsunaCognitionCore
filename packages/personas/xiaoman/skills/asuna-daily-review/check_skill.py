#!/usr/bin/env python3
"""asuna-daily-review 的零依赖离线自检。

这份技能是「每日自省」的取数＋初判做法，所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节在、脚本能编译、换行是 LF（读字节数 CR）；
2. 内容要点：头判据句、取数各步、四维判据 a／b／c／d、c 的五种候选形态、d 的排除凭据、报告三块、
   「改不改」三答案、四个落口、「夜间回合的边界」三拍与时间顺序都在；
3. 家规：正文无日期、无来历叙述；不带别人的个人信息（禁词表、字面编号、这台机器的私密名单；
   名单配不上或 0 条有效词记红 `leak_scan_ran`，「没跑」不许长得像「过了」）；
4. 没有占位符残留；随书 CHANGELOG.md 首条是「10-30 新建：金主委托每日自省」。

不联网、不碰数据库、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import re
import sys

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就崩。输出字节固定成 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 分工与口径",
    "## 一、取数",
    "## 二、四维初判",
    "## 三、报告结构",
    "## 四、产出落口（一条只落一口）",
    "## 夜间回合的边界",
    "## 做到的标准",
]

HEAD_SENTENCE = "不需要迎合任何人：没被接 ≠ 她的错。先问那个场子收不收这种话，再问她说得有不有趣。"

FETCH = [
    ("fetch_window_local_day", "local_window"),
    ("fetch_window_end_rule", "读的那一刻"),
    ("fetch_groups_from_program", "群清单从程序现场取"),
    ("fetch_groups_fields_projection", "fields=['_id','kind','sequence']"),
    ("fetch_skip_local_test_groups", "local-"),
    ("fetch_zero_outbound_one_line", "0 出站"),
    ("fetch_zero_outbound_no_full_pull", "不拉那个群的全场"),
    ("fetch_paging_by_scene_seq", "scene_seq > 上一页最大值"),
    ("fetch_more_must_continue", "没续完不许下"),
    ("fetch_sentence_merge", "同一个 `episode_id`"),
    ("fetch_time_receipt_then_queued", "`receipt_at`；没有就用 `queued_at`"),
    ("fetch_window_before_10", "T0−10 分钟"),
    ("fetch_window_after_10", "T1+10 分钟"),
    ("fetch_drop_internal_rows", "asuna:internal"),
    ("fetch_scene_merge_20min", "不超过 20 分钟的并成一场"),
    ("fetch_window_not_full", "后窗未满"),
    ("fetch_front_reading", "前窗读法"),
    ("fetch_cold_room", "场是冷的"),
    ("fetch_back_reading", "后窗读法"),
    ("fetch_late_reply", "迟到接话"),
    ("fetch_no_reply", "无回复"),
    ("fetch_line_number_is_scene_seq", "行号＝`messages.scene_seq`"),
]

DIMENSIONS = [
    ("dim_a_timing", "**a 时机对不对**"),
    ("dim_b_fit", "**b 合不合适**"),
    ("dim_b_room_question", "这个场子收不收这种话"),
    ("dim_c_bullied", "**c 有没有被欺负**"),
    ("dim_c_no_conclusion", "不写「被欺负」「没被欺负」这样的结论句"),
    ("dim_c_line_numbers", "每条都带原文行号"),
    ("dim_c_quote_tease", "**引用调侃**"),
    ("dim_c_command_bait", "**拿命令词钓**"),
    ("dim_c_empty_loop", "**空单循环**"),
    ("dim_c_empty_loop_scope", "做不到或不烧钱的活"),
    ("dim_c_siege", "**围攻**"),
    ("dim_c_meme_long_answer", "**玩梗场子逼长答**"),
    ("dim_c_final_to_xiaoman", "终判归小满"),
    ("dim_d_nobody_replied", "**d 为什么没人回**"),
    ("dim_d_exclude_natural_end", "先排除「自然话题结束」"),
    ("dim_d_literal_proof_a", "她这句是那个话题的最后一条，而且她之后场上已经换题"),
    ("dim_d_literal_proof_b", "之后全场无人续"),
    ("dim_d_no_proof_no_claim", "没有凭据就不许写「话题结束」"),
    ("dim_d_cause_unknown", "原因未定"),
]

REPORT = [
    ("report_header", "**1. 表头**"),
    ("report_sentence_table", "**2. 逐句表**"),
    ("report_table_columns", "场景代号｜行号｜时刻｜她的话"),
    ("report_summary_and_verdict", "**3. 全天小结＋判定**"),
    ("report_must_answer", "有没有要改的，或者需不需要改"),
    ("report_three_answers", "**要改／不用改／数据不够**"),
    ("report_no_verdict_fails", "**只有「没判」不合格**"),
    ("report_change_items", "改什么、落哪一口、一句理由、证据行号"),
    ("report_no_judging_person", "不替那个人写感受和动机"),
]

OUTLETS = [
    ("outlet_group_notes", "**群笔记**"),
    ("outlet_person_understanding", "**对人的理解**"),
    ("outlet_pocket_ledger", "**随身账**"),
    ("outlet_pocket_ledger_rule", "只在她今天的做法撞了已有规矩时才动"),
    ("outlet_ideas_book", "**想法本**"),
    ("outlet_ideas_review_by_self_improvement", "过堂归自我改进那一拍"),
]

BOUNDARY = [
    ("boundary_self_review_scope", "**每日自省（这一份，23:30）管方法与人**"),
    ("boundary_settlement_scope", "**夜间沉淀管事实与领悟的记忆晋升**"),
    ("boundary_cite_not_repromote", "沉淀只引用、不重复晋升"),
    ("boundary_self_improvement_scope", "**自我改进拍管想法本过堂**"),
    ("boundary_mood_backfill", "自省当场补记"),
    ("boundary_mood_close_void", "close／void"),
    ("boundary_time_order", "自省 23:30 在前，夜间沉淀在后"),
]

PERSONAL_TOKENS = ["主人", "旧居", "交流群", "姐姐", "金主"]

# 无日期、无来历：正文里出现这些形状就红（CHANGELOG 不查）。
DATE_SHAPES = [
    ("iso_date", re.compile(r"\b20\d\d[-/.]\d{1,2}[-/.]\d{1,2}\b")),
    ("month_day", re.compile(r"(?<![\d:])\d{1,2}[-/]\d{1,2}(?![\d:])")),
    ("cn_date", re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]")),
    ("cn_year", re.compile(r"20\d\d\s*年")),
]
PROVENANCE_WORDS = ["来路", "实测于", "那次", "那一回", "当时说", "上回", "上次", "金主委托", "委托"]

LITERAL_ID = re.compile(r"#\d")
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")

CHANGELOG_FIRST = "10-30 新建：金主委托每日自省"


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


def read_frontmatter(text):
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
    bad = []
    for target in paths:
        try:
            with open(target, "rb") as handle:
                count = handle.read().count(b"\r")
        except OSError as exc:                           # noqa: BLE001
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
    check("name_matches_directory", bool(fields and fields.get("name") == EXPECTED_NAME),
          "name=%s dir=%s" % ((fields or {}).get("name"), EXPECTED_NAME))
    desc = (fields or {}).get("description", "")
    check("description_specific_enough", len(desc) >= 120, "len=%d" % len(desc))
    check("description_has_head_criterion", "不需要迎合任何人" in desc)
    kinds = re.findall(r"[a-z]+", (fields or {}).get("scene_kinds", ""))
    check("scene_kinds_home", "home" in kinds, "scene_kinds=%s" % ((fields or {}).get("scene_kinds") or "没写"))

    # 头判据句：标题后第一条非空行就是它
    lines = [ln for ln in body.splitlines() if ln.strip()]
    first_after_title = lines[1] if len(lines) > 1 and lines[0].startswith("# ") else ""
    check("head_sentence_is_first", HEAD_SENTENCE in first_after_title, first_after_title[:60])

    for index, section in enumerate(SECTIONS):
        check("section_%d" % index, ("\n" + section) in ("\n" + body), section)

    for group in (FETCH, DIMENSIONS, REPORT, OUTLETS, BOUNDARY):
        for name, token in group:
            check(name, token in body, token)

    # 边界节三拍都在该节里（不是散在别处）
    start = body.find("\n## 夜间回合的边界")
    nxt = body.find("\n## ", start + 4) if start != -1 else -1
    section_text = body[start:nxt if nxt != -1 else len(body)] if start != -1 else ""
    check("boundary_three_beats_inside_section",
          all(tok in section_text for tok in ("每日自省", "夜间沉淀", "自我改进拍")),
          "边界节里三拍没写全")
    check("boundary_split_table", "| 条目 | 归谁 |" in section_text)

    # 判定三答案：三个词都在判定那一节里
    verdict_at = body.find("**判定一节必答")
    verdict_text = body[verdict_at:verdict_at + 700] if verdict_at != -1 else ""
    check("verdict_three_answers_present", all(w in verdict_text for w in ("要改", "不用改", "数据不够")))

    # 家规：无日期、无来历
    for label, shape in DATE_SHAPES:
        found = shape.findall(body)
        check("no_date_" + label, not found, "出现：" + ",".join(str(f) for f in found[:3]))
    prov = [w for w in PROVENANCE_WORDS if w in body]
    check("no_provenance_words", not prov, ",".join(prov))
    check("no_personal_tokens", not [t for t in PERSONAL_TOKENS if t in body],
          ",".join(t for t in PERSONAL_TOKENS if t in body))
    check("no_literal_ids", not LITERAL_ID.search(body), ",".join(LITERAL_ID.findall(body)[:5]))

    listed_path, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False,
              "私密名单没配上（试过 %s）：真人名／群名这一项没真查——不是跑过了"
              % ("、".join(listed_path) if listed_path else "都没有"))
        leak_note = ""
    elif not entries:
        check("leak_scan_ran", False, "名单 0 条（%s）——没真查，不是跑过了" % listed_path)
        leak_note = ""
    else:
        found = listed_hits(entries, text)
        check("no_listed_words", not found, "、".join(found))
        leak_note = "，泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries)

    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 2500, "body_chars=%d" % len(body))

    # 随书 CHANGELOG：首条是新建那一条
    changelog = os.path.join(HERE, "CHANGELOG.md")
    check("changelog_exists", os.path.isfile(changelog))
    first_entry = ""
    if os.path.isfile(changelog):
        with open(changelog, encoding="utf-8") as handle:
            entries_cl = [ln for ln in handle.read().splitlines() if ln.startswith("- ")]
        first_entry = entries_cl[0] if entries_cl else ""
    check("changelog_first_entry", first_entry.startswith("- " + CHANGELOG_FIRST), first_entry[:40])

    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    for script in scripts:
        try:
            with open(os.path.join(HERE, script), "rb") as handle:
                source = handle.read()
            compile(source, os.path.join(HERE, script), "exec")
            check("compiles_" + script, True)
        except Exception as exc:  # noqa: BLE001
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

    cr_files = cr_bytes([path, changelog] + [os.path.join(HERE, script) for script in scripts])
    check("line_endings_are_lf", not cr_files, "有 CR：" + "、".join(cr_files))

    notes = []
    if any(d == "__pycache__" for d in os.listdir(HERE)):
        notes.append("NOTE 技能目录里有 __pycache__，发布前清掉：find skills -name '__pycache__' -type d -prune -exec rm -rf {} +")

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
    print("%d/%d 通过：头判据、取数、四维、报告、落口、边界要点齐全，正文无日期无来历%s。" % (total, total, leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
