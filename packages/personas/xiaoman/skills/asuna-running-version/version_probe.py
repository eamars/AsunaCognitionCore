#!/usr/bin/env python3
"""asuna-running-version 的探针：只读，回答「现在跑的是哪版」。

四段，全是读，不写任何东西：

1. 监工那次重启记下的实况（<data>/restart/last.json）：result、checkout、loaded
2. 发布选择（<adr008>/activation.json）：每个 project 的 state／candidate／published_at／changed_files，
   以及 active（上次真跑起来的那份）
3. 内容比对：把检出的源码和在跑那份（selection 的 workerPath／packageRoot）逐文件比 sha256
4. git 事实：HEAD、本机记的 origin/main、GitHub 上的 main、落后／超前几笔、有没有未提交的改动

用法：
    python3 version_probe.py                      # 自动找（asuna.config 的 ROOT／DATA，或环境变量）
    python3 version_probe.py --repo <检出根> --data <数据根> --project core
退出码 0 = 四段都跑到了（内容不同、落后几笔都不算错，是要我读的数）；
1 = 该找到的东西没找到（会说清哪一段缺）。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就 UnicodeEncodeError 整段崩
# （2026-10-15 实测）。我的沙箱 env 带 PYTHONUTF8=1／PYTHONIOENCODING=utf-8，自检撞不到这一族。
# 输出字节固定成 UTF-8：那种控制台顶多显示成乱码，不再崩；stderr 同理，报错才看得见。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

PROJECT_SRC = {                      # 检出里对应的位置
    "core": ("src",),
    "xiaoman": ("packages/personas/xiaoman",),
}


def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def find_roots():
    """检出的 ROOT 与这个 profile 的 DATA：能用 asuna.config 就用它，否则退回环境变量。"""
    try:
        from asuna import config as asuna_config
        return str(asuna_config.ROOT), str(asuna_config.DATA)
    except Exception:                                  # noqa: BLE001 没装 asuna 也要能跑
        pass
    data = os.environ.get("ASUNA_DATA_ROOT")
    repo = os.environ.get("ASUNA_REPO")
    if data and repo:
        return repo, data
    return None, data


def git(repo, *args):
    try:
        done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=120)
    except Exception as exc:                           # noqa: BLE001 git 不在也要能报清楚
        return 1, "", str(exc)
    return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError:
        return None
    except ValueError as exc:
        return {"_坏在哪": "%s: %s" % (type(exc).__name__, exc)}


def part_restart(data):
    section("1. 监工记下的那次重启（<data>/restart/last.json）")
    record = read_json(os.path.join(data, "restart", "last.json"))
    if record is None:
        print("没有这份记录：这台机器上还没有过被监工记下的重启。")
        print("这一格缺 ≠ 没装：restart_from_program 只在有记录且起来不到 24 小时时才给我。")
        return False
    print("down_at:", record.get("down_at"), " back_at:", record.get("back_at"))
    print("result:", record.get("result"), " rung:", record.get("rung"), " asked:", record.get("asked"))
    print("checkout:", json.dumps(record.get("checkout"), ensure_ascii=False))
    print("  diverged = 本机比远端新（或分叉），不是没装；changed_files = 有未提交改动，跳过快进")
    loaded = record.get("loaded")
    if not loaded:
        print("loaded: 这一格是空的（那次没记上）")
        return False
    print("loaded.commit:", loaded.get("commit"))
    print("loaded.packages:")
    for name, digest in sorted((loaded.get("packages") or {}).items()):
        print("   %-42s %s" % (name, digest))
    print("loaded.selections:")
    for project, value in sorted((loaded.get("selections") or {}).items()):
        print("   %-12s %s" % (project, json.dumps(value, ensure_ascii=False)))
    return True


def part_activation(data, project):
    section("2. 发布选择（<adr008>/activation.json）")
    path = os.path.join(data, "adr008", "activation.json")
    activation = read_json(path)
    if activation is None:
        print("找不到", path)
        return None
    print("文件:", path)
    for project_id, value in sorted((activation.get("projects") or {}).items()):
        mark = "  <= 我关心的" if project_id == project else ""
        print("%s: state=%s candidate=%s published_at=%s changed_files=%d%s"
              % (project_id, value.get("state"), str(value.get("candidate"))[:12],
                 value.get("published_at"), len(value.get("changed_files") or []), mark))
    active = activation.get("active") or {}
    print("\nactive（上次真跑起来的那份）：")
    for project_id, value in sorted(active.items()):
        print("%s: state=%s sha256=%s activated_at=%s"
              % (project_id, value.get("state"), str(value.get("sha256"))[:12], value.get("activated_at")))
    return (activation.get("projects") or {}).get(project)


def part_content(repo, project, selection):
    section("3. 内容比对：检出的源码 vs 在跑那份（逐文件 sha256）")
    if not selection:
        print("activation.json 里没有这个 project，跳过。")
        return True
    where = selection.get("workerPath") or selection.get("packageRoot")
    if not where or not os.path.isdir(where):
        print("在跑那份的目录找不到：", where)
        return False
    src_dirs = [os.path.join(repo, *PROJECT_SRC.get(project, ())) ] if project in PROJECT_SRC else []
    src = os.path.join(src_dirs[0], "asuna") if project == "core" else src_dirs[0]
    run = os.path.join(where, "asuna") if project == "core" else where
    if not os.path.isdir(src) or not os.path.isdir(run):
        print("比不了：", src, os.path.isdir(src), run, os.path.isdir(run))
        return False
    def walk(base):
        found = {}
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".tmp", "node_modules")]
            for name in filenames:
                full = os.path.join(dirpath, name)
                found[os.path.relpath(full, base)] = sha256(full)
        return found
    left, right = walk(src), walk(run)
    common = sorted(set(left) & set(right))
    diff = [name for name in common if left[name] != right[name]]
    print("检出:", src)
    print("在跑:", run)
    print("可比文件 %d，内容不同 %d" % (len(common), len(diff)))
    for name in diff[:20]:
        print("   不同:", name)
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    if only_left:
        print("只在检出里有（%d）：%s" % (len(only_left), "、".join(only_left[:12])))
    if only_right:
        print("只在跑的那份里有（%d）：%s" % (len(only_right), "、".join(only_right[:12])))
    return True


def part_git(repo):
    section("4. git 事实（只读命令；检出对我不可写）")
    if not repo or not os.path.isdir(os.path.join(repo, ".git")):
        print("找不到检出仓库：", repo)
        return False
    head = git(repo, "rev-parse", "--short", "HEAD")[1]
    local_origin = git(repo, "rev-parse", "--short", "refs/remotes/origin/main")[1]
    remote = git(repo, "ls-remote", "origin", "refs/heads/main")[1]
    remote_sha = remote.split()[0][:8] if remote else "?"
    behind = git(repo, "rev-list", "--count", "HEAD..refs/remotes/origin/main")[1]
    ahead = git(repo, "rev-list", "--count", "refs/remotes/origin/main..HEAD")[1]
    print("HEAD:", head, " 本机记的 origin/main:", local_origin, " GitHub 上的 main:", remote_sha)
    print("落后本机记的 origin/main:", behind, "笔；超前:", ahead, "笔")
    print("（远端真值看 ls-remote；本机记的 origin/* 只在宿主 fetch 时才动，可能是旧的）")
    dirty = git(repo, "status", "--porcelain", "--untracked-files=no")[1]
    print("未提交的改动：%d 个文件" % (len([line for line in dirty.split("\n") if line.strip()])))
    for line in [line for line in dirty.split("\n") if line.strip()][:10]:
        print("   ", line)
    print("脏工作区 → 启动器的 fastForwardCheckout 会跳过快进（changed_files），不覆盖不报错：本机长期落后一格不是故障。")
    return True


def main():
    parser = argparse.ArgumentParser(description="现在跑的是哪版（只读探针）")
    parser.add_argument("--repo", help="检出的根目录（默认从 asuna.config.ROOT 或 ASUNA_REPO 找）")
    parser.add_argument("--data", help="这个 profile 的数据根（默认 asuna.config.DATA 或 ASUNA_DATA_ROOT）")
    parser.add_argument("--project", default="core", help="要比内容的 project（默认 core）")
    args = parser.parse_args()
    found_repo, found_data = find_roots()
    repo = args.repo or found_repo
    data = args.data or found_data
    print("repo =", repo or "（没找到）")
    print("data =", data or "（没找到）")
    if not data:
        print("没有数据根就什么都查不到：带 --data <数据根> 再跑。")
        return 1
    ok = []
    ok.append(part_restart(data))
    selection = part_activation(data, args.project)
    ok.append(part_content(repo or "", args.project, selection))
    ok.append(part_git(repo or ""))
    print("\n读法：state 只有 ACTIVE 是在跑；包 sha 会变，比内容要比文件；"
          "checkout 的 diverged／changed_files 都不是「没装」。")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
