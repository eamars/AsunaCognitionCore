#!/usr/bin/env python3
"""DECIDE 可选字段「按条目去重」的离线自检：不需要 Mongo、不需要 pytest、不联网、不发 QQ、不调模型。

用法：``python3 tools/decide_delta_rounds_offline_check.py``（在认知核候选根目录跑）。

跑的是 ``tests/decide_delta_rounds_cases.py`` 那一套：``next=recall`` 之后的第二次 DECIDE 逐字重写
第一轮那几样再加一条新的 → 旧的只生效一次、新的生效一次；新条目排在 index 0 也不被误吞；同一份
delta 崩溃重放 / advance 重入 no-op；attach 后一次 DECIDE 覆盖前一次、被退回时不无声丢图；
read 在 recall 那一轮只被验一遍。真 Mongo 的 CAS、真夹具世界里的 promote / group_action 两条路径
仍由宿主侧 ``tests/test_decide_delta_rounds.py`` 复测（操作员跑），两者不互相代替。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import decide_delta_rounds_cases as cases      # noqa: E402
import outbound_image_cases as media_cases     # noqa: E402  同一套存储替身（假库清单在它那里）

if media_cases.STUBBED:
    print("（本轮假掉的第三方库：" + ", ".join(media_cases.STUBBED) + "）")
results = cases.run_all()
for name, ok, note in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, " — " + note if note else ""))
failed = [name for name, ok, _note in results if not ok]
print("DECIDE 多轮去重离线自检：%d/%d 通过" % (len(results) - len(failed), len(results)))
if failed:
    print("失败：" + ", ".join(failed))
sys.exit(1 if failed else 0)
