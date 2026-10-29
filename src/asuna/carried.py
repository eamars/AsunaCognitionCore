"""What she carries: one function says it for every reader (ADR-096).

`carried(store, persona, cls, place)` gives the sections of her persona, voice, `self` and `core` that reach a turn of
one (place, class) pair: each section where its tier puts it (`memory_tiers.placed`), readable in the class, with its
`place:` tags honoured. The system prompt and its re-render, the identity budget and its gate, the room line, the
relevance gate, the action brain, `doc_refs_from_program`, the owner's probe, the memory tab and the settings card read
it; her notes and ledgers go through `note_sections`. Where a write leaves each section comes from
`memory_tiers.Tiers.placement_after`, so the gate measures what the write will carry.

Each pair has its own identity budget (`render.identity_tokens`, owner-only): `common.md`, persona, voice and the self
and core blocks as sent, in estimated tokens. A write that grows the layer in a pair over it is refused (`gate`); one
that shrinks it or keeps it the same goes through. A write returns the exact numbers (`room_line`);
`things_from_program` says how full each pair is in coarse words when they change (`room_block`). `count_days` keeps
per section × pair × day how many turns carried it, her recalls of it and the program's score (`carried_counts`, 30
days), and each section's first and last time carried (`carried_sections`). `install_checks` are her four checks
after an install, read only (`tools/carried_check.py`).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from . import clock
from . import visibility
from .evidence import canonical, sha
from .records import scenes as scene_records
from .records import episodes as episode_records
from .records.view import is_text
from .store.words import Larger, Range, Set, Smaller

IDENTITY = ('persona', 'voice', 'self', 'core')
SELF_BLOCKS = (('current_self', 'self'), ('character_core', 'core'))    # the context names of the self and core blocks
PERSONA_SHARE = 0.5          # the share of the ceiling a package's own seeds may fill before they get room on top
ROOM_VERSION = 2
# The pairs in her words (her choice, 2026-10-25), in the order she lists them: each place has one class, and a group
# the owner configured as home is a group read at home.
PAIR_WORDS = {('home', visibility.OWNER_PRIVATE): '家里', ('group', visibility.OWNER_PRIVATE): '家里那个群',
              ('group', visibility.PUBLIC): '外面的群', ('peer', visibility.OWNER_PRIVATE): '线',
              ('dm', visibility.PUBLIC): '私聊'}
# How full a pair's identity layer is, as the share of its limit (things_from_program, when it changes): a share under
# the bound takes the word; at the limit itself it is still 快满了, past it 超了.
ROOM_WORDS = ((0.5, '还宽裕'), (0.8, '用了一大半'), (1.0, '快满了'), (None, '超了'))
# What the per-place limit covers, said the same everywhere (the room line counts exactly these).
SCOPE_WORDS = '程序的开头说明、persona、voice、self、core'
# Her wording (2026-10-25): the room line lists, for the pairs that carry the section, each pair's total and its room.
ROOM_LINE = '这节约 %s。%s'
ROOM_PAIR, ROOM_LEFT, ROOM_OVER, ROOM_SEPARATOR = '%s %s（%s）', '剩 %s', '超 %s', '｜'
ROOM_NOWHERE = '带它的地方：无'
ROOM_FREED = '（原本带在 %d 处，每处腾出约 %s token）'    # her ask (2026-10-25): what a let_go freed, not only where it is now
TIER_LINE = '这一节的真带是 %s；你写的 when_shown 是 %s'      # her inject, by the name she is shown
TIER_LAST = '上一次挪档：%s · %s · %s'
TIER_NONE = '挪档史：无记录'
BY_WORDS = {'her': '你', 'program': '程序'}
OVER_WORDS = '%s 现在超 %s token，这次改动会让它更长。要腾地方：let_go 一节，或者把它写短。现在带得最多的是：%s'
# A write that takes a pair from within its limit to over it: the same words, from the number it would reach.
OVER_PAST = '%s 这次改动会让它超 %s token。要腾地方：let_go 一节，或者把它写短。现在带得最多的是：%s'
OVER_ALSO = '这一节会让 %d 处变长：%s'    # her wording: a public section can push several pairs over at once
COUNTS = 'carried_counts'          # section × pair × day, COUNT_DAYS kept
COUNTED = 'carried_days'           # the days counted
SECTIONS = 'carried_sections'      # each section's first and last time carried, never pruned
COUNT_DAYS = 30


# ── the owner of carried_counts, carried_days and carried_sections ──
# Read and written only through these. A persona given None finds nothing (ADR-104 section 4).
def count_day(store, rows):
    """A local day's count rows, each written whole (made or replaced)."""
    counts = store.collection(COUNTS)
    for row in rows:
        counts.replace(row, create=True)


def mark_day(store, persona, day, rows, at):
    """A persona's local day (an ISO date) is counted, with how many count rows it has."""
    store.collection(COUNTED).replace({'_id': 'day:%s:%s' % (persona, day), 'persona': persona, 'day': day,
                                       'rows': rows, 'at': at}, create=True)


def counted_days(store, persona):
    """The days counted for a persona (ISO dates)."""
    return set(store.collection(COUNTED).group({'persona': persona}, ['day'], None)) if is_text(persona) else set()


def forget_days(store, persona, before):
    """A persona's count rows and day marks of days before `before` (an ISO date) go; how many count rows went."""
    if not is_text(persona):
        return 0
    where = {'persona': persona, 'day': Range(lt=before)}
    deleted = store.collection(COUNTS).delete(where, many=True)
    store.collection(COUNTED).delete(dict(where), many=True)
    return deleted


def note_section(store, persona, ref, start, end):
    """A section was carried from `start` to `end`: its first and last time carried, kept."""
    store.collection(SECTIONS).update({'_id': 'section:' + sha(canonical([persona, ref]))[:32]},
                                      [Set({'persona': persona, 'section': ref}), Smaller('first_carried_at', start),
                                       Larger('last_carried_at', end)], create=True)


def number(value):
    return format(int(value), ',')


def pairs(config):
    """The (place, class) pairs a turn can have: the four places, and a group read at home when one is configured."""
    found = list(visibility.PLACE_CLASS.items())
    if config.get('home_groups'):
        found.append(('group', visibility.OWNER_PRIVATE))
    return found


def contents(store, persona, slugs=IDENTITY):
    from .documents import DocumentStore
    docs = DocumentStore(store, persona)
    return {slug: docs.read(slug)[1] for slug in slugs}


def placed(store, persona, slug, content, placements=None):
    """A document as turns read it: each section's `inject` follows its tier, and `placements` ({sid: tier}, from
    placement_after) where a write will leave them."""
    from . import memory_tiers
    return memory_tiers.placed(store, persona, slug, content, placements)


def sections(content, cls, place=None):
    """Of a placed document, the sections carried in a turn of this class and place."""
    from .render import readable_sections
    if not content or 'sections' not in content:
        return []
    return readable_sections(content, cls, place=place)


def carried(store, persona, cls, place, *, docs=None, placements=None):
    """{slug: carried sections} of persona, voice, self and core for one (place, class) pair."""
    docs = docs if docs is not None else contents(store, persona)
    return {slug: sections(placed(store, persona, slug, docs.get(slug), (placements or {}).get(slug)), cls, place)
            for slug in IDENTITY}


def note_sections(store, persona, slug, content, cls=visibility.PUBLIC, placements=None):
    """A note's sections as a turn reads them, before its per-turn view (context_budget.note_view): placed, readable
    here (group notes are public), tucked ones included so the view can count them."""
    from .documents import INJECTS
    from .render import readable_sections
    content = placed(store, persona, slug, content, placements)
    return readable_sections(content, cls, inject=INJECTS) if content and 'sections' in content else []


def system_text(common, found, docs=None):
    """The persona render: common.md, then the carried persona sections, then voice (a legacy persona revision without
    sections renders its body)."""
    from .documents import render_markdown

    def text(slug):
        content = (docs or {}).get(slug)
        if content is not None and 'sections' not in content:
            return content.get('body', '')
        return render_markdown(found.get(slug) or [])
    out = common + '\n' + text('persona')
    voice = text('voice')
    return out + ('\n' + voice if voice else '')


def self_block(slug, found):
    """The self or core block as a turn sends it."""
    return {'items': [{'heading': s['heading'], 'body': s['body'], 'ref': 'doc:%s#%s' % (slug, s['sid'])} for s in found]}


def tokens(common, found, docs):
    """Estimated tokens of one pair's identity layer as sent: the persona render and the self and core blocks (a block
    is sent once its document has sections)."""
    from .render import estimate_tokens
    total = estimate_tokens(system_text(common, found, docs))
    for slug in ('self', 'core'):
        if ((docs or {}).get(slug) or {}).get('sections'):
            total += estimate_tokens(json.dumps(self_block(slug, found.get(slug) or []), ensure_ascii=False))
    return total


def identity(store, persona, *, docs=None, placements=None, common=None):
    """{(place, class): estimated tokens} of each pair's identity layer."""
    return {pair: size for pair, (_, size) in laid_out(store, persona, docs=docs, placements=placements,
                                                        common=common).items()}


def limit(store, persona):
    """Each pair's identity ceiling: render.identity_tokens (owner-only), plus what a package's own seeds need above the
    persona share with a quarter to grow (render.SEED_ROOM), never above the character window × render.max_window_share;
    None when nothing bounds it."""
    from .persona_model import effective
    from .render import SEED_ROOM, model_and_policy, seed_estimate
    model, policy = model_and_policy(store, persona)
    ceiling = effective(model, 'render.identity_tokens', policy)
    share = effective(model, 'render.max_window_share', policy)
    window = (store.config.get('character') or {}).get('context_window')
    seeded = seed_estimate(store, persona)
    wanted = math.ceil(seeded * SEED_ROOM) if seeded else None
    if ceiling:
        wanted = ceiling + max(0, (wanted or 0) - int(ceiling * PERSONA_SHARE))
    cap = int(window * share) if window and share else None
    return min(wanted, cap) if wanted and cap else wanted or cap


def placements_after(store, persona, slug, intent, before, after):
    """{sid: tier} where this write leaves the sections it moves (memory_tiers.Tiers.placement_after)."""
    from . import memory_tiers
    if not memory_tiers.ENABLED:
        return {}
    plan = memory_tiers.Tiers(store, persona).placement_after(slug, intent or {}, before, after)
    return {sid: steps[-1][0] for sid, steps in plan.items() if steps}


def weight(slug, section):
    """Estimated tokens of one section as it is carried."""
    from .documents import render_markdown
    from .render import estimate_tokens
    if slug in ('self', 'core'):
        return estimate_tokens(json.dumps(self_block(slug, [section])['items'][0], ensure_ascii=False))
    return estimate_tokens(render_markdown([section]))


def laid_out(store, persona, *, docs=None, placements=None, common=None):
    """{(place, class): (carried sections by slug, estimated tokens)} of each pair: what `identity` counts."""
    from .render import common_text
    docs = docs if docs is not None else contents(store, persona)
    common = common if common is not None else common_text(store.config)
    laid = {slug: placed(store, persona, slug, docs.get(slug), (placements or {}).get(slug)) for slug in IDENTITY}
    out = {}
    for pair in pairs(store.config):
        found = {slug: sections(laid[slug], pair[1], pair[0]) for slug in IDENTITY}
        out[pair] = (found, tokens(common, found, docs))
    return out


def ordered(pairs_found):
    """Pairs in her order (PAIR_WORDS)."""
    order = list(PAIR_WORDS)
    return sorted(pairs_found, key=lambda pair: order.index(pair) if pair in order else len(order))


def carrying(store, persona, slug, sid, laid=None):
    """The pairs that carry this section now."""
    laid = laid if laid is not None else laid_out(store, persona)
    return [pair for pair in ordered(laid) if any(s['sid'] == sid for s in laid[pair][0][slug])]


def room_line(store, persona, slug, section, was=0):
    """What a write to her identity, or a let_go, returns: the section's weight and, for each pair that carries it, the
    room left (or how far over), from the number the gate uses; None when nothing bounds it. `was`: how many pairs
    carried it before a let_go, so a section carried nowhere now says what it freed."""
    ceiling = limit(store, persona)
    if not ceiling or slug not in IDENTITY or not section:
        return None
    laid = laid_out(store, persona)
    parts = []
    for pair in carrying(store, persona, slug, section['sid'], laid):
        size = laid[pair][1]
        left = ceiling - size
        parts.append(ROOM_PAIR % (PAIR_WORDS[pair], number(size),
                                  (ROOM_LEFT if left >= 0 else ROOM_OVER) % number(abs(left))))
    heavy = number(weight(slug, section))
    nowhere = ROOM_NOWHERE + (ROOM_FREED % (was, heavy) if was else '')
    return ROOM_LINE % (heavy, ROOM_SEPARATOR.join(parts) or nowhere)


def room_word(size, ceiling):
    """The coarse word for a pair's share of its limit (ROOM_WORDS; the limit itself is still 快满了)."""
    share = size / ceiling
    for bound, word in ROOM_WORDS:
        if bound is None or share < bound or (bound == 1.0 and share <= bound):
            return word
    return ROOM_WORDS[-1][1]


def room_ranges():
    """ROOM_WORDS as the ranges the program uses, for the note that explains them."""
    out, low = [], 0
    for bound, word in ROOM_WORDS:
        out.append('%s %s' % (word, '不到 %d%%' % (bound * 100) if not low else
                              '%d%%–%d%%' % (low * 100, bound * 100) if bound else '过了 %d%%' % (low * 100)))
        low = bound
    return '，'.join(out)


def _local(store, persona, moment):
    try:
        when = datetime.fromisoformat(str(moment).replace('Z', '+00:00'))
    except ValueError:
        return str(moment)
    return when.astimezone(_zone(store)).strftime('%Y-%m-%d %H:%M')


def tier_line(store, persona, slug, section):
    """When a section's `inject` and its tier differ: both, and its last move (when, who, why) on the next line; None
    when they agree or tiers are off."""
    from . import memory_tiers
    if not memory_tiers.ENABLED or not section:
        return None
    tiers = memory_tiers.Tiers(store, persona)
    row = tiers.item(slug, section['sid'])
    if not row or memory_tiers.TO_INJECT[row['place']] == section.get('inject'):
        return None
    last = tiers.last_move(row['_id'])
    history = (TIER_LAST % (_local(store, persona, last['at']), BY_WORDS[memory_tiers.moved_by(last)],
                            memory_tiers.REASONS.get(last['reason'], last['reason'])) if last else TIER_NONE)
    return TIER_LINE % (row['place'], section.get('inject')) + '\n' + history


def over_words(store, persona, pair, before, after, ceiling, docs=None):
    """A refusal: the pair, how far over it is (or would be), the way out, and the three largest sections it carries
    now; every number is that pair's own (laid_out, as carried counts it)."""
    found = laid_out(store, persona, docs=docs)[pair][0]
    sizes = sorted(((weight(slug, s), s.get('heading') or s['sid']) for slug in IDENTITY for s in found[slug]),
                   reverse=True)[:3]
    largest = '、'.join('「%s」%s' % (heading, number(size)) for size, heading in sizes)
    if before > ceiling:
        return OVER_WORDS % (PAIR_WORDS[pair], number(before - ceiling), largest)
    return OVER_PAST % (PAIR_WORDS[pair], number(after - ceiling), largest)


def gate(store, persona):
    """For DocumentStore.apply and adopt_seed: refuse a write that grows the identity layer in a pair over its limit
    (each pair on its own, measured as the write will carry it), and growth of a note far over its own limit."""
    from .context_budget import note_gate
    from .documents import DocumentError, DocumentStore

    def check(slug, new_content, intent=None):
        before = DocumentStore(store, persona).read(slug)[1]
        moved = placements_after(store, persona, slug, intent, before, new_content)
        if slug not in IDENTITY:
            note_gate(slug, placed(store, persona, slug, before), placed(store, persona, slug, new_content, moved))
            return
        ceiling = limit(store, persona)
        if not ceiling:
            return
        current = contents(store, persona)
        proposed, placements = {**current, slug: new_content}, {slug: moved}
        now = identity(store, persona, docs=current)
        then = identity(store, persona, docs=proposed, placements=placements)
        over = [(then[pair] - ceiling, pair) for pair in then if then[pair] > now[pair] and then[pair] > ceiling]
        if over:
            pair = max(over)[1]
            said = over_words(store, persona, pair, now[pair], then[pair], ceiling, current)
            if len(over) > 1:     # every pair this write takes or keeps over, so trimming one is not refused again
                pairs = [p for p in then if any(p == q for _, q in over)]
                said += '\n' + OVER_ALSO % (len(pairs), '｜'.join('%s 超 %s' % (PAIR_WORDS[p], number(then[p] - ceiling))
                                                                  for p in pairs))
            raise DocumentError('PERSONA_RENDER_OVER_BUDGET', said)
    return check


def room_block(store, persona, cls, scene_id):
    """things_from_program: how full each pair readable here is, in coarse words, only when the words changed since
    this conversation was last told; None otherwise."""
    from . import memory_tiers
    ceiling = limit(store, persona)
    if not ceiling:
        return None
    words = {PAIR_WORDS[pair]: room_word(size, ceiling)
             for pair, size in identity(store, persona).items() if visibility.readable(pair[1], cls)}
    key = 'room:%s:%s' % (persona, sha(str(scene_id).encode())[:24])
    told = memory_tiers.room_told(store, key)
    if told and told.get('words') == words and told.get('version') == ROOM_VERSION:
        return None
    memory_tiers.tell_room(store, key, persona, scene_id, words, ROOM_VERSION, clock.now().isoformat())
    return words


# ── what was carried, counted (carried_counts) ─────────────────────
def manifest(found, place, cls, moment, notes=(), brought_up=(), would_surface=()):
    """What a turn carried, for its episode manifest: the section refs of its pair, the group-notes sections shown,
    the sections its own retrieval brought up, and the carried ones it would have brought up had they not been
    carried (together, the program's score)."""
    return {'at': moment.isoformat() if hasattr(moment, 'isoformat') else moment, 'place': place, 'class': cls,
            'refs': ['doc:%s#%s' % (slug, s['sid']) for slug in IDENTITY for s in found.get(slug) or []],
            'notes': list(notes), 'brought_up': list(brought_up), 'would_surface': list(would_surface)}


def _zone(store):
    from .schedule_rules import her_zone
    return her_zone(store.config)['tz']


def _bounds(day, zone):
    start = datetime.combine(day, datetime.min.time(), zone)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


class _Past:
    """Each turn's carried sections where its episode does not record them: the tier at the turn's time from the
    `move` rows, the documents' sections and tags as they are now (so the rows are labelled reconstructed)."""

    def __init__(self, store, persona):
        from . import memory_tiers
        from .documents import DocumentStore
        rows = memory_tiers.Tiers(store, persona).items()
        self.items = {row['_id']: row for row in rows}
        self.moves = {}
        for move in memory_tiers.moves(store, persona).each(fields=['item', 'from', 'to', 'at']):
            self.moves.setdefault(move['item'], []).append((move['at'], move['from'], move['to']))
        for moves in self.moves.values():
            moves.sort()
        docs, self.sections = DocumentStore(store, persona), {}
        for row in rows:
            if row['doc'] not in self.sections:
                content = docs.read(row['doc'])[1] or {}
                self.sections[row['doc']] = {s['sid']: s for s in content.get('sections') or []}

    def tier_at(self, row, moment):
        if moment < (row.get('added') or ''):
            return None
        moves = self.moves.get(row['_id']) or []
        place = moves[0][1] if moves else row['place']
        for at, _, to in moves:
            if at > moment:
                break
            place = to
        return place

    def refs(self, moment, scene_id, cls, place):
        from . import memory_tiers
        from .group_admin import notes_slug
        out = []
        for row in self.items.values():
            kind = row['store']
            if kind not in (*IDENTITY, 'group_notes') or self.tier_at(row, moment) != memory_tiers.CARRIED:
                continue
            if kind == 'group_notes' and row['doc'] != notes_slug(scene_id):
                continue
            section = self.sections.get(row['doc'], {}).get(row['sid'])
            if not section or not visibility.readable(section.get('visibility') or 'public', cls):
                continue
            pins = visibility.section_places(section)
            if kind != 'group_notes' and pins and place not in pins:
                continue
            out.append('doc:%s#%s' % (row['doc'], row['sid']))
        return out


def _turns(store, persona, start, end):
    """The day's turns, found through their `turn.output` audit rows (indexed by type and time): (time, pair, refs
    carried, refs the program scored, reconstructed)."""
    past, seen, out = None, set(), []
    from . import audit as audit_trail
    for row in audit_trail.events(store, 'turn.output', since=start, before=end).each(
            fields=['stream_id', 'occurred_at']):
        if row['stream_id'] in seen:
            continue
        seen.add(row['stream_id'])
        ep = episode_records.get(store, row['stream_id'], fields=['persona', 'scene_id', 'manifest.session_class',
                                                                  'manifest.carried', 'context.memories'])
        if not ep or ep.get('persona') != persona:
            continue
        mark = (ep.get('manifest') or {}).get('carried')
        if mark:
            out.append((mark['at'], (mark['place'], mark['class']), [*mark['refs'], *(mark.get('notes') or [])],
                        [*(mark.get('brought_up') or []), *(mark.get('would_surface') or [])], False))
            continue
        scene = scene_records.get(store, ep.get('scene_id'), fields=['kind']) or {}
        cls = (ep.get('manifest') or {}).get('session_class') or visibility.PUBLIC
        place = visibility.place_of(store.config, {**scene, '_id': ep.get('scene_id')}, cls)
        past = past or _Past(store, persona)
        brought = [m.get('_id') for m in (ep.get('context') or {}).get('memories') or [] if m.get('kind') == 'own_item']
        out.append((row['occurred_at'], (place, cls), past.refs(row['occurred_at'], ep.get('scene_id'), cls, place),
                    brought, True))
    return out


def _recalls(store, persona, start, end):
    """Her recalls of her sections that day: [(pair, ref)], from `recall.read` (the sections she read and her own
    items that came back), the pair from the turn's place and class."""
    out = []
    from . import audit as audit_trail
    for row in audit_trail.events(store, 'recall.read', since=start, before=end, by=None).each(
            fields=['stream_id', 'payload']):
        payload = row.get('payload') or {}
        ep = episode_records.get(store, row.get('stream_id'), fields=['persona', 'manifest.session_class'])
        if not ep or ep.get('persona') != persona:
            continue
        cls = (ep.get('manifest') or {}).get('session_class') or visibility.PUBLIC
        refs = {'doc:%s#%s' % (item.get('doc'), item.get('sid')) for item in payload.get('sections_read') or []}
        refs |= {m for m in payload.get('memories') or [] if isinstance(m, str) and m.startswith('doc:')}
        out += [((payload.get('place'), cls), ref) for ref in sorted(refs)]
    return out


def _entry(rows, ref, pair):
    return rows.setdefault((ref, pair), {'turns_carried': 0, 'program_score': 0, 'recall_hits': 0, 'first': None,
                                         'last': None, 'reconstructed': False})


def day_counts(store, persona, day, zone=None):
    """The carried_counts rows of one local day, per section × pair: the turns that carried it, the pair's turns that
    day, her recalls of it there, and in how many turns the program's retrieval scored it above the floor
    (program_score: brought up, or would have been had it not been carried). Also returns, per section, the first and
    last time it was carried that day (for carried_sections)."""
    zone = zone or _zone(store)
    start, end = _bounds(day, zone)
    pair_turns, rows = {}, {}
    for at, pair, refs, scored, rebuilt in _turns(store, persona, start, end):
        pair_turns[pair] = pair_turns.get(pair, 0) + 1
        for ref in refs:
            entry = _entry(rows, ref, pair)
            entry['turns_carried'] += 1
            entry['first'] = min(filter(None, (entry['first'], at)))
            entry['last'] = max(filter(None, (entry['last'], at)))
            entry['reconstructed'] |= rebuilt
        for ref in set(scored):
            entry = _entry(rows, ref, pair)
            entry['program_score'] += 1
            entry['reconstructed'] |= rebuilt
    for pair, ref in _recalls(store, persona, start, end):
        if pair in PAIR_WORDS:
            _entry(rows, ref, pair)['recall_hits'] += 1
    out, spans = [], {}
    for (ref, pair), entry in sorted(rows.items()):
        out.append({'_id': 'count:' + sha(canonical([persona, day.isoformat(), ref, list(pair)]))[:32],
                    'persona': persona, 'section': ref, 'pair': PAIR_WORDS.get(pair, '%s/%s' % pair),
                    'day': day.isoformat(), 'turns_carried': entry['turns_carried'],
                    'pair_turns': pair_turns.get(pair, 0), 'recall_hits': entry['recall_hits'],
                    'program_score': entry['program_score'], 'reconstructed': entry['reconstructed']})
        if entry['first']:
            first, last = spans.get(ref, (entry['first'], entry['last']))
            spans[ref] = (min(first, entry['first']), max(last, entry['last']))
    return out, spans


def count_days(store, persona, moment=None):
    """The nightly count (the audit retention thread): each whole local day not counted yet (carried_days), back to
    when the tiers went on and at most COUNT_DAYS; day rows older than COUNT_DAYS go, carried_sections (each
    section's first and last time carried) stays. Returns {'days', 'rows', 'deleted'}."""
    from . import memory_tiers
    moment = moment or clock.now()
    zone = _zone(store)
    today = moment.astimezone(zone).date()
    oldest = today - timedelta(days=COUNT_DAYS)
    deleted = forget_days(store, persona, oldest.isoformat())
    first = memory_tiers.items(store, persona, by='added').first(fields=['added'])
    if not first or not first.get('added'):
        return {'days': 0, 'rows': 0, 'deleted': deleted}
    began = datetime.fromisoformat(str(first['added']).replace('Z', '+00:00')).astimezone(zone).date()
    done = counted_days(store, persona)
    day, days, written = max(oldest, began), 0, 0
    while day < today:
        if day.isoformat() not in done:
            found, carried_at = day_counts(store, persona, day, zone)
            count_day(store, found)
            for ref, (start, end) in carried_at.items():
                note_section(store, persona, ref, start, end)
            mark_day(store, persona, day.isoformat(), len(found), moment.isoformat())
            days, written = days + 1, written + len(found)
        day += timedelta(days=1)
    return {'days': days, 'rows': written, 'deleted': deleted}



# ── install checks (hers, read only) ───────────────────────────────
# A section that would grow one pair only, to see that pair's refusal: (visibility, place tag).
PROBE = {('home', visibility.OWNER_PRIVATE): ('owner_private', 'home'),
         ('peer', visibility.OWNER_PRIVATE): ('owner_private', 'peer'),
         ('group', visibility.OWNER_PRIVATE): ('owner_private', 'group'),
         ('group', visibility.PUBLIC): ('public', 'group'), ('dm', visibility.PUBLIC): ('public', 'dm')}


def _named(text):
    """The pair a refusal names (the longest pair word it starts with)."""
    words = sorted(PAIR_WORDS.items(), key=lambda item: -len(item[1]))
    return next((pair for pair, word in words if (text or '').startswith(word + ' ')), None)


def install_checks(store, persona):
    """The four checks she runs after an install, reading only: [(check, passed, what it saw, in numbers)].
    1. The latest turn's system_ref section list is what carried() gives its pair now.
    2. Each pair's refusal says carried()'s number for the pair it names (a write that would grow it, never made).
    3. A write to her identity gets its room line.
    4. Every section whose inject and tier differ is said."""
    import re
    from . import memory_tiers
    from .documents import DocumentError
    out, ep = [], None
    from . import audit as audit_trail
    for row in audit_trail.events(store, 'turn.output').rows(newest_first=True, limit=50, fields=['stream_id']):
        ep = episode_records.get(store, row['stream_id'], fields=['system_ref'], persona=persona, carried=True)
        if ep:
            break
    if ep:
        ref = ep['system_ref']
        now = carried(store, persona, ref['session_class'], ref.get('place'))
        same = all(ref['carried'].get(slug) == [s['sid'] for s in now[slug]] for slug in ('persona', 'voice'))
        out.append(('system_ref_is_carried', same, {'pair': PAIR_WORDS.get((ref.get('place'), ref['session_class']))}))
    else:
        out.append(('system_ref_is_carried', False, {'turns_with_carried_ref': 0}))
    ceiling, docs = limit(store, persona), contents(store, persona)
    sizes, check = identity(store, persona, docs=docs), gate(store, persona)
    persona_doc = docs.get('persona') or {'sections': []}
    for pair in [pair for pair in ordered(sizes) if pair in PROBE]:
        shown, (seen, tag) = None, PROBE[pair]
        probe = {'sid': 'install-check', 'heading': 'install-check', 'visibility': seen, 'inject': 'always',
                 'tags': ['place:' + tag], 'body': '字' * (max((ceiling or 0) - sizes[pair], 0) + 200),
                 'body_sha256': 'install-check'}
        proposed = {**persona_doc, 'sections': [*persona_doc.get('sections', []), probe]}
        try:
            check('persona', proposed, None)
        except DocumentError as exc:
            shown = exc.detail
        named, then = _named(shown), identity(store, persona, docs={**docs, 'persona': proposed})
        expected = None
        if named and ceiling:
            expected = sizes[named] - ceiling if sizes[named] > ceiling else then[named] - ceiling
        said = re.search(r'超 ([\d,]+) token', shown or '')
        got = int(said.group(1).replace(',', '')) if said else None
        out.append(('refusal_is_carried_number', bool(named and got == expected),
                    {'pair': PAIR_WORDS[pair], 'named': PAIR_WORDS.get(named), 'carried': sizes[pair],
                     'limit': ceiling, 'said': got, 'expected': expected}))
    home = carried(store, persona, visibility.OWNER_PRIVATE, 'home', docs=docs)
    sample = next(((slug, s) for slug in IDENTITY for s in home[slug]), None)
    line = room_line(store, persona, *sample) if sample else None
    out.append(('room_line', bool(line and line.startswith('这节约 ')),
                {'sections_carried_at_home': sum(len(found) for found in home.values())}))
    tiers, differ, said = memory_tiers.Tiers(store, persona), 0, 0
    for slug in IDENTITY:
        for section in (docs.get(slug) or {}).get('sections') or []:
            row = tiers.item(slug, section['sid'])
            if row and memory_tiers.TO_INJECT[row['place']] != section.get('inject'):
                differ += 1
                said += (tier_line(store, persona, slug, section) or '').startswith('这一节的真带是')
    out.append(('tier_line', said == differ, {'differ': differ, 'said': said}))
    return out
