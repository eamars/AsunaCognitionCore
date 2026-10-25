"""What she learned elsewhere comes back when she asks (ADR-097 D3, D4): lines from her other groups, past versions
of her notes, and the place rules that decide what may leave a group.

`recall` with a word reaches the chat lines of her other groups that contain it, when it is a word that may cross
(key_words.cross_words: outside the segmenter's dictionary, or a whole ASCII word or number) and the place she is in
says it at most `said_here` times itself: a sentence crosses only through such words, and a word this place already
says has its own memories here.

In a group turn, a line with such a word that her other groups have said at least `seen_elsewhere` times in the last
`window_days` days brings one line of presence (`cue`): the word, how often, the day of the latest and that place's
kind, and that recall finds it; no words from there. Others' lines count too, from places that let only her own lines
leave. Never on a templated line (a place's repeated opening, a status record), never on a word the turn's delivered
lines already have, once per word per conversation in `repeat_minutes`, at most one a turn and only in a free one of
her own items' slots, after her own note on the word. Each cue is a row in `memory_fires`, with its turn and line. Her own lines come back as 「你在别处说过」, others' as 「别人提过」, each with
the place's kind and the day, never the place or the speaker; an @-mention in them reads 「@某人」. Her own line ranks
first, then a line that explains the word, then the newest. A line someone later corrected (a reply the program
resolves, summary_attribution.corrections) comes back marked as corrected, with the correction. She can read the few
lines around one by its ref (`fetch`), under the same rules, the speakers only as 你 or 别人.

Lines are found through `crossing_words`, a collection the program derives from her groups' chat lines and can always
rebuild: one row per cross word with the lines that have it (unit id, hers or others', scope; no text), others' the
newest OTHERS_KEPT, and per group how many lines of the window said it and when the latest was (`seen`). It is built when missing and again at settlement (a new generation, the old one dropped after),
and topped up at each recall from the group lines said since. Place rules are never in it: they are checked when it
is read and again at a fetch, so a change of the rules file counts at once.

What leaves a place is the deployment's choice, in `<data>/private/memory-crossing.json`: per place `all` (her lines
and others'), `own_lines` (only hers) or `never` (nothing), `default` for a place it does not name (own_lines when
the file is absent), each place's kind, the date ranges whose note versions never come back, and the numbers above
(NUMBERS gives their defaults). A rule governs only
what leaves its place; any place may receive. Only groups are sources: home, her private chats and every
owner-private scope never are. Her thoughts never cross from here: only her spoken lines do.

Past versions of a group's notes (in that group) and of her running records (where they are readable) come back for
a word the section's current text no longer has, marked 「你以前记过」 with the day and the reason of the change that
replaced them. Not served: versions written on an excluded day, and every version of an item she marked as her own
judgment (from 我自己的判断). A judgment of a person she did not mark, and an old number with no correction, cannot be
told apart by the program; the day and the reason are what she reads them by.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from . import key_words
from .config import DATA, character_id, excerpt

RULES = ('all', 'own_lines', 'never')
DEFAULT = 'own_lines'
PATH = DATA / 'private' / 'memory-crossing.json'
DOC = 'elsewhere'                    # recall sections: {doc: elsewhere, section: ref} reads the lines around one
SHOWN = 3                            # past versions a recall returns
ELSEWHERE_SHOWN = 2                  # lines from elsewhere a recall returns
WORDS = 'crossing_words'             # the word index of her groups' lines (program-derived, rebuildable)
OTHERS_KEPT = 20                     # others' lines kept per word, the newest
FIRES = 'memory_fires'               # what came back and when (cues), for the readings; kept FIRES_DAYS
FIRES_DAYS = 30
# The deployment's numbers (memory-crossing.json), with these defaults and bounds.
NUMBERS = {'window_days': (14, 1, 90), 'said_here': (2, 0, 100), 'seen_elsewhere': (5, 1, 1000),
           'repeat_minutes': (60, 0, 1440)}
CUE = '%s：这个词你在别的群见过 %d 次，最近 %s%s；recall 写上它能找到'
EXCERPT = 200
AROUND = 2                           # lines before and after the one fetched
LATER = 30                           # lines after a line that may correct it
EXPLAINS = ('就是', '指的是', '意思是')
SOMEONE = '@某人'
MARKS = {(True, False): '你在别处说过：%s', (False, False): '别人提过：%s',
         (True, True): '已被更正·此前说过：%s', (False, True): '已被更正·别人此前提过：%s'}
BEFORE = {False: '你以前记过：%s（改于 %s：%s）', True: '已被更正·此前记过：%s（改于 %s：%s）'}
GONE = '你以前记过：%s（已删，%s：%s）'
REASON_CHARS = 80
HOW = '读这一句前后几句：sections 写 {doc: elsewhere, section: 它的 ref}'
WHO = {True: '你', False: '别人'}
LEFT_OUT = '别人的话这个地方不外带，只给了你自己的'
MISSING = {'gone': '%s#%s：没有这一句', 'here': '%s#%s：这一句就在这个对话里，翻这里的记录',
           'never': '%s#%s：那个地方的话不外带'}
OWN_JUDGMENT = '我自己的判断'

_cache = {'mtime': None, 'value': None}


def settings(path=None):
    """The deployment's rules: {default, places, kinds, history_excluded}, defaults filled; a malformed entry is
    dropped (an unknown rule reads as the default)."""
    path = path or PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _cache['mtime'] != (path, mtime):
        raw = {}
        if mtime is not None:
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raw = {}
        raw = raw if isinstance(raw, dict) else {}
        default = raw.get('default') if raw.get('default') in RULES else DEFAULT
        places = {str(k): v for k, v in (raw.get('places') or {}).items() if v in RULES}
        kinds = {str(k): v for k, v in (raw.get('kinds') or {}).items() if isinstance(v, str) and v}
        excluded = [tuple(pair) for pair in raw.get('history_excluded') or []
                    if isinstance(pair, list) and len(pair) == 2 and all(isinstance(d, str) for d in pair)]
        numbers = {name: raw[name] if type(raw.get(name)) is int and low <= raw[name] <= high else default_value
                   for name, (default_value, low, high) in NUMBERS.items()}
        _cache.update(mtime=(path, mtime), value={'default': default, 'places': places, 'kinds': kinds,
                                                  'history_excluded': excluded, **numbers})
    return _cache['value']


def number(name):
    """One of the deployment's numbers (NUMBERS)."""
    return settings().get(name, NUMBERS[name][0])


def rule(scene_id):
    rules = settings()
    return rules['places'].get(scene_id, rules['default'])


def kind(scene_id):
    return settings()['kinds'].get(scene_id)


def query_words(store, persona, here, query):
    """The words of a recall's query that reach other places: cross words this place says at most `said_here` times."""
    from .memory_tiers import Tiers
    vocabulary(store)
    words = key_words.cross_words(query)
    said = Tiers(store, persona).said(here['_id']) if words else set()
    return [word for word in words if word not in said]


def _day(value, zone):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return ''
    local = moment.astimezone(zone['tz'] if zone else timezone.utc)
    current = datetime.now(timezone.utc).astimezone(local.tzinfo)
    return ('%d/' % local.year if local.year != current.year else '') + '%d/%d' % (local.month, local.day)


def _clean(store, scene_id, text):
    """A line as it may cross: its @-mentions of people say only that someone was named."""
    from . import channel_kinds
    platform = channel_kinds.of(scene_id)
    text = platform.INBOUND_MENTION.sub(SOMEONE, text or '') if platform else (text or '')
    return excerpt(text, EXCERPT)


def _sources(store, here_id):
    """The groups whose lines may leave, other than this conversation: {scope_key: (scene, rule)}."""
    from .visibility import is_owner_private_scope
    out = {}
    for scene in store.db.scenes.find({'kind': 'group', '_id': {'$ne': here_id}},
                                      {'scope_key': 1, 'policy_epoch': 1, 'kind': 1}):
        if is_owner_private_scope(scene.get('scope_key') or '') or rule(scene['_id']) == 'never':
            continue
        out[scene['scope_key']] = (scene, rule(scene['_id']))
    return out


def _correction(store, scene, unit):
    """The correction a later line made of this one (a resolved reply), as (who, text), or None."""
    from .summary_attribution import corrections
    line = store.db.messages.find_one({'_id': (unit.get('source_event_ids') or [None])[0]})
    if not line:
        return None
    later = list(store.db.messages.find({'scene_id': scene['_id'], 'policy_epoch': scene.get('policy_epoch', 1),
                                         'scene_seq': {'$gt': line.get('scene_seq', 0)},
                                         '$or': [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]})
                 .sort('scene_seq', 1).limit(LATER))
    me = character_id(store.config)
    for found in corrections(store, scene, [line, *later]):
        if found.get('corrects') == line['_id']:
            row = next((r for r in later if r['_id'] == found['message_id']), None)
            if row:
                return WHO[row.get('direction') == 'outbound' and row.get('author') == me], \
                    _clean(store, scene['_id'], row.get('text'))
    return None


def elsewhere(store, persona, here, query, zone):
    """recall: lines of her other groups that have a word of the query that may cross, at most ELSEWHERE_SHOWN,
    best first."""
    sources = _sources(store, here['_id'])
    words = query_words(store, persona, here, query) if sources else []
    if not words:
        return []
    me = character_id(store.config)
    wanted = [unit for unit, scope, hers in lines_for(store, words)
              if scope in sources and (hers or sources[scope][1] == 'all')]
    epochs = [{'scope_key': key, 'policy_epoch': scene.get('policy_epoch', 1)} for key, (scene, _) in sources.items()]
    rows = list(store.db.memory_units.find({'_id': {'$in': wanted}, 'kind': 'chat_chunk', 'status': 'active',
                                            'character_id': me, '$or': epochs},
                                           {'body_markdown': 1, 'scope_key': 1, 'policy_epoch': 1, 'epistemic_type': 1,
                                            'occurred_at': 1, 'source_event_ids': 1})) if wanted else []
    rows = [unit for unit in rows if any(key_words.found(word, unit.get('body_markdown') or '') for word in words)]
    said = _said_at(store, rows)
    picked, seen = [], set()
    for unit in rows:
        body = unit.get('body_markdown') or ''
        if body in seen:
            continue
        seen.add(body)
        mine = unit.get('epistemic_type') == 'public_statement'
        picked.append(((not mine, not any(cue in body for cue in EXPLAINS), -_seconds(said.get(unit['_id']))),
                       unit, mine))
    out = []
    for _, unit, mine in sorted(picked, key=lambda item: item[0])[:ELSEWHERE_SHOWN]:
        scene = sources[unit['scope_key']][0]
        corrected = _correction(store, scene, unit)
        entry = {'line': MARKS[(mine, bool(corrected))] % _clean(store, scene['_id'], unit.get('body_markdown')),
                 'when': _day(said.get(unit['_id']), zone), 'ref': unit['_id']}
        if kind(scene['_id']):
            entry['kind'] = kind(scene['_id'])
        if corrected:
            entry['correction'] = '%s后来更正：%s' % corrected
        out.append(entry)
    return out


# ── the word index ───────────────────────────────────────────────
def _groups(store):
    from .visibility import is_owner_private_scope
    return {s['_id']: s for s in store.db.scenes.find({'kind': 'group'}, {'scope_key': 1, 'policy_epoch': 1})
            if not is_owner_private_scope(s.get('scope_key') or '')}


def _mention(scene_id):
    from . import channel_kinds
    platform = channel_kinds.of(scene_id)
    return platform.INBOUND_MENTION if platform else None


def _postings(units, groups, times, since):
    """{word: {'hers': [[unit, scope]], 'theirs': [[unit, scope, said at]], 'seen': {scope: [lines, latest]}}} for
    these chat units; `seen` counts the lines said since `since` (her lines by their receipts, `times`)."""
    scenes = {scene['scope_key']: scene_id for scene_id, scene in groups.items()}
    out = {}
    for unit in units:
        hers = unit.get('epistemic_type') == 'public_statement'
        at = str(times.get(unit['_id']) or unit.get('occurred_at') or '')
        for word in key_words.cross_words(unit.get('body_markdown'), _mention(scenes.get(unit['scope_key']))):
            entry = out.setdefault(word, {'hers': [], 'theirs': [], 'seen': {}})
            if hers:
                entry['hers'].append([unit['_id'], unit['scope_key']])
            else:
                entry['theirs'].append([unit['_id'], unit['scope_key'], at])
            if at and at >= since:
                lines, latest = entry['seen'].get(unit['scope_key'], (0, ''))
                entry['seen'][unit['scope_key']] = [lines + 1, max(latest, at)]
    return out


def _since(moment=None):
    from datetime import timedelta
    return ((moment or datetime.now(timezone.utc)) - timedelta(days=number('window_days'))).isoformat()


def vocabulary(store, ensure=False):
    """The learned words of the index's build, learned in this process once per build; `ensure` builds the index
    first when there is none (a place's words must be cut as the index cuts them)."""
    mark = store.db[WORDS].find_one({'_id': 'mark'}, {'build': 1, 'vocabulary': 1})
    if not mark and ensure:
        build(store)
        return store.db[WORDS].find_one({'_id': 'mark'}, {'build': 1})
    if mark and _loaded.get('build') != mark.get('build'):
        key_words.learn(mark.get('vocabulary') or [])
        _loaded['build'] = mark.get('build')
    return mark


_loaded = {}


def build(store, moment=None):
    """Build the word index again from every chat line of her groups, as a new generation; the old one goes once the
    new one is in place. Two passes: the cross words in her lines are counted and the frequent ones learned
    (key_words.vocabulary), then the lines are cut again with them. Returns how many words it holds."""
    from .state import now
    vocabulary(store)
    groups = _groups(store)
    rows = list(store.db.memory_units.find({'kind': 'chat_chunk', 'status': 'active',
                                            'character_id': character_id(store.config),
                                            'scope_key': {'$in': [s['scope_key'] for s in groups.values()]}},
                                           {'body_markdown': 1, 'scope_key': 1, 'epistemic_type': 1, 'occurred_at': 1,
                                            'source_event_ids': 1}))
    times = _said_at(store, [unit for unit in rows if not unit.get('occurred_at')])
    scenes = {scene['scope_key']: scene_id for scene_id, scene in groups.items()}
    counts = Counter(word for unit in rows for word in key_words.cross_words(
        unit.get('body_markdown'), _mention(scenes.get(unit['scope_key']))))
    learned = key_words.vocabulary(counts)
    key_words.learn(learned)
    words = _postings(rows, groups, times, _since(moment))
    column = store.db[WORDS]
    mark = column.find_one({'_id': 'mark'}) or {}
    generation = int(mark.get('generation') or 0) + 1
    seqs = {scene_id: (store.db.messages.find_one({'scene_id': scene_id}, {'scene_seq': 1}, sort=[('scene_seq', -1)])
                       or {}).get('scene_seq', 0) for scene_id in groups}
    batch = [{'_id': '%d:%s' % (generation, word), 'row': 'word', 'generation': generation, 'word': word,
              'hers': entry['hers'],
              'theirs': sorted(entry['theirs'], key=lambda posting: posting[2])[-OTHERS_KEPT:],    # oldest first
              'seen': [[scope, lines, latest] for scope, (lines, latest) in entry['seen'].items()]}
             for word, entry in words.items()]
    for start in range(0, len(batch), 1000):
        column.insert_many(batch[start:start + 1000], ordered=False)
    import uuid
    built = uuid.uuid4().hex
    column.update_one({'_id': 'mark'}, {'$set': {'row': 'mark', 'generation': generation, 'seqs': seqs, 'build': built,
                                                 'vocabulary': learned, 'at': moment.isoformat() if moment else now()}},
                      upsert=True)
    _loaded['build'] = built
    column.delete_many({'row': 'word', 'generation': {'$ne': generation}})
    return len(batch)


def top_up(store):
    """Add the group lines said since the index's mark: each group's chunked lines after its last indexed one, up to
    the first line the indexer has not chunked yet. Returns the generation to read."""
    column = store.db[WORDS]
    mark = column.find_one({'_id': 'mark'})
    if not mark:
        build(store)
        return column.find_one({'_id': 'mark'})['generation']
    vocabulary(store)
    from .evidence import canonical, sha
    from .ingress import PROGRAM_AUTHOR
    groups = _groups(store)
    seqs = dict(mark.get('seqs') or {})
    me = character_id(store.config)
    reached, units = {}, []
    for scene_id, scene in groups.items():
        upto = seqs.get(scene_id, 0)
        rows = list(store.db.messages.find({'scene_id': scene_id, 'scene_seq': {'$gt': upto}},
                                           {'text': 1, 'direction': 1, 'delivery_state': 1, 'author': 1, 'policy_epoch': 1,
                                            'memory_chunk_version': 1, 'scene_seq': 1}).sort('scene_seq', 1))
        ids = []
        for row in rows:
            chunked = row.get('memory_chunk_version') == 2
            never = (row.get('author') == PROGRAM_AUTHOR or row.get('policy_epoch', 1) != scene.get('policy_epoch', 1)
                     or (row.get('direction') == 'outbound' and row.get('delivery_state') != 'DELIVERED'))
            if not chunked and not never:
                break                    # the indexer has not reached it yet: a later recall takes it
            if chunked:
                parts = len((row.get('text') or '').encode()) // 900 + 2
                ids += ['chunk-' + sha(canonical([row['_id'], 2, index])) for index in range(parts)]
            upto = row['scene_seq']
        if upto != seqs.get(scene_id, 0):
            reached[scene_id] = upto
        if ids:
            units += list(store.db.memory_units.find({'_id': {'$in': ids}, 'kind': 'chat_chunk', 'status': 'active',
                                                      'character_id': me},
                                                     {'body_markdown': 1, 'scope_key': 1, 'epistemic_type': 1,
                                                      'occurred_at': 1, 'source_event_ids': 1}))
    generation = mark['generation']
    since = _since()
    added = _postings(units, groups, _said_at(store, [u for u in units if not u.get('occurred_at')]), since)
    kept = {row['word']: row for row in column.find({'_id': {'$in': ['%d:%s' % (generation, w) for w in added]}},
                                                    {'word': 1, 'seen': 1})}
    for word, entry in added.items():
        seen = {scope: [lines, latest] for scope, lines, latest in (kept.get(word) or {}).get('seen') or []}
        for scope, (lines, latest) in entry['seen'].items():
            was = seen.get(scope, [0, ''])
            seen[scope] = [was[0] + lines, max(was[1], latest)]
        column.update_one({'_id': '%d:%s' % (generation, word)}, {
            '$setOnInsert': {'row': 'word', 'generation': generation, 'word': word},
            '$set': {'seen': [[scope, lines, latest] for scope, (lines, latest) in seen.items()]},
            '$addToSet': {'hers': {'$each': entry['hers']}},
            '$push': {'theirs': {'$each': entry['theirs'], '$slice': -OTHERS_KEPT}}}, upsert=True)
    if reached:
        column.update_one({'_id': 'mark', 'generation': generation},
                          {'$max': {'seqs.' + scene_id: seq for scene_id, seq in reached.items()}})
    return generation


def seen_for(store, words):
    """{word: [(scope, lines in the window, latest)]} from the index, topped up first."""
    generation = top_up(store)
    return {row['word']: row.get('seen') or [] for row in store.db[WORDS].find(
        {'_id': {'$in': ['%d:%s' % (generation, word) for word in words]}}, {'word': 1, 'seen': 1})}


def lines_for(store, words):
    """[(unit id, scope, hers)] of the lines that have one of the words, the index topped up first."""
    generation = top_up(store)
    out = []
    for row in store.db[WORDS].find({'_id': {'$in': ['%d:%s' % (generation, word) for word in words]}}):
        out += [(unit, scope, True) for unit, scope in row.get('hers') or []]
        out += [(unit, scope, False) for unit, scope, _ in row.get('theirs') or []]
    return out


def _said_at(store, units):
    """{unit id: when its line was said}: her own lines keep their time on the delivery receipt, not the unit
    (scene_links.message_times, the order every cross-place merge uses)."""
    from .scene_links import message_times
    sources = {(unit.get('source_event_ids') or [None])[0]: unit['_id'] for unit in units}
    rows = list(store.db.messages.find({'_id': {'$in': [key for key in sources if key]}},
                                       {'direction': 1, 'receipt': 1, 'receipt_at': 1, 'occurred_at': 1, 'received_at': 1}))
    times = message_times(store, rows)
    out = {unit['_id']: unit.get('occurred_at') for unit in units}
    out.update({sources[key]: at for key, (at, _) in times.items() if key in sources and at})
    return out


def _seconds(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def fetch(store, here, ref, zone):
    """recall sections {doc: elsewhere, section: ref}: the lines around one line of another group, the place rule
    checked again now, speakers as 你 or 别人. (section, None), or (None, why in words)."""
    from .visibility import is_owner_private_scope
    unit = store.db.memory_units.find_one({'_id': ref, 'kind': 'chat_chunk', 'status': 'active'},
                                          {'scope_key': 1, 'policy_epoch': 1, 'source_event_ids': 1, 'occurred_at': 1})
    scene = store.db.scenes.find_one({'scope_key': unit['scope_key'], 'kind': 'group'},
                                     {'scope_key': 1, 'policy_epoch': 1}) if unit else None
    if not scene or is_owner_private_scope(scene.get('scope_key') or '') \
            or unit.get('policy_epoch', 1) != scene.get('policy_epoch', 1):
        return None, MISSING['gone'] % (DOC, ref)
    if scene['_id'] == here['_id']:
        return None, MISSING['here'] % (DOC, ref)
    leaving = rule(scene['_id'])
    if leaving == 'never':
        return None, MISSING['never'] % (DOC, ref)
    line = store.db.messages.find_one({'_id': (unit.get('source_event_ids') or [None])[0]}, {'scene_seq': 1})
    if not line:
        return None, MISSING['gone'] % (DOC, ref)
    me = character_id(store.config)
    rows = store.db.messages.find({'scene_id': scene['_id'], 'policy_epoch': scene.get('policy_epoch', 1),
                                   'scene_seq': {'$gte': line['scene_seq'] - AROUND, '$lte': line['scene_seq'] + AROUND},
                                   '$or': [{'direction': 'inbound'}, {'delivery_state': 'DELIVERED'}]},
                                  {'text': 1, 'author': 1, 'direction': 1, 'scene_seq': 1}).sort('scene_seq', 1)
    lines, left_out = [], 0
    for row in rows:
        mine = row.get('direction') == 'outbound' and row.get('author') == me
        if leaving == 'own_lines' and not mine:
            left_out += 1
            continue
        lines.append({'who': WHO[mine], 'text': _clean(store, scene['_id'], row.get('text'))})
    section = {'doc': DOC, 'sid': ref, 'when': _day(_said_at(store, [{**unit, '_id': ref}]).get(ref), zone),
               'lines': lines}
    if kind(scene['_id']):
        section['kind'] = kind(scene['_id'])
    if left_out:
        section['left_out'] = LEFT_OUT
    return section, None


# ── past versions of her notes ─────────────────────────────────────
def _excluded(value, zone, ranges):
    day = _local_date(value, zone)
    return bool(day) and any(start <= day <= end for start, end in ranges)


def _local_date(value, zone):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return ''
    return moment.astimezone(zone['tz'] if zone else timezone.utc).date().isoformat()


_versions = {}


def versions(store, persona, slug):
    """`history` of one document, kept while its ledger has no newer revision (one small read to check)."""
    from .documents import DocumentStore
    newest = [next(iter(store.db[name].find(query, {'created_at': 1, '_id': 1}).sort([('created_at', -1), ('_id', -1)])
                        .limit(1)), None)
              for name, query in (('state_revisions', {'entity_key': DocumentStore(store, persona).key(slug)}),
                                  ('journal_revisions', {'persona': persona, 'slug': slug}))]
    mark = (store.name, persona, slug)
    seal = [(row or {}).get('_id') for row in newest]
    kept = _versions.get(mark)
    if kept and kept[0] == seal:
        return kept[1]
    value = history(store, persona, slug)
    _versions[mark] = (seal, value)
    return value


def history(store, persona, slug):
    """Every past text of each section of one of her documents, oldest first: {sid: [(body, written_at, replaced_at,
    reason of the change that replaced it)]}; the current text is not among them. A record kept as rows reads its
    rows' revisions after the revisions of the document it was before."""
    from .documents import DocumentStore
    docs = DocumentStore(store, persona)
    texts = {}                       # sid -> [(body, at, reason)] each time the text changed (or the section went)
    for revision in store.db.state_revisions.find({'entity_key': docs.key(slug)},
                                                  {'content.sections': 1, 'created_at': 1, 'reason': 1}).sort('created_at', 1):
        sections = {s['sid']: s.get('body') or '' for s in (revision.get('content') or {}).get('sections') or []}
        for sid in set(texts) | set(sections):
            body = sections.get(sid)
            if not texts.get(sid) or texts[sid][-1][0] != body:
                texts.setdefault(sid, []).append((body, revision.get('created_at'), revision.get('reason')))
    for row in store.db.journal_revisions.find({'persona': persona, 'slug': slug, 'sid': {'$exists': True}},
                                               {'sid': 1, 'body': 1, 'created_at': 1, 'reason': 1}).sort('created_at', 1):
        if not texts.get(row['sid']) or texts[row['sid']][-1][0] != row.get('body'):
            texts.setdefault(row['sid'], []).append((row.get('body'), row.get('created_at'), row.get('reason')))
    out = {}
    for sid, changes in texts.items():
        for (body, written, _), (_, replaced, reason) in zip(changes, changes[1:]):
            if body:
                out.setdefault(sid, []).append((body, written, replaced, reason))
    return out


def before(store, persona, here, cls, query, zone):
    """recall: past versions of her notes readable here that have a word of the query that may cross, which their
    section no longer has; one per section, newest change first, at most SHOWN."""
    from . import visibility
    from .documents import DocumentStore
    from .group_admin import notes_slug
    from .memory_tiers import Tiers, ref
    words = query_words(store, persona, here, query)
    if not words:
        return []
    from .documents import JOURNALS
    docs = DocumentStore(store, persona)
    slugs = [notes_slug(here['_id'])] if here.get('kind') == 'group' else []
    slugs += sorted({*JOURNALS, *store.db.journal_entries.distinct('slug', {'persona': persona})})
    judged = {(row['doc'], row['sid']) for row in Tiers(store, persona).items(**{'from': OWN_JUDGMENT})}
    ranges = settings()['history_excluded']
    found = []
    for slug in slugs:
        current = {s['sid']: s for s in (docs.read(slug)[1] or {}).get('sections') or []}
        corrected = {s.get('corrects') for s in current.values() if s.get('corrects')}
        for sid, past in versions(store, persona, slug).items():
            section = current.get(sid)
            seen = visibility.readable((section or {}).get('visibility') or
                                       ('public' if slug.startswith('group:') else 'owner_private'), cls)
            if not seen or (slug, sid) in judged:
                continue
            now_text = ((section or {}).get('heading') or '') + '\n' + ((section or {}).get('body') or '')
            lost = [word for word in words if not key_words.found(word, now_text)]
            for body, written, replaced, reason in reversed(past):
                if _excluded(written, zone, ranges) or not any(key_words.found(word, body) for word in lost):
                    continue
                text = excerpt(body, EXCERPT)
                why = excerpt((reason or '').strip() or '没写', REASON_CHARS)
                line = (GONE % (text, _day(replaced, zone), why) if section is None
                        else BEFORE[sid in corrected] % (text, _day(replaced, zone), why))
                found.append((-_seconds(replaced), {'line': line, **({'now': ref(slug, sid)} if section else {})}))
                break
    return [entry for _, entry in sorted(found, key=lambda pair: pair[0])[:SHOWN]]


# ── the presence cue (D2) ─────────────────────────────────────────
def cue(store, persona, scene, event, delivered, own, zone, moment=None):
    """A group turn's one line of presence, or None: the word of this line that her other groups say most often, when
    it may cross, this place says it at most `said_here` times, the turn's delivered lines do not have it, no cue named
    it here within `repeat_minutes`, and her own items this turn do not have it. The fire is written as a row."""
    from datetime import timedelta
    from .memory_tiers import Tiers
    if scene.get('kind') != 'group' or (event.get('episode_kind') or 'external') != 'external':
        return None
    text = event.get('text') if isinstance(event.get('text'), str) else ''
    tiers = Tiers(store, persona)
    if not text or key_words.templated(text, tiers.openings(scene['_id'])):
        return None
    vocabulary(store)
    said = tiers.said(scene['_id'])
    shown = [own_item.get('heading', '') + '\n' + own_item.get('body_markdown', '') for own_item in own]
    words = [word for word in key_words.cross_words(text, _mention(scene['_id'])) if word not in said
             and not any(key_words.found(word, line) for line in [*delivered, *shown])]
    if not words:
        return None
    moment = moment or datetime.now(timezone.utc)
    recent = (moment - timedelta(minutes=number('repeat_minutes'))).isoformat()
    words = [word for word in words if not store.db[FIRES].find_one(
        {'kind': 'cue', 'scene_id': scene['_id'], 'word': word, 'at': {'$gte': recent}}, {'_id': 1})]
    if not words:
        return None
    groups = {group['scope_key']: group_id for group_id, group in _groups(store).items()
              if group_id != scene['_id'] and rule(group_id) != 'never'}
    since = _since(moment)
    best = None
    for word, seen in seen_for(store, words).items():
        places = [(scope, lines, latest) for scope, lines, latest in seen if scope in groups and latest >= since]
        lines = sum(n for _, n, _ in places)
        if lines >= number('seen_elsewhere') and (best is None or lines > best[1]):
            best = (word, lines, max(places, key=lambda place: place[2]))
    if not best:
        return None
    word, lines, (scope, _, latest) = best
    place_kind = kind(groups[scope])
    line = CUE % (key_words.found(word, text) or word, lines, _month_day(latest, zone),
                  '，' + place_kind if place_kind else '')
    source = store.db.messages.find_one({'_id': 'in-' + _episode(event)}, {'scene_seq': 1}) or {}
    store.db[FIRES].insert_one({'kind': 'cue', 'persona': persona, 'scene_id': scene['_id'], 'word': word,
                                'event_id': event.get('event_id'), 'episode_id': _episode(event),
                                'scene_seq': source.get('scene_seq'), 'at': moment.isoformat(), 'lines': lines,
                                'latest': latest, 'kind_set': bool(place_kind)})
    return {'kind': 'cue', 'cue': line}


def _episode(event):
    from .ingress import episode_id
    return episode_id(event)


def _month_day(value, zone):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return ''
    local = moment.astimezone(zone['tz'] if zone else timezone.utc)
    return '%02d-%02d' % (local.month, local.day)


def prune(store, moment=None):
    """At settlement: fire rows older than FIRES_DAYS go. Returns how many."""
    from datetime import timedelta
    cutoff = ((moment or datetime.now(timezone.utc)) - timedelta(days=FIRES_DAYS)).isoformat()
    return store.db[FIRES].delete_many({'at': {'$lt': cutoff}}).deleted_count
