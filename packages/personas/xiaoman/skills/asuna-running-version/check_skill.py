#!/usr/bin/env python3
"""asuna-running-version 的零依赖离线自检。

这份技能是「现在跑的是哪版」的判据集，所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节齐全、脚本能编译；
2. 判据齐全：八条判据（先看 loaded、缺 loaded ≠ 没装、比内容不比包 sha、主仓合了 ≠ 在跑、
   activation.json、diverged 的读法、脏工作区跳过快进、看工具表）加两条顺手（git 只读命令、
   import 到的是检出那份）的字面要点都在；
3. 引用的代码位置不烂：正文反引号里形如 `src/asuna/restarts.py:254`、`tools/asuna-launch.mjs:91-106`
   的锚点逐个查——文件在不在、有没有那么多行。技能里的行号是最容易过期的东西，守卫立在这儿；
4. 不带别人的个人信息：私密名单（真人名／群名／站点／主机）命中只报类别和名单第几行，
   不打印词本身；另查字面编号（#数字）和占位符残留。

不联网、不碰数据库、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-running-version/check_skill.py   # 候选根目录
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
    "## 一、先看这一回合的",
    "## 二、缺 `loaded` 那一格不等于「没装」",
    "## 三、比内容，别只比包 sha",
    "## 四、「主仓合了」不等于「我这边在跑」",
    "## 五、查 `activation.json`",
    "## 六、回执说「本机检出有 origin/main 没有的提交」＝本机比远端新",
    "## 七、脏工作区会让本机长期落后一格，这不是故障",
    "## 八、新参数进没进，看这一回合的工具表",
    "## 九、顺手：git 事实怎么读",
    "## 十、怎么算查清楚了",
    "## 版本",
    "## 试用记录",
]

# 八条判据 + 两条顺手：每条查一个只有写全了才会出现的字面
CRITERIA = [
    ("criterion_loaded_first", "restart_from_program"),
    ("criterion_loaded_fields", "selections"),
    ("criterion_missing_loaded_not_absent", "不等于「没装」"),
    ("criterion_missing_loaded_ask_first", "先问一句"),
    ("criterion_missing_loaded_24h", "24 小时"),
    ("criterion_compare_content", "逐文件 sha256"),
    ("criterion_repack_changes_sha", "重新 pack"),
    ("criterion_main_not_running", "不等于「我这边在跑」"),
    ("criterion_states", "HOST_RESTART_REQUIRED"),
    ("criterion_applied_state", "APPLIED"),
    ("criterion_active_is_running", "ACTIVE"),
    ("criterion_activation_path", ".runtime/adr008/activation.json"),
    ("criterion_activation_fields", "published_at"),
    ("criterion_activation_changed_files", "changed_files"),
    ("criterion_diverged_words", "diverged"),
    ("criterion_diverged_means_newer", "本机比远端新"),
    ("criterion_diverged_misread", "读成没装"),
    ("criterion_fast_forward_name", "fastForwardCheckout"),
    ("criterion_fast_forward_skip", "跳过"),
    ("criterion_dirty_not_fault", "不是故障"),
    ("criterion_tool_table", "工具表"),
    ("criterion_import_is_checkout", "不是 worker 正在跑的那份"),
    ("criterion_git_read_commands", "rev-list --count"),
    ("criterion_git_write_denied", "index.lock"),
]

# 代码锚点：反引号里的 path:line 或 path:line-line。仓库根找到才真查。
CODE_ANCHOR = re.compile(r"^[\w./-]+\.(?:py|mjs|js|json|md|yml):(\d+)(?:-(\d+))?$")

PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")
LITERAL_ID = re.compile(r"#\d")

# 别人的个人信息：称呼与场景词。具体人名、群名不写进这张表（仓库是公开的，表里的字本身就会把人带出去）。
PERSONAL_TOKENS = ["姐姐", "交流群", "旧居"]


def probe_dir():
    """编译临时目录：先试技能目录旁（development_run 只放行候选里的写），
    写不动就退到当前工作目录（从 /task 那边跑的情形）。两处都不行返回 None。"""
    for base in (HERE, os.getcwd()):
        candidate = os.path.join(base, "_compile-probe-%d" % int(time.time() * 1000))
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue
    return None


def find_repo_root():
    """从脚本位置和 cwd 向上找仓库根：src/asuna 与 pyproject.toml 同层。"""
    for start in (HERE, os.getcwd()):
        current = os.path.abspath(start)
        while True:
            if (os.path.isdir(os.path.join(current, "src", "asuna"))
                    and os.path.isfile(os.path.join(current, "pyproject.toml"))):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return None


def private_list():
    """私密名单：ASUNA_PRIVATE_WORDS 指的文件，否则 <数据根>/private/personal-words.txt。

    数据根优先用 asuna.config.DATA（家里跑就有），再退回 ASUNA_DATA_ROOT。
    一行一条 category|word|why。
    """
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as asuna_config
            data = str(asuna_config.DATA)
        except Exception:                                   # noqa: BLE001 没装 asuna 也要能跑
            data = None
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


def anchors(body):
    """正文反引号里的代码锚点：[(相对路径, 最大行号)]。"""
    found = []
    for span in re.findall(r"`([^`\n]+)`", body):
        match = CODE_ANCHOR.match(span.strip())
        if match:
            found.append((span.strip(), int(match.group(1)), int(match.group(2) or match.group(1))))
    return sorted(set(found))


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
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return fields, body


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
    check("frontmatter_parses", fields is not None)
    check("frontmatter_name_present", bool(fields and fields.get("name")))
    check("name_matches_directory",
          bool(fields and fields.get("name") == EXPECTED_NAME),
          "name=%s dir=%s" % ((fields or {}).get("name"), EXPECTED_NAME))
    desc = (fields or {}).get("description", "")
    check("description_specific_enough", len(desc) >= 120, "len=%d" % len(desc))

    for index, section in enumerate(SECTIONS):
        check("section_%d" % index, ("\n" + section) in ("\n" + body), section)
    for name, token in CRITERIA:
        check(name, token in body, token)

    # 代码锚点：文件在不在、有没有那么多行
    root = find_repo_root()
    anchor_note = ""
    if root:
        broken, checked = [], 0
        for token, first, last in anchors(body):
            checked += 1
            target = os.path.join(root, *token.split(":")[0].split("/"))
            if not os.path.isfile(target):
                broken.append("%s（文件不在）" % token)
                continue
            with open(target, encoding="utf-8", errors="replace") as handle:
                lines = sum(1 for _ in handle)
            if last > lines:
                broken.append("%s（只有 %d 行）" % (token, lines))
        check("code_anchors_exist", not broken, "、".join(broken))
        anchor_note = "，代码锚点核过 %d 条" % checked
    else:
        notes.append("NOTE 没找到仓库根（src/asuna 与 pyproject.toml 同层），代码锚点检查跳过——"
                     "在检出或候选里跑才会真查")

    listed_path, entries = private_list()
    if entries is None:
        notes.append("NOTE 私密名单没配上（%s），真人名／群名这一项没查" % (listed_path or "都没有"))
    else:
        found = listed_hits(entries, text)
        check("no_listed_words", not found, "、".join(found))

    personal = [token for token in PERSONAL_TOKENS if token in body]
    check("no_personal_info", not personal, ",".join(personal))
    check("no_literal_ids", not LITERAL_ID.search(body),
          "出现字面编号：" + ",".join(LITERAL_ID.findall(body)[:5]))
    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 1500, "body_chars=%d" % len(body))
    check("selfcheck_documented", "check_skill.py" in body)
    check("probe_shipped", "version_probe.py" in body)

    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))
    # 编译临时产物落技能目录旁，用完即删：宿主沙箱只放行候选目录里的写（撞过）。
    tmp = probe_dir()
    check("compile_probe_writable", tmp is not None,
          "技能目录旁和当前目录都写不动：临时目录不可写（沙箱限制），编译这一项没法真查")
    try:
        for script in (scripts if tmp else []):
            try:
                py_compile.compile(os.path.join(HERE, script), cfile=os.path.join(tmp, script + "c"),
                                   doraise=True)
                check("compiles_" + script, True)
            except Exception as exc:                       # noqa: BLE001 编译失败要原样报出来
                check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    if [d for d in os.listdir(HERE) if d == "__pycache__"]:
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
    print("%d/%d 通过：八条判据加两条顺手都在，没夹个人信息%s。" % (total, total, anchor_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
