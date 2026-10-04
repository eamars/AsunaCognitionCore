#!/usr/bin/env python3
"""出站图片附件（QQ 私聊 B 阶段第一步）的离线自检：不需要 Mongo、不需要 pytest、不联网、不发 QQ。

用法：python3 tools/outbound_image_offline_check.py
跑的是 tests/outbound_image_cases.py 同一套用例：通道字节端点的围栏（真在 127.0.0.1 起服务、
真发 HTTP 请求）、claim 的 supports 与附件元数据、她的 attach_image 工具逐次判定（含群方向确定性拒绝）、
整回合（think → attach_image → 正文或 stay_silent）写出的 SPEAK 行上的元数据、历史投影的附件位、
BlobStore 的 sha 复核与 scope 判定。
真 Mongo 的 CAS、真 GridFS、真 NapCat 渲染仍由宿主侧 tests/test_*.py 与适配器 selftest 复测，
两者不互相代替。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import outbound_image_cases as cases       # noqa: E402

if cases.STUBBED:
    print("（本轮假掉的第三方库：" + ", ".join(cases.STUBBED) + "）")
results = cases.run_all()
for name, ok, note in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, " — " + note if note else ""))
failed = [name for name, ok, _note in results if not ok]
print("出站图片附件离线自检：%d/%d 通过" % (len(results) - len(failed), len(results)))
if failed:
    print("失败：" + ", ".join(failed))
sys.exit(1 if failed else 0)
