"""LOFTER jigsaw stage B：用 stage A 存的 id 发唯一一次 /captcha/check，成功就用唯一一次登录。

加密照 captcha.js（读码为准，见文件头）：
  body = AES-128-CBC/PKCS7(JSON 文本, key=utf8(AES_SECRETKEY_KEY), iv=utf8(AES_IV)) 的密文原始字节
         （JS 那边是 base64(ciphertext) 再 base64ToArrayBuffer，等价于密文字节）
  X-EncSecKey = base64( RSA_PKCS1_v1_5( key + "-" + iv ) )
  payload = {"id":..., "type":"jigsaw", "data":"{\"xPos\": <float>}"}   # data 是字符串
  回包 = 密文字节 → 解密 → 明文（可能再套一层 base64）→ JSON
"""
import base64
import hashlib
import json
import os
import re
import time

import httpx
from cryptography.hazmat.primitives import padding as asym_padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

TAG = os.environ.get("CAPTAG", "capA")
import sys
XPOS = float(os.environ.get("XPOS") or (sys.argv[1] if len(sys.argv)>1 else -1))
DO_LOGIN = os.environ.get("DO_LOGIN", "yes")
RSA_PUB = ("MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAm4re9B8pjX71Up+b97dvV41bEvNTD0e7aaMyPr8FTHkINSrr"
           "GqXjz4pQ6x8AbioULXYIrzcMO3LyXolLcjE/+0Ubx8KMu30CS2D7TVHEkaZKqz5EKOgWFeepAL6++klyjXO+vVWSDjb8"
           "R6g1VoQKh9MPxLJGqXoFOh9cDahdDRLH1M4a8XboWwljx4CM+vHAuDAwY7i3R4E+bsE+GW5LI7zt/rnTF4tnt0CFazl6"
           "5SiXthyPJglwCZOF2SLs8JJCrknVoWeDyGBMmQ/0gghK4VMAyFcxHCs8y4v7HtOEsRvS4fksSzLSpyNkhGGuNKHk5tBm"
           "5L5m6vApmvUYP6QSdwIDAQAB")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TOKENISH = re.compile(r"[A-Za-z0-9+/=_.:%-]{16,}")

st = json.load(open("%s_state.json" % TAG, encoding="utf-8"))
key = st["aes_key"].encode()
iv = st["aes_iv"].encode()
print("state: id=%s xpos=%.2f 四把读数=%s bg=%dx%d front_w=%d cookies=%d"
      % (st["id"], XPOS, st.get("readings"), st["bg_w"], st["bg_h"], st["front_w"], len(st["cookies"])))


def scrub(s):
    return TOKENISH.sub(lambda m: "<tok len=%d>" % len(m.group(0)), s if isinstance(s, str) else str(s))


def walk(o):
    if isinstance(o, dict):
        return {k: walk(v) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v) for v in o]
    if isinstance(o, str):
        return scrub(s) if False else scrub(o)
    return o


def aes_enc(pt: bytes):
    p = asym_padding.PKCS7(128).padder()
    return p.update(pt) + p.finalize()


def aes_dec(ct: bytes):
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = d.update(ct) + d.finalize()
    try:
        u = asym_padding.PKCS7(128).unpadder()
        return u.update(raw) + u.finalize()
    except Exception:
        return raw


pub = serialization.load_der_public_key(base64.b64decode(RSA_PUB))
encseckey = base64.b64encode(pub.encrypt((st["aes_key"] + "-" + st["aes_iv"]).encode(), asym_rsa.PKCS1v15())).decode()
print("X-EncSecKey: 生成 ok, base64 长度=%d" % len(encseckey))

payload = json.dumps({"id": st["id"], "type": st["type"], "data": json.dumps({"xPos": XPOS})},
                     ensure_ascii=False, separators=(",", ":"))
print("payload 明文(未加密，含 id):", payload)

c = httpx.Client(headers={"user-agent": UA, "referer": "https://www.lofter.com/front/login",
                          "origin": "https://www.lofter.com"}, timeout=25, follow_redirects=True)
for kv in st["cookies"]:
    n, _, v = kv.partition("=")
    c.cookies.set(n, v, domain=".lofter.com", path="/")

padder = asym_padding.PKCS7(128).padder()
body = padder.update(payload.encode()) + padder.finalize()
enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
body = enc.update(body) + enc.finalize()
print("请求体 = 密文字节 %d 个（AES-128-CBC/PKCS7）" % len(body))

time.sleep(2.0)
rc = c.post("https://captcha.lofter.com/captcha/check", content=body,
            headers={"content-type": "application/json", "X-EncSecKey": encseckey})
print("=== 唯一一次 /captcha/check: HTTP %s, 响应 %d 字节 ===" % (rc.status_code, len(rc.content)))
result = None
try:
    pt = aes_dec(rc.content)
    txt = pt.decode("utf-8", "replace")
    try:
        result = json.loads(txt)
    except Exception:
        result = json.loads(base64.b64decode(txt).decode("utf-8", "replace"))
    print("check 解密后 JSON:", json.dumps(walk(result), ensure_ascii=False)[:800])
except Exception as e:
    print("check 响应解密失败:", type(e).__name__, str(e)[:200])
    print("原始响应(前 400):", scrub(rc.text[:400]))

ok = bool(isinstance(result, dict) and result.get("code") == 0 and (result.get("data") or {}).get("success"))
token = (result.get("data") or {}).get("token") if isinstance(result, dict) else None
print("check 通过=%s ticket 存在=%s 长度=%s" % (ok, bool(token), len(token) if token else None))
if not ok or not token or DO_LOGIN != "yes":
    print("按规则停手（不重发 check，也不登录）")
    raise SystemExit(0)

time.sleep(1.5)
phone_raw = os.environ.get("LOFTER_PHONE", "")
pwd = os.environ.get("LOFTER_PASS", "")
digits = re.sub(r"\D", "", phone_raw)
phone = digits[2:] if digits.startswith("86") and len(digits) == 13 else digits
rl = c.post("https://www.lofter.com/lpt/login.do", params={"product": "lofter-pc"},
            data={"phone": phone, "passport": hashlib.sha256(pwd.encode()).hexdigest(),
                  "type": 0, "clientType": 0, "deviceType": 3, "Target": "www.lofter.com"},
            headers={"capttoken": token, "accept": "*/*"})
print("=== 唯一一次登录 POST /lpt/login.do: HTTP %s ===" % rl.status_code)
for h in rl.headers.get_list("set-cookie"):
    parts = h.split(";")
    print("set-cookie: name=%s attrs=%s" % (parts[0].split("=")[0], "; ".join(p.strip() for p in parts[1:])))
print("body(脱敏):", scrub(rl.text)[:900])

found = {}


def hunt(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            p = path + "." + k if path else k
            if isinstance(v, str) and re.search(r"token|auth|deviceid", k, re.I):
                found[p] = v
            hunt(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            hunt(v, "%s[%d]" % (path, i))


try:
    hunt(rl.json())
except Exception:
    pass
print("登录态字段（键名+长度）:", {k: len(v) for k, v in found.items()})
auth = None
for k in ("token", "data.token", "response.token", "result.token"):
    if k in found:
        auth = found[k]
        break
if auth is None:
    for k, v in found.items():
        if len(v) > 40:
            auth = v
            break

# 前端 sm() 成功时写的 cookie，照抄（域 .lofter.com path /）
if auth:
    c.cookies.set("LOFTER-PHONE-LOGIN-AUTH", auth, domain=".lofter.com", path="/")
    c.cookies.set("token", auth, domain=".lofter.com", path="/")
    c.cookies.set("LOFTER-PHONE-LOGIN-FLAG", "1", domain=".lofter.com", path="/")
    c.cookies.set("phone", phone, domain=".lofter.com", path="/")
    for k, v in found.items():
        if "deviceid" in k.lower():
            c.cookies.set("deviceid", v, domain=".lofter.com", path="/")
    print("已按前端 sm() 的口径把登录 cookie 装上（值不外传）")

_BLOG_KEYS = ("blogName", "blogId", "blogdomain", "blogNickName")


def _m(v):
    """打码：账号事实只报首末两位，不进 stdout。"""
    s = "" if v is None else str(v)
    return (s[:2] + "~" + s[-2:]) if len(s) > 4 else ("~" if s else s)


def _mb(o):
    if isinstance(o, dict):
        return {k: (_m(v) if k in _BLOG_KEYS and not isinstance(v, (dict, list)) else _mb(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_mb(x) for x in o]
    return o


r1 = c.get("https://www.lofter.com/loginCheck.do", headers={"referer": "https://www.lofter.com/"})
print("=== 只读 1: GET /loginCheck.do HTTP %s ===" % r1.status_code)
blog = None
try:
    j1 = r1.json()
    print("   ", json.dumps(walk(_mb(j1)), ensure_ascii=False)[:900])
    n = j1.get("response") or {}
    if isinstance(n, dict):
        blog = n.get("blogName")
except Exception:
    print("   非 JSON:", scrub(r1.text[:300]))

r2 = c.post("https://api.lofter.com/v1.1/postCollection.api", params={"product": "lofter-android-7.6.12"},
            data={"method": "getCollectionList", "blogdomain": (blog or "") + ".lofter.com"},
            headers={"user-agent": "LOFTER-Android 8.1.0 (V2245A; Android 12; null) WIFI",
                     "content-type": "application/x-www-form-urlencoded; charset=utf-8",
                     "lofter-phone-login-auth": auth or ""})
print("=== 只读 2: POST postCollection.api blogdomain=%s.lofter.com HTTP %s ===" % (_m(blog), r2.status_code))
try:
    j2 = r2.json()
    print("   meta=", walk(j2.get("meta")), " msg=", walk((j2.get("meta") or {}).get("msg")))
    rs = j2.get("response")
    if isinstance(rs, dict):
        for k, v in rs.items():
            print("   response.%s:" % k, ("list len=%d" % len(v)) if isinstance(v, list) else walk(v))
except Exception as e:
    print("   非 JSON:", scrub(r2.text[:400]), type(e).__name__)
