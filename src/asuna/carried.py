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
per section × pair × day how many turns carried it (`carried_counts`, 30 days).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from . import visibility
from .evidence import canonical, sha

IDENTITY = ('persona', 'voice', 'self', 'core')
SELF_BLOCKS = (('current_self', 'self'), ('character_core', 'core'))    # the context names of the self and core blocks
PERSONA_SHARE = 0.5          # the share of the ceiling a package's own seeds may fill before they get room on top
ROOM_VERSION = 1
# The pairs in her words: each place has one class, and a group the owner configured as home is a group read at home.
PAIR_WORDS = {('home', visibility.OWNER_PRIVATE): '家里', ('peer', visibility.OWNER_PRIVATE): '另一个自己那条线',
              ('group', visibility.PUBLIC): '群里', ('group', visibility.OWNER_PRIVATE): '算作家里的群',
              ('dm', visibility.PUBLIC): '私聊'}
# How full a pair's identity layer is, as the share of its limit (things_from_program, when it changes).
ROOM_WORDS = ((0.5, '还宽裕'), (0.8, '用了一大半'), (1.0, '快满了'), (None, '超了'))
ROOM_LINE = ('这一节约 %s token。各处每回合随身带的身份部分（程序的开头说明、persona、voice、self、core 合起来，每个地方各算各的，'
             '上限 %s）：%s。')
TIER_LINE = '你写的 when_shown 是 %s，它现在在%s：每回合带不带看它在哪；when_shown 照你写的留着，程序不改它。'
INJECT_WORDS = {'always': 'always（每回合都带）', 'on_demand': 'on_demand（用到才带）', 'never': 'never（不自动带）'}
OVER_WORDS = ('写完%s随身带的身份部分约 %s token，上限 %s，超出 %s（写之前是 %s；每个地方各算各的）；%s'
              '先用 let_go 把不常用的随身节放到手边（recall 还读得到），或把这次写的改短')
OVER_LARGEST = '那里最大的随身节：%s。'
COUNTS = 'carried_counts'
COUNT_DAYS = 30


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
    from .render import common_text
    docs = docs if docs is not None else contents(store, persona)
    common = common if common is not None else common_text(store.config)
    laid = {slug: placed(store, persona, slug, docs.get(slug), (placements or {}).get(slug)) for slug in IDENTITY}
    return {pair: tokens(common, {slug: sections(laid[slug], pair[1], pair[0]) for slug in IDENTITY}, docs)
            for pair in pairs(store.config)}


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


def room_parts(store, persona, sizes, ceiling):
    parts = []
    for pair, size in sizes.items():
        left = ceiling - size
        parts.append('%s %s（%s %s）' % (PAIR_WORDS[pair], number(size), '还剩' if left >= 0 else '超出', number(abs(left))))
    return '、'.join(parts)


def room_line(store, persona, slug, section):
    """What a write to her identity, or a let_go, returns: the section's weight and each pair's size and room, from the
    number the gate uses; None when nothing bounds it."""
    ceiling = limit(store, persona)
    if not ceiling or slug not in IDENTITY or not section:
        return None
    return ROOM_LINE % (number(weight(slug, section)), number(ceiling),
                        room_parts(store, persona, identity(store, persona), ceiling))


def tier_line(store, persona, slug, section):
    """When a section's `inject` and its tier differ: both, said once (None when they agree or tiers are off)."""
    from . import memory_tiers
    if not memory_tiers.ENABLED or not section:
        return None
    row = memory_tiers.Tiers(store, persona).item(slug, section['sid'])
    if not row or memory_tiers.TO_INJECT[row['place']] == section.get('inject'):
        return None
    return TIER_LINE % (INJECT_WORDS.get(section.get('inject'), section.get('inject')), row['place'])


def over_words(store, persona, pair, before, after, ceiling, docs, placements):
    """A refusal: the pair that is over, with that pair's own numbers before and after, and its largest carried
    sections."""
    found = carried(store, persona, pair[1], pair[0], docs=docs, placements=placements)
    sizes = sorted(((weight(slug, s), slug, s['sid']) for slug in IDENTITY for s in found[slug]), reverse=True)[:3]
    largest = '、'.join('%s#%s（约 %s）' % (slug, sid, number(size)) for size, slug, sid in sizes)
    return OVER_WORDS % (PAIR_WORDS[pair], number(after), number(ceiling), number(after - ceiling), number(before),
                         OVER_LARGEST % largest if largest else '')


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
            raise DocumentError('PERSONA_RENDER_OVER_BUDGET', over_words(store, persona, pair, now[pair], then[pair],
                                                                          ceiling, proposed, placements))
    return check


def room_block(store, persona, cls, scene_id):
    """things_from_program: how full each pair readable here is, in coarse words, only when the words changed since
    this conversation was last told; None otherwise."""
    from .context_budget import _tier
    from .memory_tiers import COLLECTION
    ceiling = limit(store, persona)
    if not ceiling:
        return None
    words = {PAIR_WORDS[pair]: _tier(ROOM_WORDS, size / ceiling)
             for pair, size in identity(store, persona).items() if visibility.readable(pair[1], cls)}
    key = 'room:%s:%s' % (persona, sha(str(scene_id).encode())[:24])
    told = store.db[COLLECTION].find_one({'_id': key})
    if told and told.get('words') == words and told.get('version') == ROOM_VERSION:
        return None
    store.db[COLLECTION].update_one({'_id': key}, {'$set': {'row': 'room_told', 'persona': persona, 'scene_id': scene_id,
                                                            'words': words, 'version': ROOM_VERSION,
                                                            'at': datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return words


# ── what was carried, counted (carried_counts) ─────────────────────
def manifest(found, place, cls, moment, notes=(), brought_up=()):
    """What a turn carried, for its episode manifest: the section refs of its pair, the group-notes sections shown,
    and the sections its own retrieval brought up."""
    return {'at': moment.isoformat() if hasattr(moment, 'isoformat') else moment, 'place': place, 'class': cls,
            'refs': ['doc:%s#%s' % (slug, s['sid']) for slug in IDENTITY for s in found.get(slug) or []],
            'notes': list(notes), 'brought_up': list(brought_up)}


def _zone(store, persona):
    from zoneinfo import ZoneInfo
    from .persona_model import timezone as persona_timezone
    from .render import model_and_policy
    model, policy = model_and_policy(store, persona)
    try:
        return ZoneInfo(persona_timezone(model, policy, store.config)[0])
    except Exception:
        return timezone.utc


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
        for move in store.db[memory_tiers.COLLECTION].find({'row': 'move', 'persona': persona},
                                                           {'item': 1, 'from': 1, 'to': 1, 'at': 1}):
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
        out, notes = [], []
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
            (notes if kind == 'group_notes' else out).append('doc:%s#%s' % (row['doc'], row['sid']))
        return out, notes


def _entry(rows, ref, pair):
    return rows.setdefault((ref, pair), {'turns': 0, 'brought_up': 0, 'last_carried': None, 'reconstructed': False})


def day_counts(store, persona, day, zone=None):
    """The carried_counts rows of one local day: per section × pair, the turns that carried it, the pair's turns that
    day, when it was last carried, and in how many of its turns the program's retrieval brought it up."""
    zone = zone or _zone(store, persona)
    start, end = _bounds(day, zone)
    turns = []
    for ep in store.db.episodes.find({'persona': persona, 'manifest.carried.at': {'$gte': start, '$lt': end}},
                                     {'manifest.carried': 1}):
        mark = ep['manifest']['carried']
        turns.append((mark['at'], (mark['place'], mark['class']), [*mark['refs'], *(mark.get('notes') or [])],
                      mark.get('brought_up') or [], False))
    past, seen = None, set()
    for row in store.db.audit_events.find({'type': 'turn.output', 'occurred_at': {'$gte': start, '$lt': end}},
                                          {'stream_id': 1, 'occurred_at': 1}).sort('occurred_at', 1):
        if row['stream_id'] in seen:
            continue
        seen.add(row['stream_id'])
        ep = store.db.episodes.find_one({'_id': row['stream_id']}, {'persona': 1, 'scene_id': 1,
                                                                   'manifest.session_class': 1, 'manifest.carried': 1,
                                                                   'context.memories': 1})
        if not ep or ep.get('persona') != persona or (ep.get('manifest') or {}).get('carried'):
            continue
        scene = store.db.scenes.find_one({'_id': ep.get('scene_id')}, {'kind': 1}) or {}
        cls = (ep.get('manifest') or {}).get('session_class') or visibility.PUBLIC
        place = visibility.place_of(store.config, {**scene, '_id': ep.get('scene_id')}, cls)
        past = past or _Past(store, persona)
        refs, notes = past.refs(row['occurred_at'], ep.get('scene_id'), cls, place)
        brought = [m.get('_id') for m in (ep.get('context') or {}).get('memories') or [] if m.get('kind') == 'own_item']
        turns.append((row['occurred_at'], (place, cls), [*refs, *notes], brought, True))
    pair_turns, rows = {}, {}
    for at, pair, refs, brought, rebuilt in turns:
        pair_turns[pair] = pair_turns.get(pair, 0) + 1
        for ref in refs:
            entry = _entry(rows, ref, pair)
            entry['turns'] += 1
            entry['last_carried'] = max(filter(None, (entry['last_carried'], at)))
            entry['reconstructed'] |= rebuilt
        for ref in brought:
            entry = _entry(rows, ref, pair)
            entry['brought_up'] += 1
            entry['reconstructed'] |= rebuilt
    return [{'_id': 'count:' + sha(canonical([persona, day.isoformat(), ref, list(pair)]))[:32], 'persona': persona,
             'day': day.isoformat(), 'section': ref, 'place': pair[0], 'class': pair[1], **entry,
             'pair_turns': pair_turns[pair]} for (ref, pair), entry in sorted(rows.items())]


def count_days(store, persona, moment=None):
    """The nightly count (the audit retention thread): each whole local day not counted yet, back to when the tiers
    went on and at most COUNT_DAYS; rows older than COUNT_DAYS go. Returns {'days', 'rows', 'deleted'}."""
    from . import memory_tiers
    moment = moment or datetime.now(timezone.utc)
    zone = _zone(store, persona)
    today = moment.astimezone(zone).date()
    oldest = today - timedelta(days=COUNT_DAYS)
    rows = store.db[COUNTS]
    deleted = rows.delete_many({'persona': persona, 'day': {'$lt': oldest.isoformat()}}).deleted_count
    first = store.db[memory_tiers.COLLECTION].find_one({'row': 'item', 'persona': persona}, {'added': 1},
                                                       sort=[('added', 1)])
    if not first or not first.get('added'):
        return {'days': 0, 'rows': 0, 'deleted': deleted}
    began = datetime.fromisoformat(str(first['added']).replace('Z', '+00:00')).astimezone(zone).date()
    done = set(rows.distinct('day', {'persona': persona}))
    day, days, written = max(oldest, began), 0, 0
    while day < today:
        if day.isoformat() not in done:
            found = day_counts(store, persona, day, zone)
            for row in found:
                rows.replace_one({'_id': row['_id']}, row, upsert=True)
            days, written = days + 1, written + len(found)
        day += timedelta(days=1)
    return {'days': days, 'rows': written, 'deleted': deleted}
