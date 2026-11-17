#!/usr/bin/env python3
"""asuna-offline-selfchecks 的零依赖离线自检。

本技能是核心技能 asuna-self-improvement 之上的**增量笔记**，所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、章节在、脚本语法能编译（内存 compile，不落文件）、
   换行是 LF（读字节数 CR，文本模式那把尺看不见 CR）；
2. 指向：正文指向核心技能，并写明两份不一致时按核心技能办；
3. 增量与「不回潮」：几条增量（挂错项目的红、单个用例文件与 p3 现行跑法、pytest 不收
   *_cases.py 的盲区、p5b 退役读法、没收录 ≠ 已退役、适配器自检去处、候选根临时脚本落点与包内容判据、发布前私密词扫描的常设判据、发布撞 EFFECTIVE_PROJECT_CHANGED 那一节的字面守卫）都还在；通用离线套件
   的命令清单没有回潮到散文里——反引号里的字面量（旧试用记录引用的命令、错误原文）按引用处理，
   不算回潮；
4. 反引号仓库路径存在性：正文反引号里形如 tests/...、tools/...、docs/... 的仓库路径逐个查
   文件在不在，不在就红——2026-10-12 那轮 p3 死引用（指向已随 9d3ed60e 删除的文件）就是这一族，
   守卫立在这儿防复发。要能找到仓库根（tests/ tools/ pyproject.toml 同层）才真查；
   找不到只留 NOTE（比如装在 node_modules 里的冻结版），不算失败。

5. 补遗的钉：「判据补遗」一节里各条各一个 pin_* 检查，只认本节范围内的字面。
6. 内容级私密词扫描（同日补）：leak_scan_ran／no_listed_words／no_listed_words_outside_envoy 三格。
   名单配不上或 0 条＝红 leak_scan_ran（没真查，不是干净）；本技能目录里的文件零命中；
   找得到包根时再扫整个包根，命中只许落在 integration/envoy_meters_read.py（既有基线：命中 12 处，
   全在那个文件里；漂了只打 NOTE，不变红）。命中只报 文件:行号:类别，绝不回显词本身。
   名单条目数 11-17 起不再钉基线：这个数随我加词长大，钉死一个会长大的数＝每加一个词白响一次。现在
   每次现读＋按类别打印（好和 private_words summary 一眼对照），差值只在带 --expect-entries 时算，
   且只报差、不算失败；对不上的处置写在 SKILL.md「判据补遗」(d)。
7. 第 5 件事（SKILL.md 头拿真 YAML 解析，在 pre_publish_scan.py）的自检针 11-17 补：import 同目录那份，
   喂一发坏头（description 值里带 ASCII「冒号＋空格」）进它的 check_skill_head，断言红；再喂一发好头，
   断言绿；再用它真读本技能 SKILL.md，断言绿。三发的结果都印进输出；关口加载不了、或这台机没有可用的
   YAML 库，一律红（没真查不许长得像过了）。谁把那段删了或换成宽容正则，红在这里，
   不会只剩「行动侧清单少一本」那种静默。

不联网、不跑离线套件、不写 Mongo、不发 QQ。

语法检查不落文件：compile(源码, 路径, 'exec') 在内存里查，沙箱里外都能真查，也不需要临时目录
（2026-10-18 之前用 py_compile 写 .pyc，先试技能目录旁、再退当前目录，行动脑沙箱里两处都不让写，
这一格只能报「没真查」——检查根本没跑起来）。语法不过照旧逐条 compiles_<脚本> 红并带 SyntaxError。
分寸：compile() 只查语法，不查 import 和运行时——脚本能编译不等于能跑。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
    python3 skills/asuna-offline-selfchecks/check_skill.py   # 候选根目录
    python3 skills/asuna-offline-selfchecks/check_skill.py --expect-entries <上一份报告的名单条数>
        # 给了才算名单条数差值（只报差、不算失败；这个数会随加词长大）
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import argparse
import importlib.util
import io
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

CORE_SKILL = "asuna-self-improvement"

# 增量内容：核心技能没有、本技能必须写清的几条
INCREMENTS = [
    ("increment_wrong_project", "No such file or directory"),
    ("increment_wrong_project_meaning", "选错项目，不是产品坏了"),
    ("increment_single_case_files", "PYTHONPATH=tests"),
    ("increment_p3_replacement", "test_schedule_rules"),
    ("increment_pytest_blind_spot", "pytest 默认不收"),
    ("increment_p5b_retired", "p5b_ui_offline_check"),
    ("increment_not_included_not_retired", "没收录 ≠ 已退役"),
    ("increment_adapter_elsewhere", "qq-napcat-adapter"),
]

# 「候选根」一节的关键串（2026-10-22）：这一节被删走样就要红。INCREMENTS 同一族写法，逐条判。
PACKAGING_RULES = [
    ("rule_tmp_script_not_in_candidate_root", "不许直接写在候选根"),
    ("rule_tmp_script_goes_to_task", "写到 `/task` 工作区"),
    ("rule_tmp_script_tmp_subdir", "`.tmp/` 子目录"),
    ("rule_whitelist_scan_before_publish", "只留 `package.json` 里 `files` 白名单列出的路径"),
    ("rule_package_content_proof", "只认 artifact 那串 sha256 和 `.tgz` 的文件清单"),
    ("rule_changed_files_is_not_package", "`changed_files` 反映的是候选树／冻结快照那一格，不等于包内容"),
]

# 「development_publish 撞 EFFECTIVE_PROJECT_CHANGED 的处置」一节的字面守卫（2026-10-25 主人交代）：
# 那一节整节只有标题带这个错误名，哪天它被顺手删掉、或标题被改写得认不出，就红这一条——防这节无声消失。
# 反证：把标题里那个词删掉再跑一次，应当只红 guard_effective_project_changed，别的不连带。
PUBLISH_CLASH_GUARDS = [
    ("guard_effective_project_changed", "EFFECTIVE_PROJECT_CHANGED"),
]

# 「发布前自检（私密词扫描）」一节的常设判据（2026-10-23，主人 10-14 拍的那条）。
# 一条判据名底下挂 11 个关键串：整节被剥走样就红这一条，detail 列出缺哪几个串——
# 剥一节只红对应那一条，不连带红别的（主人交代）。不按名单序号写，序号会漂（10-23 凌晨名单加过条目）。
PREPUB_SCAN_RULES = [
    ("prepub_section_title", "## 发布前自检（私密词扫描）"),
    ("prepub_pass_zero_new", "零新增命中"),
    ("prepub_pass_only_envoy", "命中**全部**落在 `integration/envoy_meters_read.py`"),
    ("prepub_stop_head", "停下来报主人"),
    ("prepub_stop_other_file", "命中冒出"),
    ("prepub_stop_list_count", "名单条目数跟上一份报告对不上"),
    ("prepub_stop_envoy_changed", "本身在这次改动里被改"),
    ("prepub_why_rubber_stamp", "把「停」练成橡皮章"),
    ("prepub_no_entry_index", "不按序号引用名单条目"),
    ("prepub_three_way_wording", "可判的三岔"),
]

# 「判据补遗（2026-10-24 并版：八条）」一节的钉。每条一个检查名，只认本节范围内的字面
# （别处，比如版本条目或试用记录复述了同一句，不算数）；缺哪个字面写进 detail。
BACKLOG_TITLE = "## 判据补遗"
BACKLOG_PINS = [
    ("pin_a_active_root", ["中选中那格的 `packageRoot/skills`", "`node_modules` 里那份不算"]),
    ("pin_b_corroboration", ["必须带旁证", "不拿最新一版当现场"]),
    ("pin_c_module_file", ["`模块.__file__`", "主干那份 blob"]),
    ("pin_d_content_scan_documented", ["内容级私密词扫描",
                                       "命中 12 处全在 `integration/envoy_meters_read.py`",
                                       "名单条目数不是基线", "不要开查道链"]),
    ("pin_f_which_zero", ["报 0 之前先说它是哪种 0", "必须显式给 `fields` 或先枚举键路径"]),
    ("pin_g_receipt_or_no_number", ["指不到就写「我没读到号」", "在跑，号等回执"]),
    ("pin_h_table_beats_prose", ["以表格为准，并追问同一格"]),
    ("pin_i_temp_one_command", ["跨命令要留的东西一律写 `/task`", "别拿 TEMP 当中间存储"]),
    ("pin_j_local_hash_offline", ["别为了算 sha 出网", "哈希未算", "import hashlib,sys"]),
    ("pin_k_alternates_notes", ["alternates 文件必须 LF 行尾", "路径写相对路径", "远端只用 https"]),
    ("pin_n_short_sha_by_command", ["rev-parse --short=12", "cat-file -t", "发布候选 sha"]),
    ("pin_o_commit_subject_one_line", ["第一段只写一句", "80 字"]),
    ("pin_m_dates_by_script", ["脚本读钟面", "不手打日期", "假数"]),
    ("pin_l_fork_root_cause", ["主检出落后", "不许 merge／rebase／reset 硬挪", "先发布，再把自动提交"]),
]

# 派活交代的落点（2026-11-02 主人交代，来路是 10-22 部署环境那条 TEMP 回收改动）：正文一提到临时目录／TEMP，
# 就必须同时写「跨命令要留的东西一律写 `/task`」。只提 TEMP 不提落点，等于叫行动脑把中间产物放进一条命令后
# 就回收掉的地方——静默丢，还丢在回执之后，我看见的是绿。核心技能那份正文（asuna-self-improvement）同一条判据。
TEMP_MENTION = re.compile(r"临时目录|TEMP|TMPDIR|\bTMP\b")
TEMP_LANDING_RULE = "跨命令要留的东西一律写 `/task`"

# 内容级私密词扫描的既有基线（2026-10-24 发布前扫整棵候选根的读数；命中 11→12 处，全在 envoy 那个文件）：
# 漂了只打 NOTE，不变红。命中只许在那一个文件里、本次改动零新增——这两条才是基线。
#
# 名单条目数从 11-17 起不再钉在这里。钉死一个会长大的数（它随我加词／删词长大：69→90→103→106→125→130→129，
# 逐次读数与来路在 SKILL.md「判据补遗」(d)）等于每加一个词白响一次；响多了这条就成了噪音，等名单真被人改了
# 也没人看它。现在每次现读、按类别打印（好和 `private_words summary` 一眼对照），差值只在调用方带
# --expect-entries N（N 抄上一份报告那一行，与 pre_publish_scan.py 同一口径）时才算，且只报差、不算失败。
# 数对不上时的处置也印在输出里：先跑一次 private_words summary 对一次，对得上就只更数，不要开查道链。
ENVOY_FILE = "integration/envoy_meters_read.py"
BASELINE_ENVOY_HITS = 12
# 名单认的类别（与 private_words 工具的 summary、pre_publish_scan.py 的 CATEGORIES 同一套）。
CATEGORIES = {"person", "group", "account", "site", "host", "email", "other"}

# 11-04：发布前一条命令（pre_publish_scan.py）并进「发布前自检（私密词扫描）」一节。一条判据名底下挂几个关键串，缺哪个写进 detail。
PREPUB_SCRIPT_RULES = [
    ("prepub_script_named", "pre_publish_scan.py"),
    ("prepub_script_expect_flag", "--expect"),
    ("prepub_script_missing_is_stop", "缺失默认算停"),
    ("prepub_script_expect_entries", "--expect-entries"),
    ("prepub_script_unjudged_said", "②没判"),
    ("prepub_script_exit_codes", "2 = 没法判"),
    ("prepub_script_self_compare", "--candidate <ACTIVE 的 packageRoot>"),
    ("prepub_fifth_thing_probe", "第⑤件事有自己的自检针"),
    ("prepub_entries_count_grows", "这个数会随我加词长大"),
]

SECTIONS = [
    "## 用途",
    "## 增量",
    "## 候选根：临时脚本落点与包内容判据",
    BACKLOG_TITLE,
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

# 反引号里允许出现的「故意已删」仓库路径：引用它们的行说的就是它们不在了，存在性检查放行。
# 加条必须写为什么放行；哪天这些名字回到仓库，条目该顺手删掉。
KNOWN_ABSENT = {
    "tools/p5b_ui_offline_check.py": "随 ADR-008 旧工作台退役，正文「退役」一节就是记录这件事",
    "tests/p3_schedule_cases.py": "随 9d3ed60e 删除，正文「p3 的现行跑法」一节写明",
    "tools/p3_offline_check.py": "随 9d3ed60e 删除，正文「p3 的现行跑法」一节写明",
}

# tests/... tools/... docs/...：左边不能是单词字符或斜杠（/task/tools/... 这种错误原文不算），
# 右边到空白、中文标点、引号、反引号为止。
REPO_PATH = re.compile(r"(?<![\w/])(?:tests|tools|docs)/[^\s、，。；：（）》\"'`|]*")

# 反引号里的字面量是引用（命令原话、错误原文、旧记录里的实跑输出），只在散文里判红。
PROSE = re.compile(r'`[^`]*`', re.S)
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")


def section_of(body, title):
    """按「## 标题」截出一节（到下一个二级标题为止）；没有这一节返回 None。"""
    start = body.find("\n" + title)
    if start == -1:
        return None
    end = body.find("\n## ", start + 1 + len(title))
    return body[start:end] if end != -1 else body[start:]


def private_list():
    """私密名单：ASUNA_PRIVATE_WORDS 指的文件，否则 <数据根>/private/personal-words.txt，
    再不行从脚本往上找 .runtime/private/personal-words.txt（冻结快照、候选都在 .runtime 下面）。
    返回 (路径, 条目) 或 (试过的候选, None)；三条都不中，调用方记一条红，不 NOTE 一行算过。"""
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
    here = HERE
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        candidates.append(os.path.join(here, ".runtime", "private", "personal-words.txt"))
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        entries = []
        with open(candidate, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                parts = line.strip().split("|", 2)
                if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                    entries.append((number, parts[0].strip(), parts[1].strip()))
        return candidate, entries
    return [c for c in candidates if c] or None, None


def compile_entries(entries):
    """名单条目编成正则：纯 ASCII 词按词边界、忽略大小写；含中文的词按子串。"""
    compiled = []
    for number, category, word in entries:
        if all(ch.isascii() for ch in word):
            rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", re.IGNORECASE)
        else:
            rx = re.compile(re.escape(word))
        compiled.append((number, category, rx))
    return compiled


def scan_text(compiled, text):
    """逐行逐条目匹配，返回 [(行号, 类别)]（一行里几个条目中就记几处）。不回显词。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for _, category, rx in compiled:
            if rx.search(line):
                hits.append((lineno, category))
    return hits


def read_utf8(target):
    """读成 UTF-8 文本；读不了或不是 UTF-8（比如 png）返回 None，调用方当「没扫」。"""
    try:
        with open(target, "rb") as handle:
            return handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def package_root():
    """HERE 是 <包根>/skills/<技能名>；上两级有 package.json 和 skills/ 才算找到包根。"""
    root = os.path.dirname(os.path.dirname(HERE))
    if os.path.isfile(os.path.join(root, "package.json")) and os.path.isdir(os.path.join(root, "skills")):
        return root
    return None


def walk_texts(root):
    """包根下全部文件（跳过 node_modules、.git、__pycache__），返回 [(相对路径, 文本或 None)]。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "__pycache__")]
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            found.append((rel, read_utf8(full)))
    return found


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
    """从脚本位置和 cwd 向上找仓库根：tests/ tools/ pyproject.toml 同层。"""
    for start in (HERE, os.getcwd()):
        d = os.path.abspath(start)
        while True:
            if (os.path.isdir(os.path.join(d, "tests"))
                    and os.path.isdir(os.path.join(d, "tools"))
                    and os.path.isfile(os.path.join(d, "pyproject.toml"))):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def backticked_repo_paths(body):
    """正文反引号里形如 tests/... tools/... docs/... 的仓库路径；裸目录、通配、占位符不查。"""
    tokens = []
    for span in re.findall(r"`([^`\n]+)`", body):
        for m in REPO_PATH.finditer(span):
            tok = m.group(0).rstrip(".,:;)]>》")
            if tok.endswith("/") or any(c in tok for c in "*?[<"):
                continue
            tokens.append(tok)
    return sorted(set(tokens))


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


def core_skill_body():
    """核心技能 asuna-self-improvement 的正文。按「core 候选 → 主检出」的顺序找，读到哪份写进 detail。"""
    for rel in (
        os.path.join(".runtime", "work", "self-development", "core",
                    "packages", "cognition-core", "skills", CORE_SKILL, "SKILL.md"),
        os.path.join("packages", "cognition-core", "skills", CORE_SKILL, "SKILL.md"),
    ):
        for start in (HERE, os.getcwd()):
            d = os.path.abspath(start)
            for _ in range(12):
                d = os.path.dirname(d)
                cand = os.path.join(d, rel)
                if os.path.isfile(cand):
                    text = read_utf8(cand)
                    if text is None:
                        return None, cand
                    return read_frontmatter(text)[1], cand
    return None, None

# ── 第 5 件事（SKILL.md 头拿真 YAML 解析）的自检针 ─────────────────────────────────────────
# 为什么要有这一族：那一段护的是「我这侧发布探针是宽容正则、一路绿，装载侧真 YAML 解析、一路空」
# 那一格（11-17 查明，两本技能就是这么从行动侧清单里静默消失的）。可它自己没人守——谁把 yaml.safe_load
# 换成宽容正则、或整段删掉，自检照绿，关口裸着。反证口径（实测过）：把第 5 件事那段换成宽容正则，
# 红的就是 skill_head_probe_bad_head_red 这一格，别的不连带。
PREPUB_SCRIPT = "pre_publish_scan.py"
PROBE_BAD = ("---\nname: probe-head-bad\n"
             "description: 直路是 generate_image，标 source_image: required 的路线才走它\n"
             "---\n正文一行（上一行那个值里带 ASCII 冒号＋空格）\n")
PROBE_GOOD = ("---\nname: probe-head-good\n"
              "description: 直路是 generate_image，标 source_image=required 的路线才走它\n"
              "---\n正文一行（同一个值改成＝号）\n")


def load_pre_publish_scan():
    """按文件路径 import 同目录的 pre_publish_scan.py，只为拿它的 check_skill_head。
    那份脚本只在 __main__ 里跑 main()，import 不带副作用（模块级只固定 stdout／stderr 编码）。
    返回 (模块, 问题)；拿不到就是 (None, 说明)，调用方记红——不许 NOTE 一行算过。"""
    script = os.path.join(HERE, PREPUB_SCRIPT)
    if not os.path.isfile(script):
        return None, "同目录没有 %s（第 5 件事整个不在了）" % PREPUB_SCRIPT
    try:
        spec = importlib.util.spec_from_file_location("_probe_pre_publish_scan", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 加载失败要原样报出来
        return None, "%s import 不了：%s: %s" % (PREPUB_SCRIPT, type(exc).__name__, exc)
    if not callable(getattr(module, "check_skill_head", None)):
        return None, "%s 里没有可调的 check_skill_head（被删或改名）" % PREPUB_SCRIPT
    return module, ""


def skill_head_probe(skill_md):
    """三发：坏头必须红、好头必须绿、本技能 SKILL.md 真读一遍必须绿。
    返回 (要印的行, [(检查名, 过不过, 说明)])；两发样本无论绿不绿都印进输出。
    样本走内存喂：把那份模块里的 open 换成 BytesIO，用完还原。为什么不落临时文件：开发沙箱只让写
    候选目录（实测 TEMP 里 open 报 PermissionError: [Errno 13]），冻结快照那一份还可能只读——
    为样本要临时目录会红在环境上，不像关口红。真读文件那一格由本技能 SKILL.md 这一发覆盖（走真的 open）。
    临时目录只活一条命令，跨命令要留的东西一律写 `/task`（或候选里）——这里同一条命令内写读，不需要留。"""
    module, problem = load_pre_publish_scan()
    results = [("skill_head_gate_importable", module is not None, problem)]
    lines = ["PROBE 第 5 件事的尺子：%s%s"
             % (getattr(module, "__file__", "没加载成"), "" if not problem else " — " + problem)]
    if module is None:
        for name in ("skill_head_probe_bad_head_red", "skill_head_probe_good_head_green",
                     "skill_head_self_head_loads"):
            results.append((name, False, "关口加载不了——这一格没真查，不许长得像「过了」"))
        lines.append("PROBE 坏头：没跑；好头：没跑（关口加载不了）")
        return lines, results
    yaml_lib = getattr(module, "yaml", None)
    if yaml_lib is None:
        lines.append("PROBE YAML 库：没有可用的（%s）——不退化成正则"
                     % getattr(module, "YAML_IMPORT_ERROR", "读不到原因"))
        for name in ("skill_head_probe_bad_head_red", "skill_head_probe_good_head_green",
                     "skill_head_self_head_loads"):
            results.append((name, False, "这台机没有可用的 YAML 库——没真查，不许长得像「过了」"))
        lines.append("PROBE 坏头：没真查；好头：没真查（没有 YAML 库）")
        return lines, results
    lines.append("PROBE YAML 库：PyYAML %s（%s）"
                 % (getattr(yaml_lib, "__version__", "?"), getattr(yaml_lib, "__file__", "?")))
    feeds = (("坏头", "mem://probe-bad.SKILL.md", PROBE_BAD, True, "skill_head_probe_bad_head_red"),
             ("好头", "mem://probe-good.SKILL.md", PROBE_GOOD, False, "skill_head_probe_good_head_green"))
    streams = {key: io.BytesIO(text.encode("utf-8")) for _label, key, text, _want, _name in feeds}
    saved = getattr(module, "open", None)
    module.open = lambda target, mode="rb": streams[target]      # noqa: ARG005 只用 'rb'
    printed = []
    try:
        for label, key, _text, want_red, name in feeds:
            streams[key].seek(0)
            try:
                problems = module.check_skill_head(key)
            except Exception as exc:  # noqa: BLE001 探针自己抛错也要报出来
                results.append((name, False, "check_skill_head 抛异常：%s: %s" % (type(exc).__name__, exc)))
                printed.append("PROBE %s：check_skill_head 抛异常 %s" % (label, type(exc).__name__))
                continue
            red = bool(problems)
            shape = "description 值里带 ASCII 冒号＋空格" if want_red else "同一个值改成＝号"
            if red == want_red:
                results.append((name, True, ""))
            elif want_red:
                results.append((name, False, "坏头却是绿（装载侧收得下）——真 YAML 解析那一格可能被换成宽容正则或被删了"))
            else:
                results.append((name, False, "好头却红了：%s" % "｜".join(problems)[:200]))
            printed.append("PROBE %s（%s）：%s%s" % (
                label, shape, "红（装载侧收不下）" if red else "绿（0 条问题）",
                "" if red == want_red else " ← 与期望不符"))
            if red and want_red:
                printed.append("PROBE %s 逮住的第一条：%s" % (label, problems[0][:220]))
    finally:
        if saved is None:
            del module.open
        else:
            module.open = saved
    try:
        problems = module.check_skill_head(os.path.abspath(skill_md))
        printed.append("PROBE 本技能 SKILL.md（真读文件那一格）：%s"
                       % ("绿（0 条问题）" if not problems else "红（装载侧收不下）"))
        results.append(("skill_head_self_head_loads", not problems,
                        "本技能 SKILL.md 的头装载侧收不下：%s" % "｜".join(problems)[:200]))
    except Exception as exc:  # noqa: BLE001
        printed.append("PROBE 本技能 SKILL.md：check_skill_head 抛异常 %s" % type(exc).__name__)
        results.append(("skill_head_self_head_loads", False,
                        "check_skill_head 抛异常：%s: %s" % (type(exc).__name__, exc)))
    lines.extend(printed)          # 三发的结果不管绿不绿都要出现在输出里（交代点名的那一格）
    return lines, results


def main():
    parser = argparse.ArgumentParser(description="asuna-offline-selfchecks 的零依赖离线自检（只读）")
    parser.add_argument("skill_md", nargs="?", help="SKILL.md 路径（默认取脚本旁边那份）")
    parser.add_argument("--expect-entries", type=int,
                        help="上一份报告里的私密名单条数；给了才算差值（只报差，不算失败）")
    args = parser.parse_args()
    path = args.skill_md or os.path.join(HERE, "SKILL.md")
    results = []
    notes = []

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

    # 「候选根」一节的关键串（临时脚本落点、白名单扫描、包内容判据、来路那串包 sha）
    for name, token in PACKAGING_RULES:
        check(name, token in body, token)

    # 发布撞 EFFECTIVE_PROJECT_CHANGED 那一节的字面守卫（同上：验字面在不在，不验我照做没有）
    for name, token in PUBLISH_CLASH_GUARDS:
        check(name, token in body, token)

    # 「发布前自检（私密词扫描）」一节：一条判据名，缺哪些关键串写进 detail。
    missing_prepub = [name + "（" + token + "）" for name, token in PREPUB_SCAN_RULES
                      if token not in body]
    check("prepublish_private_word_criterion", not missing_prepub, "、".join(missing_prepub))
    missing_script = [name + "（" + token + "）" for name, token in PREPUB_SCRIPT_RULES if token not in body]
    check("prepublish_script_documented", not missing_script, "、".join(missing_script))

    # 「判据补遗」一节的八条钉：只认本节范围内的字面（别处复述的不算）。
    backlog = section_of(body, BACKLOG_TITLE) or ""
    for name, tokens in BACKLOG_PINS:
        missing = [token for token in tokens if token not in backlog]
        check(name, not missing, "补遗一节里缺：" + "、".join(missing))
    # TEMP 落点这一族（2026-11-02）：提到了临时目录就必须给落点。本技能正文必判；
    # 核心技能那份读得到就一起判（读到哪份写进 detail），读不到打 NOTE——「没真查」不许长得像「过了」。
    temp_missing = []
    if TEMP_MENTION.search(body) and TEMP_LANDING_RULE not in body:
        temp_missing.append("本技能正文")
    core_body, core_path = core_skill_body()
    if core_body is None:
        notes.append("NOTE 读不到核心技能 %s 的正文（试过的位置：%s）——TEMP 落点这一格只真查了本技能正文"
                     % (CORE_SKILL, core_path or "没找到路径"))
    elif TEMP_MENTION.search(core_body) and TEMP_LANDING_RULE not in core_body:
        temp_missing.append("核心技能正文")
    check("temp_rule_present_when_temp_mentioned", not temp_missing,
          "提到临时目录／TEMP 却没写「%s」：%s" % (TEMP_LANDING_RULE, "、".join(temp_missing)))
    # 通用清单回潮：命令字面量回到散文 = 又把核心技能抄了一遍
    regressed = [token for token in GENERIC_SUITE_TOKENS if token in prose]
    check("no_generic_suite_list_in_prose", not regressed, ",".join(regressed))

    # 反引号仓库路径存在性（防 p3 那一族死引用复发）
    root = find_repo_root()
    path_note = ""
    if root:
        tokens = backticked_repo_paths(body)
        missing = [t for t in tokens
                   if not os.path.exists(os.path.join(root, *t.split("/")))
                   and t not in KNOWN_ABSENT]
        check("repo_paths_exist", not missing,
              "%s 下不存在：%s" % (root, ", ".join(missing)))
        path_note = "，反引号仓库路径核过 %d 条" % len(tokens)
    else:
        notes.append("NOTE 没找到仓库根（tests/ tools/ pyproject.toml 同层），反引号仓库路径存在性"
                     "检查跳过——在 checkout 或候选里跑才会真查")

    # 内容级私密词扫描（2026-10-24 补）：development_publish 不扫文件内容，八份里原先只有这份没有。
    # 「没真查」不许长得像「过了」：名单配不上或 0 条都记 leak_scan_ran 红。命中只报 文件:行号:类别。
    listed_path, entries = private_list()
    leak_note = ""
    if entries is None:
        check("leak_scan_ran", False,
              "私密名单没配上（试过 %s）：真人名／群名这一项没真查——不是跑过了"
              % ("、".join(listed_path) if listed_path else "都没有"))
    elif not entries:
        check("leak_scan_ran", False, "名单 0 条（%s）——没真查，不是跑过了" % listed_path)
    else:
        compiled = compile_entries(entries)
        own_files = {os.path.abspath(path)}
        for name in os.listdir(HERE):
            if os.path.isfile(os.path.join(HERE, name)):
                own_files.add(os.path.abspath(os.path.join(HERE, name)))
        own_hits = []
        for target in sorted(own_files):
            text_of = read_utf8(target)
            if text_of is None:
                continue
            for lineno, category in scan_text(compiled, text_of):
                own_hits.append("%s:%d:%s" % (os.path.basename(target), lineno, category))
        check("no_listed_words", not own_hits, "、".join(own_hits))
        # 名单条目数：现读值，不当失败也不钉基线（这个数随我加词长大）。分档数一并打出来，
        # 好与 `private_words summary` 一眼对照；差值只在带 --expect-entries 时算。
        by_cat = {}
        for _number, category, _word in entries:
            by_cat[category] = by_cat.get(category, 0) + 1
        breakdown = "／".join("%s %d" % (cat, by_cat[cat]) for cat in sorted(by_cat))
        leak_note = "，泄露检查扫过（名单现读 %d 条：%s；命中只报类别与行号）" % (len(entries), breakdown)
        odd_cats = sorted({category for _number, category, _word in entries if category not in CATEGORIES})
        check("private_list_categories_known", not odd_cats,
              "名单里有认不出的类别 %s（工具与 pre_publish_scan 只认 %s）——三把尺会数出不同的条目数：%s"
              % ("、".join(odd_cats), "／".join(sorted(CATEGORIES)),
                 "、".join("第%d行 %s" % (number, category)
                           for number, category, _word in entries if category not in CATEGORIES)))
        remedy = "处置：先跑一次 private_words summary 对一次——脚本数到＝工具数到就是我在加词，更掉那个数即可，" \
                 "不要开查道链；只有两边数对不上、或命中位置冒出 %s 以外，才当名单被人改了来查。" % ENVOY_FILE
        if args.expect_entries is None:
            notes.append("NOTE 名单现读 %d 条（%s）。这一格不算失败：这个数会随我加词长大。要差值就带 "
                         "--expect-entries <上一份报告的数> 再跑。" % (len(entries), breakdown))
        elif args.expect_entries != len(entries):
            notes.append("NOTE 名单现读 %d 条，与 --expect-entries %d 差 %+d（只报差、不算失败：这个数会随我加词长大）。%s"
                         % (len(entries), args.expect_entries, len(entries) - args.expect_entries, remedy))
        else:
            notes.append("NOTE 名单现读 %d 条（%s），与 --expect-entries 一致——一致也不等于该把它钉成基线。"
                         % (len(entries), breakdown))
        pkg_root = package_root()
        if pkg_root:
            outside = []
            envoy = 0
            for rel, text_of in walk_texts(pkg_root):
                if text_of is None:
                    continue
                for lineno, category in scan_text(compiled, text_of):
                    if rel == ENVOY_FILE:
                        envoy += 1
                    else:
                        outside.append("%s:%d:%s" % (rel, lineno, category))
            check("no_listed_words_outside_envoy", not outside, "、".join(outside))
            if envoy != BASELINE_ENVOY_HITS:
                notes.append("NOTE %s 命中 %d 处，基线 %d（会漂，不变红；本次改动没动那个文件才算对得上）"
                             % (ENVOY_FILE, envoy, BASELINE_ENVOY_HITS))
        else:
            notes.append("NOTE 没找到包根（上两级要有 package.json 和 skills/），整包扫描没跑——"
                         "只扫了本技能目录，不是整包干净")

    check("selfcheck_documented", "check_skill.py" in body)
    check("no_placeholder_markers", not PLACEHOLDER.search(prose))
    check("skill_body_not_thin", len(body) >= 1500, "body_chars=%d" % len(body))

    # 同目录脚本：必须存在且语法能编译。不落文件，在内存里查（compile(源码, 路径, 'exec')）：
    # 2026-10-18 之前用 py_compile 写 .pyc，先试技能目录旁、再退当前目录，行动脑沙箱里两处都不让写，
    # 这一格只能报「没真查」——检查根本没跑起来。内存 compile 沙箱里外都真查，也不需要临时目录。
    # 分寸：compile() 只查语法，不查 import 和运行时（脚本能编译不等于能跑）。
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    check("check_script_shipped", os.path.basename(__file__) in scripts, ",".join(scripts))

    # 换行：字节级数 CR（文本模式那把尺是瞎的，见 cr_bytes）。覆盖发出去的每一份文本：
    # SKILL.md 加同目录全部 .py。跑的时候要看的是冻结快照，不是候选——候选可能被别人抹平成 LF。
    cr_files = cr_bytes([path] + [os.path.join(HERE, name) for name in scripts])
    check("line_endings_are_lf", not cr_files,
          "有 CR（仓库守卫 test_line_endings 会红）：" + "、".join(cr_files))
    for script in scripts:
        try:
            with open(os.path.join(HERE, script), "rb") as handle:
                source = handle.read()
            compile(source, os.path.join(HERE, script), "exec")
            check("compiles_" + script, True)
        except Exception as exc:  # noqa: BLE001 编译失败要原样报出来
            check("compiles_" + script, False, "%s: %s" % (type(exc).__name__, exc))

    # 第 5 件事的自检针（坏头必须红、好头必须绿、本技能自己的头必须绿）
    probe_lines, probe_results = skill_head_probe(path)
    results.extend(probe_results)

    stray = [d for d in os.listdir(HERE) if d == "__pycache__"]
    if stray:
        notes.append("NOTE 技能目录里有 __pycache__（compileall 留下的），发布前清掉："
                     "find skills -name '__pycache__' -type d -prune -exec rm -rf {} +")

    total = len(results)
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, detail in results:
        if not ok and detail:
            print("FAIL %s  <- %s" % (name, detail))
    for line in probe_lines:                 # 第 5 件事的三发：不管绿不绿都要出现在输出里
        print(line)
    for line in notes:
        print(line)
    if failed:
        print("%d/%d 通过，失败：%s" % (total - len(failed), total, ", ".join(failed)))
        return 1
    print("%d/%d 通过：指向核心技能、增量都在，通用清单没回潮%s%s。" % (total, total, path_note, leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
