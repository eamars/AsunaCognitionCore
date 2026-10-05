#!/usr/bin/env python3
"""asuna-image-generation-and-display 的零依赖离线自检。

只查技能文件自己：frontmatter 能不能解析、name 与目录名是否一致、关键工具名 / 端点别名 /
服务路径 / 关键步骤 / 边界语句在不在、QQ 私聊 `attach_image` 那条路的清单字段与失败码在不在、
「本机页面核验」的归属是不是 Claude（不是主人）、示例图路径是不是相对的、同目录脚本能不能编译。

2026-10-05 起改口径：QQ 私聊发图是那一轮调用 `attach_image` 工具（DECIDE 阶段与它的 `attach`
字段已退役）。退役说法——`integration_dev`、`/skills` 挂载路径、把 DECIDE 的 `attach` 字段 /
`ATTACH_NOT_WHEN_SILENT` / `episode.rejections` / `maxItems: 1` 当当前流程——回到散文里就红。

归属与「过期说法」两类红只看散文：反引号里的字面量（错误码、历史段引用的旧句子、反证记录里
被改坏的副本内容）按引用处理，不算数——和占位标记同一套口径。

不联网、不调生图服务、不生成图、不写 Mongo、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-image-generation-and-display/check_skill.py   # 候选根目录
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
    ("probe_script_in_channel_candidate", "napcat-qq"),
]

# 硬边界：这些句子必须在，否则下次容易越界
BOUNDARIES = [
    ("boundary_group_own_only", "群里只发自己做的图"),
    ("boundary_no_base64_transport", "base64"),
    ("boundary_keep_qq_adapter", "QQ 适配器"),
    ("boundary_no_visual_review_claim", "未做视觉复核"),
    ("boundary_honest_failure", "如实"),
    ("boundary_no_regen_for_test", "不为了"),
    ("size_cap_numbers", "4 MiB"),
    ("small_display_copy", "SaveAnimatedWEBP"),
]

# QQ 私聊 attach_image 发图：前提、来源、写法、失败码，一条都不能漏
ATTACH = [
    # 前提
    ("attach_tool", "attach_image"),
    ("attach_context_offer", "image_artifacts_from_program"),
    ("attach_owner_private", "owner_private"),
    ("attach_dm_route", "target.type=dm"),
    ("attach_offer_bounded", "最多 6 条"),
    ("attach_offer_absence", "清单缺席"),
    ("attach_tool_absence", "工具也不出现"),
    # 只对主人私聊
    ("attach_group_refused", "确定性拒绝"),
    # 图从哪来
    ("attach_source_blobstore", "BlobStore"),
    ("attach_source_registered_flag", "registered: false"),
    ("attach_from_linked_scene", "from_linked_scene"),
    ("attach_canonical_person", "canonical person"),
    ("attach_local_scope_example", "scene:local-dm"),
    ("attach_qq_scene_example", "（主人的 QQ 私聊场景，场景 id 以配置为准）"),
    # 怎么写（当前口径：那一轮调用 attach_image 工具）
    ("attach_max_one_per_turn", "一回合最多一张"),
    ("attach_replace_on_second_call", "再调用就换成新的那张"),
    ("attach_id_required", "必填"),
    ("attach_id_not_a_path", "不是文件路径也不是文件名"),
    ("attach_speak_no_see_image", "见图"),
    ("attach_metadata_first_row", "第一行"),
    ("attach_adapter_capability", "supports=image"),
    ("attach_silent_no_send", "stay_silent"),
    # 工具侧失败码（工具错误，同回合可改）
    ("attach_reject_is_tool_error", "工具错误"),
    ("attach_fix_same_turn", "同一回合"),
    ("attach_err_target_not_allowed", "ATTACH_TARGET_NOT_ALLOWED"),
    ("attach_err_not_in_context", "ATTACH_ARTIFACT_NOT_IN_CONTEXT"),
    ("attach_err_artifact_unavailable", "ATTACHMENT_ARTIFACT_UNAVAILABLE"),
    ("attach_err_scope_denied", "ATTACHMENT_SCOPE_DENIED"),
    ("attach_err_not_an_image", "ATTACHMENT_NOT_AN_IMAGE"),
    ("attach_err_over_limit", "ATTACHMENT_OVER_LIMIT"),
    ("attach_err_hash_mismatch", "ATTACHMENT_HASH_MISMATCH"),
    ("attach_outbound_size_cap", "8 MiB"),
    # 字节端点侧失败码
    ("attach_endpoint_attempt_mismatch", "PUBLICATION_ATTEMPT_MISMATCH"),
    ("attach_endpoint_not_declared", "ATTACHMENT_NOT_DECLARED"),
    ("attach_endpoint_artifact_denied", "ATTACHMENT_ARTIFACT_DENIED"),
    ("attach_endpoint_sha_mismatch", "ATTACHMENT_SHA_MISMATCH"),
    ("attach_endpoint_media_type_mismatch", "ATTACHMENT_MEDIA_TYPE_MISMATCH"),
    # 适配器侧读法与历史读法
    ("attach_group_not_her_own", "ATTACHMENT_NOT_HER_OWN"),
    ("attach_adapter_unknown_target", "attachment_target_not_enabled"),
    ("attach_adapter_over_limit", "attachment_over_limit"),
    ("attach_adapter_fetch_unavailable", "attachment_fetch_unavailable"),
    ("attach_adapter_not_an_image", "attachment_not_an_image"),
    ("attach_adapter_sends_nothing", "整条不发"),
    ("attach_skipped_marker", "attachment_skipped"),
    ("attach_skipped_reason", "channel_does_not_declare_image"),
    ("attach_history_attested", "attested"),
    ("attach_history_evidence_mismatch", "attachment_evidence_mismatch"),
    # 还没实测的那一条，别被写成「已经能看到图了」
    ("attach_base64_uri_caveat", "base64://"),
    # 旧 DECIDE 流程只作历史保留：历史段必须在，且明说别照它教当前流程
    ("attach_history_section", "别照它教当前流程"),
    ("attach_history_decide_retired", "DECIDE 阶段后来整体退役"),
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
    "## 步骤 8",          # 追加在末尾：老检查名（section_0..section_14）不跟着移位
]

# 归属：本机页面那次核验是 Claude 做的，主人那晚在睡。写回「主人核过」就是假事实。
CLAUDE_PAGE_CHECK = re.compile(r"Claude[^\n]{0,60}在本机页面核过")
OWNER_PAGE_CHECK = re.compile(r"主人[^\n]{0,20}在本机页面核过|主人在页面核验|主人页面渲染")

# 已经过期的说法：出站图片能力上线后、DECIDE 退役后不能再这么写（只看散文，反引号里的引用不算）
STALE_CLAIMS = [
    "QQ 私聊现在收不到图",
    "宿主 outbox 只交",
    '私聊段白名单是 ("text",)',
    "integration_dev",
    "/skills/asuna",
    "DECIDE 给 attach",
    "ATTACH_NOT_WHEN_SILENT",
    "episode.rejections",
    "maxItems: 1",
]

# 反引号里的字面量是引用（示例、错误码、历史段与被改坏副本里引用的旧句子），只在散文里判红。
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
    prose = PROSE.sub(" ", body)
    check("frontmatter_parses", fields is not None)
    check("frontmatter_name_present", bool(fields and fields.get("name")))
    check("name_matches_directory",
          bool(fields and fields.get("name") == EXPECTED_NAME),
          "name=%s dir=%s" % ((fields or {}).get("name"), EXPECTED_NAME))
    desc = (fields or {}).get("description", "")
    check("description_specific_enough", len(desc) >= 120, "len=%d" % len(desc))
    check("description_mentions_attach_image", "attach_image" in desc,
          "frontmatter description 没提 attach_image 这条路")

    for name, section in [("section_" + str(i), s) for i, s in enumerate(SECTIONS)]:
        check(name, ("\n" + section) in ("\n" + body), section)

    for name, token in TOOLS + SERVICE + BOUNDARIES + ATTACH:
        check(name, token in body, token)

    check("display_relative_markdown_image", bool(RELATIVE_IMAGE.search(body)))
    check("display_no_absolute_image_path", not ABSOLUTE_IMAGE.search(body))
    check("selfcheck_documented", "check_skill.py" in body)
    check("no_placeholder_markers", not PLACEHOLDER.search(prose))
    check("skill_body_not_thin", len(body) >= 4000, "body_chars=%d" % len(body))

    # 归属更正：页面核验是 Claude 做的，主人还在睡；散文里写回「主人核过」就是假事实
    check("attribution_page_check_by_claude",
          bool(CLAUDE_PAGE_CHECK.search(prose)) and not OWNER_PAGE_CHECK.search(prose),
          "散文里缺 Claude 核过的说法，或还留着「主人核过 / 主人在页面核验」")
    check("attribution_owner_asleep", "主人还在睡" in body, "没写明这一轮主人还在睡、没有主人侧新核验")

    # 过期说法：出站图片上线、DECIDE 退役后不能再这么写（反引号里的引用不算）
    stale = [item for item in STALE_CLAIMS if item in prose]
    check("no_stale_text_only_claim", not stale, ",".join(stale))

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
    print("%d/%d 通过：技能文件、工具名、attach_image 那条路的清单与失败码、历史段、归属都在。" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
