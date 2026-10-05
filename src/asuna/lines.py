"""Her own open/close of a peer line (ADR-013 §6).

A peer line is a direct-message route of a channel kind that declares ``PEER_LINE`` (another agent, e.g. the
dsh-peer channel). While she has it closed, the channel API passes the peer's messages over (``line_closed``)
instead of waking her; her own words still go out, since speaking is her choice. She picks a category; the
program maps it to a time and shows her the state in words. The owner may also close the bridge itself
(its ``closedUntil``); that is a separate switch she does not see.
"""
from datetime import datetime, timedelta, timezone

from . import channel_kinds
from .state import now

CLOSE_FOR = ('an_hour', 'until_morning', 'until_reopened')
MORNING_HOUR = 8


def peer_lines(store):
    """[{scene_id, person_id, label}] of the configured peer-line routes."""
    out = []
    for channel_id, channel in (store.config.get('channels') or {}).items():
        kind = channel_kinds.get(channel_id)
        if not getattr(kind, 'PEER_LINE', False):
            continue
        for route in channel.get('routes', {}).values():
            if route['target']['type'] != 'dm':
                continue
            identity = store.db.identities.find_one({'_id': route['person_id']}, {'display_name': 1}) or {}
            out.append({'scene_id': route['scene_id'], 'person_id': route['person_id'],
                        'label': identity.get('display_name') or route['person_id']})
    return out


def _row(store, scene_id):
    return store.db.artifacts.find_one({'_id': 'peer-line:' + scene_id})


def closed_until(store, scene_id, moment=None):
    """None when open; a datetime when closed until then; ``'reopen'`` when closed until she reopens it."""
    row = _row(store, scene_id)
    if not row or not row.get('closed'):
        return None
    if row.get('until_reopened'):
        return 'reopen'
    until = datetime.fromisoformat(row['closed_until'])
    return until if until > (moment or datetime.now(timezone.utc)) else None


def is_closed(store, scene_id, moment=None):
    return closed_until(store, scene_id, moment) is not None


def _morning(moment, zone):
    from zoneinfo import ZoneInfo
    local = moment.astimezone(ZoneInfo(zone))
    morning = local.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    return (morning if morning > local else morning + timedelta(days=1)).astimezone(timezone.utc)


def set_line(store, scene_id, *, closed, choice=None, zone='UTC', moment=None, by='character'):
    moment = moment or datetime.now(timezone.utc)
    row = _row(store, scene_id) or {'_id': 'peer-line:' + scene_id, 'kind': 'peer-line', 'scene_id': scene_id,
                                     'scope_key': 'scene:' + scene_id}
    value = {**row, 'closed': closed, 'changed_at': now(), 'changed_by': by, 'until_reopened': False, 'closed_until': None}
    if closed:
        if choice not in CLOSE_FOR:
            raise ValueError('LINE_CLOSE_FOR_INVALID')
        if choice == 'until_reopened':
            value['until_reopened'] = True
        else:
            until = moment + timedelta(hours=1) if choice == 'an_hour' else _morning(moment, zone)
            value['closed_until'] = until.isoformat()
    return store.put('artifacts', value, expected=row.get('revision'), stream='peer-line:' + scene_id)


def describe(until, zone):
    """The state in words."""
    if until is None:
        return '开着：对方的话会直接到你这里，叫醒你。'
    if until == 'reopen':
        return '关着，等你自己打开：这期间对方的话不会到你这里，也不会以后补给你。'
    from zoneinfo import ZoneInfo
    local = until.astimezone(ZoneInfo(zone))
    return '关着，到 %d月%d日 %02d:%02d 自己打开：这期间对方的话不会到你这里，也不会以后补给你。' % (
        local.month, local.day, local.hour, local.minute)


def view(store, lines, zone, moment=None):
    return {'items': [{'line': line['label'], 'state': describe(closed_until(store, line['scene_id'], moment), zone)}
                      for line in lines],
            'note': '这是你和另一个智能体之间的线。开关由你自己决定（peer_line）：关着时她的话会被跳过、不补发；'
                    '你自己的话照常发得出去。'}
