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
   名单配不上、或名单在却解析出 0 条有效词，都记一条红（`leak_scan_ran`）——2026-10-16 起不再「NOTE 一行、绿数照旧」：
   「检查项没跑」不许长得像「检查项过了」。定位多一条兜底：环境变量都没有就从脚本往上找
   .runtime/private/personal-words.txt。

不联网、不碰数据库（算账本身要读库的是 budget_per_place.py，不是这份自检）、不发 QQ。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-render-budget-per-place/check_skill.py   # 候选根目录
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

SECTIONS = [
    "## 一、算法（写死，别自己发明）",
    "## 二、最值钱的一格（推论）",
    "## 三、怎么跑（不用找人跑）",
    "## 四、加东西之前",
    "## 五、技能里引用代码只写「文件＋名字」，不写行号",
    "## 六、两份口径、自我层、锚点形状",
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
    # v2（2026-10-25）：两份口径、自我层、锚点形状
    ("rule_two_calibres", "两种口径"),
    ("rule_placed_is_the_carried_one", "memory_tiers.py:placed"),
    ("rule_gate_which_copy_undecided", "待读码"),
    ("rule_self_layer_outside_6144", "不受 6144 管"),
    ("rule_self_saved_is_not_budget_saved", "不等于「预算省了 N」"),
    ("rule_anchor_is_shape", "自证锚点认形状，不认绝对数"),
]

# 账本脚本源码里必须有的字面（只查字面在不在，不查跑通；跑通看试用记录里的实跑）：
# 同时输出两份口径、逐节说为什么不一样、自我层单独一格且明写不受 6144 管、锚点是形状。
LEDGER_BOTH_CALIBRES = ["预算口径", "带出门", "memory_tiers.placed", "doc 里怎么说 vs memory_tiers 排成哪一档",
                        "没解释掉的", "inject=%s／visibility=%s／tags=%s"]
LEDGER_SELF_LAYER = ["自我层（单独一格", "不受 %s 管", "memory_tiers.SELF_DOC"]
LEDGER_ANCHOR_SHAPE = ["ANCHOR = (", "形状", "只出现在一个场合的节数", 'd["group"] == 0 and d["home"] > 0']
# 绝对值锚点的旧写法：任何一处（脚本、正文、frontmatter description）再出现就红。description 那一行每一拍进技能目录、被当触发依据读，
# 所以它与正文同口径一起扫。
STALE_ABSOLUTE_ANCHOR = ["home≈", "≈733", "733"]
DESC_MUST_SAY = ["两种口径", "memory_tiers.placed", "不受 6144 管", "形状"]

# 代码锚点：`文件:名字`。行号每次有人改那个文件就漂，名字不会——所以锚点只准写文件里真有的标识符。
CODE_ANCHOR = re.compile(r"^([\w./-]+\.(?:py|mjs|js|json|md|yml)):([A-Za-z_][A-Za-z0-9_.]*)$")
# 行号锚点（`文件:19`、`文件:91-106`、光一个 `:244-245`）：写法本身判红。
LINE_ANCHOR = re.compile(r"^(?:[\w./-]+\.(?:py|mjs|js|json|md|yml)|):\d+(?:-\d+)?$")
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")
LITERAL_ID = re.compile(r"#\d")

PERSONAL_TOKENS = ["姐姐", "交流群", "旧居"]


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
    candidates = []
    if named:
        candidates.append(named)
    if data:
        candidates.append(os.path.join(data, "private", "personal-words.txt"))
    # 兜底（2026-10-16）：本机两个环境变量都没设，但 asuna 能 import——开发沙箱与任务沙箱都实测到
    # config.DATA = <部署根>/.runtime，所以第三条 asuna.config.DATA 在本机就够。这条往上找
    # .runtime/private/personal-words.txt 是给 asuna 不在 sys.path 上的环境兜底：裸检出、别的机器、
    # 装在 node_modules 里的冻结版。三条都不中才算没配上，那时调用方记一条红，不 NOTE 一行算过。
    here = HERE
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
    # 一个都没配上：返回试过的全部候选，让调用方把「没查过」写进红里
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
        # 2026-10-16 改口径：以前这里 NOTE 一行、绿数照旧——「没跑」和「过了」长得一样。
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

    personal = [token for token in PERSONAL_TOKENS if token in body]
    check("no_personal_info", not personal, ",".join(personal))
    check("no_literal_ids", not LITERAL_ID.search(body),
          "出现字面编号：" + ",".join(LITERAL_ID.findall(body)[:5]))
    check("no_placeholder_markers", not PLACEHOLDER.search(body))
    check("skill_body_not_thin", len(body) >= 1500, "body_chars=%d" % len(body))
    check("selfcheck_documented", "check_skill.py" in body)
    check("ledger_shipped", "budget_per_place.py" in body)

    # v2（2026-10-25）：账本脚本必须同时输出两份口径、自我层单独一格、锚点是形状不是绝对值。
    # 这里只查脚本源码里的字面（这份自检不碰数据库），绝不等于「脚本跑得通」。
    ledger_src = ""
    try:
        with open(os.path.join(HERE, "budget_per_place.py"), "rb") as handle:
            ledger_src = handle.read().decode("utf-8")
    except OSError as exc:                                 # noqa: BLE001 读不到也要报出来
        check("ledger_readable", False, str(exc))
    for name, tokens in (("ledger_prints_both_calibres", LEDGER_BOTH_CALIBRES),
                         ("ledger_self_layer_marked_outside_budget", LEDGER_SELF_LAYER),
                         ("ledger_anchor_is_shape", LEDGER_ANCHOR_SHAPE)):
        missing = [token for token in tokens if token not in ledger_src]
        check(name, ledger_src and not missing, "脚本里缺：" + "、".join(missing))
    # 旧绝对值锚点三处各一条：脚本、正文（去掉反引号里的引用）、frontmatter description
    prose = re.sub(r"`[^`\n]*`", "", body)
    for name, where in (("no_absolute_anchor_in_ledger", ledger_src), ("no_absolute_anchor_in_body", prose),
                        ("no_absolute_anchor_in_frontmatter", desc)):
        hit = [token for token in STALE_ABSOLUTE_ANCHOR if token in where]
        check(name, not hit, "还写着绝对值锚点：" + "、".join(hit))
    desc_missing = [token for token in DESC_MUST_SAY if token not in desc]
    check("frontmatter_description_current", not desc_missing,
          "frontmatter description 没写到（那一行每一拍进我的技能目录）：" + "、".join(desc_missing))

    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))

    # 换行：字节级数 CR（文本模式那把尺是瞎的，见 cr_bytes）。覆盖发出去的每一份文本：
    # SKILL.md 加同目录全部 .py。跑的时候要看的是冻结快照，不是候选——候选可能被别人抹平成 LF。
    cr_files = cr_bytes([path] + [os.path.join(HERE, name) for name in scripts])
    check("line_endings_are_lf", not cr_files,
          "有 CR（仓库守卫 test_line_endings 会红）：" + "、".join(cr_files))
    # 语法检查不落文件：compile(源码, 路径, 'exec') 在内存里查，沙箱里外都能真查，不需要临时目录
    # （2026-10-18 之前用 py_compile 写 .pyc，行动脑沙箱里技能目录和 cwd 都不让写，这一格只能报「没真查」）。
    # 分寸：compile() 只查语法，不查 import 和运行时（脚本能编译不等于能跑）。
    for script in scripts:
        try:
            with open(os.path.join(HERE, script), "rb") as handle:
                source = handle.read()
            compile(source, os.path.join(HERE, script), "exec")
            check("compiles_" + script, True)
        except Exception as exc:                       # noqa: BLE001 编译失败要原样报出来
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

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
    print("%d/%d 通过：口径与推论都在，没夹个人信息%s。" % (total, total, anchor_note + leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
