"""Quiet-time upkeep of a group (ADR-049): what she learns there and condensing its conversation early.

On a visit, or at home in her heartbeat or reflection, she may choose to have a group's conversation condensed once
the group has gone quiet (`group_focus` op `condense`; `keep` takes the choice back). A home plan exists only while a
group is marked: every few minutes it condenses the marked groups whose quiet has lasted long enough for how busy they
are, or whose local night it is, through DSH's own compaction of that conversation (host request `compact_session`).
The plugin refuses while a turn of hers runs there; the next look tries again. The next turn there says once that the
conversation was condensed, so she can add to the group's notes what the summary dropped.

A `write_notes` visit also carries a few phrases several people there have used since her last look and that her
group notes do not have yet, for her to work out or skip. Nothing is stored beyond her own notes.

Times, counts and sizes reach her only as words from the tables below (TABLES_VERSION).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

TABLES_VERSION = 1
# Average incoming lines a day over the last week → minutes of quiet before condensing (Xiaoman's measurement,
# 2026-10-12: 8 days of 16 groups; ADR-049).
QUIET_TIERS = ((100, 10), (30, 15), (0, 30))
WEEK_DAYS = 7
NIGHT_HOURS = (1, 7)                  # local night in the group's own clock: condensing waits for no quiet there
PLAN_ID = 'plan-asuna-condense'
UNAVAILABLE = ('no_commands_service', 'no_compact_command')   # the Host has no way to condense: not retried
LOOK_EVERY_SECONDS = 300
# How long a conversation was on its latest request → words (never the number).
SIZE_WORDS = ((40000, '短'), (90000, '中等'), (150000, '长'), (None, '很长'))
SIZE_NOTE = '对话越长，群里安静一阵以后再接话时读回来越慢（很长的要二十来秒）；压过以后前面变成一段摘要，原话就不在眼前了。'
CONDENSED_NOTE = ('这个群的对话%s按你的选择压过了：开头那段摘要就是压缩留下的，更早的原话不在眼前了。'
                  '看一眼摘要，漏了要紧的就补进群笔记。')
CONDENSED_SHOWN_HOURS = 24
# Phrases for a write_notes visit.
PHRASES_SHOWN = 5
PHRASE_MIN_PEOPLE = 3
PHRASE_MIN_DAYS = 3                   # a group's own word comes back on different days; a day's topic does not
PHRASE_COMMON_PEOPLE = 2              # used by this many people ...
PHRASE_COMMON_GROUPS = 2              # ... in this many of her other groups: ordinary talk
PEOPLE_WORDS = ((4, '三个人'), (6, '四五个人'), (None, '好几个人'))
PHRASE_NOTE = ('这几个词（短语）是这里这一周好几个人、好几天都在用，你上次来看以后又出现过，别的群不怎么说，'
               '你的群笔记里还没有的，按用的人多少排。'
               '弄懂一个就把意思写进群笔记，带上是哪天推出来的；看不懂或不值得记就跳过。')
_CJK = re.compile(r'[㐀-鿿]{2,}')
_LATIN = re.compile(r'[A-Za-z][A-Za-z0-9_\-]{2,}')
# A phrase made only of these is ordinary grammar, not a group's word.
FUNCTION_CHARS = frozenset('的了吗呢吧啊呀哦嗯我你他她它们都也就还在是有个上下不没这那么什')
_MARKUP = re.compile(r'\[[^\]]{0,40}\]|@\S+|https?://\S+|att-[0-9a-f]+')


def _at(stamp):
    try:
        moment = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _tier(table, value):
    for limit, word in table:
        if limit is None or value < limit:
            return word
    return table[-1][1]


def per_day(store, scene_id, moment):
    """Average incoming lines a day there over the last week."""
    since = (moment - timedelta(days=WEEK_DAYS)).isoformat()
    return store.db.messages.count_documents({'scene_id': scene_id, 'direction': 'inbound',
                                              'received_at': {'$gte': since}}) / WEEK_DAYS


def quiet_minutes(store, scene_id, moment):
    """How long the group must be quiet before condensing, by how busy it is."""
    busy = per_day(store, scene_id, moment)
    return next(minutes for floor, minutes in QUIET_TIERS if busy >= floor)


def last_line(store, scene_id):
    """When someone other than her last spoke there; her own lines never restart the wait."""
    row = store.db.messages.find_one({'scene_id': scene_id, 'direction': 'inbound'}, {'received_at': 1},
                                     sort=[('received_at', -1)])
    return _at(row['received_at']) if row and row.get('received_at') else None


def night_there(store, scene, moment):
    from .schedule_rules import scene_timezone
    zone = scene_timezone(store.config, scene or {})
    hour = moment.astimezone(zone['tz']).hour
    return NIGHT_HOURS[0] <= hour < NIGHT_HOURS[1]


def due(store, scene, moment):
    """Whether a marked group may be condensed now."""
    if night_there(store, scene, moment):
        return True
    last = last_line(store, scene['_id'])
    return last is None or moment - last >= timedelta(minutes=quiet_minutes(store, scene['_id'], moment))


def size_words(scene):
    tokens = (scene or {}).get('conversation_tokens')
    if not tokens:
        return None
    return {'length': '这个群的对话现在' + _tier(SIZE_WORDS, int(tokens)), 'note': SIZE_NOTE}


def main_session(store, scene, persona):
    """The character session this group's conversation continues in now (native_worker.resolve_role_session):
    (session id, its working folder), or None."""
    primary = store.db.sessions.find_one({'native_host': True, 'main_conversation': True, 'scene_id': scene['_id'],
                                          'persona': persona, 'policy_epoch': scene.get('policy_epoch'),
                                          'character_context': scene.get('character_context')})
    if not primary:
        return None
    session_id, seen = primary['_id'], {primary['_id']}
    while True:
        successor = (store.db.sessions.find_one({'_id': session_id}, {'successor_id': 1}) or {}).get('successor_id')
        if not successor or successor in seen:
            row = store.db.sessions.find_one({'_id': session_id}, {'cwd': 1}) or {}
            return session_id, row.get('cwd') or primary.get('cwd')
        seen.add(successor)
        session_id = successor


# ---- her choice -------------------------------------------------------------------------------------------------
def mark(store, scene, ep, moment=None):
    moment = moment or datetime.now(timezone.utc)
    store.db.scenes.update_one({'_id': scene['_id']}, {'$set': {'condense_wanted': {
        'at': moment.isoformat(), 'episode_id': ep['_id'], 'turn': ep.get('turn_kind') or ep.get('episode_kind')}}})
    store.audit(ep['_id'], 'condense.wanted', {'scene_id': scene['_id']}, ep['scope_key'])
    minutes = quiet_minutes(store, scene['_id'], moment)
    return {'done': '记下了：等这个群安静下来就压一压这段对话',
            'when': ('这个群按它平常的热闹，安静满 %d 分钟、或者那边凌晨一点到七点，就会压；你那时在这里说着话就再等等'
                     % minutes),
            **({'size': size_words(scene)} if size_words(scene) else {})}


def unmark(store, scene, ep):
    store.db.scenes.update_one({'_id': scene['_id']}, {'$unset': {'condense_wanted': ''}})
    store.audit(ep['_id'], 'condense.kept', {'scene_id': scene['_id']}, ep['scope_key'])
    return {'done': '好，这个群的对话先不压了'}


def marked(store):
    return list(store.db.scenes.find({'condense_wanted': {'$exists': True}, 'kind': 'group'}))


# ---- the plan's look --------------------------------------------------------------------------------------------
def look(store, persona, compact, moment=None):
    """Condense every marked group that is due. compact(session_id, scene_id, cwd) → the plugin's answer dict."""
    moment = moment or datetime.now(timezone.utc)
    done = []
    for scene in marked(store):
        if not due(store, scene, moment):
            continue
        found = main_session(store, scene, persona)
        if not found:
            store.db.scenes.update_one({'_id': scene['_id']}, {'$unset': {'condense_wanted': ''}})
            store.audit('condense', 'condense.no_conversation', {'scene_id': scene['_id']})
            continue
        try:
            session_id, cwd = found
            answer = compact(session_id, scene['_id'], cwd) or {}
        except Exception as exc:              # the next look tries again
            store.audit('condense', 'condense.failed', {'scene_id': scene['_id'], 'error': str(exc)[:200]})
            continue
        if answer.get('reason') in UNAVAILABLE:
            # This Host cannot condense at all: the mark is taken back rather than tried every few minutes.
            store.db.scenes.update_one({'_id': scene['_id']}, {'$unset': {'condense_wanted': ''}})
        if answer.get('compacted') or answer.get('reason') == 'nothing_to_compact':
            store.db.scenes.update_one({'_id': scene['_id']}, {
                '$set': {'condensed_at': moment.isoformat(), **({'conversation_tokens': None} if answer.get('compacted') else {})},
                '$unset': {'condense_wanted': ''}})
            done.append(scene['_id'])
        store.audit('condense', 'condense.result', {'scene_id': scene['_id'], 'session_id': found[0],
                                                    **{k: answer.get(k) for k in ('compacted', 'items', 'tokens', 'reason')}})
    return done


def condensed_block(store, scene, moment=None):
    """Once after condensing: until she next speaks there, or for a day."""
    when = _at((scene or {}).get('condensed_at'))
    moment = moment or datetime.now(timezone.utc)
    if not when or moment - when > timedelta(hours=CONDENSED_SHOWN_HOURS):
        return None
    from .config import character_id
    spoke = store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'outbound',
                                        'author': character_id(store.config), 'receipt_at': {'$gt': when.isoformat()}},
                                       {'_id': 1})
    if spoke:
        return None
    from .config import ago
    return CONDENSED_NOTE % ago(max(0.0, (moment - when).total_seconds() / 3600))


# ---- phrases for a write_notes visit -----------------------------------------------------------------------------
def last_look(store, scene_id, current_event_id=None):
    """When she last visited this group before this visit (the heartbeat plan's ledger), or None."""
    plan = store.db.plans.find_one({'_id': 'plan-asuna-presence'}, {'visits': 1}) or {}
    times = [_at(visit.get('at')) for visit in plan.get('visits') or []
             if visit.get('scene_id') == scene_id and visit.get('event_id') != current_event_id]
    times = [moment for moment in times if moment]
    return max(times) if times else None


def _phrases(text):
    text = _MARKUP.sub(' ', str(text or ''))
    found = set()
    for run in _CJK.findall(text):
        for size in range(2, min(6, len(run)) + 1):
            for start in range(0, len(run) - size + 1):
                piece = run[start:start + size]
                if not set(piece) <= FUNCTION_CHARS:
                    found.add(piece)
    found.update(word.lower() for word in _LATIN.findall(text))
    return found


def _speakers(rows, me, days=None):
    seen = defaultdict(set)
    for row in rows:
        if row.get('author') and row.get('author') != me:
            stamp = str(row.get('received_at') or '')[:10]
            for phrase in _phrases(row.get('text')):
                seen[phrase].add(row['author'])
                if days is not None and stamp:
                    days[phrase].add(stamp)
    return seen


def phrases(store, scene, persona, since, moment=None):
    """At most five phrases of this group for a write_notes visit: used by at least three people there over the last
    week, on at least three different days (a group's own words come back; a day's topic does not), at least once
    since her last look, not ordinary talk in her other groups, not in her group notes. Most people first; a phrase
    overlapping one already shown is left out."""
    from .config import character_id
    from .documents import DocumentStore
    from .group_admin import notes_slug
    moment = moment or datetime.now(timezone.utc)
    me = character_id(store.config)
    week = (moment - timedelta(days=WEEK_DAYS)).isoformat()
    since = (since or (moment - timedelta(days=WEEK_DAYS))).isoformat()
    rows = list(store.db.messages.find({'scene_id': scene['_id'], 'direction': 'inbound',
                                        'received_at': {'$gte': week}}, {'author': 1, 'text': 1, 'received_at': 1}))
    days = defaultdict(set)
    people = _speakers(rows, me, days)
    fresh = set().union(*(_phrases(row.get('text')) for row in rows if str(row.get('received_at') or '') >= since)) \
        if rows else set()
    here = {phrase: len(who) for phrase, who in people.items()
            if len(who) >= PHRASE_MIN_PEOPLE and len(days[phrase]) >= PHRASE_MIN_DAYS and phrase in fresh}
    if not here:
        return None
    common = Counter()
    by_scene = defaultdict(list)
    for row in store.db.messages.find({'scene_id': {'$ne': scene['_id']}, 'direction': 'inbound',
                                       'received_at': {'$gte': week}}, {'scene_id': 1, 'author': 1, 'text': 1}):
        by_scene[row['scene_id']].append(row)
    for scene_rows in by_scene.values():
        for phrase, who in _speakers(scene_rows, me).items():
            if phrase in here and len(who) >= PHRASE_COMMON_PEOPLE:
                common[phrase] += 1
    _, notes = DocumentStore(store, persona).read(notes_slug(scene['_id']))
    notes = str(notes or '')
    ranked = sorted(((phrase, count) for phrase, count in here.items()
                     if common[phrase] < PHRASE_COMMON_GROUPS and phrase not in notes),
                    key=lambda item: (-item[1], -len(item[0]), item[0]))
    chosen = []
    for phrase, count in ranked:
        if any(phrase in other or other in phrase for other, _ in chosen):
            continue
        chosen.append((phrase, count))
        if len(chosen) == PHRASES_SHOWN:
            break
    if not chosen:
        return None
    return {'items': [{'phrase': phrase, 'people': _tier(PEOPLE_WORDS, count)} for phrase, count in chosen],
            'note': PHRASE_NOTE}
