"""Read-only probe of the deployed NapCat: what history/catch-up abilities really exist.

Only read-only actions: get_version_info, get_group_msg_history,
get_friend_msg_history, get_msg, plus one call per name probe.
No message text is printed: only field names, ids, counts, segment types.
"""
import json
import sys
import time

sys.path.insert(0, "/app")

from qqadapter import config as cfgmod                    # noqa: E402
from qqadapter.journal import Counters                    # noqa: E402
from qqadapter.onebot import OneBot                       # noqa: E402

cfg = cfgmod.load()
account = cfg.napcat["account_id"]

events = []
ob = OneBot(cfg.napcat, Counters(), lambda e: events.append(e), log=lambda m: None)
ob.start()
assert ob.wait_up("/api", 20), "api ws down"


def call(action, params, timeout=25.0):
    t0 = time.time()
    try:
        r = ob.api_call(action, params, timeout=timeout)
    except Exception as exc:            # noqa: BLE001
        return {"_error": type(exc).__name__, "_ms": round((time.time() - t0) * 1000)}
    return {"_ms": round((time.time() - t0) * 1000),
            "retcode": r.get("retcode"), "status": r.get("status"),
            "message": str(r.get("message") or "")[:80],
            "wording": str(r.get("wording") or "")[:80],
            "data": r.get("data")}


def shape_of_messages(data, key="messages"):
    msgs = (data or {}).get(key) if isinstance(data, dict) else None
    if not isinstance(msgs, list):
        return {"_shape": type(data).__name__,
                "_keys": sorted((data or {}).keys()) if isinstance(data, dict) else None}
    out = {"n": len(msgs)}
    if msgs:
        m0 = msgs[0]
        out["msg_keys"] = sorted(m0.keys()) if isinstance(m0, dict) else type(m0).__name__
        ids = [m.get("message_id") for m in msgs if isinstance(m, dict)]
        seqs = [m.get("message_seq") for m in msgs if isinstance(m, dict) and m.get("message_seq") is not None]
        times = [m.get("time") for m in msgs if isinstance(m, dict)]
        out["id_min_max"] = [min(ids), max(ids)] if ids else None
        out["seq_min_max"] = [min(seqs), max(seqs)] if seqs else "no message_seq"
        out["time_min_max"] = [min(times), max(times)] if times else None
        out["sender_keys"] = sorted((m0.get("sender") or {}).keys())
        segtypes = {}
        for m in msgs:
            for seg in (m.get("message") or []):
                if isinstance(seg, dict):
                    segtypes[seg.get("type")] = segtypes.get(seg.get("type"), 0) + 1
        out["segment_types"] = segtypes
        out["overlap_with_push_shape"] = sorted(
            set(m0.keys()) & {"post_type", "message_type", "self_id", "group_id", "user_id",
                              "time", "message_id", "sender", "message", "font", "raw_message"})
        out["missing_vs_push"] = sorted(
            {"post_type", "self_id", "message_type", "user_id", "group_id"} - set(m0.keys()))
    return out


print("== version", json.dumps(call("get_version_info", {}), ensure_ascii=False)[:400])

groups = [r.target_id for r in cfg.routes.values() if r.message_type == "group"]
dm_peers = [r.sender_id for r in cfg.routes.values() if r.message_type == "private"]
print("== authorized groups:", len(groups), "dm peers:", len(dm_peers))

gid = groups[0]
r = call("get_group_msg_history", {"group_id": gid, "count": 100})
print("== get_group_msg_history count=100 retcode", r.get("retcode"), r.get("message"), r.get("_ms"), "ms")
print("   shape", json.dumps(shape_of_messages(r.get("data")), ensure_ascii=False))

r2 = call("get_group_msg_history", {"group_id": gid, "count": 500})
d2 = r2.get("data") or {}
print("== count=500 retcode", r2.get("retcode"), "n=", len((d2.get("messages") or [])), "ms", r2.get("_ms"))

msgs = (r.get("data") or {}).get("messages") or []
seqs = sorted([m.get("message_seq") for m in msgs if isinstance(m, dict) and m.get("message_seq") is not None])
if seqs:
    r3 = call("get_group_msg_history", {"group_id": gid, "message_seq": seqs[0], "count": 50})
    m3 = (r3.get("data") or {}).get("messages") or []
    s3 = sorted([m.get("message_seq") for m in m3 if isinstance(m, dict) and m.get("message_seq") is not None])
    print("== page2 by message_seq:", r3.get("retcode"), "n=", len(m3),
          "overlap_with_page1=", len(set(s3) & set(seqs)),
          "seq_min_max=", [s3[0], s3[-1]] if s3 else None)

if msgs:
    probe = msgs[0]
    g = call("get_msg", {"message_id": probe.get("message_id")})
    gd = g.get("data") or {}
    print("== get_msg(history id) retcode", g.get("retcode"),
          "same_id=", gd.get("message_id") == probe.get("message_id"),
          "real_id=", gd.get("real_id"), "seq=", gd.get("message_seq"),
          "keys=", sorted(gd.keys()))

if dm_peers:
    r5 = call("get_friend_msg_history", {"user_id": dm_peers[0], "count": 20})
    print("== get_friend_msg_history retcode", r5.get("retcode"), r5.get("message"))
    print("   shape", json.dumps(shape_of_messages(r5.get("data")), ensure_ascii=False))

for name in ("get_group_msg", "fetch_msg", "get_latest_msg", "catchup", "sync_msg", "get_msg_history"):
    p = call(name, {"group_id": gid, "count": 1}, timeout=10)
    print("== probe", name, "->", p.get("retcode"), p.get("_error") or p.get("message") or p.get("wording"))

ob.stop()
print("== live events seen while probing:", len(events))
