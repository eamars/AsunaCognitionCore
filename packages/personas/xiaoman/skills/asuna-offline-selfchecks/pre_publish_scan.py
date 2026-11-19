#!/usr/bin/env python3
"""pre_publish_scan.py：人格包／通道包发布前的一条命令，并掉原来手敲的几条。只读，不写任何东西。

六件事（前三件是规格，第四件是顺手并进来的「各份 check_skill 全绿」，第五件护「我这侧全绿、装载侧全空」那一格，第六件护「正本里手抄的 task 号是真号」那一格）：
  1. 候选 vs ACTIVE 冻结快照：逐文件 sha256 比，列 changed（内容不同）／added（只在候选）／
     missing（只在 ACTIVE、候选里没有＝缺失，防吞）。`--expect <路径前缀>` 可重复：给了就要求
     changed／added 全落在这些前缀里，落到预期之外的算停；missing 默认算停，确实要删的用
     `--allow-missing <路径>` 逐个放行。
  2. 按候选 package.json 的 `files` 白名单扫候选根：根上不在白名单里的路径。ACTIVE 快照里也有的
     （既有的）只报 NOTE，候选新冒出来的（ACTIVE 没有）也只报 NOTE（白名单外＝不进包；11-12 起）；里面一个文件都没有的空目录不进包，只报 NOTE。另报 __pycache__ 残留（发布前要清）
     和 .tmp/ 在不在。
  3. 私密词扫描，按「三岔」判（asuna-offline-selfchecks「发布前自检（私密词扫描）」那一节原样）：
     候选与 ACTIVE 各扫一次整棵根（逐行 find，命中只报 文件＋行号＋类别＋名单行号，不回显词）。
       11-12 起：白名单外、ACTIVE 快照里没有的文件（不进包，ACTIVE 侧永远数到 0）的命中差与「被改」单列成「比对不到」NOTE，不当新增，不停；它不是干净的证据。
       通过：命中全部落在 integration/envoy_meters_read.py，且本次改动零新增命中
             （候选与 ACTIVE 逐文件命中数、命中文件两处对得上）；
       停：① 命中冒出 integration/envoy_meters_read.py 以外的文件；
           ② 名单条目数跟上一份报告对不上（`--expect-entries N`，N 抄上一份报告那一行；
              不给就是「②没判」，最后一行明说，不写成干净）；
           ③ integration/envoy_meters_read.py 本身在这次改动里被改（与 ACTIVE 的 sha 不同）。
     名单读不到或 0 条 → 没真查，算停（退出码 2），不许长得像「过了」。
  4. 对有改动的技能目录跑它自己的 check_skill.py（子进程，sys.executable），报 rc 和最后一行；
     `--no-checks` 可跳过。
  5. 候选根下每份 `SKILL.md` 的头拿真 YAML 解析器解析一遍（`yaml.safe_load`，与 DSH 装载侧
     dsh-skill-filesystem 的 parseFrontmatter 同族：取第一个 `---` 到下一个 `---` 之间那一段）。
     红＝装载侧收不下＝整本技能从行动侧清单里静默消失（它只 warn 一行就 continue）。判据：解析抛错；
     解析出来不是映射；`name`／`description` 缺或不是非空字符串；`name` 不合装载侧的 SKILL_NAME；
     装载侧会抛错的废弃／非布尔 invocation 字段；以及解析器**不抛错**的那道静默——值里「空格＋#」
     被 YAML 当注释、后半截丢掉（只对 plain scalar 判，引号／块标量／流式放过）。
     没有可用的 YAML 库＝这一格没真查，退出码 2，不退化成正则。
     `--skill-heads <根>`（可重复）只跑这一格、不跑其余五件，用来现扫 ACTIVE 那几根。
  6. 候选根下（含各技能目录）每一份 `SKILL.md`／`CHANGELOG.md` 里手抄的 `task-<hex>` 号，能读到库就按
     `tasks._id` 逐枚数行（`asuna.dbread.count`，只读；读法见技能 asuna-database）：零行的判红，列 文件＋行号。
     形状不是「`task-`＋32 位十六进制」的（短号 `task-554c309c` 那一族、或长串的切痕）拿它按 `_id` 等值必然零行，
     所以不按 _id 判——逐枚列成 NOTE 带长度，不静默（那一枚是没判，不是干净）。
     连不到库（import 不了、连不上、返回读不出）＝这一格没真查：只打一行 NOTE 明写「没真查」，
     并进最后一行括号里的未判清单，既不停也不拖红——它不该把整支扫描变成一个红。
     零行默认停；确实要留着当历史账的那一枚（修正记录里被换掉的旧号那一族）用 `--allow-task-id <号>`
     逐个放行，放行当场打一行 NOTE 带文件名——放行是明着记一笔，不是安静。这一格不看 `--expect`（同第⑤件事）。

用法：
    python3 skills/asuna-offline-selfchecks/pre_publish_scan.py [--expect skills/<名字>]... \\
        [--expect-entries N] [--allow-task-id task-<hex>]... [--candidate <候选根>] [--project xiaoman] [--data <数据根>]
    python3 skills/asuna-offline-selfchecks/pre_publish_scan.py --skill-heads <根> [--skill-heads <根2>]...   # 只跑第 5 件事
默认候选根＝本脚本往上两级（skills/<技能>/ 的上上级）；项目名读候选 package.json 的 name 末段；
ACTIVE 快照＝<数据根>/adr008/activation.json 的 active.<项目>.packageRoot。
把当前 ACTIVE 当候选对拍：`--candidate <ACTIVE 的 packageRoot>`（应当 changed／added／missing 全 0）。
退出码：0 = 通过，可发（最后一行写「通过」，②没判会写进括号）；1 = 停（最后一行列出是哪几条）；
2 = 没法判（候选根／ACTIVE／名单找不到／这台机没有可用的 YAML 库）。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

try:                                                            # 第 5 件事的尺子：真解析器，不是正则
    import yaml
except Exception as _yaml_exc:                                  # noqa: BLE001 库不在＝没真查，不降级
    yaml = None
    YAML_IMPORT_ERROR = "%s: %s" % (type(_yaml_exc).__name__, _yaml_exc)
else:
    YAML_IMPORT_ERROR = ""

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"__pycache__", ".tmp", "node_modules", ".git", ".runtime"}
ENVOY = "integration/envoy_meters_read.py"
CATEGORIES = {"person", "group", "account", "site", "host", "email", "other"}
TEXT_EXT = {".py", ".md", ".json", ".js", ".yml", ".yaml", ".txt", ".html", ".css", ".csv", ".toml", ".cmd", ".sh", ""}
SHOW = 40
SKILL_HEAD = "SKILL.md"
# 第 6 件事的扫面与号形：手抄任务号只会出现在这两类正本里；全号＝tasks._id 的形状（task- 加 32 位十六进制），
# 前后各一道边界，别把长串切一刀当成一枚号；号形不合的（短号、切痕）单列成 NOTE，不按 _id 判。
DOC_HEADS = ("SKILL.md", "CHANGELOG.md")
TASK_ID_FULL_LEN = len("task-") + 32
TASK_ID_ANY = re.compile(r"(?<![0-9a-f])task-[0-9a-f]{6,}(?![0-9a-f])")
# 装载侧的硬要求（读码依据：deepseek-harness 的 packages/skill/skill/src/index.ts 的 SKILL_NAME，
# 与 packages/skill/skill-filesystem/src/index.ts 的 parseSkillFile／parseFrontmatter，按名字找不抄行号）
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_INVOCATION = {"disableModelInvocation": "disable-model-invocation",
                     "modelInvocable": "disable-model-invocation",
                     "userInvocable": "user-invocable"}
NON_PLAIN_START = "\"'|>&*?{[@"                # 这些起首不是 plain scalar：截断那一格放过


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def walk(root):
    """{相对路径(/): 绝对路径}，跳过 SKIP_DIRS。"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            full = os.path.join(dirpath, name)
            found[os.path.relpath(full, root).replace(os.sep, "/")] = full
    return found


def find_data(explicit):
    if explicit:
        return explicit
    env = os.environ.get("ASUNA_DATA_ROOT")
    if env:
        return env
    try:
        from asuna import config as asuna_config
        return str(asuna_config.DATA)
    except Exception:                                   # noqa: BLE001
        pass
    here = HERE
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        if os.path.isdir(os.path.join(here, ".runtime", "adr008")):
            return os.path.join(here, ".runtime")
    return None


def load_list(data):
    """私密名单：返回 (路径, [(行号, 类别, 词)]) 或 (试过的候选, None)。"""
    candidates = []
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
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
    for path in candidates:
        if path and os.path.isfile(path):
            entries = []
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    parts = line.strip().split("|", 2)
                    if line.strip() and not line.strip().startswith("#") and len(parts) == 3 \
                            and parts[0].strip() in CATEGORIES and parts[1].strip():
                        entries.append((number, parts[0].strip(), parts[1].strip()))
            return path, entries
    return candidates, None


def compile_entries(entries):
    out = []
    for number, category, word in entries:
        escaped = re.escape(word)
        if all(ch.isascii() for ch in word):
            rx = re.compile(r"(?<![A-Za-z0-9_])" + escaped + r"(?![A-Za-z0-9_])", re.IGNORECASE)
        else:
            rx = re.compile(escaped)
        out.append((number, category, rx))
    return out


def scan_hits(root, compiled):
    """{相对路径: [(行号, 类别, 名单行号)]}；二进制和读不了的跳过并计数。"""
    hits = {}
    skipped = 0
    for rel, full in walk(root).items():
        ext = os.path.splitext(rel)[1].lower()
        if ext not in TEXT_EXT:
            skipped += 1
            continue
        try:
            with open(full, "rb") as handle:
                raw = handle.read()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            skipped += 1
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for number, category, rx in compiled:
                if rx.search(line):
                    hits.setdefault(rel, []).append((lineno, category, number))
    return hits, skipped


def task_id_hits(root):
    """第 6 件事的扫面：根下每份 SKILL.md／CHANGELOG.md 里手抄的 task 号（11-19 加）。
    返回 ({_id 号形: [(相对路径, 行号)]}, {号形不合的: [(相对路径, 行号)]})——后者单列，不当零行判。"""
    full, short = {}, {}
    for rel, absolute in walk(root).items():
        if os.path.basename(rel) not in DOC_HEADS:
            continue
        try:
            with open(absolute, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for token in TASK_ID_ANY.findall(line):
                bucket = full if len(token) == TASK_ID_FULL_LEN else short
                bucket.setdefault(token, []).append((rel, lineno))
    return full, short


def task_id_rows(ids):
    """按 tasks._id 逐枚数行（asuna.dbread，只读）。任何一环不顺利就直接往外抛：
    调用方拿它走 NOTE 那条「没真查」的路，不在这儿替它兜成干净。"""
    from asuna import dbread
    rows = {}
    for token in sorted(ids):
        rows[token] = int(dbread.count("tasks", {"_id": token})["found"])
    return rows


def show_list(title, items):
    print("  %s %d" % (title, len(items)))
    for item in items[:SHOW]:
        print("     " + item)
    if len(items) > SHOW:
        print("     …另 %d 条" % (len(items) - SHOW))


def under(path, prefixes):
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def split_head(text):
    """照装载侧 parseFrontmatter／findClosingFrontmatter 的形状取 `---` 之间那一段。返回 (段, 问题列表)。"""
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return None, ["头的第一行不是逐字的 ---（装载侧判 missing YAML frontmatter，整本忽略）"]
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            return "\n".join(lines[1:i]), []
    return None, ["头没有闭合的 ---（装载侧判 missing YAML frontmatter，整本忽略）"]


def plain_value_cut(value):
    """plain scalar 里 YAML 真会起注释的那个 #：行首的，或前面是空白／制表的。返回 (留下的, 丢掉的) 或 None。"""
    for i, ch in enumerate(value):
        if ch == "#" and (i == 0 or value[i - 1] in " \t"):
            kept, lost = value[:i].rstrip(), value[i + 1:].strip()
            return (kept, lost) if (kept != value.strip() or lost) else None
    return None


def head_truncations(head, data):
    """解析器不抛错的第二种静默：值被 # 吃掉后半截。只有拿原文对才看得见，所以这里成对判。"""
    out = []
    if not isinstance(data, dict):
        return out
    for offset, line in enumerate(head.split("\n")):
        raw = line.rstrip("\r")
        if not raw or raw[0] in " \t#" or ":" not in raw:
            continue                                            # 只判顶层「key: 值」那一行
        key, _, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$", key):
            continue
        if not value or value[0] in NON_PLAIN_START:
            continue                                            # 空值／引号／块标量／流式：不判
        cut = plain_value_cut(value)
        if cut is None:
            continue
        kept, lost = cut
        out.append("第%d行 %s 的值被 YAML 当注释截断：装载侧只拿到「%s」，丢掉「%s」"
                   % (offset + 2, key, kept[:60], lost[:60]))
    return out


def check_skill_head(path):
    """真 YAML 解析一份 SKILL.md 的头。返回问题列表：空＝装载侧收得下这一本。"""
    if yaml is None:
        return ["这台机没有可用的 YAML 库（%s）——这一格没真查，不许长得像「过了」" % YAML_IMPORT_ERROR]
    try:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ["读不到或不是 UTF-8（%s）" % exc]
    head, problems = split_head(text)
    if problems:
        return problems
    try:
        data = yaml.safe_load(head)
    except yaml.YAMLError as exc:
        return ["真 YAML 解析抛错（装载侧同一件事：warn 一行就 continue，整本静默消失）：%s"
                % " ｜ ".join(str(exc).strip().splitlines())[:300]]
    if not isinstance(data, dict):
        return ["头解析出来不是映射（是 %s）——装载侧判 missing YAML frontmatter，整本忽略" % type(data).__name__]
    name, desc = data.get("name"), data.get("description")
    if not isinstance(name, str) or not name:
        problems.append("name 缺或不是非空字符串——装载侧：frontmatter requires name and description，整本忽略")
    elif not SKILL_NAME_RE.match(name):
        problems.append("name「%s」不合装载侧的 SKILL_NAME（小写字母数字加连字符），整本忽略" % name)
    if not isinstance(desc, str) or not desc:
        problems.append("description 缺或不是非空字符串——装载侧：frontmatter requires name and description，整本忽略")
    for legacy, canonical in sorted(LEGACY_INVOCATION.items()):
        if legacy in data:
            problems.append("frontmatter 字段「%s」装载侧不收（用「%s」），整本忽略" % (legacy, canonical))
    for key in ("disable-model-invocation", "user-invocable"):
        if key in data and not isinstance(data[key], bool) and data[key] not in (1, 0, "1", "0"):
            problems.append("frontmatter 字段「%s」装载侧要求布尔，现在是 %r，整本忽略" % (key, data[key]))
    problems.extend(head_truncations(head, data))
    return problems


def find_skill_heads(root):
    """根下字面存在的全部 SKILL.md（skills/<名字>/、<名字>/ 两种形状都算），按相对路径排。"""
    return [(rel, full) for rel, full in sorted(walk(root).items()) if os.path.basename(rel) == SKILL_HEAD]


def report_skill_heads(roots):
    """跑第 5 件事。返回 (份数, [(相对路径, [问题])])；每份的红当场打印。"""
    total, bad = 0, []
    for root in roots:
        found = find_skill_heads(root)
        total += len(found)
        print("  根 %s：%d 份" % (root, len(found)))
        for rel, full in found:
            problems = check_skill_head(full)
            if problems:
                bad.append((rel, problems))
                for p in problems:
                    print("     WARNING %s：%s" % (rel, p))
    return total, bad


def main():
    parser = argparse.ArgumentParser(description="发布前扫描（只读）")
    parser.add_argument("--candidate", help="候选根（默认本脚本往上两级）")
    parser.add_argument("--project", help="项目名（默认读候选 package.json 的 name 末段）")
    parser.add_argument("--data", help="数据根（默认自己找）")
    parser.add_argument("--expect", action="append", default=[], help="预期会动的路径前缀，可重复")
    parser.add_argument("--allow-missing", action="append", default=[], help="确实要删的路径，可重复")
    parser.add_argument("--expect-entries", type=int, help="上一份报告里的私密名单条数")
    parser.add_argument("--allow-task-id", action="append", default=[],
                        help="第 6 件事：库里零行但确实要留作历史账的 task 号，逐个放行（可重复）")
    parser.add_argument("--no-checks", action="store_true", help="不跑各份 check_skill.py")
    parser.add_argument("--skill-heads", action="append", default=[],
                        help="只跑第 5 件事（SKILL.md 头真 YAML 解析）于这些根，可重复；其余四件不跑")
    args = parser.parse_args()

    if args.skill_heads:
        print("只跑第 5 件事：SKILL.md 头拿真 YAML 解析器解析一遍（装载侧同族）")
        if yaml is None:
            print("  这台机没有可用的 YAML 库（%s）——这一格没真查，不退化成正则。" % YAML_IMPORT_ERROR)
            return 2
        print("  YAML 库：PyYAML %s（%s）" % (getattr(yaml, "__version__", "?"), yaml.__file__))
        missing = [r for r in args.skill_heads if not os.path.isdir(r)]
        if missing:
            print("  根读不到：%s" % "、".join(missing))
            return 2
        total, bad = report_skill_heads([os.path.abspath(r) for r in args.skill_heads])
        print("\n扫了 %d 份 SKILL.md，红 %d 份" % (total, len(bad)))
        if not total:
            print("NOTE 这些根下一份 SKILL.md 都没有——这一格没东西可查，不是干净。")
        if bad:
            print("停：%d 份的头装载侧收不下：%s" % (len(bad), "、".join(rel for rel, _ in bad)))
            return 1
        print("通过，头全解析得动。")
        return 0

    candidate = os.path.abspath(args.candidate or os.path.dirname(os.path.dirname(HERE)))
    pkg_path = os.path.join(candidate, "package.json")
    try:
        with open(pkg_path, encoding="utf-8") as handle:
            pkg = json.load(handle)
    except (OSError, ValueError) as exc:
        print("候选根读不到 package.json：%s（%s）" % (pkg_path, exc))
        return 2
    project = args.project or str(pkg.get("name", "")).split("/")[-1]
    data = find_data(args.data)
    if not data:
        print("没找到数据根：带 --data <数据根>。")
        return 2
    try:
        with open(os.path.join(data, "adr008", "activation.json"), encoding="utf-8") as handle:
            activation = json.load(handle)
    except (OSError, ValueError) as exc:
        print("读不到 activation.json：%s" % exc)
        return 2
    active = (activation.get("active") or {}).get(project) or {}
    base = active.get("packageRoot")
    if not base or not os.path.isdir(base):
        print("active.%s 没有可读的 packageRoot（%s）。" % (project, base))
        return 2
    print("候选根 =", candidate)
    print("项目 = %s；ACTIVE 快照 = %s（sha256 %s，activated_at %s）"
          % (project, base, active.get("sha256"), active.get("activated_at")))

    stops = []
    # ---- 1. 候选 vs ACTIVE
    print("\n== 1. 候选 vs ACTIVE 冻结快照（逐文件 sha256；跳过 %s） ==" % "、".join(sorted(SKIP_DIRS)))
    cand_files, base_files = walk(candidate), walk(base)
    changed = sorted(r for r in cand_files if r in base_files and sha256(cand_files[r]) != sha256(base_files[r]))
    added = sorted(r for r in cand_files if r not in base_files)
    missing = sorted(r for r in base_files if r not in cand_files)
    print("  候选 %d 个文件，ACTIVE %d 个文件" % (len(cand_files), len(base_files)))
    show_list("changed（内容不同）", changed)
    show_list("added（只在候选）", added)
    show_list("missing（ACTIVE 有、候选没有＝缺失）", missing)
    bad_missing = [m for m in missing if not under(m, args.allow_missing)]
    if bad_missing:
        stops.append("缺失 %d 个文件（没被 --allow-missing 放行）" % len(bad_missing))
    if args.expect:
        outside = [p for p in changed + added if not under(p, args.expect)]
        if outside:
            show_list("落在 --expect 之外的 changed／added", outside)
            stops.append("改动落到预期之外 %d 个文件" % len(outside))
        else:
            print("  changed／added 全落在 --expect %s 之内" % args.expect)
    else:
        print("  （没给 --expect：只列不判范围）")

    # ---- 2. files 白名单
    print("\n== 2. package.json `files` 白名单扫候选根 ==")
    allow = [str(x).rstrip("/") for x in pkg.get("files", [])]
    always = {"package.json", "README.md", "README", "LICENSE", "LICENCE", "CHANGELOG.md"}
    top = sorted(os.listdir(candidate))
    base_top = set(os.listdir(base))
    extras = [e for e in top if e not in SKIP_DIRS and e not in always
              and not any(fnmatch.fnmatch(e, a.split("/")[0]) for a in allow)]
    def has_files(entry):
        full = os.path.join(candidate, entry)
        return os.path.isfile(full) or any(fs for _d, _ds, fs in os.walk(full))
    empty_extras = [e for e in extras if e not in base_top and not has_files(e)]
    extras = [e for e in extras if e not in empty_extras]
    new_extras = [e for e in extras if e not in base_top]
    old_extras = [e for e in extras if e in base_top]
    print("  白名单：%s" % "、".join(allow))
    show_list("根上白名单外、ACTIVE 里也有的（既有，NOTE）", old_extras)
    show_list("根上白名单外、ACTIVE 里没有的（新冒出来，不进包，NOTE；里面有私密词命中的照样在第 3 件事里停）", new_extras)
    if empty_extras:
        show_list("根上白名单外的空目录（没有文件，不进包，NOTE）", empty_extras)
    stray = sorted(r for r in (os.path.relpath(os.path.join(d, n), candidate).replace(os.sep, "/")
                               for d, ns, _fs in os.walk(candidate) for n in ns if n == "__pycache__"))
    if stray:
        show_list("__pycache__ 残留（发布前要清：find . -name '__pycache__' -type d -prune -exec rm -rf {} +）", stray)
        stops.append("__pycache__ 残留 %d 处" % len(stray))
    print("  .tmp/ %s" % ("在候选根里（不进比对；发布前确认没有要留的东西）" if os.path.isdir(os.path.join(candidate, ".tmp")) else "不在"))

    # ---- 3. 私密词三岔
    print("\n== 3. 私密词扫描（三岔判据） ==")
    listed_path, entries = load_list(data)
    unjudged = []
    if entries is None:
        print("  名单没配上（试过 %s）——没真查，不是干净。" % "、".join(listed_path))
        print("\n停：私密词名单读不到，这一件没真查。")
        return 2
    if not entries:
        print("  名单 %s 里 0 条有效词——没真查，不是干净。" % listed_path)
        print("\n停：私密词名单 0 条，这一件没真查。")
        return 2
    compiled = compile_entries(entries)
    cand_hits, cand_skip = scan_hits(candidate, compiled)
    base_hits, base_skip = scan_hits(base, compiled)
    total_c = sum(len(v) for v in cand_hits.values())
    total_b = sum(len(v) for v in base_hits.values())
    print("  名单条目数：%d" % len(entries))
    print("  TOTAL HITS（候选）: %d；落在 %d 个文件；ACTIVE 对照：%d 处、%d 个文件；跳过的非文本／读不了：候选 %d、ACTIVE %d"
          % (total_c, len(cand_hits), total_b, len(base_hits), cand_skip, base_skip))
    for rel in sorted(cand_hits):
        cats = {}
        for _ln, cat, _num in cand_hits[rel]:
            cats[cat] = cats.get(cat, 0) + 1
        print("     %s：%d 处（类别 %s）" % (rel, len(cand_hits[rel]), "、".join("%s×%d" % kv for kv in sorted(cats.items()))))
    outside = sorted(r for r in cand_hits if r != ENVOY)
    if outside:
        for rel in outside:
            print("     ⚠ %s：%s" % (rel, "；".join("第%d行 %s（名单第%d行）" % h for h in cand_hits[rel][:10])))
        stops.append("① 命中冒出 %s 以外的文件：%s" % (ENVOY, "、".join(outside)))
    cand_counts = {r: len(v) for r, v in cand_hits.items()}
    base_counts = {r: len(v) for r, v in base_hits.items()}

    def shipped(rel):
        """这个路径会不会进包：顶层段在 files 白名单里（或是总带的几个文件）。"""
        head = rel.split("/")[0]
        return head in always or any(fnmatch.fnmatch(head, a.split("/")[0]) for a in allow)

    if cand_counts != base_counts:
        diff = sorted(set(cand_counts) | set(base_counts))
        delta, unmatched = [], []
        for r in diff:
            if cand_counts.get(r, 0) == base_counts.get(r, 0):
                continue
            line = "%s：ACTIVE %d → 候选 %d" % (r, base_counts.get(r, 0), cand_counts.get(r, 0))
            # 白名单外、ACTIVE 快照里根本没有的文件：不进包，ACTIVE 侧永远数到 0，这是「比对不到」，不是「新增」。
            (unmatched if (r not in base_files and not shipped(r)) else delta).append(line)
        if unmatched:
            print("  NOTE 比对不到（白名单外、ACTIVE 快照里没有这个文件，不进包，不算新增，不停）：" + "；".join(unmatched))
        if delta:
            print("  命中与 ACTIVE 不一致：" + "；".join(delta))
            stops.append("本次改动命中数／命中文件与 ACTIVE 对不上（有新增或消失）：" + "；".join(delta))
    if ENVOY in cand_files and ENVOY not in base_files and not shipped(ENVOY):
        print("  NOTE %s 不进包、ACTIVE 快照里没有：③ 比对不到，不判「被改」（不是干净的证据，只是没有可对的东西）" % ENVOY)
    elif ENVOY in cand_files and (ENVOY not in base_files or sha256(cand_files[ENVOY]) != sha256(base_files[ENVOY])):
        stops.append("③ %s 本身在这次改动里被改" % ENVOY)
    elif ENVOY not in cand_files and ENVOY in base_files:
        stops.append("③ %s 在候选里没了" % ENVOY)
    if args.expect_entries is None:
        unjudged.append("② 名单条数没对（没给 --expect-entries；本次 %d 条，抄进报告给下一次用）" % len(entries))
        print("  ② 名单条数：没给 --expect-entries，没判。本次 %d 条。" % len(entries))
    elif args.expect_entries != len(entries):
        stops.append("② 名单条数 %d 与上一份报告 %d 对不上" % (len(entries), args.expect_entries))
    else:
        print("  ② 名单条数 %d 与上一份报告一致。" % len(entries))

    # ---- 4. 各份 check_skill
    if not args.no_checks:
        print("\n== 4. 有改动的技能目录跑自己的 check_skill.py ==")
        dirs = sorted({"/".join(p.split("/")[:2]) for p in changed + added if p.startswith("skills/") and p.count("/") >= 2})
        if not dirs:
            print("  没有技能目录有改动。")
        for d in dirs:
            script = os.path.join(candidate, *d.split("/"), "check_skill.py")
            if not os.path.isfile(script):
                print("  %s：没有 check_skill.py（不判）" % d)
                continue
            done = subprocess.run([sys.executable, script], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120, cwd=candidate)
            lines = [l for l in (done.stdout or "").strip().splitlines() if l.strip()]
            print("  %s：rc=%d  %s" % (d, done.returncode, lines[-1] if lines else (done.stderr or "").strip()[-200:]))
            if done.returncode != 0:
                stops.append("%s 的 check_skill.py rc=%d" % (d, done.returncode))

    # ---- 5. SKILL.md 头：真 YAML 解析（装载侧那把尺）
    print("\n== 5. SKILL.md 头：真 YAML 解析（与 DSH 装载侧同族；解析不动＝整本静默消失） ==")
    if yaml is None:
        print("  这台机没有可用的 YAML 库（%s）——这一格没真查，不是干净。" % YAML_IMPORT_ERROR)
        print("\n停：第 5 件事没真查（没有 YAML 库）；不退化成正则。")
        return 2
    print("  YAML 库：PyYAML %s（%s）" % (getattr(yaml, "__version__", "?"), yaml.__file__))
    head_total, head_bad = report_skill_heads([candidate])
    print("  扫了 %d 份 SKILL.md，红 %d 份" % (head_total, len(head_bad)))
    if not head_total:
        print("  NOTE 候选根下一份 SKILL.md 都没有——这一格没东西可查（不因此判干净）")
    if head_bad:
        stops.append("⑤ %d 份 SKILL.md 的头装载侧收不下：%s" % (len(head_bad), "、".join(rel for rel, _ in head_bad)))

    # ---- 6. 正本里手抄的 task 号真伪（11-19 加；能读库就按 tasks._id 数行，连不到库只打 NOTE 不拖红）
    print("\n== 6. 正本里手抄的 task-<hex> 号：按 tasks._id 数行（只读；SKILL.md／CHANGELOG.md） ==")
    id_hits, id_short = task_id_hits(candidate)
    print("  按 _id 号形判 %d 枚（出现 %d 处）；号形不合、不按 _id 判 %d 枚"
          % (len(id_hits), sum(len(v) for v in id_hits.values()), len(id_short)))
    for token in sorted(id_short):
        print("     号形不合 tasks._id 的 %s（十六进制 %d 位，不是 32 位——这一枚没按 _id 判，不是干净）：%s"
              % (token, len(token) - len("task-"), "、".join("%s:%d" % w for w in id_short[token])))
    if not id_hits:
        print("  NOTE 候选里没有 _id 号形的手抄 task 号——这一格没东西可查，不因此判干净。")
    else:
        try:
            rows = task_id_rows(id_hits)
        except Exception as exc:                                    # noqa: BLE001 连不到库＝没真查，不拖红
            unjudged.append("⑥ 没真查（读不到库：%s：%s）" % (type(exc).__name__, exc))
            print("  NOTE 没真查：连不到库（%s：%s）——这一件没判，不算干净。" % (type(exc).__name__, exc))
        else:
            for token in sorted(t for t in args.allow_task_id if t not in id_hits):
                print("  NOTE --allow-task-id %s 指向候选里根本没有的号——这一枚没东西可放行。" % token)
            dead, let_go = [], 0
            for token in sorted(id_hits):
                if rows[token]:
                    continue
                where = "、".join("%s:%d" % w for w in id_hits[token])
                if token in args.allow_task_id:
                    let_go += 1
                    print("  NOTE 放行（库里零行，明着留作历史账）%s：%s" % (token, where))
                else:
                    dead.append("%s（%s）" % (token, where))
            print("  库里数到：非零 %d 枚、零行 %d 枚（其中放行 %d 枚）"
                  % (sum(1 for t in id_hits if rows[t]), sum(1 for t in id_hits if not rows[t]), let_go))
            if dead:
                stops.append("⑥ %d 枚手抄 task 号在 tasks 里零行：%s" % (len(dead), "；".join(dead)))

    print()
    if stops:
        print("停：" + "；".join(stops))
        return 1
    print("通过，可发" + ("（" + "；".join(unjudged) + "）" if unjudged else "。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
