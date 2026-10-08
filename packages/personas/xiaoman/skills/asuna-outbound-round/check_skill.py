#!/usr/bin/env python3
"""asuna-outbound-round 的零依赖离线自检。

这份技能是「出门那一轮」的规则集，所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节在、脚本能编译；
2. 内容要点：开口前五查、回看四条、一条边界的字面要点都在；
3. 不带别人的个人信息：禁词表（人名／群名／称呼）与字面编号（#数字）都不该出现在正文；
4. 没有占位符残留。

不联网、不碰数据库、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-outbound-round/check_skill.py   # 候选根目录
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import py_compile
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 时机",
    "## 开口前几查",
    "## 回看怎么做",
    "## 一条边界",
    "## 版本",
    "## 试用记录",
]

# 开口前几查：每条查一个只有写全了才会出现的字面
PRECHECKS = [
    ("precheck_freshness", "几点发的"),
    ("precheck_freshness_probe", "还开着吗"),
    ("precheck_question_type", "是非题给是非题的答案"),
    ("precheck_mention_copy_tag", "照抄整个标签"),
    ("precheck_mention_bare_name", "不带编号、不带方括号"),
    ("precheck_mention_no_hash_for_nonperson", "别带井号"),
    ("precheck_one_line_reply", "一句话回"),
    ("precheck_attribution", "归属未定"),
    ("precheck_attribution_hold_state", "先不动那件事的状态"),
]

# 回看四条
REVIEW = [
    ("review_both_sides", "接住的和砸的都要记"),
    ("review_one_lesson", "最多留一条教训"),
    ("review_rules_not_score", "比分"),
    ("review_verify_last_rule", "先验上次那条"),
]

# 一条边界：验提及不能靠回看出站消息
BOUNDARY = [
    ("boundary_outbound_is_verbatim", "出站消息存的就是我写出去的原样"),
    ("boundary_shape_before_send", "形状在发送前写对"),
    ("boundary_cant_tell", "判不了"),
]

# 时机：就地做，不绕开发库
TIMING = [
    ("timing_in_scene", "出门那一轮"),
    ("timing_no_dev_db_detour", "别在本机这边绕道翻开发库"),
]

# 别人的个人信息不进技能：称呼和场景词。出现即红。
# 具体的人名、群名不写进这张表：这个仓库是公开的，表里的字本身就会把人带出去；字面编号由下面的 LITERAL_ID 查。
PERSONAL_TOKENS = [
    "主人", "旧居", "交流群", "姐姐",
]

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

    for name, section in [("section_" + str(i), s) for i, s in enumerate(SECTIONS)]:
        check(name, ("\n" + section) in ("\n" + body), section)

    for group in (TIMING, PRECHECKS, REVIEW, BOUNDARY):
        for name, token in group:
            check(name, token in body, token)

    # 边界必须写成边界：不能只留一句「发送前写对」而丢了「别拿回看验提及」
    check("boundary_names_wrong_method", "回看自己发出去的那条" in body,
          "边界没点名它禁的是哪种验法")

    # 个人信息扫描：只扫 SKILL.md 正文（本脚本的禁词表是检查器自己的，不算）
    hits = [tok for tok in PERSONAL_TOKENS if tok in body]
    check("no_personal_info", not hits, ",".join(hits))
    check("no_literal_ids", not LITERAL_ID.search(body),
          "出现字面编号：" + ",".join(LITERAL_ID.findall(body)[:5]))

    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 800, "body_chars=%d" % len(body))
    check("selfcheck_documented", "check_skill.py" in body)

    # 同目录脚本：必须存在且能编译。编译产物落在技能目录旁的 _compile-probe
    # 子目录，用完即删，不留 __pycache__。
    # 为什么不用系统 Temp、也不用点开头目录：宿主沙箱只放行候选目录里的写，
    # 且实跑发现点开头目录里的写会被拒（PermissionError）——都撞过，别再撞。
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    tmp = os.path.join(HERE, "_compile-probe-%d" % int(time.time() * 1000))
    os.makedirs(tmp, exist_ok=True)
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
    print("%d/%d 通过：五查、回看、边界要点齐全，没夹个人信息。" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
