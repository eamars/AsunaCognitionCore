#!/usr/bin/env python3
"""become_human_due.py：become-human 自查「到点／没到」——替换人肉数「攒够 30 条或满 3 天」。

只读（asuna.dbread）。三步：
  1. 找上一次自查记录：库里 journal_entries（slug=work_log）里 heading 匹配 `become-human\\s*自查` 的最新一条，
     取它的 created_at（UTC）当锚点；没有就是「没有过自查记录」，锚点缺位（见下）。
  2. 数目标群在锚点之后我发出的话：messages 里该群 direction=outbound 且 delivery_state=DELIVERED 的行，
     scene_seq 大于「锚点前最后一条入站行」的 scene_seq（出站行没有 occurred_at，只能借入站行定界，
     所以误差至多是锚点前夹在最后一条入站行之后那几条）。
  3. 距锚点几天（按读的这一刻的 UTC 钟面算，浮点天）。
判据（原样搬自 SKILL 正文「自查节奏与记录」）：出站 >= 30 条，或距上次自查 >= 3 天，先到为准 → 到点；否则没到。
锚点缺位时（没有过自查记录）：条数按该群全部历史出站数，天数写「无记录」，判到点（从没查过就是欠着）。
`--since <UTC 时刻，如 2026-11-01T07:41:24>` 可手动指定锚点，盖过库里找到的。

目标群用 `--place <地点代号>`（也认环境变量 ASUNA_BECOME_HUMAN_PLACE）；脚本里不写群号，
代号在库里经 dbread.place 换成 scene_id，且输出里不打印 scene_id。

用法：
    python3 become_human_due.py --place <地点代号>
    python3 become_human_due.py --place <地点代号> --since 2026-11-01T07:41:24 --json
退出码：0 = 没到点；10 = 到点；1 = 该读的没读到（库读不到、代号换不出群）；2 = 没给 --place。
（10 是「到点」的读数不是故障；调用方按退出码分流，或直接读最后一行「到点」／「没到」。）
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

LIMIT_COUNT = 30
LIMIT_DAYS = 3.0
HEADING = r"become-human\s*自查"


def parse_utc(text):
    """库里的 ISO 串（Z 或 +00:00，带不带小数）→ aware UTC datetime。"""
    cleaned = text.strip().replace("Z", "+00:00")
    stamp = datetime.fromisoformat(cleaned)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def iso_prefix(stamp):
    """比较用的串：到秒的 UTC 前缀（库里 received_at 有 Z 也有 +00:00，前缀比较不受后缀影响）。"""
    return stamp.strftime("%Y-%m-%dT%H:%M:%S")


def aggregate_count(dbread, match):
    out = dbread.aggregate("messages", [{"$match": match}, {"$group": {"_id": None, "n": {"$sum": 1}}}])
    rows = out.get("rows") or []
    return rows[0]["n"] if rows else 0


def main():
    parser = argparse.ArgumentParser(description="become-human 自查到点判（只读）")
    parser.add_argument("--place", default=os.environ.get("ASUNA_BECOME_HUMAN_PLACE"), help="目标群的地点代号")
    parser.add_argument("--since", help="手动指定锚点（UTC，到秒），盖过库里找到的上次自查记录")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.place:
        print("要 --place <地点代号>（或环境变量 ASUNA_BECOME_HUMAN_PLACE）：脚本里不写群号。")
        return 2
    try:
        from asuna import dbread
    except Exception as exc:                                    # noqa: BLE001
        print("import asuna.dbread 失败：%s——这个脚本只在读得到库的地方跑（家里行动脑的沙箱）。" % exc)
        return 1

    now = datetime.now(timezone.utc)
    placed = dbread.place(args.place)
    rows = placed.get("rows") or []
    if not rows:
        print("place %s 换不出群（dbread.place 返回零行）。" % args.place)
        return 1
    scene_id = rows[0]["scene_id"]

    anchor = None
    anchor_from = None
    record_heading = None
    if args.since:
        anchor, anchor_from = parse_utc(args.since), "--since 手动指定"
    else:
        found = dbread.find("journal_entries", {"slug": "work_log", "heading": {"$regex": HEADING}},
                            fields=["heading", "created_at", "seq"], sort=[("created_at", -1)], limit=1)
        hits = found.get("rows") or []
        if hits:
            anchor = parse_utc(hits[0]["created_at"])
            anchor_from = "journal_entries(work_log) 最新一条匹配「%s」" % HEADING
            record_heading = hits[0].get("heading")

    if anchor is None:
        cut_seq = 0
        count = aggregate_count(dbread, {"scene_id": scene_id, "direction": "outbound", "delivery_state": "DELIVERED"})
        days = None
    else:
        before = dbread.find("messages", {"scene_id": scene_id, "direction": "inbound",
                                          "received_at": {"$lt": iso_prefix(anchor)}},
                             fields=["scene_seq"], sort=[("scene_seq", -1)], limit=1)
        brows = before.get("rows") or []
        cut_seq = brows[0]["scene_seq"] if brows else 0
        count = aggregate_count(dbread, {"scene_id": scene_id, "direction": "outbound",
                                         "delivery_state": "DELIVERED", "scene_seq": {"$gt": cut_seq}})
        days = (now - anchor).total_seconds() / 86400.0

    by_count = count >= LIMIT_COUNT
    by_days = days is None or days >= LIMIT_DAYS
    due = by_count or by_days
    result = {
        "place": args.place,
        "read_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "read_at_plus13": (now + timedelta(hours=13)).strftime("%m-%d %H:%M"),
        "read_at_plus8": (now + timedelta(hours=8)).strftime("%m-%d %H:%M"),
        "anchor_utc": anchor.strftime("%Y-%m-%dT%H:%M:%SZ") if anchor else None,
        "anchor_from": anchor_from or "没有过自查记录（journal_entries 里没有匹配的 work_log 条目）",
        "anchor_heading": record_heading,
        "cut_scene_seq": cut_seq,
        "outbound_since_anchor": count,
        "days_since_anchor": round(days, 2) if days is not None else None,
        "limit_count": LIMIT_COUNT,
        "limit_days": LIMIT_DAYS,
        "due_by_count": by_count,
        "due_by_days": by_days,
        "due": due,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 10 if due else 0
    print("读的时刻：UTC %s → UTC+13 %s ／ UTC+8 %s" % (result["read_at_utc"], result["read_at_plus13"], result["read_at_plus8"]))
    print("目标群：place=%s（scene_id 不打印）" % args.place)
    print("锚点：%s（%s）" % (result["anchor_utc"] or "缺位", result["anchor_from"]))
    if record_heading:
        print("  记录标题：%s" % record_heading)
    print("锚点后我在该群发出（DELIVERED）：%d 条（界＝锚点前最后一条入站行 scene_seq=%s；条数 >= %d 算到）"
          % (count, cut_seq, LIMIT_COUNT))
    if days is None:
        print("距上次自查：无记录（没有过自查，天数一格算到）")
    else:
        print("距上次自查：%.2f 天（>= %g 天算到）" % (days, LIMIT_DAYS))
    print("到点" if due else "没到")
    return 10 if due else 0


if __name__ == "__main__":
    sys.exit(main())
