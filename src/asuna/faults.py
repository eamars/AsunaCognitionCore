"""When one of her turns fails in the program (FAILED_RUNTIME), nobody may be left not knowing (ADR-076 R4).

The developer gets one `developer_inbox` note per kind of failure a day (`source.by: program`), its count kept
current as the same failure comes again; the conversation where it happened is marked, and her next turn there reads
it once (`fault_from_program`): which turn did not run, that it was the program and not her, what of it went out and
what was done (ADR-127 N1), and that it was written into the developer inbox. Deterministic and program-side: nothing
runs while turns succeed.
"""
from __future__ import annotations

import re

from . import clock
from . import developer_inbox
from .records import scenes as scene_records

CODE = re.compile(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b')
# A code the plugin puts first on the failure's line (index.js failureText), one-word ones (TIMEOUT) included.
LEAD = re.compile(r'^(?:\w+: )?([A-Z][A-Z0-9_]*[A-Z0-9]): ')
DEV_TEXT = '她的%s回合在程序里出错没跑成（%s）：今天第一次，场景 %s，回合 %s。同一天同样的错再来只加计数（count）。'
# Her line about a failed turn (ADR-127 N1, her wording, agent line 0393, 0396, 0403, 0404): the turn, the cause
# as a readable word (CAUSES), then what of it went out and what was done, by name, never a text or an argument.
TURN_HEAD = '你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了什么。'
NOTHING_DONE = '那一拍你没说出口一个字、也没做成任何事——那件事到现在还是没做。'
RETRIED = '程序为重请求过一次，第二次还是没跑成，没再自动重跑——那件事到现在还是没做。'
THAT_BEAT = '那一拍你'
WENT_OUT = '发出去 %d 句'
DONE_TOOLS = '做成了这些工具：%s'
SENT_NOTE = '已经送出去的话不用重发'
TOOLS_NOTE = '列出来的工具先核它落地没有，再决定要不要重做'
REPORTED = '这条已经记进开发者收件箱'
UNREAD = '开发者收件箱里还有 %d 条没被读过'
# The causes her line names: a code is shown only through this table, never as the error's own text (which can carry
# what the model wrote); one not in it is 「出错类型未辨」.
CAUSES = {'MALFORMED_RESPONSE': '模型回来的工具参数不成形', 'TRANSPORT': '连不上模型', 'TIMEOUT': '模型超时没回',
          'CONTEXT_WINDOW_EXCEEDED': '对话太长，模型装不下', 'PI_AI_ERROR': '模型服务报错',
          'INVALID_REQUEST': '模型拒收了这次请求', 'NO_ADAPTER': '没有能用的模型'}
UNREADABLE = '出错类型未辨'
# The plugin's mark on a turn whose broken step was requested again once (ADR-127 R1) and broke again.
RETRIED_MARK = 'ASUNA_RETRIED_ONCE'
# Tools whose doing is her speech or her thought: what went out is counted as lines, a thought is not a deed.
NOT_DEEDS = {'speak', 'stay_silent', 'think'}
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
    lead = LEAD.match(last)
    if lead:
        return lead.group(1)
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
    scene_records.note_fault(store, ep.get('scene_id'), {'at': moment.isoformat(), 'cause': name, 'kind': kind,
                             'episode_id': ep.get('_id'), **({'retried': True} if RETRIED_MARK in str(error or '') else {})})


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
    code = fault.get('cause')
    line = TURN_HEAD % (line_stamp(zone, fault.get('at')) or UNKNOWN,
                        CAUSES.get(code, UNREADABLE) if code else NO_CAUSE)
    return line + lost(store, fault) + reported(store)


def lost(store, fault):
    """What of the failed turn went out (its delivered lines) and what was done (its tools that completed, by name),
    read when her line is made; requested again and broken again is said as such."""
    from .records import episodes as episode_records
    from .records import messages as message_records
    episode = fault.get('episode_id')
    sent = message_records.turn_parts(store, episode, outbound=True, delivered=True).count() if episode else 0
    calls = (episode_records.get(store, episode, fields=['tool_calls']) or {}).get('tool_calls') if episode else None
    done = []
    for call in sorted((calls or {}).values(), key=lambda call: call.get('seq', 0)):
        if 'result' in call and call.get('tool') not in NOT_DEEDS and call.get('tool') not in done:
            done.append(call.get('tool'))
    if not sent and not done:
        return RETRIED if fault.get('retried') else NOTHING_DONE
    said = [WENT_OUT % sent] if sent else []
    if done:
        said.append(DONE_TOOLS % '、'.join(done))
    notes = ([SENT_NOTE] if sent else []) + ([TOOLS_NOTE] if done else [])
    return THAT_BEAT + '、'.join(said) + '。' + '；'.join(notes) + '。'


def reported(store):
    """It was written into the developer inbox, and how many notes there nobody has read; that half is left out when
    the count cannot be read, never shown as 0."""
    try:
        unread = len(developer_inbox.unread(store))
    except Exception:
        return REPORTED + '。'
    return REPORTED + '；' + UNREAD % unread + '。'


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
