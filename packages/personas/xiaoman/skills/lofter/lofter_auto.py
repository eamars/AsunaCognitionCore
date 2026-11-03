#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LOFTER 账号自治：读登录态文件 → 探活 → 失效就自动重登（含拼图滑块）→ 回写文件 → 再取数。

账号事实（blogdomain、blogId、token、手机号、密码）不在本文件里：
  - 登录态：<工作目录>/lofter_login.json（本脚本自己写）
  - blogdomain／blogId：lofter-account.txt（key=value 两行）；没有就用 loginCheck 回的 blogName 拼
  - 手机号／密码：只在环境变量 LOFTER_PHONE／LOFTER_PASS（sandbox_run 带 credentials=["xiaoman-lofter"]）
stdout 只出状态、码、长度，不出值。

子命令：
  status                  读文件 → 探活（loginCheck.do），不重登
  ensure                  探活；失效才重登（需 credentials）
  login                   不管死活直接重登
  collections             ensure → postCollection.api getCollectionList（已验端点）
退出码：0 成功；3 探活无法判定／新风控形状（字面已打印，不重试）；4 取数失败；5 没有凭据；6 滑块四把凑不出一致或没过。
重登预算（一次运行内）：login.do 最多 2 次（一次撞 4071、一次带票据）；captcha 取图最多 2 张（只有四把凑不出一致才换第二张）；
同一张图只发一次 check。4071 之外的风控字样即停。
"""
import argparse
import base64
import hashlib
import json
import os
import random
import re
import string
import sys
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = "lofter_login.json"
LEGACY_STATE = "lf1104_token.json"      # 旧：Fernet 密文，key 在 lf1104_token.key（同目录）
LEGACY_KEY = "lf1104_token.key"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
ANDROID_UA = "LOFTER-Android 8.1.0 (V2245A; Android 12; null) WIFI"
TOKENISH = re.compile(r"[A-Za-z0-9+/=_.:%-]{16,}")
# 前端 captcha 脚本自带的 RSA 公钥（不是我的秘密）；换版本时先核对还是不是这一把
RSA_PUB = ("MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAm4re9B8pjX71Up+b97dvV41bEvNTD0e7aaMyPr8FTHkINSrr"
           "GqXjz4pQ6x8AbioULXYIrzcMO3LyXolLcjE/+0Ubx8KMu30CS2D7TVHEkaZKqz5EKOgWFeepAL6++klyjXO+vVWSDjb8"
           "R6g1VoQKh9MPxLJGqXoFOh9cDahdDRLH1M4a8XboWwljx4CM+vHAuDAwY7i3R4E+bsE+GW5LI7zt/rnTF4tnt0CFazl6"
           "5SiXthyPJglwCZOF2SLs8JJCrknVoWeDyGBMmQ/0gghK4VMAyFcxHCs8y4v7HtOEsRvS4fksSzLSpyNkhGGuNKHk5tBm"
           "5L5m6vApmvUYP6QSdwIDAQAB")


def scrub(s):
    return TOKENISH.sub(lambda m: "<tok len=%d>" % len(m.group(0)), str(s))


def walk(o):
    if isinstance(o, dict):
        return {k: walk(v) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v) for v in o]
    return scrub(o) if isinstance(o, str) else o


def pub(info):
    """打印用：blogName／blogId 是账号事实，只报首末。"""
    d = dict(info)
    for k in ("blogName", "blogId"):
        if d.get(k):
            d[k] = short(d[k])
    return walk(d)


def short(s):
    s = str(s or "")
    return (s[:2] + "~" + s[-2:]) if len(s) > 4 else "~"


# ---------------------------------------------------------------- 路径、文件
def work_dir():
    e = os.environ.get("ASUNA_LOFTER_DIR")
    if e:
        return e
    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, STATE_FILE)) or os.path.basename(cwd) == "local-user":
        return cwd
    p = cwd
    for _ in range(8):
        cand = os.path.join(p, ".runtime", "work", "local-user")
        if os.path.isdir(cand):
            return cand
        q = os.path.dirname(p)
        if q == p:
            break
        p = q
    return cwd


def state_path():
    return os.path.join(work_dir(), STATE_FILE)


def load_state():
    p = state_path()
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            if d.get("token"):
                return d, "file"
        except Exception as e:
            print("WARN 登录态文件读不开: %s" % type(e).__name__)
    return None, "none"


def import_legacy():
    """旧的 Fernet 密文登录态（lf1104_token.*）→ 返回 dict 或 None。只读，不改旧文件。"""
    w = work_dir()
    pj, pk = os.path.join(w, LEGACY_STATE), os.path.join(w, LEGACY_KEY)
    if not (os.path.exists(pj) and os.path.exists(pk)):
        return None
    try:
        from cryptography.fernet import Fernet
        d = json.loads(Fernet(open(pk, "rb").read().strip()).decrypt(open(pj, "rb").read()).decode())
        return d if d.get("token") else None
    except Exception as e:
        print("WARN 旧登录态读不开: %s" % type(e).__name__)
        return None


def save_state(token, deviceid, by):
    d = {"schema": "lofter_login/1", "token": token, "deviceid": deviceid,
         "saved_at": int(time.time()), "saved_at_local": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by}
    p = state_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def load_account():
    """lofter-account.txt：ASUNA_LOFTER_ACCOUNT → ASUNA_DATA_ROOT/private → 往上找 .runtime/private。读不到返回 {}。"""
    cands = []
    if os.environ.get("ASUNA_LOFTER_ACCOUNT"):
        cands.append(os.environ["ASUNA_LOFTER_ACCOUNT"])
    if os.environ.get("ASUNA_DATA_ROOT"):
        cands.append(os.path.join(os.environ["ASUNA_DATA_ROOT"], "private", "lofter-account.txt"))
    p = work_dir()
    for _ in range(8):
        cands.append(os.path.join(p, ".runtime", "private", "lofter-account.txt"))
        q = os.path.dirname(p)
        if q == p:
            break
        p = q
    for c in cands:
        if os.path.exists(c):
            vals = {}
            try:
                for line in open(c, encoding="utf-8", errors="replace").read().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        vals[k.strip()] = v.strip()
            except Exception:
                return {}
            return vals
    return {}


# ---------------------------------------------------------------- HTTP 与探活
def new_client(extra=None):
    h = {"user-agent": UA}
    if extra:
        h.update(extra)
    return httpx.Client(headers=h, timeout=25, follow_redirects=True)


def plant(c, token, deviceid=None):
    """服务端不下发登录态 cookie，按前端 sm() 口径自己种。"""
    for n, v in (("LOFTER-PHONE-LOGIN-AUTH", token), ("token", token), ("LOFTER-PHONE-LOGIN-FLAG", "1")):
        c.cookies.set(n, v, domain=".lofter.com", path="/")
    if deviceid:
        c.cookies.set("deviceid", deviceid, domain=".lofter.com", path="/")


def probe(token, deviceid=None):
    """loginCheck.do：meta.status 200＝活、401＝死，其余＝无法判定。返回 (verdict, info)。"""
    c = new_client({"referer": "https://www.lofter.com/"})
    plant(c, token, deviceid)
    r = None
    try:
        r = c.get("https://www.lofter.com/loginCheck.do", headers={"referer": "https://www.lofter.com/"})
        j = r.json()
    except Exception as e:
        return "UNKNOWN", {"why": "%s HTTP=%s" % (type(e).__name__, r.status_code if r is not None else None)}
    meta = j.get("meta") or {}
    resp = j.get("response") or {}
    info = {"http": r.status_code, "status": meta.get("status"), "msg": scrub(meta.get("msg")),
            "blogName": resp.get("blogName") if isinstance(resp, dict) else None,
            "blogId": resp.get("blogId") if isinstance(resp, dict) else None}
    if meta.get("status") == 200:
        return "ALIVE", info
    if meta.get("status") == 401:
        return "DEAD", info
    return "UNKNOWN", info


# ---------------------------------------------------------------- 重登（含滑块）
def _aes_dec(akey, aiv, ct):
    from cryptography.hazmat.primitives import padding as apad
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    d = Cipher(algorithms.AES(akey.encode()), modes.CBC(aiv.encode())).decryptor()
    raw = d.update(ct) + d.finalize()
    try:
        u = apad.PKCS7(128).unpadder()
        return u.update(raw) + u.finalize()
    except Exception:
        return raw


def solve_slider():
    """取图 → 四把投票 → 唯一一次 check → 返回 (票据或 None, 退出码或 None)。"""
    sys.path.insert(0, HERE)
    import captcha_stage_a as A
    from cryptography.hazmat.primitives import padding as apad
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding as arsa
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    tag = os.path.join(work_dir(), "lofter_cap")
    for n in (1, 2):
        cc = new_client({"referer": "https://www.lofter.com/front/login"})
        rg = cc.get("https://captcha.lofter.com/captcha/get", params={"type": "jigsaw"})
        dg = rg.json()["data"]
        cid, ctype = dg["id"], dg["type"]
        open(tag + "_bg.jpeg", "wb").write(base64.b64decode(dg["bg"]))
        open(tag + "_front.png", "wb").write(base64.b64decode(dg["front"]))
        bg, fr = A.load_pair(tag + "_bg.jpeg", tag + "_front.png")
        readings, _ = A.scores(bg, fr, A.geometry(fr))
        x, why = A.vote(readings)
        print("CAPTCHA #%d 四把=%s 投票=%s xPos=%s" % (n, json.dumps(readings), why, x))
        if x is None:
            if n == 2:
                return None, 6
            continue           # 没发 check，换第二张图
        break
    rk = lambda: "".join(str(random.randint(0, 8)) if random.random() < 0.5
                         else string.ascii_lowercase[random.randint(0, 24)] for _ in range(16))
    akey, aiv = rk(), rk()
    pub = serialization.load_der_public_key(base64.b64decode(RSA_PUB))
    enc_key = base64.b64encode(pub.encrypt((akey + "-" + aiv).encode(), arsa.PKCS1v15())).decode()
    payload = json.dumps({"id": cid, "type": ctype, "data": json.dumps({"xPos": x})},
                         ensure_ascii=False, separators=(",", ":"))
    pad = apad.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(akey.encode()), modes.CBC(aiv.encode())).encryptor()
    body = enc.update(pad.update(payload.encode()) + pad.finalize()) + enc.finalize()
    time.sleep(2.0)
    rc = cc.post("https://captcha.lofter.com/captcha/check", content=body,
                 headers={"content-type": "application/json", "X-EncSecKey": enc_key})
    try:
        txt = _aes_dec(akey, aiv, rc.content).decode("utf-8", "replace")
        try:
            jr = json.loads(txt)
        except Exception:
            jr = json.loads(base64.b64decode(txt).decode("utf-8", "replace"))
    except Exception as e:
        print("CHECK HTTP=%s 解密失败 %s" % (rc.status_code, type(e).__name__))
        return None, 6
    dd = jr.get("data") or {}
    ok = jr.get("code") == 0 and dd.get("success")
    print("CHECK HTTP=%s code=%s success=%s ticket_len=%s" % (
        rc.status_code, jr.get("code"), dd.get("success"), len(dd.get("token") or "")))
    return (dd.get("token") if ok else None), (None if ok else 6)


def relogin():
    """返回 (token, deviceid) 或 sys.exit。"""
    phone_raw, pwd = os.environ.get("LOFTER_PHONE", ""), os.environ.get("LOFTER_PASS", "")
    if not phone_raw or not pwd:
        print("STOP NEEDS_CREDENTIALS：环境里没有 LOFTER_PHONE／LOFTER_PASS。"
              "用 sandbox_run 带 credentials=[\"xiaoman-lofter\"] 重跑本命令；没有这个名字就停在这、报字面，不绕。")
        sys.exit(5)
    digits = re.sub(r"\D", "", phone_raw)
    phone = digits[2:] if digits.startswith("86") and len(digits) == 13 else digits
    body = {"phone": phone, "passport": hashlib.sha256(pwd.encode()).hexdigest(),
            "type": 0, "clientType": 0, "deviceType": 3, "Target": "www.lofter.com"}
    attempts = 0

    def do(ticket=None):
        nonlocal attempts
        c = new_client({"referer": "https://www.lofter.com/front/login", "origin": "https://www.lofter.com"})
        c.get("https://www.lofter.com/front/login")
        h = {"referer": "https://www.lofter.com/front/login", "origin": "https://www.lofter.com", "accept": "*/*"}
        if ticket:
            h["capttoken"] = ticket
        attempts += 1
        r = c.post("https://www.lofter.com/lpt/login.do", params={"product": "lofter-pc"}, data=body, headers=h)
        try:
            j = r.json()
        except Exception:
            print("STOP login 回的不是 JSON HTTP=%s body(脱敏)=%s" % (r.status_code, scrub(r.text[:300])))
            sys.exit(3)
        st = (j.get("meta") or {}).get("status")
        print("LOGIN #%d HTTP=%s meta.status=%s result=%s token_len=%s" % (
            attempts, r.status_code, st, j.get("result"), len(j.get("token") or "")))
        return j, st

    j, st = do()
    if j.get("token"):
        return j["token"], j.get("deviceid")
    if st != 4071:
        print("STOP 4071 之外的新形状（不试第二下）：" + json.dumps(walk(j), ensure_ascii=False)[:500])
        sys.exit(3)
    ticket, rc = solve_slider()
    if not ticket:
        print("STOP 滑块没拿到票据（退出码 %s），按预算停手" % rc)
        sys.exit(rc or 6)
    time.sleep(1.5)
    j, st = do(ticket)
    if j.get("token"):
        return j["token"], j.get("deviceid")
    print("STOP 带票据重登仍没拿到 token：" + json.dumps(walk(j), ensure_ascii=False)[:500])
    sys.exit(3)


def ensure(force=False):
    """返回 (token, deviceid)；拿不到活的就 sys.exit。"""
    token = dev = None
    if not force:
        st, src = load_state()
        if not st:
            leg = import_legacy()
            if leg:
                st, src = leg, "legacy(lf1104_token)"
        if st:
            token, dev = st["token"], st.get("deviceid")
            v, info = probe(token, dev)
            print("PROBE source=%s verdict=%s %s" % (src, v, json.dumps(pub(info), ensure_ascii=False)))
            if v == "ALIVE":
                if src != "file":
                    save_state(token, dev, "imported from legacy")
                    print("WROTE %s（从旧登录态导入）" % STATE_FILE)
                return token, dev
            if v == "UNKNOWN":
                print("UNKNOWN 探活无法判定（不重登）。")
                sys.exit(3)
            print("DEAD 登录态失效（loginCheck 401）→ 自动重登")
        else:
            print("NONE 没有登录态文件 → 自动重登")
    token, dev = relogin()
    v, info = probe(token, dev)
    print("VERIFY after login verdict=%s %s" % (v, json.dumps(pub(info), ensure_ascii=False)))
    if v != "ALIVE":
        print("STOP 登录拿到 token 但 loginCheck 不是 200，不回写。")
        sys.exit(3)
    save_state(token, dev, "lofter_auto relogin")
    print("WROTE %s（值不打印）" % STATE_FILE)
    return token, dev


# ---------------------------------------------------------------- 取数
def task_collections(token, dev):
    acct = load_account()
    v, info = probe(token, dev)
    if acct and not acct.get("blogdomain"):
        print("WARN 账号文件在，但没有 blogdomain 这个键（读到的键名=%s）；回退到 loginCheck 的 blogName" % sorted(acct.keys()))
    dom = acct.get("blogdomain") or ((info.get("blogName") or "") + ".lofter.com")
    c = new_client({"referer": "https://www.lofter.com/"})
    plant(c, token, dev)
    r = c.post("https://api.lofter.com/v1.1/postCollection.api",
               params={"product": "lofter-android-7.6.12"},
               data={"method": "getCollectionList", "blogdomain": dom},
               headers={"user-agent": ANDROID_UA, "content-type": "application/x-www-form-urlencoded; charset=utf-8",
                        "lofter-phone-login-auth": token})
    try:
        j = r.json()
    except Exception:
        print("FAIL collections 非 JSON HTTP=%s %s" % (r.status_code, scrub(r.text[:200])))
        return 4
    meta = j.get("meta") or {}
    rs = j.get("response") if isinstance(j.get("response"), dict) else {}
    shape = ["%s=%s" % (k, ("list len=%d" % len(v)) if isinstance(v, list) else scrub(v)[:40]) for k, v in rs.items()]
    print("COLLECTIONS domain=%s HTTP=%s meta.status=%s msg=%s | %s" % (
        short(dom), r.status_code, meta.get("status"), scrub(meta.get("msg")), "; ".join(shape)[:300]))
    return 0 if meta.get("status") == 200 else 4


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("status", "ensure", "login", "collections"):
        sub.add_parser(n)
    a = ap.parse_args()
    print("登录态文件: %s exists=%s" % (state_path(), os.path.exists(state_path())))
    if a.cmd == "status":
        st, src = load_state()
        if not st:
            print("NONE 没有登录态文件")
            return 3
        v, info = probe(st["token"], st.get("deviceid"))
        print("%s %s" % (v, json.dumps(pub(info), ensure_ascii=False)))
        return 0 if v == "ALIVE" else 3
    token, dev = ensure(force=(a.cmd == "login"))
    if a.cmd in ("ensure", "login"):
        return 0
    if a.cmd == "collections":
        return task_collections(token, dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
