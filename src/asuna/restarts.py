"""Her restarts (ADR-034): the worker side of the Host supervisor (tools/asuna-supervisor.mjs).

She asks with the `restart` tool. The desk keeps her one pending request and, when it is due (now, at her time, or
when nothing is running, waiting at most QUIET_MINUTES), marks the stop as planned and writes
<data>/restart/request.json for the supervisor, which stops the Host and brings it back. The supervisor's record of
how that went, <data>/restart/last.json, reaches her home turns for a day; if she came back on an older version,
a home turn calls her at once.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUIET_MINUTES = 30            # at most this long waiting for no turn, task or queued input
TICK_SECONDS = 15
SHOWN_HOURS = 24
PLANS_AHEAD_MINUTES = 15
DESK = None                   # the running Host's desk (one Host per worker); role tools reach it here

NOTE = ('这是监工（启动器）记下的重启结果，不是你自己报的。没有「退回」就是你要的版本在跑；'
        '要核对版本就看 loaded。不用回复。')
RESULT_WORDS = {'running': '起来了，跑的是这次该跑的版本',
                'fell_back': '起来了，但退回了上一个能跑的版本（新版本没起来，原因见 attempts）'}


def supervised():
    """Whether this Host runs under the supervisor; without it nobody would take a request."""
    return os.environ.get('ASUNA_SUPERVISED') == '1'


def folder(root=None):
    from .config import DATA
    return Path(root or DATA) / 'restart'


def last(root=None):
    try:
        return json.loads((folder(root) / 'last.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _aware(value):
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _zone(zone):
    """line_stamp's zone from a context's zone or an IANA name."""
    from .schedule_rules import _zone as named
    return named(zone) if isinstance(zone, str) else zone


def _span(seconds):
    from .host_stops import _span as span
    return span(seconds)


class Desk:
    def __init__(self, app, controller, *, root=None, zone='UTC', clock=None):
        self.app, self.controller, self.root, self.zone = app, controller, root, zone
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.pending = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None

    # ── what a restart would interrupt ─────────────────────────────
    def preview(self):
        from .schedule_rules import line_stamp
        store, moment = self.app.store, self.clock()
        items = []
        if getattr(self.controller, 'active_task', None):
            task = store.db.tasks.find_one({'_id': self.controller.active_task}, {'title': 1, 'goal': 1}) or {}
            items.append('行动脑正在跑「%s」：会停在暂停里，要有人说继续才接着做' % (task.get('title') or task.get('goal') or '一个任务')[:40])
        queued = [row.get('title') or row.get('goal') or '' for row in store.db.tasks.find(
            {'state': 'READY'}, {'title': 1, 'goal': 1}).limit(5)]
        if queued:
            items.append('排着队的任务 %d 个：%s' % (len(queued), '、'.join('「%s」' % t[:20] for t in queued)))
        waiting = getattr(getattr(self.controller, 'pending', None), 'unfinished_tasks', 0)
        if waiting:
            items.append('排着队还没轮到的消息 %d 条：起来后接着处理，不会丢' % waiting)
        unsent = store.db.messages.count_documents({'direction': 'outbound', 'delivery_state': {'$in': ['QUEUED_EXTERNAL', 'SENDING']}})
        if unsent:
            items.append('还没确认送到的话 %d 条：在发的那条会变成「没给准话」，不会自动重发' % unsent)
        soon = (moment + timedelta(minutes=PLANS_AHEAD_MINUTES)).isoformat()
        for plan in store.db.plans.find({'status': 'ACTIVE', 'next_fire_at': {'$lte': soon},
                                         'kind': {'$nin': ['presence', 'settlement', 'self_development']}},
                                        {'intent': 1, 'next_fire_at': 1}).limit(5):
            items.append('%s 要响的计划「%s」：停着的时候到点，起来后补响' % (line_stamp(_zone(self.zone), plan['next_fire_at']), str(plan.get('intent', ''))[:30]))
        record = last(self.root)
        took = None
        if record and record.get('down_at') and record.get('back_at'):
            took = _span((_aware(record['back_at']) - _aware(record['down_at'])).total_seconds())
        return {'interrupts': items or ['现在没有在跑的任务、排队的消息或马上要响的计划'],
                'also': 'QQ 适配器会跟着停，起来后自动恢复；网页和你在本机的对话这段时间都不在。',
                **({'last_restart_took': took} if took else {}),
                'supervised': '有监工：停了以后由它拉起来、起不来一级级往回退' if supervised()
                              else '这次宿主不是由监工起的：没人接重启请求，现在要不了'}

    # ── her request ────────────────────────────────────────────────
    def request(self, why, when='quiet', drill=False, asked='xiaoman'):
        if not supervised():
            raise PermissionError('RESTART_NOT_SUPERVISED: 这次宿主不是由监工（启动器常驻）起的，没人接重启请求；要重启跟主人说')
        moment = self.clock()
        at = self._when(when, moment)
        with self.lock:
            self.pending = {'asked': asked, 'why': why, 'when': when, 'drill': bool(drill),
                            'requested_at': moment.isoformat(), 'not_before': at.isoformat()}
        self.start()
        return self.pending

    def _when(self, when, moment):
        if when in ('now', 'quiet'):
            return moment
        from zoneinfo import ZoneInfo
        try:
            hour, minute = (int(part) for part in str(when).split(':'))
            local = moment.astimezone(ZoneInfo(self.zone)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            raise ValueError('RESTART_WHEN_INVALID: when 是 now、quiet 或当地时刻 HH:MM（给的是 %r）' % (when,))
        if local <= moment:
            local += timedelta(days=1)
        return local.astimezone(timezone.utc)

    def cancel(self):
        with self.lock:
            had, self.pending = self.pending, None
        return had

    def quiet(self):
        c = self.controller
        return (getattr(c, 'active', None) is None and getattr(c, 'active_task', None) is None
                and not getattr(getattr(c, 'pending', None), 'unfinished_tasks', 0)
                and not getattr(getattr(c, 'task_queue', None), 'unfinished_tasks', 0))

    def due(self):
        with self.lock:
            pending = self.pending
        if not pending:
            return False
        moment = self.clock()
        if moment < _aware(pending['not_before']):
            return False
        if pending['when'] == 'now':
            return True
        waited = (moment - _aware(pending['not_before'])).total_seconds() / 60
        return self.quiet() or waited >= QUIET_MINUTES

    def go(self):
        """Hand the due request to the supervisor: the stop is planned, and what it interrupts is recorded now."""
        with self.lock:
            pending, self.pending = self.pending, None
        if not pending:
            return None
        request = {**pending, 'interrupted': self.preview()['interrupts'], 'go_at': self.clock().isoformat()}
        try:
            from .host_lease import mark_planned
            mark_planned(self.app.config, pending['asked'])
        except Exception:
            pass                               # the record still says who asked; only the "killed" notice is at stake
        target = folder(self.root)
        target.mkdir(parents=True, exist_ok=True)
        (target / 'request.json.tmp').write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(target / 'request.json.tmp', target / 'request.json')
        self.app.store.audit('restart', 'restart.requested', {k: request[k] for k in ('asked', 'why', 'when', 'drill')}, 'operator')
        return request

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        def run():
            while not self.stop_event.wait(TICK_SECONDS):
                if self.due():
                    self.go()
        self.thread = threading.Thread(target=run, name='asuna-restart-desk', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()


# ── after a restart ────────────────────────────────────────────────
def block(store, zone, moment=None, root=None, integration_state=None):
    """restart_from_program for a home turn: the supervisor's latest record, for a day."""
    from .schedule_rules import line_stamp
    record = last(root)
    moment = moment or datetime.now(timezone.utc)
    zone = _zone(zone)
    if not record or not record.get('back_at') or moment - _aware(record['back_at']) > timedelta(hours=SHOWN_HOURS):
        return None
    asked = {'xiaoman': '你自己要的', 'nobody': '没人要：宿主自己退出了，监工把它拉起来'}.get(record.get('asked'), str(record.get('asked')))
    down = _span((_aware(record['back_at']) - _aware(record['down_at'])).total_seconds())
    tries = record.get('attempts') or []
    value = {'what': ('演练' if record.get('drill') else '重启') + '：' + asked,
             'why': str(record.get('why') or '')[:200],
             'when': '%s 停，%s 起来，中间约 %s' % (line_stamp(zone, record['down_at']), line_stamp(zone, record['back_at']), down),
             'result': RESULT_WORDS.get(record.get('result'), str(record.get('result'))),
             'attempts': ['第 %d 次：%s' % (i + 1, '起来了' if a.get('ok') else '没起来：' + str(a.get('reason'))[:120]) for i, a in enumerate(tries)],
             'loaded': record.get('loaded') or {},
             'note': NOTE}
    if record.get('reverted'):
        value['reverted'] = record['reverted']
    if record.get('interrupted'):
        value['interrupted'] = record['interrupted']
    paused = [row.get('title') or row.get('goal') for row in store.db.tasks.find(
        {'state': 'PAUSED', 'pause_reason': 'host_restart', 'paused_at': {'$gte': record['down_at']}}, {'title': 1, 'goal': 1}).limit(5)]
    if paused:
        value['paused_tasks'] = ['「%s」：停在暂停里，工具记录都在，说一声继续就接着做' % str(t)[:40] for t in paused]
    adapter = integration_state if integration_state is not None else _adapter_since(record['back_at'], root)
    if adapter:
        value['qq_adapter'] = adapter
    return value


def _adapter_since(back_at, root=None):
    """Whether the QQ adapter came back after this restart, from its own health file."""
    from .config import DATA
    health = Path(root or DATA) / 'integration' / 'owner' / 'service-data' / 'health.json'
    try:
        seen = datetime.fromtimestamp(health.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return '起来了，在跑' if seen >= _aware(back_at) else '重启后还没起来（它的健康记录停在重启前）'


def call_after_fallback(store, controller, config, root=None, moment=None):
    """Once, right after a restart that fell back: a home turn tells her she runs the previous version."""
    record = last(root)
    moment = moment or datetime.now(timezone.utc)
    if not record or record.get('result') != 'fell_back' or not record.get('back_at'):
        return False
    if moment - _aware(record['back_at']) > timedelta(minutes=30):
        return False
    if store.db.audit_events.find_one({'type': 'restart.called', 'payload.id': record['id']}, {'_id': 1}):
        return False
    chat = config['chat']
    text = ('这是监工的通知，不是用户消息：刚才那次重启新版本没起来，现在跑的是上一个能跑的版本。'
            '原因和每一次尝试都在 restart_from_program 里；要不要再试、改什么，你定。')
    controller.offer_internal('presence', 'presence:restart-' + record['id'], chat['scene_id'], chat['person_id'], text)
    store.audit('restart', 'restart.called', {'id': record['id']}, 'operator')
    return True
