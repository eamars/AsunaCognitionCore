#!/usr/bin/env python3
"""asuna-turret-frame 的零依赖离线自检（除了读头那一格要 PyYAML）。

查四件事：
1. 头：用真 YAML 解析器读（yaml.safe_load，取第一个 --- 到下一个 --- 之间），不用宽松正则；解析抛错、
   name 与目录名不一致、description 为空、值里带 ASCII「冒号＋空格」，各记一条红。没有 PyYAML 记红（没真查不许像过了）。
2. 正本要点的字面都在（五个读口、控制面全在 POST、不自报固件版本、认机器三样、同一枚流、原位会漂、基线现读；
   11-21 起另加两组：DATE 钉第二节「`Date` 头是真 UTC＋时区现读别背常数」那一格，
   FRAME 钉第一节「取帧那一趟的交回形状＋当场发得出去」那三条命令句。两组各钉各的——
   删掉哪一格只红那一组的钉，互为反证，不合成一发；一枚钉只钉它那半句字面，同一块里另半句被删不红）；
3. 不带别人的个人信息：私密名单命中只报类别和名单行号；名单配不上或 0 条记红；
   另扫「像 IP 的字面」，技能里不写设备地址；
4. 换行是 LF（读字节数 CR）、脚本能编译（compile 在内存里查，只查语法）。

用法：python3 check_skill.py [SKILL.md 路径]；退出码 0 = 全绿。
"""
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

PINS = [
    ("pin_five_get_routes", "`/api/health`、`/api/video`、`/api/video/state`、`/api/selection`、`/api/state`"),
    ("pin_ws", "WebSocket `/ws`"),
    ("pin_control_all_post", "控制面全在 POST"),
    ("pin_pose_read_ways", "`/ws` 只 `recv`；或裸 `GET /api/state`"),
    ("pin_no_firmware_report", "这台不自报固件版本"),
    ("pin_identity_three", "`camera_id` ＋ `epoch` ＋ release 路径"),
    ("pin_identity_belongs_camera", "属于 camera，不属于整机"),
    ("pin_other_device_identity", "别把另一台设备（OpenTrickler）的设备号和固件版本贴到这台身上"),
    ("pin_same_stream", "同一枚流"),
    ("pin_pose_drifts", "「原位」会漂"),
    ("pin_baseline_read_now", "现读一遍当基线"),
    ("pin_report_delta", "报 yaw、pitch 各自的差值"),
    ("pin_no_old_baseline", "不许拿上一次记的那组数当原位"),
    ("pin_no_drift_as_mine", "不把漂移记成自己干的"),
    ("pin_yaml_colon_rule", "不写 ASCII 冒号加空格"),
    # DATE 组（11-21）：第二节 `Date` 头／时区那一格。旧字面「Date 偏了约 5 小时」是按 UTC+8
    # 换算错的产物，这三枚钉的就是改后的新形状：真 UTC ＋ 那句是我的假事实 ＋ 现读时区别背常数。
    ("pin_date_header_true_utc", "`Date` 头是真 UTC"),
    ("pin_date_old_five_hours_is_my_math", "换算才得出的**假事实**"),
    ("pin_tz_read_now_no_constant", "换算前先现读本机时区，别背常数"),
    # FRAME 组（11-21）：第一节取帧那一趟的交回形状那三条命令句（绝对路径＋共用存储、
    # artifact_id＋kind、当拍 speak picture 不许隔拍）只管这一本取帧这一族。
    ("pin_frame_return_scope_only_this", "只管这一本取帧这一族"),
    ("pin_frame_abs_path_and_sharing", "交回必须带帧在盘上的绝对路径，并写明那块存储是不是长期共用"),
    ("pin_frame_artifact_id_and_kind", "交回必须报 `artifact_id` ＋ `kind`"),
    ("pin_frame_send_same_turn", "`read_image` 之后当拍用 `speak` 的 picture，不许隔拍"),
    ("pin_frame_refusal_literal", "不在 image_artifacts_from_program 里"),
]
IP_LIKE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])")


def private_list():
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    cands = [named] if named else []
    data = os.environ.get("ASUNA_DATA_ROOT")
    if data:
        cands.append(os.path.join(data, "private", "personal-words.txt"))
    here = HERE
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        cands.append(os.path.join(here, ".runtime", "private", "personal-words.txt"))
    for path in cands:
        if path and os.path.isfile(path):
            entries = []
            with open(path, encoding="utf-8") as h:
                for n, line in enumerate(h, 1):
                    parts = line.strip().split("|", 2)
                    if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                        entries.append((n, parts[0].strip(), parts[1].strip()))
            return path, entries
    return None, None


def listed_hits(entries, text):
    hits = []
    for n, cat, word in entries:
        if all(c.isascii() for c in word):
            found = re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.I)
        else:
            found = word in text
        if found:
            hits.append("%s（名单第 %d 行）" % (cat, n))
    return hits


def head_text(text):
    """装载侧口径：第一个 --- 到下一个 --- 之间。"""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    return text[3:end].strip("\n"), text[end + 4:]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SKILL.md")
    results, notes = [], []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    with open(path, "rb") as h:
        raw = h.read()
    check("line_endings_are_lf", b"\r" not in raw, "有 CR 字节")
    text = raw.decode("utf-8")
    head, body = head_text(text)
    check("frontmatter_delimited", head is not None)
    fields = None
    try:
        import yaml
        try:
            fields = yaml.safe_load(head or "")
            check("frontmatter_real_yaml_parses", isinstance(fields, dict),
                  "解析结果不是映射（YAML %s）" % yaml.__version__)
        except Exception as exc:  # noqa: BLE001
            check("frontmatter_real_yaml_parses", False, "%s: %s" % (type(exc).__name__, str(exc)[:200]))
    except ImportError:
        check("frontmatter_real_yaml_parses", False, "这台机没有 PyYAML——没真查，不是过了")
    fields = fields if isinstance(fields, dict) else {}
    check("name_matches_directory", fields.get("name") == EXPECTED_NAME, "name=%r dir=%r" % (fields.get("name"), EXPECTED_NAME))
    desc = fields.get("description")
    check("description_is_nonempty_string", isinstance(desc, str) and len(desc) >= 120,
          "len=%s" % (len(desc) if isinstance(desc, str) else desc))
    raw_values = [ln.split(":", 1)[1] for ln in (head or "").splitlines() if re.match(r"^[A-Za-z_][\w-]*:", ln)]
    check("no_ascii_colon_space_in_values", not any(": " in v.strip() for v in raw_values), "头里某个值带「冒号＋空格」")
    check("scene_kinds_present", isinstance(fields.get("scene_kinds"), list), repr(fields.get("scene_kinds")))
    for name, token in PINS:
        check(name, token in body, token)
    check("no_ip_like_literals", not IP_LIKE.search(text), "正文出现像 IP 的字面——设备地址不进技能")
    check("no_placeholder_markers", not re.search(r"\bTODO\b|\bTBD\b|\bFIXME\b", body))
    check("no_literal_ids", not re.search(r"#\d", body))

    lp, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False, "私密名单没配上——没真查，不是跑过了")
    elif not entries:
        check("leak_scan_ran", False, "名单 0 条——没真查")
    else:
        found = listed_hits(entries, text)
        check("no_listed_words", not found, "、".join(found))
        notes.append("泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries))

    for script in sorted(f for f in os.listdir(HERE) if f.endswith(".py")):
        try:
            with open(os.path.join(HERE, script), "rb") as h:
                src = h.read()
            compile(src, script, "exec")
            check("compiles_" + script, b"\r" not in src, "有 CR 字节")
        except Exception as exc:  # noqa: BLE001
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

    total = len(results)
    failed = [n for n, ok, _ in results if not ok]
    for n, ok, d in results:
        if not ok and d:
            print("FAIL %s  <- %s" % (n, d))
    for line in notes:
        print("NOTE", line)
    if failed:
        print("%d/%d 通过，失败：%s" % (total - len(failed), total, ", ".join(failed)))
        return 1
    print("%d/%d 通过：头用真 YAML 解析器读过，正本要点都在。" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
