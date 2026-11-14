#!/usr/bin/env python3
"""asuna-daily-review 锚点底稿：起止钟点、窗口边界、群清单、每群出站数、行号区间、并句、
时刻、前后窗计数、机械接话行、段内行、迟到行、后窗未满、非 DELIVERED、跑批凭据，一次取齐，
写成底稿，报告照抄，模型不再手找。语义判断（话题、凭据、a/b/c/d）不在这里，仍手判。
特别是「话题结束」的凭据①②（SKILL.md 二、d 维第 1 条）：整条归语义层，机械层不负责（没实现，不是漏了）；底稿里的「无机械接话」只是「后窗没有机械接话行」，不等于「无回复」。
「按人读数」「迟来接话的疑似派单」两格只是机械列出人和行号、标字面线索，是判词还是段子、是不是派单仍由我当场手判。

用法（在 sandbox_run 或 development_run project=core 里，工作目录＝任务工作区；asuna.dbread 只读）：
    python3 anchors.py [--day YYYY-MM-DD] [--end 'YYYY-MM-DD HH:MM[:SS]'] [--out DIR]
        默认 day＝本地今天（脚本默认值没改）；晨版每天 08:00 跑、复盘昨天一整天，必须显式传 --day <昨天>，不靠默认值；end＝次日零点与读的那一刻里较早的那个。
        写出 DIR/anchors_<day>.json 与 DIR/anchors_<day>.md，stdout 只打摘要。
    python3 anchors.py --check-report 报告.md [--json anchors_<day>.json] [--exclude-place gXXXXXX ...]
        拿报告逐句表里的时刻、前窗行数、后窗接话行、后窗未满、delivery_state、窗口终点、漏句，
        逐条对底稿；有一条对不上退出码 1。
    python3 anchors.py --tables anchors_<day>.json [--owner-author qq:<号> ...]
        只重出「分表（按群一行）」与「主动发起效果追踪」两段（不连库）；底稿 md 末尾本来就带这两段。
    python3 anchors.py --selftest     # 离线：只验纯函数，不连库
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

INT = "asuna:internal"
PLACEHOLDER = re.compile(r"^\[(图片|表情包|视频|语音|文件|合并转发)")
RE_GIVE = re.compile(r"给\s*〔(\d+)〕")
RE_NICK = re.compile(r"@[^\s，。！？】@]{0,12}小满")
# 「疑似派单」字面线索（迟来接话那一桶的标注，11-09 实证：迟来的「接话」有时其实是一条派给我的活）：只标注、不改任何计数，是不是派单手判。
RE_DISPATCH = re.compile(r"帮我|帮忙|麻烦你|劳驾|请你|给我(来|做|写|画|查|发|整理)|你(去|来|能不能|可以)?(查|做|画|写|发|整理|看|试)一?下?|去(查|做|画|写)")
UNIT = 500


def parse_ts(s):
    s = str(s).replace("Z", "+00:00")
    x = dt.datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=dt.timezone.utc)
    return x


def utc_str(x):
    return x.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def is_placeholder(text):
    t = (text or "").strip()
    return (not t) or bool(PLACEHOLDER.match(t))


def dispatch_suspect(text):
    """字面上像派活（帮我／麻烦你／你去查…）：只给「疑似派单」标注用，不进任何计数。"""
    return bool(RE_DISPATCH.search(text or ""))


def hit_kind(text, qq, segs):
    """机械接话线索：@她的qq号 或 「给 〔她的某段行号〕」回应行。昵称@只当软线索另列。"""
    text = text or ""
    kinds = []
    if "@" + qq in text:
        kinds.append("@qq")
    m = RE_GIVE.search(text)
    if m and int(m.group(1)) in segs:
        kinds.append("react")
    return kinds


RE_MENTION = re.compile(r"@\S+|给\s*〔\d+〕|\[[^\]]*\]")


def _bigrams(text):
    """去掉 @、「给 〔行号〕」、[…] 占位、标点空白后的字面二元组集合（只给「语义在接」标注用，不进任何计数）。"""
    body = re.sub(r"[\W_]+", "", RE_MENTION.sub("", text or ""))
    return {body[i:i + 2] for i in range(len(body) - 1)}


def sem_label(row_text, her_text):
    """「语义在接」标注格（只标注、不改任何计数）：给一个其他人的行打一个字面标签。
    空正文：去掉 @／回应字样后不足两个字（纯 @、纯表情回应）；字面有重叠：与她那句共享至少一个二元组；
    无字面重叠：有正文但一个二元组都不共享（疑似是在接别的话头，终判归小满）。"""
    mine = _bigrams(row_text)
    body = re.sub(r"[\W_]+", "", RE_MENTION.sub("", row_text or ""))
    if len(body) < 2:
        return "空正文"
    return "字面有重叠" if mine & _bigrams(her_text) else "无字面重叠"


def build_sentences(rows):
    """同一 episode_id 里连续、segment_index 递增的出站行并成一句。"""
    out, cur, prev_idx = [], None, -1
    for r in sorted(rows, key=lambda r: r["scene_seq"]):
        idx = int(r.get("segment_index") or 0)
        if cur and cur["episode_id"] == r.get("episode_id") and idx > prev_idx:
            cur["rows"].append(r)
        else:
            cur = {"episode_id": r.get("episode_id"), "rows": [r]}
            out.append(cur)
        prev_idx = idx
    return out


def row_time(r):
    return r.get("receipt_at") or r.get("queued_at")


def sha16(text):
    return hashlib.sha256(text.encode()).hexdigest()


def place_code(scene_id):
    return "g" + sha16(scene_id)[:6]


def pages(db, coll, base, fields, limit=UNIT):
    out, last, n = [], None, 0
    while True:
        q = dict(base)
        if last is not None:
            q["scene_seq"] = {"$gt": last}
        r = db.find(coll, q, fields=fields, sort=[("scene_seq", 1)], limit=limit)
        rows = r["rows"]
        out += rows
        n += 1
        if len(rows) < limit:
            return out, n
        last = rows[-1]["scene_seq"]


def window_bounds(db, day, end_arg):
    tz = db._zone(None)
    start = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tz)
    midnight = (start.replace(tzinfo=None) + dt.timedelta(days=1)).replace(tzinfo=tz)
    now = dt.datetime.now(tz).replace(microsecond=0)
    if end_arg:
        shape = "%Y-%m-%d %H:%M:%S" if end_arg.count(":") == 2 else "%Y-%m-%d %H:%M"
        end = dt.datetime.strptime(end_arg, shape).replace(tzinfo=tz)
        src = "手给 --end"
    elif now < midnight:
        end, src = now, "读的那一刻（这天还没过完）"
    else:
        end, src = midnight, "次日零点"
    return tz, start, end, midnight, now, src


def local_str(x, tz):
    return x.astimezone(tz).strftime("%H:%M:%S") if x else "时刻未知"


def sentence_anchor(S, others, qq, soft_ok, tz, start, end, internal_by_ep, morn_end=None):
    rows = S["rows"]
    segs = {r["scene_seq"] for r in rows}
    ts = [parse_ts(row_time(r)) for r in rows if row_time(r)]
    t0 = parse_ts(row_time(rows[0])) if row_time(rows[0]) else (min(ts) if ts else None)
    t1 = parse_ts(row_time(rows[-1])) if row_time(rows[-1]) else (max(ts) if ts else None)
    texts = [(r.get("text") or "").strip() for r in rows]
    real = [t for t in texts if t and not PLACEHOLDER.match(t)]
    stick = any(is_placeholder(t) for t in texts)
    A = {"lo": rows[0]["scene_seq"], "hi": rows[-1]["scene_seq"], "segs": sorted(segs), "n_seg": len(rows),
         "episode_id": S["episode_id"], "t0": local_str(t0, tz), "t1": local_str(t1, tz),
         "t0_receipt": local_str(parse_ts(rows[0]["receipt_at"]), tz) if rows[0].get("receipt_at") else None,
         "t0_queued": local_str(parse_ts(rows[0]["queued_at"]), tz) if rows[0].get("queued_at") else None,
         "text80": " ⏎ ".join(real).replace("\n", " ")[:80] or "[纯贴纸/文件段]",
         "chars": len("".join(real)), "commas": sum(t.count("，") + t.count(",") for t in real),
         "has_sticker_or_file": stick,
         "states": sorted({r.get("delivery_state") or "无" for r in rows}),
         "not_delivered": [(r["scene_seq"], r.get("delivery_state")) for r in rows
                           if r.get("delivery_state") != "DELIVERED"],
         "reply_to_any": any(r.get("reply_to") for r in rows)}
    eps = {S["episode_id"]} | {r.get("reply_to") for r in rows if r.get("reply_to")}
    trig = [x for ep in eps if ep for x in internal_by_ep.get(ep, [])]
    A["trigger_rows"] = [{"seq": x["scene_seq"], "dir": x["direction"], "t": local_str(x["_t"], tz),
                          "author": ("internal" if x.get("author") == INT else x.get("author"))} for x in trig[:4]]
    A["has_internal_trigger"] = any(x["direction"] == "internal" for x in trig)
    if t0 is None or t1 is None:
        A["note"] = "时刻未知：前后窗不算"
        return A
    # 入站时刻只到秒：窗界按整秒比，等值那一秒归右区间（出站回执带小数秒，不截就会把同一秒的行错归前窗）
    t0, t1 = t0.replace(microsecond=0), t1.replace(microsecond=0)
    pre = [o for o in others if t0 - dt.timedelta(minutes=10) <= o["_t"] < t0]
    A["pre_n"] = len(pre)
    A["pre_people"] = len({o.get("author") for o in pre})
    A["pre_last"] = ({"seq": pre[-1]["scene_seq"], "t": local_str(pre[-1]["_t"], tz),
                      "gap_sec": int((t0 - pre[-1]["_t"]).total_seconds())} if pre else None)
    before_any = [o for o in others if o["_t"] < t0]
    A["last_other_before"] = ({"seq": before_any[-1]["scene_seq"], "t": local_str(before_any[-1]["_t"], tz),
                               "gap_sec": int((t0 - before_any[-1]["_t"]).total_seconds())}
                              if before_any else None)
    A["pre10_directed"] = [o["scene_seq"] for o in pre if hit_kind(o.get("text"), qq, segs)]
    A["pre10_directed_soft"] = [o["scene_seq"] for o in pre if RE_NICK.search(o.get("text") or "")
                                and not hit_kind(o.get("text"), qq, segs)]
    post_end = min(t1 + dt.timedelta(minutes=10), end)
    post = [o for o in others if t1 <= o["_t"] < post_end]
    A["post_n"] = len(post)
    A["post_people"] = len({o.get("author") for o in post})
    A["post_unfull"] = (t1 + dt.timedelta(minutes=10)) > end
    ph = [(o["scene_seq"], hit_kind(o.get("text"), qq, segs), local_str(o["_t"], tz),
           int((o["_t"] - t1).total_seconds())) for o in post if hit_kind(o.get("text"), qq, segs)]
    A["post_hits"] = ph[:8]
    A["post_hit_first"] = ph[0][0] if ph else None
    A["post_soft_nick"] = [o["scene_seq"] for o in post if RE_NICK.search(o.get("text") or "")
                           and not hit_kind(o.get("text"), qq, segs)][:5]
    # 「语义在接」标注（只标注，不改上面任何一个计数）：① 每条机械接话命中行的字面标签；
    # ② 后窗里没带机械线索、但字面与她那句有两个以上二元组重叠的行（疑似语义上在接、字面没带词）。
    her_full = "".join(real)
    A["sem_hit_labels"] = [(x[0], sem_label(next((o.get("text") for o in post if o["scene_seq"] == x[0]), ""), her_full))
                           for x in ph[:8]]
    A["sem_nonhit_overlap"] = [o["scene_seq"] for o in post if not hit_kind(o.get("text"), qq, segs)
                               and len(_bigrams(o.get("text")) & _bigrams(her_full)) >= 2][:5]
    gap = [(o["scene_seq"], hit_kind(o.get("text"), qq, segs), local_str(o["_t"], tz),
            int((o["_t"] - t0).total_seconds())) for o in others
           if t0 < o["_t"] < t1 and hit_kind(o.get("text"), qq, segs)]
    A["gap_hits_inside_segments"] = gap
    late = [(o["scene_seq"], hit_kind(o.get("text"), qq, segs), local_str(o["_t"], tz))
            for o in others if t1 + dt.timedelta(minutes=10) <= o["_t"] < end
            and hit_kind(o.get("text"), qq, segs)]
    A["late_hit_n"] = len(late)
    A["late_hits_first3"] = late[:3]
    # 迟来接话一桶的「疑似派单」标注（字面线索，只标注不改 late_hit_n；是不是派单手判）
    A["late_dispatch_suspect"] = [o["scene_seq"] for o in others
                                  if t1 + dt.timedelta(minutes=10) <= o["_t"] < end
                                  and hit_kind(o.get("text"), qq, segs) and dispatch_suspect(o.get("text"))][:5]
    # 逐行接话记录（只给分表／效果追踪用，不进任何既有计数）：[行号, author, 距末段秒, 桶]；
    # 桶＝post（后 10 分钟内）／tail（10 分钟后至窗口终点）／morn（窗口终点至跑起时刻，只有晨版跑在次日零点之后才读）
    hr_end = morn_end or end
    A["morn_read"] = morn_end is not None
    A["morn_until"] = local_str(morn_end, tz) if morn_end else None
    A["hit_rows"] = [[o["scene_seq"], o.get("author"), int((o["_t"] - t1).total_seconds()),
                      "post" if o["_t"] < t1 + dt.timedelta(minutes=10) else ("tail" if o["_t"] < end else "morn")]
                     for o in others if t1 <= o["_t"] < hr_end and hit_kind(o.get("text"), qq, segs)]
    for label, mins in (("h30", 30), ("h90", 90), ("h6h", 360)):
        lim = t1 + dt.timedelta(minutes=mins)
        hs = [(o["scene_seq"], int((o["_t"] - t1).total_seconds())) for o in others
              if t1 <= o["_t"] < min(lim, end) and hit_kind(o.get("text"), qq, segs)]
        A[label] = {"hits": hs[:12], "n": len(hs), "unfull": lim > end,
                    "first_latency_sec": hs[0][1] if hs else None}
    after = [o for o in others if t1 <= o["_t"] < end]
    A["after_n"] = len(after)
    A["after_first"] = ({"seq": after[0]["scene_seq"], "t": local_str(after[0]["_t"], tz),
                         "gap_sec": int((after[0]["_t"] - t1).total_seconds())} if after else None)
    A["after_last"] = ({"seq": after[-1]["scene_seq"], "t": local_str(after[-1]["_t"], tz)} if after else None)
    if A["reply_to_any"]:
        A["cls_hint"] = "回复(reply_to 有值)"
    elif A["pre10_directed"]:
        A["cls_hint"] = "回复(前10分钟有指向我的行)"
    else:
        A["cls_hint"] = "发起候选(须再看是否续接他人30分钟内话头；取严侧归回复)"
    return A


def gen(db, args):
    tz, start, end, midnight, now, src = window_bounds(db, args.day, args.end)
    fmt = "%Y-%m-%d %H:%M:%S"
    win = db.local_window(start.strftime(fmt), end.strftime(fmt))
    morn_end = now if (end == midnight and now > midnight) else None  # 晨前迟到接：次日零点→跑起时刻
    ext = db.local_window((start - dt.timedelta(minutes=10)).strftime(fmt), (morn_end or end).strftime(fmt))
    head = {"day": args.day, "generated_at_local": now.strftime(fmt), "tz": str(tz),
            "start_local": start.strftime(fmt), "end_local": end.strftime(fmt), "end_source": src,
            "next_midnight_local": midnight.strftime(fmt), "utc": [win["$gte"], win["$lt"]],
            "right_open": True, "morn_end_local": morn_end.strftime(fmt) if morn_end else None}
    # 群清单
    raw, skip = [], 0
    while True:
        r = db.find("scenes", {"kind": "group"}, fields=["_id", "kind", "sequence"], limit=50, skip=skip)
        raw += r["rows"]
        skip += 50
        if len(r["rows"]) < 50:
            break
    groups = sorted(x["_id"] for x in raw if not x["_id"].startswith("local-"))
    head["scenes_group_rows"] = len(raw)
    head["groups_kept"] = len(groups)
    # 全部出站按场景×状态数一遍
    agg = db.aggregate("messages", [
        {"$match": {"direction": "outbound", "queued_at": win}},
        {"$group": {"_id": {"s": "$scene_id", "d": "$delivery_state"}, "n": {"$sum": 1},
                    "lo": {"$min": "$scene_seq"}, "hi": {"$max": "$scene_seq"}}}], limit=500)
    if agg.get("more"):
        head["agg_more_warning"] = agg["more"]
    per, nongroup = {}, {}
    for x in agg["rows"]:
        sid, st = x["_id"]["s"], x["_id"]["d"]
        tgt = per if sid in groups else nongroup
        e = tgt.setdefault(sid, {"n": 0, "lo": x["lo"], "hi": x["hi"], "states": {}})
        e["n"] += x["n"]
        e["lo"], e["hi"] = min(e["lo"], x["lo"]), max(e["hi"], x["hi"])
        e["states"][str(st)] = e["states"].get(str(st), 0) + x["n"]
    head["groups_with_outbound"] = len(per)
    head["zero_outbound_groups"] = [g for g in groups if g not in per]
    zero = head["zero_outbound_groups"]
    head["zero_group_at"] = None  # 读不到就是 None，分表写「未读」，不填 0
    if zero:
        try:
            qq0 = zero[0].split(":")[1]
            za = db.aggregate("messages", [
                {"$match": {"direction": "inbound", "scene_id": {"$in": zero}, "occurred_at": win,
                            "text": {"$regex": "@" + qq0 + "|@[^\\s，。！？】@]{0,12}小满"}}},
                {"$group": {"_id": {"s": "$scene_id", "a": "$author"}, "n": {"$sum": 1}}}], limit=500)
            if za.get("more"):
                head["zero_group_at_more"] = za["more"]
            else:
                head["zero_group_at"] = {}
                for x in za["rows"]:
                    head["zero_group_at"].setdefault(x["_id"]["s"], {})[x["_id"]["a"]] = x["n"]
                for sid0 in zero:
                    head["zero_group_at"].setdefault(sid0, {})
        except Exception as exc:  # noqa: BLE001
            head["zero_group_at_error"] = "%s: %s" % (type(exc).__name__, exc)
    head["nongroup_outbound"] = {k: {"n": v["n"], "lo": v["lo"], "hi": v["hi"]} for k, v in nongroup.items()}
    # 尾段：终点之后到次日零点
    tail = {}
    if end < midnight:
        tw = db.local_window(end.strftime(fmt), midnight.strftime(fmt))
        ta = db.aggregate("messages", [
            {"$match": {"direction": "outbound", "scene_id": {"$regex": ":group:"}, "queued_at": tw}},
            {"$group": {"_id": "$scene_id", "n": {"$sum": 1}, "lo": {"$min": "$scene_seq"},
                        "hi": {"$max": "$scene_seq"}}}], limit=500)
        tail = {x["_id"]: {"n": x["n"], "lo": x["lo"], "hi": x["hi"]} for x in ta["rows"]}
    head["tail_after_end_outbound_rows"] = tail
    # 跑批凭据：这一天前后的自省任务
    t_lo = db.local_window((start + dt.timedelta(hours=12)).strftime(fmt),
                           (midnight + dt.timedelta(hours=30)).strftime(fmt))
    tr = db.find("tasks", {"created_at": t_lo, "title": {"$regex": "自省|daily-review|日省"}},
                 fields=["_id", "title", "state", "created_at", "started_at", "finished_at", "failure_type",
                         "tool_steps"], sort=[("created_at", 1)], limit=50)
    head["review_tasks"] = [{
        "id": x["_id"], "title": (x.get("title") or "")[:40], "state": x.get("state"),
        "created": local_str(parse_ts(x["created_at"]), tz) if x.get("created_at") else None,
        "started": local_str(parse_ts(x["started_at"]), tz) if x.get("started_at") else None,
        "finished": local_str(parse_ts(x["finished_at"]), tz) if x.get("finished_at") else None,
        "failure_type": x.get("failure_type"), "steps": x.get("tool_steps")} for x in tr["rows"]]
    result = {"head": head, "groups": {}}
    for sid in sorted(per):
        qq = sid.split(":")[1]
        code = place_code(sid)
        outs, npg = pages(db, "messages", {"scene_id": sid, "direction": "outbound", "queued_at": win},
                          ["scene_seq", "episode_id", "segment_index", "text", "reply_to", "delivery_state",
                           "queued_at", "receipt_at", "author"])
        her = {o.get("author") for o in outs}
        ins, npg2 = pages(db, "messages", {"scene_id": sid, "direction": {"$in": ["inbound", "internal"]},
                                           "occurred_at": ext},
                          ["scene_seq", "direction", "author", "text", "occurred_at", "episode_id"])
        others, internal_by_ep = [], {}
        for x in ins:
            x["_t"] = parse_ts(x["occurred_at"]) if x.get("occurred_at") else None
            if x["_t"] is None:
                continue
            internal_by_ep.setdefault(x.get("episode_id"), []).append(x)
            if x.get("author") == INT or x.get("author") in her or x.get("author") == "qq:" + qq:
                continue
            others.append(x)
        others.sort(key=lambda o: (o["_t"], o["scene_seq"]))
        in_win = [o for o in others if start <= o["_t"] < end]
        lens = [len((o.get("text") or "").strip()) for o in in_win if not is_placeholder(o.get("text"))]
        sents = build_sentences(outs)
        sa = [sentence_anchor(S, others, qq, True, tz, start, end, internal_by_ep, morn_end) for S in sents]
        notes = db.find("state_heads", {"_id": {"$regex": sha16(sid)[:16] + "|group_notes:" + code}},
                        fields=["_id"], limit=20)["rows"]
        sl = [a["chars"] for a in sa]
        result["groups"][sid] = {
            "place": code, "qq": qq, "outbound": per[sid], "out_pages": npg, "ctx_pages": npg2,
            "out_rows_fetched": len(outs), "ctx_rows_fetched": len(ins),
            "n_sentences": len(sa), "others_rows": len(in_win),
            "others_people": len({o.get("author") for o in in_win}),
            "others_len_median": statistics.median(lens) if lens else None,
            "others_placeholder_rows": len(in_win) - len(lens),
            "her_len_median": statistics.median(sl) if sl else None,
            "her_commas_mean": round(statistics.mean(a["commas"] for a in sa), 2) if sa else None,
            "note_doc_ids": [x["_id"] for x in notes],
            "note_lookup": "按 sha 前缀与旧格式正则查；0 行只说明这两种形状没命中，不是「没有群笔记」的凭据"
            if not notes else "命中",
            "by_person": by_person(others, sa, qq, start, end, tz),
            "sentences": sa}
    return result


def by_person(others, sentences, qq, start, end, tz):
    """按人读数（纯机械，不判语义）：每个别人的「指向我的行」（@我的号、或昵称@小满）和「接了我哪句的行」（机械接话命中，每句取 6 小时内前 12 条），逐条带行号和时刻；
    指向行里字面像派活的标「疑似派单」。「这条指向行是判词还是段子」「是不是真派单」归语义层，这里不判。"""
    who = {}
    seq_author = {o["scene_seq"]: o.get("author") for o in others}
    for o in others:
        if not (start <= o["_t"] < end):
            continue
        kinds = []
        if "@" + qq in (o.get("text") or ""):
            kinds.append("@qq")
        elif RE_NICK.search(o.get("text") or ""):
            kinds.append("昵称@")
        if kinds:
            e = who.setdefault(o.get("author"), {"directed": [], "connected": []})
            e["directed"].append({"seq": o["scene_seq"], "t": local_str(o["_t"], tz), "kind": kinds[0],
                                  "suspect_dispatch": dispatch_suspect(o.get("text"))})
    for a in sentences:
        for seq, _lat in (a.get("h6h") or {}).get("hits", []):
            au = seq_author.get(seq)
            if au is None:
                continue
            e = who.setdefault(au, {"directed": [], "connected": []})
            e["connected"].append({"seq": seq, "after_sentence": a["lo"]})
    return {k: v for k, v in sorted(who.items(), key=lambda kv: str(kv[0]))}


def person_md(g):
    """「按人读数」表（按群）：人｜指向我的行（行号／类型／疑似派单）｜接了我哪句（行号←句首行）。只标注。"""
    bp = g.get("by_person") or {}
    if not bp:
        return ["- 按人读数：本群窗口内没有指向我的行、也没有机械接话命中", ""]
    L = ["按人读数（纯机械：指向行＝@我的号或昵称@；「疑似派单」是字面线索不是结论；判词还是段子、是不是真派单归语义层）：", "",
         "| 人 | 指向我的行（行号·类型·疑似派单） | 接了我哪句（接话行←句首行） |", "|---|---|---|"]
    for au, e in bp.items():
        d = "、".join("%d·%s%s" % (x["seq"], x["kind"], "·疑似派单" if x["suspect_dispatch"] else "") for x in e["directed"]) or "—"
        c = "、".join("%d←%d" % (x["seq"], x["after_sentence"]) for x in e["connected"]) or "—"
        L.append("| %s | %s | %s |" % (au, d, c))
    return L + [""]


def sem_cell(a):
    """「语义在接」标注格的文字：命中行各打一个字面标签；后窗里没带机械线索但字面有重叠的行另列为「疑似在接」。只标注。"""
    parts = ["%d:%s" % (s, lab) for s, lab in a.get("sem_hit_labels", [])]
    if a.get("sem_nonhit_overlap"):
        parts.append("疑似在接(无机械线索):" + "、".join(str(x) for x in a["sem_nonhit_overlap"]))
    return "；".join(parts) or "—"


def md_of(res, owners=()):
    h = res["head"]
    L = ["# 锚点底稿 " + h["day"], "",
         "- 窗口（本地，右开）：%s → %s（终点来源：%s；次日零点＝%s）" % (
             h["start_local"], h["end_local"], h["end_source"], h["next_midnight_local"]),
         "- 换成 UTC：%s → %s；时区 %s；底稿生成 %s" % (h["utc"][0], h["utc"][1], h["tz"], h["generated_at_local"]),
         "- 群清单：scenes kind=group %d 行，剔本机测试群后 %d 个；有出站 %d 个；0 出站 %d 个"
         % (h["scenes_group_rows"], h["groups_kept"], h["groups_with_outbound"], len(h["zero_outbound_groups"])),
         "- 0 出站的群：" + "、".join(g.split(":")[-1] for g in h["zero_outbound_groups"]),
         "- 终点之后到次日零点仍有出站行：%s" % (json.dumps({k.split(":")[-1]: v for k, v in
                                               h["tail_after_end_outbound_rows"].items()}, ensure_ascii=False)
                                      or "无"),
         "- 非群出站：%s" % json.dumps({k: v["n"] for k, v in h["nongroup_outbound"].items()}, ensure_ascii=False),
         "- 跑批凭据（这一天前后的自省任务）：" + ("无" if not h["review_tasks"] else "")]
    for t in h["review_tasks"]:
        L.append("  - %(id)s｜%(state)s｜建 %(created)s 起 %(started)s 止 %(finished)s｜失败 %(failure_type)s｜%(steps)s 步｜%(title)s" % t)
    L.append("")
    for sid, g in res["groups"].items():
        L += ["## %s（群号 %s）" % (g["place"], g["qq"] and sid.split(":")[-1]),
              "- 出站 %d 行（%s）seq %d–%d，并成 %d 句；出站页数 %d、上下文行 %d（页 %d），都按本页行数<页容量判完"
              % (g["outbound"]["n"], json.dumps(g["outbound"]["states"], ensure_ascii=False),
                 g["outbound"]["lo"], g["outbound"]["hi"], g["n_sentences"], g["out_pages"],
                 g["ctx_rows_fetched"], g["ctx_pages"]),
              "- 别人入站 %d 行／%d 人；别人行长中位 %s（另 %d 行占位）；她句长中位 %s；她每句逗号均值 %s"
              % (g["others_rows"], g["others_people"], g["others_len_median"], g["others_placeholder_rows"],
                 g["her_len_median"], g["her_commas_mean"]),
              "- 群笔记键：%s（%s）" % (g["note_doc_ids"] or "无", g["note_lookup"]), "",
              "| 行号 | 时刻 | 段数 | 状态 | 前窗(行/人/末行距) | 后窗(行/人/未满) | 机械接话首行(30/90/6h) | 语义在接(仅标注) | 段内指向我 | 迟到接话行数 | 末段后全场(行/末行) | 归类提示 | 她的话 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for a in g["sentences"]:
            if "pre_n" not in a:
                L.append("| %d–%d | %s | %d | %s | 时刻未知 | | | | | | | | %s |" % (
                    a["lo"], a["hi"], a["t0"], a["n_seg"], ",".join(a["states"]), a["text80"]))
                continue
            pl = a["pre_last"]
            f = lambda k: ("%s%s" % (a[k]["hits"][0][0] if a[k]["hits"] else "无", "·窗未满" if a[k]["unfull"] else ""))
            L.append("| %d–%d | %s–%s | %d | %s | %d/%d/%s | %d/%d/%s | %s/%s/%s | %s | %s | %s | %d/%s | %s | %s |" % (
                a["lo"], a["hi"], a["t0"], a["t1"], a["n_seg"], ",".join(a["states"]),
                a["pre_n"], a["pre_people"], ("%ds" % pl["gap_sec"]) if pl else "场冷",
                a["post_n"], a["post_people"], "后窗未满" if a["post_unfull"] else "满",
                f("h30"), f("h90"), f("h6h"),
                sem_cell(a),
                "、".join("%d(+%ds)" % (x[0], x[3]) for x in a["gap_hits_inside_segments"]) or "无",
                ("%d" % a["late_hit_n"]) + (("（疑似派单：" + "、".join(str(x) for x in a["late_dispatch_suspect"]) + "）") if a.get("late_dispatch_suspect") else ""), a["after_n"], (a["after_last"] or {}).get("seq", "—"),
                a["cls_hint"].split("(")[0], a["text80"].replace("|", "｜")))
        L.append("")
        L += person_md(g)
    L += group_rows_md(res, owners) + effect_md(res, owners)
    return "\n".join(L) + "\n"


# ---- 终判层两格：分表（按群一行）与主动发起效果追踪（只读底稿，机械列出，不判语义）----
# 不计分的家人场合：现有口径只有「小满家群整群剔出」一处（SKILL.md「owner 的反应不计分」一节）；家里线与别的非群线不进群清单，分表另行列出并标不计分。
FAMILY_PLACES = {"g9a8e3b": "小满家群"}
CONT_LIMIT_SEC = 1800  # 延续一轮的时限：首个接话行之后 30 分钟内的第二行才算「有」，超了写「跨时段（+Ns）」


def _author_map(g):
    m = {}
    for au, e in (g.get("by_person") or {}).items():
        for x in e.get("connected", []):
            m[x["seq"]] = au
        for x in e.get("directed", []):
            m[x["seq"]] = au
    return m


def _hit_list(a, amap):
    """一句的机械接话行 [(行号, author, 距末段秒, 桶)]；新底稿读 hit_rows（逐行齐全），
    旧底稿退回 h6h 前 12 条（作者靠按人读数反查，查不到记 ?）。第二项＝是否逐行齐全。"""
    if "hit_rows" in a:
        return [tuple(x) for x in a["hit_rows"]], True
    return [(s, amap.get(s, "?"), lat, "post" if lat < 600 else "tail")
            for s, lat in (a.get("h6h") or {}).get("hits", [])], False


def _is_cand(a):
    """主动发起的机械候选：只核判据①（前 10 分钟没有指向我的行：@我的号、昵称@）。
    判据②（续接他人 30 分钟内话头）归语义手判，这里不实现。时刻未知的句子返回 None（不入候选、另计）。"""
    if "pre_n" not in a:
        return None
    return not a.get("pre10_directed") and not a.get("pre10_directed_soft")


def _view(a, amap, owners):
    hits, full = _hit_list(a, amap)
    ok = [h for h in hits if h[1] not in owners]
    if full:
        tail_n = sum(1 for h in ok if h[3] == "tail")
        morn_n = sum(1 for h in ok if h[3] == "morn") if a.get("morn_read") else None
    else:
        tail_n, morn_n = a.get("late_hit_n", 0), None
    return {"hits": sorted(ok, key=lambda h: h[2]), "post": [h for h in ok if h[3] == "post"],
            "tail_n": tail_n, "morn_n": morn_n, "owner_n": len(hits) - len(ok), "full": full}


def group_rows(res, owners=()):
    """分表数据：每个我所在的群一行（歇着的、零行的、不计分的都出行），另加非群线的不计分行。"""
    owners = set(owners)
    head = res["head"]
    by_place = {g["place"]: g for g in res["groups"].values()}
    sids = sorted(set(res["groups"]) | set(head.get("zero_outbound_groups", [])), key=place_code)
    zat = head.get("zero_group_at")
    rows = []
    for sid in sids:
        code = place_code(sid)
        row = {"place": code, "gid": sid.split(":")[-1], "noscore": FAMILY_PLACES.get(code), "legacy": False,
               "sent": 0, "at": 0, "cand": 0, "unk": 0, "got": 0, "pending": 0, "tail": 0, "morn": 0, "note": []}
        g = by_place.get(code)
        if g is None:
            row["note"].append("0 出站（歇着）")
            if zat is None or sid not in zat:
                row["at"] = None
            else:
                row["at"] = sum(n for au, n in zat[sid].items() if au not in owners)
        else:
            amap = _author_map(g)
            row["sent"] = g["n_sentences"]
            row["at"] = sum(1 for au, e in (g.get("by_person") or {}).items() if au not in owners
                            for _ in e.get("directed", []))
            for a in g["sentences"]:
                c = _is_cand(a)
                if c is None:
                    row["unk"] += 1
                    continue
                if "hit_rows" not in a:
                    row["legacy"] = True
                if not c:
                    continue
                v = _view(a, amap, owners)
                row["cand"] += 1
                if v["post"]:
                    row["got"] += 1
                elif a.get("post_unfull"):
                    row["pending"] += 1
                row["tail"] += v["tail_n"]
                row["morn"] = None if (row["morn"] is None or v["morn_n"] is None) else row["morn"] + v["morn_n"]
        if row["noscore"]:
            row["note"].append("不计分（家人场合：%s）" % row["noscore"])
        rows.append(row)
    lines = []
    for sid, v in sorted((head.get("nongroup_outbound") or {}).items()):
        kind = "家里线" if "agent:home" in sid else "非群线"
        lines.append({"label": "线 %s【不计分·%s】" % (sid, kind), "n": v["n"]})
    return rows, lines


def group_rows_md(res, owners=()):
    rows, lines = group_rows(res, owners)
    head = res["head"]
    L = ["## 分表（按群一行）", "",
         "- 每天每个我所在的群固定一行；歇着的群、零行的群也出行（零就零）；不计分的（owner 本人那一拍、家人场合）照样出行并标「不计分」，不进合计。",
         "- 「其中主动发起」＝机械候选：只核前 10 分钟没有指向我的行（@我的号、昵称@）；续接他人 30 分钟内话头那一条归手判，终数以手判为准。",
         "- 被接＝后 10 分钟内有机械接话行（@我的号、「给 〔行号〕」回应行）；当日尾接＝10 分钟之后到当天 24:00 的机械接话行数；晨前迟到接＝次日 00:00 到跑起时刻的机械接话行数；读不到写「未读」，不填 0。",
         ("- 按 --owner-author 剔 owner 行：" + "、".join(sorted(owners))) if owners else
         "- owner 身份未核实：没传 --owner-author，owner 的行没剔。"]
    if any(r["legacy"] for r in rows):
        L.append("- 旧底稿缺逐行接话记录：被接按 6 小时内前 12 条接话行算，当日尾接取底稿迟到接话行数（带 * 的含 owner 行、未逐行核），晨前迟到接一律未读。")
    if head.get("end_local") != head.get("next_midnight_local"):
        L.append("- 窗口终点早于次日零点（%s）：当日尾接只数到终点，未到 24:00。" % head.get("end_local"))
    L += ["", "| 群 | 我发句数 | 被@数 | 其中主动发起（机械候选·待手判） | 发起后 10 分钟内被接（接／共） | 当日尾接 | 晨前迟到接 | 备注 |",
          "|---|---|---|---|---|---|---|---|"]
    tot = {"sent": 0, "at": 0, "cand": 0, "got": 0, "tail": 0, "n": 0, "at_unread": 0}
    for r in rows:
        score = not r["noscore"]
        label = "群 %s（群号 %s；名未核实）%s" % (r["place"], r["gid"], "【不计分】" if not score else "")
        morn = "未读" if (r["morn"] is None or r["legacy"]) and r["cand"] else str(r["morn"] if r["cand"] else 0)
        star = "*" if r["legacy"] else ""
        note = list(r["note"])
        if r["pending"]:
            note.append("后窗未满 %d 句" % r["pending"])
        if r["unk"]:
            note.append("时刻未知 %d 句未入候选" % r["unk"])
        tail_c = ("%d%s" % (r["tail"], star)) if r["cand"] else "—（无发起句）"
        morn = morn if r["cand"] else "—（无发起句）"
        L.append("| %s | %d | %s | %d | %d／%d | %s | %s | %s |" % (
            label, r["sent"], "未读" if r["at"] is None else r["at"], r["cand"], r["got"], r["cand"],
            tail_c, morn, "；".join(note) or "—"))
        if score:
            tot["n"] += 1
            tot["sent"] += r["sent"]
            tot["cand"] += r["cand"]
            tot["got"] += r["got"]
            tot["tail"] += r["tail"]
            if r["at"] is None:
                tot["at_unread"] += 1
            else:
                tot["at"] += r["at"]
    for x in lines:
        L.append("| %s | %d 行出站 | — | — | — | — | — | 不计分（非群线，不进群清单） |" % (x["label"], x["n"]))
    L.append("| 合计（计分群，共 %d 个） | %d | %d%s | %d | %d／%d | %d | — | 不含不计分行 |" % (
        tot["n"], tot["sent"], tot["at"], ("（另 %d 群未读）" % tot["at_unread"]) if tot["at_unread"] else "",
        tot["cand"], tot["got"], tot["cand"], tot["tail"]))
    return L + [""]


def effect_md(res, owners=()):
    """主动发起效果追踪：每条机械候选一行——对话有没有起来、谁接的（author 标签）、有没有延续一轮。
    只列行号和机械线索，不写原因、不写结论句；没接的只给素材（后窗行数、此后全场行数与末行），话题结束的凭据①②归手判。"""
    owners = set(owners)
    by_place = {g["place"]: g for g in res["groups"].values()}
    L = ["## 主动发起效果追踪（逐条）", "",
         "- 每条＝一条机械发起候选（判据②归手判，手判后以手判为准）；「谁接」＝接话行←author，owner 的行不计分、不列。",
         "- 延续一轮＝首个接话行之后 30 分钟内还有第二个接话行才写「有」（行号、距首接秒数）；超过 30 分钟写「跨时段（+Ns）」、秒数留着，那是下一个话题、不叫当场延续；这一格是机械线索，对话有没有真的起来归手判。",
         "- 没接的那一条只给素材，不写原因：话题结束要凭据①②的行号，没有就不写；没人回不直接归因话题结束。", "",
         "| 群 | 行号 | 时刻 | 后 10 分钟别人 | 谁接（接话行←author） | 延续一轮 | 当日尾接 | 晨前迟到接 | 没接时的素材 | 她的话 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    n_rows, skipped = 0, []
    for code, g in sorted(by_place.items()):
        if code in FAMILY_PLACES:
            skipped.append("%s（%s）" % (code, FAMILY_PLACES[code]))
            continue
        amap = _author_map(g)
        for a in g["sentences"]:
            if _is_cand(a) is not True:
                continue
            v = _view(a, amap, owners)
            n_rows += 1
            hits = v["hits"]
            post = v["post"]
            ph = a.get("post_n", 0)
            af = a.get("after_first")
            who = "、".join("%d←%s" % (h[0], h[1]) for h in post[:6]) + ("（共 %d 行）" % len(post) if len(post) > 6 else "")
            if not post:
                who = "无机械接话行" + ("（窗未满）" if a.get("post_unfull") else "")
            if len(hits) >= 2:
                d2 = hits[1][2] - hits[0][2]
                if d2 <= CONT_LIMIT_SEC:
                    cont = "有：第 2 行 %d←%s（距首接 %ds；共 %d 行）" % (hits[1][0], hits[1][1], d2, len(hits))
                else:
                    cont = "跨时段（+%ds）：第 2 行 %d←%s（共 %d 行）" % (d2, hits[1][0], hits[1][1], len(hits))
            elif len(hits) == 1:
                cont = "无（仅 1 行）"
            else:
                cont = "—"
            tail_rows = [h[0] for h in hits if h[3] == "tail"][:3]
            tail = "%d%s" % (v["tail_n"], "" if v["full"] else "*") + (("（行 %s）" % "、".join(str(x) for x in tail_rows)) if tail_rows else "")
            morn = "未读" if v["morn_n"] is None else str(v["morn_n"])
            mat = "—"
            if not post:
                al = a.get("after_last")
                mat = "后窗别人 %d 行／%d 人；此后全场 %d 行%s" % (
                    ph, a.get("post_people", 0), a.get("after_n", 0),
                    ("，末行 %d（%s）" % (al["seq"], al["t"])) if al else "")
            L.append("| 群 %s | %d–%d | %s | %d 行／%d 人%s%s | %s | %s | %s | %s | %s | %s |" % (
                code, a["lo"], a["hi"], a["t0"], ph, a.get("post_people", 0),
                ("·首行 %d（+%ds）" % (af["seq"], af["gap_sec"])) if af else "",
                "·窗未满" if a.get("post_unfull") else "", who, cont, tail, morn, mat,
                a["text80"][:30].replace("|", "｜")))
    if not n_rows:
        L.append("| 没样本 | — | — | — | — | — | — | — | — | — |")
    L.append("")
    if skipped:
        L.append("- 不计分群不进追踪：%s。" % "、".join(skipped))
        L.append("")
    return L


def check_group_rows(text, res, exclude_places=()):
    """闸的一条机械锚点：底稿里的每个群在报告分表里都有一行；不计分的群要写「不计分」。语义判断不进闸。"""
    seen = {}
    for line in text.split("\n"):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"^群\s+(g[0-9a-f]{6})\b", cells[0]) if cells else None
        if m and m.group(1) not in seen:
            seen[m.group(1)] = line
    want = {g["place"] for g in res["groups"].values()}
    want |= {place_code(s) for s in res["head"].get("zero_outbound_groups", [])}
    out = []
    skip = set(FAMILY_PLACES) | set(exclude_places)
    for p in sorted(want):
        if p not in seen:
            out.append("分表缺群行：%s 在底稿群清单里，报告「分表（按群一行）」没有这一行（歇着的、零行的、不计分的也要出行）" % p)
        elif p in skip and "不计分" not in seen[p]:
            out.append("分表 %s 是不计分的群，行里没标「不计分」" % p)
    return out


def seq_range(cell):
    m = re.match(r"^(\d{1,7})(?:[–\-~](\d{1,7}))?$", cell.strip())
    return int(m.group(1)) if m else None


def check_report(path, js, exclude_places=()):
    res = json.load(open(js, encoding="utf-8"))
    byplace = {g["place"]: g for g in res["groups"].values()}
    text = open(path, encoding="utf-8").read()
    bad, seen, place = [], set(), None
    h = res["head"]
    m = re.search(r"窗口[^\n]*?→\s*(?:\d{4}-\d\d-\d\d\s+)?(\d\d:\d\d)", text)
    want = h["end_local"][11:16]
    if m and m.group(1) != want:
        bad.append("窗口终点：报告写 %s，底稿是 %s（%s）" % (m.group(1), want, h["end_source"]))
    for line in text.split("\n"):
        hm = re.match(r"^#+ .*?\b(g[0-9a-f]{6})\b", line)
        if hm:
            place = hm.group(1)
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.match(r"^g[0-9a-f]{6}", cells[0]):
            place, cells = cells[0][:7], cells[1:]
        if len(cells) < 4 or place not in byplace or seq_range(cells[0]) is None:
            continue
        lo = seq_range(cells[0])
        A = next((a for a in byplace[place]["sentences"] if a["lo"] == lo), None)
        tag = "%s %s" % (place, cells[0])
        if A is None:
            bad.append("%s：报告有这一句，底稿没有这个首段行号" % tag)
            continue
        seen.add((place, lo))
        if re.match(r"^\d\d:\d\d:\d\d", cells[1]) and cells[1][:8] not in (A["t0"], A.get("t0_receipt"), A.get("t0_queued")):
            bad.append("%s：时刻 报告 %s／底稿 %s（回执 %s、入队 %s）" % (tag, cells[1][:8], A["t0"], A.get("t0_receipt"), A.get("t0_queued")))
        fi = next((i for i, c in enumerate(cells) if i >= 3 and re.match(r"^\d+ 行", c)), None)
        if fi is not None and "pre_n" in A:
            n = int(re.match(r"^(\d+) 行", cells[fi]).group(1))
            pm = re.search(r"[／/]\s*(\d+) 人", cells[fi])
            if n != A["pre_n"]:
                bad.append("%s：前窗行数 报告 %d／底稿 %d" % (tag, n, A["pre_n"]))
            elif pm and int(pm.group(1)) != A["pre_people"]:
                bad.append("%s：前窗人数 报告 %s／底稿 %d" % (tag, pm.group(1), A["pre_people"]))
            if fi + 1 < len(cells) and "post_hit_first" in A:
                back = cells[fi + 1]
                mm = re.match(r"^接[：:]\s*(\d+)", back)
                if mm and int(mm.group(1)) != A["post_hit_first"]:
                    bad.append("%s：后窗首个接话行 报告 %s／底稿 %s" % (tag, mm.group(1), A["post_hit_first"]))
                elif not mm and re.match(r"^机械\s*0", back) and A["post_hit_first"] is not None:
                    bad.append("%s：报告写机械 0，底稿后窗有接话行 %s" % (tag, [x[0] for x in A["post_hits"]]))
                if "后窗未满" in back and not A["post_unfull"]:
                    bad.append("%s：报告写后窗未满，底稿是满的" % tag)
        if A["not_delivered"] and not re.search(r"UNKNOWN|CANCELLED|未送达|delivery_state|投递", line):
            bad.append("%s：底稿有非 DELIVERED 行 %s，报告这一行没写状态" % (tag, A["not_delivered"]))
    for place, g in byplace.items():
        if place in exclude_places:
            continue  # 整群剔出自省范围（小满家群）：底稿里仍有、报告不列，不算漏句。只影响对账，不改底稿任何计数。
        for a in g["sentences"]:
            if (place, a["lo"]) not in seen:
                bad.append("%s %d–%d：底稿有这一句，报告逐句表里没有（%s）" % (place, a["lo"], a["hi"], a["t0"]))
    bad += check_group_rows(text, res, exclude_places)
    for b in bad:
        print("DIFF", b)
    print("对账：%d 条对不上" % len(bad) if bad else "对账：报告与底稿一致（只对了机械锚点；语义判断不在这里）")
    return 1 if bad else 0


def selftest():
    ok = []
    ok.append(hit_kind("@900000001 hi", "900000001", {1}) == ["@qq"])
    ok.append(hit_kind("给 〔9838〕 你 点了「爱心」", "900000001", {9837, 9838}) == ["react"])
    ok.append(hit_kind("给 〔9999〕", "900000001", {9838}) == [])
    ok.append(is_placeholder("[表情包]") and is_placeholder("") and not is_placeholder("好"))
    rows = [{"scene_seq": 1, "episode_id": "a", "segment_index": 0}, {"scene_seq": 2, "episode_id": "a", "segment_index": 1},
            {"scene_seq": 3, "episode_id": "b", "segment_index": 0}, {"scene_seq": 4, "episode_id": "a", "segment_index": 0}]
    ok.append([len(s["rows"]) for s in build_sentences(rows)] == [2, 1, 1])
    ok.append(place_code("qq:900000001:group:900000002") == "g24969f")
    ok.append(sem_label("@900000001 ", "今天天气真好") == "空正文")
    ok.append(sem_label("天气真的不错", "今天天气真好") == "字面有重叠")
    ok.append(sem_label("美女们早安呀～", "今天天气真好") == "无字面重叠")
    ok.append(sem_label("给 〔123〕 你 点了「爱心」", "今天天气真好") in ("空正文", "无字面重叠"))
    ok.append(seq_range("9552–9553") == 9552 and seq_range("x") is None)
    ok.append(dispatch_suspect("麻烦你帮我查一下") and not dispatch_suspect("哈哈哈这个好笑"))
    _t = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)
    _o = [{"scene_seq": 5, "author": "qq:a", "text": "@900000001 帮我查一下", "_t": _t},
          {"scene_seq": 6, "author": "qq:b", "text": "笑死", "_t": _t}]
    _bp = by_person(_o, [{"lo": 3, "h6h": {"hits": [(6, 40)]}}], "900000001", _t - dt.timedelta(hours=1),
                    _t + dt.timedelta(hours=1), dt.timezone.utc)
    ok.append(_bp["qq:a"]["directed"][0]["suspect_dispatch"] and _bp["qq:b"]["connected"] == [{"seq": 6, "after_sentence": 3}]
              and not _bp["qq:b"]["directed"])
    _sid, _zero = "qq:900000001:group:900000002", "qq:900000001:group:900000009"
    _a = {"lo": 5, "hi": 5, "t0": "10:00:00", "text80": "占位", "pre_n": 0, "pre10_directed": [], "pre10_directed_soft": [],
          "post_n": 2, "post_people": 2, "post_unfull": False, "after_n": 2, "after_first": {"seq": 6, "gap_sec": 3},
          "after_last": {"seq": 7, "t": "10:01:00"}, "late_hit_n": 0, "morn_read": False,
          "hit_rows": [[6, "qq:b", 30, "post"], [7, "qq:o", 40, "post"], [9, "qq:b", 900, "tail"]]}
    _res = {"head": {"zero_outbound_groups": [_zero], "nongroup_outbound": {"agent:home:dm:x": {"n": 3}},
                     "end_local": "m", "next_midnight_local": "m", "zero_group_at": {_zero: {"qq:o": 2, "qq:c": 1}}},
            "groups": {_sid: {"place": place_code(_sid), "n_sentences": 1, "sentences": [_a],
                              "by_person": {"qq:c": {"directed": [{"seq": 4}], "connected": []},
                                            "qq:o": {"directed": [{"seq": 3}], "connected": []}}}}}
    _rows, _lines = group_rows(_res, {"qq:o"})
    _by = {r["place"]: r for r in _rows}
    _z = _by[place_code(_zero)]
    _g = _by[place_code(_sid)]
    ok.append(len(_rows) == 2 and _z["sent"] == 0 and _z["at"] == 1 and _g["at"] == 1 and _g["cand"] == 1
              and _g["got"] == 1 and _g["tail"] == 1 and _g["morn"] is None and len(_lines) == 1)
    _txt = "\n".join(group_rows_md(_res, {"qq:o"}) + effect_md(_res, {"qq:o"}))
    ok.append(check_group_rows(_txt, _res) == [] and "没样本" not in _txt and "6←qq:b" in _txt and "7←qq:o" not in _txt)
    ok.append(len(check_group_rows(_txt.replace("群 " + place_code(_zero), "x"), _res)) == 1)
    _res["head"]["zero_group_at"] = None
    ok.append([r["at"] for r in group_rows(_res)[0] if r["place"] == place_code(_zero)] == [None])
    print("selftest %d/%d" % (sum(ok), len(ok)))
    return 0 if all(ok) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("--end")
    ap.add_argument("--out", default=".")
    ap.add_argument("--check-report")
    ap.add_argument("--json")
    ap.add_argument("--exclude-place", action="append", default=[],
                    help="对账时跳过这个群的漏句检查（可重复；小满家群整群剔出自省范围用）")
    ap.add_argument("--owner-author", action="append", default=[],
                    help="owner 的 author 标签（可重复）：分表与效果追踪里剔掉他的行；不传就是身份未核实、没剔")
    ap.add_argument("--tables", help="拿一份已有的 anchors_<day>.json 只重出分表与效果追踪两段（不连库）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.check_report:
        js = args.json
        if not js:
            sys.exit("--check-report 要 --json anchors_<day>.json（先跑一遍生成）")
        return check_report(args.check_report, js, tuple(args.exclude_place))
    if args.tables:
        _r = json.load(open(args.tables, encoding="utf-8"))
        print("\n".join(group_rows_md(_r, tuple(args.owner_author)) + effect_md(_r, tuple(args.owner_author))))
        return 0
    from asuna import dbread as db
    if not args.day:
        args.day = db.now()[:10]
    if not args.owner_author:
        print("警告：没传 --owner-author，owner 的接话会被算成别人的接话（进被接数、分表、效果追踪）；晨版必须带上，号现取、不写进技能。")
    res = gen(db, args)
    os.makedirs(args.out, exist_ok=True)
    jp = os.path.join(args.out, "anchors_%s.json" % args.day)
    mp = os.path.join(args.out, "anchors_%s.md" % args.day)
    with open(jp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        f.write(md_of(res, tuple(args.owner_author)))
    h = res["head"]
    print("窗口 %s → %s（%s）UTC %s → %s" % (h["start_local"], h["end_local"], h["end_source"], h["utc"][0], h["utc"][1]))
    print("群 %d（scenes %d 行），有出站 %d，0 出站 %d；终点后尾段出站 %s" % (
        h["groups_kept"], h["scenes_group_rows"], h["groups_with_outbound"], len(h["zero_outbound_groups"]),
        {k.split(":")[-1]: v["n"] for k, v in h["tail_after_end_outbound_rows"].items()} or "无"))
    for sid, g in res["groups"].items():
        print("  %s %s 出站 %d 行 seq %d–%d %d 句 状态 %s" % (g["place"], sid.split(":")[-1], g["outbound"]["n"],
              g["outbound"]["lo"], g["outbound"]["hi"], g["n_sentences"], g["outbound"]["states"]))
    print("写出 %s、%s（sha256 %s）" % (jp, mp, hashlib.sha256(open(jp, "rb").read()).hexdigest()[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
