#!/usr/bin/env python3
"""skill_roster.py：数「这条道上有哪几份技能」——群／别人私聊／家里各几份、各是谁。

只读。输入＝各生效包 `skills/*/SKILL.md` 的头部（frontmatter）里的 `scene_kinds`；输出名单加个数。
口径（照 asuna-outbound-round 正文「别编名字」那一节）：
  - 群 ＝ scene_kinds 里有 group；别人私聊 ＝ 有 dm；
  - 家里 ＝ 有 home，或者头部根本没写 scene_kinds（没写的按只在家里算，例：只在家里可用那几份）；
  - 一份技能可以同时在几处；同名技能出现在两个根里只算一份（并报出来）。

默认的根：<数据根>/adr008/activation.json 里 `active.<项目>.packageRoot` 下的 `skills/`
（生效根；node_modules 里那份是装在盘上的位置，不算）。数据根按 --data、环境变量
ASUNA_DATA_ROOT、asuna.config.DATA、从本脚本往上找 `.runtime` 的顺序找。
也可以用 --root <skills 目录或包根> 指定（可重复），这时不读 activation.json——
发布前拿候选根当输入就是这么用：`--root <候选根>`。

用法：
    python3 skill_roster.py                  # 读生效根
    python3 skill_roster.py --root <包根>     # 读指定根（候选）
    python3 skill_roster.py --json           # 机器可读
退出码：0 = 数出来了；1 = 一个根都没找到／没有读到任何技能。
"""
import argparse
import json
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))


def find_data(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("ASUNA_DATA_ROOT")
    if env:
        return env
    try:
        from asuna import config as asuna_config
        return str(asuna_config.DATA)
    except Exception:                                   # noqa: BLE001 没装 asuna 也要能跑
        pass
    here = HERE
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        if os.path.isdir(os.path.join(here, ".runtime", "adr008")):
            return os.path.join(here, ".runtime")
    return None


def active_skill_roots(data):
    """返回 [(标签, skills 目录)]；activation.json 读不到返回 (None, 说明)。"""
    path = os.path.join(data, "adr008", "activation.json")
    try:
        with open(path, encoding="utf-8") as handle:
            activation = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, "读不到 %s：%s" % (path, exc)
    roots = []
    for project, value in sorted((activation.get("active") or {}).items()):
        base = (value or {}).get("packageRoot")
        if not base:
            continue
        skills = os.path.join(base, "skills")
        if os.path.isdir(skills):
            roots.append((project, skills))
    return roots, None


def explicit_roots(values):
    roots = []
    for value in values:
        skills = os.path.join(value, "skills")
        target = skills if os.path.isdir(skills) else value
        roots.append((os.path.basename(os.path.normpath(value)) or value, target))
    return roots


def read_kinds(skill_md):
    """返回 (name, kinds 列表或 None)；头部读不出来返回 (None, None)。"""
    with open(skill_md, "rb") as handle:
        text = handle.read().decode("utf-8", "replace")
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    fields = {}
    for line in text[3:end].strip("\n").splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    raw = fields.get("scene_kinds")
    kinds = re.findall(r"[a-z_]+", raw) if raw is not None else None
    return fields.get("name"), kinds


def collect(roots):
    skills = {}
    dupes = []
    bad = []
    for label, skills_dir in roots:
        for entry in sorted(os.listdir(skills_dir)):
            md = os.path.join(skills_dir, entry, "SKILL.md")
            if not os.path.isfile(md):
                continue
            name, kinds = read_kinds(md)
            if name is None:
                bad.append("%s/%s（头部读不出来）" % (label, entry))
                continue
            if name in skills:
                dupes.append("%s（%s 与 %s）" % (name, skills[name]["root"], label))
                continue
            skills[name] = {"root": label, "kinds": kinds}
    return skills, dupes, bad


def build(skills):
    group = sorted(n for n, v in skills.items() if v["kinds"] and "group" in v["kinds"])
    dm = sorted(n for n, v in skills.items() if v["kinds"] and "dm" in v["kinds"])
    home = sorted(n for n, v in skills.items() if v["kinds"] is None or "home" in v["kinds"])
    no_kinds = sorted(n for n, v in skills.items() if v["kinds"] is None)
    home_not = sorted(n for n in skills if n not in home)
    return {"group": group, "dm": dm, "home": home,
            "home_by_default_no_scene_kinds": no_kinds, "not_at_home": home_not,
            "total": len(skills)}


def main():
    parser = argparse.ArgumentParser(description="按头部 scene_kinds 数技能名单（只读）")
    parser.add_argument("--data", help="数据根（默认自己找）")
    parser.add_argument("--root", action="append", default=[], help="指定包根或 skills 目录，可重复；给了就不读 activation.json")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if args.root:
        roots, err = explicit_roots(args.root), None
    else:
        data = find_data(args.data)
        if not data:
            print("没找到数据根：带 --data <数据根> 或 --root <包根>。")
            return 1
        roots, err = active_skill_roots(data)
    if not roots:
        print(err or "一个带 skills/ 的根都没找到。")
        return 1
    skills, dupes, bad = collect(roots)
    if not skills:
        print("根在，但一份技能头部都没读到。")
        return 1
    result = build(skills)
    result["roots"] = [{"label": l, "skills_dir": d} for l, d in roots]
    result["duplicates"] = dupes
    result["unreadable"] = bad
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print("根（%d）：" % len(roots))
    for label, directory in roots:
        print("  %-12s %s" % (label, directory))
    print("技能共 %d 份（同名只算一份）" % result["total"])
    print("群（group）%d 份：%s" % (len(result["group"]), "、".join(result["group"])))
    print("别人私聊（dm）%d 份：%s" % (len(result["dm"]), "、".join(result["dm"])))
    print("家里（home，含头部没写 scene_kinds 的）%d 份：%s" % (len(result["home"]), "、".join(result["home"])))
    print("  其中头部没写 scene_kinds、按只在家里算 %d 份：%s"
          % (len(result["home_by_default_no_scene_kinds"]), "、".join(result["home_by_default_no_scene_kinds"]) or "无"))
    if result["not_at_home"]:
        print("  不在家里露面的 %d 份：%s" % (len(result["not_at_home"]), "、".join(result["not_at_home"])))
    if dupes:
        print("同名跨根（只取先出现的）：" + "；".join(dupes))
    if bad:
        print("头部读不出来：" + "；".join(bad))
    print("口径：读的是生效根＋头部字段，不是群任务现场的 catalog 读数。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
