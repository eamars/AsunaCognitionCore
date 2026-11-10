"""When one of her turns fails in the program (FAILED_RUNTIME), nobody may be left not knowing (ADR-076 R4).

The developer gets one `developer_inbox` note per kind of failure a day (`source.by: program`), its count kept
current as the same failure comes again; the conversation where it happened is marked, and her next turn there reads
it once (`fault_from_program`): which turn did not run, that it was the program and not her, and that it was
reported. Deterministic and program-side: nothing runs while turns succeed.
"""
from __future__ import annotations

import re

from . import clock
from . import developer_inbox
from .records import scenes as scene_records

CODE = re.compile(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b')
DEV_TEXT = '她的%s回合在程序里出错没跑成（%s）：今天第一次，场景 %s，回合 %s。同一天同样的错再来只加计数（count）。'
HER_LINE = '你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么；已经报给开发者了。'
# A due plan that did not run (ADR-119 F10), in her wording.
PLAN_DEV_TEXT = '她的计划到点没排上（%s）：今天第一次，计划 %s，场景 %s。同一天同样的错再来只加计数（count）。'
PLAN_LINE = '你安排的计划「%s」%s 到点了没排上：程序没把它交上去（%s），不是你做错了什么。%s'
GOES_ON = {True: '这条计划还在，下次照旧。', False: '这条不再响了。'}
PLAN_MORE = '从上次告诉你以来，这里没排上的计划一共 %d 次。'
# A due plan handed to her late (ADR-119 F10): the two times and the cause as known, her wording.
LATE_LINE = '这条计划 %s 到点，%s 才交到你手上：中间这一截程序没交过来（%s），不是你拖的。'
INTENT_CHARS = 40
NO_CAUSE = '原因没记下来'          # a cause with no record, one word for it (her F4 rule, line 0281)
KINDS = {'self_development': '自我改进', 'task_feedback': '收任务结果', 'external': '回话', 'scheduled': '计划到点',
         'visit': '出门', 'note': '便条', 'settlement': '夜间沉淀', 'presence': '心跳', 'consult': '回答行动脑',
         'task_time': '定到点的事'}


def cause(error):
    """The failure's name: its error code if it carries one, else the exception's class."""
    last = next((line.strip() for line in reversed(str(error or '').splitlines()) if line.strip()), '')
    code = CODE.search(last)
    if code:
        return code.group(0)
    head = last.split(':', 1)[0].rsplit('.', 1)[-1]
    return head[:60] or 'unknown'


def turn_failed(store, ep, error, now=None):
    """Report a failed turn to the developer and mark its conversation for her next turn there."""
    moment = now or clock.now()
    name, kind = cause(error), ep.get('episode_kind') or 'external'
    row = developer_inbox.leave(store, ep.get('persona') or store.config['chat']['persona'], developer_inbox.NOTE,
                                DEV_TEXT % (KINDS.get(kind, kind), name, ep.get('scene_id'), ep.get('_id')),
                                key=['turn_failed', kind, name, moment.date().isoformat()],
                                source={'by': 'program', 'kind': 'turn_failed', 'cause': name})
    developer_inbox.bump(store, row['_id'])
    scene_records.note_fault(store, ep.get('scene_id'), {'at': moment.isoformat(), 'cause': name, 'kind': kind})


def plan_failed(store, plan, error, goes_on, now=None):
    """A due plan that did not run: its conversation is marked for her next turn there (apart from the turn-fault
    mark), and the developer is told once a day per failure, counted. A failed inbox write is audited and does not
    stop the mark; her line does not claim the report."""
    moment = now or clock.now()
    name = cause(error)
    scene_records.note_plan_fault(store, plan.get('scene_id'), {'at': moment.isoformat(), 'cause': name,
                                  'intent': str(plan.get('intent') or '')[:INTENT_CHARS], 'goes_on': bool(goes_on),
                                  'plans.' + plan['_id']: moment.isoformat()})
    try:
        row = developer_inbox.leave(store, store.config['chat']['persona'], developer_inbox.NOTE,
                                    PLAN_DEV_TEXT % (name, plan.get('_id'), plan.get('scene_id')),
                                    key=['plan_failed', name, moment.date().isoformat()],
                                    source={'by': 'program', 'kind': 'plan_failed', 'cause': name})
        developer_inbox.bump(store, row['_id'])
    except Exception as exc:
        store.audit(plan['_id'], 'schedule.fault_unreported', {'error': str(exc)[:300]}, plan.get('scope_key'))


def plan_line(store, scene, zone):
    """The once-only line for her next turn where a due plan of hers did not run, or None."""
    fault = scene.get('plan_fault')
    if not fault or not fault.get('count'):
        return None
    from .schedule_rules import line_stamp
    from .local_time import UNKNOWN
    line = PLAN_LINE % (fault.get('intent') or '', line_stamp(zone, fault.get('at')) or UNKNOWN,
                        fault.get('cause') or NO_CAUSE, GOES_ON[fault.get('goes_on') is not False])
    return line + (PLAN_MORE % fault['count'] if fault['count'] > 1 else '')


def late_line(zone, due, handed, why):
    """The line in a plan's turn that reached her late, the times on her clock (「时间不详」 when unreadable)."""
    from .schedule_rules import line_stamp
    from .local_time import UNKNOWN
    return LATE_LINE % (line_stamp(zone, due) or UNKNOWN, line_stamp(zone, handed) or UNKNOWN, why)


def her_line(store, scene, zone):
    """The once-only line for her next turn where a turn of hers failed, or None. The mark stays until a turn that
    showed it commits (`told`), so a turn that fails after it was prepared does not lose it."""
    fault = scene.get('fault')
    if not fault:
        return None
    from .schedule_rules import line_stamp
    from .local_time import UNKNOWN
    return HER_LINE % (line_stamp(zone, fault.get('at')) or UNKNOWN, fault.get('cause') or '原因不明')


def told(store, ep):
    """A turn ran to its end: the once-only marks its context showed (manifest `told`) are cleared, each only if it is
    still the mark that was shown (a newer one set meanwhile stays for the next turn)."""
    shown = (ep.get('manifest') or {}).get('told') or {}
    if shown.get('fault'):
        scene_records.clear_fault(store, ep['scene_id'], shown['fault'])
    if shown.get('plan_fault'):
        # Each plan she was told about keeps a line that she was (her ask: to count the times later).
        moment = clock.now().isoformat()
        for plan_id, failed_at in (shown['plan_fault'].get('plans') or {}).items():
            store.audit(plan_id, 'schedule.fault_told', {'told_at': moment, 'failed_at': failed_at,
                                                         'episode_id': ep.get('_id')}, ep.get('scope_key'))
        scene_records.clear_plan_fault(store, ep['scene_id'], shown['plan_fault'])
    if shown.get('unsent'):
        scene_records.clear_unsent(store, ep['scene_id'], shown['unsent'])
    if shown.get('host_stops'):
        # ADR-101: the outages it showed stay until such a turn commits, and at least a day (host_stops.listed).
        from . import host_stops
        try:
            host_stops.shown(store, shown['host_stops'])
        except Exception:
            pass                        # unstamped, it is shown again next time: the safe side of a failed write
