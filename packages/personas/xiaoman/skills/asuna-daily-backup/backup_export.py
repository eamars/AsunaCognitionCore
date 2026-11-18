"""第 1 步 导出：Mongo 严格只读 -> json-lines v1 快照。

围栏（全文见 _bk_common.py 开头）：Mongo 只读；NAS 只在 xiaoman-backups 里动；删本机旧份前先核 NAS 有同日同 sha 那份；
NAS 只认局域网那台；用户态 SMB 走凭据 nas-smb；措辞只到「SMB 读回一致」。本步只碰 Mongo 与本机输出目录。

格式正本 json-lines v1：第 1 行 meta；其余每行 {"_record":"doc","_coll":<表名>,"doc":<文档>}；
doc 用 bson.json_util.dumps(json_options=CANONICAL_JSON_OPTIONS, ensure_ascii=False) 写，
读回用 bson.json_util.loads(line)["doc"] 还原（int32 在快照里是 {"$numberInt": ...}，别拿原始 JSON 直接比）。

用法：python3 backup_export.py --out <输出目录> [--colls 表1 表2 ...]
  默认三张表：journal_entries state_heads state_revisions。
  库地址与库名从环境变量名 ASUNA_MONGO_URI／ASUNA_DATABASE 读（值不落文件）。
  文件名里的时刻用游标开起来前一刻的本机钟面，不是计划时刻；目标已存在就不覆盖。
  写出 <快照名>.export-summary.json 与快照同目录，第 2 步读它里面的写侧 sha。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bk_common  # noqa: E402,F401 统一 UTF-8 输出

from bson import json_util  # noqa: E402
from bson.json_util import CANONICAL_JSON_OPTIONS  # noqa: E402
from pymongo import MongoClient  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--colls", nargs="*", default=["journal_entries", "state_heads", "state_revisions"])
args = ap.parse_args()

OUT = os.path.abspath(args.out)
COLLS = args.colls
URI = os.environ.get("ASUNA_MONGO_URI") or ""
DBNAME = os.environ.get("ASUNA_DATABASE") or ""
if not URI or not DBNAME:
    print("FAIL: 环境没给 ASUNA_MONGO_URI／ASUNA_DATABASE，不猜地址")
    raise SystemExit(1)
os.makedirs(OUT, exist_ok=True)

EXT = re.compile(r'"\$[a-zA-Z]+"')


def mask(u):
    return re.sub(r"//[^@/]*@", "//***@", u)


def localnow():
    return datetime.now().astimezone()


client = MongoClient(URI, serverSelectionTimeoutMS=8000)
db = client[DBNAME]
print("=== 连接（只读）===")
print("uri(掩码)      :", mask(URI))
print("pymongo        :", __import__("pymongo").version)
print("address        :", client.address)
print("database       :", DBNAME)
print("read_preference:", client.read_preference)
print("write concern  :", client.write_concern)
try:
    bi = db.command("buildInfo")
    srv_ver = bi.get("version")
    print("server version :", srv_ver)
except Exception as e:  # noqa: BLE001 权限不足也照实报
    srv_ver = None
    print("server version : 读不到", type(e).__name__, str(e)[:200])


def opcounters(tag):
    """能读到就报写计数器（只读证据）；读不到照实说读不到。"""
    try:
        oc = db.command("serverStatus").get("opcounters", {})
        print("  %s opcounters: insert=%s update=%s delete=%s" % (tag, oc.get("insert"), oc.get("update"), oc.get("delete")))
        return dict((k, oc.get(k)) for k in ("insert", "update", "delete"))
    except Exception as e:  # noqa: BLE001
        print("  %s opcounters 读不到: %s %s" % (tag, type(e).__name__, str(e)[:160]))
        return None


print("\n=== 导出前 ===")
oc_before = opcounters("导出前")
counts_before = {}
for c in COLLS:
    t = time.perf_counter()
    counts_before[c] = db[c].count_documents({})
    print("count_documents %-18s = %6d  (%.2fs)" % (c, counts_before[c], time.perf_counter() - t))

taken = localnow()
taken_utc = taken.astimezone(timezone.utc)
name = "xiaoman-asuna-backup-%s.jsonl" % taken.strftime("%Y-%m-%dT%H%M")
final = os.path.join(OUT, name)
part = final + ".part"
if os.path.exists(final):
    print("FAIL: 目标已存在，不覆盖:", final)
    raise SystemExit(1)

meta = {
    "_record": "meta",
    "format": ('json-lines v1: 第一行 meta，其余每行 {"_record":"doc","_coll":<表名>,"doc":<文档>}；'
               "doc 用 bson.json_util.dumps(json_options=CANONICAL_JSON_OPTIONS, ensure_ascii=False) 写，"
               '读回用 bson.json_util.loads(line)["doc"] 还原 BSON 类型（$oid/$date/$numberLong）'),
    "snapshot_date": taken.strftime("%Y-%m-%d"),
    "source_uri": mask(URI),
    "source_database": DBNAME,
    "server_version": srv_ver,
    "collections": COLLS,
    "filter": "{} 整表，无过滤无投影",
    "sort": '[("_id", 1)]，batch_size=1000',
    "read_mode": "只读游标 find()；本次连接未执行任何写/drop/建索引命令",
    "taken_at_utc": taken_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "taken_at_local": taken.strftime("%Y-%m-%d %H:%M:%S.%f%z"),
    "writer": "pymongo %s cursor -> json_util canonical" % __import__("pymongo").version,
}

print("\n=== 导出 ===")
print("taken_at_local :", meta["taken_at_local"], "（文件名用这个时刻，不是计划时刻）")
print("taken_at_utc   :", meta["taken_at_utc"])
print("目标           :", final)

h = hashlib.sha256()
ndocs = Counter()
bytes_coll = Counter()
ext_types = Counter()
t_start = time.perf_counter()
with open(part, "wb") as f:
    def w(s):
        b = s.encode("utf-8")
        h.update(b)
        f.write(b)

    w(json.dumps(meta, ensure_ascii=False) + "\n")
    for c in COLLS:
        tc = time.perf_counter()
        cur = db[c].find({}).sort([("_id", 1)]).batch_size(1000)
        n = 0
        for doc in cur:
            line = '{"_record": "doc", "_coll": "%s", "doc": %s}\n' % (
                c, json_util.dumps(doc, json_options=CANONICAL_JSON_OPTIONS, ensure_ascii=False))
            for m in EXT.findall(line):
                ext_types[m] += 1
            w(line)
            n += 1
            ndocs[c] += 1
            bytes_coll[c] += len(line.encode("utf-8"))
        print("  %-18s 写了 %6d 条 | %13d B | %.1fs" % (c, n, bytes_coll[c], time.perf_counter() - tc))
    f.flush()
    os.fsync(f.fileno())
dur = time.perf_counter() - t_start
size = os.path.getsize(part)
sha_written = h.hexdigest()
os.replace(part, final)
print("写完:", size, "B | 行数", 1 + sum(ndocs.values()), "| 导出耗时 %.1fs" % dur)
print("写侧 sha256    :", sha_written)

print("\n=== 导出后 ===")
oc_after = opcounters("导出后")
counts_after = {}
for c in COLLS:
    counts_after[c] = db[c].count_documents({})
    print("count_documents %-18s = %6d  （导出中写入 %d）" % (c, counts_after[c], counts_after[c] - ndocs[c]))

print("\n=== 扩展类型普查（对整份快照每行的 $ 键计数）===")
for k, v in sorted(ext_types.items(), key=lambda kv: -kv[1]):
    print("  %-16s %d" % (k, v))
if not ext_types:
    print("  （一个扩展类型键都没有）")

summary = {
    "file": name,
    "path": final,
    "size_bytes": size,
    "sha256_written": sha_written,
    "taken_at_local": meta["taken_at_local"],
    "taken_at_utc": meta["taken_at_utc"],
    "finished_at_local": localnow().strftime("%Y-%m-%d %H:%M:%S.%f%z"),
    "export_seconds": round(dur, 2),
    "lines_total": 1 + sum(ndocs.values()),
    "counts_before": counts_before,
    "counts_written": dict(ndocs),
    "counts_after": counts_after,
    "ext_types": dict(ext_types),
    "opcounters_before": oc_before,
    "opcounters_after": oc_after,
    "server_version": srv_ver,
    "database": DBNAME,
}
spath = final + ".export-summary.json"
with open(spath, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
print("\nsummary ->", spath)
client.close()
