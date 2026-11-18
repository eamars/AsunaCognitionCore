"""第 4 步 保留：本机留 --keep-local 份，NAS 留 --keep-nas 份（默认 2 和 7）。不带 --do 只报不删。

围栏（全文见 _bk_common.py 开头）：Mongo 只读（本步不碰）；NAS 只在 xiaoman-backups 里动，只认 xiaoman-asuna-backup- 前缀删；
删本机旧份前先核 NAS 上有没有同一天、同字节数、同 sha 的那份（逐字节读回比），NAS 没存着的那份不许删，核不过本机一份都不删；
NAS 只认局域网那台；用户态 SMB 走凭据 nas-smb，不走盘符／UNC；措辞只到「SMB 读回一致」，不写「NAS 自己校验过」。

没脚本化的一格：星期日把某份改名加 -weekly 的规矩，这里没有原文可照，不替我做。含 weekly 字样的名字一律不进删除候选、
也不计入份数（保守做法，是我的判断，不是从旧规则原文抄来的）；碰到这种名字，报告里要看到它被跳过。

用法：python3 backup_retain.py --workdir <本机快照目录> --nas-host <私网IP> [--keep-local 2] [--keep-nas 7] [--do]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bk_common as bk  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--workdir", required=True)
ap.add_argument("--nas-host", required=True)
ap.add_argument("--share", default="Downloads")
ap.add_argument("--pylibs", default=os.path.join(os.getcwd(), "pylibs"))
ap.add_argument("--keep-local", type=int, default=2)
ap.add_argument("--keep-nas", type=int, default=7)
ap.add_argument("--do", action="store_true")
args = ap.parse_args()
if args.keep_local < 1 or args.keep_nas < 1:
    print("FAIL: 保留份数至少 1")
    raise SystemExit(1)

HOST = bk.require_lan_host(args.nas_host)
WD = os.path.abspath(args.workdir)
DIRP = bk.nas_dir(HOST, args.share)
BS = bk.BS
smbclient, USER, PW, sess = bk.smb_session(HOST, args.pylibs)
print("会话 session_id =", sess.session_id, "| --do =", args.do)


def mine(names):
    return sorted(n for n in names if n.startswith(bk.PREFIX) and n.endswith(".jsonl"))


def split_weekly(names):
    return [n for n in names if "weekly" not in n.lower()], [n for n in names if "weekly" in n.lower()]


local_all = mine(os.listdir(WD))
local, local_skip = split_weekly(local_all)
print()
print("=== 本机我的快照（%d 枚计入，保留上限 %d）===" % (len(local), args.keep_local))
for n in local:
    print("   %-48s size=%d" % (n, os.path.getsize(os.path.join(WD, n))))
if local_skip:
    print("   跳过（含 weekly）:", local_skip)

nas_all = mine(smbclient.listdir(DIRP))
nas, nas_skip = split_weekly(nas_all)
print()
print("=== NAS 我的快照（%d 枚计入，保留上限 %d）===" % (len(nas), args.keep_nas))
for n in nas:
    print("   %-48s size=%d" % (n, smbclient.stat(DIRP + BS + n).st_size))
if nas_skip:
    print("   跳过（含 weekly）:", nas_skip)

WEEKLY_CAP = 4
for side, skipped in (("本机", local_skip), ("NAS", nas_skip)):
    if len(skipped) > WEEKLY_CAP:
        print("周留档 %s %d 份，超过上限 %d，未清（脚本不清周留档）" % (side, len(skipped), WEEKLY_CAP))

drop_local = local[: max(0, len(local) - args.keep_local)]
drop_nas = nas[: max(0, len(nas) - args.keep_nas)]
print()
print("本机拟删:", drop_local)
print("NAS 拟删:", drop_nas)
print("今天:", time.strftime("%Y-%m-%d %A"), "（-weekly 改名不在本脚本里）")

print()
print("=== 删本机之前的核对：NAS 上有没有同一天那份（逐字节比 sha）===")
safe = True
checked = {}
for n in drop_local:
    lp = os.path.join(WD, n)
    np_ = bk.nas_file(HOST, args.share, n)
    lsz, lsha = os.path.getsize(lp), bk.sha_file(lp)
    try:
        nsz = smbclient.stat(np_).st_size
        nsha = bk.sha_file(np_, opener=smbclient.open_file)
    except Exception as e:  # noqa: BLE001
        print("   %s -> NAS 读不到（%s）→ 本机这份不删" % (n, type(e).__name__))
        safe = False
        continue
    ok = (lsz == nsz) and (lsha == nsha)
    print("   %s" % n)
    print("      本机 size=%d sha=%s" % (lsz, lsha))
    print("      NAS  size=%d sha=%s  SMB 读回一致=%s" % (nsz, nsha, ok))
    checked[n] = lsha
    if not ok:
        safe = False

print()
if not args.do:
    print("没带 --do：这次只核不删")
elif not safe:
    print("核对没过 → 本机一份都不删（NAS 侧也不动）")
else:
    print("=== 执行：删本机旧份 ===")
    for n in drop_local:
        lp = os.path.join(WD, n)
        sz = os.path.getsize(lp)
        os.remove(lp)
        print("   已删本机 %s | size=%d | sha=%s" % (n, sz, checked.get(n)))
        for ext in (".sha256", ".export-summary.json"):
            side = lp + ext
            if os.path.exists(side):
                os.remove(side)
                print("      并删本机 %s" % os.path.basename(side))
    print()
    print("=== 执行：NAS 保留 %d 份（只删我前缀的，别人的条目不碰）===" % args.keep_nas)
    for n in drop_nas:
        np_ = bk.nas_file(HOST, args.share, n)
        sz = smbclient.stat(np_).st_size
        nsha = bk.sha_file(np_, opener=smbclient.open_file)
        smbclient.remove(np_)
        print("   已删 NAS %s | size=%d | sha=%s" % (n, sz, nsha))
        try:
            smbclient.remove(np_ + ".sha256")
            print("      并删它的 sidecar")
        except Exception as e:  # noqa: BLE001
            print("      sidecar 没删（本来可能没有）:", type(e).__name__)

print()
print("=== 收尾：两边现读 ===")
print("本机:", mine(os.listdir(WD)))
for n in sorted(smbclient.listdir(DIRP)):
    print("   NAS %-48s size=%d" % (n, smbclient.stat(DIRP + BS + n).st_size))
