"""第 2 步 恢复演练：只读打开快照，读回一节流水，与活库现读并排。

围栏（全文见 _bk_common.py 开头）：Mongo 只读（本步只走 asuna.dbread）；NAS 只在 xiaoman-backups 里动（本步不碰 NAS）；
删本机旧份前先核 NAS 有同日同 sha 那份；NAS 只认局域网那台；用户态 SMB 走凭据 nas-smb；措辞只到「SMB 读回一致」。

靶子节号不许写死：默认每次现读一个「当天之前、不可变」的节号——
  在活库 journal_entries 里取 slug 下 created_at 早于今天本地 00:00 的最近几条，
  挑第一条同时满足 revision == 1 且 updated_at 与 created_at 相差不到 1 秒（建出来后没被改过；
  实测从没改过的行两者也差几微秒，所以不能写成相等）的那一节。
  「不可变」是现读时的证据（没被改过），不是库保证；挑中的 seq 要在报告里照抄。
  想指定就带 --seq（此时不再挑，报告里标「手指定」）。

要点：读回必须 bson.json_util.loads；直接拿 seq == 数字比会判成找不到（int32 在快照里是 {"$numberInt": ...}）。
本进程把整份快照重读一遍再算 sha256（第二把，与导出那进程写侧算的那把对）。
措辞：两边同一台库的同一节，只配说「一致」，不写「验证了正确性」。

用法：python3 backup_drill.py --snapshot <快照路径> [--slug work_log] [--seq N] [--candidates 20]
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bk_common  # noqa: E402,F401

from asuna import dbread  # noqa: E402
from bson import json_util  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--snapshot", required=True)
ap.add_argument("--slug", default="work_log")
ap.add_argument("--seq", type=int, default=None)
ap.add_argument("--candidates", type=int, default=20)
args = ap.parse_args()

SNAP = os.path.abspath(args.snapshot)
SLUG = args.slug
OUTDIR = os.path.dirname(SNAP)
lines = []


def say(s=""):
    print(s)
    lines.append(s)


def flush_readout():
    out = os.path.join(OUTDIR, "drill_readout-%s.txt" % os.path.basename(SNAP).replace(".jsonl", ""))
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\nreadout ->", out)


def pick_seq():
    """现读一个当天之前、没被改过的节号。返回 (seq, 说明)。"""
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    when = dbread.local_window("2000-01-01 00:00:00", "%s 00:00:00" % today)
    ans = dbread.find("journal_entries", {"slug": SLUG, "created_at": when},
                      fields=["seq", "created_at", "updated_at", "revision"],
                      sort=[("created_at", -1)], limit=args.candidates)
    rows = ans.get("rows") or ans.get("documents") or []
    say("挑靶子：journal_entries slug=%s created_at 早于本地 %s 00:00，按 created_at 倒序取 %d 条，命中 %d 行"
        % (SLUG, today, args.candidates, len(rows)))
    for r in rows:
        try:
            gap = abs((datetime.fromisoformat(r["updated_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds())
        except Exception:  # noqa: BLE001 读不懂时间就当不合格
            continue
        if r.get("revision") == 1 and gap < 1.0:
            return r["seq"], "现读挑中：revision=1 且 updated_at 与 created_at 相差 %.6f 秒（当天之前、建后未改）" % gap
    return None, "候选里没有满足条件的"


say("=== 0. 靶子 ===")
if args.seq is not None:
    SEQ, why = args.seq, "手指定（没经过「当天之前、不可变」那道挑选）"
else:
    SEQ, why = pick_seq()
if SEQ is None:
    say("FAIL: " + why + " — 停在这里，不拿别的节号凑")
    flush_readout()
    raise SystemExit(1)
say("靶子 slug=%s seq=%s | %s" % (SLUG, SEQ, why))
say()

say("=== A. 快照侧（只读打开，mode=\"rb\"）===")
say("snapshot path : %s" % os.path.basename(SNAP))
st = os.stat(SNAP)
say("size bytes    : %d | mtime %s" % (st.st_size, datetime.fromtimestamp(st.st_mtime)))

h = hashlib.sha256()
meta = None
percoll = {}
target = None
bad = 0
with open(SNAP, "rb") as f:
    first = True
    for raw in f:
        h.update(raw)
        try:
            rec = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            bad += 1
            continue
        if first:
            meta, first = rec, False
            continue
        coll = rec.get("_coll")
        percoll[coll] = percoll.get(coll, 0) + 1
        if coll == "journal_entries":
            doc = json_util.loads(json.dumps(rec))["doc"]
            if doc.get("slug") == SLUG and doc.get("seq") == SEQ:
                target = doc
sha_snap = h.hexdigest()
say("sha256(本进程重读整份) : %s" % sha_snap)
try:
    with open(SNAP + ".export-summary.json", encoding="utf-8") as f:
        summ = json.load(f)
    say("sha256(导出那进程写的) : %s" % summ.get("sha256_written"))
    say("两把逐字一致           : %s" % (sha_snap == summ.get("sha256_written")))
except Exception as e:  # noqa: BLE001
    say("summary 读不到: %s %s" % (type(e).__name__, e))
say("lines total   : %d (1 meta + %d docs) | JSON 解析失败 %d 行" % (1 + sum(percoll.values()), sum(percoll.values()), bad))
say("docs per coll : %s | total %d" % (percoll, sum(percoll.values())))
if meta:
    say("meta collections: %s | taken_at_utc %s | taken_at_local %s"
        % (meta.get("collections"), meta.get("taken_at_utc"), meta.get("taken_at_local")))
say("target found  : %s" % (target is not None))
if target is None:
    say("（快照里没找到这一节 — 停在这里）")
    flush_readout()
    raise SystemExit(1)

body = target.get("body") or ""
b_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
say("--- 靶子那节（快照侧）---")
say("heading       : %s" % target.get("heading"))
say("_id           : %s" % target.get("_id"))
say("chars         : %d | bytes utf8 %d" % (len(body), len(body.encode("utf-8"))))
say("sha256(body)  : %s" % b_sha)
say("body_sha256(存) %s" % target.get("body_sha256"))
say("first60       : %s" % body[:60].replace("\n", "\\n"))
say()

say("=== B. 活库侧（现读同一节，asuna.dbread）===")
ans = dbread.find("journal_entries", {"slug": SLUG, "seq": SEQ}, limit=5)
say("dbread meta   : %s" % json.dumps({k: ans[k] for k in ("database", "collection", "filter", "limit", "found") if k in ans},
                                         ensure_ascii=False))
rows = ans.get("rows") or ans.get("documents") or []
live = rows[0] if rows else None
if live is None:
    say("活库零行 — 无法并排")
    flush_readout()
    raise SystemExit(1)
lbody = live.get("body") or ""
lsha = hashlib.sha256(lbody.encode("utf-8")).hexdigest()
say("heading       : %s" % live.get("heading"))
say("chars         : %d | bytes utf8 %d" % (len(lbody), len(lbody.encode("utf-8"))))
say("sha256(body)  : %s" % lsha)
say("body_sha256(存) %s" % live.get("body_sha256"))
say("first60       : %s" % lbody[:60].replace("\n", "\\n"))
say()

say("=== C. 并排 ===")
say("chars    snapshot=%d  live=%d  equal=%s" % (len(body), len(lbody), len(body) == len(lbody)))
say("sha256   snapshot=%s" % b_sha)
say("         live    =%s" % lsha)
say("         equal=%s" % (b_sha == lsha))
say("first60  equal=%s" % (body[:60] == lbody[:60]))
say("heading  equal=%s" % (target.get("heading") == live.get("heading")))
say("整节全文逐字 equal=%s" % (body == lbody))
say("_id      snapshot=%s live=%s equal=%s" % (target.get("_id"), live.get("_id"), target.get("_id") == live.get("_id")))
say()
say("措辞守住：两边同一来源（同一台库的同一节），只配说「一致」，不写「验证了正确性」。")
flush_readout()
