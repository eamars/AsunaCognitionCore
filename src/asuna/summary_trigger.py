"""ADR-005 P2：自动摘要什么时候该动手——触发点从场景自己真实出现过的节奏里算出来。

上一版写死「待处理 ≥4 条，或 ≥2 条且最早一条安静 ≥120 秒」。那两组数在快群里太慢（攒一整晚，
摘要盖的是三天前的事），在慢私聊里又太急（对方只是去上班了，不是话说完了）。所以这一片改成
先读这个场景**已经落库的行**，算出它自己的发言间隔分布与成簇大小，再判断四件事：

  1. 现在这段安静对**这个场景**算不算反常——话说完了没有（pause_anomalous）；
  2. 待整理的是不是已经攒够**本场景典型的一簇**，而且这一簇看着是说完了的（cluster_complete）；
  3. 是不是顶到了送进模型的窗口上限——批不可能比窗口更大，这是结构不是偏好（window_full）；
  4. 最老那条是不是已经等得比本场景的典型停顿还久，再等只会被后面的话冲掉（pending_stale）；
  外加一条收尾线索（closure_cue）：最后一条是落定／更正类表述时，这一批已经是一个完整状态。

外加一道闸：除了窗口顶满，其余信号都要求「这一阵话说完了」（安静过半条停顿线）——人还在连着发的时候整理，下一秒就得重做。
任一成立就动手，都不成立就照旧不动。每个中间量都随决定一起返回并进证据，审计里能看见是哪些
真实数据把触发点推到这里的。留下的常数只有形状参数（离散倍数、观察窗口条数）和安全上下界，
它们是护栏不是触发点。冷启动没有任何间隔可看时用一个先验值，一旦本场景或同部署别的场景观察到
真实间隔就立刻被实测值顶掉——先验是起点，不是策略。

时间口径跟 P1-b／P1-c 同一套（三支：messages.occurred_at／messages.receipt_at／
sink_receipts.received_at），直接复用 history_query 里那几个解析函数，不另抄一份会漂移的副本；
线索词同样复用 P1-c 那份，两处对「什么算落定／更正／又抛回去的问句」不各自定义。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

try:                                  # 宿主按包加载
    from .discussion_digest import (CONFIRM_CUES, CORRECTION_CUES, QUESTION_CUES, QUESTION_MARKS,
                                    _first_cue)
    from .history_query import (DELIVERED, DELIVERY_FIELD, OUTBOUND, _outbound_time, _receipt_ref,
                               _sink_times, _stamp)
except Exception:                     # 同目录平铺加载（离线自检）也认
    from discussion_digest import (CONFIRM_CUES, CORRECTION_CUES, QUESTION_CUES, QUESTION_MARKS,
                                   _first_cue)
    from history_query import (DELIVERED, DELIVERY_FIELD, OUTBOUND, _outbound_time, _receipt_ref,
                               _sink_times, _stamp)

# 形状参数与安全上下界：它们决定「怎么算」和「别算飞了」，不决定「第几条／第几秒触发」。
OBSERVE_ROWS = 120          # 每个场景最多回看多少行来归纳节奏（有界扫描，不是触发条件）
SPREAD_SIGMAS = 2.0         # 比本场景典型停顿再散两个 MAD 才算反常
QUIET_FLOOR_SECONDS = 20.0  # 下界：比索引线程轮转加一次模型调用还短的停顿不值得打断
QUIET_CAP_SECONDS = 6 * 3600.0   # 上界：再慢的场景也有一条兜底，不让原文无限期等着
SEED_QUIET_SECONDS = 120.0  # 冷启动先验：一个真实间隔都没见过时才用，见到就换掉
SEED_BURST_ROWS = 3         # 同上：没有实测成簇大小时，先验要求至少攒够三条
MIN_PENDING_FOR_SEED = 2    # 冷启动不为一句话碎片动手（窗口顶满除外）
SETTLE_RATIO = 0.5            # 安静过半条停顿线才算「这一阵话说完了」：内容类信号都要过这道闸
MAX_ITEMS = 12              # 返回体里列表的有界长度


def _epoch(value):
    """行上的时间戳读成 UTC epoch 秒；读不出来就返回 None，不拿 scene_seq 或写入时间冒充。"""
    text = _stamp(value)
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        moment = datetime.fromisoformat(text[:32])
    except ValueError:
        return None
    if moment.tzinfo is None:            # 宿主自己写的都带时区；裸时间按 UTC 认
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _gaps(times):
    return [later - earlier for earlier, later in zip(times, times[1:]) if later > earlier]


def _spread(values, multiplier=1.0, floor=0.0):
    """中位数 + 离散倍数×MAD：比均值抗那几条隔夜的超长间隔。"""
    if not values:
        return None
    median = statistics.median(values)
    mad = statistics.median([abs(value - median) for value in values])
    return max(median + multiplier * mad, floor)


def _bursts(timed, split_after):
    """按「比这条停顿线更久」切簇：返回每簇的条数与字符量（只看真实到达顺序，不看内容）。"""
    counts, byte_totals, current, current_bytes, previous = [], [], 0, 0, None
    for row in timed:
        if previous is not None and row['at'] - previous > split_after:
            counts.append(current)
            byte_totals.append(current_bytes)
            current, current_bytes = 0, 0
        current += 1
        current_bytes += row['chars']
        previous = row['at']
    if current:
        counts.append(current)
        byte_totals.append(current_bytes)
    return counts, byte_totals


def observe(store, scene, *, now_ts=None, rows_limit=OBSERVE_ROWS):
    """从这个场景已经存在的行里归纳它自己的节奏。只读；不写库、不调模型、不猜。"""
    rows = list(store.db.messages.find(
        {'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
         '$or': [{'direction': 'inbound'}, {'direction': OUTBOUND, DELIVERY_FIELD: DELIVERED}]},
        {'scene_seq': 1, 'direction': 1, 'author': 1, 'text': 1, 'occurred_at': 1,
         'received_at': 1, 'receipt_at': 1, 'receipt': 1}).sort('scene_seq', -1).limit(rows_limit))
    rows.sort(key=lambda row: row.get('scene_seq') or 0)
    refs = {ref for row in rows if row.get('direction') == OUTBOUND
            for ref in [_receipt_ref(row)] if ref}
    sink_times, sink_note = _sink_times(store, refs) if refs else ({}, '')
    timed, no_time = [], 0
    for row in rows:
        if row.get('direction') == OUTBOUND:
            at = _outbound_time(row, sink_times)[0]      # 行内 receipt_at 优先，缺了才关联送达回执
        else:
            at = row.get('occurred_at') or row.get('received_at')
        stamp = _epoch(at)
        if stamp is None:
            no_time += 1
            continue
        timed.append({'at': stamp, 'seq': row.get('scene_seq'), 'author': row.get('author'),
                      'direction': row.get('direction'), 'chars': len(row.get('text') or '')})
    peer_gaps = _gaps([row['at'] for row in timed if row['direction'] != OUTBOUND])
    all_gaps = _gaps([row['at'] for row in timed])
    gaps = peer_gaps or all_gaps
    quiet = _spread(gaps, SPREAD_SIGMAS, QUIET_FLOOR_SECONDS) if gaps else None
    if quiet:
        quiet = min(quiet, QUIET_CAP_SECONDS)
    burst_counts, burst_bytes = _bursts(timed, quiet or SEED_QUIET_SECONDS)
    stamps = [row['at'] for row in timed]
    return {'scene_id': scene['_id'], 'observed_rows': len(rows), 'samples': len(gaps),
            'peer_gaps': [round(gap, 1) for gap in peer_gaps[-MAX_ITEMS:]],
            'all_gaps': [round(gap, 1) for gap in all_gaps[-MAX_ITEMS:]],
            'quiet_after': round(quiet, 1) if quiet else None,
            'quiet_source': 'observed' if quiet else None,
            'burst_rows': int(round(statistics.median(burst_counts))) if burst_counts else None,
            'burst_bytes': int(statistics.median(burst_bytes)) if burst_bytes else None,
            'rows_without_time': no_time, 'sink_note': sink_note,
            'first_at': min(stamps, default=None), 'last_at': max(stamps, default=None),
            'times': {row['seq']: row['at'] for row in timed if row['seq'] is not None}}


def pooled(profiles, *, exclude=None):
    """同部署其他场景已经实测到的节奏，合起来当冷启动先验；一个都没实测到就返回 None。"""
    gaps, bursts = [], []
    for scene_id, profile in (profiles or {}).items():
        if scene_id == exclude or not profile:
            continue
        gaps.extend(profile.get('peer_gaps') or profile.get('all_gaps') or [])
        if profile.get('burst_rows'):
            bursts.append(profile['burst_rows'])
    if not gaps:
        return None
    quiet = _spread(gaps, SPREAD_SIGMAS, QUIET_FLOOR_SECONDS)
    return {'quiet_after': round(min(quiet, QUIET_CAP_SECONDS), 1) if quiet else None,
            'burst_rows': int(round(statistics.median(bursts))) if bursts else None,
            'samples': len(gaps), 'source': 'pooled_prior'}


def cluster_closed(rows):
    """这一批是不是一个说完了的话轮簇：至少两个人说过话，且最后一条没把话又抛回去。"""
    if len({row.get('author') for row in rows}) < 2:
        return False
    last = rows[-1].get('text') or ''
    if _first_cue(last, QUESTION_CUES) or any(mark in last for mark in QUESTION_MARKS):
        return False
    return True


def closure_cue(rows):
    """最后一条是不是落定或更正：这两种情况下这一批已经是一个值得留下的状态。"""
    if not rows:
        return False
    last = rows[-1].get('text') or ''
    return bool(_first_cue(last, CONFIRM_CUES) or _first_cue(last, CORRECTION_CUES))


def decide(profile, pending, *, pooled_prior=None, now_ts=None, window_rows, row_char_cap=4000):
    """该不该现在整理这一批。返回带全部中间量的决定，调用方原样进证据／条目。"""
    now_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    profile = profile or {}
    pooled_prior = pooled_prior or {}
    quiet = profile.get('quiet_after') or pooled_prior.get('quiet_after') or SEED_QUIET_SECONDS
    if profile.get('quiet_source'):
        quiet_source = profile['quiet_source']
    elif pooled_prior.get('quiet_after'):
        quiet_source = 'pooled_prior'
    else:
        quiet_source = 'seed'
    burst_rows = profile.get('burst_rows') or pooled_prior.get('burst_rows') or SEED_BURST_ROWS
    times = profile.get('times') or {}
    marks = [times[row['scene_seq']] for row in pending
             if row.get('scene_seq') is not None and row['scene_seq'] in times]
    missing = len(pending) - len(marks)
    if marks:
        silence = now_ts - max(marks)
        pending_age = now_ts - min(marks)
    else:
        silence = now_ts - profile['last_at'] if profile.get('last_at') else None
        pending_age = None
    if missing and profile.get('first_at') is not None:
        # 观察窗口外（更老）的待整理行至少从最早观察到的那一刻就在等：按下界算，不假装知道。
        pending_age = max(pending_age or 0.0, now_ts - profile['first_at'])
    # 「这一阵话说完了没有」：安静过半条停顿线。人还在连着发的时候，内容攒得再多也不整理，
    # 只有窗口顶满这条结构上限会打断——否则摘要下一秒就得重做，白花一次模型调用。
    settled = silence is not None and silence >= SETTLE_RATIO * quiet
    signals, hold = [], None
    if not pending:
        hold = 'nothing_pending'
    else:
        if silence is not None and silence >= quiet:
            signals.append('pause_anomalous')
        if len(pending) >= window_rows:
            signals.append('window_full')
        if settled and burst_rows and len(pending) >= burst_rows and cluster_closed(pending):
            signals.append('cluster_complete')
        if settled and pending_age is not None and pending_age >= quiet:
            signals.append('pending_stale')
        if settled and len(pending) >= 2 and closure_cue(pending):
            signals.append('closure_cue')
        if signals and quiet_source == 'seed' and len(pending) < MIN_PENDING_FOR_SEED \
                and 'window_full' not in signals:
            signals, hold = [], 'cold_start_needs_more_than_a_fragment'
        elif not signals:
            hold = 'scene_still_talking'
    return {'fire': bool(signals), 'signals': signals, 'hold': hold,
            'quiet_after': round(quiet, 1), 'quiet_source': quiet_source, 'burst_rows': burst_rows,
            'silence': round(silence, 1) if silence is not None else None,
            'pending_age': round(pending_age, 1) if pending_age is not None else None,
            'pending_rows': len(pending),
            'pending_bytes': sum(len(row.get('text') or '') for row in pending),
            'pending_times_missing': missing, 'settled': settled, 'window_rows': window_rows,
            'row_char_cap': row_char_cap, 'samples': profile.get('samples', 0),
            'rows_without_time': profile.get('rows_without_time', 0),
            'cluster_closed': cluster_closed(pending) if pending else False,
            'closure_cue': closure_cue(pending)}
