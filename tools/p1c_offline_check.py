#!/usr/bin/env python3
"""ADR-005 P1-c 离线自检：不需要 Mongo、不需要 pytest，直接跑同一套整理用例。

用法：python3 tools/p1c_offline_check.py
它验证的是整理逻辑与围栏（假集合真算过滤/排序/分页），不验证真实 Mongo 上的时间与游标。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
# The cases check the digest by names, without people.py's labels (history_query's fallback when People cannot be
# loaded): People is kept out of this run on purpose. It used to fail to load here only by accident (the cases put
# src/asuna on the path, whose queue.py shadows the standard library's, which pymongo imported through state.py).
sys.modules["asuna.people"] = None
import discussion_digest_cases as cases          # noqa: E402

results = cases.run_all()
for name, ok, why in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else " -> " + why))
failed = [name for name, ok, _why in results if not ok]
print("P1-c 离线自检：%d/%d 通过" % (len(results) - len(failed), len(results)))
if failed:
    print("失败：" + ", ".join(failed))
sys.exit(1 if failed else 0)
