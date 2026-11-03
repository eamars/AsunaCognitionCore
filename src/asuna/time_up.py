"""An action stage at its limit (ADR-112 §12.2): the program asks her, and cuts only if she does not decide.

`StageClock` is the deadline of one executor stage, read by `NativeLane.wait` once a tick. At the deadline it writes
`time_up` on the task (which ask this is, and when), records `task.time_up`, and calls `ask` (her `task_time` turn, on
a thread of its own); the stage goes on working. Her `task` option `more` raises the task's `time_more` by one and
removes `time_up`: the clock sees the count rise and moves the deadline one block on, and the same native run goes on.
A stage that ends while she is asked ends as always; one she stops ends as `stop` does; when TIME_UP_WINDOW passes with
no `more`, `due` says to cut, and the stage is cut as it was before. The window runs from when her turn starts
(`time_up.turn_at`, written by her turn): while her other turns hold her, the stage goes on working, up to one more
block, and is then cut as `not_asked`. `task.time_up_outcome` records which it was: more, ended, stopped, cut or
not_asked. Each stage's asks have their own key (`key`), so a task's later stage is asked again.

The words for her are program text: 你 is her. Bump TIME_UP_VERSION with any change to them.
"""
from __future__ import annotations

import time
import uuid

from .records import tasks as task_records
from .state import now as utc_now

TIME_UP_VERSION = 1
TIME_UP_WINDOW = 600          # seconds from the deadline in which her `more` keeps the stage going
RECENT_SECONDS = 300          # the stretch her activity line looks back over

TEXT = '你交给行动脑的一件事，这一段到了时间上限，还在做：要不要接着让它做，你来定。'
NOT_NOW = '这件事这会儿没有在等你加时：只有它到了时间上限、程序来问你的那一回合能用 more。'
RESTART_PENDING = '宿主在等这件事做完好重启：现在不能加时；要它先交报告，就用 task 的 message 叫它收尾。'
GRANTED = '加了：同一趟接着做，再给它 %d 分钟，之前查到的它都还看得到；到点再来问你。'
ALREADY_BACK = '这件事已经不在跑了（%s），不用加时；有结果会照常交给你。'


def _span(seconds):
    if seconds < 60:
        return '%d 秒' % max(1, int(seconds))
    return '约 %d 分钟' % round(seconds / 60)


def lately(activity):
    """Her line on how the stage's calls went in the last RECENT_SECONDS (tool_watch.Calls.activity)."""
    if activity['ended']:
        return '最近 %d 分钟用了 %d 次工具，最后一次在 %s前' % (RECENT_SECONDS // 60, activity['ended'],
                                                       _span(activity['since_last']))
    if activity['running']:
        return '最近 %d 分钟没有用完的工具调用；这会儿有 %d 个还没回来' % (RECENT_SECONDS // 60, activity['running'])
    if activity['since_last'] is not None:
        return '最近 %d 分钟没有用工具（上一次在%s前）' % (RECENT_SECONDS // 60, _span(activity['since_last']))
    return '最近 %d 分钟没有用工具（这一段还没用过）' % (RECENT_SECONDS // 60)


def behind(store, task_id):
    """What waits behind this task for the one action worker, always said, none too."""
    from .tasks import place_words
    waiting = [row for row in task_records.in_states(store, ['READY'], besides=task_id).rows(fields=['scene_id'])]
    if not waiting:
        return '后面没有排着的'
    places = '、'.join(dict.fromkeys(place_words(store, row['scene_id']) for row in waiting))
    return '后面还有 %d 件在排（来自%s），行动脑一次只做一件，这件做着它们就等着' % (len(waiting), places)


def facts(store, task, *, minutes, block, activity):
    """What only the program knows when a stage reaches its limit, as words for her `task_time` turn."""
    granted = task.get('time_more') or 0
    return {
        'ran': '这一段已经跑了约 %d 分钟（每段上限 %d 分钟）' % (minutes, block // 60),
        'steps': '这件事一共用了 %d 步工具' % (task.get('tool_steps') or 0),
        'lately': lately(activity),
        'queue': behind(store, task['_id']),
        'more_so_far': '你已经给它加过 %d 次时' % granted if granted else '这是它第一次到点',
        'window': ('%d 分钟里不用 more 加时，它就会被停下（和以前到上限一样，停下时不交报告）；要它先交报告，用 task 的 '
                   'message 叫它收尾；不该再做了就 stop。' % (TIME_UP_WINDOW // 60)),
    }


class StageClock:
    """The deadline of one executor stage; `due()` once a tick, `ended()` when the stage ends however it ends."""

    def __init__(self, service, task, block, ask, *, window=TIME_UP_WINDOW, clock=time.monotonic):
        self.service, self.task_id, self.scope = service, task['_id'], task['scope_key']
        self.block, self.window, self.ask, self.clock = block, window, ask, clock
        self.started = clock()
        self.deadline = self.started + block
        self.until = None          # while she is asked: the latest the window can end (her turn not started)
        self.granted = 0           # the task's time_more when she was asked
        self.asks = 0
        self.stage = uuid.uuid4().hex[:12]
        self.turn_seen = None      # when this clock first saw her turn started

    def key(self):
        """This ask of this stage: what her turn is known by."""
        return '%s:%s:%d' % (self.task_id, self.stage, self.asks)

    def due(self):
        """True when the stage is to be cut now."""
        moment = self.clock()
        if self.until is None:
            if moment >= self.deadline:
                self._ask(moment)
            return False
        task = task_records.get(self.service.store, self.task_id, fields=['time_more', 'time_up'])
        if task and (task.get('time_more') or 0) > self.granted:
            return self._more()
        if self.turn_seen is None and ((task or {}).get('time_up') or {}).get('turn_at'):
            self.turn_seen = moment         # her turn has started: the window runs from here
        if moment < (self.until if self.turn_seen is None else self.turn_seen + self.window):
            return False
        with self.service.lock:
            # Her more and the cut are decided under one lock: a grant saved a moment ago is not cut.
            task = task_records.get(self.service.store, self.task_id)
            if task and (task.get('time_more') or 0) > self.granted:
                return self._more()
            if task and task.get('time_up'):
                task_records.save(self.service.store, {k: v for k, v in task.items() if k != 'time_up'},
                                  expected=task['revision'], stream=self.task_id)
        self._outcome('cut' if self.turn_seen is not None else 'not_asked')
        return True

    def minutes(self):
        """How long this stage has run, in whole minutes."""
        return round((self.clock() - self.started) / 60)

    def _more(self):
        self.turn_seen = None
        self._outcome('more')
        self.deadline += self.block
        self.until = None
        return False

    def ended(self):
        """The stage ended (a result, her stop, or an error): if she was being asked, say how it ended."""
        if self.until is None:
            return
        task = task_records.get(self.service.store, self.task_id, fields=['state', 'cancel_reason']) or {}
        self._outcome('stopped' if task.get('state') == 'CANCELLED' else 'ended', clear=True)
        self.until = None

    def _ask(self, moment):
        self.asks += 1
        self.until = self.deadline + self.block
        with self.service.lock:
            task = task_records.get(self.service.store, self.task_id)
            if not task or task['state'] != 'RUNNING':
                return                     # it is ending anyway; the window keeps the old bound
            self.granted = task.get('time_more') or 0
            task = task_records.save(self.service.store, {**task, 'time_up': {'ask': self.asks, 'at': utc_now()}},
                                     expected=task['revision'], stream=self.task_id)
        minutes = round((moment - self.started) / 60)
        self.service.store.audit(self.task_id, 'task.time_up', {'ask': self.asks, 'minutes': minutes,
                                                                'steps': task.get('tool_steps') or 0}, self.scope)
        self.ask(task, minutes, self.key())

    def _outcome(self, outcome, clear=False):
        self.service.store.audit(self.task_id, 'task.time_up_outcome', {'ask': self.asks, 'outcome': outcome},
                                 self.scope)
        if not clear:
            return
        with self.service.lock:
            task = task_records.get(self.service.store, self.task_id)
            if task and task.get('time_up'):
                task_records.save(self.service.store, {k: v for k, v in task.items() if k != 'time_up'},
                                  expected=task['revision'], stream=self.task_id)


def started(service, task_id):
    """Her turn about a stage starts: `time_up.turn_at` marks it, and the stage's clock runs the window from when it
    sees the mark. None when the stage is no longer waiting for her."""
    with service.lock:
        task = task_records.get(service.store, task_id)
        if not task or task['state'] != 'RUNNING' or not task.get('time_up'):
            return None
        return task_records.save(service.store, {**task, 'time_up': {**task['time_up'], 'turn_at': utc_now()}},
                                 expected=task['revision'], stream=task_id)


def grant(service, task, restart_pending):
    """Her `more`: one more block for a stage she is being asked about. The words for her, and whether it was given."""
    with service.lock:
        current = task_records.get(service.store, task['_id'])
        if current['state'] != 'RUNNING':
            from .handover import status_words
            return ALREADY_BACK % status_words(current), False
        if not current.get('time_up'):
            return NOT_NOW, False
        if restart_pending():
            return RESTART_PENDING, False
        task_records.save(service.store, {**{k: v for k, v in current.items() if k != 'time_up'},
                                          'time_more': (current.get('time_more') or 0) + 1},
                          expected=current['revision'], stream=current['_id'])
    service.store.audit(current['_id'], 'task.time_more', {'ask': current['time_up'].get('ask'),
                                                           'granted': (current.get('time_more') or 0) + 1},
                        current['scope_key'])
    return GRANTED % (service.store.config['workflow_timeout_seconds'] // 60), True
