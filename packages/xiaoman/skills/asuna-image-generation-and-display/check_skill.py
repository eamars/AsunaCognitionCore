#!/usr/bin/env python3
"""asuna-image-generation-and-display 的零依赖离线自检。

只查技能文件自己：frontmatter 能不能解析、name 与目录名是否一致、关键工具名 / 端点别名 /
服务路径 / 关键步骤 / 边界语句在不在、示例图路径是不是相对的、同目录脚本能不能编译。

不联网、不调生图服务、不生成图、不写 Mongo、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import py_compile
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

# 关键工具名与它们必须出现的语境（子串，按字面查）
TOOLS = [
    ("tool_import_artifact", "import_integration_artifact"),
    ("tool_import_endpoint_alias", 'endpoint="image"'),
    ("tool_read_image", "read_image"),
    ("tool_read_image_fence_error", "IMAGE_ATTACHMENT_NOT_IN_SCENE"),
    ("tool_read_image_route_error", "VISION_ROUTE_UNSUPPORTED"),
    ("import_artifact_path_arg", "artifact_path"),
    ("import_target_arg", "target_relative_path"),
    ("import_size_cap_arg", "max_bytes"),
    ("import_overwrite_arg", "overwrite"),
    ("receipt_sha256", "sha256"),
]

# 服务侧必须写清的路径 / 契约
SERVICE = [
    ("service_manifest", "/.well-known/agent-manifest.json"),
    ("service_resolve", "/project/resolve"),
    ("service_generate", "/project/generate"),
    ("service_job_poll", "/project/jobs/"),
    ("service_view_url", "/view?filename="),
    ("service_ready_only", "ready=true"),
    ("service_result_contract", "result_contract"),
    ("service_prompt_granularity", "prompt_granularity"),
    ("service_config_probe_host", "integration_test"),
]

# 硬边界：这些句子必须在，否则下次容易越界
BOUNDARIES = [
    ("boundary_no_group", "不发群"),
    ("boundary_no_base64_transport", "base64"),
    ("boundary_keep_qq_adapter", "QQ 适配器"),
    ("boundary_no_visual_review_claim", "未做视觉复核"),
    ("boundary_honest_failure", "如实"),
    ("boundary_no_regen_for_test", "不为了"),
    ("size_cap_numbers", "4 MiB"),
    ("small_display_copy", "SaveAnimatedWEBP"),
]

SECTIONS = [
    "## 用途",
    "## 前提与授权",
    "## 步骤 0",
    "## 步骤 1",
    "## 步骤 2",
    "## 步骤 3",
    "## 步骤 4",
    "## 步骤 5",
    "## 步骤 6",
    "## 步骤 7",
    "## 边界",
    "## 离线自检",
    "## 已知坑",
    "## 版本",
    "## 试用记录",
]

# 占位标记只在散文里算问题：反引号里的字面量（示例、错误码、被改坏的副本内容）是引用，不是没写完。
PROSE = re.compile(r'`[^`]*`', re.S)

# 展示口径：报告里必须是相对路径的 Markdown 图片
RELATIVE_IMAGE = re.compile(r"!\[[^\]]*\]\((?![A-Za-z]:[\\/]|/|file://)[^)\s]+\)")
ABSOLUTE_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*(?:[A-Za-z]:[\\/]|/|file://)")
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

    for name, section in [(("section_" + str(i)), s) for i, s in enumerate(SECTIONS)]:
        check(name, ("\n" + section) in ("\n" + body), section)

    for name, token in TOOLS + SERVICE + BOUNDARIES:
        check(name, token in body, token)

    check("display_relative_markdown_image", bool(RELATIVE_IMAGE.search(body)))
    check("display_no_absolute_image_path", not ABSOLUTE_IMAGE.search(body))
    check("selfcheck_documented", "check_skill.py" in body)
    check("no_placeholder_markers", not PLACEHOLDER.search(PROSE.sub(' ', body)))
    check("skill_body_not_thin", len(body) >= 4000, "body_chars=%d" % len(body))

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
    print("%d/%d 通过：技能文件、工具名与关键步骤都在。" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
