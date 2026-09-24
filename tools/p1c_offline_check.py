#!/usr/bin/env python3
"""ADR-005 P1-c 离线自检：不需要 Mongo、不需要 pytest，直接跑同一套整理用例。

用法：python3 tools/p1c_offline_check.py
它验证的是整理逻辑与围栏（假集合真算过滤/排序/分页）；真实 Mongo 的三支时间与游标
由 tests/test_discussion_digest.py 在隔离宿主里复测，两者不互相代替。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import discussion_digest_cases as cases          # noqa: E402

results = cases.run_all()
for name, ok, why in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else " -> " + why))
failed = [name for name, ok, _why in results if not ok]
print("P1-c 离线自检：%d/%d 通过" % (len(results) - len(failed), len(results)))
if failed:
    print("失败：" + ", ".join(failed))
sys.exit(1 if failed else 0)
