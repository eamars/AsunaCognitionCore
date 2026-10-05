#!/usr/bin/env python3
"""asuna-offline-selfchecks 的零依赖离线自检。

本技能是核心技能 asuna-self-improvement 之上的**增量笔记**，所以这里查三件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节在、脚本能编译；
2. 指向：正文指向核心技能，并写明两份不一致时按核心技能办；
3. 增量与「不回潮」：四条增量（挂错项目的红、单个用例文件与 p3 基线、p5b 退役读法、
   没收录 ≠ 已退役、适配器自检去处）都还在；通用离线套件的命令清单没有回潮到散文里
   ——反引号里的字面量（旧试用记录引用的命令、错误原文）按引用处理，不算回潮。

不联网、不跑离线套件、不写 Mongo、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-offline-selfchecks/check_skill.py   # 候选根目录
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import py_compile
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

CORE_SKILL = "asuna-self-improvement"

# 增量内容：核心技能没有、本技能必须写清的几条
INCREMENTS = [
    ("increment_wrong_project", "No such file or directory"),
    ("increment_wrong_project_meaning", "选错项目，不是产品坏了"),
    ("increment_single_case_files", "PYTHONPATH=tests"),
    ("increment_p3_baseline", "p3-baseline"),
    ("increment_baseline_skip_not_fail", "跳过不算失败"),
    ("increment_p5b_retired", "p5b_ui_offline_check"),
    ("increment_not_included_not_retired", "没收录 ≠ 已退役"),
    ("increment_adapter_elsewhere", "qq-napcat-adapter"),
]

SECTIONS = [
    "## 用途",
    "## 增量",
    "## 版本",
    "## 试用记录",
]

# 通用清单回潮：这些命令字面量属于核心技能的「发布前自检」，本技能散文里不该再出现。
# （旧试用记录里引用它们的原话都在反引号里，按引用放过。）
GENERIC_SUITE_TOKENS = [
    "tools/p2_offline_check.py",
    "tools/p3_offline_check.py",
    "tools/p5_offline_check.py",
    "compileall -q src/asuna",
    "discussion_digest_cases",
]

# 反引号里的字面量是引用（命令原话、错误原文、旧记录里的实跑输出），只在散文里判红。
PROSE = re.compile(r'`[^`]*`', re.S)
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
    prose = PROSE.sub(" ", body)
    check("frontmatter_parses", fields is not None)
    check("frontmatter_name_present", bool(fields and fields.get("name")))
    check("name_matches_directory",
          bool(fields and fields.get("name") == EXPECTED_NAME),
          "name=%s dir=%s" % ((fields or {}).get("name"), EXPECTED_NAME))
    desc = (fields or {}).get("description", "")
    check("description_specific_enough", len(desc) >= 120, "len=%d" % len(desc))
    check("description_points_core_skill", CORE_SKILL in desc,
          "frontmatter description 没指向核心技能 " + CORE_SKILL)

    for name, section in [("section_" + str(i), s) for i, s in enumerate(SECTIONS)]:
        check(name, ("\n" + section) in ("\n" + body), section)

    # 指向：正文里指向核心技能，并写明不一致时按它办
    check("points_to_core_skill", CORE_SKILL in body, "正文没提 " + CORE_SKILL)
    check("points_precedence", ("按 `" + CORE_SKILL + "`") in body,
          "没写明两份不一致时按核心技能办")

    for name, token in INCREMENTS:
        check(name, token in body, token)

    # 通用清单回潮：命令字面量回到散文 = 又把核心技能抄了一遍
    regressed = [token for token in GENERIC_SUITE_TOKENS if token in prose]
    check("no_generic_suite_list_in_prose", not regressed, ",".join(regressed))

    check("selfcheck_documented", "check_skill.py" in body)
    check("no_placeholder_markers", not PLACEHOLDER.search(prose))
    check("skill_body_not_thin", len(body) >= 1500, "body_chars=%d" % len(body))

    # 同目录脚本：必须存在且只用标准库能编译（编译产物写到临时目录，不脏技能目录）
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    tmp = tempfile.mkdtemp(prefix="skillcheck-")
    for script in scripts:
        target = os.path.join(tmp, script + "c")
        try:
            py_compile.compile(os.path.join(HERE, script), cfile=target, doraise=True)
            check("compiles_" + script, True)
        except Exception as exc:  # noqa: BLE001 编译失败要原样报出来
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

    stray = [d for d in os.listdir(HERE) if d == "__pycache__"]
    notes = []
    if stray:
        notes.append("NOTE 技能目录里有 __pycache__（compileall 留下的），发布前清掉："
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
    print("%d/%d 通过：指向核心技能、四条增量都在，通用清单没回潮。" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
