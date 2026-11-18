"""日更备份四步共用的小工具（只被同目录 backup_*.py import，不单独跑）。

围栏（四个脚本都带这一段，改一处记得四处对齐）：
  1. Mongo 只读：连接只调 count_documents／find／buildInfo／serverStatus，没有任何写、drop、建索引。
  2. NAS 只在 xiaoman-backups 这个子目录里动：别的条目一律不碰，删也只认 xiaoman-asuna-backup- 前缀。
  3. 删本机旧份之前，先核 NAS 上有没有同一天、同 sha、同字节数的那份；核不过，本机一份都不删。
  4. NAS 只认局域网那一台：--nas-host 必须是私网 IPv4 字面，不是就拒，不解析域名、不试别的地址。
  5. 用户态 SMB，凭据走保险箱名字 nas-smb（环境变量 NAS_SMB_USER／NAS_SMB_PASS，值不落文件、不打印）；
     pyspnego 强制内置 NTLM。不走系统盘符／系统 UNC（Z:／UNC 经操作系统一律 WinError 5）；
     下面 smbclient 吃的 \\\\server\\share 串是库自己的路径格式，不经操作系统。
  6. 措辞只到「SMB 读回一致」（NAS 返回的字节与本机 sha 一致）；不许写「NAS 自己校验过」——
     校验是我这头算的，NAS 没替我校验任何东西。
"""
import hashlib
import ipaddress
import os
import re
import sys

PREFIX = "xiaoman-asuna-backup-"
SUBDIR = "xiaoman-backups"
CHUNK = 4 * 1024 * 1024
BS = chr(92)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def mask(text, user="", pw=""):
    text = text if isinstance(text, str) else str(text)
    if pw:
        text = text.replace(pw, "[凭据已隐藏]")
    if user:
        text = re.sub(re.escape(user), "[用户名已隐藏]", text)
    return text


def sha_file(path, opener=open):
    h = hashlib.sha256()
    with opener(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def require_lan_host(host):
    """围栏 4：只收私网 IPv4 字面。"""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        print("FAIL: --nas-host 必须是 IP 字面（不解析域名）")
        raise SystemExit(1)
    if ip.version != 4 or not ip.is_private:
        print("FAIL: --nas-host 不是私网 IPv4，围栏 4：NAS 只在局域网那台")
        raise SystemExit(1)
    return host


def nas_dir(host, share):
    return BS * 2 + host + BS + share + BS + SUBDIR


def nas_file(host, share, name):
    """围栏 2：只给 xiaoman-backups 里的文件名；带路径分隔符的名字一律拒。"""
    if BS in name or "/" in name or name in ("", ".", ".."):
        print("FAIL: 文件名带路径成分，围栏 2 拒绝:", name)
        raise SystemExit(1)
    return nas_dir(host, share) + BS + name


def smb_session(host, pylibs):
    """围栏 5：内置 NTLM 的用户态 SMB 会话。返回 (smbclient, user, pw, session)。"""
    user = os.environ.get("NAS_SMB_USER") or ""
    pw = os.environ.get("NAS_SMB_PASS") or ""
    if not user or not pw:
        print("FAIL: 环境没给 NAS_SMB_USER／NAS_SMB_PASS（凭据名 nas-smb），不试")
        raise SystemExit(1)
    if pylibs and pylibs not in sys.path:
        sys.path.insert(0, pylibs)
    import spnego
    original = spnego.client

    def forced(*a, **kw):  # 默认走系统 SSPI，这层拿不到凭据句柄 -> 强制内置 NTLM
        kw["options"] = (kw.get("options") or spnego.NegotiateOptions.none) | spnego.NegotiateOptions.use_ntlm
        return original(*a, **kw)

    spnego.client = forced
    import smbclient
    try:
        sess = smbclient.register_session(host, username=user, password=pw, auth_protocol="ntlm")
    except Exception as e:  # noqa: BLE001 原样报
        print("session setup 失败:", type(e).__name__, "|", mask(str(e), user, pw)[:600])
        raise SystemExit(1)
    return smbclient, user, pw, sess
