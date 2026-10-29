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
KINDS = {'self_development': '自我改进', 'task_feedback': '收任务结果', 'external': '回话', 'scheduled': '计划到点',
         'visit': '出门', 'note': '便条', 'settlement': '夜间沉淀', 'presence': '心跳', 'consult': '回答行动脑'}


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


def her_line(store, scene, zone):
    """The once-only line for her next turn where a turn of hers failed, or None. The mark stays until a turn that
    showed it commits (`told`), so a turn that fails after it was prepared does not lose it."""
    fault = scene.get('fault')
    if not fault:
        return None
    from .schedule_rules import line_stamp
    return HER_LINE % (line_stamp(zone, fault.get('at')) or '刚才', fault.get('cause') or '原因不明')


def told(store, ep):
    """A turn ran to its end: the once-only marks its context showed (manifest `told`) are cleared, each only if it is
    still the mark that was shown (a newer one set meanwhile stays for the next turn)."""
    shown = (ep.get('manifest') or {}).get('told') or {}
    if shown.get('fault'):
        scene_records.clear_fault(store, ep['scene_id'], shown['fault'])
    if shown.get('unsent'):
        scene_records.clear_unsent(store, ep['scene_id'], shown['unsent'])
    if shown.get('host_stops'):
        # ADR-101: the outages it showed stay until such a turn commits, and at least a day (host_stops.listed).
        from . import host_stops
        try:
            host_stops.shown(store, shown['host_stops'])
        except Exception:
            pass                        # unstamped, it is shown again next time: the safe side of a failed write
