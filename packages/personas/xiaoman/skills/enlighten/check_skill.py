#!/usr/bin/env python3
"""enlighten 的零依赖离线自检（不联网、不登录、不花配额）。

查：frontmatter 能解析且 name 与目录名一致、章节齐、正文里那些「照字面直接打」的判据字面全在、
脚本能编译、换行是 LF、正文与脚本里没有裸 7+ 位数字串或手机号形状（站点 id／表计 id／序列号是账号事实）、
脚本不硬编码绝对用户目录、脚本里没有一枚 generate_rpt 请求、私密词名单扫过（没配上就 SKIP 并明说：skip 不等于干净）。

用法：python3 check_skill.py
退出码 0＝无 FAIL（SKIP 不算绿，会在末行单列）；否则最后一行写「N/M 通过（SKIP K），失败：...」
"""
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = os.path.basename(HERE)
CATEGORIES = {"person", "group", "account", "site", "host", "email", "other"}

SECTIONS = ['## 什么时候读这一份', '## 文件与凭据约定', '## 登录通路', '## 只读能打的三条 GET',
            '## 死路清单', '## 红线：日报告册的真取数口＝POST', '## 单位与刻度',
            '## 两本账对不上', '## 停手规矩与预算', '## 未核实', '## 来路', '## 版本']

MUST = [
    ('login_form_keys', 'user[email]'),
    ('login_success_literal', 'message 逐字 "success"'),
    ('login_session_id_second_leg', 'session_id'),
    ('env_email', 'ENLIGHTEN_EMAIL'),
    ('env_password', 'ENLIGHTEN_PASSWORD'),
    ('vault_name', 'enlighten'),
    ('env_site_placeholder', 'ASUNA_ENLIGHTEN_SITE'),
    ('get_energy', '/systems/{SITE}/energy?start_date=D&end_date=D&interval=day&tz=Pacific/Auckland'),
    ('get_inverter', '/systems/{SITE}/inverter_data_x/energy.json'),
    ('get_rollup', '/admin/sites/{SITE}/devices/{METER}/rollup?page=1'),
    ('tz_literal', 'Pacific/Auckland'),
    ('tz_slash_unescaped', '斜杠不转义'),
    ('one_shot_per_interval', '只回整段区间的合计'),
    ('one_day_per_shot', '一天一发'),
    ('dead_daily_intl', '/reports/system_daily_international.json'),
    ('dead_report_chart', '/report/chart'),
    ('dead_body', '{"status":404,"error":"Not Found"}'),
    ('dead_no_retry', '同一堵墙'),
    ('post_gate', '/systems/{SITE}/generate_rpt'),
    ('post_csrf', 'authenticity_token'),
    ('post_readonly_redline', '只读趟禁止碰'),
    ('unit_header', 'Energy Produced ( Wh )'),
    ('unit_js', "unit: 'Wh'"),
    ('unit_convert', '1 kWh = 1000 Wh'),
    ('no_silent_divide', '别顺手除 1000'),
    ('measure_point', '测量点'),
    ('no_redirect_chain', '见 302 立即停'),
    ('session_not_persisted', '登录态不写盘'),
    ('no_unit_field', '没有单位字段、没有时区字段'),
    ('provenance_task', 'task-190ecdf76e64f641a1455b410c130a9e'),
]
SCRIPTS = ['enlighten_read.py']

checks = []


def check(name, ok, why=""):
    checks.append((name, bool(ok), why))


skill = open(os.path.join(HERE, "SKILL.md"), "rb").read()
check("skill_lf_only", skill.count(b"\r") == 0, "SKILL.md 有 CR")
text = skill.decode("utf-8")
m = re.match(r"---\n(.*?)\n---\n", text, re.S)
check("frontmatter_parses", m, "开头没有 --- 包着的头")
head = m.group(1) if m else ""
check("name_matches_dir", re.search(r"^name: %s$" % re.escape(NAME), head, re.M), "name 与目录名不一致")
check("has_description", re.search(r"^description: .{200,}", head, re.M), "description 缺或太短")
check("home_only", re.search(r"^scene_kinds: \[home\]$", head, re.M), "应只在 home 可用")
for s in SECTIONS:
    check("section:" + s, s in text, "缺章节 " + s)
titles = re.findall(r"^#{1,3} .*", text, re.M)
check("sections_unique", len(titles) == len(set(titles)), "有重名章节")
check("code_fences_paired", text.count("```") % 2 == 0, "代码围栏不成对")
for key, needle in MUST:
    check("must:" + key, needle in text, "正文缺「%s」" % needle)
check("placeholder_used", "{SITE}" in text and "{METER}" in text, "站点／表计 id 该用占位符")
check("no_todo", not re.search(r"TODO|FIXME|待填", text), "有占位符没填")

all_files = [f for f in os.listdir(HERE) if f.endswith((".md", ".py"))]
PHONE = re.compile(r"(?<!\d)(?:\+?86)?1[3-9]\d{9}(?!\d)")
BARE = re.compile(r"(?<![\w.])\d{7,11}(?![\w.,])")
for f in all_files:
    b = open(os.path.join(HERE, f), "rb").read()
    check("lf_only:" + f, b.count(b"\r") == 0, "有 CR")
    if f == "check_skill.py":
        continue
    t = b.decode("utf-8")
    check("no_phone_shape:" + f, not PHONE.search(t), "有手机号形状")
    bare = BARE.findall(t)
    check("no_bare_digits:" + f, not bare, "有裸 7+ 位数字串 %d 处（账号事实该走环境变量或占位符）" % len(bare))
for f in SCRIPTS:
    try:
        compile(open(os.path.join(HERE, f), encoding="utf-8").read(), f, "exec")
        ok, why = True, ""
    except Exception as e:
        ok, why = False, "编译不过：%s" % e
    check("compiles:" + f, ok, why)
    t = open(os.path.join(HERE, f), encoding="utf-8").read()
    check("no_hardcoded_user_dir:" + f, not re.search(r"[A-Za-z]:[\\/]+(Users|workspace)", t), "脚本硬编码了绝对路径")
    check("script_uses_env_ids:" + f, "ASUNA_ENLIGHTEN_SITE" in t, "脚本没走环境变量拿站点 id")
    posted = [ln for ln in t.splitlines()
              if "generate_rpt" in ln and re.search(r"BASE|client\.(get|post)|url\s*=", ln)]
    check("script_never_posts_report:" + f, not posted,
          "脚本里有 generate_rpt 请求形状（只读趟红线）：%d 行" % len(posted))
check("changelog_first_entry",
      open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8").read().lstrip().startswith("# CHANGELOG"),
      "CHANGELOG 格式")

# 私密词扫描：命中只报名单行号与类别，永不打印词本身。没配上＝SKIP（skip 不等于干净）。
target = os.environ.get("ASUNA_PRIVATE_WORDS") or ""
if not target:
    try:
        from asuna import private_words
        target = str(private_words.path())
    except Exception:
        target = ""
entries = []
if target and os.path.isfile(target):
    for number, line in enumerate(open(target, encoding="utf-8").read().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue                                   # 注释行占行号但不是条目（名单头两行就是注释）
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].strip() in CATEGORIES and parts[1].strip():
            entries.append((number, parts[0].strip(), parts[1].strip()))


def pattern(word):
    escaped = re.escape(word)
    if all(ch.isascii() for ch in word):
        return re.compile(r"(?<![A-Za-z0-9_])" + escaped + r"(?![A-Za-z0-9_])", re.IGNORECASE)
    return re.compile(escaped)


if not entries:
    print("SKIP private_words_scan  名单没配上（ASUNA_PRIVATE_WORDS 未设，asuna 也没配上；查过的位置：%s）"
          "——skip 不等于干净" % (target or "无"))
else:
    hits = []
    for f in all_files:
        t = open(os.path.join(HERE, f), encoding="utf-8").read()
        for number, category, word in entries:
            if pattern(word).search(t):
                hits.append("%s 命中名单第 %d 行（%s）" % (f, number, category))
    check("private_words_clean:%d条" % len(entries), not hits, "；".join(hits[:6]))

bad = [c for c in checks if not c[1]]
skipped = 1 if not entries else 0
for n, ok, why in checks:
    print(("PASS " if ok else "FAIL ") + n + (("  - " + why) if not ok else ""))
print("%d/%d 通过%s%s" % (len(checks) - len(bad), len(checks),
                          ("（另 SKIP %d 项）" % skipped) if skipped else "",
                          ("，失败：" + "、".join(c[0] for c in bad)) if bad else ""))
sys.exit(1 if bad else 0)
