#!/usr/bin/env python3
"""asuna-usage-readout 的零依赖离线自检（只查文件本身，不读会话记录、不连库）。

查六件事：文件结构（frontmatter、章节、LF 换行、脚本能编译）；来源／口径字面与六格口径（v3：① 落档件数
只从字段数、② 跨类拷贝去重四条、③ 反思回合已核）都在；三张表（含标明「不是正式读数」的样例表）与硬规矩
都在；v1／v2 已被核掉的旧字面不残留（含 2026-10-23 v2、未逐条核、0 样本、写死的 484／7 件）；版本与试用
记录按写就时刻标、另起一行标计划首次真跑；不带个人信息（私密名单命中只报类别与行号，名单配不上、或名单在
却解析出 0 条有效词，都记红）。

行号锚点：一律红（2026-10-15 定的规矩，仓库共用测试 tests/test_skill_anchors.py 查的是同一条）。v3 曾为
六格① 的代码位置开过四处白名单，2026-10-17 撤掉：代码位置写 `文件:函数名`，行号会随每次编辑漂走、不算锚点。

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
    ("src_message_id", "data.message.id"),
    ("src_seeded", "isSeeded"),
    ("src_parent_session", "parentSession"),
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
    ("rule_dedup_first", "先去重"),
    ("rule_landed", "tier.ran != tier.chosen"),
    ("rule_why_not_cause", "不许拿它当降档原因报"),
    ("rule_compaction_separate", "单独列一类，不混进"),
    ("rule_numbers_drift", "数会随在跑的任务变"),
    ("probe_task", "task-f83b69fb5d8b9c905060b7d71fa95ba1"),
]

# 六格口径（v3）：每格查几句只有照那趟验证写出来才会出现的字面
CELLS = [
    # ① 落档件数只从字段数——审计看不见「开工即落档」
    ("cell1_field", "tasks.tier.fell = {reason, mid_run, at, code?}"),
    ("cell1_reason_refused", "`refused`（高档没接这件）"),
    ("cell1_reason_down", "`down`（连不上、超时、服务器错）"),
    ("cell1_reason_busy", "`busy`（被限流）"),
    ("cell1_reason_owner", "`owner`（钥匙、凭据或额度问题，要等主人）"),
    ("cell1_count_field", "落档件数只从 `tasks.tier.fell` 字段数"),
    ("cell1_pure_function", "纯函数"),
    ("cell1_no_audit", "内部没有任何 audit 调用"),
    ("cell1_state_commit", "通用 `state.commit`"),
    ("cell1_stream_round", "`stream_id` 是回合 id，不是任务 id"),
    ("cell1_dispatch_anchor", "src/asuna/action_tiers.py:at_dispatch"),
    ("cell1_plugin_anchor", "src/asuna/native_worker.py:BusinessWorker.dispatch"),
    ("cell1_gate", "同一函数里 `task.tier.ran=='高'` 那道判断挡着"),
    ("cell1_gate_dispatch", "哪怕 `dispatch` 里 `tier.ran=='高'` 那道判断没通过"),
    ("cell1_invisible", "「开工即落档」的那件在审计面永远看不见"),
    ("cell1_recorded", "`{'recorded': bool(task)}`"),
    ("cell1_recorded_ne", "`recorded` ≠ 真写了"),
    ("cell1_two_sources", "两个来源不能相加、也不能互查"),
    ("cell1_audit_rest", "`action-tiers`"),
    ("cell1_over", "`{over: true}`"),
    ("cell1_only_high", '只在 `tier.ran=="高"`'),
    ("cell1_two_things", "「没落过档」和「没这个字段」是两回事"),
    ("cell1_doc", "RUNTIME_API.md"),
    ("cell1_at_dispatch", "at_dispatch"),
    ("cell1_audit_answered", "本次读代码已答"),
    # ② 会话种类按目录名前缀 ＋ 跨类拷贝去重四条
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
    ("cell2_7of7", "7/7 对上"),
    ("cell2_native_unusable", "native_session_id"),
    ("cell2_sha_fail", "sha(task_id)[:32]"),
    ("cell2_scheduler_wrong", "把它算成差事是错的"),
    ("cell2_errand_fields", "`lane=character`"),
    ("cell2_read_now_col", "跑数那天重新数，别抄"),
    ("cell2_dirs_rows", "498 个目录／496 行"),
    ("cell2_missing_rows", "库里为何缺行未查明"),
    ("cell2_dedup_global", "全局按 `data.message.id` 去重：一条 id 只算一次，归它首次出现时所属的那一类"),
    ("cell2_tie_time", "「首次」＝行内 `time` 最早"),
    ("cell2_tie_created", "同刻按会话首行 `createdAt`"),
    ("cell2_copy_rule", "`time` 早于该会话首行 `createdAt` 的调用行＝分叉／播种带进来的历史"),
    ("cell2_two_cells", "自有调用数／拷贝来的调用数"),
    ("cell2_no_merge", "不许合成一个数"),
    ("cell2_mark_n", "拷贝占比高的那一类要标样本量"),
    ("cell2_errand_own_7", "差事自有只有 7 条"),
    ("cell2_no_id_fallback", "退回启发式键"),
    ("cell2_compaction_no_id", "`compaction/summary` 行没有这个字段"),
    # ③ 反思回合：第一份样本已核
    ("cell3_code", "REFLECT_PREFIX"),
    ("cell3_id", "sha(episode_id)[:32]"),
    ("cell3_sample", "asuna-reflect-8609"),
    ("cell3_verified", "第一份样本已核"),
    ("cell3_preset", "`agentPreset=asuna-xiaoman`"),
    ("cell3_no_origin", "**无** `origin`"),
    ("cell3_no_parent", "**无** `parentSession`"),
    ("cell3_unseeded", "`isSeeded=False`"),
    ("cell3_depth", "`delegationDepth` 存在且为 0"),
    ("cell3_calls", "本体 3 条调用（10-16T11:17Z）"),
    ("cell3_db_row", "库里 `sessions` 1 行"),
    ("cell3_db_fields", "`lane=character`、`scene_id=local-dm`、`task_id=null`、`retired=true`"),
    ("cell3_no_copied_history", "不背拷贝来的历史"),
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
    ("cell5_split_now", "本次已按 `tier.ran` 拆开"),
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
    ("cell6_rows_grow", "3528 行，同一趟再数 3780 行"),
]

# 会让读数出错的坑（v3：坑 1 换成核过的结论，坑 2 查到成因）
PITS = [
    ("pit_keys_equal", "行对行完全一致"),
    ("pit_both_5990", "both=5990"),
    ("pit_both_6026", "both=6026"),
    ("pit_share_history", "19% 是全部历史（5990/31632）"),
    ("pit_share_window", "窗口内是 1.76%（62/3528）"),
    ("pit_window_role", "窗口内重复全在 `asuna-role-` 那一类"),
    ("pit_samefile_zero", "同一文件内按 id 判重是 0 条"),
    ("pit_errand_shared", "98 条 `message.id` 与 `asuna-role` 相同，只有 7 条是它自己的"),
    ("pit_errand_read", "Claude 10-17 12:58 数，只数 id 不读正文"),
    ("pit_webui_seed_combo", "74/309 条压缩 usage 组合出现在多个会话"),
    ("pit_webui_seed_read", "我 10-17 11:08 数"),
    ("pit_compaction_no_id", "压缩行没有 `data.message.id`"),
    ("pit_compaction_74", "74 个 usage 组合同时出现在 `asuna-role-` 与 `session-` 两个前缀下"),
    ("pit_compaction_reread", "74/311"),
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
    ("c5_quoted_not_current", "照抄留档、**不当现值用**"),
    ("c6_hard", "**硬约束：只读数字、字段名、枚举短码和计数，不读正文**"),
    ("c6_not_hint", "这条写成硬规矩，不是提示"),
    ("c7_source_time", "每个数带来源＋读的时刻"),
    ("c8_unverified_cover", "没验过的覆盖率要标出来"),
    ("c8_934", "不是全部 934 个"),
    ("c8_tiers_location", "`action_brain.tiers` 在库里的存储位置没找到"),
]

TABLES = [
    ("table1_kinds", "我的对话／行动脑（低档、高档分开）／差事／反思回合（已有 1 份样本，见六格③）／压缩／摘要／门／调度／网页界面会话"),
    ("table1_tiers_split", "低档、高档分开"),
    ("table1_own_copy_cells", "自有调用数／拷贝来的调用数（两格分开，不许合成一个数）"),
    ("table1_mark_sample_size", "拷贝占比高的那一类必须标样本量"),
    ("table1_sample_is_sample", "这不是正式读数，是样例"),
    ("table1_sample_high", "93.52%"),
    ("table1_sample_low", "94.63%"),
    ("table1_sample_cw_all", "102（全部）"),
    ("table1_sample_cw_none", "0（一行都没有）"),
    ("table1_sample_one_day", "全部落在 10-16 那一天"),
    ("table1_sample_scope", "不能推广到别的种类"),
    ("table1_drift_rows", "213→227→228"),
    ("table1_drift_rate", "94.23→94.59→94.63"),
    ("table2_rate", "选高几次"),
    ("table2_landed", "落档几件"),
    ("table2_landed_from_field", "件数只从 `tasks.tier.fell` 字段数"),
    ("table3_states", "交回／卡住／取消／暂停"),
    ("table3_cause", "被拒按成因分"),
    ("hard_no_body", "不许 print 整行"),
    ("hard_sandbox", "`sandbox_run` 看不到那个目录"),
    ("hard_only_numbers", "**只读数字、字段名、枚举短码和计数，不读正文。**"),
    ("hard_no_stale_numbers", "当天会旧的数不写进这份技能"),
]

# 版本与试用记录：日期一律写就时刻，计划真跑另起一行
VERSION = [
    ("ver_planned_run", "计划首次真跑：2026-10-23 20:30（本地）"),
    ("ver_written_word", "写就时刻"),
    ("ver_v3_written", "v3（写就 2026-10-17"),
    ("ver_v2_written", "v2（写就 2026-10-17 09:21）"),
    ("ver_v1_written", "v1（写就 2026-10-16 21:21）"),
    ("trial_v1", "2026-10-16 21:21 写就 v1"),
    ("trial_v2", "2026-10-17 09:21 写就 v2"),
    ("trial_v3", "2026-10-17 13:07 写就 v3"),
]

# 被核掉／改掉的旧字面：留在正文里就说明那一格没真改
STALE = [
    # v1 被 10-16 21:24 那轮核对核掉的
    ("no_fell_field", "库里没有单独的降档原因字段"),
    ("old_hit_formula", "cacheRead / (cacheRead + input)"),
    ("four_places", "散在四处"),
    ("preset_kind_split", "用文件第一行的 `agentPreset` 分"),
    ("v1_sample_2534", "2534"),
    ("v1_write_cache_23", "只在 23 条出现"),
    ("rolling_week", "时间窗＝从读的时刻往前七天"),
    # v2 被 10-17 这两趟核掉／改掉的（日期、判重键、反思样本、写死的数）
    ("v2_run_date", "2026-10-23 v2"),
    ("dup_unverified", "未逐条核"),
    ("reflect_no_sample", "0 样本"),
    ("hardcoded_task_dirs", "484"),
    ("hardcoded_tier_tasks", "7 件"),
    ("old_dup_share", "约 19%"),
    ("old_compaction_suspect", "疑似同一行被两边各数一次"),
]

PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")
LITERAL_ID = re.compile(r"#\d")
LINE_ANCHOR = re.compile(r"`(?:[\w./-]+\.(?:py|mjs|js|json|md|yml)|):\d+(?:-\d+)?`")
# 代码位置写 `文件:函数名`（2026-10-15 的规矩，仓库共用测试 tests/test_skill_anchors.py 同一条）：
# 行号一律红，没有白名单。下面这三处只是「六格① 确实写了代码位置」的正向检查，不是例外。
CODE_ANCHORS = (
    "src/asuna/action_tiers.py:at_dispatch",
    "src/asuna/state.py:Store.put",
    "src/asuna/native_worker.py:BusinessWorker.dispatch",
)
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
    for name, tok in FACTS + CELLS + PITS + CRITERIA + TABLES + VERSION:
        check(name, tok in body, tok)
    for name, tok in STALE:
        check("stale_gone_" + name, tok not in body, "旧字面还在正文里：%s" % tok)
    stray = [m.group(0) for m in LINE_ANCHOR.finditer(body)]
    check("no_line_anchors", not stray, "正文里有行号锚点（代码位置写 `文件:函数名`）：%s" % "、".join(stray[:5]))
    check("code_anchors_present",
          all(a in body for a in CODE_ANCHORS), "六格① 的代码位置缺了：这三处名字锚点不在正文")
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
    print("%d/%d 通过：来源口径、六格口径（含跨类拷贝去重四条）、三处坑、八条判据、三张表（含样例表标记）、"
          "版本写就时刻与计划真跑日都在，v1／v2 退役字面没残留%s。（只查文件本身，没读过会话记录和库。）"
          % (total, total, leak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
