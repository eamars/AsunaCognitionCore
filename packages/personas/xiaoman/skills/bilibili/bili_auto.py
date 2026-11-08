#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站账号自治：读 cookie 文件 → 探活 → 失效就按技能记载的扫码流程重登 → 回写文件 → 再取数。

只用标准库（扫码出图那一步按需把纯 python 的 segno 轮子装进 <工作目录>/libs）。
账号事实（uid、cookie 值）一律不在本文件里：从 cookie 文件读，stdout 不打印值。

子命令（先 `python3 bili_auto.py -h`）：
  status                  读文件 → 探活（nav code）→ 报 ALIVE/DEAD/UNKNOWN，不重登
  ensure                  探活；DEAD 才走扫码重登（要人来扫，见 SKILL.md「什么时候喊人」）
  login                   不管死活，直接发码轮询（前台，出码与轮询同一趟）
  view BVID               ensure → x/web-interface/view
  hotcomment BVID         免登录链：www 页 → view → reply?sort=2；每跳隔几秒；失败如实报不编
  arcs [--mid N]          ensure → wbi 签名的 x/space/wbi/arc/search（默认查 cookie 文件里自己的 uid）
  danmaku CID             弹幕 XML（raw deflate 解压后落盘 / 打印条数）
  download BVID --out F   ensure → view → playurl（带 Referer）→ 主镜像失败走 backup_url
退出码：0 成功；2 要人扫码但没扫成（过期/超时/被拒）；3 探活无法判定（-412、网络等，字面已打印，不重登）；4 取数 HTTP/业务码失败。
"""
import argparse
import hashlib
import http.cookiejar
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
REF = "https://www.bilibili.com/"
API = "https://api.bilibili.com"
PASSPORT = "https://passport.bilibili.com"
COOKIE_FILE = "bili_login.json"
QR_PNG = "bili_login_qr_cur.png"
QR_TTL_S = 180        # 网页码真 TTL≈180 秒（11-03 19:17 实测）
QR_WALL_S = int(os.environ.get("ASUNA_BILI_QR_WALL", "185"))   # 前台轮询的墙钟上限（环境变量只给离线测试缩短用）
POLL_EVERY_S = 2
HOP_PAUSE_S = 3       # 免登录链每跳之间的间隔

MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 61, 26, 1, 17, 0, 7, 48,
             56, 30, 4, 22, 63, 54, 34, 36, 60, 25, 21, 62, 57, 16, 44, 52, 24, 6, 55,
             40, 20, 64, 59, 51]

# 错误码表（实测；没见过的码一律字面报，不替它解释）
CODES = {
    0: "OK",
    -101: "账号未登录（cookie 失效或没带对：手拼头分隔符必须是 '; '）",
    -352: "风控校验失败（免登录打 /x/v2/reply/main、popular 会这样；换免登录链）",
    -401: "非法访问（免登录打 space/acc/info 会这样）",
    -403: "访问权限不足（arc/search 没签 wbi）",
    -509: "请求过于频繁（歇一会儿，别连打）",
    -412: "请求被拦（UA/头指纹，不是缺 wbi 签名）",
    86101: "扫码：未扫",
    86090: "扫码：已扫、待手机上确认",
    86038: "扫码：二维码已失效",
}


# ---------------------------------------------------------------- 路径与文件
def work_dir():
    """cookie 文件所在目录：ASUNA_BILI_DIR → 当前目录（含文件或名为 local-user）→ 往上找 .runtime/work/local-user。"""
    e = os.environ.get("ASUNA_BILI_DIR")
    if e:
        return e
    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, COOKIE_FILE)) or os.path.basename(cwd) == "local-user":
        return cwd
    p = cwd
    for _ in range(8):
        cand = os.path.join(p, ".runtime", "work", "local-user")
        if os.path.isdir(cand):
            return cand
        np_ = os.path.dirname(p)
        if np_ == p:
            break
        p = np_
    return cwd


def cookie_path():
    return os.path.join(work_dir(), COOKIE_FILE)


def load_doc():
    p = cookie_path()
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("WARN cookie 文件读不开: %s" % type(e).__name__)
        return None


def cookie_header_from(doc):
    """优先 logged_in.cookie_header（'; ' 分隔）；没有就用 cookies_final 按 '; ' 拼。"""
    li = (doc or {}).get("logged_in") or {}
    h = li.get("cookie_header") or ""
    if h:
        return h
    cf = li.get("cookies_final") or {}
    return "; ".join("%s=%s" % (k, v) for k, v in cf.items())


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


# ---------------------------------------------------------------- HTTP
def http_get(url, cookie="", referer=REF, opener=None, timeout=25, accept="application/json, text/plain, */*"):
    h = {"User-Agent": UA, "Referer": referer, "Accept": accept}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, headers=h)
    op = opener.open if opener else urllib.request.urlopen
    try:
        with op(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def get_json(url, cookie="", referer=REF, opener=None):
    st, hd, body = http_get(url, cookie, referer, opener)
    try:
        return st, json.loads(body)
    except Exception:
        return st, {"_nonjson": body[:120].decode("utf-8", "replace")}


def code_text(j, st):
    if "_nonjson" in j:
        return "HTTP %s 非 JSON: %r%s" % (st, j["_nonjson"], "（412＝指纹拦）" if st == 412 else "")
    c = j.get("code")
    return "HTTP %s code=%s message=%r%s" % (st, c, j.get("message"),
                                               ("（%s）" % CODES[c]) if c in CODES and c != 0 else "")


# ---------------------------------------------------------------- 探活
def probe(cookie):
    """返回 (verdict, json)。verdict: ALIVE / DEAD / UNKNOWN。只有 nav code -101 才判 DEAD。"""
    if not cookie:
        return "DEAD", {"_why": "没有 cookie"}
    try:
        st, j = get_json(API + "/x/web-interface/nav", cookie)
    except Exception as e:
        return "UNKNOWN", {"_why": "传输错误 %s" % type(e).__name__}
    d = j.get("data") or {}
    if j.get("code") == 0 and d.get("isLogin") is True:
        return "ALIVE", j
    if j.get("code") == -101:
        return "DEAD", j
    return "UNKNOWN", dict(j, _http=st)


def mid_mask(m):
    s = str(m or "")
    return (s[:1] + "~" + s[-1:]) if len(s) > 2 else "~"


# ---------------------------------------------------------------- 扫码重登
def ensure_segno():
    libs = os.path.join(work_dir(), "libs")
    if libs not in sys.path:
        sys.path.insert(0, libs)
    try:
        import segno  # noqa: F401
        return True
    except Exception:
        pass
    import zipfile
    j = json.loads(http_get("https://pypi.org/pypi/segno/json", timeout=30, referer="")[2])
    w = [f for f in j["urls"] if f["packagetype"] == "bdist_wheel"][0]
    b = http_get(w["url"], timeout=90, referer="")[2]
    zipfile.ZipFile(io.BytesIO(b)).extractall(libs)
    import importlib
    importlib.invalidate_caches()
    import segno  # noqa: F401
    return True


def qr_login():
    """前台：出码 → 落 PNG → 轮询到终态/墙钟。出码与轮询在同一趟里（detached 子进程随沙箱命令一起死）。
    成功回写 cookie 文件并返回 True；否则返回 False（字面已打印）。"""
    png_abs = os.path.abspath(os.path.join(work_dir(), QR_PNG))
    if os.path.exists(png_abs):
        os.remove(png_abs)     # 旧码不留：文件存在＝这趟刚出的新码
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    st, j = get_json(PASSPORT + "/x/passport-login/web/qrcode/generate", opener=op)
    if st != 200 or j.get("code") != 0:
        print("STOP generate 失败: " + code_text(j, st))
        return False
    url, key = j["data"]["url"], j["data"]["qrcode_key"]
    ensure_segno()
    import segno
    segno.make(url, error="M", micro=False).save(png_abs, kind="png", scale=8, border=4)
    t_issue = time.time()
    # 这两行是给「喊人」那一半读的：PNG 绝对路径是唯一送达形状
    print("NEEDS_SCAN png=%s" % png_abs, flush=True)
    print("ISSUED_AT=%s ttl≈%ds wall_cap=%ds（别 detach，前台轮询）" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), QR_TTL_S, QR_WALL_S), flush=True)
    seen_scanned = False
    result, d = None, {}
    while time.time() - t_issue < QR_WALL_S:
        time.sleep(POLL_EVERY_S)
        try:
            st, pj = get_json(PASSPORT + "/x/passport-login/web/qrcode/poll?" +
                              urllib.parse.urlencode({"qrcode_key": key}), opener=op)
        except Exception as e:
            print("poll 传输错误 %s（继续）" % type(e).__name__, flush=True)
            continue
        d = pj.get("data") or {}
        inner = d.get("code")
        if inner == 86101:
            continue
        if inner == 86090:
            if not seen_scanned:
                print("SCANNED 已扫，等手机上点确认 since=%ds" % int(time.time() - t_issue), flush=True)
                seen_scanned = True
            continue
        if inner == 86038:
            result = "EXPIRED"
            print("STOP 二维码已失效 86038 since=%ds（重发新码要先确认人在场，别空转）" % int(time.time() - t_issue))
            break
        if inner == 0:
            result = "CONFIRMED"
            break
        result = "UNEXPECTED"
        print("STOP 未见过的 poll 内码，字面: " + code_text(pj, st) + " inner=%r msg=%r" % (inner, d.get("message")))
        break
    if result is None:
        print("STOP 墙钟 %ds 到，无终态，按失效处理（零 cookie）" % QR_WALL_S)
        return False
    if result != "CONFIRMED":
        return False
    # 交换：沿 poll 给的带 auth 的 url 跟重定向，jar 里就有登录 cookie
    ex_url = d.get("url") or ""
    hops = []
    try:
        st, hd, _ = http_get(ex_url, opener=op, timeout=25, accept="*/*")
        hops.append(st)
    except Exception as e:
        print("STOP 交换请求失败 %s" % type(e).__name__)
        return False
    names = {c.name: c.value for c in jar}
    if "SESSDATA" not in names:
        print("STOP 交换后 jar 里没有 SESSDATA；cookie 名=%s hops=%s" % (sorted(names), hops))
        return False
    header = "; ".join("%s=%s" % (k, v) for k, v in names.items())
    verdict, nj = probe(header)
    nd = nj.get("data") or {}
    print("exchange hops=%s cookie 名=%s nav verdict=%s code=%s" % (hops, sorted(names), verdict, nj.get("code")))
    if verdict != "ALIVE":
        print("STOP 交换成功但 nav 不是已登录：" + json.dumps({k: nj.get(k) for k in ("code", "message")}, ensure_ascii=False))
        return False
    doc = load_doc() or {}
    doc["schema"] = "bili_web_qr_login/1"
    doc["state"] = "logged_in"
    doc["logged_in"] = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cookie_names_final": sorted(names),
        "cookies_final": names,
        "cookie_header": header,   # '; ' 分隔
        "uid": nd.get("mid"),
        "nav_readback": {"code": nj.get("code"), "isLogin": nd.get("isLogin")},
        "by": "bili_auto.py qr_login",
    }
    doc.pop("qrcode_key", None)
    atomic_write_json(cookie_path(), doc)
    print("WROTE cookie 文件 %s（值不打印）uid=%s" % (COOKIE_FILE, mid_mask(nd.get("mid"))))
    return True


def ensure_login():
    """返回 (header, doc)；拿不到有效登录态就 sys.exit。"""
    doc = load_doc()
    header = cookie_header_from(doc)
    verdict, nj = probe(header)
    if verdict == "ALIVE":
        print("ALIVE nav code=0 isLogin=true uid=%s" % mid_mask((nj.get("data") or {}).get("mid")))
        return header, doc
    if verdict == "UNKNOWN":
        print("UNKNOWN 探活无法判定（不重登）: " + json.dumps(nj, ensure_ascii=False)[:300])
        sys.exit(3)
    print("DEAD nav: " + (code_text(nj, 200) if "code" in nj else nj.get("_why", "")))
    print("→ 登录态已失效，进扫码重登（需要有人扫）。")
    if not qr_login():
        sys.exit(2)
    doc = load_doc()
    return cookie_header_from(doc), doc


# ---------------------------------------------------------------- wbi
def mixin_key(img_key, sub_key):
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_TAB[:32])


def wbi_sign(params, mk):
    p = dict(params)
    p["wts"] = int(time.time())
    clean = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in sorted(p.items())}
    q = urllib.parse.urlencode(sorted(clean.items()))
    return q + "&w_rid=" + hashlib.md5((q + mk).encode()).hexdigest()


def wbi_keys(cookie):
    st, j = get_json(API + "/x/web-interface/nav", cookie)
    w = (j.get("data") or {}).get("wbi_img") or {}
    f = lambda u: u.rsplit("/", 1)[-1].split(".")[0]
    return f(w.get("img_url", "")), f(w.get("sub_url", ""))


# ---------------------------------------------------------------- 任务
def site_ts(ts):
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S UTC+8 站点侧")


def task_view(bvid, cookie):
    st, j = get_json(API + "/x/web-interface/view?" + urllib.parse.urlencode({"bvid": bvid}), cookie)
    if st != 200 or j.get("code") != 0:
        print("FAIL view " + code_text(j, st))
        return None
    d = j["data"]
    print("VIEW bvid=%s aid=%s cid=%s title=%r" % (d.get("bvid"), d.get("aid"), d.get("cid"), d.get("title")))
    print("  pubdate=%s（%s；站点侧口径，本机钟面会跨日）" % (d.get("pubdate"), site_ts(d.get("pubdate") or 0)))
    print("  stat=%s" % json.dumps(d.get("stat"), ensure_ascii=False))
    return d


def task_hotcomment(bvid):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    st, hd, body = http_get("https://www.bilibili.com/video/" + bvid, opener=op, accept="text/html,*/*")
    print("hop1 www 视频页 HTTP %s bytes=%d jar=%s" % (st, len(body), sorted(c.name for c in jar)))
    if st != 200:
        print("FAIL hop1 视频页没拿到（当没看到，不编）")
        return 4
    time.sleep(HOP_PAUSE_S)
    st, j = get_json(API + "/x/web-interface/view?" + urllib.parse.urlencode({"bvid": bvid}), opener=op)
    print("hop2 view " + code_text(j, st))
    if st != 200 or j.get("code") != 0:
        print("FAIL hop2 view 免登录没过（当没看到，不编）")
        return 4
    aid = j["data"]["aid"]
    print("  aid=%s title=%r" % (aid, j["data"].get("title")))
    time.sleep(HOP_PAUSE_S)
    q = urllib.parse.urlencode({"type": 1, "oid": aid, "sort": 2})
    st, j = get_json(API + "/x/v2/reply?" + q, opener=op, referer="https://www.bilibili.com/video/" + bvid)
    print("hop3 reply?sort=2 " + code_text(j, st))
    if st != 200 or j.get("code") != 0:
        print("FAIL hop3 热评没拿到（当没看到，不编；别改打 /reply/main 或 popular，免登录 -352）")
        return 4
    reps = (j.get("data") or {}).get("replies") or []
    print("HOTCOMMENT count_in_page=%d" % len(reps))
    for r in reps[:5]:
        print("  - like=%s %s %r" % (r.get("like"), site_ts(r.get("ctime") or 0),
                                     ((r.get("content") or {}).get("message") or "")[:80]))
    return 0


def task_arcs(cookie, doc, mid):
    mid = mid or ((doc or {}).get("logged_in") or {}).get("uid")
    if not mid:
        print("FAIL 没有 --mid，cookie 文件里也没有 uid")
        return 4
    ik, sk = wbi_keys(cookie)
    mk = mixin_key(ik, sk)
    base = {"mid": mid, "pn": 1, "ps": 30, "order": "pubdate", "platform": "web", "web_location": int("155010" + "1"),
            "dm_img_list": "[]", "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wg",
            "dm_cover_img_str": "QU5HTEUgKEludGVsLCBJbnRlbChSKSkgRGlyZWN0M0QxMSBvczNfT1MyOTAwZjQsIERpcmVjdDNfT1MyOV92MQ==",
            "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}'}
    for attempt in (1, 2):
        st, j = get_json(API + "/x/space/wbi/arc/search?" + wbi_sign(base, mk), cookie)
        print("arcs try%d %s" % (attempt, code_text(j, st)))
        if j.get("code") == 0:
            break
        time.sleep(HOP_PAUSE_S)
    if j.get("code") != 0:
        return 4
    dd = j["data"]
    vl = (dd.get("list") or {}).get("vlist") or []
    print("ARCS page=%s vlist_len=%d is_risk=%s" % (json.dumps(dd.get("page")), len(vl), dd.get("is_risk")))
    for v in vl[:10]:
        print("  - %s %r created=%s" % (v.get("bvid"), v.get("title"), site_ts(v.get("created") or 0)))
    return 0


def task_danmaku(cid):
    st, hd, raw = http_get("https://comment.bilibili.com/%s.xml" % cid, accept="*/*")
    if st != 200:
        print("FAIL danmaku HTTP %s" % st)
        return 4
    enc = (hd.get("Content-Encoding") or hd.get("content-encoding") or "").lower()
    try:
        xml = zlib.decompress(raw, -15) if enc == "deflate" else raw
    except Exception:
        xml = raw
    txt = xml.decode("utf-8", "replace")
    n = len(re.findall(r"<d p=", txt))
    out = os.path.join(work_dir(), "danmaku_%s.xml" % cid)
    open(out, "wb").write(xml)
    print("DANMAKU cid=%s encoding=%r chars=%d count=%d -> %s" % (cid, enc, len(txt), n, out))
    return 0


def task_download(bvid, out, cookie):
    d = task_view(bvid, cookie)
    if not d:
        return 4
    st, j = get_json(API + "/x/player/playurl?" + urllib.parse.urlencode(
        {"bvid": bvid, "cid": d["cid"], "qn": 64, "fnval": 1}), cookie, referer="https://www.bilibili.com")
    print("playurl " + code_text(j, st))
    if j.get("code") != 0:
        return 4
    du = (j["data"].get("durl") or [{}])[0]
    cands = [du.get("url")] + list(du.get("backup_url") or [])
    for i, u in enumerate([c for c in cands if c][:2]):
        host = urllib.parse.urlsplit(u).netloc
        try:
            st, hd, body = http_get(u, referer="https://www.bilibili.com", timeout=300, accept="*/*")
        except Exception as e:
            print("  源#%d %s 传输错误 %s" % (i, host, type(e).__name__))
            continue
        print("  源#%d %s HTTP %s bytes=%d（接口 size=%s）" % (i, host, st, len(body), du.get("size")))
        if st == 200 and len(body) > 0:
            open(out, "wb").write(body)
            print("DOWNLOADED -> %s sha12=%s" % (out, hashlib.sha256(body).hexdigest()[:12]))
            return 0
        time.sleep(HOP_PAUSE_S)
    print("FAIL 主镜像与 backup 各试一次都没拿到（按规矩不硬试第三次）")
    return 4


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("ensure")
    sub.add_parser("login")
    for n in ("view", "hotcomment"):
        sub.add_parser(n).add_argument("bvid")
    p = sub.add_parser("arcs")
    p.add_argument("--mid")
    sub.add_parser("danmaku").add_argument("cid")
    p = sub.add_parser("download")
    p.add_argument("bvid")
    p.add_argument("--out", required=True)
    a = ap.parse_args()

    print("cookie 文件: %s exists=%s" % (cookie_path(), os.path.exists(cookie_path())))
    if a.cmd == "status":
        doc = load_doc()
        v, nj = probe(cookie_header_from(doc))
        d = nj.get("data") or {}
        print("%s code=%s isLogin=%s uid=%s" % (v, nj.get("code"), d.get("isLogin"), mid_mask(d.get("mid"))))
        return 0 if v == "ALIVE" else (2 if v == "DEAD" else 3)
    if a.cmd == "login":
        return 0 if qr_login() else 2
    if a.cmd == "hotcomment":
        return task_hotcomment(a.bvid)
    if a.cmd == "danmaku":
        return task_danmaku(a.cid)
    header, doc = ensure_login()
    if a.cmd == "ensure":
        return 0
    if a.cmd == "view":
        return 0 if task_view(a.bvid, header) else 4
    if a.cmd == "arcs":
        return task_arcs(header, doc, a.mid)
    if a.cmd == "download":
        return task_download(a.bvid, a.out, header)
    return 0


if __name__ == "__main__":
    sys.exit(main())
