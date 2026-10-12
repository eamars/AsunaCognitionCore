"""Her switches (ADR-052): mute a group, turn tools off in a conversation, block a person.

Each switch ends by itself: after 24 hours unless she gives another number of hours (at most a week), so a switch she
forgot never turns into her being inconsistent with someone who did nothing. The program keeps them and says where
one is on: the switched conversation lists its own switches, her home lists them all and the ones that ended lately.
She sets them with tools she has: mute with `group_focus`, block with `understand_person` (the person speaking to her),
tools off and an early end with `set_policy`.

- Muted: the group rests (focus.active is false: only words addressed to her wake her, no first word from her, no
  summaries) and she does not visit it; it stays in her heartbeat marked muted.
- Tools off: the conversation keeps listing them (the tool list stays stable), and a call is refused saying so.
- Blocked: that account's lines are kept and searchable but wake her nowhere and do not count as addressed to her.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .evidence import sha
from .state import Denied, now

DEFAULT_HOURS = 24
MAX_HOURS = 168
ENDED_SHOWN = timedelta(hours=12)                # an ended switch is listed at home this long, then gone
KEEP = ('think', 'recall', 'stay_silent')        # a turn needs these: never switched off
WORDS = {'mute': '静音', 'tools_off': '关了工具', 'block': '屏蔽'}
NOTE = ('你自己开着的开关（静音、关工具、屏蔽），until_at 到点自己结束；要提前结束，在家里用 set_policy：'
        'key=switch_off，value 写开关的 id。ended 是最近结束的。')


def _moment(moment=None):
    return moment or datetime.now(timezone.utc)


def hours_of(value):
    """The hours a switch lasts: DEFAULT_HOURS when not given, else a whole number 1..MAX_HOURS."""
    if value is None:
        return DEFAULT_HOURS
    try:
        hours = int(value)
    except (TypeError, ValueError):
        raise Denied('SWITCH_HOURS_INVALID: hours 给的是「%s」' % value) from None
    if not 1 <= hours <= MAX_HOURS or str(value).strip() not in (str(hours), str(float(hours))):
        raise Denied('SWITCH_HOURS_INVALID: hours 给的是「%s」' % value)
    return hours


def set_switch(store, ep, kind, *, label, scene_id=None, person_id=None, tools=None, hours=None, why=None,
               moment=None):
    """One switch per kind and target; setting it again replaces it (a new end, new tools)."""
    moment = _moment(moment)
    target = scene_id if kind != 'block' else person_id
    _id = 'switch-' + sha('|'.join([ep['persona'], kind, target]).encode())[:16]
    current = store.db.switches.find_one({'_id': _id})
    doc = {'_id': _id, 'persona': ep['persona'], 'kind': kind, 'label': label,
           **({'scene_id': scene_id} if scene_id else {}), **({'person_id': person_id} if person_id else {}),
           **({'tools': sorted(set(tools))} if tools is not None else {}),
           'until': (moment + timedelta(hours=hours_of(hours))).isoformat(), 'state': 'on', 'set_at': now(),
           'set_in': ep['_id'], **({'why': why} if why else {})}
    store.put('switches', doc, expected=current and current['revision'], stream='switches:' + ep['persona'])
    store.audit(ep['_id'], 'switch.set', {k: v for k, v in doc.items() if k != 'revision'}, ep['scope_key'])
    return doc


def clear(store, ep, switch_id):
    row = store.db.switches.find_one({'_id': str(switch_id or '').strip(), 'persona': ep['persona'], 'state': 'on'})
    if not row:
        raise Denied('SWITCH_NOT_FOUND: ' + ('没写是哪个开关' if not switch_id else '「%s」不是开着的开关（可能已经到期了）' % switch_id))
    store.put('switches', {**row, 'state': 'cleared', 'cleared_at': now()}, expected=row['revision'],
              stream='switches:' + ep['persona'])
    store.audit(ep['_id'], 'switch.cleared', {'switch': row['_id'], 'kind': row['kind']}, ep['scope_key'])
    return row


def on(store, *, kind=None, scene_id=None, person_id=None, moment=None):
    """The switches on now (not cleared, not past their end)."""
    query = {'state': 'on', 'until': {'$gt': _moment(moment).isoformat()}}
    for key, value in (('kind', kind), ('scene_id', scene_id), ('person_id', person_id)):
        if value is not None:
            query[key] = value
    return list(store.db.switches.find(query).sort('until', 1))


def muted(store, scene_id, moment=None):
    found = on(store, kind='mute', scene_id=scene_id, moment=moment)
    return found[0] if found else None


def tools_off(store, scene_id, moment=None):
    """tool name -> the switch that turned it off in this conversation."""
    return {tool: row for row in on(store, kind='tools_off', scene_id=scene_id, moment=moment) for tool in row['tools']}


def blocked(store, person_id, moment=None):
    found = on(store, kind='block', person_id=person_id, moment=moment) if person_id else []
    return found[0] if found else None


def _item(row):
    what = WORDS[row['kind']] + '：' + row['label'] + ('（%s）' % '、'.join(row['tools']) if row.get('tools') else '')
    return {'id': row['_id'], 'what': what, 'until_at': row['until'], **({'why': row['why']} if row.get('why') else {})}


def here_block(store, scene_id, moment=None):
    """switches_from_program in the switched conversation: what she switched here from home, and until when."""
    rows = [row for row in on(store, scene_id=scene_id, moment=moment) if row['kind'] != 'block']
    return {'items': [_item(row) for row in rows], 'note': NOTE} if rows else None


def home_block(store, persona, moment=None):
    """switches_from_program at home: every switch on, and the ones that ended in the last hours (said once a while)."""
    moment = _moment(moment)
    rows = [row for row in on(store, moment=moment) if row['persona'] == persona]
    since = (moment - ENDED_SHOWN).isoformat()
    ended = list(store.db.switches.find({'persona': persona, '$or': [
        {'state': 'on', 'until': {'$lte': moment.isoformat(), '$gt': since}},
        {'state': 'cleared', 'cleared_at': {'$gt': since}}]}))
    if not rows and not ended:
        return None
    return {'note': NOTE, **({'items': [_item(row) for row in rows]} if rows else {}),
            **({'ended': [{'what': _item(row)['what'], 'ended_at': row.get('cleared_at') or row['until'],
                           'how': '你提前关的' if row['state'] == 'cleared' else '到时间自己结束了'} for row in ended]}
               if ended else {})}
