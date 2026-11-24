"""Her switches (ADR-052): mute a group, turn tools off in a conversation, block a person.

A switch lasts until she ends it, or for the number of hours she gives it (ADR-135 D3): one with no end has no
`until`. The program keeps them and lists them at home only: every one that is on, and the ones that ended lately.
She sets them with tools she has: mute with `group_focus`, block with `watch` op `block` (the person speaking to her),
tools off and an early end with `set_policy`.

- Muted: the group rests (focus.active is false: only words addressed to her wake her, no first word from her, no
  summaries) and she does not visit it; it stays in her heartbeat marked muted.
- Tools off: they leave the conversation's tool list while the switch is on (role_tools.switched_off).
- Blocked: that account's lines are kept and searchable but wake her nowhere and do not count as addressed to her.
"""
from __future__ import annotations

from datetime import timedelta

from . import clock
from .evidence import sha
from .records.view import ANY, View, fenced, is_text, pinned
from .state import Denied, now
from .store.words import And, Exists, Or, Range
from .config import echoed

ENDED_SHOWN = timedelta(hours=12)                # an ended switch is listed at home this long, then gone
KEEP = ('think', 'recall', 'end_turn')          # a turn needs these: never switched off (end_turn: ADR-131)
WORDS = {'mute': '静音', 'tools_off': '关了工具', 'block': '屏蔽'}
OPEN = '一直开着，到你结束它'                     # how a switch with no end reads
NOTE = ('你自己开着的开关（静音、关工具、屏蔽）：写着 until_at 的到点自己结束，别的一直开着；要结束，在家里用 set_policy：'
        'key=switch_off，value 写开关的 id。ended 是最近结束的。')


def _moment(moment=None):
    return moment or clock.now()


# ── the owner of `switches` ──
# Read and written only through these: a switch as stored. None follows the store's rule (ADR-104 section 4): an id,
# the persona, a conversation or a person given None, or a value not of its kind, finds nothing without a read; a
# kind or a state given None finds the switches without one. Not given is `ANY`.
COLLECTION = 'switches'


def get(store, switch_id, *, persona=ANY, state=ANY):
    """The switch with this id (of this persona, in this state), or None."""
    if not is_text(switch_id):
        return None
    if persona is ANY and state is ANY:
        return store.collection(COLLECTION).get(switch_id)
    where = pinned(fenced({'_id': switch_id}, {'persona': (persona, is_text)}), {'state': (state, is_text)})
    return View(store, COLLECTION, where).first()


def on(store, *, kind=ANY, scene_id=ANY, person_id=ANY, moment=None):
    """The switches on now (not cleared, not past their end; one with no end is on until she clears it), those with
    an end first, the soonest first."""
    where = pinned(fenced({'state': 'on'}, {'scene_id': (scene_id, is_text), 'person_id': (person_id, is_text)}),
                   {'kind': (kind, is_text)})
    if where is not None:
        where = And(where, Or({'until': Range(gt=_moment(moment).isoformat())}, {'until': Exists(False)}))
    rows = View(store, COLLECTION, where).rows()
    return sorted(rows, key=lambda row: (row.get('until') is None, row.get('until') or '', row['_id']))


def changed(store, persona, since, moment):
    """A persona's switches that ended after `since` (ISO text) and by `moment`: run out, or cleared by her."""
    where = fenced({}, {'persona': (persona, is_text)}) if is_text(since) else None
    if where is not None:
        where = And(where, Or({'state': 'on', 'until': Range(lte=moment.isoformat(), gt=since)},
                              {'state': 'cleared', 'cleared_at': Range(gt=since)}))
    return View(store, COLLECTION, where).rows()


def save(store, row, **kwargs):
    """The revisioned write of a switch (`Store.put`: `expected`, `stream`)."""
    return store.put(COLLECTION, row, **kwargs)


def hours_of(value):
    """The hours a switch lasts: None (until she ends it) when not given, else a whole number of at least 1."""
    if value is None:
        return None
    try:
        hours = int(value)
    except (TypeError, ValueError):
        raise Denied('SWITCH_HOURS_INVALID: hours 给的是「%s」，要写一个整数，或者不写' % echoed(value)) from None
    if hours < 1 or str(value).strip() not in (str(hours), str(float(hours))):
        raise Denied('SWITCH_HOURS_INVALID: hours 给的是「%s」，要写一个整数，或者不写' % echoed(value))
    return hours


def ends(row):
    """How a switch ends, for what she reads: its time, or that it has none."""
    return {'until_at': row['until']} if row.get('until') else {'lasts': OPEN}


def set_switch(store, ep, kind, *, label, scene_id=None, person_id=None, tools=None, hours=None, why=None,
               moment=None, ready=None):
    """One switch per kind and target; setting it again replaces it (a new end, new tools). `ready`, when given, runs
    after the checks and before the write (a caller's checkpoint, ADR-132 D2)."""
    moment = _moment(moment)
    target = scene_id if kind != 'block' else person_id
    _id = 'switch-' + sha('|'.join([ep['persona'], kind, target]).encode())[:16]
    current = get(store, _id)
    hours = hours_of(hours)
    doc = {'_id': _id, 'persona': ep['persona'], 'kind': kind, 'label': label,
           **({'scene_id': scene_id} if scene_id else {}), **({'person_id': person_id} if person_id else {}),
           **({'tools': sorted(set(tools))} if tools is not None else {}),
           **({'until': (moment + timedelta(hours=hours)).isoformat()} if hours else {}), 'state': 'on', 'set_at': now(),
           'set_in': ep['_id'], **({'why': why} if why else {})}
    if ready:
        ready()
    save(store, doc, expected=current and current['revision'], stream='switches:' + ep['persona'])
    store.audit(ep['_id'], 'switch.set', {k: v for k, v in doc.items() if k != 'revision'}, ep['scope_key'])
    return doc


def clear(store, ep, switch_id, ready=None):
    """End a switch early; `ready` as in `set_switch`."""
    row = get(store, str(switch_id or '').strip(), persona=ep['persona'], state='on')
    if not row:
        raise Denied('SWITCH_NOT_FOUND: ' + ('没写是哪个开关' if not switch_id else '「%s」不是开着的开关（可能已经到期了）' % echoed(switch_id)))
    if ready:
        ready()
    save(store, {**row, 'state': 'cleared', 'cleared_at': now()}, expected=row['revision'],
         stream='switches:' + ep['persona'])
    store.audit(ep['_id'], 'switch.cleared', {'switch': row['_id'], 'kind': row['kind']}, ep['scope_key'])
    return row


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
    return {'id': row['_id'], 'what': what, **ends(row), **({'why': row['why']} if row.get('why') else {})}


def home_block(store, persona, moment=None):
    """switches_from_program at home: every switch on, and the ones that ended in the last hours (said once a while)."""
    moment = _moment(moment)
    rows = [row for row in on(store, moment=moment) if row['persona'] == persona]
    since = (moment - ENDED_SHOWN).isoformat()
    ended = changed(store, persona, since, moment)
    if not rows and not ended:
        return None
    return {'note': NOTE, **({'items': [_item(row) for row in rows]} if rows else {}),
            **({'ended': [{'what': _item(row)['what'], 'ended_at': row.get('cleared_at') or row['until'],
                           'how': '你提前关的' if row['state'] == 'cleared' else '到时间自己结束了'} for row in ended]}
               if ended else {})}
