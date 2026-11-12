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


def sentence_anchor(S, others, qq, soft_ok, tz, start, end, internal_by_ep):
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
    ext = db.local_window((start - dt.timedelta(minutes=10)).strftime(fmt), end.strftime(fmt))
    head = {"day": args.day, "generated_at_local": now.strftime(fmt), "tz": str(tz),
            "start_local": start.strftime(fmt), "end_local": end.strftime(fmt), "end_source": src,
            "next_midnight_local": midnight.strftime(fmt), "utc": [win["$gte"], win["$lt"]],
            "right_open": True}
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
        sa = [sentence_anchor(S, others, qq, True, tz, start, end, internal_by_ep) for S in sents]
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


def md_of(res):
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
    return "\n".join(L) + "\n"


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
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.check_report:
        js = args.json
        if not js:
            sys.exit("--check-report 要 --json anchors_<day>.json（先跑一遍生成）")
        return check_report(args.check_report, js, tuple(args.exclude_place))
    from asuna import dbread as db
    if not args.day:
        args.day = db.now()[:10]
    res = gen(db, args)
    os.makedirs(args.out, exist_ok=True)
    jp = os.path.join(args.out, "anchors_%s.json" % args.day)
    mp = os.path.join(args.out, "anchors_%s.md" % args.day)
    with open(jp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        f.write(md_of(res))
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
