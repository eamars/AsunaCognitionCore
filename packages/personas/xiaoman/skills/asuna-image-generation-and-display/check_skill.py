#!/usr/bin/env python3
"""asuna-image-generation-and-display 的零依赖离线自检。

只查技能文件自己：frontmatter 能不能解析、name 与目录名是否一致、关键工具名 / 端点别名 /
服务路径 / 关键步骤 / 边界语句在不在、发图那条路（QQ（napcat）speak 的 picture，别处 attach_image）的清单字段与失败码在不在、
改图那条路（「改图与 generate_image」一节：source_image 入口、11 条路线读数、三条 IMAGE_WORKFLOW_*
即时拒绝码、改图归属、本地 Pillow 修字、剥文字块判据、排队成本）在不在、
群聊生图上限那条（「群聊生图上限」一节标题、节内「最多 4 张」与「到顶默认不发」、
「唯一的例外」是不是 10:59 更正版、10:57 旧措辞有没有被抄回这一节）在不在、
「往群里发图之前的自检」一节在不在且四条要点（全年龄底线、看群笔记／最近聊天、只发自己做的图、
不为试功能发图）齐不齐、示例图路径是不是相对的、
同目录脚本能不能编译、SKILL.md 与同目录脚本的换行是不是 LF（读字节数 CR，文本模式那把尺看不见 CR）。

2026-10-05 起改口径：QQ 私聊发图是那一轮调用 `attach_image` 工具（DECIDE 阶段与它的 `attach`
字段已退役）。退役说法——`integration_dev`、`/skills` 挂载路径、把 DECIDE 的 `attach` 字段 /
`ATTACH_NOT_WHEN_SILENT` / `episode.rejections` / `maxItems: 1` 当当前流程——回到散文里就红。

2026-10-14 起再改口径（ADR-064 phase 2，REPLY_PARTS）：QQ（napcat）的 channel kind 声明了 reply parts，
那一轮她只通过 speak 说话，发图是 picture 那一项；没声明的对话（列着 attach_image 的那些）照旧。
判据押这两条路的说法在不在，不押裸字面量 attach_image 的在/不在——既不许硬要求它在，也不许硬要求它不在。

2026-10-16 起再补口径（改图通路现场验收）：「改图与 generate_image」一节必须在，且该节切片里
source_image 入口与三条 IMAGE_WORKFLOW_* 即时拒绝码必须齐（错误码在别处出现不算数——那一节才是教改图的地方）；
`九条路线全是 t2i` 是 2026-10-16 前的旧读数，反引号外裸写回散文（当现行事实）才红。

2026-10-16 v8 再补（群聊生图上限：主人提、小满定标准）：这一节进 SECTIONS（缺标题就红），节内切片必须含
「最多 4 张」与「到顶默认不发」（正文照主人原话抄，那一句写的是「到顶怎么办：默认不发。」，
两种写法任一命中即算在，都被删掉才红）。「唯一的例外」那段必须含「对外不报张数」（10:59 更正版），
10:57 旧版那句「超了要在交回时写一句」回到这一节就红——防止旧措辞把更正版覆盖掉。
标题被删时切片为空、这几条一起红：切片为空不等于查过，不会绿着放过。

同一轮补上泄露检查（这一族以前在本脚本里根本没有）：私密名单找得到就真扫，命中只报类别与名单行号；
找不到名单、或名单在却解析出 0 条有效词，都记一条红（leak_scan_ran），不像别的技能脚本那样 NOTE 一行就算过——
「检查项没跑」和「检查项过了」不能长得一样。名单定位依次试：ASUNA_PRIVATE_WORDS → ASUNA_DATA_ROOT →
asuna.config.DATA → 从脚本所在目录往上找 .runtime/private/personal-words.txt
（2026-10-16 实测更正：开发沙箱里两个环境变量都没设，但 `asuna` 能 import、第三条就够；
最后那条是给 `asuna` 不在 sys.path 上的环境兜底：裸检出、别的机器、装在 node_modules 里的冻结版）。

群发前自检的四条要点只在「往群里发图之前的自检」这一节里查：正文别处合法提到历史口径
（版本段引用「不发群」旧边界、试用记录里的旧句子）不算缺、也不误报红；把「不发群」这类
旧限制写回这一节才红。

归属与「过期说法」两类红只看散文：反引号里的字面量（错误码、历史段引用的旧句子、反证记录里
被改坏的副本内容）按引用处理，不算数——和占位标记同一套口径。

2026-10-20 起再补两条锚点判据（起因：ADR-083 重排 RUNTIME_API.md 后我指过去的节名失效过，
而这份自检里没有任何判据在守节名——节名改错它照绿）：`no_line_anchors`（反引号里的行号锚一律红，
判法照 asuna-usage-readout 那份搬、没有白名单）与 `section_anchors_resolve`（正文里 § 指节名的锚、
以及 RUNTIME_API.md 后面用箭头串起来的路径式节名，逐个去那份文档的标题表里找，找不到就红并报出
SKILL.md 的行号与那一行原文）。那份文档的找法不绑死环境：从脚本往上走认仓库根（.git 或
pyproject.toml）取根下那份，再退 core 候选根那份；两处都没有就报 UNCHECKED（没查），
不算过也不判红。这两条不进仓库共用测试：共用测试一红会卡住改文档节名的人（Claude 与主人 10-20 定的）。

2026-10-24 v11 再补一节判据（「本机已有那张图怎么进可发清单」）：第二条通路 register_imported_image 带
scope_key 那一格在不在（scope 字面值从 `scenes` 读、`source` 前缀决定这行算谁的、清单新的在前最多 6 张、
群那条从最新 200 行里筛、超 8 MiB 拒绝）、登记剥 PNG 文字块这条代价在不在（同一张图像素没动但 sha 与 size
都变：`d1aa3735…` 2,227,501 B → `748e7ce1…` 2,225,102 B，差 2,399 B ⇒ sha 不能当「与原件一模一样」的证据），
以及两条账面判据（`read_image` 按路径看过 ≠ 图在可发清单里；等不到 ack 那一支不进 `settle()` ⇒ 库里 UNKNOWN、
`sends.jsonl` 连那一行都不落，判到没到只有平台侧只读回读或对方本人；文本那格 DELIVERED 推不出图那格到了——
库里是两条独立消息行）。「只有 render_svg 这一条路」是 10-21 想法本里的待提案、本技能正文从没写过（本轮扫过
候选整棵、origin/main 那份文件与 `git log -S`，三处 0 命中）——它进 STALE_CLAIMS：不带反引号写回散文才红。

2026-10-27 起再补一节判据（「官方定妆」里的黑发配方）：正向双写 (jet black hair:1.4)＋(black hair:1.4)、
负面三项 white hair, silver hair, gray hair、以及两条限制（仅该路线验证、画完仍逐次 read_image）五条字面
押在该节切片里——配方与限制同等承重，只留配方不留限制，下次就会被当通用配方搬去别的路线。

不联网、不调生图服务、不生成图、不写 Mongo、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-image-generation-and-display/check_skill.py   # 候选根目录
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import re
import sys

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就 UnicodeEncodeError 整段崩，整段输出丢掉
# （2026-10-15 实测：六份 check_skill.py 全中，rc=1、stdout 0 字节）。我的沙箱 env 带 PYTHONUTF8=1／
# PYTHONIOENCODING=utf-8，自检撞不到这一族。输出字节固定成 UTF-8：那种控制台顶多显示成乱码，
# 不再崩；stderr 同理，报错才看得见。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

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
    # 2026-10-14 口径：QQ（napcat）用 speak 的 picture；别处列着 attach_image 就用它。
    # 押这两条路的说法，不押裸字面量 attach_image 的在/不在。
    ("attach_qq_speak_picture", "speak 的 picture"),
    ("attach_non_qq_route", "别处列着 attach_image"),
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
    ("attach_history_section", "旧写法别照做"),
    ("attach_history_decide_retired", "DECIDE 阶段已退役"),
]

# 改图那条路（2026-10-16 现场验收）：入口、路线读数、即时拒绝码、归属、本地修字、剥文字块、排队成本。
# 押这些字面量在不在；「九条路线全是 t2i」反过来进 STALE_CLAIMS（旧读数写回散文才红）。
EDIT = [
    # 入口：source_image 收 ref / artifact_id，能喂的图 = read_image 这一回合能看的那些
    ("edit_source_image_entry", "source_image"),
    ("edit_route_count", "11 条"),
    ("edit_route_required", "qwen-image-2.1-edit"),
    ("edit_route_optional_nine", "九条标"),
    ("edit_service_picks_edit_route", "服务自己挑一条改图路线"),
    # 配错路线：瞬时返回，不排队、不白传图
    ("edit_err_takes_no_source", "IMAGE_WORKFLOW_TAKES_NO_SOURCE"),
    ("edit_err_needs_source", "IMAGE_WORKFLOW_NEEDS_SOURCE"),
    ("edit_err_needs_more_pictures", "IMAGE_WORKFLOW_NEEDS_MORE_PICTURES"),
    ("edit_mask_absent", "mask_image"),
    ("edit_inpaint_unreachable", "永远进不去"),
    # 归属：改自己的还是我的；改别人的 produced: false、只能发回原图所在对话
    ("edit_own_result_mine", "改我自己画的图，结果还是我的"),
    ("edit_others_result_produced_false", "produced: false"),
    ("edit_send_back_to_origin", "只能发回原图所在那个对话"),
    # 修图内错字：本地 Pillow 合成，家里才有 sandbox_run
    ("edit_local_fix_pillow", "Pillow"),
    ("edit_fonts_present", "中文字体不缺"),
    ("edit_group_no_sandbox_run", "群里交出去的任务没有"),
    # 发出去的图剥掉 PNG 文字块；任务目录原件照旧带 prompt 块
    ("edit_strip_text_chunk", "tEXt"),
    ("edit_strip_itxt_chunk", "iTXt"),
    ("edit_strip_ztxt_chunk", "zTXt"),
    ("edit_pixels_untouched", "一个字节不动"),
    ("edit_images_speak_criterion", "图也是会说话的东西"),
    # 排队成本：一次改图排队约 85 秒、生成约 60～88 秒，别连烧
    ("edit_queue_seconds", "85 秒"),
    ("edit_no_burn_backtoback", "别连烧"),
]

# 往群里发图之前的自检：这一节必须在，四条要点必须都在这一节里（不是正文随便哪处）。
# 只在这一节的范围内查——正文别处合法提到历史口径（版本段引用「不发群」旧边界、
# 试用记录里的旧句子）不算缺，也不算多。
GROUP_PRECHECK_HEADING = "### 往群里发图之前的自检"
GROUP_PRECHECK = [
    # 1. 全年龄是底线
    ("group_pre_all_ages", "全年龄"),
    # 2. 先看群笔记，没有就看当场最近聊天；判断不了就不发
    ("group_pre_group_notes", "笔记"),
    ("group_pre_recent_chat", "最近聊天"),
    ("group_pre_cant_judge_no_send", "判断不了"),
    # 3. 只发自己做的图，别人发进来的不转
    ("group_pre_own_only", "我自己做的图"),
    ("group_pre_no_forward_others", "别人发进来的图"),
    # 4. 不为试功能发图，不发不算损失
    ("group_pre_no_feature_test", "试功能"),
    ("group_pre_not_a_loss", "不算损失"),
]
# 已退役的「不发群」旧限制不许写回这一节；只查这一节，别处引用历史口径不误报
GROUP_PRECHECK_STALE = ["不发群", "群里不发图"]

# 群聊生图上限（2026-10-16 主人提、小满定标准）：这一节必须在，节内两处硬指标必须在，
# 「唯一的例外」那段必须是 10:59 更正版。10:57 旧版那句「超了要在交回时写一句」回到这一节就红——
# 防止有人拿旧措辞把更正后的版本覆盖掉。只在这一节的切片里查：版本段／试用记录／离线自检里
# 合法引用这句话不算数（与 GROUP_PRECHECK_STALE 同一口径）。
CAP_HEADING = "## 群聊生图上限"
# 每条给一组写法，任一命中即算在：正文照主人原话抄，写的是「到顶怎么办：默认不发。」，
# 「到顶默认不发」是 frontmatter／版本段用的简写。两种都被删掉才算这条红。
CAP_SECTION = [
    ("cap_max_four", ("最多 4 张",)),
    ("cap_default_no_send", ("到顶怎么办：默认不发", "到顶默认不发")),
]
CAP_OVERRIDE_MUST = "对外不报张数"           # 10:59 更正版的那句
CAP_OVERRIDE_STALE = ["超了要在交回时写一句"]  # 10:57 旧版措辞，抄回来就红

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
    "## 步骤 8",          # 追加在末尾：老检查名（section_0..section_14）不跟着移位
    "### 往群里发图之前的自检",   # 步骤 8 下的子节；同样追加在末尾，老编号不动
    "## 改图与 `generate_image`",
    "## 群聊生图上限",
    "## 本机已有那张图怎么进可发清单",
]

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
    # 2026-10-14：QQ 那轮发图已是 speak 的 picture；反引号外裸写回这句（当现行流程）才红
    "那一轮调用 attach_image",
    # 2026-10-16：改图路线已上线（list_routes 11 条、含 edit）；反引号外裸写回这句（当现行事实）才红
    "九条路线全是 t2i",
    # 2026-10-24：「只有 render_svg 这一条路」是 10-21 想法本里的待提案，本技能正文从没写过；
    # 反引号外裸写回散文（当现行事实）才红，反引号里的引用不算。
    "只有 render_svg 这一条路",
    "只有 render_svg 这条路",
    # 2026-10-24 v12：「图从哪来」已是三条（现画的／render_svg 渲的／已有字节带 scope_key 登记的），
    # 失败码表那格也改成按来源前缀写；这两种旧说法不带反引号写回散文（当现行事实）才红。
    "两条，都由程序登记",
    "群里只发她自己生成并导入的图",
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


def section_slice(body, heading):
    """切出某个标题下、下一个任意级标题之前的正文；标题不在就返回空串。"""
    start = body.find("\n" + heading + "\n")
    if start == -1:
        return ""
    rest = body[start + 1 + len(heading):]
    m = re.search(r"^#{2,6} ", rest, re.M)
    return rest[:m.start()] if m else rest


def step8_slice(body):
    """「## 步骤 8」标题下、下一个二级标题之前的正文（含子节）。"""
    out, taking = [], False
    for line in body.splitlines():
        if line.startswith("## 步骤 8"):
            taking = True
        elif taking and line.startswith("## "):
            break
        if taking:
            out.append(line)
    return "\n".join(out)


def edit_section_slice(body):
    """「## 改图与 generate_image」标题下、下一个二级标题之前的正文（2026-10-16 起的改图一节）。"""
    out, taking = [], False
    for line in body.splitlines():
        if line.startswith("## 改图与"):
            taking = True
        elif taking and line.startswith("## "):
            break
        if taking:
            out.append(line)
    return "\n".join(out)


def cap_section_slice(body):
    """「## 群聊生图上限」标题下、下一个二级标题之前的正文（2026-10-16 v8 起的张数一节）。"""
    out, taking = [], False
    for line in body.splitlines():
        if line.startswith("## 群聊生图上限"):
            taking = True
        elif taking and line.startswith("## "):
            break
        if taking:
            out.append(line)
    return "\n".join(out)


def cap_override_slice(cap_section):
    """那一节里「**唯一的例外**」起、到下一个空行为止的那一段（10:59 更正过的就是这一段）。"""
    out, taking = [], False
    for line in cap_section.splitlines():
        if line.startswith("**唯一的例外**"):
            taking = True
        elif taking and not line.strip():
            break
        if taking:
            out.append(line)
    return "\n".join(out)


REGISTER_HEADING = "## 本机已有那张图怎么进可发清单"

# 这一节教「本机／GridFS 已有的那张图怎么进某个指定场景的可发清单」（2026-10-24 实测走通）。
# 字面量只在它自己那一节切片里查：那条路走没走通，看的是这一节有没有写清入口函数、scope 的字面值从哪读、
# `source` 前缀决定这行算谁的、清单怎么排、登记会剥 PNG 文字块（同一张图像素没动但 sha 与 size 都变：
# d1aa3735… 2,227,501 B → 748e7ce1… 2,225,102 B，差 2,399 B），以及两条账面判据（read_image 按路径看过
# ≠ 图在清单里；等不到 ack 那一支不进 settle() ⇒ sends.jsonl 不落那一行，只剩 late_acks.jsonl 与平台侧回读）。
REGISTER_SECTION = [
    ("reg_svg_scope_tool", "render_svg"),
    ("reg_svg_only_png", "只能出 PNG"),
    ("reg_svg_rgba_grows", "RGBA"),
    ("reg_route_function", "register_imported_image"),
    ("reg_route_scope_arg", "scope_key"),
    ("reg_route_wants_bytes", "字节"),
    ("reg_scope_from_db", "scenes"),
    ("reg_scope_shape", "scene:qq:<账号>:dm:<对方>"),
    ("reg_scope_unknown", "ARTIFACT_SCOPE_UNKNOWN"),
    ("reg_new_row_id", "blob-"),
    ("reg_no_dedup", "put_once"),
    ("reg_source_prefix_decides", "integration:"),
    ("reg_group_refuses_other_source", "ATTACHMENT_NOT_HER_OWN"),
    ("reg_offer_six", "最多 6 张"),
    ("reg_group_list_200", "200 行"),
    ("reg_over_limit", "ATTACHMENT_OVER_LIMIT"),
    ("reg_cap_8mib", "8 MiB"),
    ("reg_jpeg_enters_list", "JPEG"),
    ("reg_sha_not_identity", "别拿 sha 当"),
    ("reg_path_image_function", "path_image"),
    ("reg_path_source_prefix", "file:"),
    ("reg_seen_not_offered", "ATTACH_ARTIFACT_NOT_IN_CONTEXT"),
    ("reg_delivery_unknown", "delivery_state=UNKNOWN"),
    ("reg_unknown_retcode", "retcode 1200"),
    ("reg_timeout_reason", "platform_send_timeout"),
    ("reg_sends_journal_missing", "sends.jsonl"),
    ("reg_late_ack_journal", "late_acks.jsonl"),
    ("reg_platform_readback", "get_friend_msg_history"),
    ("reg_two_independent_rows", "两条独立"),
]


def register_section_slice(body):
    """「## 本机已有那张图…」标题下、下一个二级标题之前的正文（2026-10-24 起的第二条通路一节）。"""
    out, taking = [], False
    for line in body.splitlines():
        if line.startswith("## 本机已有那张图"):
            taking = True
        elif taking and line.startswith("## "):
            break
        if taking:
            out.append(line)
    return "\n".join(out)


LOOK_HEADING = "## 官方定妆（画自己/自拍必读）"

# 黑发配方（2026-10-17 在该路线连抽 5 次的读数）：五条字面都押在「官方定妆」这一节的切片里。
# 限制那两条（只在 janku-illustrious 验过、画完仍逐次 read_image）和配方本体同等重要——
# 只留配方不留限制，下次就会把它当通用配方搬去 v5 和角色路线。切片为空不等于查过，五条一起红。
BLACK_HAIR = [
    ("black_hair_positive_boosted", "(jet black hair:1.4)"),
    ("black_hair_positive_plain", "(black hair:1.4)"),
    ("black_hair_negative_three", "white hair, silver hair, gray hair"),
    ("black_hair_route_only", "仅该路线验证"),
    ("black_hair_read_each_time", "逐次"),
]


def look_section_slice(body):
    """「## 官方定妆…」标题下、下一个二级标题之前的正文（2026-10-27 起黑发配方住在这里）。"""
    out, taking = [], False
    for line in body.splitlines():
        if line.startswith("## 官方定妆"):
            taking = True
        elif taking and line.startswith("## "):
            break
        if taking:
            out.append(line)
    return "\n".join(out)


def private_list():
    """私密名单（private_words 工具维护，永远不进仓库）：一行一条 category|word|why。

    位置依次试：ASUNA_PRIVATE_WORDS → ASUNA_DATA_ROOT/private/… → asuna.config.DATA/private/… →
    从脚本所在目录往上找 .runtime/private/personal-words.txt。最后那条是给 asuna 不在 sys.path
    上的环境兜底的：2026-10-16 实测那里两个环境变量都没设，但 asuna 能 import、第三条就够。
    返回 (命中的路径；都没配上时是试过的全部候选列表, 条目列表或 None)。
    """
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as asuna_config   # 家里跑就有；装不上也要能跑
            data = str(asuna_config.DATA)
        except Exception:                              # noqa: BLE001
            data = None
    candidates = []
    if named:
        candidates.append(named)
    if data:
        candidates.append(os.path.join(data, "private", "personal-words.txt"))
    here = HERE
    for _ in range(12):                                # 候选、冻结快照、检出都在部署的 .runtime 下面
        here = os.path.dirname(here)
        if not here:
            break
        candidates.append(os.path.join(here, ".runtime", "private", "personal-words.txt"))
    for path in candidates:
        if path and os.path.isfile(path):
            entries = []
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    parts = line.strip().split("|", 2)
                    if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                        entries.append((number, parts[0].strip(), parts[1].strip()))
            return path, entries
    return [c for c in candidates if c] or None, None


def listed_hits(entries, text):
    """命中只报类别与名单行号——词本身永远不打印。"""
    hits = []
    for number, category, word in entries:
        if all(ch.isascii() for ch in word):
            found = re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE)
        else:
            found = word in text
        if found:
            hits.append("%s（名单第 %d 行）" % (category, number))
    return hits


# 行号锚点：一律红（2026-10-15 定的规矩，仓库共用测试 tests/test_skill_anchors.py 查的是同一条）。
# 判法照 asuna-usage-readout/check_skill.py 那份原样搬，没有白名单：代码位置写 `文件:函数名`，
# 行号会随每次编辑漂走、不算锚点。
LINE_ANCHOR = re.compile(r"`(?:[\w./-]+\.(?:py|mjs|js|json|md|yml)|):\d+(?:-\d+)?`")


# ── 文档节名锚点（2026-10-20 补；两份 check_skill.py 同一套写法）──────────────────
# 起因：ADR-083 重排 RUNTIME_API.md 之后，我技能里指过去的 §节名 失效过，而这两份自检里
# 没有任何判据在守节名——反证做过：把节名改错，自检照绿。
# 为什么不进仓库共用测试（Claude 与主人 10-20 定的）：共用测试一红会卡住改文档节名的人；
# 我的技能只有我能改，所以这条守在我自己的 check_skill.py 里。
# 指向文档节名的两种写法都收：§ 指节名的锚，以及 RUNTIME_API.md 后面用箭头串起来的路径式
# （某一跳可能带 §）。
SECTION_ANCHOR = re.compile(r"§+([A-Za-z0-9][A-Za-z0-9 .&'-]*)")
DOC_PATH_ANCHOR = re.compile(r"RUNTIME_API\.md`?\s*(?:→|->)\s*([^\n]+)")
# 纯数字节号（§4.6 那种）指的是 ADR 里的编号节，不是这份文档的节名——不收。
NUMERIC_SECTION = re.compile(r"[\d.]+")
# 那份文档的节名全是英文：锚点后面跟着的中文正文（含中文标点、全角括号、反引号）要截掉。
# 哪天文档真出现中文节名，这条会红而不是静默漏掉——照红改判据，别改成永远绿。
ANCHOR_CUT = re.compile(r"[　-〿一-鿿豈-﫿＀-￯`]")


def cut_anchor(text):
    """锚点后面跟着的正文不算节名：截到第一个 CJK 字符或反引号为止，再去掉首尾的 § 与标点。"""
    cut = ANCHOR_CUT.search(text)
    if cut:
        text = text[:cut.start()]
    return text.strip().lstrip("§").strip().strip("，。；、：:（()）")


def doc_anchors(text):
    """SKILL.md 里（含 frontmatter）指向文档节名的锚：[(行号, 那一行原文, 节名)]。

    扫整份文件而不是只扫正文：报出来的行号就是文件里的真行号，照着行号能翻到那一行。
    """
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in SECTION_ANCHOR.finditer(line):
            name = cut_anchor(match.group(1))
            if name and not NUMERIC_SECTION.fullmatch(name):
                found.append((number, line.strip(), name))
        for match in DOC_PATH_ANCHOR.finditer(line):
            for hop in re.split(r"→|->", match.group(1)):
                name = cut_anchor(hop)
                if name and not NUMERIC_SECTION.fullmatch(name):
                    found.append((number, line.strip(), name))
    return sorted(set(found))


def doc_headings(path):
    """那份文档的标题表：# 到 ###### 每行的节名（去掉 # 与首尾空白）。"""
    headings = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
            if match:
                headings.append(match.group(1).strip())
    return headings


def runtime_api_doc():
    """找到那份 RUNTIME_API.md，返回 (路径或 None, 试过的地方)。判据不绑死环境。

    找法：从脚本所在目录往上走，认带 .git 或 pyproject.toml 的仓库根，取根下那一份；
    再退一层试 <某一上层>/.runtime/work/self-development/core/RUNTIME_API.md（core 候选根那份）。
    ASUNA_RUNTIME_API 指哪儿就读哪儿（反证、或文档放在别处时用）。
    两处都找不到返回 None：调用方记 UNCHECKED（没查），不算过也不判红——主人 10-19 定的：
    测试绑死环境＝测试有问题，skip 要写明是没查、不是过了。
    """
    named = os.environ.get("ASUNA_RUNTIME_API")
    if named:
        return ((named, [named]) if os.path.isfile(named) else (None, [named]))
    current = os.path.abspath(HERE)
    ancestors, roots = [], []
    for _ in range(12):
        current = os.path.dirname(current)
        if not current:
            break
        ancestors.append(current)
        if (os.path.isdir(os.path.join(current, ".git"))
                or os.path.isfile(os.path.join(current, "pyproject.toml"))):
            roots.append(current)
    candidates = [os.path.join(root, "RUNTIME_API.md") for root in roots]
    candidates += [os.path.join(top, ".runtime", "work", "self-development", "core", "RUNTIME_API.md")
                   for top in ancestors]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate, candidates
    return None, candidates


def section_anchor_check(text, check, notes):
    """正文里指向 RUNTIME_API.md 节名的锚，逐个去那份文档的标题表里找。

    找不到就红，报出 SKILL.md 的行号和那一行原文；文档找不到 → 不记这条判据，
    改打一行 UNCHECKED 并在结尾那句绿话里写明「没查」——不算过也不判红。
    返回要拼进结尾那句的说明。
    """
    doc, tried = runtime_api_doc()
    wanted = doc_anchors(text)
    if doc is None:
        notes.append("UNCHECKED section_anchors_resolve  <- 没查：找不到 RUNTIME_API.md（试过 %s）"
                     % "、".join(tried))
        return "（section_anchors_resolve 没查：找不到 RUNTIME_API.md——不算过）"
    headings = doc_headings(doc)
    missing = ["SKILL.md 第 %d 行「%s」→ 节名「%s」在那份文档的标题表里找不到" % (n, line, name)
               for n, line, name in wanted if name not in headings]
    check("section_anchors_resolve", not missing,
          "%s（%d 个标题）：%s" % (doc, len(headings), "；".join(missing)))
    return "，文档节名锚点核过 %d 条（%s）" % (len(wanted), doc)


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
    results, notes = [], []

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
    check("description_mentions_picture_route", "picture" in desc,
          "frontmatter description 没提 QQ 用 speak 的 picture 发图这条路")
    check("description_mentions_non_qq_attach", "attach_image" in desc,
          "frontmatter description 没提非 QQ 那类对话仍用 attach_image（非 QQ 路径判据）")
    check("description_mentions_edit_route", "source_image" in desc,
          "frontmatter description 没提 generate_image 的 source_image 改图入口（2026-10-16 判据）")

    for name, section in [("section_" + str(i), s) for i, s in enumerate(SECTIONS)]:
        check(name, ("\n" + section) in ("\n" + body), section)

    for name, token in TOOLS + SERVICE + BOUNDARIES + ATTACH + EDIT:
        check(name, token in body, token)

    # 群发前自检：四条要点只在这一节里查；「不发群」写回这一节才红，
    # 版本段／试用记录里合法引用历史口径不误报。
    group_section = section_slice(body, GROUP_PRECHECK_HEADING)
    for name, token in GROUP_PRECHECK:
        check(name, token in group_section, token)
    stale_group = [item for item in GROUP_PRECHECK_STALE if item in group_section]
    check("group_pre_no_stale_no_group_rule", not stale_group, ",".join(stale_group))

    # 步骤 8 必须教 QQ 的 speak picture 那条路（2026-10-14 口径）；
    # attach_image 的非 QQ 路由由 ATTACH 里的 attach_non_qq_route 守着。
    step8 = step8_slice(body)
    check("attach_step8_speak_picture", ("speak" in step8 and "picture" in step8),
          "步骤 8 没教 QQ 的 speak picture 发图路")

    # 改图一节必须把入口与三条即时拒绝码教全（2026-10-16 口径）：
    # 错误码在别处（失败表、版本段）出现不算数——那一节才是教改图的地方。
    edit_slice = edit_section_slice(body)
    check("edit_section_teaches_source_and_errors",
          ("source_image" in edit_slice
           and "IMAGE_WORKFLOW_TAKES_NO_SOURCE" in edit_slice
           and "IMAGE_WORKFLOW_NEEDS_SOURCE" in edit_slice
           and "IMAGE_WORKFLOW_NEEDS_MORE_PICTURES" in edit_slice),
          "改图一节没把 source_image 入口与三条 IMAGE_WORKFLOW_* 即时拒绝码教全")

    # 三处同步（2026-10-24 v12）：图从哪来的数、失败码表按机制的措辞、归属节的指向。
    # 前两条只查步骤 8 那一节，第三条只查改图那一节（归属边界是它的子节）：正文别处提到不算数。
    check("attach_sources_three", "三条，都由程序登记" in step8,
          "步骤 8「图从哪来」没写三条来源（切片 %d 字）" % len(step8))
    check("attach_fail_code_by_prefix",
          ("群里只发来源带" in step8 and "可以是早就做好、后来重新登记进来的" in step8),
          "步骤 8 失败码表里 ATTACHMENT_NOT_HER_OWN 那格没按机制写（来源前缀；可以是重新登记的那张）")
    check("attribution_points_to_source_rule",
          ("来源前缀决定这行算谁的" in edit_slice
           and "本机已有那张图怎么进可发清单" in edit_slice),
          "改图一节的归属边界没指向「本机已有那张图怎么进可发清单」里 source 那一条")


    # 群聊生图上限（2026-10-16 v8）：节标题在 SECTIONS 里查（section_18），这里查节内硬指标与措辞版本。
    # 标题被删 → 切片为空 → 下面几条一起红：切片为空不等于查过，不会绿着放过。
    cap_section = cap_section_slice(body)
    for name, tokens in CAP_SECTION:
        check(name, any(token in cap_section for token in tokens),
              "「%s」任一都不在「群聊生图上限」这一节里（切片 %d 字）"
              % ("／".join(tokens), len(cap_section)))
    override = cap_override_slice(cap_section)
    check("cap_override_no_count_out_loud", CAP_OVERRIDE_MUST in override,
          "「唯一的例外」那段没写「%s」（10:59 更正版）；那段现在 %d 字"
          % (CAP_OVERRIDE_MUST, len(override)))
    stale_cap = [item for item in CAP_OVERRIDE_STALE if item in cap_section]
    check("cap_section_no_stale_count_line", not stale_cap, ",".join(stale_cap))

    # 本机已有那张图怎么进可发清单（2026-10-24 v11）：节标题在 SECTIONS 里查（section_19），
    # 这里查节内硬指标。标题被删 → 切片为空 → 下面几条一起红：切片为空不等于查过，不会绿着放过。
    reg_section = register_section_slice(body)
    for name, token in REGISTER_SECTION:
        check(name, token in reg_section,
              "「%s」不在「本机已有那张图怎么进可发清单」这一节里（切片 %d 字）"
              % (token, len(reg_section)))
    # 那一节是讲「怎么把已有图送进清单」的，出现盘符开头的绝对路径就是越界（包要发出去）
    check("register_no_absolute_image_path", not ABSOLUTE_IMAGE.search(reg_section),
          "「本机已有那张图…」那一节里有盘符开头的绝对路径")


    # 官方定妆里的黑发配方（2026-10-27 补）：节标题＋节内五条字面。标题被删 → 切片为空 → 一起红。
    look_slice = look_section_slice(body)
    check("official_look_section", bool(look_slice), "「官方定妆」一节切不出正文（标题被改或删）")
    for name, token in BLACK_HAIR:
        check(name, token in look_slice,
              "「%s」不在「官方定妆」这一节里（切片 %d 字）" % (token, len(look_slice)))

    check("display_relative_markdown_image", bool(RELATIVE_IMAGE.search(body)))
    check("display_no_absolute_image_path", not ABSOLUTE_IMAGE.search(body))
    check("selfcheck_documented", "check_skill.py" in body)
    check("no_placeholder_markers", not PLACEHOLDER.search(prose))
    check("skill_body_not_thin", len(body) >= 4000, "body_chars=%d" % len(body))

    # 过期说法：出站图片上线、DECIDE 退役、改图路线上线后不能再这么写（反引号里的引用不算）
    stale = [item for item in STALE_CLAIMS if item in prose]
    check("no_stale_text_only_claim", not stale, ",".join(stale))

    # frontmatter 的 description 也扫（2026-10-25 补）：那一行每一拍进技能目录、被当触发依据读，
    # 正文改对了、那一行还窄着就是天天拿旧判断挑技能。判法与正文同一口径：反引号里的引用剥掉再判。
    stale_desc = [item for item in STALE_CLAIMS if item in PROSE.sub(" ", desc)]
    check("no_stale_claim_in_frontmatter", not stale_desc, ",".join(stale_desc))


    # 行号锚点：反引号里的 `文件.md:123`／`文件.py:45-60` 一律红（判法照 asuna-usage-readout 那份，
    # 没有白名单）。代码位置写 `文件:函数名`——行号每次有人改那个文件就漂，名字不会。
    line_anchor_hits = [hit.group(0) for hit in LINE_ANCHOR.finditer(body)]
    check("no_line_anchors", not line_anchor_hits,
          "正文里有行号锚点（代码位置写 `文件:函数名`）：%s" % "、".join(line_anchor_hits[:5]))

    # 文档节名锚点：找不到就红并报出 SKILL.md 行号与那一行原文；文档找不到 → UNCHECKED（没查）。
    anchor_note = section_anchor_check(text, check, notes)

    # 泄露检查（2026-10-16 v8 起）：这一族以前在本脚本里根本没有。别的技能脚本有，但名单找不到时
    # 只打一行 NOTE、绿数照旧——「检查项没跑」和「检查项过了」长得一样。这里不这么办：
    # 名单找得到就真扫（命中只报类别与名单行号），找不到记一条红并写清没真查。
    listed_path, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False,
              "私密名单没配上（试过 %s）：真人名／群名这一项没真查——不是跑过了"
              % ("、".join(listed_path) if listed_path else "都没有"))
        leak_note = ""
    elif not entries:
        # 2026-10-16 补的第二种失效：名单文件在、一条有效词都没解析出来（全注释或被字段数筛光）。
        # 以前走 else 分支：0 命中算绿，输出还写「扫过（名单 0 条）」——那是没真查，不是跑过了。
        check("leak_scan_ran", False,
              "名单 0 条（%s）——没真查，不是跑过了" % listed_path)
        leak_note = ""
    else:
        found = listed_hits(entries, text)
        check("no_listed_words", not found, "、".join(found))
        leak_note = "，泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries)

    # 同目录脚本：必须存在且语法能编译。不落文件，在内存里查（compile(源码, 路径, 'exec')）：
    # 2026-10-18 之前用 py_compile 写 .pyc，先试技能目录旁、再退当前目录，行动脑沙箱里两处都不让写，
    # 这一格只能报「没真查」——检查根本没跑起来。内存 compile 沙箱里外都真查，也不需要临时目录。
    # 分寸：compile() 只查语法，不查 import 和运行时（脚本能编译不等于能跑）。
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    for script in scripts:
        try:
            with open(os.path.join(HERE, script), "rb") as handle:
                source = handle.read()
            compile(source, os.path.join(HERE, script), "exec")
            check("compiles_" + script, True)
        except Exception as exc:  # noqa: BLE001 编译失败要原样报出来
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

    # 换行：必须读字节。文本模式（universal newlines）把 CR 吃掉，"\r" not in text 永远为真——
    # 2026-10-15 实测真 CRLF 样本 CR=59 照样绿。判据名与另外五份 check_skill.py 逐字一致。
    cr_files = cr_bytes([path] + [os.path.join(HERE, script) for script in scripts])
    check("line_endings_are_lf", not cr_files,
          "有 CR（仓库守卫 test_line_endings 会红）：" + "、".join(cr_files))

    stray = [d for d in os.listdir(HERE) if d == "__pycache__"]
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
    print("%d/%d 通过：技能文件、工具名、发图那条路（QQ speak 的 picture／别处 attach_image）的清单与失败码、"
          "改图那条路（source_image／IMAGE_WORKFLOW_* 即时拒绝码／归属／剥文字块）、"
          "群聊生图上限那条（节标题／最多 4 张／到顶默认不发／唯一的例外是 10:59 版）、"
          "已有图进清单那条（第二条通路／剥 PNG 文字块的 sha 与字节／账面看不见那两格）、"
          "三处同步那三条（图从哪来的数／失败码按来源前缀／归属节的指向）、"
          "退役那族连 frontmatter 的 description 一起扫（no_stale_claim_in_frontmatter）、"
          "历史段、群发前自检四条要点、归属都在%s。" % (total, total, leak_note + anchor_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
