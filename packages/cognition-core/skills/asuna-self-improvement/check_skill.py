#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline pins for the 派活交代 section of this skill book.

Stdlib only. It reads one markdown file (the SKILL.md next to it, or a path
given as argv[1]) and checks that literal sentences are present. It runs
nothing and writes nothing. Exit 0 = every pin found.

Groups A-D each pin ONE of the four sentences added on 2026-11-21, so deleting
one sentence reddits only its own group -- the four are never merged into one
shot. Group E pins older sentences of the same section so a green run is not
trivially caused by an empty file, and so feeding the pre-2026-11-21 book to
this script reddits exactly groups A-D and nothing else.

Every pin is searched inside the 派活交代 section slice only, so the
changelog line at the bottom of the book can never keep a pin green.
"""
import hashlib
import os
import sys

GROUPS = [
    ("A_QUOTE_INBOUND_LINE", [
        "只认本人打字的入站行",
        "都不是某个人打过字的那一行",
        "只在摘要或提示里见过，出处未定",
        "This session is being continued",
    ]),
    ("B_RECIPE_PROVENANCE", [
        "它是从哪一发的原件抄的",
        "待验，不是配方",
        "它是哪本账上的数",
        "两本账不一致就把两个值都报回来",
    ]),
    ("C_STOP_CARRIES_ITEMS", [
        "中途停也要交交代项",
        "只写「下一步读 X」的进度笔记不是终报",
        "哪几格没探到",
        "那一趟就没做完",
    ]),
    ("D_SPEC_PROVENANCE_AND_ASK", [
        "从哪一版正本抄的、当拍现读还是旧印象",
        "对得上号的角色 LoRA",
        "停下来 ask 角色脑一次",
        "不许按纸上默认的做完当作没冲突",
    ]),
    ("E_PREEXISTING_SENTENCES", [
        "只活一条命令",
        "别拿 TEMP 当中间存储",
        "落 TEMP 的那份等于没交",
        "以你现读为准",
        "当拍现读",
    ]),
]


def section_slice(text):
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("## ") and "派活交代" in ln:
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
    sec = section_slice(raw.decode("utf-8"))
    if sec is None:
        print("FAIL SECTION_MISSING 派活交代")
        print("RESULT fail 0/" + str(sum(len(n) for _, n in GROUPS)))
        return 1
    total = 0
    missed = 0
    red = []
    for name, needles in GROUPS:
        miss = [w for w in needles if w not in sec]
        total += len(needles)
        missed += len(miss)
        for w in miss:
            red.append(name)
            print("FAIL", name, w)
        print("GROUP", name, "pins", len(needles), "missing", len(miss))
    print("RESULT", "pass" if missed == 0 else "fail", str(total - missed) + "/" + str(total))
    if red:
        print("RED_GROUPS", " ".join(sorted(set(red))))
    return 0 if missed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
