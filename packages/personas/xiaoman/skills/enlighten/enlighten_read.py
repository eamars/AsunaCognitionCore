#!/usr/bin/env python3
"""Enlighten 只读读取器（照技能正文的字面直接打，不再翻 JS 包）。

只发这些请求：一枚登录 POST ＋ 若干 GET。generate_rpt 是 POST 作业，属状态变化，本脚本永不发它。

账号事实不进这个文件：站点 id 与表计 id 从环境变量读
  ASUNA_ENLIGHTEN_SITE   站点 id（命中本机私密词，别写死在文件里）
  ASUNA_ENLIGHTEN_METER  表计 id（只有 rollup 用）
凭据从保险箱名字 enlighten 的环境变量读：ENLIGHTEN_EMAIL / ENLIGHTEN_PASSWORD（值不落盘、不打印）。

用法：
  python3 enlighten_read.py login                      # 只登录，回报判据读数
  python3 enlighten_read.py day 2026-11-07 [更多日…]   # 站点级合计，一天一发
  python3 enlighten_read.py range 2026-11-04 2026-11-07
  python3 enlighten_read.py inverters 2026-11-04 2026-11-07   # 逐台区间合计＋机械相加
  python3 enlighten_read.py rollup [--page 1]          # 表计 rollup 逐日表（HTML 表格）
可选：--out 目录   把原始正文写进那个目录（默认不写盘）

退出码：0 成功；2 缺环境变量；3 登录没成；4 某发 GET 非 200；5 正文形状不是记载的那样。
"""
import argparse
import hashlib
import os
import re
import sys
import datetime

import httpx

BASE = "https://enlighten.enphaseenergy.com"
TZ = "Pacific/Auckland"          # 页面配置字面 timezone，不是账号事实
UA = "Mozilla/5.0 (read-only data pull)"
XHR = {"Accept": "application/json, text/javascript, */*;q=0.9",
       "X-Requested-With": "XMLHttpRequest"}


def now():
    loc = datetime.datetime.now().astimezone()
    return "local=%s utc=%s" % (loc.isoformat(timespec="seconds"),
                                loc.astimezone(datetime.timezone.utc).isoformat(timespec="seconds"))


def need_site():
    site = os.environ.get("ASUNA_ENLIGHTEN_SITE")
    if not site:
        print("MISSING_ENV ASUNA_ENLIGHTEN_SITE（站点 id 是账号事实，从 persona 光伏那节拿，别写死）")
        sys.exit(2)
    return site


def login(client, site=None):
    """一枚 POST。判据两条：HTTP 200 且 message 逐字 success，并且响应体带 session_id。"""
    missing = [k for k in ("ENLIGHTEN_EMAIL", "ENLIGHTEN_PASSWORD") if not os.environ.get(k)]
    if missing:
        print("MISSING_ENV %s（sandbox_run 带 credentials: [\"enlighten\"]）" % ",".join(missing))
        sys.exit(2)
    r = client.post(BASE + "/login/login.json",
                    data={"user[email]": os.environ["ENLIGHTEN_EMAIL"],
                          "user[password]": os.environ["ENLIGHTEN_PASSWORD"]},
                    headers={"Accept": "application/json"})
    msg, sess, sid_len = None, None, None
    try:
        b = r.json()
        if isinstance(b, dict):
            msg = b.get("message")
            sess = b.get("session_id")
            sid_len = len(str(sess)) if sess is not None else None
            note = "keys=%s" % ",".join(sorted(b.keys()))
    except Exception as e:
        note = "non_json ctype=%r %s" % (r.headers.get("content-type"), type(e).__name__)
    msg_ok = r.status_code == 200 and isinstance(msg, str) and msg.lower() == "success"
    ok = bool(msg_ok and sess is not None)
    # 正文整段不进日志：只打判据读数
    print("POST login http=%s message_is_success=%s message_len=%s session_id_present=%s session_id_len=%s "
          "body_bytes=%d %s jar=%s | %s"
          % (r.status_code, msg_ok, len(msg) if isinstance(msg, str) else None, sess is not None, sid_len,
             len(r.content), note, sorted(client.cookies.keys()), now()))
    if not ok:
        print("STOP: 登录判据没凑齐（message=success 与 session_id 两条都要），不做任何 GET")
        sys.exit(3)


def get(client, url, headers, out=None, tag=""):
    r = client.get(url, headers=headers)
    body = r.content
    digest = hashlib.sha256(body).hexdigest()
    print("GET %s\n    -> http=%s ctype=%r bytes=%d sha256_16=%s location=%r | %s"
          % (url, r.status_code, r.headers.get("content-type"), len(body), digest[:16],
             r.headers.get("location"), now()))
    if r.status_code != 200:
        print("    正文前 120=%s" % body[:120].decode("utf-8", "replace"))
        return r, None, 4
    if out:
        os.makedirs(out, exist_ok=True)
        p = os.path.join(out, (tag or "body") + ".txt")
        with open(p, "wb") as h:
            h.write(body)
        print("    WROTE %s (%d bytes, sha256_16=%s)" % (p, len(body), digest[:16]))
    return r, body, 0


def show_json(body, limit=600):
    t = body.decode("utf-8", "replace")
    if len(t) <= limit:
        print("    正文整段=%s" % t)
    else:
        print("    正文前 %d=%s" % (limit, t[:limit]))
    return t


def rows_of_rollup(t):
    """表头字面与逐日行（日期是 MM/DD/YYYY，新→旧）。"""
    head = re.search(r"Start Date.*?Channel", t, re.S)
    rows = re.findall(r"<td[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>"
                      r"\s*<td[^>]*>\s*([\d.]+)\s*</td>\s*<td[^>]*>\s*(\d+)\s*</td>", t)
    return ("Start Date / Energy Produced ( Wh ) / Average Real Power ( W ) / Channel"
            if head else "(表头不是记载的那个)"), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["login", "day", "range", "inverters", "rollup"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--page", default="1")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    site = None if a.what == "login" else need_site()
    xhr = dict(XHR, Referer=BASE + "/systems/%s" % site) if site else dict(XHR)
    client = httpx.Client(timeout=90.0, follow_redirects=False, headers={"User-Agent": UA})
    login(client, site)
    if a.what == "login":
        return 0

    rc = 0
    if a.what in ("day", "range"):
        if a.what == "day":
            dates = a.args or [datetime.date.today().isoformat()]
            pairs = [(d, d) for d in dates]
        else:
            pairs = [(a.args[0], a.args[1])]
        for s, e in pairs:
            url = "%s/systems/%s/energy?start_date=%s&end_date=%s&interval=day&tz=%s" % (BASE, site, s, e, TZ)
            _, body, bad = get(client, url, xhr, a.out or None, "energy_%s_%s" % (s, e))
            if bad:
                rc = bad
                continue
            t = show_json(body)
            if "production" not in t:
                print("    形状不对：没有 production 键")
                rc = 5
    elif a.what == "inverters":
        s, e = a.args[0], a.args[1]
        url = ("%s/systems/%s/inverter_data_x/energy.json?start_date=%s&end_date=%s&interval=day&tz=%s"
               % (BASE, site, s, e, TZ))
        _, body, bad = get(client, url, xhr, a.out or None, "inv_energy_%s_%s" % (s, e))
        if bad:
            return bad
        t = show_json(body, 900)
        vals = [float(v) for v in re.findall(r'"\d+":\s*([\d.]+)', t)]
        if not vals:
            print("    形状不对：production 不是逐台字典")
            rc = 5
        else:
            total = sum(vals)
            print("    逐台 %d 条，机械相加=%s（原样不换算；未逐日拆）" % (len(vals), ("%g" % total)))
    else:
        meter = os.environ.get("ASUNA_ENLIGHTEN_METER")
        if not meter:
            print("MISSING_ENV ASUNA_ENLIGHTEN_METER（rollup 要表计 id）")
            return 2
        url = "%s/admin/sites/%s/devices/%s/rollup?page=%s" % (BASE, site, meter, a.page)
        _, body, bad = get(client, url, {"Accept": "text/html"}, a.out or None, "rollup_p%s" % a.page)
        if bad:
            return bad
        head, rows = rows_of_rollup(body.decode("utf-8", "replace"))
        print("    表头=%s\n    本页逐日行数=%d（日期字面 MM/DD/YYYY，新→旧）" % (head, len(rows)))
        for d, wh, w, ch in rows[:5]:
            print("    %s | %s | %s | %s" % (d, wh, w, ch))
        if "Not Found" in body.decode("utf-8", "replace")[:200]:
            rc = 5
    return rc


if __name__ == "__main__":
    sys.exit(main())
