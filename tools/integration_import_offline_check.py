#!/usr/bin/env python3
"""集成产物导入的离线自检：不需要 Mongo、不需要 pytest、不需要 WSL，直接跑同一套用例。

用法：python3 tools/integration_import_offline_check.py
它验证的是判定与写入围栏（端点别名白名单、URL 拒绝、工作区边界、默认不覆盖、大小上限、
失败原因映射），以及 127.0.0.1 上真 HTTP 取字节；真 WSL 命名空间里「只有配置的中继可达」
由 tools/probe_integration_transport.py 与 tests/test_integration.py 在隔离宿主复测，
两者不互相代替。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import integration_import_cases as cases       # noqa: E402

results = cases.run_all()
for name, ok, why in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, " — " + why if why else ""))
failed = [name for name, ok, _why in results if not ok]
print("集成导入离线自检：%d/%d 通过" % (len(results) - len(failed), len(results)))
if failed:
    print("失败：" + ", ".join(failed))
sys.exit(1 if failed else 0)
