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
LOG_LEVEL = re.compile(r'^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(\w+)')
LOG_BAD = re.compile(r'\b(?:warn|warning|error|fatal|critical)\b|Traceback|Exception|Error:|\bexited\b', re.I)
LOG_LEVELS = ('warn', 'warning', 'error', 'fatal', 'critical')


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

def face(name, note, items=None, read=True, error='', cls='A'):
    """一面读数：面名、说明、分组条目、读没读到（附真原因）、这一面的默认归类（A／B／C）。"""
    return {'face': name, 'note': note, 'items': items or [], 'read': read, 'error': error, 'cls': cls}


def item(group, why, count, first=None, last=None, samples=None, cls=None):
    return {'group': group, 'why': why, 'n': int(count or 0), 'first': first, 'last': last,
            'samples': list(samples or []), 'cls': cls}


def audit_face(window, types, note, name, cls):
    """audit_events 的一类 type：按 type 分组数条数、首末时刻、各型样例行（窗口内最早的几条）。"""
    rows = dbread.aggregate('audit_events',
                            [{'$match': {'type': {'$in': sorted(types)}, 'occurred_at': window['$bound']}},
                             {'$group': {'_id': '$type', 'n': {'$sum': 1}, 'first': {'$min': '$occurred_at'},
                                         'last': {'$max': '$occurred_at'}}},
                             {'$sort': {'n': -1}}, {'$limit': 200}], limit=200)['rows']
    items = []
    for row in rows:
        kind = row.get('_id')
        found = dbread.find('audit_events', {'type': kind, 'occurred_at': window['$bound']},
                            fields=['occurred_at', 'stream_id', 'payload'], sort=[('occurred_at', 1)], limit=SAMPLES)
        samples = ['%s %s %s' % (local_text(one.get('occurred_at'), window['offset']),
                                 short_id(one.get('stream_id')), audit_snippet(one.get('payload')))
                   for one in found['rows']]
        items.append(item(kind, types.get(kind, ''), row.get('n'), row.get('first'), row.get('last'), samples, cls))
    return face(name, note, items, cls=cls)


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
    stuck, no_time = [], []
    for row in dbread.find('tasks', {'state': {'$in': ['BLOCKED', 'UNKNOWN']}},
                           fields=['state', 'created_at', 'lease_expires_at', 'failure_type'],
                           sort=[('created_at', 1)], limit=500)['rows']:
        moment, source = task_moment(row)
        if moment is None:
            no_time.append(row)
        elif window['start'] <= moment < window['end']:
            stuck.append((moment, source, row))
    if stuck:
        stuck.sort(key=lambda triple: triple[0])
        items.append(item('tasks.state[BLOCKED／UNKNOWN]', '卡住的任务（时刻按 created_at，缺则按 lease_expires_at）',
                          len(stuck), stuck[0][0], stuck[-1][0],
                          ['%s state=%s%s %s' % (stamp(moment, offset), row.get('state'),
                                                 '' if source == 'created_at' else '（时刻取 lease_expires_at）',
                                                 'failure_type=%s' % row.get('failure_type')
                                                 if row.get('failure_type') else '')
                           for moment, source, row in stuck[:SAMPLES]], 'B'))
    if no_time:
        items.append(item('tasks.state[BLOCKED／UNKNOWN 判不了]', '这些行既没 created_at 也没 lease_expires_at：'
                          '落不进窗口，单列不计数（n 列的是条数，时刻栏写 -）', len(no_time), None, None,
                          ['state=%s failure_type=%s' % (row.get('state'), row.get('failure_type'))
                           for row in no_time[:SAMPLES]], 'B'))
    cutoff = (window['local_start'] - timedelta(hours=stale_hours)).strftime('%Y-%m-%d %H:%M:%S')
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
    hits = count_log_lines(raw.decode('utf-8', errors='replace'), window['start'], window['end'])
    items = []
    if hits:
        items.append(item('host.log[异常事件]', '宿主控制台带时刻的异常（连续坏行并成一件事）', len(hits),
                          hits[0]['first'], hits[-1]['last'],
                          [snippet('%s 〔连续 %d 行〕 %s　末行：%s' % (stamp(one['first'], offset), one['lines'],
                                                                 one['head'], one['tail'])) for one in hits[:SAMPLES]],
                          'A'))
    return face('host.log', '宿主控制台日志里带时刻的异常行', items, cls='A')


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
                continue
            current = {'first': moment, 'last': moment, 'lines': 1, 'head': body, 'tail': body}
            out.append(current)
        elif current is not None:
            # 无时刻的行是上一条异常的续行（traceback 的 File／raise 那些），不算新事件也不结束这件事；
            # 只有带时刻的健康行才把这件事收尾。
            current['lines'] += 1
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


# ────────────────────────────── 窗口 ──────────────────────────────

class Window(dict):
    """`dbread.local_window` 给的文本区间（Mongo 过滤直接用），另挂本地起止与现读偏移（比较、渲染用）。"""


def build_window(since, until, hours, offset, start_local, end_local):
    got = dbread.local_window(start_local.strftime('%Y-%m-%d %H:%M:%S'),
                              end_local.strftime('%Y-%m-%d %H:%M:%S'))
    out = Window(got)
    out['$bound'] = {key: got[key] for key in ('$gte', '$lt') if key in got}   # 查询只拿这两端：Window 上挂的私有键喂给 Mongo 会报 InvalidDocument
    out['offset'] = offset
    out['start'] = start_local.replace(tzinfo=timezone.utc) - offset
    out['end'] = end_local.replace(tzinfo=timezone.utc) - offset
    out['local_start'] = start_local
    out['local_end'] = end_local
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

GROUPS = ('A 带报错行的失败', 'B 静默没跑（只有执行记录能证明缺席）', 'C 对照（不计入失败总数）')


def render(faces, pairing, offset, title):
    counts = {'A': 0, 'B': 0, 'C': 0}
    rows = {'A': [], 'B': [], 'C': []}
    for face_row in faces:
        for entry in face_row['items']:
            cls = entry.get('cls') or face_row.get('cls') or 'A'
            counts[cls] += entry['n']
            rows[cls].append((face_row['face'], entry))
    unread = [face_row for face_row in faces if not face_row['read']]
    if counts['A'] + counts['B'] == 0 and not unread:
        return ['0']
    lines = [title,
             '时刻配对（现读，不背偏移）：%s ／ %s ⇒ 偏移 UTC%+d:%02d（同一个 UTC 换 +8 是 %s）' % (
                 pairing[0], pairing[1], int(offset.total_seconds() // 3600),
                 abs(int(offset.total_seconds() % 3600)) // 60, shift_text(pairing[1], timedelta(hours=8))),
             '读数面 %d：已读 %d／没读到 %d%s' % (
                 len(faces), len(faces) - len(unread), len(unread),
                 '' if not unread else '（' + '、'.join('%s：%s' % (one['face'], snippet(one['error'], 70))
                                                       for one in unread) + '）'),
             '合计：系统级失败 %d 条（A %d＋B %d）；对照 %d 条' % (counts['A'] + counts['B'], counts['A'],
                                                             counts['B'], counts['C'])]
    for label, key in zip(GROUPS, ('A', 'B', 'C')):
        live = [pair for pair in rows[key] if pair[1]['n'] > 0]
        if not live:
            lines.append('■ 组 %s：0 条%s' % (label, '（另有 %d 型是 0 或读不到，列在下面）' % len(rows[key])
                                          if rows[key] else ''))
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
            for sample in entry['samples'][:SAMPLES]:
                lines.append('    - %s' % sample)
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
    check('contrast_not_in_total', '系统级失败 5 条（A 2＋B 3）；对照 9 条' in out3,
          out3.splitlines()[3] if len(out3.splitlines()) > 3 else '')
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
    if not any(one['read'] for one in faces):
        print('判不了：一面都没读到（' + '；'.join(str(one['error'])[:70] for one in faces) + '）')
        return 2
    for line in render(faces, pairing, offset,
                       'DSH 失败扫描 · 窗口 本地 %s（%s）' % (window['text'], window['how'])):
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
