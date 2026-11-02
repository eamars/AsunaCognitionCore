"""LOFTER 无浏览器登录实测（一次性脚本，凭据只从环境变量读，值不打印）。

做法来源：https://www.lofter.com/front/login 页面加载的
lofter-client-account/src/applications/login/pc.1ac5726ef308071a93eb.js
里函数 cm()：POST /lpt/login.do?product=lofter-pc
body {phone, passport:sha256(password), type:0, clientType:0, deviceType:3, Target:"www.lofter.com"}
默认 Content-Type = application/x-www-form-urlencoded; charset=UTF-8（http-fetch-client@2.0.14 的 d/f 默认值）。
成功时前端把返回的 e.token 写进 cookie LOFTER-PHONE-LOGIN-AUTH（maxAge 864e6）。
返回 code 4071 时前端弹 window.Captcha({type:["jigsaw"]})，票据存 localStorage.capttoken，
后续请求带 header capttoken。
"""
import hashlib
import json
import os
import re

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

phone_raw = os.environ.get("LOFTER_PHONE", "")
pwd = os.environ.get("LOFTER_PASS", "")
digits = re.sub(r"\D", "", phone_raw)
phone = digits[2:] if digits.startswith("86") and len(digits) == 13 else digits
print("phone env: has=%s digits_len=%d sent_len=%d" % (bool(phone_raw), len(digits), len(phone)))
print("pass env: has=%s len=%d" % (bool(pwd), len(pwd)))

TOKENISH = re.compile(r"[A-Za-z0-9+/=_.:%-]{16,}")


def scrub(s):
    if not isinstance(s, str):
        s = str(s)
    return TOKENISH.sub(lambda m: "<tok len=%d>" % len(m.group(0)), s)


def walk(o):
    if isinstance(o, dict):
        return {k: walk(v) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v) for v in o]
    if isinstance(o, str):
        return scrub(o)
    return o


def dump(title, obj, limit=1500):
    try:
        s = json.dumps(walk(obj), ensure_ascii=False)
    except Exception:
        s = scrub(obj)
    print(title, s[:limit], "..." if len(s) > limit else "")


client = httpx.Client(headers={"user-agent": UA}, timeout=25, follow_redirects=True)

r0 = client.get("https://www.lofter.com/front/login")
print("warmup GET /front/login status=%s cookies=%s" % (r0.status_code, sorted(client.cookies.keys())))

body = {
    "phone": phone,
    "passport": hashlib.sha256(pwd.encode("utf-8")).hexdigest(),
    "type": 0,
    "clientType": 0,
    "deviceType": 3,
    "Target": "www.lofter.com",
}

resp = None
for attempt in (1, 2):
    try:
        resp = client.post(
            "https://www.lofter.com/lpt/login.do",
            params={"product": "lofter-pc"},
            data=body,
            headers={
                "referer": "https://www.lofter.com/front/login",
                "origin": "https://www.lofter.com",
                "accept": "*/*",
            },
        )
        print("LOGIN attempt=%d status=%s" % (attempt, resp.status_code))
        break
    except Exception as e:  # 只有传输失败才重试一次
        print("LOGIN attempt=%d transport error: %s %s" % (attempt, type(e).__name__, scrub(str(e))[:200]))
        resp = None

if resp is None:
    raise SystemExit("login 没有得到 HTTP 响应")

print("--- response headers (names; set-cookie 只报键名+属性，不报值) ---")
for k, v in resp.headers.items():
    if k.lower() == "set-cookie":
        pieces = v.split(";")
        print("set-cookie: name=%s attrs=%s" % (pieces[0].split("=")[0], "; ".join(p.strip() for p in pieces[1:])))
    else:
        print("%s: %s" % (k, scrub(v)[:120]))

raw = resp.text
print("--- body raw (scrubbed) len=%d ---" % len(raw))
print(scrub(raw)[:2000])

parsed = None
try:
    parsed = resp.json()
except Exception:
    print("(body 不是 JSON)")

# 找 token / deviceid
found = {}


def hunt(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            p = path + "." + k if path else k
            if isinstance(v, str) and re.search(r"token|auth|deviceid|cookie", k, re.I):
                found[p] = v
            hunt(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            hunt(v, "%s[%d]" % (path, i))


if parsed is not None:
    hunt(parsed)
print("--- 登录态字段（只报键名和长度） ---")
for k, v in found.items():
    print("%s: str len=%d" % (k, len(v)))
for k in sorted(resp.cookies.keys()):
    print("client cookie jar: %s len=%d" % (k, len(resp.cookies[k])))

token = None
for key in ("token", "response.token", "data.token", "result.token"):
    if key in found:
        token = found[key]
        break
if token is None:
    for k, v in found.items():
        if re.search(r"token|auth", k, re.I) and len(v) > 40:
            token = v
            break
deviceid = None
for k, v in found.items():
    if "deviceid" in k.lower():
        deviceid = v
        break
print("token picked: %s" % (bool(token) and ("yes len=%d" % len(token)) or "no"))

# 只读验证 1：loginCheck.do（带返回 cookie）
sc = httpx.Client(headers={"user-agent": UA}, timeout=25, follow_redirects=True)
if token:
    for name in ("LOFTER-PHONE-LOGIN-AUTH", "token", "LOFTER-PHONE-LOGIN-FLAG"):
        sc.cookies.set(name, token if name != "LOFTER-PHONE-LOGIN-FLAG" else "1", domain=".lofter.com")
    if deviceid:
        sc.cookies.set("deviceid", deviceid, domain=".lofter.com")
    sc.cookies.set("LOFTER-PHONE-LOGIN-FLAG", "1", domain=".lofter.com")
r1 = sc.get("https://www.lofter.com/loginCheck.do", headers={"referer": "https://www.lofter.com/"})
print("READONLY-1 GET loginCheck.do status=%s" % r1.status_code)
try:
    dump("  json:", r1.json(), 900)
    blog_name = None
    j = r1.json()
    resp_node = j.get("response") or {}
    if isinstance(resp_node, dict):
        blog_name = resp_node.get("blogName")
    print("  blogName=%s blogId=%s" % (blog_name, resp_node.get("blogId") if isinstance(resp_node, dict) else None))
except Exception as e:
    blog_name = None
    print("  非 JSON:", scrub(r1.text)[:300], type(e).__name__)

# 只读验证 2：brief 指定的 postCollection.api
r2 = sc.post(
    "https://api.lofter.com/v1.1/postCollection.api",
    params={"product": "lofter-android-7.6.12"},
    data={"method": "getCollectionList", "blogdomain": (blog_name or "") + ".lofter.com"},
    headers={
        "user-agent": "LOFTER-Android 8.1.0 (V2245A; Android 12; null) WIFI",
        "content-type": "application/x-www-form-urlencoded; charset=utf-8",
        "lofter-phone-login-auth": token or "",
    },
)
print("READONLY-2 POST postCollection.api status=%s blogdomain=%s.lofter.com" % (r2.status_code, blog_name))
try:
    j2 = r2.json()
    meta = j2.get("meta") if isinstance(j2, dict) else None
    print("  meta=%s" % walk(meta))
    rs = j2.get("response") if isinstance(j2, dict) else None
    if isinstance(rs, dict):
        for k, v in rs.items():
            if isinstance(v, list):
                print("  response.%s: list len=%d" % (k, len(v)))
            else:
                print("  response.%s: %s" % (k, walk(v)))
except Exception as e:
    print("  非 JSON:", scrub(r2.text)[:400], type(e).__name__)
