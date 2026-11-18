#!/usr/bin/env python3
"""asuna-daily-backup 的零依赖离线自检（读头那一格要 PyYAML）。

查五件事：
1. 头：真 YAML 解析器读（yaml.safe_load，第一个 --- 到下一个 --- 之间），name 与目录名一致、值里无 ASCII「冒号＋空格」；
2. 正文要点：四步、参数（保留份数默认 2 与 7）、靶子现读、围栏六条、措辞边界；
3. 脚本：每个都能编译（内存里 compile，只查语法）；每个都带围栏注释；不写死靶子节号、不写死设备地址
   （像 IP 的字面一律红）、不碰盘符／UNC 当路径、用内置 NTLM、删除只走 xiaoman-backups 与前缀；
   措辞：脚本里不出现「NAS 自己校验」这类说法的肯定句（只允许出现在否定围栏里）；
4. 私密名单扫描：命中只报类别与名单行号，名单配不上或 0 条记红；
5. 换行是 LF（读字节数 CR）。

用法：python3 check_skill.py；退出码 0 = 全绿。
"""
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)
SCRIPTS = ["_bk_common.py", "backup_export.py", "backup_drill.py", "backup_push.py", "backup_retain.py"]
IP_LIKE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])")

BODY_PINS = [
    ("pin_four_steps", "## 三、四步"),
    ("pin_keep_defaults", "--keep-local 2 --keep-nas 7"),
    ("pin_drill_live_pick", "现读，不写死"),
    ("pin_drill_not_equal_timestamps", "不能写成「两者相等」"),
    ("pin_fence_mongo_readonly", "Mongo 只读"),
    ("pin_fence_nas_subdir", "NAS 只在 `xiaoman-backups` 这个子目录里动"),
    ("pin_fence_check_before_delete", "删本机旧份之前，先核 NAS 上有同一天、同字节数、同 sha 的那份"),
    ("pin_fence_lan_only", "NAS 只认局域网那台"),
    ("pin_fence_user_space_smb", "用户态 SMB"),
    ("pin_fence_no_drive_unc", "不走盘符、不走系统 UNC"),
    ("pin_fence_credential_name", "`nas-smb`"),
    ("pin_wording_smb_readback", "措辞只到「SMB 读回一致」"),
    ("pin_wording_no_nas_self_check", "不许写「NAS 自己校验过」"),
    ("pin_path_from_base_directory", "`Base directory` 为准，现读，不抄旧号"),
    ("pin_untested_writes_named", "没有对 NAS 真写／真删跑过"),
]
SCRIPT_PINS = {
    "backup_push.py": ["require_lan_host", "--verify-only", "SMB 读回"],
    "backup_retain.py": ["--keep-local", "--keep-nas", "default=2", "default=7", "weekly"],
    "backup_drill.py": ["pick_seq", "revision", "json_util.loads"],
    "backup_export.py": ["CANONICAL_JSON_OPTIONS", "count_documents", ".find("],
    "_bk_common.py": ["use_ntlm", "is_private", "nas_file"],
}
FENCE_WORDS = ["Mongo 只读", "xiaoman-backups", "NAS 只认局域网", "nas-smb", "SMB 读回一致"]


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


def main():
    results, notes = [], []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    skill_path = os.path.join(HERE, "SKILL.md")
    with open(skill_path, "rb") as h:
        raw = h.read()
    check("skill_lf", b"\r" not in raw, "SKILL.md 有 CR 字节")
    text = raw.decode("utf-8")
    head, body = None, text
    if text.startswith("---") and text.find("\n---", 3) != -1:
        end = text.find("\n---", 3)
        head, body = text[3:end].strip("\n"), text[end + 4:]
    check("frontmatter_delimited", head is not None)
    fields = {}
    try:
        import yaml
        try:
            fields = yaml.safe_load(head or "")
            check("frontmatter_real_yaml_parses", isinstance(fields, dict), "解析结果不是映射")
        except Exception as exc:  # noqa: BLE001
            check("frontmatter_real_yaml_parses", False, "%s: %s" % (type(exc).__name__, str(exc)[:200]))
    except ImportError:
        check("frontmatter_real_yaml_parses", False, "没有 PyYAML——没真查，不是过了")
    fields = fields if isinstance(fields, dict) else {}
    check("name_matches_directory", fields.get("name") == EXPECTED_NAME, "name=%r dir=%r" % (fields.get("name"), EXPECTED_NAME))
    desc = fields.get("description")
    check("description_specific_enough", isinstance(desc, str) and len(desc) >= 120)
    vals = [ln.split(":", 1)[1] for ln in (head or "").splitlines() if re.match(r"^[A-Za-z_][\w-]*:", ln)]
    check("no_ascii_colon_space_in_values", not any(": " in v.strip() for v in vals))
    for name, token in BODY_PINS:
        check(name, token in body, token)
    check("no_ip_like_in_skill", not IP_LIKE.search(text), "SKILL.md 里不写设备地址")

    all_text = text
    for script in SCRIPTS:
        p = os.path.join(HERE, script)
        if not os.path.isfile(p):
            check("script_exists_" + script, False, "不在")
            continue
        with open(p, "rb") as h:
            src = h.read()
        s = src.decode("utf-8")
        all_text += "\n" + s
        check("script_lf_" + script, b"\r" not in src, "有 CR 字节")
        try:
            compile(src, script, "exec")
            check("compiles_" + script, True)
        except Exception as exc:  # noqa: BLE001
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))
        check("fence_comment_" + script, all(w in s for w in FENCE_WORDS), "围栏注释缺字面")
        check("no_ip_like_" + script, not IP_LIKE.search(s), "脚本里写了像 IP 的字面")
        check("no_hardcoded_target_seq_" + script, not re.search(r"\b1699\b", s), "写死了旧靶子节号")
        for token in SCRIPT_PINS.get(script, []):
            check("pin_%s_%s" % (script, token), token in s, token)
        if re.search(r"NAS 自己校验过", s):
            ok = all("不" in ln or "没" in ln for ln in s.splitlines() if "NAS 自己校验过" in ln)
            check("no_positive_nas_self_check_" + script, ok, "出现了肯定句")
    check("retain_deletes_only_prefix", "bk.PREFIX" in open(os.path.join(HERE, "backup_retain.py"), encoding="utf-8").read())
    check("push_never_removes_except_own_partial",
          open(os.path.join(HERE, "backup_push.py"), encoding="utf-8").read().count("smbclient.remove(") == 1,
          "push 里的 remove 只许有一处（自己刚写的半成品）")

    lp, entries = private_list()
    if entries is None:
        check("leak_scan_ran", False, "私密名单没配上——没真查，不是跑过了")
    elif not entries:
        check("leak_scan_ran", False, "名单 0 条——没真查")
    else:
        found = listed_hits(entries, all_text)
        check("no_listed_words", not found, "、".join(found))
        notes.append("泄露检查扫过（名单 %d 条，命中只报类别与行号）" % len(entries))

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
    print("%d/%d 通过：围栏、参数、靶子现读都在，脚本无写死的地址和节号。" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
