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

from . import clock
from . import visibility
from .config import excerpt
from .evidence import sha
from .state import Denied, now
from .records import scenes as scene_records
from .records.view import ANY, View, fenced, is_text, pinned
from .store.words import Increase, Not, Range, Set

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


# ── the owner of `watches` ──
# Read and written only through these: a watch as stored. None follows the store's rule (ADR-104 section 4): an id,
# the persona or the person given None, or a value not of its kind, finds nothing without a read; a state given None
# finds the watches without one. Not given is `ANY`.
COLLECTION = 'watches'


def get(store, watch_id, *, persona=ANY, state=ANY):
    """The watch with this id (of this persona, in this state), or None."""
    if not is_text(watch_id):
        return None
    if persona is ANY and state is ANY:
        return store.collection(COLLECTION).get(watch_id)
    where = pinned(fenced({'_id': watch_id}, {'persona': (persona, is_text)}), {'state': (state, is_text)})
    return View(store, COLLECTION, where).first()


def active(store, persona):
    """View: a persona's watches that are on, the soonest to end first."""
    return View(store, COLLECTION, fenced({'state': 'on'}, {'persona': (persona, is_text)}), (('until', 1),))


def of_person(store, persona, person, moment):
    """View: a persona's watches on this person that are on and not past their end at `moment`."""
    return View(store, COLLECTION, fenced({'state': 'on', 'until': Range(gt=moment.isoformat())},
                                          {'persona': (persona, is_text), 'person': (person, is_text)}))


def count_active(store, persona, moment, *, besides):
    """How many of a persona's watches are on and not past their end at `moment`, other than `besides`."""
    return View(store, COLLECTION, fenced({'state': 'on', 'until': Range(gt=moment.isoformat()), '_id': Not(besides)},
                                          {'persona': (persona, is_text)})).count()


def mark_seen(store, watch_id, last_seen_at, moment, *, appeared):
    """The watch saw its person at `moment`, if its `last_seen_at` is still the one read (None: none yet); `appeared`
    counts one more appearance. Whether this write changed it."""
    where = pinned({'_id': watch_id}, {'last_seen_at': (last_seen_at, is_text)})
    if not is_text(watch_id) or where is None:
        return False
    change = [Set({'last_seen_at': moment.isoformat()}), *([Increase('appeared')] if appeared else [])]
    return store.collection(COLLECTION).update(where, change).changed == 1


def save(store, row, **kwargs):
    """The revisioned write of a watch (`Store.put`: `expected`, `stream`, `reset_counters`)."""
    return store.put(COLLECTION, row, **kwargs)


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


def _why(row, cls, store=None):
    """Her reason, where it may be read: one written at home stays at home. One written outside says so at home
    (ADR-018 §6): it may carry someone else's intent."""
    if not row.get('why') or (row.get('set_class') != visibility.PUBLIC and cls != visibility.OWNER_PRIVATE):
        return None
    if store is not None and cls == visibility.OWNER_PRIVATE and row.get('set_class') == visibility.PUBLIC:
        from .people import People
        return '%s（在%s写的）' % (row['why'], People(store).scene_title(scene_records.get(store, row.get('set_in'))))
    return row['why']


# ── adding and stopping ─────────────────────────────────────────────
def add(store, ep, persona, cls, args):
    """Watch someone she can see in this conversation (a label, #number or name that names exactly one person)."""
    from .people import People
    given = args.get('hours')
    try:
        hours = int(given)
    except (TypeError, ValueError):
        raise Denied('WATCH_HOURS_INVALID: ' + ('没写 hours' if given is None else 'hours 给的是「%s」' % given)) from None
    if not 1 <= hours <= WATCH_MAX_HOURS:
        raise Denied('WATCH_HOURS_INVALID: hours 给的是 %d' % hours)
    mode = args.get('mode') or 'once'
    if mode not in MODES:
        raise Denied('WATCH_MODE_INVALID: how_often 给的是「%s」' % mode)
    why = excerpt(' '.join(str(args.get('why') or '').split()), 100) or None
    scene = scene_records.get(store, ep['scene_id'])
    people = People(store)
    found = people.resolve(scene, args.get('person'))
    if len(found) != 1:
        raise Denied('WATCH_PERSON_UNCLEAR: 「%s」对得上 %s' % (args.get('person'), '、'.join(people.label(d) for d in found[:5]))
                     if found else 'WATCH_PERSON_NOT_HERE: ' + ('没写 person' if not args.get('person')
                                                               else '这里没有「%s」' % args.get('person')))
    person = found[0]['person']
    _id = 'watch-' + sha((persona + '|' + person).encode())[:12]
    current = get(store, _id)
    moment = clock.now()
    watching = count_active(store, persona, moment, besides=_id)
    if watching >= WATCH_MAX:
        raise Denied('WATCH_LIST_FULL: 正在盯 %d 个，上限 %d 个' % (watching, WATCH_MAX))
    doc = {'_id': _id, 'persona': persona, 'person': person, 'name': people.shown(found[0]) or people.label(found[0]),
           'set_in': scene['_id'], 'set_class': cls, 'why': why, 'mode': mode, 'state': 'on',
           'created_at': now(), 'until': (moment + timedelta(hours=hours)).isoformat(),
           'appeared': 0, 'last_seen_at': None}
    # A new watch on the same person replaces the old one and counts its sightings from nothing.
    save(store, doc, expected=current and current['revision'], stream='watches:' + persona, reset_counters=True)
    return {'watching': doc['name'], 'id': _id, 'how': MODE_WORDS[mode], 'for': '%d 小时' % hours}


def stop(store, persona, watch_id):
    row = get(store, str(watch_id or '').strip(), persona=persona, state='on')
    if not row:
        raise Denied('WATCH_NOT_FOUND: ' + ('没写 id' if not watch_id else 'id「%s」不在名单上（可能已经到期停了）' % watch_id))
    save(store, {**row, 'state': 'ended', 'ended_at': now()}, expected=row['revision'], stream='watches:' + persona)
    return {'stopped': row['name']}


# ── a line arrives ──────────────────────────────────────────────────
def seen(store, person_id, moment=None):
    """A line from this person, in any of her conversations: the watch that fires for it, else None."""
    persona = _persona(store)
    if not persona or not person_id:
        return None
    moment = moment or clock.now()
    row = of_person(store, persona, _person(store, person_id), moment).first()
    if not row:
        return None
    last = _at(row.get('last_seen_at'))
    fresh = last is None or (moment - last).total_seconds() > WATCH_QUIET_MINUTES * 60
    # Only one of two lines arriving together wins the new appearance.
    if not mark_seen(store, row['_id'], row.get('last_seen_at'), moment, appeared=fresh):
        return None
    if not fresh or (row['mode'] == 'once' and row.get('appeared')):
        return None
    if row['mode'] == 'once':
        done = get(store, row['_id'])
        save(store, {**done, 'state': 'done', 'ended_at': now()}, expected=done['revision'], stream='watches:' + persona)
    return row


# ── what her turn sees ──────────────────────────────────────────────
def watching_block(store, persona, cls, moment):
    """watching_from_program: who she watches, and how a watch that ran out went (told once)."""
    rows = active(store, persona).rows()
    if not rows:
        return None
    items, ended = [], []
    for row in rows:
        until = _at(row['until'])
        if until and until <= moment:
            ended.append({'who': row['name'], 'ended': '到期了，盯着的这段时间他' + _tier(APPEARED_WORDS, row.get('appeared') or 0)})
            save(store, {**row, 'state': 'ended', 'ended_at': now()}, expected=row['revision'],
                 stream='watches:' + persona)
            continue
        hours = (until - moment).total_seconds() / 3600 if until else 0
        items.append({'id': row['_id'], 'who': row['name'], 'left': _tier(LEFT_WORDS, hours), 'how': MODE_WORDS[row['mode']],
                      **({'why': _why(row, cls, store)} if _why(row, cls) else {})})
    out = {}
    if items:
        out.update(items=items, note=WATCHING_NOTE)
    if ended:
        out['ran_out'] = ended
    return out or None


def watched_block(store, event, cls):
    """watched_from_program: this line is from someone she watches."""
    row = get(store, event.get('watched')) if event.get('watched') else None
    if not row:
        return None
    return {'who': row['name'], 'how': MODE_WORDS[row['mode']], **({'why': _why(row, cls, store)} if _why(row, cls) else {}),
            'note': WATCHED_NOTE}
