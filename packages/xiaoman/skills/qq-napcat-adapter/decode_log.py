#!/usr/bin/env python3
"""把 qq-napcat-adapter 的日志行翻成人话摘要（离线，只读 stdin 或文件）。

用法: python3 decode_log.py adapter.log   或  粘贴日志后 Ctrl-D
只是解释器，不联网、不改状态；日志里没有的事实它不会编。
0.2 起认得群场景字段（scene/group/mentions/at_all/reply）、SEND_RESULT 的
 target=dm|group，以及 CONFIG/STATUS 里的 group_routes。
0.2.3 起认得 VERIFY 行：发送被平台接受后，adapter 会用 get_msg 把那条消息按
 自己拿回的 message_id 读回来对一次段序列。VERIFY 只是观测，不参与发送成败；
 result=verified 表示平台确实按我们提交的段序列存了这条、落在这个会话、是我们
 发的；segment_mismatch / target_mismatch / not_found / unavailable 都不改变
 platform_accepted，也不代表没发出去，更不代表对方看到了提醒。
0.3 起认得对方身份行（ADR-005 第一阶段）：
 PEERS 启动时的人数快照；PEER 每条已授权入站识别到的人（person/scene/display/
 nick/card/role/source/verified/msgs/changed）；PEER_CHANGED 改名或换名片，
 person_id 不变所以还是同一个人；PEER_FIELD_DENIED + PEER_REPOST 表示宿主还不
 收 raw 里那块身份，adapter 已把同一条事件去掉身份块重投（入站没丢）。
 source=api 是查过平台的，event_sender 是这条消息自带的，api_error:* 是没查到、
 只能标 verified=False——不要把未核实的当成确认过的事实。
0.4 起认得图片/表情等非文本段：INBOUND_SPOOLED 多 media=（几个非文本段）、
 media_types=（哪些类型）、media_only=（这条消息一个字都没有）；MEDIA_REPOST
 表示宿主还不收 raw 里那块媒体元数据，adapter 已去块重投（入站没丢，
 占位符正文也还在）。media_only=True 的那些行就是以前会被 no_text 吃掉的那类。
"""
import collections
import re
import sys

TAGS = (
    "WS_UP", "WS_CLOSED", "WS_ERROR", "WS_RETRY", "CONFIG", "IDENTITY", "READY",
    "STATUS", "INBOUND_SPOOLED", "INBOUND_ACCEPTED", "INBOUND_DUPLICATE", "INBOUND_IGNORED",
    "INBOUND_RETRY", "INBOUND_REJECTED", "INBOUND_FAILED", "OUTBOX_CLAIMED", "OUTBOX_ERROR",
    "SEND_RESULT", "VERIFY", "SELF_ECHO", "PEERS", "PEER", "PEER_CHANGED", "MEDIA_REPOST",
    "PEER_FIELD_DENIED", "PEER_REPOST", "PEER_ERROR", "RECEIPT_OK", "RECEIPT_SPOOLED", "RECEIPT_REPLAYED", "RECEIPT_REJECT",
    "RECEIPT_ABANDONED", "LATE_ACK", "SIGNAL", "SHUTDOWN", "FATAL",
)
KV = re.compile(r"(\w+)=(\S+)")
NOISY = ("FATAL", "WS_ERROR", "WS_RETRY", "INBOUND_FAILED", "INBOUND_REJECTED",
         "RECEIPT_REJECT", "RECEIPT_ABANDONED", "OUTBOX_ERROR", "MAIN_LOOP_ERROR",
         "SUBMITTER_ERROR", "RECEIPT_REPLAY_ERROR", "PEER_ERROR")


def main(paths):
    counts = collections.Counter()
    reasons = collections.Counter()
    sends = collections.Counter()
    verify = collections.Counter()
    verify_detail = []
    scenes = collections.Counter()
    groups = collections.Counter()
    mentions = 0
    at_all_seen = 0
    replies = 0
    last_status = None
    peers_snapshot = None
    peer_seen = 0
    peer_verified = collections.Counter()
    peer_people = set()
    peer_changes = []
    peer_repost = 0
    media_segments = 0
    media_only_lines = 0
    media_types = collections.Counter()
    media_repost = 0
    identity = None
    ready = None
    config = None
    warnings = []
    lines = 0
    text = ""
    for path in paths or ["-"]:
        with (sys.stdin if path == "-" else open(path, encoding="utf-8", errors="replace")) as fh:
            text += fh.read()
    for line in text.splitlines():
        lines += 1
        parts = line.split()
        tag = next((p for p in parts if p in TAGS), None)
        if tag is None:
            continue
        counts[tag] += 1
        kv = dict(KV.findall(line))
        if tag == "IDENTITY":
            identity = line[line.index("IDENTITY") + 9:].strip()
        elif tag == "CONFIG":
            config = kv
        elif tag == "READY":
            ready = kv
        elif tag == "STATUS":
            last_status = kv
        elif tag == "PEERS":
            peers_snapshot = line[line.index("PEERS") + 5:].strip()
        elif tag == "PEER":
            peer_seen += 1
            peer_people.add(kv.get("person", "?"))
            peer_verified[kv.get("verified", "?")] += 1
        elif tag == "PEER_CHANGED":
            peer_changes.append(line[line.index("PEER_CHANGED"):].strip()[:200])
        elif tag in ("PEER_FIELD_DENIED", "PEER_REPOST"):
            peer_repost += 1
        elif tag == "MEDIA_REPOST":
            media_repost += 1
        elif tag == "INBOUND_IGNORED":
            reasons[kv.get("reason", "?")] += 1
        elif tag == "INBOUND_SPOOLED":
            scene = kv.get("scene", "private")
            scenes[scene] += 1
            if kv.get("group") not in (None, "-"):
                groups[kv["group"]] += 1
            mentions += int(kv.get("mentions") or 0)
            at_all_seen += int(kv.get("at_all") or 0)
            replies += int(kv.get("reply") or 0)
            media_segments += int(kv.get("media") or 0)
            if kv.get("media_only") == "True":
                media_only_lines += 1
            for t in (kv.get("media_types") or "-").split(","):
                if t and t != "-":
                    media_types[t] += 1
        elif tag == "SEND_RESULT":
            sends["%s:%s" % (kv.get("target", "?"), kv.get("status", "?"))] += 1
            sends["out-segments %s=%s" % (kv.get("target", "?"), kv.get("segments", "none"))] += 1
        elif tag == "VERIFY":
            res = kv.get("result", "?")
            verify[res] += 1
            if res != "verified":
                verify_detail.append(line.strip()[:200])
        if tag in NOISY:
            warnings.append(line.strip()[:200])
    print("解析 %d 行" % lines)
    print("标签计数: %s" % (dict(sorted(counts.items())) or "无"))
    if config:
        print("配置: routes=%s allowed_groups=%s" % (config.get("routes"), config.get("allowed_groups")))
    if identity:
        print("身份: %s" % identity)
    if ready:
        print("READY: ws_event=%s ws_api=%s spool_inbound=%s spool_receipts=%s"
              % (ready.get("ws_event"), ready.get("ws_api"), ready.get("spool_inbound"),
                 ready.get("spool_receipts")))
    if last_status:
        print("最后 STATUS: ws_event=%s ws_api=%s spool_inbound=%s spool_receipts=%s group_routes=%s" %
              (last_status.get("ws_event"), last_status.get("ws_api"), last_status.get("spool_inbound"),
               last_status.get("spool_receipts"), last_status.get("group_routes", "-")))
    if scenes:
        print("已落盘入站场景: %s" % dict(scenes))
    if groups:
        print("出现过的群: %s" % dict(groups))
    if scenes:
        print("真实提及 %d 次 / @全体段 %d 次 / 带 reply %d 次（只有真实 segment 才计数）"
              % (mentions, at_all_seen, replies))
    if scenes:
        print("非文本段 %d 个（类型 %s），其中 %d 条消息全程没有文字（0.3 之前这类会被 no_text 丢掉）"
              % (media_segments, dict(media_types) or "无", media_only_lines))
    if media_repost:
        print("媒体块被宿主拒过并已去块重投的行: %d（入站未丢）" % media_repost)
    if reasons:
        print("入站丢弃原因: %s" % dict(reasons))
    if sends:
        print("发送结果: %s" % dict(sends))
    if verify:
        print("读回核实（仅观测，不影响发送状态）: %s" % dict(verify))
        for v in verify_detail[-6:]:
            print("  ~ %s" % v)
    if peers_snapshot:
        print("身份目录启动快照: %s" % peers_snapshot)
    if peer_seen:
        print("对方身份识别 %d 条，涉及 %d 个人；verified 计数 %s"
              % (peer_seen, len(peer_people), dict(peer_verified)))
    for c in peer_changes[-6:]:
        print("  ~ 改名/换名片（同一个人）: %s" % c)
    if peer_repost:
        print("身份块被宿主拒过并已去块重投的行: %d（入站未丢）" % peer_repost)
    print("需要看的行: %d" % len(warnings))
    for w in warnings[-10:]:
        print("  ! %s" % w)
    if not counts:
        print("（这份日志里没有 adapter 的标签行，无法判断接通与否）")


if __name__ == "__main__":
    main(sys.argv[1:])
