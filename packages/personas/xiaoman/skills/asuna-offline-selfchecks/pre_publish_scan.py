#!/usr/bin/env python3
"""pre_publish_scan.py：人格包／通道包发布前的一条命令，并掉原来手敲的几条。只读，不写任何东西。

四件事（前三件是规格，第四件是顺手并进来的「各份 check_skill 全绿」）：
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

用法：
    python3 skills/asuna-offline-selfchecks/pre_publish_scan.py [--expect skills/<名字>]... \\
        [--expect-entries N] [--candidate <候选根>] [--project xiaoman] [--data <数据根>]
默认候选根＝本脚本往上两级（skills/<技能>/ 的上上级）；项目名读候选 package.json 的 name 末段；
ACTIVE 快照＝<数据根>/adr008/activation.json 的 active.<项目>.packageRoot。
把当前 ACTIVE 当候选对拍：`--candidate <ACTIVE 的 packageRoot>`（应当 changed／added／missing 全 0）。
退出码：0 = 通过，可发（最后一行写「通过」，②没判会写进括号）；1 = 停（最后一行列出是哪几条）；
2 = 没法判（候选根／ACTIVE／名单找不到）。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"__pycache__", ".tmp", "node_modules", ".git", ".runtime"}
ENVOY = "integration/envoy_meters_read.py"
CATEGORIES = {"person", "group", "account", "site", "host", "email", "other"}
TEXT_EXT = {".py", ".md", ".json", ".js", ".yml", ".yaml", ".txt", ".html", ".css", ".csv", ".toml", ".cmd", ".sh", ""}
SHOW = 40


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


def show_list(title, items):
    print("  %s %d" % (title, len(items)))
    for item in items[:SHOW]:
        print("     " + item)
    if len(items) > SHOW:
        print("     …另 %d 条" % (len(items) - SHOW))


def under(path, prefixes):
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def main():
    parser = argparse.ArgumentParser(description="发布前扫描（只读）")
    parser.add_argument("--candidate", help="候选根（默认本脚本往上两级）")
    parser.add_argument("--project", help="项目名（默认读候选 package.json 的 name 末段）")
    parser.add_argument("--data", help="数据根（默认自己找）")
    parser.add_argument("--expect", action="append", default=[], help="预期会动的路径前缀，可重复")
    parser.add_argument("--allow-missing", action="append", default=[], help="确实要删的路径，可重复")
    parser.add_argument("--expect-entries", type=int, help="上一份报告里的私密名单条数")
    parser.add_argument("--no-checks", action="store_true", help="不跑各份 check_skill.py")
    args = parser.parse_args()

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

    print()
    if stops:
        print("停：" + "；".join(stops))
        return 1
    print("通过，可发" + ("（" + "；".join(unjudged) + "）" if unjudged else "。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
