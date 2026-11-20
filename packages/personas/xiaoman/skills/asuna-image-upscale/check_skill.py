#!/usr/bin/env python3
"""asuna-image-upscale 的零依赖离线自检。

这份技能是「小图扩大怎么走」的正本，所以这里只查它该钉住的东西，不查引擎本身：
1. 头：用真 YAML 解析器读（yaml.safe_load，取第一个 --- 到下一个 --- 之间），不用宽松正则；解析抛错、
   name 与目录名不一致、description 太短、值里带 ASCII「冒号＋空格」，各记一条红；没有 PyYAML 记红
   （没真查不许像过了）。scene_kinds 必须是 [home, group, dm]——这一本要让群和私聊那一拍也读得到，
   而一旦离开 home，仓里那道闸（tests/test_skill_scenes.py）要求这份自检带上泄露扫描并且绿。
2. 正本要点的字面都在：模型档与本机没有的那一档、四个坑、对外默认档、8 MiB 那把尺、edit 那一枪的形状、
   全身扩展格、对外三词、验收三发的读数。
3. 家规：正文无日期形状（日期与来路只进 CHANGELOG）、不带别人的个人信息、无占位符、无字面任务号／图号、
   「只补角」只许出现在否定句里、裸的 7 位以上数字串（账号形状）只许待在带 personal-scan 标记的那一行。
4. 泄露扫描：本目录每个文件都扫本机私密名单；名单配不上或 0 条 → leak_scan_ran 红，「没跑」不许长得像「过了」。
5. 换行是 LF（读字节数 CR）；CHANGELOG 有首条。

不跑引擎、不联网、不碰数据库、不花生图配额。

用法：python3 check_skill.py [SKILL.md 路径]；退出码 0 = 全绿。
"""
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 一、哪一格走哪条",
    "## 二、标准流程（对外就发这一档）",
    "## 三、引擎、命令与模型档",
    "## 四、坑（写死）",
    "## 五、edit 那一枪的已知形状（`qwen-image-2.1-edit`）",
    "## 六、全身扩展格（穷人版 outpaint）",
    "## 七、对外怎么说（口径固定）",
    "## 八、验收读数（这一本自己跑过的三发）",
    "## 九、没核实／没做的",
]

PINS = [
    # 引擎与命令
    ("pin_entry_run_sr", "`run_sr.py`"),
    ("pin_engine_dir_env", "${ASUNA_DATA}\\work\\local-user\\realesrgan_ncnn_vulkan_"),
    ("pin_abs_m_flag", "把 `-m <模型目录>` 用绝对路径补在最前"),
    ("pin_rc_always_zero", "**`run_sr.py` 自己的进程退出码永远是 0**"),
    ("pin_read_exit_line", "`EXIT: <码>`"),
    ("pin_default_model_explicit", "这一本的对外默认是显式 `-n realesrgan-x4plus`"),
    ("pin_exe_own_default", "exe 自己的默认是 `realesr-animevideov3`"),
    ("pin_model_anime", "`realesrgan-x4plus-anime`"),
    ("pin_model_animevideov3", "`realesr-animevideov3` 的 x2／x3／x4"),
    ("pin_no_realesrnet_weight", "**`realesrnet-x4plus`：usage 里列着，本机没这一档（盘上没对应权重），选它直接失败。**"),
    ("pin_version_is_provenance", "版本号 `v0.2.5.0` 是来历、不是实测"),
    ("pin_version_not_in_binary", "exe 里搜 `0.2.5.0`／`v0.2.5` 各 0 命中"),
    # 四个坑
    ("pin_m_cwd_trap", "不带 `-m` 时模型目录按**当前目录**找"),
    ("pin_v_is_verbose", "`-v` 是 **verbose**，不是选显卡"),
    ("pin_g_is_gpu", "选卡是 `-g`"),
    ("pin_no_cpu_mode", "**没有 CPU 模式**"),
    ("pin_batch_dirs", "批处理是 `-i 目录 -o 目录`"),
    ("pin_alpha_output_name", "**输入带 alpha（RGBA 的 PNG 常这样）时，exe 把产物写成 `<我给的名字>.png`"),
    ("pin_alpha_literal_shape", "`<out>.jpg.png`"),
    ("pin_alpha_drop_rgb_first", "先 `convert(\"RGB\")` 去 alpha 再跑"),
    ("pin_find_product_by_real_name", "别只按 `-o` 给的那串名字找"),
    # 对外档与出站尺
    ("pin_default_egress_tier", "`-s 2 -f jpg`"),
    ("pin_8mib_ruler", "**出站那把尺是 8 MiB**"),
    ("pin_press_before_group", "**发群先压**"),
    ("pin_4x_bytes", "11,206,870 字节（＝10.7 MiB）"),
    ("pin_4x_only_on_request", "4x 全尺寸原物只在对方明说要原图时给"),
    # edit 那一枪
    ("pin_edit_only_for_corner", "只在要修缺角／局部时开"),
    ("pin_edit_no_mask", "**没有 mask 参数**"),
    ("pin_edit_is_full_redraw", "**整图重描**"),
    ("pin_edit_diff_readings", "目标区 meanAbsDiff **10.85**"),
    ("pin_edit_non_target", "非目标区 **4.99**"),
    ("pin_edit_corner_not_local", "「只补角」不成立"),
    ("pin_edit_locks_size", "**输出锁源尺寸**"),
    ("pin_edit_hands_drift", "**手型和线条会漂**"),
    ("pin_edit_negative_useless", "**CFG 1 这条路线 `negative_prompt` 无效**"),
    ("pin_edit_positive_orders", "禁令一律写成正向指令"),
    ("pin_edit_seconds_order", "57156"),
    ("pin_black_border_is_phenomenon", "部分构图会出现"),
    ("pin_read_image_before_handoff", "`read_image` 把那个目标本身再看一遍"),
    # 全身扩展格
    ("pin_fullbody_pillow", "先用 pillow 把原图拼贴进一张竖版画布（原图居上、下半留白）"),
    ("pin_fullbody_beats_lock", "绕开了 edit「锁源尺寸」那个缺口"),
    ("pin_true_outpaint_other_slot", "**真 outpaint（无 mask 参数那种往四周扩）超分治不了——超分只放大、不添画布；那是另一格，别混写。**"),
    # 对外口径
    ("pin_three_words", "**「超分＋整图重描＋补角」**"),
    ("pin_no_fidelity_promise", "不保忠于原稿"),
    ("pin_no_extra_corner_claim", "别带上「补角」"),
    ("pin_no_promise_untouched", "不许说成「只补角」「只放大」「原图不动」"),
    ("pin_receipt_is_not_picture", "不拿引擎回执、文件存在、rc 当「图是对的」"),
    # 验收读数
    ("pin_acceptance_4x", "800×800 RGBA PNG，803,559 字节"),
    ("pin_acceptance_alpha_run", "4,390,506 字节"),
    ("pin_acceptance_jpg_run", "1,742,302 字节"),
    ("pin_acceptance_elapsed", "`ELAPSED_SEC: 3.59`"),
    # 未核实
    ("pin_unverified_egress", "没在 QQ 侧实测过落点字节"),
    ("pin_unverified_fullbody", "这一版没有重跑一遍拼图＋补下半身"),
    ("pin_read_now_on_other_machine", "换一台机要现读，不照抄"),
]

PERSONAL_TOKENS = ["主人", "金主", "姐姐", "大姐", "爹", "清尘"]
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")
LITERAL_ID = re.compile(r"#\d")
ID_SHAPES = [("task-", "任务号"), ("blob-", "图号"), ("in-ep-", "事件号")]
DATE_SHAPES = [
    (r"20\d{2}-\d{1,2}-\d{1,2}", "ISO 日期"),
    (r"20\d{2}年", "年份"),
    (r"(?<![\d.])\d{1,2}月\d{1,2}日", "几月几日"),
    (r"(?<![\d.])\d{1,2}[-/]\d{1,2}[日号]", "几号"),
    (r"(?<![\d:])\d{1,2}[-/]\d{1,2}(?![\d:])", "月-日 形状"),
]
# 裸的 7 位以上数字串＝账号形状（推公开仓那道闸同款），只许待在带标记的那一行
DIGITS = re.compile(r"(?<![0-9])[0-9]{7,}(?![0-9])")
OK_MARK = re.compile(r"personal-scan: " + "ok" + r"(?![A-Za-z0-9_])")
HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{7,40}(?![0-9A-Fa-f])")
MARKER_LINE = "<!-- personal-scan: ok"


def private_list():
    """本机私密名单（private_words 工具维护，不进仓库）。返回 (路径或候选, [(行号, 类别, 词)])。"""
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as asuna_config
            data = str(asuna_config.DATA)
        except Exception:                                       # noqa: BLE001 没装 asuna 也要能跑
            data = None
    candidates = []
    if named:
        candidates.append(named)
    if data:
        candidates.append(os.path.join(data, "private", "personal-words.txt"))
    here = HERE                                                 # 兜底：往上找 <部署根>/.runtime/private/
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


def head_text(text):
    """装载侧口径：第一个 --- 到下一个 --- 之间。"""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    return text[3:end].strip("\n"), text[end + 4:]


def dir_files():
    return sorted(os.path.join(HERE, f) for f in os.listdir(HERE)
                  if os.path.isfile(os.path.join(HERE, f)) and f.endswith((".md", ".py")))


def bare_digit_lines(text):
    """裸的 7 位以上数字串所在行号（sha／hex 串内部的不算；带 personal-scan 标记的行放行）。"""
    flagged = []
    for number, line in enumerate(text.splitlines(), 1):
        if OK_MARK.search(line):
            continue
        hex_spans = [m.span() for m in HEX_RUN.finditer(line) if any(c.isalpha() for c in m.group())]
        for m in DIGITS.finditer(line):
            s, e = m.span()
            if any(a <= s and e <= b for a, b in hex_spans):
                continue
            flagged.append((number, m.group()))
    return flagged


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SKILL.md")
    results, notes = [], []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        raw = open(path, "rb").read()
    except OSError as exc:                                      # noqa: BLE001
        print("读不到 SKILL.md：%s" % exc)
        print("0/1 通过，失败：read_skill")
        return 1
    text = raw.decode("utf-8")
    head, body = head_text(text)
    check("frontmatter_delimited", head is not None, "缺 frontmatter 或没收尾")

    fields = None
    try:
        import yaml
        try:
            fields = yaml.safe_load(head or "")
            check("frontmatter_real_yaml_parses", isinstance(fields, dict),
                  "解析结果不是映射（YAML %s）" % yaml.__version__)
        except Exception as exc:                                # noqa: BLE001
            check("frontmatter_real_yaml_parses", False, "%s: %s" % (type(exc).__name__, str(exc)[:200]))
    except ImportError:
        check("frontmatter_real_yaml_parses", False, "这台机没有 PyYAML——没真查，不是过了")
    fields = fields if isinstance(fields, dict) else {}

    check("name_matches_directory", fields.get("name") == EXPECTED_NAME,
          "name=%r 目录=%s" % (fields.get("name"), EXPECTED_NAME))
    desc = fields.get("description")
    check("description_is_nonempty_string", isinstance(desc, str) and len(desc) >= 120,
          "len=%s" % (len(desc) if isinstance(desc, str) else desc))
    for token in ("run_sr.py", "8 MiB", "超分＋整图重描＋补角"):
        check("description_says_" + token.replace(".", "_").replace(" ", "_"),
              isinstance(desc, str) and token in desc, "描述里少了 %s" % token)
    raw_values = [ln.split(":", 1)[1] for ln in (head or "").splitlines() if re.match(r"^[A-Za-z_][\w-]*:", ln)]
    check("no_ascii_colon_space_in_values", not any(": " in v.strip() for v in raw_values),
          "头里某个值带「冒号＋空格」，装载侧会抛 YAMLParseError")
    kinds = fields.get("scene_kinds")
    check("scene_kinds_is_allowed_list", isinstance(kinds, list) and set(kinds) <= {"home", "group", "dm"}
          and bool(kinds), "scene_kinds=%r（能写的只有 home／group／dm，且要写成列表）" % (kinds,))
    check("scene_kinds_reaches_group_and_dm", isinstance(kinds, list) and {"group", "dm"} <= set(kinds),
          "scene_kinds=%r——这份要让群和私聊那一拍读得到" % (kinds,))

    for section in SECTIONS:
        check("section_" + section.replace(" ", "_")[:44], section in text, "少了这一节：" + section)
    for name, token in PINS:
        check(name, token in body, "少了这一条：" % () + token)

    corner_lines = [no for no, line in enumerate(body.splitlines(), 1) if "只补角" in line]
    bad_corner = [no for no, line in enumerate(body.splitlines(), 1)
                  if "只补角" in line and not any(w in line for w in ("不成立", "不许", "别说", "不许说成"))]
    check("only_corner_claim_is_negated", not bad_corner, "「只补角」出现在没有否定词的行：%s" % bad_corner[:3])
    check("only_corner_claim_present", bool(corner_lines), "正文一次都没提「只补角」——那条口径是这条技能的核心禁令")

    for pattern, label in DATE_SHAPES:
        hit = re.search(pattern, body)
        check("no_date_" + label, not hit, "正文出现%s（%r）——日期写进 CHANGELOG"
              % (label, hit.group(0) if hit else ""))
    for word in ("来路", "实测于", "拍板"):
        check("no_provenance_" + word, word not in body, "正文写了「%s」——来历挪进 CHANGELOG" % word)
    for prefix, label in ID_SHAPES:
        check("no_id_" + label, prefix not in body, "正文带了%s（%s 形状）——只写读数，不带号" % (label, prefix))
    check("no_literal_ids", not LITERAL_ID.search(body), "正文用了字面编号 #N")
    check("no_placeholders", not PLACEHOLDER.search(text), "有 TODO／TBD／FIXME 残留")
    for token in PERSONAL_TOKENS:
        check("no_personal_" + token, token not in body, "正文出现「%s」" % token)
    digit_lines = bare_digit_lines(body)
    check("no_bare_long_digits", not digit_lines,
          "正文有裸的 7 位以上数字串（账号形状）：%s——加千分位，或在那一行加 personal-scan 标记"
          % "、".join("第%d行:%s" % item for item in digit_lines[:3]))
    check("marker_line_present_when_engine_named",
          ("realesrgan_ncnn_vulkan_" not in body) or (MARKER_LINE in body),
          "正文写了引擎目录却没带 personal-scan 标记")

    cr_files = []
    for one in dir_files():
        count = open(one, "rb").read().count(b"\r")
        if count:
            cr_files.append("%s（%d 个 CR）" % (os.path.basename(one), count))
    check("no_crlf", not cr_files, "有 CR：" + "、".join(cr_files))
    try:
        compile(open(os.path.join(HERE, "check_skill.py"), "rb").read(), "check_skill.py", "exec")
        check("self_compiles", True)
    except Exception as exc:                                    # noqa: BLE001
        check("self_compiles", False, "%s: %s" % (type(exc).__name__, exc))

    notes_path = os.path.join(HERE, "CHANGELOG.md")
    change = open(notes_path, encoding="utf-8").read() if os.path.isfile(notes_path) else ""
    check("changelog_exists", bool(change), "缺 CHANGELOG.md")
    check("changelog_first_entry", change.startswith("# CHANGELOG · " + EXPECTED_NAME) and "新建" in change[:1500],
          "CHANGELOG.md 缺首条（标题行＋「新建」那一条）")

    source, entries = private_list()
    check("leak_scan_ran", bool(entries),
          "读不到本机私密名单（试了 %s）——这一格不许「没跑」长得像「过了」"
          % ("、".join(source) if isinstance(source, list) else repr(source)))
    leak_note = ""
    if entries:
        bad = []
        for one in dir_files():
            hits = listed_hits(entries, open(one, encoding="utf-8", errors="ignore").read())
            if hits:
                bad.append("%s：%s" % (os.path.basename(one), "、".join(hits)))
        check("no_listed_words", not bad, "命中本机私密名单：" + "；".join(bad))
        leak_note = "，泄露扫描真扫（名单 %d 条）" % len(entries)
    else:
        leak_note = "（泄露扫描没跑：名单读不到）"

    if any(d == "__pycache__" for d in os.listdir(HERE)):
        notes.append("NOTE 技能目录里有 __pycache__，发布前清掉")

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
    print("%d/%d 通过：头用真 YAML 解析器读过、三节口径与验收读数齐全、正文无日期无来历无个人信息%s。"
          % (total, total, leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
