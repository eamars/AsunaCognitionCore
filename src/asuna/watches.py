"""Her watchlist (owner 2026-10-06): people she wants to hear about when they speak, in any conversation.

She adds someone she can see in the conversation she is in, for a while (WATCH_MAX_HOURS at most, WATCH_MAX
people at once). When that person speaks in any of her conversations, she hears of it there, where they spoke:
in a group their line gets her one look through the relevance gate (wake reason ``watched``, like an awaited
answer); in a private chat, where every line is already her turn, the turn says so. Nothing they say is copied
into another conversation.

- ``once`` (the default): the first time they speak, then the watch is done.
- ``burst``: each time they start speaking again after WATCH_QUIET_MINUTES of silence, until it expires.

Firing is event-driven: a line from someone nobody watches costs one indexed lookup. An expired watch is not a
turn of its own: her next turn carries one line on how it went. A why she wrote at home is shown only at home.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import visibility
from .config import excerpt
from .evidence import sha
from .state import Denied, now

WATCH_MAX = 5
WATCH_MAX_HOURS = 72
WATCH_QUIET_MINUTES = 10
MODES = ('once', 'burst')
MODE_WORDS = {'once': '他第一次说话时叫你，然后就不盯了',
              'burst': '他每次沉默十分钟以上再开口都叫你，到期为止'}
LEFT_WORDS = ((1, '不到一小时'), (6, '几个小时'), (24, '今天之内'), (None, '一天以上'))
APPEARED_WORDS = ((1, '一次也没出现'), (2, '出现过一次'), (3, '出现过两次'), (None, '出现过好几次'))
WATCHING_NOTE = ('这是你在盯着的人（watch）：他在你任何一个对话里说话，你会在那个对话里知道。'
                 '不想盯了用 watch 的 off（id 照抄）；到期会自己停。')
WATCHED_NOTE = ('你在盯着这个人（watch），他刚在这里说话了；这句不一定是对你说的，接不接由你。'
                '这是名单上的人出现了，跟你刚那句在不在等回话（awaited_from_program）是两回事。')


def _at(value):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _tier(table, value):
    for limit, words in table:
        if limit is None or value < limit:
            return words
    return table[-1][1]


def _persona(store):
    return (store.config.get('chat') or {}).get('persona')


def _person(store, person_id):
    from .people import People
    return People(store).person(person_id)


def _why(row, cls):
    """Her reason, where it may be read: one written at home stays at home."""
    if row.get('why') and (row.get('set_class') == visibility.PUBLIC or cls == visibility.OWNER_PRIVATE):
        return row['why']
    return None


# ── adding and stopping ─────────────────────────────────────────────
def add(store, ep, persona, cls, args):
    """Watch someone she can see in this conversation (a label, #number or name that names exactly one person)."""
    from .people import People
    hours = args.get('hours')
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise Denied('WATCH_HOURS_INVALID')
    if not 1 <= hours <= WATCH_MAX_HOURS:
        raise Denied('WATCH_HOURS_INVALID')
    mode = args.get('mode') or 'once'
    if mode not in MODES:
        raise Denied('WATCH_MODE_INVALID')
    why = excerpt(' '.join(str(args.get('why') or '').split()), 100) or None
    scene = store.db.scenes.find_one({'_id': ep['scene_id']})
    people = People(store)
    found = people.resolve(scene, args.get('person'))
    if len(found) != 1:
        raise Denied('WATCH_PERSON_UNCLEAR' if found else 'WATCH_PERSON_NOT_HERE')
    person = found[0]['person']
    _id = 'watch-' + sha((persona + '|' + person).encode())[:12]
    current = store.db.watches.find_one({'_id': _id})
    moment = datetime.now(timezone.utc)
    active = store.db.watches.count_documents({'persona': persona, 'state': 'on', 'until': {'$gt': moment.isoformat()},
                                               '_id': {'$ne': _id}})
    if active >= WATCH_MAX:
        raise Denied('WATCH_LIST_FULL')
    doc = {'_id': _id, 'persona': persona, 'person': person, 'name': people.shown(found[0]) or people.label(found[0]),
           'set_in': scene['_id'], 'set_class': cls, 'why': why, 'mode': mode, 'state': 'on',
           'created_at': now(), 'until': (moment + timedelta(hours=hours)).isoformat(),
           'appeared': 0, 'last_seen_at': None}
    store.put('watches', doc, expected=current and current['revision'], stream='watches:' + persona)
    return {'watching': doc['name'], 'id': _id, 'how': MODE_WORDS[mode], 'for': '%d 小时' % hours}


def stop(store, persona, watch_id):
    row = store.db.watches.find_one({'_id': str(watch_id or '').strip(), 'persona': persona, 'state': 'on'})
    if not row:
        raise Denied('WATCH_NOT_FOUND')
    store.put('watches', {**row, 'state': 'ended', 'ended_at': now()},
              expected=row['revision'], stream='watches:' + persona)
    return {'stopped': row['name']}


# ── a line arrives ──────────────────────────────────────────────────
def seen(store, person_id, moment=None):
    """A line from this person, in any of her conversations: the watch that fires for it, else None."""
    persona = _persona(store)
    if not persona or not person_id:
        return None
    moment = moment or datetime.now(timezone.utc)
    row = store.db.watches.find_one({'persona': persona, 'person': _person(store, person_id), 'state': 'on',
                                     'until': {'$gt': moment.isoformat()}})
    if not row:
        return None
    last = _at(row.get('last_seen_at'))
    fresh = last is None or (moment - last).total_seconds() > WATCH_QUIET_MINUTES * 60
    update = {'$set': {'last_seen_at': moment.isoformat()}, **({'$inc': {'appeared': 1}} if fresh else {})}
    # Only one of two lines arriving together wins the new appearance.
    if store.db.watches.update_one({'_id': row['_id'], 'last_seen_at': row.get('last_seen_at')}, update).modified_count != 1:
        return None
    if not fresh or (row['mode'] == 'once' and row.get('appeared')):
        return None
    if row['mode'] == 'once':
        done = store.db.watches.find_one({'_id': row['_id']})
        store.put('watches', {**done, 'state': 'done', 'ended_at': now()},
                  expected=done['revision'], stream='watches:' + persona)
    return row


# ── what her turn sees ──────────────────────────────────────────────
def watching_block(store, persona, cls, moment):
    """watching_from_program: who she watches, and how a watch that ran out went (told once)."""
    rows = list(store.db.watches.find({'persona': persona, 'state': 'on'}).sort('until', 1))
    if not rows:
        return None
    items, ended = [], []
    for row in rows:
        until = _at(row['until'])
        if until and until <= moment:
            ended.append({'who': row['name'], 'ended': '到期了，盯着的这段时间他' + _tier(APPEARED_WORDS, row.get('appeared') or 0)})
            store.put('watches', {**row, 'state': 'ended', 'ended_at': now()},
                      expected=row['revision'], stream='watches:' + persona)
            continue
        hours = (until - moment).total_seconds() / 3600 if until else 0
        items.append({'id': row['_id'], 'who': row['name'], 'left': _tier(LEFT_WORDS, hours), 'how': MODE_WORDS[row['mode']],
                      **({'why': _why(row, cls)} if _why(row, cls) else {})})
    out = {}
    if items:
        out.update(items=items, note=WATCHING_NOTE)
    if ended:
        out['ran_out'] = ended
    return out or None


def watched_block(store, event, cls):
    """watched_from_program: this line is from someone she watches."""
    row = store.db.watches.find_one({'_id': event.get('watched')}) if event.get('watched') else None
    if not row:
        return None
    return {'who': row['name'], 'how': MODE_WORDS[row['mode']], **({'why': _why(row, cls)} if _why(row, cls) else {}),
            'note': WATCHED_NOTE}
