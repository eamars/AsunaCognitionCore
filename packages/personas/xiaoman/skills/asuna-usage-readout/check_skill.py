#!/usr/bin/env python3
"""asuna-usage-readout 的零依赖离线自检（只查文件本身，不读会话记录、不连库）。

查五件事：文件结构（frontmatter、章节、LF 换行、脚本能编译）；来源／口径字面与六格口径（v2）都在；
八条口径判据、三张表与硬规矩都在；v1 已被核掉的旧字面不残留；不带个人信息（私密名单命中只报类别与行号，
名单配不上、或名单在却解析出 0 条有效词，都记红）。

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
    "### 六格口径", "### 八条口径判据", "## 三、三张表怎么读", "### ① 缓存命中率",
    "### ② 选高率", "### ③ 成败与拒", "## 四、每周怎么跑",
    "## 五、会让读数出错的坑", "## 六、没验过的", "## 版本", "## 试用记录",
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
    ("src_row_time", "整数毫秒"),
    ("src_compaction", "compaction/summary"),
    ("src_tier_fields", "tier.chosen"),
    ("src_tier_ran", "tier.ran"),
    ("src_tasks_state", "tasks.state"),
    ("src_states", "NEEDS_CHARACTER_DECISION"),
    ("src_dbread", "asuna.dbread"),
    ("src_local_window", "local_window"),
    ("rule_hit_formula", "cacheRead / (input + cacheRead + cacheWrite)"),
    ("rule_missing_is_inference", "缺字段按 0 算是推断"),
    ("rule_dedup_first", "先去重再算"),
    ("rule_landed", "tier.ran != tier.chosen"),
    ("rule_why_not_cause", "不许拿它当降档原因报"),
    ("rule_compaction_separate", "单独列一类，不混进"),
    ("probe_task", "task-f83b69fb5d8b9c905060b7d71fa95ba1"),
]

# 六格口径（v2）：每格查几句只有照抄那趟验证才会出现的字面
CELLS = [
    # ① 落档原因有字段
    ("cell1_field", "tasks.tier.fell = {reason, mid_run, at, code?}"),
    ("cell1_reason_refused", "`refused`（高档没接这件）"),
    ("cell1_reason_down", "`down`（连不上、超时、服务器错）"),
    ("cell1_reason_busy", "`busy`（被限流）"),
    ("cell1_reason_owner", "`owner`（钥匙、凭据或额度问题，要等主人）"),
    ("cell1_audit_fell", "`stream_id`＝任务 id"),
    ("cell1_audit_rest", "`action-tiers`"),
    ("cell1_over", "`{over: true}`"),
    ("cell1_only_high", '只在 `tier.ran=="高"` 时才写'),
    ("cell1_zero_now", "7 件带 `tier` 的任务里 `tier.fell` 0 件"),
    ("cell1_two_things", "「没落过档」和「没这个字段」是两回事"),
    ("cell1_doc", "RUNTIME_API.md"),
    ("cell1_unverified_rests", "at_dispatch"),
    # ② 会话种类按目录名前缀
    ("cell2_role", "`asuna-role-`"),
    ("cell2_errand", "`asuna-errand-`"),
    ("cell2_action", "`asuna-action-`"),
    ("cell2_summary", "`asuna-summary-`"),
    ("cell2_attend", "`asuna-attend-`"),
    ("cell2_scheduler", "`asuna-scheduler-`"),
    ("cell2_webui", "`session-<uuid>`"),
    ("cell2_reflect", "`asuna-reflect-`"),
    ("cell2_preset_same", "`agentPreset` 都是 `asuna-xiaoman`"),
    ("cell2_preset_mixes", "只按 preset 分会混"),
    ("cell2_subagent_not_errand", "不能当「差事」判据"),
    ("cell2_join", "`sessions.task_id → sessions._id`＝行动脑目录名"),
    ("cell2_7of7", "7 件 7/7 对上"),
    ("cell2_native_unusable", "native_session_id"),
    ("cell2_sha_fail", "sha(task_id)[:32]"),
    ("cell2_scheduler_wrong", "把它算成差事是错的"),
    ("cell2_errand_fields", "`lane=character`"),
    ("cell2_no_origin", "另有 8 个不带 `origin`"),
    # ③ 反思回合
    ("cell3_code", "REFLECT_PREFIX"),
    ("cell3_id", "sha(episode_id)[:32]"),
    ("cell3_zero_sample", "941 个会话里 0 个样本"),
    ("cell3_pending", "待第一份样本核"),
    # ④ 被拒八处
    ("cell4_main", "audit_events.type=='role_tool'"),
    ("cell4_main_refused", "payload.refused"),
    ("cell4_main_count", "11150 条里 846 条"),
    ("cell4_tools", "按 `tool` 分 37 种"),
    ("cell4_code_only", "52 条带 `code`"),
    ("cell4_turn", "`turn.rejected`"),
    ("cell4_turn_count", "124 条"),
    ("cell4_turn_indep", "不与 role_tool 重复"),
    ("cell4_note_subset", "是 role_tool 的子集，不能相加"),
    ("cell4_note_3s", "3 秒内找到对应被拒行"),
    ("cell4_phase", "`phase.rejected`"),
    ("cell4_execution", "`execution.rejected`"),
    ("cell4_execution_meaning", "行动脑交回的报告被退"),
    ("cell4_summary", "`summary.rejected`"),
    ("cell4_tool_failed", "`tool.failed`"),
    ("cell4_episodes", "`episodes.rejections[]`"),
    ("cell4_v1_missed", "v1 漏了最大一处"),
    ("cell4_unverified_same", "是否同一批"),
    # ⑤ 命中率分母含写缓存
    ("cell5_evidence_rows", "30955 条"),
    ("cell5_evidence_158", "158 条"),
    ("cell5_equation", "total = input + output + cacheRead + cacheWrite"),
    ("cell5_degenerate", "退化成 v1 的式子"),
    ("cell5_no_overlap", "三者互不重叠"),
    ("cell5_delta_role", "89.25%→89.17%"),
    ("cell5_delta_action", "94.71%→94.66%"),
    ("cell5_premise_unverified", "没验成立"),
    ("cell5_121_rows", "121 条行动脑写缓存行"),
    # ⑥ 窗口写死
    ("cell6_start", "2026-10-16 00:00"),
    ("cell6_tz", "Pacific/Auckland"),
    ("cell6_utc", "2026-10-15T11:00:00Z"),
    ("cell6_not_rolling", "不是滚动的「往前七天」"),
    ("cell6_relay", "是转达，不是主人字面"),
    ("cell6_tasks_field", "`created_at`"),
    ("cell6_audit_field", "`occurred_at`"),
    ("cell6_line_split", "按每一行的 `time`"),
    ("cell6_915", "915 个首行 `createdAt` ≠ 首条消息 `time`"),
    ("cell6_20_files", "还在写的有 20 个"),
    ("cell6_retention", "超 30 天清"),
    ("cell6_tier_start", "2026-10-16T07:56:38Z"),
    ("cell6_dbtool_display", "development_database_read"),
]

# 会让读数出错的坑（v2 新增三处）
PITS = [
    ("pit_dup_count", "5990 条重复"),
    ("pit_dup_share", "约 19%"),
    ("pit_dup_heuristic", "启发式"),
    ("pit_compaction_double", "118758"),
    ("pit_tools_week", "review.tools_week"),
    ("pit_tools_week_window", "[这条记录 occurred_at − 7 天, occurred_at)"),
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
    ("table1_kinds", "我的对话／行动脑（低档、高档分开）／差事／反思回合（0 样本，标待样本）／压缩／摘要／门／调度／网页界面会话"),
    ("table1_tiers_split", "低档、高档分开"),
    ("table2_rate", "选高几次"),
    ("table2_landed", "落档几件"),
    ("table3_states", "交回／卡住／取消／暂停"),
    ("table3_cause", "被拒按成因分"),
    ("hard_no_body", "不许 print 整行"),
    ("hard_sandbox", "`sandbox_run` 看不到那个目录"),
    ("hard_only_numbers", "**只读数字、字段名、枚举短码和计数，不读正文。**"),
]

# v1 被 10-16 21:24 那轮核对核掉／改掉的旧字面：留在正文里就说明六格没真改
STALE = [
    ("no_fell_field", "库里没有单独的降档原因字段"),
    ("old_hit_formula", "cacheRead / (cacheRead + input)"),
    ("four_places", "散在四处"),
    ("preset_kind_split", "用文件第一行的 `agentPreset` 分"),
    ("v1_sample_2534", "2534"),
    ("v1_write_cache_23", "只在 23 条出现"),
    ("rolling_week", "时间窗＝从读的时刻往前七天"),
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
    return [c for c in cands if c] or None, None


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
    for name, tok in FACTS + CELLS + PITS + CRITERIA + TABLES:
        check(name, tok in body, tok)
    for name, tok in STALE:
        check("stale_gone_" + name, tok not in body, "v1 旧字面还在正文里：%s" % tok)
    check("no_line_anchors", not LINE_ANCHOR.search(body), "正文里有行号锚点")
    check("criteria_numbered_1_to_8",
          all(re.search(r"^%d\. \*\*" % n, body, re.M) for n in range(1, 9)), "八条判据编号 1-8")
    check("six_cells_marked",
          all(("\n**%s " % m) in body for m in "①②③④⑤⑥"), "六格各有一行 **① … 起头")

    p, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False, "私密名单没配上（试过 %s）：没真查——不是跑过了"
              % ("、".join(p) if p else "都没有"))
        leak = ""
    elif not entries:
        # 2026-10-16 补的第二种失效：名单文件在、一条有效词都没解析出来（全注释或被字段数筛光）。
        # 以前走 else 分支：0 命中算绿，输出还写「扫过（名单 0 条）」——那是没真查，不是跑过了。
        check("leak_scan_ran", False, "名单 0 条（%s）——没真查，不是跑过了" % p)
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
    print("%d/%d 通过：来源口径、六格口径、三处坑、八条判据、三张表、硬规矩都在，v1 退役字面没残留%s。（只查文件本身，没读过会话记录和库。）" % (total, total, leak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
