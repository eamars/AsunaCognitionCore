"""Read-only probe: print integration config shape with secrets redacted.

【怎么跑】
无参数：
    python3 probe_cfg.py
读环境变量 ASUNA_INTEGRATION_CONFIG 指向的配置文件，没设则用默认路径。
只打印配置形状：token/password/secret/key 字段一律打码成 <set len=N>，
长值截断，不落明文。

【要什么布局】
默认路径 /integration/config.json 是容器内路径；本机（Windows）没有这个
路径。在本机跑要把 ASUNA_INTEGRATION_CONFIG 指到宿主上适配器落盘的
config.json 快照，否则 FileNotFoundError。

【哪来的】
10-08 摸 NapCat 补读写（catch-up）行为时写的只读探针（与 probe_catchup.py
同批，这份看配置形状），是 ADR-022 那批活体读数里唯一还能复现的脚本。
仓库内零引用：不进发布包、不进运行时。

—— Xiaoman
"""
import json
import os
import sys

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就 UnicodeEncodeError 整段崩，整段输出丢掉
# （2026-10-15 实测：--selfcheck 的字面量、带中文显示名的配置、带中文 wording 的回包，三种数据都崩在
# Lib/encodings/cp1252.py 第 19 行）。我的沙箱 env 带 PYTHONUTF8=1／PYTHONIOENCODING=utf-8，撞不到这一族。
# 输出字节固定成 UTF-8：那种控制台顶多显示成乱码，不再崩；stderr 同理，报错才看得见。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

P = os.environ.get("ASUNA_INTEGRATION_CONFIG", "/integration/config.json")
c = json.load(open(P, encoding="utf-8"))


def redact(o, key=""):
    if isinstance(o, dict):
        return {k: redact(v, k) for k, v in o.items()}
    if isinstance(o, list):
        return [redact(v, key) for v in o]
    if isinstance(o, str):
        lk = key.lower()
        if any(s in lk for s in ("token", "password", "secret", "key")):
            return "<set len=%d>" % len(o)
        if len(o) > 80:
            return o[:80] + "..."
    return o


for k, v in c.items():
    if isinstance(v, dict):
        print("==", k, "->", json.dumps(redact(v), ensure_ascii=False, indent=1)[:2000])
    elif isinstance(v, list):
        print("==", k, "-> list of", len(v))
    else:
        print("==", k, "->", type(v).__name__)
