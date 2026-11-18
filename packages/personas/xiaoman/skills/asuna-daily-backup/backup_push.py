"""第 3 步 推 NAS：用户态 SMB ＋ pyspnego 强制内置 NTLM。本脚本不删任何东西：只写、读回算 sha、落 sidecar、列目录。

围栏（全文见 _bk_common.py 开头）：Mongo 只读（本步不碰）；NAS 只在 xiaoman-backups 里动，别人的条目一律不碰；
删本机旧份前先核 NAS 有同日同 sha 那份（删在第 4 步）；NAS 只认局域网那台（--nas-host 非私网 IPv4 字面就拒）；
用户态 SMB 走凭据 nas-smb（环境变量 NAS_SMB_USER／NAS_SMB_PASS），不走盘符／UNC；
措辞只到「SMB 读回一致」：下面所有 sha 都是我这头对 NAS 返回的字节算的，不是 NAS 自己校验过。

用法：
  推：     python3 backup_push.py --snapshot <快照> --nas-host <私网IP> [--share Downloads] [--pylibs <依赖目录>]
  复核：   python3 backup_push.py --snapshot <快照> --nas-host <私网IP> --verify-only [--extra <NAS文件名> ...]
           新进程、新会话，把 NAS 上今天那枚再读一遍算第二把 sha，只读不落不删；
           --extra 的名字用于「删之前先核 NAS 上有同日那份」：本机同名文件与 NAS 并排。
  --pylibs 默认 <cwd>/pylibs（smbprotocol／pyspnego 装在那里；包数与版本现读，不抄旧值）。
"""
import argparse
import hashlib
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bk_common as bk  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--snapshot", required=True)
ap.add_argument("--nas-host", required=True)
ap.add_argument("--share", default="Downloads")
ap.add_argument("--pylibs", default=os.path.join(os.getcwd(), "pylibs"))
ap.add_argument("--verify-only", action="store_true")
ap.add_argument("--extra", nargs="*", default=[])
ap.add_argument("--copy-cap", type=float, default=420.0)
ap.add_argument("--read-cap", type=float, default=420.0)
args = ap.parse_args()

HOST = bk.require_lan_host(args.nas_host)
SRC = os.path.abspath(args.snapshot)
NAME = os.path.basename(SRC)
if not (NAME.startswith(bk.PREFIX) and NAME.endswith(".jsonl")):
    print("FAIL: 快照名不是 %s*.jsonl，围栏 2 只认这个前缀" % bk.PREFIX)
    raise SystemExit(1)
DIRP = bk.nas_dir(HOST, args.share)
BIG = bk.nas_file(HOST, args.share, NAME)
SIDECAR = BIG + ".sha256"
BS = bk.BS

smbclient, USER, PW, sess = bk.smb_session(HOST, args.pylibs)


def mask(t):
    return bk.mask(t, USER, PW)


def sha_nas(path):
    h = hashlib.sha256()
    total, t = 0, time.perf_counter()
    with smbclient.open_file(path, mode="rb") as f:
        while True:
            b = f.read(bk.CHUNK)
            if not b:
                break
            total += len(b)
            h.update(b)
    return total, h.hexdigest(), time.perf_counter() - t


def stat_dir():
    out = {}
    for n in sorted(smbclient.listdir(DIRP)):
        s = smbclient.stat(DIRP + BS + n)
        out[n] = (s.st_size, int(s.st_mtime_ns))
        print("   %-46s size=%-12d mtime_ns=%d" % (n, s.st_size, int(s.st_mtime_ns)))
    return out


print("=== 会话 ===")
print("session setup: 成功 | session_id =", sess.session_id)
conn = getattr(sess, "connection", None)
for attr in ("dialect", "is_signed", "is_encrypted", "max_transact_size", "max_read_size"):
    try:
        print("   connection." + attr, "=", mask(str(getattr(conn, attr))))
    except Exception:  # noqa: BLE001
        print("   connection." + attr, "读不到")
print()

if args.verify_only:
    print("=== 复核（新会话，只读）：全目录 stat ===")
    stat_dir()
    print()
    lsha = bk.sha_file(SRC)
    print("本机 size:", os.path.getsize(SRC), "| 本机 sha256:", lsha)
    nsz, nsha, el = sha_nas(BIG)
    print("NAS 读回 size:", nsz, "| 耗时 %.1fs" % el)
    print("NAS 读回 sha256（第二把，新会话）:", nsha)
    print("size 一致:", nsz == os.path.getsize(SRC), "| SMB 读回 sha 逐字一致:", nsha == lsha)
    with smbclient.open_file(SIDECAR, mode="rb") as f:
        back = f.read()
    print("sidecar 字节:", back, "| 里面那把 == 本机那把:", back.decode("utf-8").split()[0] == lsha)
    for n in args.extra:
        lp = os.path.join(os.path.dirname(SRC), n)
        print()
        print("=== 删除前的同日份核对：%s ===" % n)
        if not os.path.exists(lp):
            print("本机没有同名文件可比:", lp)
            continue
        try:
            nsz2, nsha2, el2 = sha_nas(bk.nas_file(HOST, args.share, n))
        except Exception as e:  # noqa: BLE001
            print("NAS 侧读不到:", type(e).__name__, mask(str(e))[:300])
            continue
        lsha2 = bk.sha_file(lp)
        print("本机 size:", os.path.getsize(lp), "| sha256:", lsha2)
        print("NAS  size:", nsz2, "| sha256:", nsha2, "| 读回 %.1fs" % el2)
        print("同日那份 NAS 真存着（SMB 读回 size 与 sha 都对得上）:", nsz2 == os.path.getsize(lp) and nsha2 == lsha2)
    raise SystemExit(0)

print("=== 第 1 步：列共享根（只看不动）===")
ROOT = BS * 2 + HOST + BS + args.share
try:
    names = sorted(n for n in smbclient.listdir(ROOT) if n not in (".", ".."))
    print("条目数:", len(names))
except Exception as e:  # noqa: BLE001
    print("列根目录失败:", type(e).__name__, "|", mask(str(e))[:400])
    raise SystemExit(1)
print()

print("=== 第 2 步：落点目录（推之前，全量 stat 留档）===")
try:
    before = stat_dir()
except Exception as e:  # noqa: BLE001
    print("列落点失败:", type(e).__name__, "|", mask(str(e))[:400])
    raise SystemExit(1)
mine_before = [n for n in before if n.startswith(bk.PREFIX) and n.endswith(".jsonl")]
print("目录内现有条目数:", len(before), "| 推之前我的快照份数:", len(mine_before), mine_before)
if NAME in before:
    print("FAIL: NAS 上已有同名文件，不覆盖:", NAME)
    raise SystemExit(1)
print()

print("=== 第 3 步：探针（我自己的子目录）===")
PROBE = bk.nas_file(HOST, args.share, "probe-%s.txt" % datetime.now().strftime("%Y%m%d"))
try:
    with smbclient.open_file(PROBE, mode="wb") as f:
        f.write(b"probe\n")
    with smbclient.open_file(PROBE, mode="rb") as f:
        raw = f.read()
    print("路径:", PROBE, "| 读回:", raw, "| sha256:", hashlib.sha256(raw).hexdigest())
except Exception as e:  # noqa: BLE001
    print("探针失败:", type(e).__name__, "|", mask(str(e))[:400])
    raise SystemExit(1)
print()

src_size = os.path.getsize(SRC)
src_sha = bk.sha_file(SRC)
print("=== 第 4 步：整体拷贝（上限 %d 秒）===" % int(args.copy_cap))
print("源文件:", NAME, "| size:", src_size, "| 本机 sha256:", src_sha)
t0 = time.perf_counter()
done = True
try:
    with open(SRC, "rb") as fi, smbclient.open_file(BIG, mode="wb") as fo:
        while True:
            buf = fi.read(bk.CHUNK)
            if not buf:
                break
            fo.write(buf)
            if time.perf_counter() - t0 > args.copy_cap:
                done = False
                print("超过上限，中断")
                break
except Exception as e:  # noqa: BLE001
    done = False
    print("拷贝报错:", type(e).__name__, "|", mask(str(e))[:600])
print("拷贝耗时 %.1fs" % (time.perf_counter() - t0))
if not done:
    try:
        smbclient.remove(BIG)
        print("已删半成品（我自己刚写的这一枚）:", BIG)
    except Exception as e:  # noqa: BLE001
        print("删半成品失败:", type(e).__name__)
    raise SystemExit(1)
print()

print("=== 第 5 步：同会话内读回算 sha256（第一把）===")
t1 = time.perf_counter()
h = hashlib.sha256()
total = 0
timed_out = False
try:
    with smbclient.open_file(BIG, mode="rb") as fo:
        while True:
            if time.perf_counter() - t1 > args.read_cap:
                timed_out = True
                break
            buf = fo.read(bk.CHUNK)
            if not buf:
                break
            total += len(buf)
            h.update(buf)
except Exception as e:  # noqa: BLE001
    print("读回失败:", type(e).__name__, "|", mask(str(e))[:400])
nas_sha_1 = h.hexdigest()
print("NAS 读回 size:", total, "| 耗时 %.1fs" % (time.perf_counter() - t1), "| 超时中断:", timed_out)
print("NAS 读回 sha256（第一把）:", nas_sha_1)
ok1 = total == src_size and nas_sha_1 == src_sha and not timed_out
print("size 与本机一致:", total == src_size, "| SMB 读回 sha 与本机一致:", ok1)
print()

print("=== 第 6 步：sidecar（哈希存第二处）===")
side_text = "%s  %s\n" % (nas_sha_1, NAME)
try:
    with smbclient.open_file(SIDECAR, mode="wb") as f:
        f.write(side_text.encode("utf-8"))
    with smbclient.open_file(SIDECAR, mode="rb") as f:
        back = f.read()
    print("sidecar 路径:", SIDECAR)
    print("sidecar 读回字节:", back, "| 里面那把 == 第一把:", back.decode("utf-8").split()[0] == nas_sha_1)
except Exception as e:  # noqa: BLE001
    print("sidecar 写/读失败:", type(e).__name__, "|", mask(str(e))[:400])
print()

print("=== 第 7 步：推之后全量 stat（不删）===")
after = stat_dir()
mine_after = [n for n in after if n.startswith(bk.PREFIX) and n.endswith(".jsonl")]
print("推之后我的快照份数:", len(mine_after), mine_after)
print("别人的条目（不在我的前缀里）:", [n for n in after if not n.startswith(bk.PREFIX) and not n.startswith("probe-")])
raise SystemExit(0 if ok1 else 2)
