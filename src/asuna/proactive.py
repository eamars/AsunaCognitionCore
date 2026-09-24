"""ADR-005 P5：没被@的时候要不要醒一次——分寸从这个场景已经落库的真实行里算。

程序只回答一件事：**现在能不能问她想不想说**。这句话值不值得说，是角色在 DECIDE 里自己定的，
沉默不需要理由，也不因为"预算还有"就被暗示该开口。所以这里全是闸门，没有内容打分：

  · 只在**有新入站消息**时评估——没有任何定时器会去重开旧话题（DELIVERY_PLAN §P5）；
  · 快速连发时不插话：密度用 P2 那套中位数＋MAD 的场景节奏线判，不另写一份间隔统计；
  · 深夜／凌晨不评估：默认本地 23:00–08:00 安静时段，配置可改；带紧急线索词的例外**只放宽这一道闸**；
  · 同一话题在她被接话之前只试一次；说过之后没人接就退回旁听，不催问；
  · 场景级最小间隔与每小时上限都从"我自己已送达的主动出站行"倒推，不另存一份计数器；
  · 前台行动在跑、或本场景队列里已经排着别的输入 → 这次机会直接作废，不排队等。

每个中间量随决定一起写进那一行入站记录（`processing_outcome`／`proactive`）并进证据：
审计里能看见是哪几行把她拦下来／放出去，拦她的每一条都有名字。时间口径沿用 P1-b／P2 那三支
（入站 occurred_at、出站行内 receipt_at、再退 sink_receipts.received_at），读不到时间就照实说读不到。
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

try:                                  # 宿主按包加载
    from . import summary_trigger
    from .history_query import (DELIVERED, DELIVERY_FIELD, OUTBOUND, _outbound_time, _receipt_ref,
                               _sink_times)
    from .discussion_digest import _first_cue
except Exception:                     # 同目录平铺加载（离线自检）也认
    import summary_trigger
    from history_query import (DELIVERED, DELIVERY_FIELD, OUTBOUND, _outbound_time, _receipt_ref,
                               _sink_times)
    from discussion_digest import _first_cue

WAKE_REASON = 'proactive_unprompted'
OUTCOME_WAKE = 'PROACTIVE_WAKE'
OUTCOME_HOLD = 'PROACTIVE_HOLD'

# 形状参数与安全上下界：决定"怎么算"和"别算飞了"，不决定第几条触发。
OBSERVE_ROWS = 120            # 每次评估最多回看多少行（有界扫描）
DENSE_TAIL_GAPS = 6           # 看最近这么几个到达间隔判断"是不是还在快速连发"
DENSE_GAP_RATIO = 0.5         # 最近间隔中位数 < 本场景停顿线×这个比例 → 算还在抢着说
DENSE_MAX_GAP = 30.0          # 并且中位数还得真够快（秒）：节奏忽长忽短不算“快速一问一答”
DENSE_MIN_GAPS = 3            # 到达间隔不够这几个，本场景的节奏还不认识，不拿先验线拦人
PROBE_INTERVAL_SECONDS = 180.0     # 两次"问她要不要说"之间的最小间隔（机会预算）
MIN_INTERVAL_SECONDS = 120.0       # DECISIONS §7：同场景两次确认发布的插话至少间隔 120 秒
MERGE_WINDOW_SECONDS = 10.0        # DECISIONS §7：10 秒内的片段算一波，等她发完再考虑插话
MAX_PER_HOUR = 2                   # 每小时主动开口上限
QUIET_DEFAULT = (('23:00', '08:00'),)   # 默认安静时段（本地钟点）；配置可覆盖或清空
URGENT_CUES = ('紧急', '急事', '故障', '崩了', '挂了', '报错', '出问题了', '救命')
MAX_WINDOWS = 4
MAX_CUES = 12
REPORT_FIELDS = ('fire', 'signals', 'holds', 'quiet_now', 'quiet_windows', 'local_minutes',
                 'urgent_cue', 'dense', 'dense_median', 'dense_max_gap', 'quiet_after',
                 'quiet_source', 'samples', 'burst_rows', 'merge_window_seconds',
                 'since_wake', 'since_utterance', 'utterances_last_hour', 'topic_id',
                 'topic_attempts', 'topic_responded', 'probe_interval_seconds',
                 'min_interval_seconds', 'max_per_hour', 'note')


# ── 配置：一个场景开不开、怎么开 ────────────────────────────────
def now_ts():
    """评估用的单一时刻：调用方可注入固定钟点，检查里不谎称真等过冷却。"""
    return datetime.now(timezone.utc).timestamp()


def _clock(text, fallback):
    parts = str(text or '').strip().split(':')
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return fallback
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return fallback
    return hour * 60 + minute


def route_settings(config, scene):
    """这个群场景开没开主动模式。没配 = 一切照旧（旁听就是旁听），不猜默认开启。"""
    limits = {'enabled': False, 'quiet_windows': [tuple(QUIET_DEFAULT[0])], 'utc_offset_minutes': None,
              'probe_interval_seconds': PROBE_INTERVAL_SECONDS,
              'min_interval_seconds': MIN_INTERVAL_SECONDS, 'max_per_hour': MAX_PER_HOUR,
              'dense_max_gap': DENSE_MAX_GAP, 'merge_window_seconds': MERGE_WINDOW_SECONDS,
              'urgent_cues': list(URGENT_CUES), 'why': 'scene_not_group'}
    if not isinstance(scene, dict) or scene.get('kind') != 'group':
        return limits
    limits['why'] = 'not_enrolled'
    channel = (config or {}).get('channels', {}).get(scene.get('channel_id') or '')
    route = None
    for candidate in (channel or {}).get('routes', {}).values():
        if candidate.get('scene_id') == scene.get('_id'):
            route = candidate
            break
    if route is None:
        return limits
    block = route.get('proactive')
    if not isinstance(block, dict) or block.get('enabled') is not True:
        return limits
    windows = []
    raw = block.get('quiet_hours', [list(pair) for pair in QUIET_DEFAULT])
    if isinstance(raw, list):
        for pair in raw[:MAX_WINDOWS]:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            start, end = _clock(pair[0], None), _clock(pair[1], None)
            if start is not None and end is not None and start != end:
                windows.append((start, end))
    offset = block.get('utc_offset_minutes')
    if type(offset) is not int or not -840 <= offset <= 840:
        offset = None
    cues = block.get('urgent_cues')
    if not isinstance(cues, list) or not all(isinstance(item, str) and 1 <= len(item) <= 12 for item in cues):
        cues = list(URGENT_CUES)
    for field, key, floor, cap in (('probe_interval_seconds', 'probe_interval_seconds', 30, 86400),
                                   ('min_interval_seconds', 'min_interval_seconds', 60, 86400),
                                   ('max_per_hour', 'max_per_hour', 1, 12),
                                   ('dense_max_gap', 'dense_max_gap_seconds', 5, 600),
                                   ('merge_window_seconds', 'merge_window_seconds', 0, 120)):
        value = block.get(key)
        if type(value) is int and floor <= value <= cap:
            limits[field] = value
    limits.update(enabled=True, quiet_windows=windows, utc_offset_minutes=offset,
                  urgent_cues=list(cues[:MAX_CUES]), why='enrolled')
    return limits


def local_minutes(now_ts, offset_minutes=None):
    """评估时刻换成本地钟点（分钟）。没给偏移就按宿主本地时区，不硬绑某个城市。"""
    if offset_minutes is None:
        offset = datetime.now().astimezone().utcoffset() or timedelta(0)
        zone = timezone(offset)
    else:
        zone = timezone(timedelta(minutes=offset_minutes))
    moment = datetime.fromtimestamp(now_ts, zone)
    return moment.hour * 60 + moment.minute


def in_quiet(minutes, windows):
    for start, end in windows:
        if start < end and start <= minutes < end:
            return True
        if start > end and (minutes >= start or minutes < end):   # 跨过午夜
            return True
    return False


# ── 观察：只读已经落库的行，不猜、不写、不调模型 ──────────────────
def observe(store, scene, *, now_ts, trigger=None, limits=None):
    """把"我最近主动说过几次、哪条被接了、现在几点、群里说得多快"从真实行里读出来。"""
    limits = limits or {}
    rhythm = summary_trigger.observe(store, scene, now_ts=now_ts, rows_limit=OBSERVE_ROWS)
    quiet = rhythm.get('quiet_after') or summary_trigger.SEED_QUIET_SECONDS
    quiet_source = rhythm.get('quiet_source') or 'seed'
    rows = list(store.db.messages.find(
        {'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
         '$or': [{'direction': 'inbound'}, {'direction': OUTBOUND, DELIVERY_FIELD: DELIVERED}]},
        {'scene_seq': 1, 'direction': 1, 'author': 1, 'text': 1, 'occurred_at': 1, 'received_at': 1,
         'receipt_at': 1, 'receipt': 1, 'episode_id': 1, 'platform_message_id': 1,
         'proactive': 1, 'event.group_context': 1}).sort('scene_seq', -1).limit(OBSERVE_ROWS))
    rows.sort(key=lambda row: row.get('scene_seq') or 0)
    merge = limits.get('merge_window_seconds', MERGE_WINDOW_SECONDS)
    burst = 0
    for row in rows:                                   # 这波片段发完没：不排队等，也不逐条回
        if row.get('direction') != 'inbound':
            continue
        stamp = summary_trigger._epoch(row.get('occurred_at') or row.get('received_at'))
        if stamp is not None and 0 <= now_ts - stamp <= merge:
            burst += 1
    refs = {ref for row in rows if row.get('direction') == OUTBOUND
            for ref in [_receipt_ref(row)] if ref}
    sink_times, sink_note = _sink_times(store, refs) if refs else ({}, '')
    origins = {}
    mine = [row for row in rows if row.get('direction') == OUTBOUND and row.get('author') == 'xiaoman'
            and row.get('episode_id')]
    if mine:
        keys = ['in-' + row['episode_id'] for row in mine]
        origins = {doc['_id']: doc for doc in store.db.messages.find(
            {'_id': {'$in': keys}}, {'_id': 1, 'event.group_context': 1})}
    utterances, wakes = [], []
    for row in rows:
        if row.get('direction') == OUTBOUND:
            origin = origins.get('in-' + str(row.get('episode_id')))
            origin_group = (origin or {}).get('event', {}).get('group_context', {})
            if origin_group.get('wake_reason') != WAKE_REASON:
                continue
            at = _outbound_time(row, sink_times)[0]
            stamp = summary_trigger._epoch(at)
            if stamp is None:
                continue
            utterances.append({'at': stamp, 'seq': row.get('scene_seq'), 'row_id': row['_id'],
                               'platform_id': row.get('platform_message_id'),
                               'topic_id': origin_group.get('topic_id')})
        elif (row.get('proactive') or {}).get('wake') is True:
            stamp = summary_trigger._epoch(row.get('occurred_at') or row.get('received_at'))
            if stamp is not None:
                wakes.append({'at': stamp, 'seq': row.get('scene_seq'), 'row_id': row['_id']})
    trigger_group = (trigger or {}).get('event', {}).get('group_context') or {}
    trigger_id = (trigger or {}).get('_id')
    wakes = [wake for wake in wakes if wake['row_id'] != trigger_id]
    since_wake = min((now_ts - wake['at'] for wake in wakes), default=None)
    since_utterance = min((now_ts - item['at'] for item in utterances), default=None)
    last_hour = [item for item in utterances if now_ts - item['at'] <= 3600]
    topic_id = trigger_group.get('topic_id')
    same_topic = [item for item in utterances if topic_id and item['topic_id'] == topic_id]
    newest = max(same_topic, key=lambda item: item['at'], default=None)
    responded = False
    if newest:
        responded = any(row.get('direction') == 'inbound'
                        and ((row.get('event') or {}).get('group_context') or {}).get('reply_message_id')
                        in {newest['row_id'], newest['platform_id']}
                        and (row.get('scene_seq') or 0) > (newest['seq'] or 0)
                        for row in rows)
    tail = (rhythm.get('peer_gaps') or [])[-DENSE_TAIL_GAPS:]
    median = statistics.median(tail) if tail else None
    dense_max = limits.get('dense_max_gap', DENSE_MAX_GAP)
    minutes = local_minutes(now_ts, limits.get('utc_offset_minutes'))
    body = (trigger or {}).get('text')
    cue = _first_cue(body if isinstance(body, str) else '', limits.get('urgent_cues') or list(URGENT_CUES))
    return {'scene_id': scene['_id'], 'scene_kind': scene.get('kind'),
            'trigger_id': trigger_id, 'topic_id': topic_id,
            'trigger_time': summary_trigger._epoch((trigger or {}).get('occurred_at')
                                                   or (trigger or {}).get('received_at')),
            'samples': rhythm.get('samples', 0), 'burst_rows': burst,
            'merge_window_seconds': merge, 'quiet_after': round(quiet, 1),
            'quiet_source': quiet_source, 'peer_gaps_tail': [round(gap, 1) for gap in tail],
            'dense_median': round(median, 1) if median is not None else None,
            'dense_max_gap': dense_max,
            'dense': bool(tail) and len(tail) >= DENSE_MIN_GAPS and median <= dense_max
                   and median < DENSE_GAP_RATIO * quiet,
            'local_minutes': minutes, 'quiet_now': in_quiet(minutes, limits.get('quiet_windows') or []),
            'urgent_cue': cue, 'last_wake_at': max((wake['at'] for wake in wakes), default=None),
            'since_wake': round(since_wake, 1) if since_wake is not None else None,
            'last_utterance_at': max((item['at'] for item in utterances), default=None),
            'since_utterance': round(since_utterance, 1) if since_utterance is not None else None,
            'utterances_last_hour': len(last_hour), 'topic_attempts': len(same_topic),
            'topic_responded': responded, 'my_proactive_rows': len(utterances),
            'observed_rows': len(rows), 'rows_without_time': rhythm.get('rows_without_time', 0),
            'sink_note': sink_note}


# ── 判断：闸门全过才醒，拦下她的每一条都有名字 ────────────────────
def decide(profile, limits, *, now_ts=None, can_run=True):
    holds, signals = [], []
    profile = profile or {}
    limits = limits or {}
    now_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    if not limits.get('enabled'):
        holds.append('not_enrolled')
    if profile.get('scene_kind') != 'group':
        holds.append('not_a_group_scene')
    if profile.get('trigger_time') is None:
        holds.append('trigger_without_time')
    if profile.get('quiet_now') and not profile.get('urgent_cue'):
        holds.append('quiet_hours')
    if profile.get('dense'):
        holds.append('dense_exchange')
    if profile.get('burst_rows', 0) >= 2:
        holds.append('candidate_merge_window')
    since_wake = profile.get('since_wake')
    probe = limits.get('probe_interval_seconds', PROBE_INTERVAL_SECONDS)
    if since_wake is not None and since_wake < probe:
        holds.append('probe_cooldown')
    since_said = profile.get('since_utterance')
    floor = limits.get('min_interval_seconds', MIN_INTERVAL_SECONDS)
    if since_said is not None and since_said < floor:
        holds.append('scene_cooldown')
    if profile.get('utterances_last_hour', 0) >= limits.get('max_per_hour', MAX_PER_HOUR):
        holds.append('hourly_cap')
    if profile.get('topic_attempts') and not profile.get('topic_responded'):
        holds.append('topic_attempt_unanswered')
    if not can_run:
        holds.append('foreground_busy')
    if not holds:
        signals.append('unprompted_group_message')
        if profile.get('topic_attempts'):
            signals.append('topic_was_replied')
        if profile.get('urgent_cue'):
            signals.append('urgent_cue')
    note = ''
    if profile.get('quiet_source') == 'seed':
        note = '本场景还没有实测节奏，密度按先验停顿线判'
    elif profile.get('rows_without_time'):
        note = '有 %d 行读不到时间，没算进间隔' % profile['rows_without_time']
    return {'fire': not holds, 'holds': holds, 'signals': signals,
            'quiet_windows': [list(pair) for pair in (limits.get('quiet_windows') or [])],
            'probe_interval_seconds': probe, 'min_interval_seconds': floor,
            'max_per_hour': limits.get('max_per_hour', MAX_PER_HOUR), 'note': note,
            **{field: profile.get(field) for field in REPORT_FIELDS
               if field not in ('fire', 'signals', 'holds', 'probe_interval_seconds',
                                'min_interval_seconds', 'max_per_hour', 'note')}}


def consider(store, evidence, config, scene, row, *, now_ts=None, can_run=True):
    """旁听行落库之后的一次评估：把决定写进那一行，返回（决定，可直接入队的事件）。

    不调模型、不发 QQ、不新增集合；写不下去（CAS 撞车）就当这次没评估，下一条消息还会再问。
    """
    limits = route_settings(config, scene)
    moment = now_ts() if now_ts is None else now_ts
    if not limits['enabled']:
        return {'fire': False, 'holds': [limits.get('why') or 'not_enrolled'], 'signals': [],
                'note': '这个场景没开主动模式，照旧只旁听'}, None
    profile = observe(store, scene, now_ts=moment, trigger=row, limits=limits)
    decision = decide(profile, limits, now_ts=moment, can_run=can_run)
    current = store.db.messages.find_one({'_id': row['_id']})
    if not current:
        return decision, None
    event = dict(current.get('event') or {})
    if decision['fire']:
        event['group_context'] = {**(event.get('group_context') or {}),
                                  'wake_reason': WAKE_REASON, 'topic_via': 'proactive'}
    record = {field: decision.get(field) for field in REPORT_FIELDS}
    record.update(decided_at=datetime.fromtimestamp(moment, timezone.utc).isoformat(),
                  wake=bool(decision['fire']))
    try:
        updated = store.put('messages', {**current, 'event': event,
                                         'processing_outcome': OUTCOME_WAKE if decision['fire']
                                         else OUTCOME_HOLD,
                                         'proactive': record},
                            expected=current['revision'], stream=current.get('episode_id') or 'proactive')
    except Exception:
        return {**decision, 'fire': False, 'holds': decision['holds'] + ['decision_write_conflict']}, None
    evidence.record('proactive.wake' if decision['fire'] else 'proactive.hold',
                    {'scene_id': scene['_id'], 'message_id': row['_id'], 'decision': record})
    return decision, (updated if decision['fire'] else None)
