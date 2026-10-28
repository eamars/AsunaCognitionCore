"""Her own mute in a group: one state slot per group conversation, so she knows where her words cannot go out.

The slot (`own_mutes`, one row per scene) says whether she is muted there, since when if known, until when if known,
whether it is the whole group, and by whom (a person id; she reads that person's label in this group, or that it is
not known). It is set by:
- the channel adapter, `POST /v1/channels/<id>/own_mute`: a platform notice that she was muted or unmuted (or the
  whole group), and the adapter's own look at the platform (`source` `lookup`: at start, and after a send refused
  for a mute);
- a send the adapter reports `failed` with `response.reason` `muted`.
It is cleared by a lift, by a look that finds no mute, by its end time passing, and by any of her messages the
platform accepts there. A whole-group mute does not hold her where she is the group's owner or an admin. Nothing is
ever held back because of it: a send is always tried, so a mute lifted early is never blocked by stale state.

She reads it in words, on her clock (`line`, `place_words`): in every turn in that group, in her places at home, and
as the reason on a line of hers that did not go out (`FAILED_WORDS`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from .state import Conflict, now
from .records import scenes as scene_records

SOURCES = ('notice', 'lookup')                     # what the adapter may post; receipts add send_failed and sent
REASON = 'muted'                                   # a failed receipt's response.reason for a send refused by a mute
FAILED_WORDS = '没发出去：你在这个群被禁言了'
UNKNOWN_UNTIL = '到什么时候不知道'
UNKNOWN_BY = {False: '谁禁的不知道', True: '谁开的不知道'}
NOTE_TURN = '你说的话发不出去'
NOTE_PLACE = '去了能看、能写笔记，说话发不出去'
MAX_SECONDS = 400 * 86400                          # an end further away than this is not a time the platform gives


def _moment(moment=None):
    return moment or datetime.now(timezone.utc)


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def row_of(store, scene_id):
    return store.db.own_mutes.find_one({'_id': 'own-mute|' + scene_id})


def active(store, scene_id, moment=None):
    """The mute on her in this group now, or None (not muted, lifted, or past its end)."""
    row = row_of(store, scene_id)
    if not row or not row.get('muted'):
        return None
    if row.get('until') and row['until'] <= _moment(moment).isoformat():
        return None
    return row


def _her_role(store, scene):
    from .people import People
    return People(store).self_role(scene)


def apply(store, scene, *, muted, source, whole_group=False, until=None, by=None, at=None, moment=None):
    """Set or clear the slot; returns what it now says ('muted', 'cleared', 'unchanged' or 'not_her')."""
    moment = _moment(moment)
    if muted and whole_group and _her_role(store, scene) in ('owner', 'admin'):
        return 'not_her'                                  # a whole-group mute does not hold the owner or an admin
    for _ in range(3):
        current = row_of(store, scene['_id'])
        on = active(store, scene['_id'], moment)
        base = {'_id': 'own-mute|' + scene['_id'], 'scene_id': scene['_id'], 'scope_key': scene.get('scope_key'),
                'updated_at': now(), 'source': source}
        if muted:
            same = on is not None and bool(on.get('whole_group')) == bool(whole_group)
            if source == 'send_failed' and on is not None:
                return 'unchanged'                        # already known; the refused send adds nothing
            doc = {**base, 'muted': True, 'whole_group': bool(whole_group),
                   'since': at or (on.get('since') if same else None) or (now() if source == 'notice' else None),
                   'until': until if until is not None else (on.get('until') if same and source == 'send_failed' else None),
                   'by': by or (on.get('by') if same else None)}
        else:
            if on is None:
                return 'unchanged'
            if source == 'notice' and bool(on.get('whole_group')) != bool(whole_group):
                return 'unchanged'                        # lifting the other kind of mute leaves this one
            doc = {**base, 'muted': False, 'whole_group': bool(on.get('whole_group')), 'since': on.get('since'),
                   'until': on.get('until'), 'by': on.get('by'), 'cleared_at': now(), 'cleared_by': source}
        try:
            store.put('own_mutes', doc, expected=current['revision'] if current else None,
                      stream='own_mute:' + scene['_id'])
            return 'muted' if muted else 'cleared'
        except Conflict:
            continue
    raise Conflict('OWN_MUTE_BUSY: 这个群的禁言状态刚被别处改过，这次没写进去；重试一次')


def _scene_of_group(store, channel_id, group):
    from .group_members import routed_group
    route = routed_group(store, channel_id, group, 'OWN_MUTE')
    scene = scene_records.get(store, route['scene_id'])
    if not scene:
        raise PermissionError('OWN_MUTE_SCENE_UNKNOWN: 这个群还没有对话记录；有人说过话以后再送')
    return scene


def receive(store, channel_id, body):
    """POST /v1/channels/<id>/own_mute: {group_id, source, muted, whole_group?, until?, operator_id?, at?}."""
    from . import channel_kinds
    if set(body) - {'group_id', 'source', 'muted', 'whole_group', 'until', 'operator_id', 'at'}:
        raise PermissionError('OWN_MUTE_FIELD_DENIED: 只收 group_id、source、muted、whole_group、until、operator_id、at')
    group = str(body.get('group_id') or '')
    if body.get('source') not in SOURCES or not isinstance(body.get('muted'), bool) \
            or not isinstance(body.get('whole_group', False), bool):
        raise ValueError('OWN_MUTE_INVALID: source 要是 %s 之一，muted 和 whole_group 要是真假值' % '、'.join(SOURCES))
    epochs = {}
    for key in ('until', 'at'):
        value = body.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or not 0 < value < datetime.now(timezone.utc).timestamp() + MAX_SECONDS):
            raise ValueError('OWN_MUTE_INVALID: %s 要是平台给的秒数时间（给的是 %r）' % (key, value))
        epochs[key] = _iso(value) if value else None
    operator = body.get('operator_id')
    account = channel_kinds.of_channel(channel_id).ACCOUNT
    if operator is not None and not (isinstance(operator, str) and account.fullmatch(operator)):
        raise ValueError('OWN_MUTE_INVALID: operator_id 要是一个账号（给的是 %r）' % (operator,))
    scene = _scene_of_group(store, channel_id, group)
    by = None
    if operator:
        from .people import People
        people = People(store)
        by = people.person(people.account_person(scene['_id'], operator))
    status = apply(store, scene, muted=body['muted'], source=body['source'], whole_group=body.get('whole_group', False),
                   until=epochs['until'], by=by, at=epochs['at'])
    return {'status': status}


def after_receipt(store, row, state, body):
    """A send's receipt: refused for a mute sets the slot; one the platform accepted clears it."""
    scene = scene_records.get(store, row.get('scene_id')) if row.get('scene_id') else None
    if not scene or scene.get('kind') != 'group':
        return None
    if state == 'FAILED' and (body.get('response') or {}).get('reason') == REASON:
        return apply(store, scene, muted=True, source='send_failed')
    if state == 'DELIVERED' and active(store, scene['_id']) is not None:
        return apply(store, scene, muted=False, source='sent')
    return None


def _parts(store, scene, row, zone):
    from .people import People
    from .schedule_rules import line_stamp
    whole = bool(row.get('whole_group'))
    until = ('到 ' + line_stamp(zone, row['until'])) if row.get('until') else UNKNOWN_UNTIL
    who = None
    if row.get('by'):
        people = People(store)
        doc = people.roster(scene['_id']).get(scene['_id'] + '|' + row['by'])
        who = people.label(doc) if doc else None
    by = (who + ('开的' if whole else '禁的')) if who else UNKNOWN_BY[whole]
    head = '这个群开着全员禁言' if whole else '你在这个群被禁言了'
    return head, until, by


def line(store, scene, zone, moment=None):
    """Her turn's line in a group where she is muted, or None: muted, until when on her clock, by whom."""
    row = active(store, scene['_id'], moment)
    if row is None:
        return None
    head, until, by = _parts(store, scene, row, zone)
    return '%s，%s，%s：%s。' % (head, until, by, NOTE_TURN)


def place_words(store, scene, zone, moment=None):
    """The same in her places at home, said for choosing whether to go."""
    row = active(store, scene['_id'], moment)
    if row is None:
        return None
    head, until, by = _parts(store, scene, row, zone)
    return '%s，%s，%s；%s' % (head, until, by, NOTE_PLACE)
