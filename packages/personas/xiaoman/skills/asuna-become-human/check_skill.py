#!/usr/bin/env python3
"""asuna-become-human 的零依赖离线自检。

为什么有这份脚本：ADR-078 §3 那条闸门（我 2026-10-17 签的）——声明了 `home` 以外场景的技能，
必须自带一份带私密词泄露判据的自检，仓库测试 tests/test_skill_scenes.py
::test_a_skill_that_leaves_home_passes_its_own_private_words_scan 会跑它。10-18 晚
`scene_kinds` 开了 `group`，所以这份脚本同时落地。

只钉三样，不加别的判据（不做风格、字数、形状检查——那份技能管的是说话，读数不给话打分）：

1. 10-18 晚新加的三节锚点：「范围」「跑偏判据」（六条齐，第 6 条反向跑偏在）「自查节奏与记录」。
   按节名与关键句钉，**不钉行号**——正文以后插一段话不该让这一格假红。
2. 私密词泄露扫描：真跑本机私密名单（`ASUNA_PRIVATE_WORDS` → `<数据目录>/private/personal-words.txt`
   → 从脚本往上找 `.runtime/private/personal-words.txt`）。命中只报类别与名单行号，词本身不打印；
   命中就红（no_listed_words）。名单配不上、或名单在却解析出 0 条有效词，记一条红（leak_scan_ran）：
   「没真查」不许长得像「查过了」。

3. 换行是 LF：读字节数 CR。文本模式那把尺看不见 CR（2026-10-15 撞过一次），判据名与另外几份 check_skill.py 逐字一致。

不联网、不查历史、不写 Mongo、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]      # 默认取脚本旁边的 SKILL.md
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import re
import sys

# 宿主普通 Windows 控制台默认码页可能不是 UTF-8：中文一 print 就整段崩（2026-10-15 实测六份自检全中）。
# 输出字节固定成 UTF-8，那种控制台顶多显示成乱码，不再把报错吞掉。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))

# 三节锚点：节名 ＋ 每节里只有写全了才会出现的字面（主人 2026-10-18 20:35 定的那几格）
ANCHORS = [
    # 范围
    ("section_scope", "## 范围"),
    ("scope_one_group_named", "这一个群聊场合（place `g68847c`；群名不带出去，正文只留这个 place 号）里成立"),
    ("scope_ordinary_member_with_tools", "当一个会用工具的普通群友"),
    ("scope_other_groups_not_applied", "**别的群不套用**"),
    ("scope_persona_unchanged", "**不改整体人设**"),
    ("scope_voice_section_owns_tone", "照旧归 voice 那节"),
    # 跑偏判据
    ("section_drift_criteria", "## 跑偏判据"),
    ("drift_1_service_tone", "**客服腔收尾**"),
    ("drift_2_unasked_steps", "**没人问就给分点步骤**"),
    ("drift_3_no_volunteering", "**主动揽活**"),
    ("drift_3_nobody_named_no_offer", "**没人点名就不揽**"),
    ("drift_4_report_tone", "**报告腔**"),
    ("drift_5_over_closing", "**过度收尾**"),
    ("drift_6_reverse_listed", "**反向跑偏**"),
    ("drift_6_faking_ignorance_is_drift", "**为了不像助手而装不知道，也是跑偏**"),
    # 自查节奏与记录
    ("section_selfcheck", "## 自查节奏与记录"),
    ("selfcheck_not_on_the_speaking_turn", "**自查不放在开口那一拍**"),
    ("selfcheck_30_messages", "**30 条我在那个群说的话**"),
    ("selfcheck_three_days_first", "**满 3 天**"),
    ("selfcheck_low_tier_review", "**低档行动脑**"),
    ("selfcheck_dated_record", "带日期的记录"),
    ("selfcheck_shapes_and_counts_only", "**只写看到什么形状、各几条**"),
    ("selfcheck_no_scores", "**不写分数、不写「像人几分」**"),
    ("selfcheck_rewrite_in_place_no_dispatch", "**命中就重写那句话，不派活**"),
    ("selfcheck_dispatch_only_when_atmosphere_unknown", "**才当场派一趟低档**"),
    ("selfcheck_no_lying", "不撒谎，有人问是不是 AI 就照实答"),
    ("selfcheck_no_fake_typos", "不加错字、不耍装人的小把戏"),
    ("selfcheck_no_pressure", "不给任何人压力"),
    # 10-18 晚同时改的那格：闸门本身在正文里有交代
    ("gate_declared_in_body", "check_skill.py"),
]

DRIFT_SECTION = re.compile(r"## 跑偏判据.*?(?=\n## )", re.S)
NUMBERED_ITEM = re.compile(r"^\d+\. \*\*", re.M)


def private_list():
    """私密名单（private_words 工具维护，永远不进仓库）：一行一条 category|word|why。

    三条定位与 asuna-bot-or-person 那份自检一致：环境变量 → 数据目录 → 从脚本往上找
    .runtime/private/personal-words.txt。三条都不中返回试过的候选，让调用方把「没查过」写进红里。
    """
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


def hit_label(number, category):
    """命中在输出里的样子：只有类别和名单行号。防泄露的检查自己不许漏词。"""
    return "%s（名单第 %d 行）" % (category, number)


def listed_hits(entries, text):
    """命中返回 [(名单行号, 类别, 词)]。纯 ASCII 词按整词判（大小写不敏感），其余按字面子串。"""
    hits = []
    for number, category, word in entries:
        if all(ch.isascii() for ch in word):
            found = re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE)
        else:
            found = word in text
        if found:
            hits.append((number, category, word))
    return hits


def cr_bytes(paths):
    """字节级数 CR。文本模式读（universal newlines）会把 CR 吃掉，查换行永远绿——
    2026-10-15 实测：真 CRLF 样本 CR=59，同一份用 open(..., encoding="utf-8") 读进来
    再问 "\r" not in text 仍是 True。只有读字节才看得见。返回带 CR 的文件说明。"""
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

    for name, token in ANCHORS:
        check(name, token in text, token)

    # 六条判据必须还是六条：数「## 跑偏判据」那一节里以「数字. **」开头的行
    section = DRIFT_SECTION.search(text)
    check("drift_section_present", section is not None, "找不到 ## 跑偏判据 那一节")
    count = len(NUMBERED_ITEM.findall(section.group(0))) if section else 0
    check("drift_six_items_count_is_six", count == 6, "跑偏判据那一节数到 %d 条（应为 6）" % count)

    # 泄露扫描：真跑本机名单。名单配不上或 0 条有效词都记红，不 NOTE 一行算过。
    listed_path, entries = private_list()
    leak_note = ""
    if entries is None:
        check("leak_scan_ran", False,
              "私密名单没配上（试过 %s）：真人名／群名这一项没真查——不是跑过了"
              % ("、".join(listed_path) if listed_path else "都没有"))
    elif not entries:
        check("leak_scan_ran", False, "名单 0 条（%s）——没真查，不是跑过了" % listed_path)
    else:
        check("leak_scan_ran", True)
        hits = listed_hits(entries, text)
        leak_note = "，泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries)
        check("no_listed_words", not hits,
              ("命中私密名单，人工过一眼是不是真人名／群名："
               + "、".join(hit_label(n, c) for n, c, _w in hits)) if hits else "")

    # 换行：必须读字节。文本模式（universal newlines）把 CR 吃掉，"\r" not in text 永远为真——
    # 2026-10-15 实测真 CRLF 样本 CR=59 照样绿。判据名与另外五份 check_skill.py 逐字一致。
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    cr_files = cr_bytes([path] + [os.path.join(HERE, script) for script in scripts])
    check("line_endings_are_lf", not cr_files,
          "有 CR（仓库守卫 test_line_endings 会红）：" + "、".join(cr_files))

    total = len(results)
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, detail in results:
        if not ok and detail:
            print("FAIL %s  <- %s" % (name, detail))
    if failed:
        print("%d/%d 通过，失败：%s" % (total - len(failed), total, ", ".join(failed)))
        return 1
    print("%d/%d 通过：范围／跑偏判据（六条齐）／自查节奏与记录三节锚点都在，"
          "scene_kinds 开了 group 也带了这份自检%s。" % (total, total, leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
