"""ADR-030: the program's watchdog over handovers between the brains.

A delegated task's result is handed back to the character brain in a turn of her own (tasks.TaskService.feedback),
queued in the worker's memory. The watchdog catches the two definite failures and nothing else: a finished task whose
result is neither taken nor on its way (lost), and a running task whose lease expired while no one runs it
(orphaned). It reads task state, calls no model and does nothing in normal operation. Slowness is not a failure: one
executor model serves both brains, so it never judges by how long something has taken.

A lost result is handed back again by its cause, read from the database: a hand-back that failed before her turn
(recorded `handback.failures`) gets the full result once more, then the short version; one whose turn on it failed
(a hand-back episode that ended without committing) gets the short version; one lost without an error (a restart)
gets the full result. When the short version fails too, the developer is told and the watchdog stops.
"""
from __future__ import annotations

import time

SWEEP_SECONDS = 60
FINISHED = ('RETURNED', 'BLOCKED', 'DONE', 'PARTIAL', 'NEEDS_CHARACTER_DECISION', 'UNKNOWN')
TAKEN = ('DELIVERED', 'WAITING_TASK', 'SUPPRESSED', 'UNDELIVERABLE')
FULL, SHORT, GIVE_UP = 'full', 'short', 'give_up'
REPORT_FAILURES_BEFORE_SHORT = 2


def result_event_id(task, short=False):
    return task['_id'] + ':result:' + str(task['intent_revision']) + (':short' if short else '')


def waiting(task):
    """A finished task whose result has not reached her (a task without a hand-back record never had one)."""
    return task.get('state') in FINISHED and task.get('feedback_state') not in (*TAKEN, None)


def continuations(store, task_ids):
    """{task id: the newest task that continues it} for the given tasks."""
    found = {}
    for row in store.db.tasks.find({'continues_task_id': {'$in': list(task_ids)}},
                                   {'continues_task_id': 1, 'created_at': 1}).sort('created_at', 1):
        found[row['continues_task_id']] = row['_id']
    return found


def lost(store, on_its_way):
    """Finished tasks whose result was handed back by no one: not taken, not queued, not being handed back now."""
    rows = store.db.tasks.find({'state': {'$in': list(FINISHED)},
                                'feedback_state': {'$exists': True, '$nin': [*TAKEN, None]}})
    return [task for task in rows if task['_id'] not in on_its_way]


def orphaned(store, running, moment=None):
    """Running tasks whose lease expired while this worker is not running them."""
    moment = time.time() if moment is None else moment
    rows = store.db.tasks.find({'state': 'RUNNING', 'lease_expires_at': {'$lt': moment}})
    return [task for task in rows if task['_id'] != running]


def next_step(store, task):
    """FULL, SHORT or GIVE_UP for a lost result, from what the database says happened to it."""
    from .coordinator import RESUMABLE
    record = task.get('handback') or {}
    short = store.db.episodes.find_one({'source_event_id': result_event_id(task, True), 'episode_kind': 'task_feedback'})
    if record.get('short_failed') or short and short['state'] not in (*RESUMABLE, 'FAILED_PROTOCOL', 'COMMITTED'):
        return GIVE_UP
    if short:
        return SHORT                         # the short hand-back was cut off (a restart): resume it
    full = store.db.episodes.find_one({'source_event_id': result_event_id(task), 'episode_kind': 'task_feedback'})
    if full and full['state'] not in (*RESUMABLE, 'FAILED_PROTOCOL', 'COMMITTED'):
        return SHORT                         # her turn on it failed: the same full result would likely fail again
    if record.get('failures', 0) >= REPORT_FAILURES_BEFORE_SHORT:
        return SHORT
    return FULL


def cause(store, task):
    """Why the result is lost, for the card: report, turn or restart."""
    from .coordinator import RESUMABLE
    if (task.get('handback') or {}).get('failures'):
        return 'report'
    full = store.db.episodes.find_one({'source_event_id': result_event_id(task), 'episode_kind': 'task_feedback'})
    return 'turn' if full and full['state'] not in (*RESUMABLE, 'FAILED_PROTOCOL', 'COMMITTED') else 'restart'


# Her task list in words (ADR-030 D7): one phrase per task instead of raw state fields.
OUTCOME_WORDS = {'RETURNED': '跑完了', 'DONE': '跑完了', 'PARTIAL': '跑完了一部分', 'BLOCKED': '没做成',
                 'NEEDS_CHARACTER_DECISION': '停下来等你定', 'UNKNOWN': '结果不确定'}


def status_words(task, continued_by=None):
    """What she reads about one task: where its run and its result stand. `continued_by`: the task that carried
    this one on, which is the one to go by."""
    state = task.get('state')
    if continued_by and state not in ('READY', 'RUNNING'):
        return '后来接着做了一轮，以 %s 那条为准' % continued_by
    if state == 'READY':
        return '排着队，还没开始跑'
    if state == 'RUNNING':
        return '在跑'
    if state == 'PAUSED':
        return '做到一半宿主重启停了：主人说继续才接着做'
    if state == 'CANCELLED':
        return '宿主停机时撤下了：要做就用 message_action 接着做' if task.get('cancel_reason') == 'host_stop' else '叫停了'
    if state == 'STALE':
        return '交代改过了，这一份作废'
    outcome = OUTCOME_WORDS.get(state, '跑完了')
    handed = task.get('feedback_state')
    if handed is None:
        return outcome                       # no hand-back record (an old row): nothing to say about one
    if handed in ('DELIVERED', 'WAITING_TASK'):
        return outcome + '，结果已经交给你'
    if handed == 'UNDELIVERABLE':
        return outcome + '，但结果交不到你手上：补交也没成，开发者已经知道；要再看就用 message_action 让它重跑'
    if handed == 'SUPPRESSED':
        return outcome + '；它所在的对话后来变了，结果不再交给你'
    return outcome + '，结果还没交到你手上：报告存着，程序会交给你'
