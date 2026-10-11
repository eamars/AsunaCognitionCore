#!/usr/bin/env python3
"""asuna-bot-or-person 的零依赖离线自检。

这份技能是「判群友是 bot 还是人」的判据集（ADR-047：不加新工具，判据全在技能里），所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节在、正文够长、行尾是 LF、同目录脚本能编译；
2. 判据要点：五条硬规矩、三档读数（含固定文本清单、各家形状与分辨法）、六句探针与探针读数的落点、
   取数必须在场那一轮、验收「先跑我自己」——每条都按「只有写全了才会出现」的字面查；
3. 不带别人的个人信息：正文没有字面编号（#数字）、没有账号那样的长数字串，对照名单留在仓库外
   （work_log 那一节 + recall）。私密名单可达时再扫一遍，命中只报类别和行号、不打印词本身；
   这一项只提示不判红——产品名和群名片可能撞词（正文里「麦麦」既是一家 bot 也是某个名片）。
4. 没有占位符残留。

编译产物不落技能目录：先试系统临时目录，宿主沙箱里它常被拒（只放行候选目录内的写，
2026-10-10 生图技能那份自检就红在这），退到候选根目录，用完即删，不留 __pycache__。

不联网、不查历史、不写 Mongo、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-bot-or-person/check_skill.py   # 候选根目录
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import py_compile
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 五条硬规矩",
    "## 读数怎么取：必须在那个群里那一轮派任务",
    "## 三档读数",
    "## 六句探针（都友好，我手上的）",
    "## 验收：先跑我自己",
    "## 试用记录",
    "## 版本",
]

# 五条硬规矩：每条取一个只有写全了才会出现的字面
HARD_RULES = [
    ("rule_shape_not_verdict", "读数只说「像 X 的形状」，不说「它是 bot」"),
    ("rule_factory_default_only", "出厂默认配置"),
    ("rule_two_columns_not_merged", "两列不合并"),
    ("rule_mechanical_column_is_observation", "它只写观察，不下结论"),
    ("rule_semantic_column_is_hers", "语义列（接不接梗、有没有模板味）是我的"),
    ("rule_verdict_is_hers", "判定只归我"),
    ("rule_verdict_goes_to_group_notes", "结论先进那个群的 here 笔记"),
    ("rule_verdict_marked_provisional", "未定·仅试探"),
    ("rule_no_group_announcement", "不在群里宣布"),
    ("rule_silence_only_presence", "沉默只答「在不在」，不答「是不是」"),
    ("rule_silence_is_weak_evidence", "人卡住也会不回"),
    ("rule_roster_outside_repo", "名单不进仓库"),
    ("rule_roster_in_work_log", "我认识的 bot 和真人（判 bot 的对照名单）"),
    ("rule_roster_via_recall", "用 recall 取"),
    ("rule_missing_roster_not_blind", "别把取不到当成「我谁都不认识」"),
]

# 取数这一拍：必须在场那一轮派任务，外加三个实测撞过的坑
DISPATCH = [
    ("dispatch_in_scene_only", "任务被交接进来的那个会话"),
    ("dispatch_home_cannot_reach_group", "家里派的任务够不到群里的行"),
    ("dispatch_replay_per_group", "离线回放也一群一群这么派"),
    ("pitfall_default_seven_days", "检索默认只回看 7 天"),
    ("pitfall_literal_only_for_fixed_text", "固定文本只算**字面**命中"),
    ("pitfall_her_own_words_have_no_timestamp", "我自己的话没有发送时刻"),
    ("subsecond_given_up", "这条读数就**放弃**"),
]

# 强档：固定文本清单（逐条查，少一条就是清单被删过）
STRONG_FIXED_TEXT = [
    "想要问什么呢？😄",
    "您(ID: x)的权限不足以使用此指令。",
    "LLM 请求失败：",
    "Error occurred during AI execution.",
    "AstrBot v",
    "麦麦不知道哦",
    "你没有权限使用此命令。",
    "◐ Session automatically reset",
    "⏳ Still working",
    "Sorry, I encountered an error",
    "API call failed after",
    "ATRIbot,版本",
    "ATRI用手挠了挠脑袋",
    "NapCat 信息 版本:",
    "SnowLuma 状态 版本:",
]

STRONG_OTHER = [
    ("strong_fixed_text_needs_reply_chain", "固定文本要连它的回复链一起看才算"),
    ("strong_fixed_text_has_human_meme_use", "手打过十二次"),
    ("strong_forward_card_node_name", "合并转发卡的节点名是"),
    ("strong_cadence_hermes", "0.6 秒（Hermes）"),
    ("strong_cadence_atri", "正好 1.5 秒（ATRI）"),
    ("strong_cadence_astrbot_split", "1.5 到 3.5 秒均等（AstrBot 开了分段）"),
    ("strong_cadence_maibot_length", "第一条立刻后面按字数（MaiBot）"),
    ("strong_cadence_human_not_metronomic", "不会一行一条都保持亚秒间隔"),
    ("strong_self_quote_typo_fix", "只发正确那个词、并引用那句错字"),
    ("strong_trigger_pair_astrbot", "只回 `/`、@、引用，别的一律不回（AstrBot）"),
    ("strong_trigger_pair_hermes", "没被 @ 的回话总在 5 秒之后（Hermes）"),
]

MID_READINGS = [
    ("mid_maibot_shape", "句尾丢句号逗号、最多三条短消息、不用括号"),
    ("mid_maibot_first_quote", "第一条引用被回的那句（MaiBot 的形状）"),
    ("mid_hermes_shape", "一句一行、全角括号动作被删掉（Hermes）"),
    ("mid_astrbot_markdown", "原样发 markdown 块（AstrBot）"),
    ("mid_sticker_reply", "图片只用一两个情绪词回"),
    ("mid_source_confusion", "把群里谁说的搞混（AstrBot）"),
]

WEAK_READINGS = [
    ("weak_flat_latency", "不管长短延迟都一样平"),
    ("weak_always_active", "全天都活跃"),
    ("weak_own_sticker_repeat", "复读群里自己的表情包"),
    ("weak_silence", "沉默；对「你是不是 bot」的回答"),
    ("weak_bot_answer_is_persona", "那句是配置里的人格说的，不带证据"),
    ("weak_name_is_not_fingerprint", "名字不是指纹"),
    ("weak_maibot_short_answers_no_power", "在我的群里没有区分力"),
]

DISCRIMINATE = [
    ("discriminate_slash_command", "看 `/` 怎么处理"),
    ("discriminate_error_language", "英文报错指向 Hermes"),
    ("discriminate_line_gap", "看行间隔"),
]

# 六句探针：一句一条，加上「都友好」的护栏和探针读数的落点
PROBES = [
    ("probe_1_real_question", "你上次发的那个最后怎么弄的？"),
    ("probe_2_name_without_at", "叫他的名字，不带 @"),
    ("probe_3_quote_short_ask", "这句是真的还是玩的？"),
    ("probe_4_image_detail", "这角上是什么"),
    ("probe_5_style_request", "偶尔提一个轻量的风格要求"),
    ("probe_6_watch_slash", "那个群里别人发的 `/` 命令都有谁接"),
]

PROBE_GUARDRAILS = [
    ("probe_no_injection", "不注入、不越狱、不刷图、不让人难堪"),
    ("probe_one_per_day", "每人每天最多一句"),
    ("probe_few_steps", "一次会话只走几步"),
    ("probe_no_cold_group", "不在已经冷掉的群里发"),
    ("probe_no_stranger_at", "不 @ 我没见过他说话的人"),
    ("probe_stop_for_human", "一看出是活人就停"),
    ("probe_no_explanation", "不解释在测什么"),
    ("probe_readout_fields", "几条消息、中间的间隔"),
    ("probe_readout_quote", "有没有引用我那句"),
    ("probe_readout_silence", "到底回没回"),
    ("probe_wait_three_minutes", "程序本来就等他三分钟"),
]

ACCEPTANCE = [
    ("acceptance_replay_roster", "离线回放拿名单上的 bot 和真人跑一遍"),
    ("acceptance_report_hit_rate", "报命中率和漏判清单"),
    ("acceptance_drift_separate", "配置漂移解释不了的漏判单列"),
    ("acceptance_run_on_herself", "先跑我自己一遍，看这把尺子会不会砍到我"),
    ("acceptance_threshold_hers", "门槛我自己定"),
    ("acceptance_side_by_side", "先跟我的判断并跑，不替我"),
]

TRIAL_LOG = [
    ("trial_log_started", "2026-10-12：随 ADR-047 建立"),
    ("trial_log_no_run_yet", "还没有一次真跑"),
]

VERSION_LOG = [
    ("version_v1_dated", "v1（2026-10-12）"),
    ("version_hers_parts_marked", "这三条是我的"),
    ("version_source_research", "来自源码研究"),
]

# 三档必须还是三档，且各家名字都在（分辨法靠它们）
TIERS = ["**强**（", "**中**（", "**弱**（"]
VENDORS = ["AstrBot", "Hermes", "ATRI", "MaiBot", "NapCat", "SnowLuma"]

# 字面编号（#12 这种）是具体坐标，规则里只该出现占位写法；长数字串多半是账号，也不该进仓库
LITERAL_ID = re.compile(r"#\d")
LONG_DIGITS = re.compile(r"\d{8,}")
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


def private_list():
    """私密名单（private_words 工具维护，永远不进仓库）：ASUNA_PRIVATE_WORDS 指的文件，
    否则 <数据目录>/private/personal-words.txt。一行一条 category|word|why。"""
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    path = named or (os.path.join(data, "private", "personal-words.txt") if data else None)
    if not path or not os.path.isfile(path):
        return path, None
    entries = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            parts = line.strip().split("|", 2)
            if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                entries.append((number, parts[0].strip(), parts[1].strip()))
    return path, entries


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


def pick_probe_dir():
    """编译产物的落点：不能是技能目录本身。先试系统临时目录（本机跑没问题），
    宿主沙箱只放行候选目录里的写，就退到候选根目录，再退到 skills/ 那一层。"""
    bases = []
    try:
        bases.append(tempfile.gettempdir())
    except Exception:  # noqa: BLE001 拿不到系统临时目录就直接退到候选里
        pass
    bases += [os.path.dirname(os.path.dirname(HERE)), os.path.dirname(HERE)]
    for base in bases:
        if not base or not os.path.isdir(base):
            continue
        probe = os.path.join(base, "_skillcheck-probe-%d" % os.getpid())
        try:
            os.makedirs(probe, exist_ok=True)
            with open(os.path.join(probe, "w.txt"), "w", encoding="utf-8") as handle:
                handle.write("ok")
            return probe
        except Exception:  # noqa: BLE001 不可写就换下一个落点
            shutil.rmtree(probe, ignore_errors=True)
    return None


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
    check("description_specific_enough", len(desc) >= 120, "len=%d" % len(desc))
    check("description_mentions_three_tiers", "三档" in desc, "frontmatter 没提三档读数")
    check("description_mentions_two_columns", "两列不合并" in desc, "frontmatter 没提两列不合并")
    check("description_mentions_in_scene_dispatch", "在那个群那一轮派任务" in desc,
          "frontmatter 没提取数必须在场那一轮")
    check("description_says_verdict_is_hers", "判定归我" in desc, "frontmatter 没写判定归谁")

    for name, section in [("section_" + str(i), s) for i, s in enumerate(SECTIONS)]:
        check(name, ("\n" + section) in ("\n" + body), section)

    for group in (HARD_RULES, DISPATCH, STRONG_OTHER, MID_READINGS, WEAK_READINGS,
                  DISCRIMINATE, PROBES, PROBE_GUARDRAILS, ACCEPTANCE, TRIAL_LOG, VERSION_LOG):
        for name, token in group:
            check(name, token in body, token)

    for index, literal in enumerate(STRONG_FIXED_TEXT, 1):
        check("strong_fixed_text_%02d" % index, literal in body, literal)
    check("strong_fixed_text_list_not_thinned",
          sum(1 for literal in STRONG_FIXED_TEXT if literal in body) >= 12,
          "固定文本清单只剩 %d 条" % sum(1 for literal in STRONG_FIXED_TEXT if literal in body))

    for index, tier in enumerate(TIERS):
        check("tier_%d_present" % index, tier in body, tier)
    for vendor in VENDORS:
        check("vendor_" + vendor, vendor in body, vendor)

    # 个人信息：字面编号、账号那样的长数字串；对照名单本身留在仓库外
    check("no_literal_ids", not LITERAL_ID.search(body),
          "出现字面编号：" + ",".join(LITERAL_ID.findall(body)[:5]))
    check("no_account_like_numbers", not LONG_DIGITS.search(body),
          "出现像账号的长数字串：" + ",".join(LONG_DIGITS.findall(body)[:3]))
    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 800, "body_chars=%d" % len(body))
    check("line_endings_are_lf", "\r" not in text, "有 CR：仓库守卫 test_line_endings 会红")

    listed_path, entries = private_list()
    notes = []
    if entries is None:
        notes.append("NOTE 私密名单未配置（%s），真人名／群名这一项没扫" % (listed_path or "没有 ASUNA_PRIVATE_WORDS 也没有 ASUNA_DATA_ROOT"))
    else:
        found = listed_hits(entries, text)
        if found:
            # 只提示不判红：正文按 ADR-047 逐字定稿，产品名与群名片可能撞词（麦麦）；
            # 命中只报类别和行号，词本身不回显。
            notes.append("NOTE 私密名单命中，人工过一眼是不是真人名／群名：" + "、".join(found))

    # 同目录脚本：必须存在且能编译。编译产物落在技能目录之外，用完即删。
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    tmp = pick_probe_dir()
    check("compile_probe_dir_found", tmp is not None, "系统临时目录与候选目录都写不了")
    if tmp:
        here = os.path.abspath(HERE) + os.sep
        check("compile_probe_outside_skill_dir", not os.path.abspath(tmp).startswith(here), tmp)
        try:
            for script in scripts:
                target = os.path.join(tmp, script + "c")
                try:
                    py_compile.compile(os.path.join(HERE, script), cfile=target, doraise=True)
                    check("compiles_" + script, True)
                except Exception as exc:  # noqa: BLE001 编译失败要原样报出来
                    check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        check("compile_probe_cleaned_up", not os.path.exists(tmp), "临时目录没删掉：" + tmp)
    else:
        for script in scripts:
            check("compiles_" + script, False, "没有可写的编译产物落点")

    stray = [name for name in os.listdir(HERE) if name == "__pycache__"]
    check("no_stray_pycache", not stray, ",".join(stray))

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
    print("%d/%d 通过：五条硬规矩、三档读数（固定文本清单 %d 条齐）、六句探针与护栏、"
          "验收先跑我自己都在；名单留在仓库外，没夹字面编号和账号。"
          % (total, total, len(STRONG_FIXED_TEXT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
