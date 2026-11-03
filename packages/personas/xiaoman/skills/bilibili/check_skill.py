#!/usr/bin/env python3
"""bilibili 的零依赖离线自检（不联网、不碰账号、不花配额）。
查：frontmatter 能解析且 name 与目录名一致、章节齐、脚本能编译、换行是 LF、正文与脚本里没有手机号形状或裸 7+ 位数字串（账号事实不该在这里）、
没有 cookie/token 形状的字面值、脚本不硬编码 uid／blogId／绝对用户目录、关键规矩要点都在。
用法：python3 check_skill.py     退出码 0=全绿；否则最后一行写「N/M 通过，失败：...」
"""
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = os.path.basename(HERE)
SECTIONS = ['## 什么时候读这一份', '## 文件约定', '## 自动化的最低形状', '## 扫码重登', '## 登录后的读侧与写侧', '## 免登录调用链', '## 实测坑', '## 错误码表', '## 未核实', '## 停手规矩']
MUST = [('nav_probe', 'code=0` 且 `data.isLogin=true'), ('dead_only_101', '`code=-101` 才判死'), ('ttl_180', '约 180 秒'), ('foreground_poll', '前台、带 timeout'), ('same_trip', '出码与轮询在同一趟'), ('png_path_only', 'PNG 落盘的绝对路径'), ('ask_before_issue', '先确认人在场'), ('no_second_card', '不自己再发第二张'), ('cookie_sep', 'cookie 头分隔符是 `; `，不是 `&`'), ('wbi', '投稿族要 wbi 签名'), ('hot_chain', 'x/v2/reply?type=1&oid=<aid>&sort=2'), ('avoid_main', '/x/v2/reply/main'), ('backup_url', 'backup_url'), ('raw_deflate', 'raw deflate'), ('beijing', '北京时间'), ('unverified_list', '写侧（评论、动态、专栏投稿）全部没发过')]
SCRIPTS = ['bili_auto.py']

checks = []


def check(name, ok, why=""):
    checks.append((name, bool(ok), why))


skill = open(os.path.join(HERE, "SKILL.md"), "rb").read()
text = skill.decode("utf-8")
m = re.match(r"---\n(.*?)\n---\n", text, re.S)
check("frontmatter_parses", m, "开头没有 --- 包着的头")
head = m.group(1) if m else ""
check("name_matches_dir", re.search(r"^name: %s$" % re.escape(NAME), head, re.M), "name 与目录名不一致")
check("has_description", re.search(r"^description: .{40,}", head, re.M), "description 缺或太短")
check("home_only", re.search(r"^scene_kinds: \[home\]$", head, re.M), "应只在 home 可用")
for s in SECTIONS:
    check("section:" + s, s in text, "缺章节 " + s)
for key, needle in MUST:
    check("must:" + key, needle in text, "正文缺「%s」" % needle)

all_files = [f for f in os.listdir(HERE) if f.endswith((".md", ".py"))]
for f in all_files:
    b = open(os.path.join(HERE, f), "rb").read()
    check("lf_only:" + f, b.count(b"\r") == 0, "有 CR")
for f in SCRIPTS:
    try:
        compile(open(os.path.join(HERE, f), encoding="utf-8").read(), f, "exec")
        ok = True
    except Exception as e:
        ok = False
    check("compiles:" + f, ok, "编译不过")
PHONE = re.compile(r"(?<!\d)(?:\+?86)?1[3-9]\d{9}(?!\d)")
BARE = re.compile(r"(?<![\w.])\d{7,11}(?![\w.,])")
COOKIEVAL = re.compile(r"(SESSDATA|bili_jct|LOFTER-PHONE-LOGIN-AUTH)\s*=\s*[A-Za-z0-9%]{12,}")
for f in all_files:
    if f == "check_skill.py":
        continue
    t = open(os.path.join(HERE, f), encoding="utf-8").read()
    check("no_phone_shape:" + f, not PHONE.search(t), "有手机号形状")
    bare = [x for x in BARE.findall(t)]
    check("no_bare_digits:" + f, not bare, "有裸 7+ 位数字串：%d 处" % len(bare))
    check("no_cookie_value:" + f, not COOKIEVAL.search(t), "有 cookie 值形状")
for f in SCRIPTS:
    t = open(os.path.join(HERE, f), encoding="utf-8").read()
    check("no_hardcoded_user_dir:" + f, not re.search(r"[A-Za-z]:[\\/]+(Users|workspace)", t), "脚本里硬编码了绝对路径")
check("changelog_first_entry", open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read().lstrip().startswith("# CHANGELOG"), "CHANGELOG 格式")
check("no_placeholder", not re.search(r"TODO|FIXME|待填|XXX占位", text), "有占位符")

bad = [c for c in checks if not c[1]]
for n, ok, why in checks:
    print(("PASS " if ok else "FAIL ") + n + (("  - " + why) if not ok else ""))
print("%d/%d 通过%s" % (len(checks) - len(bad), len(checks), ("，失败：" + "、".join(c[0] for c in bad)) if bad else ""))
sys.exit(1 if bad else 0)
