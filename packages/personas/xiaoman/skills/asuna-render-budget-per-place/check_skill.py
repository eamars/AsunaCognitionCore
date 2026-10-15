#!/usr/bin/env python3
"""asuna-render-budget-per-place 的零依赖离线自检。

这份技能是一笔固定算法的账，所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节齐全、脚本能编译、
   换行是 LF（读字节数 CR，文本模式那把尺看不见 CR）；
2. 口径齐全：四场合各渲染、每节的数＝去掉这一节少多少、预算卡最大那份、上限的三层来源、
   token 估法、那条推论（放掉单场合的节只腾几格、要真腾只能动处处都出现的节）、
   行动脑自己算、加不进去是常态、赶时间别动大节——字面要点都在；
3. 引用的代码位置不烂：正文反引号里形如 `src/asuna/render.py:largest` 的锚点逐个查——文件在、
   且那个名字在文件里找得到（字节级读）。行号每次有人改那个文件就漂，名字不会，
   所以正文里再出现行号锚点也直接判红；
4. 不带别人的个人信息：私密名单命中只报类别和名单第几行；另查字面编号与占位符。

不联网、不碰数据库（算账本身要读库的是 budget_per_place.py，不是这份自检）、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-render-budget-per-place/check_skill.py   # 候选根目录
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import py_compile
import re
import shutil
import sys
import time

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就 UnicodeEncodeError 整段崩，整段输出丢掉
# （2026-10-15 实测：六份 check_skill.py 全中，rc=1、stdout 0 字节）。我的沙箱 env 带 PYTHONUTF8=1／
# PYTHONIOENCODING=utf-8，自检撞不到这一族。输出字节固定成 UTF-8：那种控制台顶多显示成乱码，
# 不再崩；stderr 同理，报错才看得见。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 一、算法（写死，别自己发明）",
    "## 二、最值钱的一格（推论）",
    "## 三、怎么跑（不用找人跑）",
    "## 四、加东西之前",
    "## 五、技能里引用代码只写「文件＋名字」，不写行号",
    "## 版本",
    "## 试用记录",
]

# 口径与推论：每条查一个只有写全了才会出现的字面
RULES = [
    ("rule_four_places", "家里／线／群／私聊"),
    ("rule_place_class_source", "PLACE_CLASS"),
    ("rule_section_is_delta", "去掉这一节少多少"),
    ("rule_budget_bounds_largest", "最大的那份"),
    ("rule_limit_key", "render.budget_tokens"),
    ("rule_limit_value", "核默认 6144"),
    ("rule_limit_precedence", "policy 存储 > persona-model 默认 > 核默认"),
    ("rule_token_estimate", "estimate_tokens"),
    ("rule_token_estimate_rule", "÷4"),
    ("rule_place_tags", "place:"),
    ("rule_inference_swap", "换成另一个场合"),
    ("rule_inference_freed_8", "只腾出"),
    ("rule_only_everywhere_helps", "处处都出现"),
    ("rule_action_brain_runs_it", "import asuna.render"),
    ("rule_no_need_to_ask", "不用找人跑"),
    ("rule_over_is_normal", "加不进去是常态"),
    ("rule_over_history", "6501/6144"),
    ("rule_gate_name", "PERSONA_RENDER_OVER_BUDGET"),
    ("rule_gate_advice", "on_demand"),
    ("rule_no_hurry_on_big_section", "别在赶时间时动"),
    ("rule_import_is_checkout", "不是 worker 正在跑那份"),
    ("rule_points_running_version", "asuna-running-version"),
    ("rule_anchor_rule", "行号每次有人改那个文件就漂，名字不会"),
]

# 代码锚点：`文件:名字`。行号每次有人改那个文件就漂，名字不会——所以锚点只准写文件里真有的标识符。
CODE_ANCHOR = re.compile(r"^([\w./-]+\.(?:py|mjs|js|json|md|yml)):([A-Za-z_][A-Za-z0-9_.]*)$")
# 行号锚点（`文件:19`、`文件:91-106`、光一个 `:244-245`）：写法本身判红。
LINE_ANCHOR = re.compile(r"^(?:[\w./-]+\.(?:py|mjs|js|json|md|yml)|):\d+(?:-\d+)?$")
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")
LITERAL_ID = re.compile(r"#\d")

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
    """正文反引号里的代码锚点：[(token, 相对路径, 名字)]。名字必须是文件里真有的标识符。"""
    found = []
    for span in re.findall(r"`([^`\n]+)`", body):
        match = CODE_ANCHOR.match(span.strip())
        if match:
            found.append((span.strip(), match.group(1), match.group(2)))
    return sorted(set(found))


def line_anchors(body):
    """正文反引号里还带着行号的锚点（`文件:19`、`文件:91-106`、光一个 `:244-245`）：写法本身就该判红。"""
    return sorted({span.strip() for span in re.findall(r"`([^`\n]+)`", body)
                   if LINE_ANCHOR.match(span.strip())})


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
    for name, token in RULES:
        check(name, token in body, token)

    root = find_repo_root()
    anchor_note = ""
    if root:
        broken, checked = [], 0
        for token, rel, name in anchors(body):
            checked += 1
            target = os.path.join(root, *rel.split("/"))
            if not os.path.isfile(target):
                broken.append("%s（文件不在）" % token)
                continue
            with open(target, "rb") as handle:          # 字节级读：查名字不看换行，也不怕编码
                raw = handle.read()
            if name.encode() not in raw:
                broken.append("%s（%s 里找不到这个名字）" % (token, rel))
        stale = line_anchors(body)
        if stale:
            broken.append("还写着行号锚点（行号会漂，改成文件＋名字）：" + "、".join(stale))
        check("code_anchors_named", not broken, "、".join(broken))
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
    check("ledger_shipped", "budget_per_place.py" in body)

    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))

    # 换行：字节级数 CR（文本模式那把尺是瞎的，见 cr_bytes）。覆盖发出去的每一份文本：
    # SKILL.md 加同目录全部 .py。跑的时候要看的是冻结快照，不是候选——候选可能被别人抹平成 LF。
    cr_files = cr_bytes([path] + [os.path.join(HERE, name) for name in scripts])
    check("line_endings_are_lf", not cr_files,
          "有 CR（仓库守卫 test_line_endings 会红）：" + "、".join(cr_files))
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
    print("%d/%d 通过：口径与推论都在，没夹个人信息%s。" % (total, total, anchor_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
