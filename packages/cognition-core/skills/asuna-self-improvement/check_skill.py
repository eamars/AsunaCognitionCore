#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline pins for the rules in this skill book.

Stdlib only. It reads one markdown file -- the SKILL.md next to it, or the path
given as argv[1]. There is NO flag: `argv[1]` is always taken for a file name,
so `--help` dies with FileNotFoundError (rc 1). It checks that literal
sentences are present, or, for each group's `absent` patterns (regular
expressions), absent. It runs nothing and writes nothing. Exit 0 = every pin
found and every absent pattern clean.

One group per rule cell: deleting one sentence reddits only its own group, and
the groups are never merged into one shot. Each group also says which `## `
section of the book it searches, so the changelog at the bottom can never keep
a pin green, and a rule copied into the wrong section does not pass either.

The NUMBER of groups is deliberately not written in the book -- group K pins
that. Read it from this script's own output: `GROUPS <n>` (how many groups
this script has right now), `RESULT <found>/<total>` (pins), `RED_GROUPS ...`.

A-D pin the four sentences added in 派活交代 on 2026-11-21 (v12); E pins older
sentences of that same section, so a green run is not trivially caused by an
empty file. F and G pin the two cells v13 added in 派活交代, H the half-cell v13
added in 写盘交代模板, I the 挑发布窗口 cell as v14 rewrote it (its retracted
number must stay out), J the 历史前提 cell v14 added, K the hardcoded group
count v14 removed from 发布前自检.
"""
import hashlib
import os
import re
import sys

GROUPS = [
    {"name": "A_QUOTE_INBOUND_LINE", "section": "派活交代", "absent": [], "needles": [
        "只认本人打字的入站行",
        "都不是某个人打过字的那一行",
        "只在摘要或提示里见过，出处未定",
        "This session is being continued",
    ]},
    {"name": "B_RECIPE_PROVENANCE", "section": "派活交代", "absent": [], "needles": [
        "它是从哪一发的原件抄的",
        "待验，不是配方",
        "它是哪本账上的数",
        "两本账不一致就把两个值都报回来",
    ]},
    {"name": "C_STOP_CARRIES_ITEMS", "section": "派活交代", "absent": [], "needles": [
        "中途停也要交交代项",
        "只写「下一步读 X」的进度笔记不是终报",
        "哪几格没探到",
        "那一趟就没做完",
    ]},
    {"name": "D_SPEC_PROVENANCE_AND_ASK", "section": "派活交代", "absent": [], "needles": [
        "从哪一版正本抄的、当拍现读还是旧印象",
        "对得上号的角色 LoRA",
        "停下来 ask 角色脑一次",
        "不许按纸上默认的做完当作没冲突",
    ]},
    {"name": "E_PREEXISTING_SENTENCES", "section": "派活交代", "absent": [], "needles": [
        "只活一条命令",
        "别拿 TEMP 当中间存储",
        "落 TEMP 的那份等于没交",
        "以你现读为准",
        "当拍现读",
    ]},
    # v13: 画图／改图这类单子派低档（v14 起有钉）
    {"name": "F_V13_IMAGE_ORDER_LOW_TIER", "section": "派活交代", "absent": [], "needles": [
        "这类单子一律派低档",
        "都不算升档理由",
        "真要我判断的是「这张该不该画」",
        "审美取舍归我，腿只跑",
    ]},
    # v13: core 的改动记录走版本节，不走 CHANGELOG（v14 起有钉）
    {"name": "G_V13_CORE_CHANGELOG_SHAPE", "section": "派活交代", "absent": [], "needles": [
        "版本节加一行」，别写「CHANGELOG 一行",
        "变更记录是正文末尾「## 版本」那一节",
        "是人格包那侧的体例，不串门",
    ]},
    # v13: 候选根新建文件要回读核到（写盘交代模板 那一节，v14 起有钉）
    {"name": "H_V13_CANDIDATE_ROOT_WRITE", "section": "写盘交代模板", "absent": [], "needles": [
        "新建文件那份回执只当「写请求收到」",
        "写完必须 `development_read` 回读一次核到",
        "这一格只管新建",
    ]},
    # v14: 挑发布窗口那一格是形状句，不是某个分钟数
    {"name": "I_PUBLISH_WAIT_SHAPE", "section": "发布", "absent": ["约 14 分钟"], "needles": [
        "取决于那一刻还有没有在跑的活",
        "拿其中任何一枚当规格都是错的",
        "两枚读数留下并标「个案」",
        "held.changes",
        "有两本账，别混",
    ]},
    # v14: 派活纸里的历史前提
    {"name": "J_HISTORY_PRECONDITION", "section": "派活交代", "absent": [], "needles": [
        "不当拍现读，就整句删掉",
        "这句历史前提我是读了哪一行知道的",
        "说不出它是从哪一行读来的",
        "被腿用现读顶回",
    ]},
    # v14: 组数只从脚本输出读，正文写死就红
    {"name": "K_COUNT_NOT_HARDCODED", "section": "发布前自检",
     "absent": [r"[\d一二两三四五六七八九十]组钉"], "needles": [
        "这一本正文自己的钉",
        "组数不在正文里写死",
    ]},
]


SEPARATORS = "（( ：:、，。—-"


def heading_match(rest, heading):
    """True when `rest` is this section heading, or that heading plus a separator."""
    if rest == heading:
        return True
    if not rest.startswith(heading):
        return False
    return rest[len(heading)] in SEPARATORS


def section_slice(text, heading):
    """The lines between the `## <heading>` section and the next `## ` line (### stays in).

    A heading matches when it equals the section heading, or that heading is
    followed by a separator （ or ： etc -- never as a bare substring, so 发布
    does not land on 发布前自检 and 发布前自检 does not swallow 发布.
    """
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        rest = ln[3:] if ln.startswith("## ") else None
        if rest is not None and heading_match(rest, heading):
            start = i
            break
    if start is None:
        return None
    out = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        out.append(ln)
    return "\n".join(out)


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    path = argv[1] if len(argv) > 1 else os.path.join(here, "SKILL.md")
    raw = open(path, "rb").read()
    print("file", path)
    print("bytes", len(raw), "sha256", hashlib.sha256(raw).hexdigest())
    text = raw.decode("utf-8")
    total = sum(len(g["needles"]) + len(g["absent"]) for g in GROUPS)
    print("GROUPS", len(GROUPS), "PINS", total)
    found = 0
    red = []
    for g in GROUPS:
        needles, absent = g["needles"], g["absent"]
        sec = section_slice(text, g["section"])
        if sec is None:
            print("FAIL", g["name"], "SECTION_MISSING", g["section"])
            miss, hits = list(needles), list(absent)
        else:
            miss = [w for w in needles if w not in sec]
            hits = [p for p in absent if re.search(p, sec)]
        for w in miss:
            print("FAIL", g["name"], w)
        for p in hits:
            print("FAIL", g["name"], "FORBIDDEN", p)
        pins = len(needles) + len(absent)
        found += pins - len(miss) - len(hits)
        if miss or hits:
            red.append(g["name"])
        print("GROUP", g["name"], "section", g["section"], "pins", pins,
              "missing", len(miss), "forbidden_found", len(hits))
    print("RESULT", "pass" if found == total else "fail", str(found) + "/" + str(total))
    if red:
        print("RED_GROUPS", " ".join(sorted(set(red))))
    return 0 if found == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
