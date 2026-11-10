"""Tiered memory (ADR-062): where each of her items lives, kept up by what is memorable, moved down by the program.

Every section of her persona, voice, ledgers, group notes, running records and the `self` and `core` documents is an
item. The program never rewrites an item's text; beside it, in the collection `memory_tiers` (rows `item`), it keeps
the item's place (随身 carried in every turn where it is readable, 手边 at hand: found by a turn about it or by
`recall`, 收着 put away: found by `recall` only), when it was last memorable and its stay. A 随身 item lapses to 手边
when its stay runs out; each memorable moment (recall returned it, a rewrite that changed it, its `doc:` ref cited, a
second conversation it came up in) starts the stay again and, once per stay, doubles the next. Nothing imitates
forgetting on the stored side (ADR-117 L4): no gist replaces an item's text, no correction or merge supersedes one;
what she held before stays in the revision ledger. A ledger or a group's notes over its count cap lapses its least recently memorable item. Her identity layer
(persona, voice, self, core) has no count cap: a write of hers that takes a place over its token ceiling (carried.py)
lands, her next home turn that can write lists that place's carried sections for her to choose (`identity_over`), and
after that turn the program lets go, in order, until the place fits (`lapse_over`). Nothing at hand moves down by disuse: a
memory at hand (an item that is not a fact) comes up by itself only while its last use or memorable moment is within
its age bound (`within_age`: JOURNAL_AGE_DAYS for a running record's row, the forgetting half-life's step-back for the
rest), and `recall` reaches it whatever its age; facts have no age bound. Every move is one row `move` and one audit line `memory.moved`, saying who made it (`by`: `her` for her let_go
and her own `inject` writes, `program` for the rest), and is told once in each conversation that can read the item
(`things_from_program`). Where a write leaves each section is one rule, `Tiers.placement_after`, which the identity
gate (carried.py) measures before the write lands. A group's notes over their per-turn limit fold by last surfacing
(`fold_order`, kept and recomputed on a write and at settlement); a folded section is at hand for `deliver`. An item
at hand comes up when the turn's message has one of its keys (key_words.py: her tags, and a group note's rare heading
words), or when it is close enough in meaning; each place's common words, which decide what is rare there, are kept
beside the fold order (rows `rarity`, recomputed at settlement and made when missing). A turn whose message is program
text (`PROGRAM_TEXT_KINDS`) still brings items up, but marks nothing (`deliver`'s `counts`). The program never writes
her `inject`: the tier is the record of what is carried. She reads all of it as words from the tables below.
"""
from __future__ import annotations

import re
import time
from datetime import timedelta, timezone

from . import clock
from .evidence import canonical, sha
from .memory_pilot import FLOOR, OWN_SLOTS, SLOTS   # her own items: two of a turn's six slots, above the pilot's floor
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import memories as memory_records
from .records.view import View, fenced, is_text
from .store.words import AddToSet, AnyOf, Exists, HoldsNone, Increase, NoneOf, OnCreate, Range, Set, Unset

TIERS_VERSION = 1
COLLECTION = 'memory_tiers'

CARRIED, AT_HAND, PUT_AWAY = '随身', '手边', '收着'
DOWN = {CARRIED: AT_HAND, AT_HAND: PUT_AWAY}
DEPTH = {CARRIED: 0, AT_HAND: 1, PUT_AWAY: 2}
FROM_INJECT = {'always': CARRIED, 'on_demand': AT_HAND, 'never': PUT_AWAY}
TO_INJECT = {CARRIED: 'always', AT_HAND: 'on_demand', PUT_AWAY: 'never'}
SELF_DOC, CORE_DOC = 'self', 'core'
SELF_DOCS = (SELF_DOC, CORE_DOC)
STORE_WORDS = {'persona': '人设', 'voice': '口吻', 'ledger': '活账', 'group_notes': '群笔记', 'core': 'core',
               'self': '自我', 'journal': '流水'}
# Each item is a fact (what is: no age bound) or a memory (what happened, or her own judgment: follows the cycle). Her answer (2026-10-13): per item, not per store. The store gives the default;
# she may say it, or say where the item came from, when she writes it.
# Stores whose items are facts unless she says; every other store's (self, journal, voice) are memories: her voice is
# something she keeps changing (her answer).
FACTS = ('persona', 'ledger', 'group_notes', 'core')
FACT, MEMORY = '事实', '记忆'
NATURES = (FACT, MEMORY)
FROM_NATURE = {'主人定的': FACT, '查过的': FACT, '别人说的': MEMORY, '我自己的判断': MEMORY}
SOURCES = tuple(FROM_NATURE)
# Her rule (2026-10-13): a fact needs an author who can correct it. Her own judgment becomes a fact only when someone
# else confirms it (met again from another conversation) or when she has checked it (rewritten with 查过的 and a basis).
OWN_JUDGMENT, CHECKED = '我自己的判断', '查过的'
OTHERS_SAID = ('别人说的', '主人定的')
# Considered and dropped (owner's call, 2026-10-13): a correction thread that upholds it. No honest signal for it
# exists without the program judging what was said, which would grade her text.
JUDGMENT_NOT_FACT = ('你自己的判断不能由你自己签成事实，除非你查过了：'
                     '用 replace_section 把它改写成带依据的一条（依据：谁、何时、从哪来），from 写 查过的。')
CAPS = {'ledger': 10, 'group_notes': 10}           # her identity has a token ceiling per place instead (carried.py)
FIRST_STAY_DAYS = {'group_notes': 28, 'core': 56, 'voice': 56}
STAY_DAYS, STAY_CAP_DAYS = 14, 56
# The switch-on day only: each first stay spread per item from its usual length up to twice that (14..28 days; a
# group's notes 28..56), never past the stay cap, so what nothing uses lapses gradually, not all on one day (owner
# 2026-10-13, after the dry run). Later items take the usual first stay.
JOURNAL_AGE_DAYS = 30             # a running record's row comes up by itself while used within this (within_age)
TICK_SECONDS = 600                # a turn runs `tick` at most this often in one process (tick_due)
# What a turn's readers read of each item row (ADR-117 B3): never whole rows. Counts stay counts of rows.
THINGS_FIELDS = ['store', 'place', 'doc', 'visibility']
CARRIED_FIELDS = ['store', 'place', 'doc', 'sid', 'felt', 'memorable_at', 'last_use_at', 'heading']
DELIVER_FIELDS = ['doc', 'sid', 'place', 'store', 'fact', 'added', 'heading', 'memorable_at', 'last_use_at']
# ADR-117 D1: the turns whose message is program text (a heartbeat, a visit, self-development, the night's
# settlement, and a turn a note woke, whose message is notes.WAKE_TEXT; the note itself is in note_from_program).
# Their items still come up, but nothing is counted: no use, no memorable moment, no rehearsal, no program score, no
# came-back count (context.prepare). Her own recall in such a turn counts.
PROGRAM_TEXT_KINDS = ('presence', 'visit', 'self_development', 'settlement', 'note')
AGE_WORDS = ((1, '刚写的'), (7, '这几天'), (14, '前阵子'), (45, '上个月'), (None, '更早'))
COUNT_WORDS = ((0, '没有'), (3, '几条'), (9, '好几条'), (19, '十几条'), (99, '几十条'), (None, '很多条'))
# How much room a store's 随身 has left under its cap, said in every turn instead of its count: the carried items are
# in front of her already; what she could not see was how close the cap is (her ask, 2026-10-19).
ROOM_WORDS = ((0, '满了'), (1, '还能放一条'), (3, '还能放两三条'), (9, '还能放好几条'), (None, '还空着很多'))
REASONS = {'stay': '一阵子没用到', 'overflow': '随身满了', 'cooled': '很久没用', 'let_go': '你放手了',
           'superseded': '被更正替换', 'merged': '合并了', 'gist_skipped': '两晚没写意思', 'rewritten': '你改写了它',
           'ceiling': '这一处随身超了上限'}
# Who moved an item (her ask, ADR-096): her own let_go and her own `inject` writes (reason let_go) are hers; every
# other move, the lift a rewrite brings included, is the program's.
BY = {'let_go': 'her'}
# A group-notes section carried but folded to its heading this turn, when a turn brings it up (deliver).
FOLDED = CARRIED + '（折叠了）'


def moved_by(move):
    """Who made a move: its `by`, or for a row written before moves said it, the same rule from its reason."""
    return move.get('by') or BY.get(move.get('reason'), 'program')
HER_OPS = ('replace_section', 'append_section', 'set_tags')     # her writes (placement_after)
MOVED_SHOWN = 5
HEADINGS_SHOWN = 8
# What a basis looks like (her answer 2026-10-13: an item is a claim with its basis): signing a fact checks for one.
BASIS = ('依据', '来源', '据', '样本', '证据', '查过', '测过', '主人说', '主人定', '因为', '出处')
LOOK_BACK_DAYS = 7
WORLD_LEDGER = 'world'
# ADR-117 L3: a place's identity layer over its ceiling (`Tiers.identity_over`, `lapse_over`). Her line and the lapse's
# are the persona's words (persona_model `memory.over_line`, `memory.lapse_line`). A section listed under the line, in
# the order the program would let them go (its days since last thought of, its 30-day score there, what it frees); a
# felt section, listed after the rest and never let go by the program; what a choice says when the program will let
# nothing go (only a felt section would make it fit; or only document order would decide between the section it would
# take and the next one, her choice of 2026-11-06); a place over even with every section gone, said once; how long a
# turn that showed the choice may hold the lapse (one cut and never resumed does not hold it for ever).
PAIR_OVER = 'pair_over'
OVER_SECTION = '「%s」%d 天没想到，30 天里想到 %d 次｜约 %s token'
FELT_MARK = '（记下了感受：程序不替你放）'
FELT_WAIT = '只放没记下感受的节已经不够让这一处回到上限以内；记下感受的节程序不替你放，等你挑。'
TIE_WAIT = '程序要放的那一节和下一节分不出先后（一样多天没想到，30 天里想到的次数也一样），程序不按文档顺序替你放，等你挑。'
CANNOT_FIT = '这一处就算把你在这里随身带的节都放下，也还超上限（现在 %s／上限 %s）：程序什么都没放。'
WAITS = {'felt_wait': FELT_WAIT, 'tie_wait': TIE_WAIT}
SHOWN_WAIT_SECONDS = 3600
# Her choice when a store is over its cap (her ask, 2026-10-18; no keep act, ADR-062): what is carried, and the default.
OVER_LINE = ('随身满了（%s %d/%d）：随身的有 %s。想换就 let_go 一条；这一回合不挑，下一回合程序照旧放最久没用到的「%s」。')
SEARCHED = '找了：随身、手边、收着'
NOTHING = '随身、手边、收着三处都没找到'
# A tag never carries an item back (no pin, owner 2026-10-13): only a changed rewrite does (ADR-062 §4.2 step 7).
NOT_BACK = 'when_shown 改成 always 不会把它带回随身：你把它改写出变化，它才会回来；现在它在%s。'
# What she is told once per conversation, in her system prompt where the memory rules are (ADR-062 §4.3): the persona
# model's `memory.tiers_told` (a persona package words it; the core default is neutral, persona_model.CORE_DEFAULTS).


def told_text(config):
    from .persona_model import effective
    return effective((config or {}).get('persona_model') or {}, 'memory.tiers_told')
THINGS_NOTE = ('你的东西在哪：活账和群笔记的随身还能放多少条，其余的随身、手边、收着各有几条；moved 是程序挪过的，每件只说一次'
               '（又用到、改写出变化就回来）；identity_room 是各处每回合随身带的（%s 合起来）用了上限的多少：%s；变了才说；'
               'identity_over 是哪一处超了上限：随身的节按程序会放的先后列着，各腾出多少，先由你挑；'
               'came_back 是最近一天里各样东西按词回来过几次，每天说一次；'
               'self_items 是把 current_self 拆成条的提议。')
# What came back in the last day (ADR-097 D5), each kind in words; told once a day in each conversation.
CAME_BACK_KINDS = (('note', '你的笔记回来'), ('cue', '别的群见过的词提醒'), ('elsewhere_hers', 'recall 找到你在别处说过的'),
                   ('elsewhere_theirs', 'recall 找到别人提过的'), ('before', 'recall 找到你以前记过的'))
TIMES_WORDS = ((0, '没有'), (1, '一次'), (3, '两三次'), (9, '好几次'), (None, '很多次'))
CAME_BACK_ITEMS = 3


def _things_note():
    from .carried import SCOPE_WORDS, room_ranges
    return THINGS_NOTE % (SCOPE_WORDS, room_ranges())


THINGS_NOTE = _things_note()
SELF_OFFER = ('current_self 现在是一整段。想好了就把它拆成一条一条，用 write_document 写进 doc=self（append_section）：'
              '一条是一个说法连同它的依据（样本、来源、证据），不按行拆；原来那段留作历史，程序不替你拆。')



def _iso(moment):
    return moment.isoformat()


def _at(value):
    """A stored time (clock.moment); None when there is none, which each caller words (never used, not yet shown)."""
    return clock.moment(value) if value else None


def _without(found, keys):
    """A pair's carried sections by document ({slug: sections}) without these (slug, sid)."""
    return {slug: [s for s in sections if (slug, s['sid']) not in keys] for slug, sections in found.items()}


def unused(row, moment):
    """Whole days since an item was last memorable or used (0 when it never was, or no row)."""
    last = max(filter(None, (_at((row or {}).get('memorable_at')), _at((row or {}).get('last_use_at')))), default=moment)
    return max(0, int((moment - last).total_seconds() // 86400))


def words(table, value):
    for limit, word in table:
        if limit is None or value <= limit:
            return word
    return table[-1][1]


def age_word(added, moment):
    days = (moment - (_at(added) or moment)).total_seconds() / 86400
    for limit, word in AGE_WORDS:
        if limit is None or days < limit:
            return word
    return AGE_WORDS[-1][1]


def store_of(slug, kind):
    """Which store a document is, or None when it is not tiered (her working documents)."""
    if slug in ('persona', 'voice'):
        return slug
    if slug == SELF_DOC:
        return 'self'
    if slug == CORE_DOC:
        return 'core'
    if str(slug).startswith('group:'):
        return 'group_notes'
    return {'ledger': 'ledger', 'journal': 'journal'}.get(kind)


def item_id(persona, doc, sid):
    return 'tier:' + sha(canonical([persona, doc, sid]))[:32]


def ref(doc, sid):
    return 'doc:%s#%s' % (doc, sid)


# ── the owner of `memory_tiers` ──
# Its rows (`row`: item, move, over, pair_over, fold, rarity, told, offer, room_told), read and written only through `Tiers` and
# these. A persona given None finds nothing (ADR-104 section 4).
def items(store, persona, /, *, by=None, **where):
    """View: a persona's items (rows `item`) whose fields equal these (or meet these words), ordered by `by` (none: the
    database's order)."""
    return View(store, COLLECTION, fenced({'row': 'item', **where}, {'persona': (persona, is_text)}),
                ((by, 1),) if by else ())


def personas(store):
    """The personas with tier items, ascending."""
    return store.collection(COLLECTION).group({'row': 'item'}, ['persona'], None)


def moves(store, persona):
    """View: a persona's moves (rows `move`)."""
    return View(store, COLLECTION, fenced({'row': 'move'}, {'persona': (persona, is_text)}))


def room_told(store, key):
    """The identity room last told in a conversation (carried.room_block's row), or None."""
    return store.collection(COLLECTION).get(key) if is_text(key) else None


def tell_room(store, key, persona, scene_id, words, version, at):
    """The identity room told in a conversation, kept to say it again only when its words change."""
    store.collection(COLLECTION).update({'_id': key}, Set({'row': 'room_told', 'persona': persona,
                                                           'scene_id': scene_id, 'words': words, 'version': version,
                                                           'at': at}), create=True)


# ADR-117 L4: what the night list and supersession left in the rows, removed at each start (0 once it has run): the
# night list's offers (the weekly reading's `week` offers stay) and the mark a correction or a merge put on the item it
# put away (`superseded_at`, read by nothing now), and the shortened-from mark of an item she rewrote after its gist
# (the gist step never set `rewritten_at`, so a later one is hers). The item rows, their moves and her documents stay.
RETIRED_OFFERS = ('gist', 'merge', 'repeated')


def retire_night_list(store):
    """{offers_deleted, superseded_unset, detail_unset}: the counts of rows the step changed (all 0 when nothing was
    left)."""
    rows = store.collection(COLLECTION)
    offers = rows.delete({'row': 'offer', 'what': AnyOf(list(RETIRED_OFFERS))}, many=True)
    unset = 0
    for move in rows.find({'row': 'move', 'reason': AnyOf(['superseded', 'merged'])}, fields=['item']):
        item = rows.get(move['item']) if is_text(move.get('item')) else None
        if item and 'superseded_at' in item:
            rows.update({'_id': item['_id']}, Unset('superseded_at'))
            unset += 1
    detail = 0
    for item in rows.find({'row': 'item', 'detail_of': Exists(True)}, fields=['gist', 'rewritten_at']):
        if str(item.get('rewritten_at') or '') > str(((item.get('gist') or {}).get('done')) or '~'):
            rows.update({'_id': item['_id']}, [Unset('detail_of'), Unset('gist')])
            detail += 1
    return {'offers_deleted': offers, 'superseded_unset': unset, 'detail_unset': detail}


class Tiers:
    def __init__(self, store, persona):
        self.store, self.persona = store, persona
        self.rows = store.collection(COLLECTION)

    # ── items ──────────────────────────────────────────────────────
    def items(self, *, fields=None, **query):
        """Her items' rows meeting `query`; `fields`: only these of each (and `_id`), as a turn's readers read them."""
        return items(self.store, self.persona, **query).rows(fields=fields)

    def item(self, doc, sid):
        return self.rows.get(item_id(self.persona, doc, sid))

    def _first(self, where, *, by=None, fields=None):
        """The first row meeting `where` (newest first by `by`), or None."""
        return next(self.rows.find(where, ((by, -1),) if by else (), 0, 1, fields), None)

    def _make(self, row):
        """Write a row once: a row of this id already there is left as it is. Returns the stored row."""
        self.rows.update({'_id': row['_id']}, OnCreate({k: v for k, v in row.items() if k != '_id'}), create=True)
        return self.rows.get(row['_id'])

    def last_move(self, item):
        """The latest move of an item, or None."""
        return self._first({'row': 'move', 'item': item}, by='at')

    def _new(self, doc, sid, kind, section, place, moment, *, scene_id=None, felt=False, dated=None):
        """A new item's row, written and last memorable at `moment`, or at `dated` (first written, last changed: an
        imported entry's own times)."""
        added, last = dated if dated and all(dated) else (_iso(moment), _iso(moment))
        row = {'_id': item_id(self.persona, doc, sid), 'row': 'item', 'tiers_version': TIERS_VERSION,
               'persona': self.persona, 'doc': doc, 'sid': sid, 'store': kind, 'fact': kind in FACTS,
               'nature': FACT if kind in FACTS else MEMORY,
               'heading': section.get('heading') or sid, 'visibility': section.get('visibility') or 'public',
               'place': place, 'added': added, 'memorable_at': last, 'stay_from': last,
               'stay_days': FIRST_STAY_DAYS.get(kind, STAY_DAYS), 'doubled': False, 'stays': 0, 'uses': 0,
               'body_sha256': section.get('body_sha256') or sha((section.get('body') or '').encode()),
               'chars': len(section.get('body') or ''), 'surfaced_in': [], 'recalled_in': [],
               **({'scene_id': scene_id} if scene_id else {}), **({'felt': True} if felt else {})}
        return self._make(row)

    def sync(self, moment=None):
        """Every item has a row. One the program has not seen takes its place from its `inject` (always 随身,
        on_demand 手边, never 收着) with a fresh stay: nothing lapses on the day the switch goes on. On that day (no
        rows yet), each first stay is spread per item from its usual length to twice that, within the cap. It reads
        every document, so it runs once per process start (memory_pilot.attach), for what was written while the
        worker was down; every write makes its own rows (`written`)."""
        from .documents import DocumentStore
        moment = moment or clock.now()
        docs = DocumentStore(self.store, self.persona)
        known = {(row['doc'], row['sid']) for row in items(self.store, self.persona).each(fields=['doc', 'sid'])}
        switch_on = not known
        for slug in docs.slugs():
            content = docs.read(slug)[1] or {}
            kind = store_of(slug, content.get('kind'))
            if not kind:
                continue
            for section in content.get('sections') or []:
                if (slug, section['sid']) in known:
                    continue
                place = FROM_INJECT.get(section.get('inject'), AT_HAND)
                row = self._new(slug, section['sid'], kind, section, AT_HAND if kind == 'journal' and place == CARRIED
                                else place, moment)
                usual = int(row.get('stay_days') or STAY_DAYS)
                if switch_on and usual < STAY_CAP_DAYS:
                    spread = int(sha(row['_id'].encode())[:8], 16) % (min(usual, STAY_CAP_DAYS - usual) + 1)
                    self.rows.update({'_id': row['_id']}, Set({'stay_days': usual + spread}))

    def placed(self, slug, content, override=None):
        """A document as the turn reads it: each section's `inject` follows its place (a copy; the text untouched).
        `override` ({sid: place}) is where a write will leave the sections it moves (placement_after)."""
        if not content or not content.get('sections'):
            return content
        places = {row['sid']: row['place'] for row in items(self.store, self.persona, doc=slug).each(
            fields=['sid', 'place'])}
        places.update(override or {})
        if not places:
            return content
        return {**content, 'sections': [{**section, 'inject': TO_INJECT[places[section['sid']]]}
                                        if section['sid'] in places else section
                                        for section in content['sections']]}

    # ── moves ──────────────────────────────────────────────────────
    def move(self, row, to, reason, moment=None, *, scene_id=None, said=None):
        """One item to another place: the row, a `move` row told once per conversation, one audit line. `said`: what
        the move row keeps beside it for telling (`lapse_line`, the line `told` gives; the numbers it was said with)."""
        moment = moment or clock.now()
        if row['place'] == to:
            return None
        fields = {'place': to, 'moved_at': _iso(moment)}
        if to == CARRIED:                         # a new stay from now
            fields.update(stay_from=_iso(moment), memorable_at=_iso(moment), doubled=False)
        if reason == 'stay':
            fields['stays'] = int(row.get('stays') or 0) + 1
        self.rows.update({'_id': row['_id']}, Set(fields))
        by = moved_by({'reason': reason})
        move = {'_id': 'move:' + sha(canonical([row['_id'], row['place'], to, _iso(moment)]))[:32], 'row': 'move',
                'persona': self.persona, 'item': row['_id'], 'doc': row['doc'], 'sid': row['sid'],
                'heading': row.get('heading'), 'store': row['store'], 'visibility': row.get('visibility'),
                'from': row['place'], 'to': to, 'reason': reason, 'by': by, 'at': _iso(moment), 'told_in': [],
                **(said or {})}
        self._make(move)
        self.store.audit('memory:' + self.persona, 'memory.moved', {'item': row['_id'], 'doc': row['doc'],
                         'sid': row['sid'], 'from': row['place'], 'to': to, 'reason': reason, 'by': by,
                         **({'scene_id': scene_id} if scene_id else {})}, 'global-safe')
        return move

    def tick(self, moment=None):
        """Lapses whose stay ran out. Nothing at hand moves by disuse (its age bound is `within_age`). Returns the
        moves."""
        moment = moment or clock.now()
        moves = []
        for row in self.items(place=CARRIED):
            start = _at(row.get('memorable_at')) or moment
            if moment - start > timedelta(days=float(row.get('stay_days') or STAY_DAYS)):
                moves.append(self.move(row, AT_HAND, 'stay', moment))
        return [move for move in moves if move]

    def memorable(self, row, why, moment=None, *, scene_id=None):
        """A memorable moment: the stay starts again from now and, once per stay, the next one doubles. It never moves
        the item: only a changed rewrite brings one back up (ADR-062 §11)."""
        moment = moment or clock.now()
        fields = {'memorable_at': _iso(moment), 'last_use_at': _iso(moment), 'last_moment': why}
        if not row.get('doubled'):
            fields.update(stay_days=min(STAY_CAP_DAYS, float(row.get('stay_days') or STAY_DAYS) * 2), doubled=True)
        self.rows.update({'_id': row['_id']}, [Set(fields), Increase('uses')])

    def _carried(self, doc):
        """A capped document's carried rows (a ledger's, a group's notes'), only the fields its readers use
        (CARRIED_FIELDS); a move reads its row whole."""
        return self.items(doc=doc, place=CARRIED, fields=CARRIED_FIELDS)

    def _lapse_order(self, rows):
        """The order carried items lapse in over a cap: least recently memorable first, felt ones last. Items one
        moment stamped together (a sync) go by their place in the document, the oldest section first."""
        from .documents import DocumentStore
        docs, place = DocumentStore(self.store, self.persona), {}
        for slug in sorted({row['doc'] for row in rows}):
            for n, section in enumerate((docs.read(slug)[1] or {}).get('sections') or []):
                place[slug, section['sid']] = n
        return sorted(rows, key=lambda row: (bool(row.get('felt')), row.get('memorable_at') or '', row['doc'],
                                             place.get((row['doc'], row['sid']), len(place))))

    def _overflow(self, doc, kind, keep, moment):
        """A ledger or a group's notes over its count cap: her choice first (her ask, 2026-10-18). The first time it is
        over, nothing moves; her next turn that reads it lists what is carried, with days unused, and she may let one
        go. A turn later, if it is still over, it lapses its least recently memorable items (felt ones last), as before.
        A store without a cap (her identity: a token ceiling per place, `identity_over`) does nothing here. The moves
        made."""
        cap = CAPS.get(kind)
        if not cap:
            return []
        carried = self._carried(doc)
        key = 'over:%s:%s' % (self.persona, doc)
        if len(carried) <= cap:
            self.rows.delete({'_id': key})
            return []
        pending = self.rows.get(key)
        order = self._lapse_order([row for row in carried if row['_id'] not in (keep, (pending or {}).get('keep'))])
        if not pending or not pending.get('shown_in'):
            # Waiting for her: one item over at most; more than that lapses by the rule now (her choice is the last).
            self.rows.update({'_id': key}, [OnCreate({'row': 'over', 'persona': self.persona, 'doc': doc,
                                                      'store': kind, 'since': _iso(moment), 'shown_in': []}),
                                            Set({'keep': keep})], create=True)
            return [move for move in (self.move(self.rows.get(row['_id']), AT_HAND, 'overflow', moment)
                                      for row in order[:max(0, len(carried) - cap - 1)]) if move]
        self.rows.delete({'_id': key})
        return [move for move in (self.move(self.rows.get(row['_id']), AT_HAND, 'overflow', moment)
                                  for row in order[:len(carried) - cap]) if move]

    def overflows(self, here, scene_id, moment):
        """The stores over their cap that this turn reads: shown once each, for her to choose; one already shown
        in an earlier turn lapses by the program's rule first (so a cap is over for one turn at most)."""
        lines = []
        for pending in list(self.rows.find({'row': 'over', 'persona': self.persona})):
            if not here({'store': pending['store'], 'doc': pending['doc'], 'visibility': None}):
                continue
            cap = CAPS.get(pending['store'])
            if not cap:
                self.rows.delete({'_id': pending['_id']})      # a store that has no cap any more
                continue
            if pending.get('shown_in'):
                self._overflow(pending['doc'], pending['store'], pending.get('keep'), moment)
                continue
            carried = self._carried(pending['doc'])
            if len(carried) <= cap:
                self.rows.delete({'_id': pending['_id']})
                continue
            listed = sorted(carried, key=lambda row: (-unused(row, moment), row.get('heading') or ''))
            oldest = self._lapse_order([row for row in carried if row['_id'] != pending.get('keep')])[0]
            lines.append(OVER_LINE % (STORE_WORDS.get(pending['store'], pending['store']), len(carried), cap,
                                      '；'.join('「%s」%d 天没用到' % (row.get('heading') or row['sid'], unused(row, moment))
                                               for row in listed),
                                      oldest.get('heading') or oldest['sid']))
            self.rows.update({'_id': pending['_id']}, AddToSet('shown_in', scene_id))
        return lines

    # ── her identity over a place's ceiling (ADR-117 L3) ────────────
    # One row `pair_over` per (place, class) pair her own write took over its ceiling (over_pairs), until the pair is
    # back to its `target`: `shown_in` the turns (episode ids) that showed her the choice, `shown_at` the first,
    # `shown_plan` and `shown_picked` what the latest showing said (lapse_plan's verdict and the sections it would let
    # go). Each step is one audit line `memory.identity_over` (its `phase`).
    def _over_key(self, pair):
        return 'pair_over:%s:%s|%s' % (self.persona, pair[0], pair[1])

    def _over_said(self, pair, phase, **payload):
        self.store.audit('memory:' + self.persona, 'memory.identity_over',
                         {'pair': '%s/%s' % tuple(pair), 'phase': phase, **payload}, 'global-safe')

    def over_pairs(self, plan, moment=None, *, scene_id=None):
        """Her own write took these pairs over their ceiling, or grew them while over it ({pair: {'over', 'before',
        'after'}}, carried.over_plan): each waits for her choice in her next home turn that can write. The row keeps
        its `target`, what the program asks her to free back down to: the larger of the ceiling and the pair's size
        just before her write, so a pair already over for another reason (the owner's ceiling, the program's own
        text) is only asked back to where her write found it. A pair already waiting keeps its earliest target.
        Only her write paths call this (write_document, adopt_seed, promote_memory), never an import or a start."""
        from . import carried
        ceiling = carried.limit(self.store, self.persona)
        for pair, measured in plan.items():
            key = self._over_key(pair)
            if not self.rows.get(key, ['_id']):
                target = max(ceiling or 0, measured['before'])
                self.rows.update({'_id': key}, OnCreate({'row': PAIR_OVER, 'persona': self.persona, 'pair': list(pair),
                                                         'since': _iso(moment or clock.now()), 'target': target,
                                                         'shown_in': []}), create=True)
            self._over_said(pair, 'over', over=measured['over'], before=measured['before'], after=measured['after'],
                            **({'scene_id': scene_id} if scene_id else {}))

    def _over_rows(self):
        from .carried import ordered
        rows = {tuple(row['pair']): row for row in self.rows.find({'row': PAIR_OVER, 'persona': self.persona})}
        return [rows[pair] for pair in ordered(rows)]

    def _over_closed(self, row, phase, **payload):
        self.rows.delete({'_id': row['_id']})
        self._over_said(row['pair'], phase, **payload)

    def _identity(self):
        """What the over pairs are measured with: (ceiling, docs, common text, laid out, carried rows by (doc, sid)),
        read once."""
        from . import carried
        from .render import common_text
        docs = carried.contents(self.store, self.persona)
        common = common_text(self.store.config)
        laid = carried.laid_out(self.store, self.persona, docs=docs, common=common)
        rows = {(row['doc'], row['sid']): row for row in self.items(doc=AnyOf(list(carried.IDENTITY)), place=CARRIED,
                                                                         fields=CARRIED_FIELDS)}
        return carried.limit(self.store, self.persona), docs, common, laid, rows

    def _target(self, row, ceiling):
        """What a row asks her to free back down to: its kept target (over_pairs), never below the ceiling as it is now
        (a ceiling the owner raised since her write asks for less); None when nothing bounds the pair any more, which
        then fits. A ceiling lowered since her write keeps the kept target."""
        if not ceiling:
            return None
        return max(row.get('target') or ceiling, ceiling)

    def lapse_plan(self, pair, found, measured, moment=None, target=None):
        """What letting go would do for one pair whose carried sections are `found` ({slug: sections}), with `measured`
        from _identity, read only, until the pair is back to `target` (its row's, else the ceiling). The order is one
        measure for what she is shown and what the program does: the sections the program may let go (carried, with
        their tier row, not felt), the most days since last thought of first (the later of the last memorable moment
        and the last use, `unused`), then the lowest 30-day program score in this pair (carried.program_scores), then
        document order; the felt sections after them, never let go by the program. Returns {'verdict', 'order' [(doc,
        sid, days, score)], 'felt' (the same), 'picked' [(doc, sid)]}: `fits` (nothing to do), `lapse` (let `picked`
        go), `felt_wait` (only with a felt section would it fit), `tie_wait` (the last section it would take and the
        first it would keep differ in document order only: her choice, 2026-11-06), `cannot_fit` (not even with every
        section gone). The two waits let nothing go."""
        from . import carried
        moment = moment or clock.now()
        ceiling, docs, common, _, carried_rows = measured
        bound = target if target is not None else ceiling
        if not bound or carried.tokens(common, found, docs) <= bound:
            return {'verdict': 'fits', 'order': [], 'felt': [], 'picked': []}
        position = {(slug, section['sid']): (n, i) for n, slug in enumerate(carried.IDENTITY)
                    for i, section in enumerate((docs.get(slug) or {}).get('sections') or [])}
        keys = [(slug, section['sid']) for slug in carried.IDENTITY for section in found.get(slug) or []
                if (slug, section['sid']) in carried_rows]       # every section has its row (ADR-117 B3)
        scores = carried.program_scores(self.store, self.persona, [ref(*key) for key in keys], pair) if keys else {}
        measure = {key: (unused(carried_rows[key], moment), scores.get(ref(*key), 0)) for key in keys}
        ranked = sorted(keys, key=lambda key: (-measure[key][0], measure[key][1], position.get(key, (len(position), 0))))
        felt = [key for key in ranked if carried_rows[key].get('felt')]
        order = [key for key in ranked if not carried_rows[key].get('felt')]
        plan = {'order': [(*key, *measure[key]) for key in order], 'felt': [(*key, *measure[key]) for key in felt],
                'picked': []}

        def fits(keys_gone):
            return carried.tokens(common, _without(found, set(keys_gone)), docs) <= bound
        for n in range(1, len(order) + 1):
            if fits(order[:n]):
                picked = order[:n]
                kept = order[n] if n < len(order) else None
                tied = kept is not None and measure[picked[-1]] == measure[kept]
                return {**plan, 'verdict': 'tie_wait' if tied else 'lapse', 'picked': picked}
        for n in range(1, len(felt) + 1):
            if fits(order + felt[:n]):
                return {**plan, 'verdict': 'felt_wait', 'picked': order + felt[:n]}
        return {**plan, 'verdict': 'cannot_fit', 'picked': order + felt}

    def identity_over(self, turn, moment=None):
        """For her home turn that can write (`turn`: its episode id): one choice per pair her write took over, in her
        order of places, from the plan as it is now (lapse_plan, back to the row's target): her line (persona_model
        `memory.over_line`; `{over}` is how far her writes put it over, `{cap}` where it goes back to), the pair's
        sections in the order the program would let them go, each with its days since last thought of, its 30-day
        score there and the tokens letting it go frees there, the felt ones after them marked as never let go by the
        program, and `waiting` when the program will let nothing go. A pair back at its target is closed; a pair that
        cannot get back even with every section gone is said once and closed. Marks the turn as having shown each
        choice, and what it said (`shown_plan`, `shown_picked`)."""
        from . import carried
        from .persona_model import words as persona_words
        rows = self._over_rows()
        if not rows:
            return []
        moment = moment or clock.now()
        measured = self._identity()
        ceiling, docs, common, laid, _ = measured
        out = []
        for row in rows:
            pair = tuple(row['pair'])
            target = self._target(row, ceiling)
            found, size = laid.get(pair, ({}, 0))
            plan = self.lapse_plan(pair, found, measured, moment, target)
            where = carried.PAIR_WORDS.get(pair, '%s/%s' % pair)
            if plan['verdict'] == 'fits':
                self._over_closed(row, 'fits', tokens=size, target=target)
                continue
            if plan['verdict'] == 'cannot_fit':
                out.append({'where': where, 'line': CANNOT_FIT % (carried.number(size), carried.number(target))})
                self._over_closed(row, 'cannot_fit', tokens=size, target=target, episode=turn)
                continue
            heading = {(slug, section['sid']): section.get('heading') or section['sid']
                       for slug in carried.IDENTITY for section in found.get(slug) or []}

            def entry(doc, sid, days, score, mark=''):
                freed = size - carried.tokens(common, _without(found, {(doc, sid)}), docs)
                return OVER_SECTION % (heading[doc, sid], days, score, carried.number(freed)) + mark
            choice = {'where': where,
                      'line': persona_words(self.store.config, 'memory.over_line', over=carried.number(size - target),
                                            now=carried.number(size), cap=carried.number(target)),
                      'sections': [entry(*item) for item in plan['order']]
                                  + [entry(*item, mark=FELT_MARK) for item in plan['felt']]}
            if plan['verdict'] in WAITS:
                choice['waiting'] = WAITS[plan['verdict']]
            out.append(choice)
            picked = [ref(*key) for key in plan['picked']]
            first = turn and turn not in (row.get('shown_in') or [])
            change = [Set({'shown_plan': plan['verdict'], 'shown_picked': picked})]
            if first:
                change.append(AddToSet('shown_in', turn))
                if not row.get('shown_at'):
                    change.append(Set({'shown_at': _iso(moment)}))
            if first or row.get('shown_plan') != plan['verdict'] or row.get('shown_picked') != picked:
                self.rows.update({'_id': row['_id']}, change)
                self._over_said(pair, 'shown', episode=turn, plan=plan['verdict'], over=size - target,
                                sections=len(plan['order']) + len(plan['felt']), picked=len(picked))
        return out

    def _shown_ended(self, row, moment):
        """Whether every turn that showed her the choice has ended (an episode no longer running), or the first showed
        it more than SHOWN_WAIT_SECONDS ago (a turn cut and never resumed does not hold the place over)."""
        from .coordinator import RESUMABLE
        shown = row.get('shown_in') or []
        if not shown:
            return False
        first = _at(row.get('shown_at'))
        if first and (moment - first).total_seconds() > SHOWN_WAIT_SECONDS:
            return True
        found = episode_records.many(self.store, shown).rows(fields=['state'])
        # A turn whose episode is not written yet (its prepare runs first) is still running.
        return len(found) == len(set(shown)) and not any(episode.get('state') in RESUMABLE for episode in found)

    def lapse_over(self, moment=None, rows=None):
        """After every home turn that showed her the choice has ended: each pair still over its target lets `picked`
        go one place down, from the plan as it is now (lapse_plan), but only when the plan she was last shown let the
        same sections go (`shown_plan` lapse, `shown_picked`). Otherwise nothing moves and her next home turn shows the
        plan as it is (a wait, a change since she was shown it, or a place that cannot get back, said once there). A
        section carried in several pairs frees them all. Each move is told with her line (persona_model
        `memory.lapse_line`; `{over}` how far her writes put it over). The moves."""
        from . import carried
        from .persona_model import words as persona_words
        moment = moment or clock.now()
        rows = [row for row in (self._over_rows() if rows is None else rows) if self._shown_ended(row, moment)]
        if not rows:
            return []
        measured = self._identity()
        ceiling, docs, common, laid, _ = measured
        gone, moves = set(), []
        for row in rows:
            pair = tuple(row['pair'])
            target = self._target(row, ceiling)
            found = _without(laid.get(pair, ({}, 0))[0], gone)
            size = carried.tokens(common, found, docs)
            plan = self.lapse_plan(pair, found, measured, moment, target)
            if plan['verdict'] == 'fits':
                self._over_closed(row, 'fits', tokens=size, target=target)
                continue
            shown = (row.get('shown_plan'), row.get('shown_picked'))
            if plan['verdict'] != 'lapse' or shown != ('lapse', [ref(*key) for key in plan['picked']]):
                self.rows.update({'_id': row['_id']}, [Set({'shown_in': []}), Unset('shown_at')])
                self._over_said(pair, plan['verdict'] if plan['verdict'] != 'lapse' else 'changed',
                                over=size - target, shown=shown[0])
                continue
            measure = {(doc, sid): (days, score) for doc, sid, days, score in plan['order']}
            for key in plan['picked']:
                item = self.rows.get(item_id(self.persona, *key))
                if not item or item['place'] != CARRIED:
                    continue
                days, score = measure[key]
                line = persona_words(self.store.config, 'memory.lapse_line', 节名=item.get('heading') or key[1],
                                     over=carried.number(size - target), days=days, score=score)
                said = {'lapse_line': '%s：%s' % (carried.PAIR_WORDS.get(pair, '%s/%s' % pair), line),
                        'pair': list(pair), 'over': size - target, 'days': days, 'score': score}
                moves.append(self.move(item, AT_HAND, 'ceiling', moment, said=said))
            gone |= set(plan['picked'])
            self._over_closed(row, 'lapsed', sections=len(plan['picked']), over=size - target)
        return [move for move in moves if move]

    # ── her writes ─────────────────────────────────────────────────
    def placement_after(self, slug, intent, before, after):
        """Where a write leaves each section it moves, {sid: [(place, reason), ...]} in order, the last one the place it
        ends in: the one rule for the write (written) and for the gate that measures it first (carried.gate). Her
        write: a new section starts carried (a running record's at hand) unless she wrote it tucked away; a rewrite
        that changed an item brings it back to carried; a tag that tucks a section away is her let_go, and a tag never
        lifts one. Anything else (a seed adopted, an
        import): a section new to the program takes its place from its `inject`, as sync would."""
        kind = store_of(slug, (after or {}).get('kind'))
        if not kind:
            return {}
        old = {s['sid']: s for s in (before or {}).get('sections') or []}
        new = {s['sid']: s for s in (after or {}).get('sections') or []}
        op, plan = intent.get('op'), {}
        start = AT_HAND if kind == 'journal' else CARRIED
        told = FROM_INJECT.get(intent.get('inject'))
        for sid in [sid for sid in new if sid not in old]:
            if op in HER_OPS:
                plan[sid] = [(told if told and DEPTH[told] > DEPTH[start] else start, 'new')]
            elif not self.item(slug, sid):
                place = FROM_INJECT.get(new[sid].get('inject'), AT_HAND)
                plan[sid] = [(AT_HAND if kind == 'journal' and place == CARRIED else place, 'new')]
        sid = intent.get('sid')
        row = self.item(slug, sid) if sid in old and sid in new else None
        if (op == 'replace_section' and row and start == CARRIED and row['place'] != CARRIED
                and old[sid].get('body_sha256') != new[sid].get('body_sha256')):
            plan[sid] = [(CARRIED, 'rewritten')]
        if told and row and op in ('set_tags', 'replace_section'):
            now = plan[sid][-1][0] if sid in plan else row['place']
            if DEPTH[told] > DEPTH[now]:
                plan.setdefault(sid, []).append((told, 'let_go'))
        return plan

    def written(self, slug, intent, before, after, *, scene_id=None, felt=False, moment=None, before_revision=None,
                over=None, dated=None):
        """After a document write (hers; or a seed adopted, an import: `intent` of another op), the moves
        placement_after gives, made: every new section gets its row (her new item starts carried, a running record's
        at hand; another write's takes its place from its `inject`, as sync would, and takes no store over its cap), a
        rewrite that changed an item starts its stay again from carried. A group's notes refold. `over`: what the gate measured of her own write (gate.planned): each pair it took over
        its ceiling waits for her choice (over_pairs); only her write paths pass it. `dated` ({sid: (first written,
        last changed)}): the times an import's new rows keep, so an old entry does not read as just written. Returns
        the moves a reader should be told of (an overflow names what it lapsed)."""
        moves = self._written(slug, intent, before, after, scene_id=scene_id, felt=felt, moment=moment,
                              before_revision=before_revision, dated=dated)
        if over:
            self.over_pairs(over, moment, scene_id=scene_id)
        return moves

    def _written(self, slug, intent, before, after, *, scene_id=None, felt=False, moment=None, before_revision=None,
                 dated=None):
        moment = moment or clock.now()
        kind = store_of(slug, (after or {}).get('kind'))
        if not kind:
            return []
        old = {s['sid']: s for s in (before or {}).get('sections') or []}
        new = {s['sid']: s for s in (after or {}).get('sections') or []}
        op, moves = intent.get('op'), []
        start = AT_HAND if kind == 'journal' else CARRIED
        plan = self.placement_after(slug, intent, before, after)
        for sid in [sid for sid in new if sid not in old]:
            # Encoding: what she just wrote is fresh in mind, unless she wrote it tucked away herself.
            row = self.item(slug, sid) or self._new(slug, sid, kind, new[sid], start, moment,
                                                    dated=(dated or {}).get(sid))
            self.rows.update({'_id': row['_id']}, Set({
                'place': (plan.get(sid) or [(row['place'], None)])[-1][0], 'heading': new[sid].get('heading') or sid,
                'visibility': new[sid].get('visibility'),
                **({'scene_id': scene_id} if scene_id else {}), **({'felt': True} if felt else {})}))
            # Only her write takes a store over its cap here; another write's rows are made as sync made them.
            if op in HER_OPS and self.item(slug, sid)['place'] == CARRIED:
                moves += self._overflow(slug, kind, row['_id'], moment)
        declared = declared_nature(intent)
        if declared:
            # What she says an item is, or where it came from, when she writes or tags it. The line it rests on goes
            # with it, and exactly while it is someone's word (ADR-108 D2): another source removes it.
            words = [Set({**declared, **anchor_field(declared, intent)})]
            if declared.get('from') and declared['from'] not in OTHERS_SAID:
                words.append(Unset('line'))
            for sid in ([sid for sid in new if sid not in old] if op == 'append_section'
                        else [intent.get('sid')] if intent.get('sid') in new else []):
                self.rows.update({'_id': item_id(self.persona, slug, sid)}, words)
        sid = intent.get('sid')
        if op == 'replace_section' and sid in old and sid in new:
            row = self.item(slug, sid)
            changed = old[sid].get('body_sha256') != new[sid].get('body_sha256')
            if row:
                self.rows.update({'_id': row['_id']}, Set({
                    'heading': new[sid].get('heading') or sid, 'visibility': new[sid].get('visibility'),
                    'body_sha256': new[sid].get('body_sha256'), 'chars': len(new[sid].get('body') or '')}))
            if row and changed:
                self.memorable(row, 'rewritten', moment, scene_id=scene_id)
                # A shortened item rewritten anew no longer stands for the full text it was shortened from: that text
                # stays in the revision ledger, and read_sections stops showing it under the new one (ADR-117 §20).
                self.rows.update({'_id': row['_id']}, [Set({'rewritten_at': _iso(moment)}),
                                                       *([Unset('detail_of'), Unset('gist')]
                                                         if row.get('detail_of') or row.get('gist') else [])])
        if op in ('replace_section', 'set_tags') and sid in old and sid in new:
            for place, reason in plan.get(sid) or []:
                # The lift a changed rewrite brings, then the let_go a tag that tucks it away is.
                moves.append(self.move(self.item(slug, sid), place, reason, moment, scene_id=scene_id))
                if reason == 'rewritten':
                    moves += self._overflow(slug, kind, item_id(self.persona, slug, sid), moment)
        self._refold(slug, kind, after)
        return [move for move in moves if move]

    # ── a group's notes over their limit fold (ADR-096) ─────────────
    def fold_order(self, slug, content):
        """The order a group's notes fold in over their per-turn limit: the section that surfaced longest ago first.
        Surfacing is a turn bringing it up, her recall, her rewrite, and her writing it; ties keep the document's
        order (so among sections never surfaced since they were written, the oldest first)."""
        rows = {row['sid']: row for row in self.items(doc=slug)}

        def last(section):
            row = rows.get(section['sid']) or {}
            return max(filter(None, (row.get('last_use_at'), row.get('recalled_at'), row.get('rewritten_at'),
                                     row.get('added'))), default='')
        listed = list(enumerate((content or {}).get('sections') or []))
        return [section['sid'] for _, section in sorted(listed, key=lambda pair: (last(pair[1]), pair[0]))]

    def _refold(self, slug, kind, content):
        if kind == 'group_notes':
            self.refold(slug, content)

    def refold(self, slug, content, moment=None):
        """Recompute and keep a group's fold order (on her write and at settlement, not every turn, so the block is
        not re-sent for it)."""
        order = self.fold_order(slug, content)
        self.rows.update({'_id': 'fold:%s:%s' % (self.persona, slug)}, Set({
            'row': 'fold', 'persona': self.persona, 'doc': slug, 'order': order, 'at': _iso(moment or clock.now())}),
            create=True)
        return order

    def folding(self, slug, content):
        """The kept fold order of a group's notes, made once when there is none."""
        row = self.rows.get('fold:%s:%s' % (self.persona, slug), ['order'])
        return row['order'] if row else self.refold(slug, content)

    # ── a place's common words, for her items' keys (ADR-097) ───────
    def place_lines(self, scene_id, moment=None):
        """The place's recent lines that decide what is rare there: its newest inbound lines of the last
        crossing.number('window_days') days, at most key_words.WINDOW_LINES."""
        from . import crossing, key_words
        since = _iso((moment or clock.now()) - timedelta(days=crossing.number('window_days')))
        rows = message_records.inbound(self.store, scene_id, since=since).each(
            newest_first=True, limit=key_words.WINDOW_LINES, fields=['text'])
        return [row['text'] for row in rows if isinstance(row.get('text'), str)]

    def rerate(self, scene_id, moment=None):
        """Count a place's common words, and the cross words it says itself, again and keep them. Returns the row."""
        from . import channel_kinds, crossing, key_words
        crossing.vocabulary(self.store, ensure=True)     # the place's words are cut as the word index cuts them
        lines = self.place_lines(scene_id, moment)
        platform = channel_kinds.of(scene_id)
        row = {'row': 'rarity', 'persona': self.persona, 'scene_id': scene_id, 'lines': len(lines),
               'limit': key_words.limit(len(lines)), 'common': key_words.common(lines),
               'said': key_words.said(lines, platform.INBOUND_MENTION if platform else None, crossing.number('said_here')),
               'openings': key_words.openings(lines), 'at': _iso(moment or clock.now())}
        self.rows.update({'_id': 'rarity:%s:%s' % (self.persona, scene_id)}, Set(row), create=True)
        return row

    def _rated(self, scene_id, field):
        row = self.rows.get('rarity:%s:%s' % (self.persona, scene_id), [field])
        return set((row if row and field in row else self.rerate(scene_id))[field])

    def rarity(self, scene_id):
        """A place's kept common words, counted once when there are none."""
        return self._rated(scene_id, 'common')

    def said(self, scene_id):
        """The cross words a place says itself (key_words.said), counted once when there are none."""
        return self._rated(scene_id, 'said')

    def openings(self, scene_id):
        """The openings a place repeats (key_words.openings), counted once when there are none."""
        return self._rated(scene_id, 'openings')

    def rerate_all(self, moment=None):
        """At settlement: every place with lines in the window counted again; a place with none keeps no row."""
        from . import crossing
        moment = moment or clock.now()
        since = _iso(moment - timedelta(days=crossing.number('window_days')))
        places = sorted(set(message_records.inbound(self.store, since=since).values('scene_id')))
        for scene_id in places:
            self.rerate(scene_id, moment)
        self.rows.delete({'row': 'rarity', 'persona': self.persona, 'scene_id': NoneOf(places)}, many=True)
        return len(places)

    def let_go(self, slug, sid, *, scene_id=None, moment=None):
        """Her let_go: the item one place down now (a put-away item stays where it is)."""
        row = self.item(slug, sid)
        if not row:
            return None
        to = DOWN.get(row['place'])
        return self.move(row, to, 'let_go', moment, scene_id=scene_id) if to else None

    def used(self, refs, why, scene_id, moment=None):
        """Her use of items by `doc:slug#sid` refs: recall returned them, or she cited them in a tool call."""
        for doc, sid in refs:
            row = self.item(doc, sid)
            if row:
                if why == 'recalled':
                    self.rows.update({'_id': row['_id']}, [AddToSet('recalled_in', scene_id),
                                                           Set({'recalled_at': _iso(moment or clock.now())})])
                self.memorable(row, why, moment, scene_id=scene_id)

    def surfaced(self, refs, scene_id, moment=None):
        """Items a turn surfaced: memorable only when a second, different conversation brings one up."""
        for doc, sid in refs:
            row = self.item(doc, sid)
            if not row:
                continue
            seen = set(row.get('surfaced_in') or [])
            self.rows.update({'_id': row['_id']}, [AddToSet('surfaced_in', scene_id),
                                                   Set({'last_use_at': _iso(moment or clock.now())})])
            if scene_id not in seen and seen:
                self.memorable(row, 'surfaced_again', moment, scene_id=scene_id)

    # ── what she reads each turn ───────────────────────────────────
    def things(self, cls, scene, zone, moment=None, *, home=False, readable_docs=None, choose=None):
        """things_from_program: her items by store and place in words, and the moves since this conversation was
        last told, each once, with its clock time. A home turn is offered the split of current_self until `self`
        exists. `choose`: the episode id of a home turn that can write, which is shown each place over its identity
        ceiling for her to choose first (identity_over)."""
        from . import visibility
        from .schedule_rules import line_stamp
        moment = moment or clock.now()

        def here(row):
            if not visibility.readable(row.get('visibility') or 'public', cls):
                return False
            if row['store'] == 'group_notes':
                return readable_docs is not None and row['doc'] in readable_docs
            return True
        counts, docs = {}, {}
        for row in self.items(fields=THINGS_FIELDS):
            if here(row):
                counts.setdefault(row['store'], {CARRIED: 0, AT_HAND: 0, PUT_AWAY: 0})[row['place']] += 1
                docs.setdefault(row['store'], set()).add(row['doc'])

        def room(kind):
            # Measured as the cap is (_overflow): a document's carried items, the tightest one this turn reads.
            return min(CAPS[kind] - len(self._carried(doc)) for doc in docs[kind])
        places = {STORE_WORDS[kind]: '、'.join(
            '%s %s' % (place, words(ROOM_WORDS, max(0, room(kind))) if place == CARRIED and kind in CAPS
                       else words(COUNT_WORDS, n)) for place, n in tally.items())
                  for kind, tally in sorted(counts.items())}
        moves = [move for move in self.rows.find({'row': 'move', 'persona': self.persona,
                                                  'told_in': HoldsNone([scene['_id']])}, [('at', -1)])
                 if here(move)][:MOVED_SHOWN]
        block = {'places': places}
        from .carried import room_block
        room = room_block(self.store, self.persona, cls, scene['_id'])
        if room:
            block['identity_room'] = room
        over = self.overflows(here, scene['_id'], moment)
        if over:
            block['over'] = over
        choices = self.identity_over(choose, moment) if choose else []
        if choices:
            block['identity_over'] = choices
        if moves:
            block['moved'] = ['%s %s' % (line_stamp(zone, move['at']), told(move)) for move in reversed(moves)]
            self.rows.update({'_id': AnyOf([move['_id'] for move in moves])}, AddToSet('told_in', scene['_id']),
                             many=True)
        if home and not items(self.store, self.persona, doc=SELF_DOC).first():
            block['self_items'] = SELF_OFFER
        came = self.came_back(here, scene, zone, moment)
        if came:
            block['came_back'] = came
        return block

    def came_back(self, here, scene, zone, moment):
        """Once a local day in each conversation: what came back in the last day, each kind in words, and the notes
        readable here that came back most (never which place it was)."""
        from . import crossing
        day = moment.astimezone(zone['tz'] if isinstance(zone, dict) else timezone.utc).date().isoformat()
        key = 'came_back:%s:%s' % (self.persona, scene['_id'])
        if (self.rows.get(key, ['day']) or {}).get('day') == day:
            return None
        since = _iso(moment - timedelta(days=1))
        rows = crossing.fire_rows(self.store, since, persona=self.persona,
                                  kinds=[k for k, _ in CAME_BACK_KINDS]).rows(fields=['kind', 'ref'])
        tally = {kind: sum(1 for row in rows if row['kind'] == kind) for kind, _ in CAME_BACK_KINDS}
        notes = {}
        for row in rows:
            if row['kind'] == 'note' and row.get('ref'):
                notes[row['ref']] = notes.get(row['ref'], 0) + 1
        named = []
        for ref_, n in sorted(notes.items(), key=lambda pair: -pair[1]):
            doc, _, sid = ref_[len('doc:'):].partition('#')
            item = self.item(doc, sid)
            if item and here(item):
                named.append('「%s」%s' % (item.get('heading') or sid, words(TIMES_WORDS, n)))
            if len(named) == CAME_BACK_ITEMS:
                break
        parts = ['%s %s' % (label, words(TIMES_WORDS, tally[kind])) + ('（%s）' % '、'.join(named) if kind == 'note' and named else '')
                 for kind, label in CAME_BACK_KINDS]
        self.rows.update({'_id': key}, Set({'row': 'told', 'persona': self.persona, 'scene_id': scene['_id'],
                                            'day': day}), create=True)
        return '最近一天：' + '；'.join(parts)


_ticked = {}                      # (database, persona): when this process last ran tick (time.monotonic)


def tick_due(store, persona):
    """A turn's `tick`: run when this process has not run it for this persona within TICK_SECONDS (a memo of this
    process; nothing is written for it). Returns the moves."""
    key = (store.name, persona)
    if key in _ticked and time.monotonic() - _ticked[key] < TICK_SECONDS:
        return []
    moves = Tiers(store, persona).tick()
    _ticked[key] = time.monotonic()
    return moves


def lapse_due(store, persona):
    """A turn's lapses over a place's identity ceiling (Tiers.lapse_over), before the turn reads anything: one indexed
    read when no place is over. Returns whether a place is still over (its choice for a home turn to show). A fault
    here never fails her turn: it is one audit line, and the place stays over until a later turn."""
    tiers = Tiers(store, persona)
    try:
        rows = tiers._over_rows()
        if not rows:
            return False
        tiers.lapse_over(rows=rows)
        return bool(tiers._over_rows())
    except Exception as exc:                          # noqa: BLE001 her turn goes on; the place waits
        try:
            store.audit('memory:' + persona, 'memory.identity_over', {'phase': 'failed', 'error': type(exc).__name__},
                        'global-safe')
        except Exception:                             # noqa: BLE001 the same database may be what failed
            pass
        return False


def signing(row, intent, body=None):
    """Why this write may not make the item a fact (her own judgment signed by herself), or None."""
    recorded = (row or {}).get('from')
    source = intent.get('from') or recorded
    if intent.get('nature') == FACT and source == OWN_JUDGMENT and not (row or {}).get('confirmed'):
        return JUDGMENT_NOT_FACT
    if recorded == OWN_JUDGMENT and intent.get('from') == CHECKED and not (row or {}).get('confirmed'):
        # Checked means rewritten with its basis, not relabelled.
        if intent.get('op') != 'replace_section' or not has_basis(body or ''):
            return JUDGMENT_NOT_FACT
    return None


def has_basis(text):
    return any(word in text for word in BASIS)


def declared_nature(intent):
    """The nature and source she gave a write ({} when neither): her word for the nature wins over the source's."""
    source = intent.get('from') if intent.get('from') in FROM_NATURE else None
    nature = intent.get('nature') if intent.get('nature') in NATURES else FROM_NATURE.get(source)
    if not nature:
        return {}
    return {'nature': nature, 'fact': nature == FACT, **({'from': source} if source else {})}


def anchor_field(declared, intent):
    """{'line': anchor} when the write names a source that is someone's word and the program resolved the line it rests on
    (`intent['anchor']`, set by the handler and never by her), else {}."""
    anchor = intent.get('anchor')
    if declared.get('from') in OTHERS_SAID and isinstance(anchor, dict):
        return {'line': {'scene': anchor['scene'], 'seq': anchor['seq']}}
    return {}


def sources(store, persona, slug, scene):
    """{section id: where its claim rests} for a document's items that rest on a line, as `scene` reads them (ADR-108
    D2: People.source_of). An item shows its source only while it is someone's word."""
    from .people import People
    people, found = People(store, persona), {}
    for row in items(store, persona, doc=slug).rows():
        if row.get('line') and row.get('from') in OTHERS_SAID:
            found[row['sid']] = people.source_of(scene, row['line'])
    return found


def told(move):
    """A move as her result or the moved line says it, in words: the line it was made with (`lapse_line`, a lapse
    over a place's ceiling), else its heading, places and reason."""
    if move.get('lapse_line'):
        return move['lapse_line']
    return '「%s」%s→%s（%s）' % (move.get('heading') or move['sid'], move['from'], move['to'],
                               REASONS.get(move['reason'], move['reason']))



ABOUT = ('self', 'person', 'place', 'world')


def recalled(store, window_days, moment=None):
    """{memory id: [episode ids]} for memories she recalled herself (`recall.read`) in at least two different
    conversations within the window: promotion's candidates come from her acts, not from what she was shown."""
    moment = moment or clock.now()
    since = (moment - timedelta(days=float(window_days or 7))).isoformat()
    seen = {}
    from . import audit as audit_trail
    for row in audit_trail.events(store, 'recall.read', since=since, by=None).each(
            fields=['stream_id', 'scope_key', 'payload.memories']):
        for memory_id in (row.get('payload') or {}).get('memories') or []:
            if isinstance(memory_id, str) and not memory_id.startswith('doc:'):
                entry = seen.setdefault(memory_id, ({}, set()))
                entry[0][row['stream_id']] = True
                entry[1].add(row.get('scope_key'))
    return {key: list(episodes) for key, (episodes, scopes) in seen.items() if len(scopes) >= 2}


def candidates(store, window_days, limit=20):
    """promotion_candidates: what she recalled in different conversations."""
    picked = recalled(store, window_days)
    rows = {row['_id']: row for row in memory_records.many(store, list(picked), status='active').each(
        fields=['body_markdown', 'kind'])}
    return [{'memory_id': key, 'kind': rows[key].get('kind'), 'excerpt': rows[key].get('body_markdown', '')[:300],
             'episodes': episodes} for key, episodes in sorted(picked.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            if key in rows][:limit]


def land(store, ep, item, episodes):
    """promote_memory with `about`: the fact store of its subject. self → `core`; world → the ledger WORLD_LEDGER;
    place → that group's notes when every source is from one group (and none from home); person → the index as
    before (a person's facts are written with understand_person). Returns (ref, words) or (None, words)."""
    from .documents import DocumentStore
    from .group_admin import notes_slug
    about = item.get('about')
    body = '%s\n依据：%s' % (item['fact'], item['why'])
    heading = item['fact'].splitlines()[0][:30]
    slug, intent = None, {'op': 'append_section', 'heading': heading, 'reason': 'promote_memory: ' + item['why'][:200]}
    if about == 'self':
        slug = CORE_DOC
    elif about == 'world':
        slug, intent = WORLD_LEDGER, {**intent, 'kind': 'ledger', 'visibility': item.get('visibility') or 'owner_private'}
    elif about == 'place':
        scenes = {row.get('scene_id') for row in episode_records.many(store, list(episodes)).rows(fields=['scene_id'])}
        groups = [scene for scene in scene_records.many(store, list(scenes), fields=['kind'])
                  if scene.get('kind') == 'group']
        if len(scenes) == 1 and len(groups) == 1 and item.get('visibility') == 'public':
            slug, intent = notes_slug(groups[0]['_id']), {**intent, 'visibility': 'public'}
    if not slug:
        return None, ('关于一个人的事实用 understand_person 写到那个人那里；这条先照旧记进长期记忆。' if about == 'person'
                      else '来源不全是同一个群（或有家里的话），记不进群笔记；这条先照旧记进长期记忆。' if about == 'place'
                      else None)
    from .render import budget_gate
    docs = DocumentStore(store, ep['persona'])
    before = docs.read(slug)
    # What it adds is carried: the same gate as her own writes (ADR-096): a place it leaves over waits for her choice.
    gate = budget_gate(store, ep['persona'], refuse=False)
    docs.apply(slug, intent, body, base_revision_id=before[0], author='character',
               mutation_id='%s:promote:%s' % (ep['_id'], sha(canonical(item))[:16]), budget=gate)
    after = docs.read(slug)[1]
    sid = after['sections'][-1]['sid']
    Tiers(store, ep['persona']).written(slug, {**intent, 'nature': FACT}, before[1], after, scene_id=ep.get('scene_id'),
                                        before_revision=before[0], over=gate.planned)
    return ref(slug, sid), '记进了 %s' % ref(slug, sid)


WEEK_NOTE = ('这一周你的记忆：left 是从随身放下的，每条后面写着之后你有没有 recall 过它；put_away 是随便翻到的一条收着的原话；'
             'changed 是这周你改过的。')
WEEK_TEXT_CHARS = 2000


def week(store, persona, zone, moment=None):
    """Her weekly reading of her memory (her answer, 2026-10-13), in a self-evaluation turn, at most once a week: what
    left 随身 this week and whether she recalled it afterwards, one put-away item's own text (chosen by the week), and
    one line of what she changed. No scores, no counts. None when shown within the last week."""
    from .config import excerpt
    from .documents import DocumentStore
    from .schedule_rules import line_stamp
    moment = moment or clock.now()
    tiers = Tiers(store, persona)
    since = (moment - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    if tiers._first({'row': 'offer', 'persona': persona, 'what': 'week', 'at': Range(gte=since)}):
        return None
    left = []
    for move in tiers.rows.find({'row': 'move', 'persona': persona, 'from': CARRIED, 'at': Range(gte=since)},
                                [('at', 1)]):
        row = tiers.rows.get(move['item']) or {}
        again = (row.get('recalled_at') or '') > move['at']
        left.append('%s「%s」放到了%s（%s）；之后你%s' % (line_stamp(zone, move['at']), move.get('heading') or move['sid'],
                                                    move['to'], REASONS.get(move['reason'], move['reason']),
                                                    'recall 过它' if again else '没再 recall 它'))
    block = {'left': left or ['这一周没有东西从随身放下。']}
    week_id = moment.isocalendar()[:2]
    away = sorted(tiers.items(place=PUT_AWAY, fields=['doc', 'sid', 'heading']),
                  key=lambda row: sha(canonical([list(week_id), row['_id']])))
    if away:
        row = away[0]
        content = DocumentStore(store, persona).read(row['doc'])[1] or {}
        text = next((s.get('body') for s in content.get('sections') or [] if s['sid'] == row['sid']), None)
        if text:
            block['put_away'] = {'ref': ref(row['doc'], row['sid']), 'heading': row.get('heading'),
                                 'text': excerpt(text, WEEK_TEXT_CHARS)}
    changed = [row.get('heading') or row['sid'] for row in tiers.items(fields=['sid', 'heading', 'rewritten_at'])
               if (row.get('rewritten_at') or '') >= since]
    block['changed'] = ('这周你改过：' + '、'.join('「%s」' % name for name in changed)) if changed else '这周你没改过哪一条。'
    tiers.rows.update({'_id': 'offer:week:%s:%d-%d' % (persona, *week_id)}, OnCreate({
        'row': 'offer', 'persona': persona, 'what': 'week', 'at': _iso(moment)}), create=True)
    return block


# What `read_sections` says its `detail` is: the earlier full version a section was once shortened from, which stays
# readable beside it whatever the section says now (ADR-117 L4).
DETAIL_WHAT = '这一节以前从下面这段全文缩短过；这是缩短之前那一版的原文。'


def detail(store, persona, row):
    """The verbatim a gist stands for (its revision before the gist), or None."""
    behind = (row or {}).get('detail_of') or {}
    if not behind:
        return None                     # not a gist (or no item at all, as for a working document): nothing behind
    from . import documents
    from .records import heads as head_records
    revision = head_records.revision(store, behind.get('revision_id')) if behind.get('revision_id') else None
    for section in ((revision or {}).get('content') or {}).get('sections') or []:
        if section.get('sid') == row['sid']:
            return section.get('body')
    old = documents.revision_of_body(store, persona, row['doc'], row['sid'], behind.get('body_sha256')) if behind \
        else None
    if old:
        return old.get('body')
    for change in documents.revisions(store, persona, row['doc'], sid=row['sid']).rows(newest_first=True):
        if sha((change.get('body') or '').encode()) == behind.get('body_sha256'):
            return change.get('body')
    return None


def placed(store, persona, slug, content, override=None):
    """A document's sections as the turn reads them."""
    return Tiers(store, persona).placed(slug, content, override)


def within_age(row, moment, *, half_life_days=30.0, step_back_below=0.1):
    """Whether an item at hand may come up by itself (deliver, outside recall): a fact always; a memory while its
    last use or memorable moment is within JOURNAL_AGE_DAYS (a running record's row) or before its freshness,
    0.5 ** (days / half_life_days), falls below step_back_below (the rest). Nothing is written."""
    if row.get('fact'):
        return True
    last = max(filter(None, (_at(row.get('memorable_at')), _at(row.get('last_use_at')))), default=moment)
    days = (moment - last).total_seconds() / 86400
    if row['store'] == 'journal':
        return days <= JOURNAL_AGE_DAYS
    return not (half_life_days and 0.5 ** (days / half_life_days) < step_back_below)


def deliver(store, persona, pilot, retrieval, query, readable, scene_id, *, recall=False, counts=True,
            half_life_days=30.0, step_back_below=0.1, moment=None, excerpt_chars=800):
    """Her own items a turn brings up by itself (手边 within its age bound, `within_age`; a recall also reaches 收着
    and every age): an item whose key the message has (key_words.py), or one scored above FLOOR as memories are; at
    most OWN_SLOTS in fused order, as memory entries with their store, place and age words, a doc ref, and the word
    that brought it. What is carried (随身) is already in front of her and is never brought up again, except a
    group-notes section folded to its heading this turn (ADR-096), which comes up labelled as carried and folded. Each
    one surfaced is marked: recalled, or surfaced in this conversation. Returns (the entries, the refs of carried items
    the turn would have brought up had they not been carried: the program's score for what she carries). With
    `counts` False (a turn whose message is program text, PROGRAM_TEXT_KINDS) the entries still come up, but nothing
    is marked and no score is returned."""
    from .config import excerpt
    from .memory_pilot import rank
    items = list(getattr(pilot, 'items', None) or [])
    if not items:
        return [], []
    tiers = Tiers(store, persona)
    rows = {(row['doc'], row['sid']): row for row in tiers.items(fields=DELIVER_FIELDS)}
    allowed = (AT_HAND, PUT_AWAY) if recall else (AT_HAND,)
    moment = moment or clock.now()
    from .group_admin import folded as _folded
    folded = {(doc, sid) for doc in {item['doc'] for item in items if item['store'] == 'group_notes'
                                     and item['scope_key'] in readable}
              for sid in _folded(store, persona, doc)}

    def tier(item):
        return (rows.get((item['doc'], item['sid'])) or {}).get('place')

    def is_folded(item):
        return tier(item) == CARRIED and (item['doc'], item['sid']) in folded

    def in_pool(item):
        if is_folded(item):
            return True
        if tier(item) not in allowed:
            return False
        return recall or within_age(rows[(item['doc'], item['sid'])], moment, half_life_days=half_life_days,
                                    step_back_below=step_back_below)
    readable_items = [item for item in items if item['scope_key'] in readable and tier(item)]
    pool = [item for item in readable_items if in_pool(item)]
    carried = [item for item in readable_items if tier(item) == CARRIED and not is_folded(item)]
    if not pool and not carried:
        return [], []
    table = tiers.rarity(scene_id)
    said = {item['key']: key_said(item, table, query) for item in pool + carried}
    try:
        vector = retrieval.query_vector(query) or retrieval.embed([query], 'query')[0]
    except Exception:
        vector = None                    # the embedding route is down: the exact word still brings an item back

    def admit(candidates):
        if vector is None:
            return [item['key'] for item in candidates if said[item['key']]][:OWN_SLOTS]
        order, scores, _ = rank(candidates, query, vector)
        order += [item['key'] for item in candidates if said[item['key']] and item['key'] not in order]
        return [key for key in order if said[key] or scores.get(key, 0) >= FLOOR][:OWN_SLOTS]
    would = []
    if carried and not recall and counts:
        # A carried item is never brought up (it is in front of her), so it cannot show use that way: one the turn
        # would have brought up, had it not been carried, is used in this conversation.
        above = admit(pool + carried)
        hits = [(item['doc'], item['sid']) for item in carried if item['key'] in above]
        tiers.surfaced(hits, scene_id, moment)
        would = [ref(*hit) for hit in hits]
    if not pool:
        return [], would
    by_key = {item['key']: item for item in pool}
    out, refs = [], []
    for key in admit(pool):
        item, row = by_key[key], rows[(by_key[key]['doc'], by_key[key]['sid'])]
        out.append({'_id': ref(item['doc'], item['sid']), 'kind': 'own_item', 'heading': item.get('heading') or row['heading'],
                    'body_markdown': excerpt(item['text'], excerpt_chars), 'store': STORE_WORDS[row['store']],
                    'place': FOLDED if is_folded(item) else row['place'],
                    'age': FACT if row.get('fact') else age_word(row.get('added'), moment),
                    **({'why': BROUGHT_BY % said[key]} if said[key] else {})})
        refs.append((item['doc'], item['sid']))
    if refs and counts:
        tiers.used(refs, 'recalled', scene_id) if recall else tiers.surfaced(refs, scene_id)
    return out, would


BROUGHT_BY = '因为这句话里有「%s」'


def key_said(item, table, text):
    """The first of an item's keys the text has, as the text spells it, or None."""
    from . import key_words
    return next(filter(None, (key_words.found(key, text) for key in key_words.keys(item, table))), None)


def headings(store, persona, pilot, query, readable, cls, scene_id, shown=()):
    """recall: the headings of her items at hand or put away whose key the question has (the keys a turn's message
    brings an item back by), beyond the bodies it returns, each with the word that matched."""
    from . import visibility
    tiers = Tiers(store, persona)
    rows = {(row['doc'], row['sid']): row for row in tiers.items(place=AnyOf([AT_HAND, PUT_AWAY]))}
    indexed = {(item['doc'], item['sid']): item for item in getattr(pilot, 'items', None) or []}
    table = tiers.rarity(scene_id)
    found = []
    for key, row in rows.items():
        if ref(*key) in shown or not visibility.readable(row.get('visibility') or 'public', cls):
            continue
        item = indexed.get(key) or {'heading': row.get('heading') or '', 'store': row['store'], 'scope_key': None}
        if item['scope_key'] is not None and item['scope_key'] not in readable:
            continue
        said = key_said(item, table, query)
        if said:
            found.append((-len(said), row['heading'], {'ref': ref(*key), 'heading': row['heading'],
                                                       'store': STORE_WORDS[row['store']], 'place': row['place'],
                                                       'why': BROUGHT_BY % said}))
    return [entry for *_, entry in sorted(found)[:HEADINGS_SHOWN]]


# A document's headings as recall lists them: the latest that fit, after one entry saying how many earlier ones there
# are and how to reach them. A log runs to hundreds of sections: 476 headings were 60,740 characters, past what a tool
# result may carry inline, so the result was cut and its path pointed at a tool she does not have (B15, 2026-10-21).
LISTED_HEADINGS_CHARS = 8000
EARLIER_HEADINGS = ('前面还有 %d 个更早的标题没列出（这份共 %d 个）：要找哪一节，用 recall 的 query 搜标题，'
                    '或 sections 写 {doc, section} 直接读。')


def doc_headings(store, persona, slug, content, cls, limit=LISTED_HEADINGS_CHARS):
    """recall with a doc and no sid: that document's headings, each with its place; the latest that fit `limit`
    characters, after a first entry naming how many earlier ones are left out."""
    import json
    from . import visibility
    places = {row['sid']: row['place'] for row in Tiers(store, persona).items(doc=slug)}
    listing = [{'sid': s['sid'], 'heading': s.get('heading') or s['sid'],
                'place': places.get(s['sid']) or FROM_INJECT.get(s.get('inject'), AT_HAND)}
               for s in (content or {}).get('sections') or [] if visibility.readable(s.get('visibility') or 'public', cls)]
    kept, size = [], 0
    for item in reversed(listing):
        size += len(json.dumps(item, ensure_ascii=False)) + 2            # with its separator in the list
        if size > limit:
            break
        kept.append(item)
    earlier = len(listing) - len(kept)
    return ([{'earlier': EARLIER_HEADINGS % (earlier, len(listing))}] if earlier else []) + kept[::-1]


DOC_REF = re.compile(r'doc:([^#\s"\'，。、]+)#([^\s"\'，。、）)]+)')


def refs_in(value):
    """The `doc:slug#sid` refs anywhere in a tool call's arguments."""
    import json
    return sorted(set(DOC_REF.findall(json.dumps(value, ensure_ascii=False))))
