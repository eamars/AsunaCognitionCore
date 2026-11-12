#!/usr/bin/env python3
"""DSH 级（系统级）失败扫描：一条命令列出窗口内两类失败。

一类是**带报错行的失败**（关口被引擎拒、环节抛异常、上游非 2xx、进程非零退出、任务级异常），
一类是**静默没跑**（只有执行记录能证明它缺席：关口没判出来、请求发出去没回、宿主或 worker 停了、
该响的拍没响、任务没回执）。输出按失败类型分组：条数＋首末本地时刻＋各型最多三条样例行。

只读：查库（`asuna.dbread`）＋读数据根下的运行文件，不写库、不落文件，结果一律 stdout。

    python3 dsh_failure_scan.py                                  # 最近 24 小时（本地钟面）
    python3 dsh_failure_scan.py --hours 72                        # 最近 72 小时
    python3 dsh_failure_scan.py --since '2026-11-04 21:10:00' --until '2026-11-07 13:07:40'
    python3 dsh_failure_scan.py --no-files                        # 只查库那几面
    python3 dsh_failure_scan.py --selfcheck                       # 不连库不读盘的纯逻辑自检

窗口是本地钟点，换算不背偏移：脚本把 `dbread.now()`（她这边现在的钟点）与同一刻的 UTC 配成一对
现推偏移，并在表头打这行配对（含同一个 UTC 换 +8 是多少）。

退出码：0 = 扫完了（有没有失败都是 0，晨扫要的就是「跑成」）；2 = 判不了（一面都没读到、或窗口不对）。
全零：输出一行 `0`。有面没读到却也全零时，不印光一个 `0`——另起行列没读到的是哪几面，
因为那种 0 是「没查」，不是「没有」。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# 依赖缺席就在这里 ImportError：不在这一行上 try、不塞替身模块——「没装上」不许长得像「过了」。
from asuna import config as asuna_config
from asuna import dbread

SAMPLES = 3
SAMPLE_CHARS = 150
ID_CHARS = 12
GRACE_MINUTES = 10                 # 窗口右端往外宽限：刚发出去还没回的调用不算「没回」
TAIL_BYTES = 8 * 1024 * 1024       # 宿主控制台日志只读末尾这一段
HEAD_BYTES = 4096                  # 事件文件只读头一截：正文（别人的话）排在后面，不进内存
TAIL_READ_BYTES = 400                # 头里没 time_ns 时补读尾部一小截（大响应才有这一格）

# ── 组 A：带报错行的失败（audit_events 的 type）──
AUDIT_WITH_ERROR = {
    'attend.failed': '关口没判出来（payload.error 带引擎拒话）',
    'chat.error': '回合里抛异常',
    'execution.failed': '行动脑那一跑抛异常',
    'execution.rejected': '行动脑交回的报告被退',
    'phase.failed': '阶段执行抛异常',
    'phase.rejected': '阶段输出被退回',
    'turn.rejected': '整回合被退回（回合级、不带工具名）',
    'condense.failed': '群笔记追加失败',
    'condense.size_failed': '群笔记尺寸那一关失败',
    'condense.plan_failed': '群笔记计划失败',
    'embedding.failed': '向量调用失败',
    'rhythm.watch_failed': '节奏看门失败',
    'tier.fell': '高档那一跑落档（reason 分 refused／down／busy／owner）',
    'system.render_drift': '渲染与预期对不上',
}
# ── 组 B：只有执行记录能证明它缺席（audit_events 的 type）──
AUDIT_SILENT = {
    'rhythm.heartbeat_missed': '该响的那一拍没响',
    'schedule.stale_dispatch': '到点派发不上',
    'schedule.stale_skipped': '到点直接跳过',
    'task.time_up': '任务到钟没跑完',
    'task.time_up_outcome': '任务到钟后的处置',
}
# ── 组 D：计划没排上／晚交到（ADR-119 F10 的五个 type）──
# 名单出处＝跑着的 core：faults.py:114（schedule.fault_told）、faults.py:71（schedule.fault_unreported）、
# schedule.py:428（schedule.handoff_late）、schedule.py:433（schedule.handoff_failed）、
# schedule.py:396（schedule.handoff_watch_failed）。这五个 type 是 11-10 才装上的：更早的窗口数出 0
# 是「库里没有」，不是那件事没发生过。**扫描只数名册里的 type**，名册外的一行都不数（自检钉着）。
AUDIT_SCHEDULE = {
    'schedule.fault_told': '计划到点没排上、这一拍把这事告诉她了（payload.failed_at 才是故障时刻）',
    'schedule.fault_unreported': '计划没排上、连给开发者的说明都没写进去（payload.error 带原因）',
    'schedule.handoff_late': '到点超过 5 分钟才交到手上（payload.due＝DSH 的 acceptedAt，巡查线 300 秒）',
    'schedule.handoff_failed': '晚交那一拍自己抛异常（payload.error）',
    'schedule.handoff_watch_failed': '晚交巡查自己抛异常（stream＝rhythm-plans）',
}
# ── 组 C：对照（降级、伴生句、我自己那一侧的拒）——列条数，不计入失败总数 ──
AUDIT_CONTRAST = {
    'attend.fallback': '关口失败那一拍的伴生句（与 attend.failed 同拍，不相加）',
    'note.refused': 'note 被拒（role_tool 的子集，不相加）',
    'render.over_budget': '渲染超预算（降级）',
    'state.conflict': '状态写冲突',
    'turn.unsent_body': '写了没发出去的正文',
}
MISSING_CAUSES = {'clash': '撞车（同一段对话同时被两处打开）', 'timeout': '等太久',
                  'unanswered': '模型没按 接话／不理 答', 'cut': '模型没答完', 'error': '程序出错'}
STOP_FAILURES = {'killed': '宿主被外部终止', 'crashed': '宿主自己崩掉退出', 'worker_down': 'worker 停了没马上起来'}
RESTART_PLANNED = {'published', 'settings', 'settings_restored'}   # 自己发版、换设置：不算失败
# 数据根 reports/ 下每拍一条的哈希链事件：只取文件名里的 type、time_ns、payload 里那几个短字段。
REPORT_FAILURES = {'provider.error': '上游调用抛异常', 'handover.lost': '交给 worker 的任务丢了',
                   'host.task_interrupted': '宿主停下时任务被打断（RUNNING→BLOCKED）'}
REPORT_SILENT = {'provider.request 无响应': '请求发出去没等到回（静默没跑）',
                 'provider.response 非 2xx': '上游回了非 2xx',
                 'provider.response 状态码读不出': '响应文件头里读不出 status_code（这一条没真判）'}
REPORT_CONTRAST = {'host.inbound_slow（对照）': '入站变慢（降级，不计入失败总数）'}
REPORT_WATCH = set(REPORT_FAILURES) | {'provider.request', 'provider.response'} | set(REPORT_CONTRAST)

# ── A／B 双面：同一件事可能在两面各留一条，记录数因此翻倍（不判原因，只把两笔账分开报）──
# 现读依据：11-04→11-07 那一窗里 attend.failed 的 stream_id 与 missed_looks 的 _id 交集 84、
# 两侧各自独有 0——同一个回合在 A 面（带报错行）与 B 面（该判没判）各留了一条。
OVERLAP_PAIRS = (('attend.failed', 'missed_looks', 'error'),)
DEDUP_CAP = 20000                 # distinct 值多过这么多就不判：判不了要明说，不许拿部分冒充全量

# ── 保留期：常数取跑着的 core（注释带出处）；host.log 那一格用这一趟真读到的最前一行时刻 ──
MISSED_KEPT_DAYS = 7              # core python/asuna/host_stops.py:213 MISSED_KEPT_DAYS（清理靠家回合触发）
AUDIT_KEPT_DAYS = 30              # core python/asuna/audit.py:141 RETENTION_DAYS（role_tool 365 天：audit.py:142）
LANE_KEPT_DAYS = 30               # core python/asuna/lane_faults.py:27 KEEP_DAYS
TAIL_MIB = TAIL_BYTES // (1024 * 1024)
GATE_CAP = 5000                   # 闸拒型拆分一窗最多读这么多条 turn.rejected，读满就不拆
DISPATCH_CAP = 5000               # 延迟分档一窗最多读这么多条 dispatched，超了要在输出里明说只读了前这么多
LOG_LEVEL = re.compile(r'^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(\w+)')
LOG_BAD = re.compile(r'\b(?:warn|warning|error|fatal|critical)\b|Traceback|Exception|Error:|\bexited\b', re.I)
LOG_LEVELS = ('warn', 'warning', 'error', 'fatal', 'critical')
# 本机通道 HTTP 服务写回时对端提前断：栈末落在 channels.py 的 wfile.write，异常是 ConnectionReset[10054]／ConnectionAborted[10053]。
# 三样都得在同一件事里出现才算（只有异常名、没有 channels.py 栈帧的照旧留在 A）。归类是「推断」，不是正面证据。
LOG_RESET = re.compile(r'ConnectionResetError|ConnectionAbortedError|WinError 1005[34]|\[1005[34]\]|Errno 1005[34]')


# ────────────────────────────── 时刻：现读配对，不背偏移 ──────────────────────────────

def derive_offset(local_now_text, utc_now):
    """把「她这边现在的钟点」与同一刻的 UTC 配成一对，推出偏移。返回 (偏移, (本地原值, UTC 原值))。"""
    local = parse_moment(local_now_text)
    if local is None or utc_now is None:
        return timedelta(0), (str(local_now_text), utc_now.isoformat() if utc_now else '')
    delta = local.replace(tzinfo=utc_now.tzinfo) - utc_now
    # 她给的钟点是分钟精度（秒位被截），真实时区偏移都是 15 分钟的整倍数：按 15 分钟对齐才稳，
    # 否则同一趟会打出 UTC+12:59 这种既不是本机偏移也对不上任何时区的怪数。
    quarters = int(round(delta.total_seconds() / 900.0))
    return timedelta(minutes=quarters * 15), (str(local_now_text), utc_now.isoformat())


def parse_moment(value):
    """库里的时刻（ISO 文本，Z 或 +00:00）／datetime／Date → 带时区的 UTC datetime；读不来给 None。"""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    text = str(value or '').strip()
    if not text:
        return None
    try:
        got = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        try:
            got = datetime.strptime(text, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            return None
        return got.replace(tzinfo=timezone.utc)
    return (got if got.tzinfo else got.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def local_text(value, offset):
    """库里的 UTC 时刻 → 本地钟面文本（偏移用现读配对那一格）。读不来的打 `?`，不编。"""
    moment = parse_moment(value)
    return (moment + offset).strftime('%Y-%m-%d %H:%M:%S') if moment else '?'


def ns_moment(ns):
    """事件文件里的 time_ns（epoch 纳秒）→ UTC datetime。"""
    try:
        whole, rest = divmod(int(ns), 10 ** 9)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(whole, timezone.utc) + timedelta(microseconds=rest // 1000)


# ────────────────────────────── 样例行：形状，不搬正文 ──────────────────────────────

def snippet(text, cap=SAMPLE_CHARS):
    """一条错误行压成一行：空白折叠、绝对路径／内网地址／长十六进制号换成占位、超长截断。"""
    flat = ' '.join(str(text or '').split())
    flat = re.sub(r'\b[A-Za-z]:[\\/][^\s"\']*', '<路径>', flat)
    flat = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?', '<地址>', flat)
    flat = re.sub(r'\b[0-9a-fA-F]{24,}\b', '<长号>', flat)
    return flat if len(flat) <= cap else flat[:cap - 1] + '…'


def audit_snippet(payload):
    """审计 payload 里那行错误：优先 error／problem／reason，再取 traceback 的末行（那行才是异常）。"""
    if not isinstance(payload, dict):
        return snippet(payload)
    for key in ('error', 'problem', 'reason', 'outcome', 'message'):
        if payload.get(key):
            return snippet('%s=%s' % (key, payload[key]))
    if any(key in payload and payload[key] == '' for key in ('error', 'problem', 'reason')):
        return snippet(' '.join('%s=（空）' % key for key in ('error', 'problem', 'reason')
                                if key in payload and payload[key] == ''))
    trace = payload.get('traceback')
    if trace:
        tail = [line for line in str(trace).splitlines() if line.strip()]
        return snippet('traceback末行=%s' % (tail[-1] if tail else ''))
    picked = {key: payload[key] for key in ('cause', 'code', 'type', 'count', 'since', 'every_seconds')
              if key in payload}
    return snippet(picked or payload)


def short_id(value):
    text = str(value or '')
    return text if len(text) <= ID_CHARS else text[:ID_CHARS] + '…'


def stamp(moment, offset):
    """任何形状的时刻 → 本地钟面文本。datetime 也要加偏移，不加打出来的就是 UTC。"""
    if isinstance(moment, datetime):
        return (moment.astimezone(timezone.utc) + offset).strftime('%Y-%m-%d %H:%M:%S')
    return local_text(moment, offset)


# ────────────────────────────── 读数面：每面返回同一形状 ──────────────────────────────

def face(name, note, items=None, read=True, error='', cls='A', coverage=None):
    """一面读数：面名、说明、分组条目、读没读到（附真原因）、这一面的默认归类（A／B／C／D），
    另挂 coverage＝这一面真读到的最前时刻（保留期核查用）。读不到就不填，不猜。"""
    return {'face': name, 'note': note, 'items': items or [], 'read': read, 'error': error, 'cls': cls,
            'coverage': coverage}

def item(group, why, count, first=None, last=None, samples=None, cls=None):
    return {'group': group, 'why': why, 'n': int(count or 0), 'first': first, 'last': last,
            'samples': list(samples or []), 'cls': cls}


def audit_face(window, types, note, name, cls):
    """audit_events 的一类 type：按 type 分组数条数、首末时刻、各型样例行（窗口内最早的几条）。

    查询的 type 名单**只从传进来的名册取**（`$in`）：库里另有的别的 type 不进这一面。"""
    rows = dbread.aggregate('audit_events',
                            [{'$match': {'type': {'$in': sorted(types)}, 'occurred_at': window['$bound']}},
                             {'$group': {'_id': '$type', 'n': {'$sum': 1}, 'first': {'$min': '$occurred_at'},
                                         'last': {'$max': '$occurred_at'}}},
                             {'$sort': {'n': -1}}, {'$limit': 200}], limit=200)['rows']
    samples_by_type = {}
    for row in rows:
        kind = row.get('_id')
        if kind not in types:
            continue
        found = dbread.find('audit_events', {'type': kind, 'occurred_at': window['$bound']},
                            fields=['occurred_at', 'stream_id', 'payload'], sort=[('occurred_at', 1)], limit=SAMPLES)
        samples_by_type[kind] = ['%s %s %s' % (local_text(one.get('occurred_at'), window['offset']),
                                               short_id(one.get('stream_id')), audit_snippet(one.get('payload')))
                                 for one in found['rows']]
    items = audit_items(rows, samples_by_type, types, cls)
    if 'turn.rejected' in types and cls == 'A':
        found = dbread.find('audit_events', {'type': 'turn.rejected', 'occurred_at': window['$bound']},
                            fields=['occurred_at', 'payload'], sort=[('occurred_at', 1)], limit=GATE_CAP)['rows']
        if len(found) < GATE_CAP:                       # 读满了就不分：判不了的照旧留在 A，不拿部分冒充全量
            items = split_gate_refusals(found, items, window['offset'])
    return face(name, note, items, cls=cls)


def is_gate_refusal(payload):
    """「闸拒型」：整回合被退回，原因是我自己这拍没先写心里话／没写要说的话（problem 字面是 unsent、或带「还没写心里话」／「没写要说的话」）。
    连看三天天天同形，判过是噪声型（我自己的拍被闸拒，不是机器坏）；字面认不出来的 problem 照旧留在组 A。"""
    problem = str((payload or {}).get('problem') or '') if isinstance(payload, dict) else ''
    return problem == 'unsent' or '还没写心里话' in problem or '没写要说的话' in problem


def split_gate_refusals(rows, items, offset):
    """turn.rejected 那一型里闸拒型的那些拆出去进组 C 对照；A 里的条数相应减掉（不进报数）。"""
    quiet = [row for row in rows if is_gate_refusal(row.get('payload'))]
    if not quiet:
        return items
    out = []
    for entry in items:
        if entry['group'] == 'turn.rejected':
            entry = dict(entry, n=max(0, entry['n'] - len(quiet)))
        out.append(entry)
    out.append(item('turn.rejected[闸拒型（噪声）]', '整回合被退回、原因是我自己这拍没先写心里话／没写要说的话（unsent）：连看三天天天同形，判为噪声型；'
                    '降为对照、不进报数（同一类里字面认不出来的照旧留在组 A）',
                    len(quiet), quiet[0].get('occurred_at'), quiet[-1].get('occurred_at'),
                    ['%s %s' % (local_text(row.get('occurred_at'), offset), audit_snippet(row.get('payload')))
                     for row in quiet[:SAMPLES]], 'C'))
    return out


def audit_items(rows, samples_by_type, types, cls):
    """聚合行 → 分组条目：**只有名册里的 type 配得到一行**，名册外的一行都不数（自检钉着）。"""
    items = []
    for row in rows or []:
        kind = row.get('_id')
        if kind not in types:
            continue
        items.append(item(kind, types.get(kind, ''), row.get('n'), row.get('first'), row.get('last'),
                          (samples_by_type or {}).get(kind) or [], cls))
    return items

def role_tool_face(window):
    """我自己的工具调用被拒（对照，不算系统级失败）：role_tool 带 payload.refused，按工具分。"""
    rows = dbread.aggregate('audit_events',
                            [{'$match': {'type': 'role_tool', 'payload.refused': {'$exists': True},
                                         'occurred_at': window['$bound']}},
                             {'$group': {'_id': '$payload.tool', 'n': {'$sum': 1}, 'first': {'$min': '$occurred_at'},
                                         'last': {'$max': '$occurred_at'}}},
                             {'$sort': {'n': -1}}, {'$limit': 8}], limit=8)['rows']
    items = [item('role_tool.refused[%s]' % (row.get('_id') or '未标工具'), '我自己那一侧的拒（对照）',
                  row.get('n'), row.get('first'), row.get('last'), [], 'C') for row in rows]
    return face('role_tool.refused', '我自己的工具调用被拒（对照，不计入失败总数）', items, cls='C')


def missed_face(window):
    """missed_looks：关口该判而没判出来的那些拍——只有这张表能证明「它没跑」。cause 分五档。"""
    rows = dbread.aggregate('missed_looks',
                            [{'$match': {'at': window['$bound']}},
                             {'$group': {'_id': {'cause': '$cause', 'scene': '$scene_id'}, 'n': {'$sum': 1},
                                         'first': {'$min': '$at'}, 'last': {'$max': '$at'}}},
                             {'$sort': {'n': -1}}, {'$limit': 200}], limit=200)['rows']
    by_cause = {}
    for row in rows:
        key = row.get('_id') or {}
        cause = str(key.get('cause') or 'error')
        bucket = by_cause.setdefault(cause, {'n': 0, 'first': None, 'last': None, 'scenes': []})
        bucket['n'] += row.get('n') or 0
        moment_first, moment_last = row.get('first'), row.get('last')
        for edge, moment in (('first', moment_first), ('last', moment_last)):
            if not moment:
                continue
            have = bucket[edge]
            if have is None or (str(moment) < str(have) if edge == 'first' else str(moment) > str(have)):
                bucket[edge] = moment        # 首取最小、末取最大：同一把尺写反会把末时刻打成中间的
        assert True
        bucket['scenes'].append((str(key.get('scene') or '?'), row.get('n') or 0))
    items = []
    for cause, bucket in sorted(by_cause.items(), key=lambda kv: -kv[1]['n']):
        samples = []
        for scene, _count in sorted(bucket['scenes'], key=lambda kv: -kv[1])[:SAMPLES]:
            for one in dbread.find('missed_looks', {'cause': cause, 'scene_id': scene, 'at': window['$bound']},
                                   fields=['at', '_id'], sort=[('at', 1)], limit=1)['rows']:
                samples.append('%s scene=%s turn=%s' % (local_text(one.get('at'), window['offset']), scene,
                                                        short_id(one.get('_id'))))
        items.append(item('missed_looks[%s]' % cause, MISSING_CAUSES.get(cause, '程序出错'), bucket['n'],
                          bucket['first'], bucket['last'], samples, 'B'))
    return face('missed_looks', '关口该判没判（84 次那一趟数的就是这张表）', items, cls='B')


def stop_face(window):
    """host_stops：非计划停机（被外部终止／自己崩／worker 停了）＋计划外原因的 worker 重启。"""
    items = []
    rows = dbread.find('host_stops', {'how': {'$in': sorted(STOP_FAILURES)}, 'back_at': window['$bound']},
                       fields=['how', 'alive_until', 'back_at', 'exit_code', 'cause', 'tries'],
                       sort=[('back_at', 1)], limit=200)['rows']
    by_how = {}
    for row in rows:
        by_how.setdefault(str(row.get('how')), []).append(row)
    for how, found in sorted(by_how.items(), key=lambda kv: -len(kv[1])):
        samples = []
        for row in found[:SAMPLES]:
            alive, back = parse_moment(row.get('alive_until')), parse_moment(row.get('back_at'))
            gone = ' 停了约 %d 分钟' % max(1, round((back - alive).total_seconds() / 60)) if alive and back else ''
            extra = ' '.join('%s=%s' % (key, row[key]) for key in ('exit_code', 'cause', 'tries')
                             if row.get(key) is not None)
            samples.append('%s→%s%s %s' % (local_text(row.get('alive_until'), window['offset']),
                                           local_text(row.get('back_at'), window['offset']), gone, snippet(extra)))
        items.append(item('host_stops[%s]' % how, STOP_FAILURES.get(how, how), len(found),
                          found[0].get('back_at'), found[-1].get('back_at'), samples, 'B'))
    restarts = dbread.find('host_stops', {'how': 'worker_restart', 'asked_at': window['$bound']},
                           fields=['cause', 'asked_at', 'back_at'], sort=[('asked_at', 1)], limit=200)['rows']
    odd = [row for row in restarts if str(row.get('cause') or 'unknown') not in RESTART_PLANNED]
    if odd:
        items.append(item('host_stops[worker_restart 计划外]', 'worker 重启，原因不在计划内那两类', len(odd),
                          odd[0].get('asked_at'), odd[-1].get('asked_at'),
                          ['%s cause=%s' % (local_text(row.get('asked_at'), window['offset']), row.get('cause'))
                           for row in odd[:SAMPLES]], 'A'))
    return face('host_stops', '宿主／worker 停过（非计划）＋计划外重启', items, cls='B')


def lane_face(window):
    """lane_faults：通道那一层的故障小时计数（按 channel|lane|stage|error 分）。
    hour_at 存的是 Date、窗口边界是文本，所以整表读回来在 Python 里比时刻（这表本来就小）。"""
    rows = dbread.find('lane_faults', {}, fields=['channel_id', 'lane', 'stage', 'error', 'hour_at',
                                                  'count', 'first_posted_at', 'last_posted_at'],
                       sort=[('hour_at', 1)], limit=500)['rows']
    by_key = {}
    for row in rows:
        moment = parse_moment(row.get('last_posted_at') or row.get('hour_at') or row.get('first_posted_at'))
        if not moment or not (window['start'] <= moment < window['end']):
            continue
        key = '%s|%s|%s|%s' % (row.get('channel_id'), row.get('lane'), row.get('stage'), row.get('error'))
        bucket = by_key.setdefault(key, {'n': 0, 'first': moment, 'last': moment})
        bucket['n'] += int(row.get('count') or 0)
        bucket['first'] = min(bucket['first'], moment)
        bucket['last'] = max(bucket['last'], moment)
    items = [item('lane_faults[%s]' % key, '通道层故障（按小时聚合的计数相加）', bucket['n'], bucket['first'],
                  bucket['last'], ['%s 该组累计 %d 次' % (stamp(bucket['last'], window['offset']), bucket['n'])], 'A')
             for key, bucket in sorted(by_key.items(), key=lambda kv: -kv[1]['n'])]
    return face('lane_faults', '通道层（入站／出站投递）故障小时表', items, cls='A')


def task_moment(row):
    """任务行的时刻：created_at 优先；老行可能没有这个键（BLOCKED／UNKNOWN 里就有这样的行），
    退回 lease_expires_at（秒）；都没有给 None——判不了的不许混进窗口计数。"""
    moment = parse_moment(row.get('created_at'))
    if moment:
        return moment, 'created_at'
    lease = row.get('lease_expires_at')
    try:
        return datetime.fromtimestamp(float(lease), timezone.utc), 'lease_expires_at'
    except (TypeError, ValueError):
        return None, ''


def running_cutoff(window, stale_hours):
    """RUNNING 未回执的分界文本：tasks.created_at 存的是 UTC 的 ISO 文本（带 T），分界必须是同一把尺。
    旧写法拿本地钟面的 `YYYY-MM-DD HH:MM:SS` 去比 UTC ISO 文本：偏移差一个时区差，且空格排在 T 前面，同一天里比较恒偏小。"""
    return (window['start'] - timedelta(hours=stale_hours)).strftime('%Y-%m-%dT%H:%M:%S')


def task_face(window, stale_hours):
    """任务级：带 failure_type 的、BLOCKED／UNKNOWN 卡住的、老于阈值还挂着的 RUNNING（未回执）。"""
    offset = window['offset']
    items = []
    rows = dbread.find('tasks', {'failure_type': {'$exists': True}, 'created_at': window['$bound']},
                       fields=['state', 'failure_type', 'created_at'], sort=[('created_at', 1)], limit=200)['rows']
    by_type = {}
    for row in rows:
        by_type.setdefault(str(row.get('failure_type')), []).append(row)
    for kind, found in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        items.append(item('tasks.failure_type[%s]' % kind, '任务级异常／被打断（这些行没有 finished_at，按 created_at 圈窗）',
                          len(found), found[0].get('created_at'), found[-1].get('created_at'),
                          ['%s state=%s' % (local_text(row.get('created_at'), offset), row.get('state'))
                           for row in found[:SAMPLES]], 'A'))
    stuck, no_time, stock = [], [], []
    for row in dbread.find('tasks', {'state': {'$in': ['BLOCKED', 'UNKNOWN']}},
                           fields=['state', 'created_at', 'lease_expires_at', 'failure_type'],
                           sort=[('created_at', 1)], limit=500)['rows']:
        moment, source = task_moment(row)
        if moment is None:
            no_time.append(row)
        elif window['start'] <= moment < window['end']:
            stuck.append((moment, source, row))
        elif moment < window['start']:
            stock.append((moment, source, row))          # 存量：窗口前建的、至今还卡着
    if stuck:
        stuck.sort(key=lambda triple: triple[0])
        items.append(item('tasks.state[BLOCKED／UNKNOWN]', '卡住的任务（时刻按 created_at，缺则按 lease_expires_at）',
                          len(stuck), stuck[0][0], stuck[-1][0],
                          ['%s state=%s%s %s' % (stamp(moment, offset), row.get('state'),
                                                 '' if source == 'created_at' else '（时刻取 lease_expires_at）',
                                                 'failure_type=%s' % row.get('failure_type')
                                                 if row.get('failure_type') else '')
                           for moment, source, row in stuck[:SAMPLES]], 'B'))
    if stock:
        stock.sort(key=lambda triple: triple[0])
        items.append(item('tasks.state[BLOCKED／UNKNOWN 存量]', '窗口前就建、至今仍卡着的存量（不是这一窗新发生的）：列在对照、不进报数；这些行该不该收尾另看',
                          len(stock), stock[0][0], stock[-1][0],
                          ['%s state=%s%s' % (stamp(moment, offset), row.get('state'),
                                              '' if source == 'created_at' else '（时刻取 lease_expires_at）')
                           for moment, source, row in stock[:SAMPLES]], 'C'))
    if no_time:
        items.append(item('tasks.state[BLOCKED／UNKNOWN 判不了]', '这些行既没 created_at 也没 lease_expires_at：'
                          '落不进窗口，单列不计数（n 列的是条数，时刻栏写 -）', len(no_time), None, None,
                          ['state=%s failure_type=%s' % (row.get('state'), row.get('failure_type'))
                           for row in no_time[:SAMPLES]], 'B'))
    cutoff = running_cutoff(window, stale_hours)
    old = dbread.find('tasks', {'state': 'RUNNING', 'created_at': {'$lt': cutoff}},
                      fields=['created_at'], sort=[('created_at', 1)], limit=200)['rows']
    if old:
        items.append(item('tasks.state[RUNNING 未回执]', '老于阈值还挂着（阈值 --stale-hours，默认 6 小时）', len(old),
                          old[0].get('created_at'), old[-1].get('created_at'),
                          ['%s 起还挂着' % local_text(row.get('created_at'), offset) for row in old[:SAMPLES]], 'B'))
    return face('tasks', '任务级失败与未回执', items, cls='A')


# ────────────────────────────── 读数面：数据根下的运行文件 ──────────────────────────────

def _head(path):
    """事件文件读头一截（＋头里没有 time_ns 时尾一截）：status_code／call_id／purpose 排在正文前面，
    time_ns 排在正文后面。大响应（embedding 那种几 MB 正文）只读头会漏掉 time_ns，
    漏了就把「已经回了」的请求误判成「没等到回」（那一窗的账记在 CHANGELOG.md）。"""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as handle:
            head = handle.read(HEAD_BYTES).decode('utf-8', errors='replace')
            tail = ''
            if '"time_ns":' not in head and size > HEAD_BYTES:
                handle.seek(max(0, size - TAIL_READ_BYTES))
                tail = handle.read(TAIL_READ_BYTES).decode('utf-8', errors='replace')
        return head, tail
    except OSError:
        return '', ''


def _moment_of(head, tail):
    """从头一截或尾一截里取 time_ns；两处都没有给 None（这条读不出时刻，不猜）。"""
    for text in (head, tail):
        moment = ns_moment(_field(text, 'time_ns'))
        if moment:
            return moment
    return None


def _field(text, name):
    got = re.search(r'"%s":\s*"?([^,"\}\]]+)"?' % re.escape(name), text)
    return got.group(1).strip().strip('"') if got else ''


def report_face(data_root, window, grace_minutes=GRACE_MINUTES):
    """reports/native-host-*/NNNNN-<type>.json：宿主每拍一条的哈希链事件。
    组 A：provider.error、上游非 2xx、任务丢、任务被打断；组 B：provider.request 无响应；组 C：入站变慢。"""
    base = os.path.join(str(data_root), 'reports')
    if not os.path.isdir(base):
        return face('reports', '宿主事件文件里的上游（provider）失败与无响应', read=False, error='读不到 %s' % base)
    offset = window['offset']
    floor = window['start'] - timedelta(hours=6)      # mtime 只做粗筛，真时刻以文件里的 time_ns 为准
    newest, buckets, answered, pending = None, {}, set(), []
    for run in sorted(os.listdir(base)):
        folder = os.path.join(base, run)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith('.json') or '-' not in name:
                continue
            kind = name.split('-', 1)[1][:-5]
            if kind not in REPORT_WATCH:
                continue
            path = os.path.join(folder, name)
            try:
                stamp_mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
            except OSError:
                continue
            if stamp_mtime < floor:
                continue
            newest = stamp_mtime if newest is None else max(newest, stamp_mtime)
            head, tail = _head(path)
            moment = _moment_of(head, tail)
            if moment is None:
                continue
            call = _field(head, 'call_id')
            if kind == 'provider.response':
                if call:
                    answered.add(call)                # 回没回应看时刻之外的全部窗口（响应可能落在窗口右端之外）
                if not (window['start'] <= moment < window['end']):
                    continue
                code = _field(head, 'status_code')
                if code and not code.startswith('2'):
                    buckets.setdefault('provider.response 非 2xx', []).append(
                        (moment, 'call=%s status=%s ref=%s' % (short_id(call), code, _field(head, 'request_ref'))))
                elif not code:
                    buckets.setdefault('provider.response 状态码读不出', []).append((moment, 'call=%s' % short_id(call)))
            elif kind == 'provider.request':
                if call and window['start'] <= moment < window['end']:
                    pending.append((moment, call, _field(head, 'purpose')))
            elif window['start'] <= moment < window['end']:
                if kind in REPORT_FAILURES:
                    extras = [('call', call, True), ('type', _field(head, 'type'), False),
                              ('cause', _field(head, 'cause'), False), ('task', _field(head, 'task_id'), True),
                              ('dur', _field(head, 'duration_seconds'), False)]
                    buckets.setdefault(kind, []).append((moment, snippet(' '.join(
                        '%s=%s' % (label, short_id(value) if cut else value) for label, value, cut in extras if value))))
                elif kind in REPORT_CONTRAST:
                    buckets.setdefault('host.inbound_slow（对照）', []).append((moment, snippet(_field(head, 'task_id'))))
    deadline = newest - timedelta(minutes=grace_minutes) if newest else None
    open_now = [(moment, call, purpose) for moment, call, purpose in pending
                if call not in answered and (deadline is None or moment <= deadline)]
    if open_now:
        buckets['provider.request 无响应'] = [(moment, 'call=%s purpose=%s 没等到响应' % (short_id(call), purpose or '?'))
                                       for moment, call, purpose in sorted(open_now)]
    items = []
    for kind, rows in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        rows = sorted(rows, key=lambda pair: pair[0])
        cls = 'B' if kind in REPORT_SILENT else ('C' if kind in REPORT_CONTRAST else 'A')
        why = REPORT_SILENT.get(kind) or REPORT_CONTRAST.get(kind) or REPORT_FAILURES.get(kind, kind)
        items.append(item(kind, why, len(rows), rows[0][0], rows[-1][0],
                          ['%s %s' % (stamp(moment, offset), text) for moment, text in rows[:SAMPLES]], cls))
    return face('reports', '宿主事件文件：provider 异常／非 2xx／无响应／任务丢', items, cls='A')


def host_log_face(data_root, window):
    """restart/host.log：只认带 ISO 时刻的行（warn／error／Traceback／exited）。
    traceback 的续行没有时刻、算到上一条头上不另计——否则一次异常能数出十几条。"""
    path = os.path.join(str(data_root), 'restart', 'host.log')
    if not os.path.isfile(path):
        return face('host.log', '宿主控制台日志里带时刻的异常行', read=False, error='读不到 %s' % path)
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as handle:
            if size > TAIL_BYTES:
                handle.seek(size - TAIL_BYTES)
                handle.readline()
            raw = handle.read()
    except OSError as exc:
        return face('host.log', '宿主控制台日志里带时刻的异常行', read=False, error=str(exc))
    offset = window['offset']
    text = raw.decode('utf-8', errors='replace')
    coverage = {'floor': first_moment(text), 'truncated': size > TAIL_BYTES, 'bytes': size}
    all_hits = count_log_lines(text, window['start'], window['end'])
    hits = [one for one in all_hits if not is_peer_disconnect(one)]
    quiet = [one for one in all_hits if is_peer_disconnect(one)]
    items = []
    if hits:
        items.append(item('host.log[异常事件]', '宿主控制台带时刻的异常（连续坏行并成一件事）', len(hits),
                          hits[0]['first'], hits[-1]['last'],
                          [snippet('%s 〔连续 %d 行〕 %s　末行：%s' % (stamp(one['first'], offset), one['lines'],
                                                                 one['head'], one['tail'])) for one in hits[:SAMPLES]],
                          'A'))
    if quiet:
        items.append(item('host.log[本机断端类（推断）]', '栈末落在 channels.py wfile.write、ConnectionReset[10054]／ConnectionAborted[10053]：'
                          '推断是本机通道 HTTP 服务写回时对端提前断开（lane_faults 没行是旁证、不是正面证据）；降为对照、不进报数',
                          len(quiet), quiet[0]['first'], quiet[-1]['last'],
                          [snippet('%s 〔连续 %d 行〕 %s　末行：%s' % (stamp(one['first'], offset), one['lines'],
                                                                 one['head'], one['tail'])) for one in quiet[:SAMPLES]],
                          'C'))
    return face('host.log', '宿主控制台日志里带时刻的异常行', items, cls='A', coverage=coverage)


def first_moment(text):
    """文本里第一条带 ISO 时刻的行——读文件的面用它说清「这一趟真追到多远」，不靠猜。"""
    for line in text.splitlines():
        got = LOG_LEVEL.match(line)
        if got:
            moment = parse_moment(got.group(1))
            if moment:
                return moment
    return None

def _mark_line(current, line):
    """一件事里出现过哪些特征（只记有没有，不存正文）。"""
    if LOG_RESET.search(line):
        current['reset'] = True
    if 'channels.py' in line:
        current['channels'] = True
    if 'wfile.write' in line:
        current['wfile'] = True


def is_peer_disconnect(event):
    """本机通道写回时对端断开这一族：三样齐才算（推断类，不是正面证据）。"""
    return bool(event.get('reset') and event.get('channels') and event.get('wfile'))


def count_log_lines(text, start, end):
    """控制台日志 → 每件事一条：连续坏行（含无时刻的 traceback 续行）并成一件事。
    一次异常吐十几行不是十几次失败。"""
    out, current = [], None
    for line in text.splitlines():
        got = LOG_LEVEL.match(line)
        if got:
            moment = parse_moment(got.group(1))
            level = got.group(2).lower()
            bad = bool(LOG_BAD.search(line)) or level in LOG_LEVELS
            if not bad or moment is None or not (start <= moment < end):
                current = None
                continue
            body = snippet(line[got.end():]) or snippet(line)
            if current is not None:
                current['last'] = moment
                current['lines'] += 1
                current['tail'] = body
                _mark_line(current, line)
                continue
            current = {'first': moment, 'last': moment, 'lines': 1, 'head': body, 'tail': body,
                       'reset': False, 'channels': False, 'wfile': False}
            _mark_line(current, line)
            out.append(current)
        elif current is not None:
            # 无时刻的行是上一条异常的续行（traceback 的 File／raise 那些），不算新事件也不结束这件事；
            # 只有带时刻的健康行才把这件事收尾。
            current['lines'] += 1
            _mark_line(current, line)
            if LOG_BAD.search(line):
                current['tail'] = snippet(line)
    return out


def restart_face(data_root, window):
    """进程级：restart/history.jsonl（起没起来、试了几档）＋worker-restarts.jsonl（非零退出）。"""
    offset = window['offset']
    items = []
    read_any = False
    for label, why, rel, line_of in (
            ('restart[没起来或试过几档]', '重启记录里 result 不是 running、或有尝试没成',
             os.path.join('restart', 'history.jsonl'), restart_line),
            ('worker 非零退出／启动失败', 'worker 退出码非零或起不来（计划内重启不计）',
             'worker-restarts.jsonl', worker_line)):
        path = os.path.join(str(data_root), rel)
        if not os.path.isfile(path):
            items.append(item(label + '（这一面读不到）', '读不到 %s' % rel, 0, None, None, [], 'C'))
            continue
        try:
            lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
        except OSError as exc:
            items.append(item(label + '（这一面读不了）', snippet(exc, 60), 0, None, None, [], 'C'))
            continue
        read_any = True
        bad = []
        for line in lines:
            if not line.strip():
                continue
            moment, text = line_of(line)
            if moment and text and window['start'] <= moment < window['end']:
                bad.append((moment, text))
        if bad:
            bad.sort(key=lambda pair: pair[0])
            items.append(item(label, why, len(bad), bad[0][0], bad[-1][0],
                              ['%s %s' % (stamp(moment, offset), text) for moment, text in bad[:SAMPLES]], 'A'))
    return face('restart', '进程级：非零退出、起不来、崩溃', items, read=read_any,
                error='' if read_any else '两个重启记录都读不到', cls='A')


def restart_line(line):
    """一条重启记录 → (时刻, 失败描述或 '')。result 不是 running、或有 attempt 没成都算。"""
    row = _loads(line)
    moment = parse_moment(row.get('down_at'))
    attempts = row.get('attempts') if isinstance(row.get('attempts'), list) else []
    failed = [one for one in attempts if isinstance(one, dict) and not one.get('ok')]
    result = str(row.get('result') or '')
    if result and result != 'running':
        return moment, 'result=%s rung=%s 试了 %d 次' % (result, row.get('rung'), len(attempts) or 1)
    if failed:
        return moment, '第 %s 档没起来（共试 %d 次）' % (failed[0].get('rung'), len(attempts))
    return moment, ''


def worker_line(line):
    """一条 worker 重启记录 → (时刻, 失败描述或 '')。「worker asked: …」是计划内，不计。"""
    row = _loads(line)
    moment = parse_moment(row.get('at'))
    reason = str(row.get('reason') or '')
    if not reason or reason.startswith('worker asked'):
        return moment, ''
    return moment, snippet(reason)


def _loads(text):
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}



# ────────────────── 双面去重 ／ 保留期核查 ／ 计划延迟分档 ──────────────────

def dedup_reading(window):
    """A／B 双面去重：同一件事（同一回合）在两面各留一条时，记录数翻倍、事件数只算一次。

    只按 `OVERLAP_PAIRS` 里写死的配对判，配不上的不猜；哪一面查不到就说「判不了」，不印 0。
    两笔账分开报：合计＝记录数（旧口径一字不改），另报按事件去重后的件数。不判原因。"""
    pairs, unknown, lost = [], [], 0
    for kind, coll, cause in OVERLAP_PAIRS:
        a_filter = {'type': kind, 'occurred_at': window['$bound']}
        b_filter = {'cause': cause, 'at': window['$bound']}
        if cause == 'error':
            # 没带 cause 的 missed_looks 行在 missed_face 里也归进 error：这里同一把尺
            b_filter = {'$or': [{'cause': cause}, {'cause': {'$exists': False}}], 'at': window['$bound']}
        try:
            a_n = int(dbread.count('audit_events', a_filter).get('found') or 0)
            b_n = int(dbread.count(coll, b_filter).get('found') or 0)
            a_keys = {str(one) for one in dbread.distinct('audit_events', 'stream_id', a_filter)['rows']}
            b_keys = {str(one) for one in dbread.distinct(coll, '_id', b_filter)['rows']}
        except Exception as exc:                       # noqa: BLE001 判不了就明说，不许印成 0
            unknown.append('%s ↔ %s[%s]：%s: %s' % (kind, coll, cause, type(exc).__name__, exc))
            continue
        if a_n > DEDUP_CAP or b_n > DEDUP_CAP:
            unknown.append('%s ↔ %s[%s]：%d／%d 条多过判定上限 %d，这一对不判'
                           % (kind, coll, cause, a_n, b_n, DEDUP_CAP))
            continue
        dup = len(a_keys & b_keys)
        lost += dup
        pairs.append({'a': kind, 'b': '%s[%s]' % (coll, cause), 'a_n': a_n, 'b_n': b_n,
                      'a_u': len(a_keys), 'b_u': len(b_keys), 'dup': dup})
    return {'lost': lost, 'pairs': pairs, 'unknown': unknown}


def dedup_quiet(window):
    """双面去重整趟挂了也要说实话：报「判不了」＋真原因，不许印成「0 条重复」蒙过去。"""
    try:
        return dedup_reading(window)
    except Exception as exc:                       # noqa: BLE001 判不了就明说，不印 0
        return {'lost': 0, 'pairs': [], 'unknown': ['整趟查挂了：%s: %s' % (type(exc).__name__, exc)]}


def dedup_lines(dedup, records):
    """把「记录数」与「按事件去重后的件数」分成两行报，谁也不冒充谁。"""
    if not dedup:
        return []
    out = []
    if dedup.get('pairs'):
        out.append('按事件去重：系统级失败 %d 件（记录 %d 条 − 双面重复 %d 条）' % (
            records - dedup['lost'], records, dedup['lost']))
        for pair in dedup['pairs']:
            out.append('  · %s 记录 %d 条（去重后 %d 件）↔ %s 记录 %d 条（去重后 %d 件）：同一批事件 %d 条%s' % (
                pair['a'], pair['a_n'], pair['a_u'], pair['b'], pair['b_n'], pair['b_u'], pair['dup'],
                '' if pair['dup'] else '（库里没有同事件重复）'))
    else:
        out.append('按事件去重：判不了（一对都没配起来）')
    for why in dedup.get('unknown') or []:
        out.append('  · 双面去重判不了：%s' % why)
    return out


def retention_lines(window, faces, offset):
    """保留期核查：窗口起点早于某面的已知保留期、或早于这一趟真读到的最前一行时，顶部打一行
    「可能数少（超出保留期）」——静默数少最坑人，宁可多嘴。全在期内也打一行说明这一趟查过。"""
    local_now = window.get('local_now') or window['local_end']
    flags = []
    for name, days in (('missed_looks', MISSED_KEPT_DAYS), ('audit_events', AUDIT_KEPT_DAYS),
                       ('lane_faults', LANE_KEPT_DAYS)):
        if window['local_start'] < local_now - timedelta(days=days):
            flags.append('%s（只留 %d 天，窗口起点 %s 比这更早）' % (
                name, days, window['local_start'].strftime('%Y-%m-%d %H:%M')))
    for one in faces:
        cover = one.get('coverage') or {}
        floor = cover.get('floor')
        if floor and window['start'] < floor:
            flags.append('%s（这一趟只读到 %s 之后的内容）' % (one['face'], stamp(floor, offset)))
        elif cover.get('truncated'):
            flags.append('%s（文件比末尾 %d MiB 还长，更早的读不到）' % (one['face'], TAIL_MIB))
    lines = ['保留期核查：窗口起点 %s｜missed_looks %d 天／audit_events %d 天／lane_faults %d 天／'
             'host.log 末尾 %d MiB（实际起点现读）→ %s'
             % (window['local_start'].strftime('%Y-%m-%d %H:%M'), MISSED_KEPT_DAYS, AUDIT_KEPT_DAYS,
                LANE_KEPT_DAYS, TAIL_MIB, '在期内' if not flags else '有面超出')]
    if flags:
        lines.append('可能数少（超出保留期）：%s' % '、'.join(flags))
    return lines


def plan_period(rule):
    """循环周期（秒）：every_seconds 直读；每日 clock 记 86400；一次性 at／after_seconds 给 None（没周期）。"""
    if not isinstance(rule, dict):
        return None
    every = rule.get('every_seconds')
    if every:
        try:
            return int(float(every))
        except (TypeError, ValueError):
            return None
    if isinstance(rule.get('clock'), dict):
        return 86400
    return None


def plan_label(plan):
    """计划名：intent 的头 40 字（跑着的 core 自己也是取 intent 那段），另带 _id 短号。"""
    intent = ' '.join(str((plan or {}).get('intent') or '').split())
    return '%s〔%s〕' % (snippet(intent or '（intent 没写）', 40), short_id(str((plan or {}).get('_id') or '?')))


def mmss(seconds):
    """秒数说人话：不到一分钟报秒，否则报几分几秒（两位小数按实测的毫秒读）。"""
    value = float(seconds)
    sign = '-' if value < 0 else ''
    value = abs(value)
    if value < 60:
        return '%s%.2f 秒' % (sign, value)
    minutes = int(value // 60)
    return '%s%d 分 %.2f 秒' % (sign, minutes, value - minutes * 60)


BANDS = ('≤1 分钟', '1–2 分钟', '>2 分钟')


def band_of(seconds):
    minutes = seconds / 60.0
    if minutes <= 1:
        return '≤1 分钟'
    return '1–2 分钟' if minutes <= 2 else '>2 分钟'


def bucket_add(bands, seconds, moment, pid, plan, offset):
    band = band_of(seconds)
    got = bands.setdefault(band, {'n': 0, 'over5': 0, 'samples': []})
    got['n'] += 1
    if seconds > 300:
        got['over5'] += 1
    got['samples'].append((moment, '%s 晚 %s' % (plan_label(plan), mmss(seconds))))


def restore_due(rule, plan, moment, offset):
    """一次性钟的应响时刻：rule.at 带 UTC 字样（at_utc 或显式偏移）时直接复原；after_seconds 用
    created_at 加秒数。复原不了给 None——本地钟面的 rule.at 不在这格硬算（没做就写没做）。"""
    if not isinstance(rule, dict):
        return None
    at = rule.get('at')
    if at and (rule.get('at_utc') or 'Z' in str(at) or '+00:00' in str(at)):
        due = parse_moment(at)
        if due:
            return (stamp(due, offset), (moment - due).total_seconds())
    after = rule.get('after_seconds')
    created = parse_moment(plan.get('created_at'))
    if after and created:
        try:
            due = created + timedelta(seconds=float(after))
        except (TypeError, ValueError):
            return None
        return (stamp(due, offset), (moment - due).total_seconds())
    return None


def delay_reading(window, rows=None, plan_of=None):
    """计划延迟分档：`plans.next_fire_at` 与 `audit_events` 里 `schedule.dispatched` 的时刻之差，分档。

    两把尺并排、各标各的读法（都不判原因）：
    ・「晚到（按下一次钟点倒推，仅循环计划末次派发）」——派发那一刻 core 已把 next_fire_at 推到下一次
      （跑着的 core schedule.py:1194–1201），所以只有该计划在这一窗最晚的那一条、且文档只往前推了一格时，
      应响时刻＝next_fire_at − 周期 才复原得出来。**软肋**：真晚到时「下一次」是按当下重算的
      （schedule.py:1197–1201），晚的那一截被推平，>5 分钟那一档可能照样量不到——量不到不等于没发生。
    ・「字面（计划文档里应响时刻还没被推）」——派发时不动 next_fire_at 的那类计划（schedule.py:1192
      只在 FIRED 时清空它），差值本身就是字面晚到。
    ・「对不上（next_fire_at 已是下一次）」与「null（一次性 FIRED）」单列，不混进档里充数：一次性计划
      FIRED 后 next_fire_at 是 None，两把尺都套不上（动机案例与两条候补路记在 CHANGELOG.md）。
    这一把与组 D 的 `schedule.handoff_late` **不是一把尺**：那一条量的是 DSH 的 acceptedAt → worker 接收，
    巡查线 300 秒（schedule.py:33 HANDOFF_LATE_SECONDS），只在超过那条线时才落行。
    """
    offset = window['offset']
    if rows is None:
        rows, skip = [], 0
        while len(rows) < DISPATCH_CAP:
            batch = dbread.find('audit_events', {'type': 'schedule.dispatched', 'occurred_at': window['$bound']},
                                fields=['stream_id', 'occurred_at'], sort=[('occurred_at', 1)],
                                limit=500, skip=skip)['rows']
            if not batch:
                break
            rows.extend(batch)
            skip += len(batch)
            if len(batch) < 500:
                break
    read_plan = plan_of or (lambda pid: (dbread.find('plans', {'_id': pid},
                                                     fields=['_id', 'intent', 'status', 'rule', 'next_fire_at',
                                                             'created_at', 'kind', 'native_recurring'],
                                                     limit=1)['rows'] or [None])[0])
    plans, last_of = {}, {}
    for row in rows:
        pid = str(row.get('stream_id') or '')
        if pid not in plans:
            plans[pid] = read_plan(pid)
        moment = parse_moment(row.get('occurred_at'))
        if moment and (pid not in last_of or moment > last_of[pid]):
            last_of[pid] = moment
    inferred, literal = {}, {}
    stats = {'rows': len(rows), 'plans': len(plans), 'no_plan': 0, 'no_moment': 0, 'mismatch': 0,
             'null': [], 'capped': len(rows) >= DISPATCH_CAP}
    for row in rows:
        pid = str(row.get('stream_id') or '')
        plan = plans.get(pid)
        moment = parse_moment(row.get('occurred_at'))
        if moment is None:
            stats['no_moment'] += 1
            continue
        if not plan:
            stats['no_plan'] += 1
            continue
        due_now = parse_moment(plan.get('next_fire_at'))
        if due_now is None:
            stats['null'].append((moment, pid, plan))
            continue
        delta = (moment - due_now).total_seconds()
        if delta >= 0:
            bucket_add(literal, delta, moment, pid, plan, offset)
            continue
        period = plan_period(plan.get('rule'))
        if period and last_of.get(pid) == moment and delta + period >= 0:
            bucket_add(inferred, delta + period, moment, pid, plan, offset)
        else:
            stats['mismatch'] += 1
    return {'inferred': inferred, 'literal': literal, 'stats': stats}


def delay_lines(window, reading):
    """延迟分档那一档的输出：每档报条数＋最晚三条的计划名与时刻；空档写「库里没有」。"""
    offset = window['offset']
    stats = reading['stats']
    lines = ['▲ 计划延迟分档（plans.next_fire_at ↔ schedule.dispatched 的时刻之差；不判原因）',
             '  这一把与 `schedule.handoff_late` 不是一把尺：那条量 DSH acceptedAt → worker 接收、5 分钟巡查线',
             '  窗口内 dispatched %d 条、涉及计划 %d 个%s' % (
                 stats['rows'], stats['plans'],
                 '（多过 %d 条，只读了前 %d 条）' % (DISPATCH_CAP, DISPATCH_CAP) if stats['capped'] else '')]
    for title, bands in (('晚到（按下一次钟点倒推，仅循环计划末次派发）', reading['inferred']),
                         ('字面（计划文档里应响时刻还没被推）', reading['literal'])):
        parts = []
        for band in BANDS:
            got = bands.get(band) or {'n': 0, 'over5': 0}
            parts.append('%s %d' % (band, got['n'])
                         + ('（其中 >5 分钟 %d）' % got['over5'] if band == '>2 分钟' else ''))
        lines.append('  %s：%s%s' % (title, '｜'.join(parts), '' if bands else '——库里没有'))
        for band in BANDS:
            got = bands.get(band) or {'samples': []}
            for _moment, text in sorted(got['samples'], key=lambda pair: pair[0], reverse=True)[:SAMPLES]:
                lines.append('    - %s %s' % (band, text))
    lines.append('  对不上（next_fire_at 已是下一次，倒推不出来）：%d 条' % stats['mismatch'])
    lines.append('  null（一次性 FIRED 后 next_fire_at 清空，上面两把都套不上）：%d 条%s' % (
        len(stats['null']), '——库里没有' if not stats['null'] else ''))
    for moment, _pid, plan in sorted(stats['null'], key=lambda triple: triple[0], reverse=True)[:SAMPLES]:
        due = restore_due(plan.get('rule') or {}, plan, moment, offset)
        if due:
            gap = ('晚 %s' % mmss(due[1])) if due[1] >= 0 else ('早 %s' % mmss(-due[1]))
            tail = '；应响 %s ⇒ %s（单列，未进档）' % (due[0], gap)
        else:
            tail = '；应响按 rule 复原不了（单列）'
        lines.append('    - %s %s 派发%s' % (stamp(moment, offset), plan_label(plan), tail))
    if stats['no_plan'] or stats['no_moment']:
        lines.append('  判不了：计划行找不到 %d 条、时刻读不出 %d 条（不混进上面任何一档）' % (
            stats['no_plan'], stats['no_moment']))
    lines.append('  · 软肋：真晚到时「下一次」是按当下重算的，>5 分钟那档可能量不到——量不到只说明这一趟没读到')
    return lines


def delay_face(window, offset):
    """延迟分档单独占一个读数面：读不到就明说，不许长得像四档全 0。"""
    try:
        reading = delay_reading(window)
    except Exception as exc:                       # noqa: BLE001 一面读不到只影响这一面
        return face('schedule 延迟分档', '计划延迟分档（两把尺并排）', read=False,
                    error='%s: %s' % (type(exc).__name__, exc), cls='C'), []
    return face('schedule 延迟分档', '计划延迟分档（plans ↔ schedule.dispatched）', cls='C'), \
        delay_lines(window, reading)


# ────────────────────────────── 窗口 ──────────────────────────────

class Window(dict):
    """`dbread.local_window` 给的文本区间（Mongo 过滤直接用），另挂本地起止与现读偏移（比较、渲染用）。"""


def build_window(since, until, hours, offset, start_local, end_local, local_now=None):
    got = dbread.local_window(start_local.strftime('%Y-%m-%d %H:%M:%S'),
                              end_local.strftime('%Y-%m-%d %H:%M:%S'))
    out = Window(got)
    out['$bound'] = {key: got[key] for key in ('$gte', '$lt') if key in got}   # 查询只拿这两端：Window 上挂的私有键喂给 Mongo 会报 InvalidDocument
    out['offset'] = offset
    out['start'] = start_local.replace(tzinfo=timezone.utc) - offset
    out['end'] = end_local.replace(tzinfo=timezone.utc) - offset
    out['local_start'] = start_local
    out['local_end'] = end_local
    now_moment = parse_moment(local_now)
    out['local_now'] = ((now_moment.replace(tzinfo=timezone.utc) - offset).replace(tzinfo=None)
                        if now_moment else end_local)
    out['text'] = '%s → %s' % (start_local.strftime('%Y-%m-%d %H:%M'), end_local.strftime('%Y-%m-%d %H:%M'))
    out['how'] = ('--since/--until 本地钟点' if (since or until) else '最近 %g 小时（本地钟面）' % hours)
    return out


def parse_clock(text):
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(text).strip(), fmt)
        except ValueError:
            continue
    return None


# ────────────────────────────── 输出 ──────────────────────────────

GROUPS = ('A 带报错行的失败', 'B 静默没跑（只有执行记录能证明缺席）', 'D 计划没排上／晚交到',
          'C 对照（不计入失败总数）')
GROUP_KEYS = ('A', 'B', 'D', 'C')


def render(faces, pairing, offset, title, dedup=None, retention=None, delay=None):
    counts = {key: 0 for key in GROUP_KEYS}
    rows = {key: [] for key in GROUP_KEYS}
    for face_row in faces:
        for entry in face_row['items']:
            cls = entry.get('cls') or face_row.get('cls') or 'A'
            counts[cls] = counts.get(cls, 0) + entry['n']
            rows.setdefault(cls, []).append((face_row['face'], entry))
    unread = [face_row for face_row in faces if not face_row['read']]
    records = counts['A'] + counts['B'] + counts['D']
    if records == 0 and not unread:
        return ['0']
    twins = {}
    for pair in (dedup or {}).get('pairs', []):
        twins[pair['a']] = (pair['b'], pair['dup'])
        twins.setdefault(pair['b'], (pair['a'], pair['dup']))
    lines = [title,
             '时刻配对（现读，不背偏移）：%s ／ %s ⇒ 偏移 UTC%+d:%02d（同一个 UTC 换 +8 是 %s）' % (
                 pairing[0], pairing[1], int(offset.total_seconds() // 3600),
                 abs(int(offset.total_seconds() % 3600)) // 60, shift_text(pairing[1], timedelta(hours=8))),
             '读数面 %d：已读 %d／没读到 %d%s' % (
                 len(faces), len(faces) - len(unread), len(unread),
                 '' if not unread else '（' + '、'.join('%s：%s' % (one['face'], snippet(one['error'], 70))
                                                       for one in unread) + '）')]
    lines += list(retention or [])
    lines.append('合计：系统级失败 %d 条（A %d＋B %d＋计划排期 %d）；对照 %d 条' % (
        records, counts['A'], counts['B'], counts['D'], counts['C']))
    lines += dedup_lines(dedup, records)
    for label, key in zip(GROUPS, GROUP_KEYS):
        live = [pair for pair in rows[key] if pair[1]['n'] > 0]
        if not live:
            lines.append('■ 组 %s：0 条%s' % (
                label, '（库里没有；下面逐型列出，写着读不到的那一型是没读到、不是没有）' if rows[key]
                else '（库里没有——名册里的型在这一窗一条都没数到）'))
            for _face_name, entry in rows[key]:
                lines.append('  %s  n=%d  %s' % (entry['group'], entry['n'], entry['why']))
            continue
        lines.append('■ 组 %s：%d 条、%d 型' % (label, counts[key], len(live)))
        for _face_name, entry in sorted(rows[key], key=lambda pair: -pair[1]['n']):
            lines.append('  %s  n=%d  首 %s  末 %s' % (entry['group'], entry['n'],
                                                       stamp(entry['first'], offset) if entry['first'] else '-',
                                                       stamp(entry['last'], offset) if entry['last'] else '-'))
            if entry.get('why'):
                lines.append('    · %s' % entry['why'])
            twin = twins.get(entry['group'])
            if twin and twin[1]:
                lines.append('    · 双面：与 %s 同一批事件 %d 条（同一件事在两面各记一次，不相加）'
                             % (twin[0], twin[1]))
            for sample in entry['samples'][:SAMPLES]:
                lines.append('    - %s' % sample)
    lines += list(delay or [])
    return lines



def shift_text(utc_text, delta):
    moment = parse_moment(utc_text)
    return (moment + delta).strftime('%Y-%m-%d %H:%M') if moment else '?'


# ────────────────────────────── 自检（不连库、不读盘）──────────────────────────────

def selfcheck():
    """纯逻辑自检：分类表不重叠、时刻配对与换算、重启行读法、日志续行不另计、样例形状、全零形状。"""
    results = []

    def check(name, ok, detail=''):
        results.append((name, bool(ok), detail))

    check('audit_groups_disjoint', not (set(AUDIT_WITH_ERROR) & set(AUDIT_SILENT)),
          str(sorted(set(AUDIT_WITH_ERROR) & set(AUDIT_SILENT))))
    check('both_failure_kinds_present', bool(AUDIT_WITH_ERROR and AUDIT_SILENT))
    check('contrast_not_in_failure_sets',
          not (set(AUDIT_CONTRAST) & (set(AUDIT_WITH_ERROR) | set(AUDIT_SILENT))))
    check('missed_causes_cover_code', {'clash', 'timeout', 'unanswered', 'cut', 'error'} <= set(MISSING_CAUSES))
    check('stop_failures_exclude_planned', 'planned' not in STOP_FAILURES and 'worker_restart' not in STOP_FAILURES)
    check('restart_planned_set_named', {'published', 'settings'} <= RESTART_PLANNED)
    check('silent_file_face_exists', 'provider.request 无响应' in REPORT_SILENT)
    check('crash_faces_present', 'host.task_interrupted' in REPORT_FAILURES and 'provider.error' in REPORT_FAILURES)

    offset, pairing = derive_offset('2026-11-07 12:07', datetime(2026, 11, 6, 23, 7, tzinfo=timezone.utc))
    check('offset_derived_from_pair', offset == timedelta(hours=13), '%s %s' % (offset, pairing))
    check('offset_not_assumed_plus8', offset != timedelta(hours=8))
    check('utc_renders_local', local_text('2026-11-06T21:49:11.357877+00:00', offset) == '2026-11-07 10:49:11',
          local_text('2026-11-06T21:49:11.357877+00:00', offset))
    check('z_suffix_parses', local_text('2026-11-06T21:49:11Z', offset) == '2026-11-07 10:49:11')
    check('datetime_moment_parses',
          local_text(datetime(2026, 11, 6, 21, 49, 11, tzinfo=timezone.utc), offset) == '2026-11-07 10:49:11')
    check('unreadable_moment_is_question', local_text('不是时刻', offset) == '?')
    check('ns_moment_is_2026', ns_moment(1_794_085_202_551_706_500).year >= 2026, str(ns_moment(1_794_085_202_551_706_500)))
    check('pairing_keeps_both_raw', pairing == ('2026-11-07 12:07', '2026-11-06T23:07:00+00:00'), str(pairing))

    check('restart_line_flags_non_running', restart_line('{"down_at":"2026-11-08T23:44:00Z","result":"failed",'
                                                         '"attempts":[{"rung":0,"ok":false}]}')[1] != '')
    check('restart_line_flags_failed_attempt', '没起来' in restart_line(
        '{"down_at":"2026-11-08T23:44:00Z","result":"running","attempts":[{"rung":0,"ok":false},'
        '{"rung":1,"ok":true}]}')[1])
    check('restart_line_ignores_healthy', restart_line('{"down_at":"2026-11-08T23:44:00Z","result":"running",'
                                                       '"attempts":[{"rung":0,"ok":true}]}')[1] == '')
    check('restart_line_broken_json_quiet', restart_line('{不是json')[1] == '')
    check('worker_line_nonzero_exit', 'exited' in worker_line('{"at":"2026-11-02T21:46:25.216Z","reason":'
                                     '"worker failed: Error: Asuna business worker exited (1)"}')[1])
    check('worker_line_planned_ignored', worker_line('{"at":"2026-11-04T00:04:48Z",'
                                                    '"reason":"worker asked: published-worker"}')[1] == '')

    log = ('2026-11-09T06:53:04.294Z warn [asuna-cognition-core] Exception in thread x\n'
           'Traceback (most recent call last):\n'
           'ConnectionAbortedError: [WinError 10053] broke\n'
           '2026-11-09T06:54:04.000Z info [asuna-cognition-core] all fine\n'
           '2026-11-11T06:54:04.000Z error [asuna-cognition-core] 窗口外\n')
    hits = count_log_lines(log, datetime(2026, 11, 9, tzinfo=timezone.utc),
                           datetime(2026, 11, 10, tzinfo=timezone.utc))
    check('log_one_exception_one_incident', len(hits) == 1, '数到 %d 件事（一次异常十几行不该数十几条）' % len(hits))
    check('log_incident_line_count', bool(hits) and hits[0]['lines'] == 3, str(hits and hits[0]['lines']))
    check('log_incident_tail_is_exception', bool(hits) and 'ConnectionAborted' in hits[0]['tail'],
          str(hits and hits[0]['tail']))
    check('log_respects_window', bool(hits) and hits[0]['first'] < datetime(2026, 11, 10, tzinfo=timezone.utc))
    two = count_log_lines(log + '2026-11-09T06:55:04.000Z warn [x] 又一次\n',
                          datetime(2026, 11, 9, tzinfo=timezone.utc), datetime(2026, 11, 10, tzinfo=timezone.utc))
    check('log_new_incident_after_gap', len(two) == 2, '数到 %d 件事（间隔后的新异常另起一件）' % len(two))
    reset_log = ('2026-11-09T06:53:04.294Z error [asuna-host] Exception in thread http\n'
                 '  File "x/channels.py", line 1, in handle\n'
                 '    self.wfile.write(data)\n'
                 'ConnectionResetError: [WinError 10054] reset\n'
                 '2026-11-09T06:54:04.000Z info [asuna-host] fine\n')
    reset_hits = count_log_lines(reset_log, datetime(2026, 11, 9, tzinfo=timezone.utc),
                                 datetime(2026, 11, 10, tzinfo=timezone.utc))
    gate_rows = [{'occurred_at': '2026-11-11T10:00:00', 'payload': {'problem': 'unsent'}},
                 {'occurred_at': '2026-11-11T11:00:00', 'payload': {'problem': '这回合还没写心里话：先调用 think'}},
                 {'occurred_at': '2026-11-11T12:00:00', 'payload': {'problem': '别的原因'}}]
    gate_items = split_gate_refusals(gate_rows, [item('turn.rejected', 'x', 3, None, None, [], 'A')], timedelta(hours=13))
    check('gate_refusal_split_to_contrast', [(one['group'], one['n'], one['cls']) for one in gate_items]
          == [('turn.rejected', 1, 'A'), ('turn.rejected[闸拒型（噪声）]', 2, 'C')], str(gate_items))
    check('gate_refusal_unknown_stays_in_A', split_gate_refusals(gate_rows[2:], [item('turn.rejected', 'x', 1)], timedelta(0))
          [0]['n'] == 1)
    check('peer_disconnect_needs_all_three', len(reset_hits) == 1 and is_peer_disconnect(reset_hits[0])
          and not is_peer_disconnect(hits[0]), str([(is_peer_disconnect(one)) for one in reset_hits + hits]))
    check('running_cutoff_is_utc_iso', running_cutoff({'start': datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)}, 6)
          == '2026-11-11T05:00:00', running_cutoff({'start': datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)}, 6))
    check('offset_snapped_to_quarter_hour', derive_offset('2026-11-09 22:34',
          datetime(2026, 11, 9, 9, 34, 52, tzinfo=timezone.utc))[0] == timedelta(hours=13))
    check('stamp_adds_offset_to_datetime', stamp(datetime(2026, 11, 6, 21, 49, 11, tzinfo=timezone.utc),
          timedelta(hours=13)) == '2026-11-07 10:49:11',
          stamp(datetime(2026, 11, 6, 21, 49, 11, tzinfo=timezone.utc), timedelta(hours=13)))

    check('snippet_single_line', '\n' not in snippet('a\n  b\t<c:\\path\\x> 198.51.100.7:1234 ' + 'x' * 300))
    check('snippet_caps', len(snippet('y' * 900)) <= SAMPLE_CHARS)
    check('snippet_redacts_address', '198.51.100.7' not in snippet('见 198.51.100.7 那台'))
    check('snippet_redacts_path', 'workspace' not in snippet('在 C:\\workspace\\a\\b.py 里'))
    check('audit_snippet_prefers_error', 'error=' in audit_snippet({'error': 'boom', 'count': 3}))
    check('audit_snippet_traceback_tail', 'ZeroDivision' in audit_snippet(
        {'traceback': 'Traceback (most recent call last):\n  x\nZeroDivisionError: 0'}))

    pair = ('2026-11-09 22:00', '2026-11-09T09:00:00+00:00')
    empty = [face(name, '', [], read=True, cls=cls) for name, cls in
             (('audit_events/with_error', 'A'), ('audit_events/silent', 'B'), ('audit_events/contrast', 'C'),
              ('missed_looks', 'B'), ('host_stops', 'B'), ('lane_faults', 'A'), ('tasks', 'A'),
              ('role_tool.refused', 'C'), ('reports', 'A'), ('host.log', 'A'), ('restart', 'A'))]
    check('all_zero_prints_one_line', render(empty, pair, timedelta(hours=13), '标题') == ['0'],
          str(render(empty, pair, timedelta(hours=13), '标题')))
    hole = empty + [face('host.log', '', read=False, error='读不到')]
    out2 = render(hole, pair, timedelta(hours=13), '标题')
    check('zero_with_unread_not_bare_zero', out2 != ['0'] and any('没读到' in line for line in out2), str(out2[:2]))

    mixed = empty[:1] + [
        face('audit_events/with_error', '', [item('attend.failed', '关口没判出来', 2,
                                                  '2026-11-06T21:46:58+00:00', '2026-11-06T21:49:11+00:00',
                                                  ['一', '二', '三', '四'], 'A')], cls='A'),
        face('missed_looks', '', [item('missed_looks[error]', '程序出错', 3, '2026-11-06T21:46:58+00:00',
                                       '2026-11-06T21:49:11+00:00', [], 'B')], cls='B'),
        face('role_tool.refused', '', [item('role_tool_refused', '对照', 9, None, None, [], 'C')], cls='C')]
    out3 = '\n'.join(render(mixed, pair, timedelta(hours=13), '标题'))
    check('group_line_has_count_and_edges', 'n=2' in out3 and '2026-11-07 10:46:58' in out3 and '10:49:11' in out3)
    check('silent_group_separate', '■ 组 B 静默没跑' in out3 and 'missed_looks[error]  n=3' in out3)
    check('contrast_not_in_total', '合计：系统级失败 5 条（A 2＋B 3＋计划排期 0）；对照 9 条' in out3,
          next((line for line in out3.splitlines() if line.startswith('合计：')), ''))
    check('schedule_group_printed', any(line.startswith('■ 组 D') and '库里没有' in line
                                        for line in out3.splitlines()))
    check('samples_capped_at_three', out3.count('\n    - ') <= SAMPLES, str(out3.count('\n    - ')))
    check('pairing_line_shows_both_offsets', 'UTC+13:00' in out3 and '换 +8' in out3)
    check('parse_clock_shapes', all(parse_clock(t) for t in ('2026-11-04 21:10:00', '2026-11-07 13:07', '2026-11-07')))
    check('parse_clock_rejects_junk', parse_clock('昨天下午') is None)
    check('moment_from_head_only', _moment_of('{"seq":1,"type":"provider.error","payload":{},"prev_hash":"a",'
          '"time_ns": 1_794_085_202_551_706_500', '') is not None)
    check('moment_from_tail_when_body_is_huge',
          _moment_of('{"seq":1,"type":"provider.response","payload":{"call_id":"c","status_code":200,"body":{',
                     '"time_ns": 1_794_085_202_551_706_500, "event_hash": "be"') is not None)
    check('moment_none_when_nowhere', _moment_of('{"seq":1,"body":{', '{"x":1}') is None)
    has_created = task_moment({'created_at': '2026-11-05T00:00:00+00:00'})
    check('task_moment_prefers_created_at', has_created[1] == 'created_at' and has_created[0] is not None)
    lease_only = task_moment({'lease_expires_at': 1794085202.5})
    check('task_moment_falls_back_to_lease', lease_only[1] == 'lease_expires_at' and lease_only[0] is not None,
          str(lease_only))
    check('task_moment_none_when_no_time', task_moment({'state': 'BLOCKED'})[0] is None)

    # ── 格③：组 D 名册五个 type、与别组不重叠；名册外的 type 一行都数不到 ──
    others = set(AUDIT_WITH_ERROR) | set(AUDIT_SILENT) | set(AUDIT_CONTRAST)
    check('roster_schedule_five_types',
          set(AUDIT_SCHEDULE) == {'schedule.fault_told', 'schedule.fault_unreported', 'schedule.handoff_late',
                                  'schedule.handoff_failed', 'schedule.handoff_watch_failed'}
          and not (set(AUDIT_SCHEDULE) & others),
          str(sorted(set(AUDIT_SCHEDULE))))
    check('audit_groups_disjoint_with_schedule', not (set(AUDIT_SCHEDULE) & others))
    roster = dict(AUDIT_SCHEDULE)
    roster.update(AUDIT_WITH_ERROR)
    built = audit_items([{'_id': kind, 'n': 3, 'first': '2026-11-06T21:49:11+00:00',
                          'last': '2026-11-06T21:49:11+00:00'}
                         for kind in ('schedule.handoff_late', 'attend.a_brand_new_type', 'rhythm.watch_failed')],
                        {}, roster, 'D')
    check('unlisted_type_counts_no_row',
          [one['group'] for one in built] == ['schedule.handoff_late', 'rhythm.watch_failed'],
          '名册外那型 ' + str([one['group'] for one in built if one['group'].startswith('attend.a')]))

    # ── 格①：同一事件同落 A／B 两面——合计（记录数）与按事件去重（件数）分两行报 ──
    pair_84 = {'a': 'attend.failed', 'b': 'missed_looks[error]', 'a_n': 84, 'b_n': 84,
               'a_u': 84, 'b_u': 84, 'dup': 84}
    twin = [face('audit_events/with_error', '', [item('attend.failed', '关口没判出来', 84, None, None)], cls='A'),
            face('missed_looks', '', [item('missed_looks[error]', '程序出错', 84, None, None)], cls='B')]
    out_twin = '\n'.join(render(twin, ('2026-11-07 12:07', '2026-11-06T23:07:00+00:00'),
                                 timedelta(0), '标题', dedup={'lost': 84, 'pairs': [pair_84], 'unknown': []}))
    check('dedup_pair_declared', OVERLAP_PAIRS == (('attend.failed', 'missed_looks', 'error'),),
          str(OVERLAP_PAIRS))
    check('dedup_separates_records_and_events',
          '合计：系统级失败 168 条（A 84＋B 84＋计划排期 0）；对照 0 条' in out_twin
          and '按事件去重：系统级失败 84 件（记录 168 条 − 双面重复 84 条）' in out_twin
          and '双面：与 missed_looks[error] 同一批事件 84 条（同一件事在两面各记一次，不相加）' in out_twin,
          out_twin.splitlines()[4] if len(out_twin.splitlines()) > 4 else '')
    check('dedup_cant_judge_is_not_zero',
          '判不了' in '\n'.join(render(twin, ('a', 'b'), timedelta(0), '标题',
                                        dedup={'lost': 0, 'pairs': [], 'unknown': ['missed_looks 查挂了']})))

    saved_dbread = globals()['dbread']

    class _Boom(object):
        def count(self, *args, **kwargs):
            raise RuntimeError('库连不上')

    globals()['dbread'] = _Boom()
    broken = dedup_quiet({'$bound': {}, 'offset': timedelta(0)})
    globals()['dbread'] = saved_dbread
    broken_text = '\n'.join(dedup_lines(broken, 0))
    check('dedup_failure_reason_shown',
          broken['lost'] == 0 and not broken['pairs'] and any('库连不上' in one for one in broken['unknown'])
          and '判不了' in broken_text and '库连不上' in broken_text, str(broken))

    # ── 格②：窗口超出保留期 → 打「可能数少（超出保留期）」；在期内也打一行说明这一趟查过 ──
    now_local = datetime(2026, 11, 10, 12, 0)
    wide = {'local_start': now_local - timedelta(days=9), 'local_end': now_local, 'local_now': now_local,
            'start': now_local - timedelta(days=9), 'end': now_local, 'offset': timedelta(0)}
    near = dict(wide, local_start=now_local - timedelta(hours=6), start=now_local - timedelta(hours=6))
    log_face = face('host.log', '', [], cls='A', coverage={'floor': now_local - timedelta(hours=2),
                                                           'truncated': True, 'bytes': 12345})
    out_wide = '\n'.join(retention_lines(wide, [log_face], timedelta(0)))
    check('retention_flags_beyond_horizon',
          '可能数少（超出保留期）' in out_wide and 'missed_looks' in out_wide
          and 'audit_events' in out_wide and 'host.log' in out_wide, out_wide.replace('\n', ' ⧸ ')[:220])
    out_near = '\n'.join(retention_lines(near, [], timedelta(0)))
    check('retention_quiet_inside_horizon', '可能数少' not in out_near and '在期内' in out_near,
          out_near[:160])
    check('retention_horizons_declared',
          (MISSED_KEPT_DAYS, AUDIT_KEPT_DAYS, LANE_KEPT_DAYS, TAIL_MIB) == (7, 30, 30, 8),
          '%s %s %s %s' % (MISSED_KEPT_DAYS, AUDIT_KEPT_DAYS, LANE_KEPT_DAYS, TAIL_MIB))

    # ── 格④：延迟分档——循环计划末次派发进倒推档；一次性 FIRED 单列 null；推过了的单列对不上 ──
    fake_dispatched = [
        {'stream_id': 'plan-loop-1', 'occurred_at': '2026-11-10T07:00:30+00:00'},
        {'stream_id': 'plan-loop-2', 'occurred_at': '2026-11-10T07:01:40+00:00'},
        {'stream_id': 'plan-loop-3', 'occurred_at': '2026-11-10T07:06:00+00:00'},
        {'stream_id': 'plan-null-1', 'occurred_at': '2026-11-10T05:43:02.458928+00:00'},
        {'stream_id': 'plan-old-1', 'occurred_at': '2026-11-09T07:00:00+00:00'},
        {'stream_id': 'plan-gone-1', 'occurred_at': '2026-11-10T07:10:00+00:00'},
    ]
    fake_plans = {
        'plan-loop-1': {'_id': 'plan-loop-1', 'intent': '每五分钟那一拍', 'rule': {'every_seconds': 300},
                        'next_fire_at': '2026-11-10T07:05:00+00:00'},
        'plan-loop-2': {'_id': 'plan-loop-2', 'intent': '两分钟那一拍', 'rule': {'every_seconds': 200},
                        'next_fire_at': '2026-11-10T07:03:20+00:00'},
        'plan-loop-3': {'_id': 'plan-loop-3', 'intent': '每天那一拍', 'rule': {'clock': {'time': '04:00'}},
                        'next_fire_at': '2026-11-11T07:00:00+00:00'},
        'plan-null-1': {'_id': 'plan-null-1', 'intent': '一次性那一拍', 'created_at': '2026-11-10T05:12:08+00:00',
                        'rule': {'at': '2026-11-10T05:40+00:00', 'at_utc': True}, 'next_fire_at': None},
        'plan-old-1': {'_id': 'plan-old-1', 'intent': '已推两次的循环', 'rule': {'every_seconds': 300},
                       'next_fire_at': '2026-11-10T07:00:00+00:00'},
    }
    plain = {'offset': timedelta(0), '$bound': {}}
    reading = delay_reading(plain, rows=fake_dispatched, plan_of=lambda pid: fake_plans.get(pid))
    out_delay = '\n'.join(delay_lines(plain, reading))

    def band_n(bands, band):
        return (bands.get(band) or {'n': 0})['n']

    check('delay_bands_split', band_n(reading['inferred'], '≤1 分钟') == 1
          and band_n(reading['inferred'], '1–2 分钟') == 1
          and band_n(reading['inferred'], '>2 分钟') == 1
          and reading['inferred']['>2 分钟']['over5'] == 1, out_delay.splitlines()[3])
    check('delay_null_mismatch_and_missing_separate',
          len(reading['stats']['null']) == 1 and reading['stats']['mismatch'] == 1
          and reading['stats']['no_plan'] == 1, str(reading['stats']))
    check('delay_one_shot_delay_recomputed', '3 分 2.46 秒' in out_delay and '未进档' in out_delay,
          next((line for line in out_delay.splitlines() if 'null' in line), ''))
    check('delay_ruler_is_not_handoff_late', '不是一把尺' in out_delay)
    check('delay_soft_spot_written', '量不到' in out_delay)
    check('delay_empty_band_says_library_empty', '库里没有' in out_delay)
    check('delay_period_shape', plan_period({'every_seconds': 300}) == 300
          and plan_period({'clock': {'time': '04:00'}}) == 86400
          and plan_period({'at': '2026-11-10T05:40+00:00'}) is None)
    saved_reader = globals()['delay_reading']
    globals()['delay_reading'] = lambda _window: (_ for _ in ()).throw(RuntimeError('这一面读挂了'))
    bad_row, bad_lines = delay_face(plain, timedelta(0))
    globals()['delay_reading'] = saved_reader
    check('delay_face_unread_says_so', bad_row['read'] is False and '读挂了' in bad_row['error']
          and not bad_lines, str(bad_row.get('error')))

    # ── 通用判据：数出 0 只报「库里没有」，任何一行都不许写「没发生过」 ──
    check('zero_words_never_never_happened', '没发生过' not in out3 + out_twin + out_delay + out_wide)
    check('zero_group_says_library_empty', any(line.startswith('■ 组') and '0 条' in line
                                               and '库里没有' in line for line in out3.splitlines()),
          next((line for line in out3.splitlines() if line.startswith('■ 组 D')), ''))
    return results


# ────────────────────────────── 主流程 ──────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description='DSH 级（系统级）失败扫描：带报错行的拒绝＋静默没跑，按类型分组')
    parser.add_argument('--hours', type=float, default=24.0, help='窗口长度（小时），默认最近 24 小时')
    parser.add_argument('--since', help='本地钟点起点，如 "2026-11-04 21:10:00"（给了就不用 --hours）')
    parser.add_argument('--until', help='本地钟点终点（不给就用现在）')
    parser.add_argument('--stale-hours', type=float, default=6.0, help='RUNNING 超几小时算未回执，默认 6')
    parser.add_argument('--data', help='数据根（默认 asuna.config.DATA）')
    parser.add_argument('--no-files', action='store_true', help='只查库那几面，不读数据根下的文件')
    parser.add_argument('--selfcheck', action='store_true', help='不连库不读盘的纯逻辑自检')
    args = parser.parse_args(argv)

    if args.selfcheck:
        results = selfcheck()
        failed = [name for name, ok, _ in results if not ok]
        for name, ok, detail in results:
            if not ok:
                print('FAIL %s  <- %s' % (name, detail))
        print('%d/%d 通过' % (len(results) - len(failed), len(results))
              + ('，失败：%s' % ', '.join(failed) if failed else ''))
        return 1 if failed else 0

    local_now = dbread.now()
    offset, pairing = derive_offset(local_now, datetime.now(timezone.utc))
    end_moment = parse_moment(local_now)
    end_local = (end_moment.replace(tzinfo=None) if end_moment
                 else datetime.now(timezone.utc).replace(tzinfo=None) + offset)
    end_local = end_local.replace(second=0, microsecond=0)
    start_local = parse_clock(args.since) or (end_local - timedelta(hours=args.hours))
    end_local = parse_clock(args.until) or end_local
    if end_local <= start_local:
        print('窗口不对：终点 %s 不晚于起点 %s' % (end_local, start_local))
        return 2
    window = build_window(args.since, args.until, args.hours, offset, start_local, end_local)

    faces = [_try(lambda types=types, note=note, name=name, cls=cls: audit_face(window, types, note, name, cls),
                  name, note, cls)
             for name, types, note, cls in (
                 ('audit_events/with_error', AUDIT_WITH_ERROR, '带报错行的审计失败行', 'A'),
                 ('audit_events/silent', AUDIT_SILENT, '该跑没跑的审计行', 'B'),
                 ('audit_events/schedule', AUDIT_SCHEDULE, '计划没排上／晚交到（schedule.*）', 'D'),
                 ('audit_events/contrast', AUDIT_CONTRAST, '降级与伴生句（对照）', 'C'))]
    faces.append(_try(lambda: missed_face(window), 'missed_looks', '关口该判没判', 'B'))
    faces.append(_try(lambda: stop_face(window), 'host_stops', '宿主／worker 停过', 'B'))
    faces.append(_try(lambda: lane_face(window), 'lane_faults', '通道层故障小时表', 'A'))
    faces.append(_try(lambda: task_face(window, args.stale_hours), 'tasks', '任务级失败与未回执', 'A'))
    faces.append(_try(lambda: role_tool_face(window), 'role_tool.refused', '我自己那一侧的拒（对照）', 'C'))
    if not args.no_files:
        root = args.data or asuna_config.DATA
        faces.append(_try(lambda: report_face(root, window), 'reports', '宿主事件文件里的上游失败与无响应', 'A'))
        faces.append(_try(lambda: host_log_face(root, window), 'host.log', '宿主控制台的异常行', 'A'))
        faces.append(_try(lambda: restart_face(root, window), 'restart', '进程级：非零退出、起不来', 'A'))
    delay_row, delay_text = delay_face(window, offset)
    faces.append(delay_row)
    if not any(one['read'] for one in faces):
        print('判不了：一面都没读到（' + '；'.join(str(one['error'])[:70] for one in faces) + '）')
        return 2
    for line in render(faces, pairing, offset,
                       'DSH 失败扫描 · 窗口 本地 %s（%s）' % (window['text'], window['how']),
                       dedup=dedup_quiet(window),
                       retention=retention_lines(window, faces, offset),
                       delay=delay_text):
        print(line)
    return 0


def _try(maker, name, note, cls):
    """一面读数读不到只标这一面没读到（附真原因），不整趟崩——也不许把没读到印成 0 条。"""
    try:
        return maker()
    except Exception as exc:                       # noqa: BLE001 一面读不到只影响这一面
        return face(name, note, read=False, error='%s: %s' % (type(exc).__name__, exc), cls=cls)


if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8')
    sys.exit(main())
