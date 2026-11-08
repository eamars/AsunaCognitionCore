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

from . import clock
from . import key_words
from .config import DATA, character_id, excerpt
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import memories as memory_records
from .records import heads as head_records
from .records.view import ANY, View, is_text
from .store.words import AddToSet, AnyOf, Larger, Not, OnCreate, Push, Range, Set

RULES = ('all', 'own_lines', 'never')
DEFAULT = 'own_lines'
PATH = DATA / 'private' / 'memory-crossing.json'
DOC = 'elsewhere'                    # recall sections: {doc: elsewhere, section: ref} reads the lines around one
SHOWN = 3                            # past versions a recall returns
ELSEWHERE_SHOWN = 2                  # lines from elsewhere a recall returns
WORDS = 'crossing_words'             # the word index of her groups' lines (program-derived, rebuildable)
OTHERS_KEPT = 20                     # others' lines kept per word, the newest
FIRES = 'memory_fires'               # what came back and when, for the readings; kept FIRES_DAYS
FIRES_DAYS = 30
# What a fire row counts: her note by its word or its meaning (note), a cue, recall's lines from elsewhere (hers,
# theirs), a past version (before), and a recall that brought back what the turn itself had not (w6).
FIRE_KINDS = ('note', 'cue', 'elsewhere_hers', 'elsewhere_theirs', 'before', 'w6')
# The deployment's numbers (memory-crossing.json), with these defaults and bounds.
NUMBERS = {'window_days': (14, 1, 90), 'said_here': (2, 0, 100), 'seen_elsewhere': (5, 1, 1000),
           'repeat_minutes': (60, 0, 1440)}
CUE = '%s：这个词你在别的群见过 %d 次，最近 %s%s；recall 写上它能找到'
# Which lines a cue's words come from (`cue_lines`): the line the turn is for, and the turn's delivered lines are in
# view; or every inbound line new to the turn, and only lines an earlier turn delivered are in view.
CUE_LINES = ('trigger', 'new')
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

_cache = {'key': None, 'value': None}


def settings(path=None):
    """The deployment's rules: {default, places, kinds, history_excluded}, defaults filled; a malformed entry is
    dropped (an unknown rule reads as the default). Kept while the file's text is the same (a small read each call:
    a file's modification time moves in the system clock's steps, so two writes in one step would look alike)."""
    path = path or PATH
    try:
        text = path.read_bytes()
    except OSError:
        text = None
    if _cache['key'] != (path, text):
        raw = {}
        if text is not None:
            try:
                raw = json.loads(text.decode('utf-8'))
            except (UnicodeDecodeError, ValueError):
                raw = {}
        raw = raw if isinstance(raw, dict) else {}
        default = raw.get('default') if raw.get('default') in RULES else DEFAULT
        places = {str(k): v for k, v in (raw.get('places') or {}).items() if v in RULES}
        kinds = {str(k): v for k, v in (raw.get('kinds') or {}).items() if isinstance(v, str) and v}
        excluded = [tuple(pair) for pair in raw.get('history_excluded') or []
                    if isinstance(pair, list) and len(pair) == 2 and all(isinstance(d, str) for d in pair)]
        numbers = {name: raw[name] if type(raw.get(name)) is int and low <= raw[name] <= high else default_value
                   for name, (default_value, low, high) in NUMBERS.items()}
        lines = raw.get('cue_lines') if raw.get('cue_lines') in CUE_LINES else CUE_LINES[0]
        _cache.update(key=(path, text), value={'default': default, 'places': places, 'kinds': kinds,
                                                  'history_excluded': excluded, 'cue_lines': lines, **numbers})
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
    current = clock.now().astimezone(local.tzinfo)
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
    for scene in scene_records.of_kind(store, 'group', besides=here_id, fields=['scope_key', 'policy_epoch', 'kind']):
        if is_owner_private_scope(scene.get('scope_key') or '') or rule(scene['_id']) == 'never':
            continue
        out[scene['scope_key']] = (scene, rule(scene['_id']))
    return out


def _correction(store, scene, unit):
    """The correction a later line made of this one (a resolved reply), as (who, text), or None."""
    from .summary_attribution import corrections
    line = message_records.get(store, (unit.get('source_event_ids') or [None])[0])
    if not line:
        return None
    later = message_records.said(store, scene['_id'], scene.get('policy_epoch', 1),
                                 after=line.get('scene_seq', 0)).rows(limit=LATER)
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
    epochs = [(key, scene.get('policy_epoch', 1)) for key, (scene, _) in sources.items()]
    rows = memory_records.many(store, wanted, pairs=epochs, character=me, kind='chat_chunk', status='active').rows(
        fields=['body_markdown', 'scope_key', 'policy_epoch', 'epistemic_type', 'occurred_at', 'source_event_ids']
    ) if wanted else []
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
    return {s['_id']: s for s in scene_records.of_kind(store, 'group', fields=['scope_key', 'policy_epoch'])
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


# ── the owner of `crossing_words` and `memory_fires` ──
# The word index (a `mark` row and one `word` row per word and generation) and the count rows (`kind`: what came
# back, and the `seen` marks), read and written only through these and this module's own code. A conversation, a
# persona or a time given None finds nothing (ADR-104 section 4); not given is `ANY`.
def fire_rows(store, since, *, persona=ANY, kinds=FIRE_KINDS):
    """View: the count rows of these kinds (of a persona) at or after `since` (ISO text)."""
    where = {'kind': AnyOf(list(kinds)), 'at': Range(gte=since)} if is_text(since) else None
    if where is not None and persona is not ANY:
        where = {**where, 'persona': persona} if is_text(persona) else None
    return View(store, FIRES, where)


def _since(moment=None):
    from datetime import timedelta
    return ((moment or clock.now()) - timedelta(days=number('window_days'))).isoformat()


def vocabulary(store, ensure=False):
    """The learned words of the index's build, learned in this process once per build; `ensure` builds the index
    first when there is none (a place's words must be cut as the index cuts them)."""
    mark = store.collection(WORDS).get('mark', ['build', 'vocabulary'])
    if not mark and ensure:
        build(store)
        return store.collection(WORDS).get('mark', ['build'])
    if mark and _loaded.get('build') != mark.get('build'):
        key_words.learn(mark.get('vocabulary') or [])
        _loaded['build'] = mark.get('build')
    return mark


_loaded = {}


def build(store, moment=None):
    """Build the word index again from every chat line of her groups up to each group's chunk mark
    (records.memories.chunk_marks, as top_up reads), as a new generation. The old one goes once the new one is in
    place; the lines after a mark are topped up once it passes them. Two passes: the cross words in her lines are
    counted and the frequent ones learned (key_words.vocabulary), then the lines are cut again with them. Returns how
    many words it holds."""
    from .state import now
    vocabulary(store)
    groups = _groups(store)
    scenes = {scene['scope_key']: scene_id for scene_id, scene in groups.items()}
    chunked = memory_records.chunk_marks(store, list(groups))
    rows = [unit for unit in memory_records.of_kind(
                store, 'chat_chunk', scopes=[s['scope_key'] for s in groups.values()],
                character=character_id(store.config), status='active').each(
                fields=['body_markdown', 'scope_key', 'epistemic_type', 'occurred_at', 'source_event_ids', 'scene_seq'])
            if (unit.get('scene_seq') or 0) <= chunked.get(scenes.get(unit['scope_key']), 0)]
    times = _said_at(store, [unit for unit in rows if not unit.get('occurred_at')])
    counts = Counter(word for unit in rows for word in key_words.cross_words(
        unit.get('body_markdown'), _mention(scenes.get(unit['scope_key']))))
    learned = key_words.vocabulary(counts)
    key_words.learn(learned)
    words = _postings(rows, groups, times, _since(moment))
    column = store.collection(WORDS)
    mark = column.get('mark') or {}
    generation = int(mark.get('generation') or 0) + 1
    seqs = {scene_id: chunked.get(scene_id, 0) for scene_id in groups}
    batch = [{'_id': '%d:%s' % (generation, word), 'row': 'word', 'generation': generation, 'word': word,
              'hers': entry['hers'],
              'theirs': sorted(entry['theirs'], key=lambda posting: posting[2])[-OTHERS_KEPT:],    # oldest first
              'seen': [[scope, lines, latest] for scope, (lines, latest) in entry['seen'].items()]}
             for word, entry in words.items()]
    for start in range(0, len(batch), 1000):
        column.insert(batch[start:start + 1000], ordered=False)
    import uuid
    built = uuid.uuid4().hex
    column.update({'_id': 'mark'}, Set({'row': 'mark', 'generation': generation, 'seqs': seqs, 'build': built,
                                        'vocabulary': learned, 'at': moment.isoformat() if moment else now()}),
                  create=True)
    _loaded['build'] = built
    column.delete({'row': 'word', 'generation': Not(generation)}, many=True)
    return len(batch)


def top_up(store):
    """Add the group lines said since the index's mark: each group's lines after its last indexed one, up to its chunk
    mark (records.memories.chunk_marks: every line before it is settled, and chunked when spoken), so a reply the
    indexer waited for is indexed once it is delivered. Returns the generation to read."""
    column = store.collection(WORDS)
    mark = column.get('mark')
    if not mark:
        build(store)
        return column.get('mark')['generation']
    vocabulary(store)
    from .evidence import canonical, sha
    from .memory import spoken
    groups = _groups(store)
    seqs = dict(mark.get('seqs') or {})
    chunked = memory_records.chunk_marks(store, list(groups))        # one read of the groups' chunk marks
    me = character_id(store.config)
    reached, units = {}, []
    for scene_id, scene in groups.items():
        upto, until = seqs.get(scene_id, 0), chunked.get(scene_id, 0)
        if until <= upto:
            continue                     # the indexer has not chunked past it yet: a later recall takes it
        rows = message_records.lines(store, scene_id, after=upto, upto=until).rows(
            fields=['text', 'direction', 'delivery_state', 'author', 'policy_epoch'])
        ids = []
        for row in rows:
            if spoken(row) and row.get('policy_epoch', 1) == scene.get('policy_epoch', 1):
                parts = len((row.get('text') or '').encode()) // 900 + 2
                ids += ['chunk-' + sha(canonical([row['_id'], 2, index])) for index in range(parts)]
        reached[scene_id] = until
        if ids:
            units += memory_records.many(store, ids, character=me, kind='chat_chunk', status='active').rows(
                fields=['body_markdown', 'scope_key', 'epistemic_type', 'occurred_at', 'source_event_ids'])
    generation = mark['generation']
    since = _since()
    added = _postings(units, groups, _said_at(store, [u for u in units if not u.get('occurred_at')]), since)
    kept = {row['word']: row for row in column.find({'_id': AnyOf(['%d:%s' % (generation, w) for w in added])},
                                                    fields=['word', 'seen'])}
    for word, entry in added.items():
        seen = {scope: [lines, latest] for scope, lines, latest in (kept.get(word) or {}).get('seen') or []}
        for scope, (lines, latest) in entry['seen'].items():
            was = seen.get(scope, [0, ''])
            seen[scope] = [was[0] + lines, max(was[1], latest)]
        # An empty list adds nothing to a stored row; a new row is made with it, as an upsert of `$each: []` does.
        empty = {key: [] for key in ('hers', 'theirs') if not entry[key]}
        column.update({'_id': '%d:%s' % (generation, word)}, [
            OnCreate({'row': 'word', 'generation': generation, 'word': word, **empty}),
            Set({'seen': [[scope, lines, latest] for scope, (lines, latest) in seen.items()]}),
            *([AddToSet('hers', *entry['hers'])] if entry['hers'] else []),
            *([Push('theirs', *entry['theirs'], keep_last=OTHERS_KEPT)] if entry['theirs'] else [])], create=True)
    if reached:
        column.update({'_id': 'mark', 'generation': generation},
                      [Larger('seqs.' + scene_id, seq) for scene_id, seq in reached.items()])
    return generation


def seen_for(store, words):
    """{word: [(scope, lines in the window, latest)]} from the index, topped up first."""
    generation = top_up(store)
    return {row['word']: row.get('seen') or [] for row in store.collection(WORDS).find(
        {'_id': AnyOf(['%d:%s' % (generation, word) for word in words])}, fields=['word', 'seen'])}


def lines_for(store, words):
    """[(unit id, scope, hers)] of the lines that have one of the words, the index topped up first."""
    generation = top_up(store)
    out = []
    for row in store.collection(WORDS).find({'_id': AnyOf(['%d:%s' % (generation, word) for word in words])}):
        out += [(unit, scope, True) for unit, scope in row.get('hers') or []]
        out += [(unit, scope, False) for unit, scope, _ in row.get('theirs') or []]
    return out


def _said_at(store, units):
    """{unit id: when its line was said}: her own lines keep their time on the delivery receipt, not the unit
    (scene_links.message_times, the order every cross-place merge uses)."""
    from .scene_links import message_times
    sources = {(unit.get('source_event_ids') or [None])[0]: unit['_id'] for unit in units}
    rows = message_records.many(store, [key for key in sources if key]).rows(
        fields=['direction', 'receipt', 'receipt_at', 'occurred_at', 'received_at'])
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
    unit = memory_records.get(store, ref, ['scope_key', 'policy_epoch', 'source_event_ids', 'occurred_at'],
                              kind='chat_chunk', status='active')
    scene = scene_records.by_scope(store, unit['scope_key'], kind='group',
                                  fields=['scope_key', 'policy_epoch']) if unit else None
    if not scene or is_owner_private_scope(scene.get('scope_key') or '') \
            or unit.get('policy_epoch', 1) != scene.get('policy_epoch', 1):
        return None, MISSING['gone'] % (DOC, ref)
    if scene['_id'] == here['_id']:
        return None, MISSING['here'] % (DOC, ref)
    leaving = rule(scene['_id'])
    if leaving == 'never':
        return None, MISSING['never'] % (DOC, ref)
    line = message_records.get(store, (unit.get('source_event_ids') or [None])[0], fields=['scene_seq'])
    if not line:
        return None, MISSING['gone'] % (DOC, ref)
    me = character_id(store.config)
    rows = message_records.said(store, scene['_id'], scene.get('policy_epoch', 1), from_seq=line['scene_seq'] - AROUND,
                                upto=line['scene_seq'] + AROUND).rows(fields=['text', 'author', 'direction', 'scene_seq'])
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


_versions = {}      # (database, persona, slug) -> (the newest revision ids, the history)
_pasts = {}         # (database, persona, slug) -> (the document's newest revision id, its _Past)


def versions(store, persona, slug):
    """`history` of one document, kept while neither its ledger nor its rows have a newer revision (one small read
    each). The document's own part is kept while its ledger has no newer revision: a running record's new row reads
    only the rows again."""
    from . import documents
    newest = [head_records.history(store, documents.DocumentStore(store, persona).key(slug), by=('created_at', '_id'))
              .first(newest_first=True, fields=['created_at']),
              documents.last_revision(store, persona, slug, ['created_at'])]
    mark = (store.name, persona, slug)
    seal = [(row or {}).get('_id') for row in newest]
    kept = _versions.get(mark)
    if kept and kept[0] == seal:
        return kept[1]
    past = _pasts.get(mark)
    if not past or past[0] != seal[0]:
        past = _pasts[mark] = (seal[0], _Past(store, persona, slug))
    value = history(store, persona, slug, past[1])
    _versions[mark] = (seal, value)
    return value


class _Past:
    """A document's own revisions, read by their sections' hashes: `changes` {sid: [[hash, or None once it went;
    revision id, written at, reason, every visibility the text had while it was the section's]]}, one each time a
    section's text changed or it went, oldest first. A text is read (`body`) only when it is needed, one revision's
    sections at a time: an appended record's past is mostly hashes."""

    def __init__(self, store, persona, slug):
        from .documents import DocumentStore
        from .evidence import sha
        self.store, self.bodies, self.changes = store, {}, {}
        for revision in head_records.history(store, DocumentStore(store, persona).key(slug)).rows(
                fields=['content.sections.sid', 'content.sections.body_sha256', 'content.sections.visibility',
                        'created_at', 'reason']):
            listed = (revision.get('content') or {}).get('sections') or []
            if any(not s.get('body_sha256') for s in listed):
                # Sections kept without their hash: this revision's texts are read whole.
                listed = [{**s, 'body_sha256': sha((s.get('body') or '').encode())}
                          for s in self._sections(revision['_id'])]
            here = {s['sid']: s for s in listed}
            for sid in set(self.changes) | set(here):
                value = (here.get(sid) or {}).get('body_sha256')
                if not self.changes.get(sid) or self.changes[sid][-1][0] != value:
                    self.changes.setdefault(sid, []).append([value, revision['_id'], revision.get('created_at'),
                                                             revision.get('reason'), set()])
                if sid in here:
                    self.changes[sid][-1][4].add(here[sid].get('visibility'))

    def _sections(self, revision_id):
        content = (head_records.revision(self.store, revision_id, ['content.sections']) or {}).get('content') or {}
        return [{'sid': s['sid'], 'body': s.get('body') or '', 'visibility': s.get('visibility')}
                for s in content.get('sections') or []]

    def body(self, revision_id, sid):
        # Only the text asked for is kept, never the revision around it: a record's revision can be 400 KB.
        if (revision_id, sid) not in self.bodies:
            self.bodies[(revision_id, sid)] = next((s['body'] for s in self._sections(revision_id) if s['sid'] == sid),
                                                   None)
        return self.bodies[(revision_id, sid)]


def _kept(seen):
    """A past text's own visibility, from every one it had: public only when it was always public; owner_private
    when it ever was; None when one is not known (a row's revision written before revisions kept it)."""
    if None in seen or not seen:
        return None
    return 'public' if seen == {'public'} else 'owner_private'


def history(store, persona, slug, past=None):
    """Every past text of each section of one of her documents, oldest first: {sid: [(body, written_at, replaced_at,
    reason of the change that replaced it, its own visibility (`_kept`))]}; the current text is not among them. A
    record kept as rows reads its rows' revisions after the revisions of the document it was before. `past`: the
    document's own part, read already."""
    from . import documents
    from .evidence import sha
    past = past or _Past(store, persona, slug)
    texts = {sid: [[value, revision_id, at, reason, None, set(seen)] for value, revision_id, at, reason, seen in changes]
             for sid, changes in past.changes.items()}
    for row in documents.revisions(store, persona, slug, sectioned=True).rows(fields=['sid', 'body', 'created_at',
                                                                                    'reason', 'visibility']):
        value = None if row.get('body') is None else sha(row['body'].encode())
        if not texts.get(row['sid']) or texts[row['sid']][-1][0] != value:
            texts.setdefault(row['sid'], []).append([value, None, row.get('created_at'), row.get('reason'),
                                                     row.get('body'), set()])
        texts[row['sid']][-1][5].add(row.get('visibility'))
    out = {}
    for sid, changes in texts.items():
        for (value, revision_id, written, _, body, seen), (_, _, replaced, reason, _, _) in zip(changes, changes[1:]):
            if value is None:
                continue
            body = body if revision_id is None else past.body(revision_id, sid)
            if body:
                out.setdefault(sid, []).append((body, written, replaced, reason, _kept(seen)))
    return out


def before(store, persona, here, cls, query, zone):
    """recall: past versions of her notes readable here (this group's notes, her running records and her ledgers)
    that have a word of the query that may cross, which their section no longer has; one per section, newest change
    first, at most SHOWN. A past text is readable here when both its section now and the text itself, with every
    visibility it had, are."""
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
    from .documents import slugs as journals
    slugs += sorted({*JOURNALS, *journals(store, persona)})
    # Her ledgers too: a fact she rewrote keeps its old wording there, read under the same rule as the rest.
    slugs += [slug for slug, _, _ in docs.of_kind('ledger')]
    judged = {(row['doc'], row['sid']) for row in Tiers(store, persona).items(**{'from': OWN_JUDGMENT})}
    ranges = settings()['history_excluded']
    found = []
    for slug in slugs:
        current = {s['sid']: s for s in (docs.read(slug)[1] or {}).get('sections') or []}
        corrected = {s.get('corrects') for s in current.values() if s.get('corrects')}
        # A group's notes are public; anything else whose visibility is not known is read as owner_private.
        unknown = 'public' if slug.startswith('group:') else 'owner_private'
        for sid, past in versions(store, persona, slug).items():
            section = current.get(sid)
            seen = visibility.readable((section or {}).get('visibility') or unknown, cls)
            if not seen or (slug, sid) in judged:
                continue
            now_text = ((section or {}).get('heading') or '') + '\n' + ((section or {}).get('body') or '')
            lost = [word for word in words if not key_words.found(word, now_text)]
            for body, written, replaced, reason, own in reversed(past):
                # A past text is shown only where its own visibility is readable too, not only the section's now.
                if (not visibility.readable(own or unknown, cls) or _excluded(written, zone, ranges)
                        or not any(key_words.found(word, body) for word in lost)):
                    continue
                text = excerpt(body, EXCERPT)
                why = excerpt((reason or '').strip() or '没写', REASON_CHARS)
                line = (GONE % (text, _day(replaced, zone), why) if section is None
                        else BEFORE[sid in corrected] % (text, _day(replaced, zone), why))
                found.append((-_seconds(replaced), {'line': line, **({'now': ref(slug, sid)} if section else {})}))
                break
    return [entry for _, entry in sorted(found, key=lambda pair: pair[0])[:SHOWN]]


# ── the presence cue (D2) ─────────────────────────────────────────
def cue(store, persona, scene, event, history, own, zone, moment=None, *, free=True):
    """A group turn's one line of presence, or None. Its words come from the line the turn is for, and the turn's
    delivered lines are in view; with `cue_lines` new, from every inbound line new to this turn (after those an earlier
    turn here delivered, and those claimed into it), and only earlier turns' lines are in view. A word that may cross,
    that this place says at most `said_here` times, that no line in view and none of her own items this turn
    have, and that no cue named here within `repeat_minutes`; of these, the one her other groups say most often, if
    at least `seen_elsewhere` times. `history` is the turn's delivered lines, [(scene_seq, text, direction)]. Every
    group turn moves the place's mark of what was delivered; only a turn from someone's line with a free own-item slot
    (`free`) gets a cue. The fire is written as a row."""
    from datetime import timedelta
    from .memory_tiers import Tiers
    if scene.get('kind') != 'group':
        return None
    seq = _line_seq(store, event)
    counts = store.collection(FIRES)
    mark = counts.get('seen:%s:%s' % (persona, scene['_id'])) or {}
    upto = mark.get('seq') or 0
    reached = max([upto, seq or 0, *[s for s, _, _ in history if isinstance(s, int)]])
    counts.update({'_id': 'seen:%s:%s' % (persona, scene['_id'])},
                  [Larger('seq', reached), Set({'kind': 'seen', 'persona': persona, 'scene_id': scene['_id']})],
                  create=True)
    if not free or (event.get('episode_kind') or 'external') != 'external':
        return None
    text = event.get('text') if isinstance(event.get('text'), str) else ''
    every = settings().get('cue_lines') == 'new'
    new = [(s, t) for s, t, direction in history if every and direction == 'inbound' and isinstance(s, int) and s > upto]
    new.append((seq, text))
    if every and isinstance(seq, int):
        # Lines that came after the one the turn is for, claimed into it before its context was built.
        new += [(row['scene_seq'], row.get('text') or '') for row in message_records.inbound(
            store, scene['_id'], after=seq, by=None).rows(fields=['scene_seq', 'text'])]
    earlier = [t for s, t, _ in history if not every or not isinstance(s, int) or s <= upto]
    tiers = Tiers(store, persona)
    vocabulary(store)
    repeated, said = tiers.openings(scene['_id']), tiers.said(scene['_id'])
    shown = [own_item.get('heading', '') + '\n' + own_item.get('body_markdown', '') for own_item in own]
    first = {}                                   # word -> (the new line's scene_seq, its spelling there)
    for line_seq, line in new:
        if not line or key_words.templated(line, repeated):
            continue
        for word in key_words.cross_words(line, _mention(scene['_id'])):
            if word not in said and word not in first and not any(key_words.found(word, t) for t in [*earlier, *shown]):
                first[word] = (line_seq, key_words.found(word, line) or word)
    if not first:
        return None
    moment = moment or clock.now()
    recent = (moment - timedelta(minutes=number('repeat_minutes'))).isoformat()
    words = [word for word in first if not View(store, FIRES, {'kind': 'cue', 'scene_id': scene['_id'], 'word': word,
                                                               'at': Range(gte=recent)}).first(fields=['_id'])]
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
    line = CUE % (first[word][1], lines, _month_day(latest, zone), '，' + place_kind if place_kind else '')
    fired(store, persona, 'cue', scene, event, moment, word=word, line_seq=first[word][0], lines=lines, latest=latest,
          kind_set=bool(place_kind))
    return {'kind': 'cue', 'cue': line}


def _line_seq(store, event):
    """The scene_seq of the line a turn is for, or None (a turn from no line)."""
    return (message_records.get(store, 'in-' + _episode(event), fields=['scene_seq']) or {}).get('scene_seq')


def fired(store, persona, what, scene, event, moment=None, *, episode=None, **fields):
    """One count row: what came back (FIRE_KINDS), in which conversation and turn (`episode`, else the event's), at
    which line (the turn's line's scene_seq) and when."""
    import uuid
    episode = episode or _episode(event)
    line = message_records.get(store, 'in-' + episode, fields=['scene_seq']) or {}
    store.collection(FIRES).insert({'_id': 'fire:' + uuid.uuid4().hex, 'kind': what, 'persona': persona,
                                    'scene_id': scene['_id'], 'event_id': event.get('event_id'), 'episode_id': episode,
                                    'scene_seq': line.get('scene_seq'), 'at': (moment or clock.now()).isoformat(),
                                    **fields})


def recalled(store, persona, ep, here, returned, crossed, before):
    """A recall's count rows: each line from elsewhere and past version it returned, and W6 when it brought back
    something the turn's own memories had not (`returned`: the ids of its memories)."""
    event = {'event_id': ep.get('source_event_id')}
    for entry in crossed:
        hers = entry['line'].startswith(tuple(MARKS[(True, corrected)].split('%s')[0] for corrected in (False, True)))
        fired(store, persona, 'elsewhere_hers' if hers else 'elsewhere_theirs', here, event, episode=ep['_id'],
              ref=entry['ref'])
    for entry in before:
        fired(store, persona, 'before', here, event, episode=ep['_id'], ref=entry.get('now'))
    automatic = {m.get('_id') for m in (ep.get('context') or {}).get('memories') or [] if isinstance(m, dict)}
    new = [key for key in [*returned, *(e['ref'] for e in crossed), *(e.get('now') for e in before)]
           if key and key not in automatic]
    if new:
        fired(store, persona, 'w6', here, event, episode=ep['_id'], new=len(set(new)))


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
    cutoff = ((moment or clock.now()) - timedelta(days=FIRES_DAYS)).isoformat()
    return store.collection(FIRES).delete({'kind': AnyOf(list(FIRE_KINDS)), 'at': Range(lt=cutoff)}, many=True)


# ── the reading (tools/memory_fires_report.py), counts only ─────────
def report(store, since, compactions=None):
    """ADR-097's reading from the count rows since `since` (ISO), per place and in all: her turns from someone's line,
    cues and cues a turn, her recalls in a cue's turn or the next one there (and those whose query has the cue's word),
    her notes back by word and by meaning, recall's lines from elsewhere (hers, others') and past versions, W6. With
    `compactions` ({DSH session id: [compaction end, ms]}), the minutes from the last compaction of the turn's session
    to each cue and note. Places are numbered by their turns and shown with their kind when set: never ids or names."""
    fires = fire_rows(store, since).rows()
    groups = set(_groups(store))
    episodes = {ep['_id']: ep for ep in episode_records.of_kind(store, 'external', scenes=sorted(groups)).rows(
        fields=['scene_id', 'native_session_id'])}
    lines = {}
    ids = ['in-' + key for key in episodes]
    for start in range(0, len(ids), 1000):
        for row in message_records.many(store, ids[start:start + 1000], since=since).rows(fields=['scene_seq']):
            lines[row['_id'][len('in-'):]] = row.get('scene_seq') or 0
    turns = {}
    for key, seq in lines.items():
        turns.setdefault(episodes[key]['scene_id'], []).append((seq, key))
    for scene_turns in turns.values():
        scene_turns.sort()
    following = {key: (scene_turns[i + 1][1] if i + 1 < len(scene_turns) else None)
                 for scene_turns in turns.values() for i, (_, key) in enumerate(scene_turns)}
    recalls = {}
    from . import audit as audit_trail
    for row in audit_trail.events(store, 'recall.read', since=since, by=None).each(fields=['stream_id', 'payload.query']):
        recalls.setdefault(row['stream_id'], []).append((row.get('payload') or {}).get('query') or '')
    order = sorted({*turns, *(f['scene_id'] for f in fires if f['scene_id'] in groups)},
                   key=lambda scene_id: (-len(turns.get(scene_id, [])), scene_id))
    label = {scene_id: 'group %d' % (n + 1) for n, scene_id in enumerate(order)}

    def blank():
        return {'turns': 0, 'cues': 0, 'recalls_after_a_cue': 0, 'recalls_with_the_cue_word': 0, 'notes_by_word': 0,
                'notes_by_meaning': 0, 'elsewhere_hers': 0, 'elsewhere_theirs': 0, 'before': 0, 'w6': 0,
                'w6_new_items': 0, 'since_compaction': []}
    places = {scene_id: blank() for scene_id in order}
    places['elsewhere (home, private chats)'] = blank()
    every = blank()
    for scene_id, scene_turns in turns.items():
        places[scene_id]['turns'] = len(scene_turns)
        every['turns'] += len(scene_turns)
    for fire in fires:
        entry = places.get(fire['scene_id']) or places['elsewhere (home, private chats)']
        kind_ = fire['kind']
        counted = ({'cue': 'cues', 'note': 'notes_by_word' if fire.get('by') == 'word' else 'notes_by_meaning',
                    'w6': 'w6'}).get(kind_, kind_)
        for target in (entry, every):
            target[counted] += 1
            if kind_ == 'w6':
                target['w6_new_items'] += int(fire.get('new') or 0)
        if kind_ == 'cue':
            asked = [q for key in (fire.get('episode_id'), following.get(fire.get('episode_id'))) if key
                     for q in recalls.get(key, [])]
            for target in (entry, every):
                target['recalls_after_a_cue'] += bool(asked)
                target['recalls_with_the_cue_word'] += any(key_words.found(fire.get('word') or '', q) for q in asked)
        if kind_ in ('cue', 'note') and compactions is not None:
            session = (episodes.get(fire.get('episode_id')) or {}).get('native_session_id') or (
                episode_records.get(store, fire.get('episode_id'), fields=['native_session_id']) or {}).get('native_session_id')
            at = datetime.fromisoformat(fire['at'].replace('Z', '+00:00')).timestamp() * 1000
            ends = [end for end in compactions.get(session, []) if end <= at]
            minutes = (at - max(ends)) / 60000 if ends else None
            for target in (entry, every):
                target['since_compaction'].append(minutes)

    def finish(entry):
        out = {k: v for k, v in entry.items() if k != 'since_compaction'}
        out['cues_a_turn'] = round(entry['cues'] / entry['turns'], 3) if entry['turns'] else None
        if compactions is not None:
            known = sorted(m for m in entry['since_compaction'] if m is not None)
            out['since_compaction'] = {'fires': len(entry['since_compaction']), 'no_compaction_before': sum(
                1 for m in entry['since_compaction'] if m is None), 'within_30_minutes': sum(1 for m in known if m < 30),
                'median_minutes': round(known[len(known) // 2]) if known else None}
        return out
    return {'since': since, 'all': finish(every),
            'places': {'%s%s' % (label.get(key, key), ' (%s)' % kind(key) if kind(key) else ''): finish(value)
                       for key, value in places.items() if value['turns'] or any(
                           value[k] for k in ('cues', 'notes_by_word', 'notes_by_meaning', 'w6'))}}
