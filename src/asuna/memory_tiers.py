"""Tiered memory (ADR-062): where each of her items lives, kept up by what is memorable, moved down by the program.

Every section of her persona, voice, ledgers, group notes, running records and the `self` and `core` documents is an
item. The program never rewrites an item's text; beside it, in the collection `memory_tiers` (rows `item`), it keeps
the item's place (随身 carried in every turn where it is readable, 手边 at hand: found by a turn about it or by
`recall`, 收着 put away: found by `recall` only), when it was last memorable and its stay. A 随身 item lapses to 手边
when its stay runs out; each memorable moment (recall returned it, a rewrite that changed it, its `doc:` ref cited, a
second conversation it came up in, a near-duplicate met from another conversation) starts the stay again and, once per stay, doubles the
next. A store over its count cap lapses its least recently memorable item. Memories (`self`, running records) cool to
收着 by disuse; facts (persona, voice, ledgers, group notes, `core`) never do: a correction or a merge supersedes
them. Every move is one row `move` and one audit line `memory.moved`, saying who made it (`by`: `her` for her let_go
and her own `inject` writes, `program` for the rest), and is told once in each conversation that can read the item
(`things_from_program`). Where a write leaves each section is one rule, `Tiers.placement_after`, which the identity
gate (carried.py) measures before the write lands. A group's notes over their per-turn limit fold by last surfacing
(`fold_order`, kept and recomputed on a write and at settlement); a folded section is at hand for `deliver`. The
program never writes her `inject`: the tier is the record of what is carried. She reads all of it as words from the
tables below.

`ENABLED` is the switch; off, nothing here is read or written and her turns are as before.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .evidence import canonical, sha

TIERS_VERSION = 1
ENABLED = True                     # the switch (ADR-062 phase 2): hers and the owner's to turn on
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
# Each item is a fact (what is: never cools by disuse, replaced only by correction) or a memory (what happened, or
# her own judgment: follows the cycle). Her answer (2026-10-13): per item, not per store. The store gives the default;
# she may say it, or say where the item came from, when she writes it.
FACTS = ('persona', 'ledger', 'group_notes', 'core')       # stores whose items are facts unless she says
MEMORIES = ('self', 'journal', 'voice')                    # her voice is something she keeps changing (her answer)
FACT, MEMORY = '事实', '记忆'
NATURES = (FACT, MEMORY)
FROM_NATURE = {'主人定的': FACT, '查过的': FACT, '别人说的': MEMORY, '我自己的判断': MEMORY}
SOURCES = tuple(FROM_NATURE)
# Her rule (2026-10-13): a fact needs an author who can correct it. Her own judgment becomes a fact only when someone
# else confirms it (met again from another conversation) or when she has checked it (rewritten with 查过的 and a basis).
OWN_JUDGMENT, CHECKED = '我自己的判断', '查过的'
OTHERS_SAID = ('别人说的', '主人定的')
FACT_AUTHORS = (*OTHERS_SAID, CHECKED)
# Considered and dropped (owner's call, 2026-10-13): a correction thread that upholds it. No honest signal for it
# exists without the program judging what was said, which would grade her text.
JUDGMENT_NOT_FACT = ('你自己的判断不能由你自己签成事实：要有人确认（另一处又碰到同样的说法），或者你查过了：'
                     '用 replace_section 把它改写成带依据的一条（依据：谁、何时、从哪来），from 写 查过的。')
CAPS = {'self': 12, 'persona': 18, 'ledger': 10, 'group_notes': 10, 'core': 12, 'voice': 6}
FIRST_STAY_DAYS = {'group_notes': 28, 'core': 56, 'voice': 56}
STAY_DAYS, STAY_CAP_DAYS = 14, 56
# The switch-on day only: each first stay spread per item from its usual length up to twice that (14..28 days; a
# group's notes 28..56), never past the stay cap, so what nothing uses lapses gradually, not all on one day (owner
# 2026-10-13, after the dry run). Later items take the usual first stay.
JOURNAL_COOL_DAYS = 30
AGE_WORDS = ((1, '刚写的'), (7, '这几天'), (14, '前阵子'), (45, '上个月'), (None, '更早'))
COUNT_WORDS = ((0, '没有'), (3, '几条'), (9, '好几条'), (19, '十几条'), (99, '几十条'), (None, '很多条'))
# How much room a store's 随身 has left under its cap, said in every turn instead of its count: the carried items are
# in front of her already; what she could not see was how close the cap is (her ask, 2026-10-19).
ROOM_WORDS = ((0, '满了'), (1, '还能放一条'), (3, '还能放两三条'), (9, '还能放好几条'), (None, '还空着很多'))
REASONS = {'stay': '一阵子没用到', 'overflow': '随身满了', 'cooled': '很久没用', 'let_go': '你放手了',
           'superseded': '被更正替换', 'merged': '合并了', 'gist_skipped': '两晚没写意思', 'rewritten': '你改写了它'}
# Who moved an item (her ask, ADR-096): her own let_go and her own `inject` writes (reason let_go) are hers; every
# other move, the lift a rewrite brings included, is the program's.
BY = {'let_go': 'her'}
# A group-notes section carried but folded to its heading this turn, when a turn brings it up (deliver).
FOLDED = CARRIED + '（折叠了）'


def moved_by(move):
    """Who made a move: its `by`, or for a row written before moves said it, the same rule from its reason."""
    return move.get('by') or BY.get(move.get('reason'), 'program')
HER_OPS = ('replace_section', 'append_section', 'correction', 'set_tags')     # her writes (placement_after)
MOVED_SHOWN = 5
FLOOR, OWN_SLOTS, SLOTS = 0.83, 2, 6     # her own items: two of a turn's six memory slots, above an absolute floor
HEADINGS_SHOWN = 8
# The night list (settlement): at most a few items, chosen by rule, told why; no keep or drop choice among them.
NIGHT_ITEMS = 5
GIST_CHARS, GIST_LIST_ABOVE, GIST_NIGHTS = 160, 240, 2
DATED = re.compile(r'\d{1,4}[年/.-]\d{1,2}|\d{1,2}月\d{1,2}|\d{1,2}:\d{2}')
# What a basis looks like (her answer 2026-10-13: an item is a claim with its basis; a gist keeps the basis line).
BASIS = ('依据', '来源', '据', '样本', '证据', '查过', '测过', '主人说', '主人定', '因为', '出处')
DUPLICATE_SCORE = 0.95
REPEATED_PLACES, REPEATED_STAYS = 2, 3
LOOK_BACK_DAYS = 7
WORLD_LEDGER = 'world'
NIGHT_WHAT = {'gist': '写一句意思', 'repeated': '几处都提到', 'merge': '合并'}
NIGHT_HOW = {
    'gist': ('用 replace_section 把它写成一两句意思（%d 字以内）；有依据的，意思后面留一行依据（谁、何时、从哪来）。'
             '原文留在后面，recall 读得到；两晚都没写，原文就自己收着。' % GIST_CHARS),
    'repeated': ('它是什么由你定：进 core（append_section 到 doc=core）、记到那个人（understand_person）、'
                 '记到那个群（那个群的笔记）、记进账（append_section 到一份活账）%s，或者还在变（不用做什么）。'),
    'merge': '两条说的是一件事：改写成一条（replace_section 其中一条），另一条 let_go。',
    'merge_fact': '两条说的是一件事，都是事实，要合并：改写成一条（replace_section 其中一条），另一条 let_go。',
}
NIGHT_WHY = {'gist': '刚放到手边，还是原样的长段',
             'repeated': '不同的对话里都碰到它', 'merge': '两条很像'}
GIST_NO_BASIS = ('这句意思没带依据，没写进去：原文有依据（%s），意思后面留一行依据（谁、何时、从哪来，不算在 %d 字里）'
                 '再写一次。' % ('%s', GIST_CHARS))
# Her choice when a store is over its cap (her ask, 2026-10-18; no keep act, ADR-062): what is carried, and the default.
OVER_LINE = ('随身满了（%s %d/%d）：随身的有 %s。想换就 let_go 一条；这一回合不挑，下一回合程序照旧放最久没用到的「%s」。')
SEARCHED = '找了：随身、手边、收着'
NOTHING = '随身、手边、收着三处都没找到'
# A tag never carries an item back (no pin, owner 2026-10-13): only a changed rewrite does (ADR-062 §4.2 step 7); a
# use keeps it from cooling but does not lift it.
NOT_BACK = ('when_shown 改成 always 不会把它带回随身：你把它改写出变化，它才会回来；再被用到只让它不再往下放；'
            '现在它在%s。')
# What she is told once per conversation, in her system prompt where the memory rules are (ADR-062 §4.3): the persona
# model's `memory.tiers_told` (a persona package words it; the core default is neutral, persona_model.CORE_DEFAULTS).


def told_text(config):
    from .persona_model import effective
    return effective((config or {}).get('persona_model') or {}, 'memory.tiers_told')
THINGS_NOTE = ('你的东西在哪：每份随身还能放多少，手边、收着各有几条；moved 是程序挪过的，每件只说一次（又用到、改写出变化就回来）；'
               'identity_room 是各处每回合随身带的身份部分（persona、voice、self、core 合起来）用了上限的多少，变了才说；'
               'self_items 是把 current_self 拆成条的提议。')
NIGHT_NOTE = '夜里的清单：每条写着为什么在这、可以怎么做，都不是留或删的选择；没做的，程序也不替你做。'
SELF_OFFER = ('current_self 现在是一整段。想好了就把它拆成一条一条，用 write_document 写进 doc=self（append_section）：'
              '一条是一个说法连同它的依据（样本、来源、证据），不按行拆；原来那段留作历史，程序不替你拆。')


def _now():
    return datetime.now(timezone.utc)


def _iso(moment):
    return moment.isoformat()


def _at(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')) if value else None
    except ValueError:
        return None


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


class Tiers:
    def __init__(self, store, persona):
        self.store, self.persona = store, persona
        self.rows = store.db[COLLECTION]

    # ── items ──────────────────────────────────────────────────────
    def items(self, **query):
        return list(self.rows.find({'row': 'item', 'persona': self.persona, **query}))

    def item(self, doc, sid):
        return self.rows.find_one({'_id': item_id(self.persona, doc, sid)})

    def _new(self, doc, sid, kind, section, place, moment, *, scene_id=None, felt=False):
        row = {'_id': item_id(self.persona, doc, sid), 'row': 'item', 'tiers_version': TIERS_VERSION,
               'persona': self.persona, 'doc': doc, 'sid': sid, 'store': kind, 'fact': kind in FACTS,
               'nature': FACT if kind in FACTS else MEMORY,
               'heading': section.get('heading') or sid, 'visibility': section.get('visibility') or 'public',
               'place': place, 'added': _iso(moment), 'memorable_at': _iso(moment), 'stay_from': _iso(moment),
               'stay_days': FIRST_STAY_DAYS.get(kind, STAY_DAYS), 'doubled': False, 'stays': 0, 'uses': 0,
               'body_sha256': section.get('body_sha256') or sha((section.get('body') or '').encode()),
               'chars': len(section.get('body') or ''), 'surfaced_in': [], 'recalled_in': [],
               **({'scene_id': scene_id} if scene_id else {}), **({'felt': True} if felt else {})}
        self.rows.update_one({'_id': row['_id']}, {'$setOnInsert': row}, upsert=True)
        return self.rows.find_one({'_id': row['_id']})

    def sync(self, moment=None):
        """Every item has a row. One the program has not seen takes its place from its `inject` (always 随身,
        on_demand 手边, never 收着) with a fresh stay: nothing lapses on the day the switch goes on. On that day (no
        rows yet), each first stay is spread per item from its usual length to twice that, within the cap."""
        from .documents import DocumentStore
        moment = moment or _now()
        docs = DocumentStore(self.store, self.persona)
        known = {(row['doc'], row['sid']) for row in self.rows.find({'row': 'item', 'persona': self.persona},
                                                                     {'doc': 1, 'sid': 1})}
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
                    self.rows.update_one({'_id': row['_id']}, {'$set': {'stay_days': usual + spread}})

    def placed(self, slug, content, override=None):
        """A document as the turn reads it: each section's `inject` follows its place (a copy; the text untouched).
        `override` ({sid: place}) is where a write will leave the sections it moves (placement_after)."""
        if not content or not content.get('sections'):
            return content
        places = {row['sid']: row['place'] for row in self.rows.find(
            {'row': 'item', 'persona': self.persona, 'doc': slug}, {'sid': 1, 'place': 1})}
        places.update(override or {})
        if not places:
            return content
        return {**content, 'sections': [{**section, 'inject': TO_INJECT[places[section['sid']]]}
                                        if section['sid'] in places else section
                                        for section in content['sections']]}

    # ── moves ──────────────────────────────────────────────────────
    def move(self, row, to, reason, moment=None, *, scene_id=None):
        """One item to another place: the row, a `move` row told once per conversation, one audit line."""
        moment = moment or _now()
        if row['place'] == to:
            return None
        fields = {'place': to, 'moved_at': _iso(moment)}
        if to == CARRIED:                         # a new stay from now
            fields.update(stay_from=_iso(moment), memorable_at=_iso(moment), doubled=False)
        if reason in ('superseded', 'merged'):
            fields['superseded_at'] = _iso(moment)
        if reason == 'stay':
            fields['stays'] = int(row.get('stays') or 0) + 1
        self.rows.update_one({'_id': row['_id']}, {'$set': fields})
        by = BY.get(reason, 'program')
        move = {'_id': 'move:' + sha(canonical([row['_id'], row['place'], to, _iso(moment)]))[:32], 'row': 'move',
                'persona': self.persona, 'item': row['_id'], 'doc': row['doc'], 'sid': row['sid'],
                'heading': row.get('heading'), 'store': row['store'], 'visibility': row.get('visibility'),
                'from': row['place'], 'to': to, 'reason': reason, 'by': by, 'at': _iso(moment), 'told_in': []}
        self.rows.update_one({'_id': move['_id']}, {'$setOnInsert': move}, upsert=True)
        self.store.audit('memory:' + self.persona, 'memory.moved', {'item': row['_id'], 'doc': row['doc'],
                         'sid': row['sid'], 'from': row['place'], 'to': to, 'reason': reason, 'by': by,
                         **({'scene_id': scene_id} if scene_id else {})}, 'global-safe')
        return move

    def tick(self, moment=None, *, half_life_days=30.0, step_back_below=0.1):
        """Lapses whose stay ran out and memories cooled by disuse; facts never cool. Returns the moves."""
        moment = moment or _now()
        moves = []
        for row in self.items(place={'$in': [CARRIED, AT_HAND]}):
            if row['place'] == CARRIED:
                start = _at(row.get('memorable_at')) or moment
                if moment - start > timedelta(days=float(row.get('stay_days') or STAY_DAYS)):
                    moves.append(self.move(row, AT_HAND, 'stay', moment))
            elif not row.get('fact'):
                last = max(filter(None, (_at(row.get('memorable_at')), _at(row.get('last_use_at')))), default=moment)
                days = (moment - last).total_seconds() / 86400
                cooled = (days > JOURNAL_COOL_DAYS if row['store'] == 'journal'
                          else half_life_days and 0.5 ** (days / half_life_days) < step_back_below)
                if cooled:
                    moves.append(self.move(row, PUT_AWAY, 'cooled', moment))
        return [move for move in moves if move]

    def memorable(self, row, why, moment=None, *, scene_id=None):
        """A memorable moment: the stay starts again from now and, once per stay, the next one doubles. It never moves
        the item: only a changed rewrite brings one back up (ADR-062 §11)."""
        moment = moment or _now()
        fields = {'memorable_at': _iso(moment), 'last_use_at': _iso(moment), 'last_moment': why}
        if not row.get('doubled'):
            fields.update(stay_days=min(STAY_CAP_DAYS, float(row.get('stay_days') or STAY_DAYS) * 2), doubled=True)
        self.rows.update_one({'_id': row['_id']}, {'$set': fields, '$inc': {'uses': 1}})

    PER_DOC = ('ledger', 'group_notes', 'self', 'core')

    def _carried(self, doc, kind):
        return self.items(doc=doc, place=CARRIED) if kind in self.PER_DOC else self.items(store=kind, place=CARRIED)

    def _overflow(self, doc, kind, keep, moment):
        """A store over its cap: her choice first (her ask, 2026-10-18). The first time it is over, nothing moves; her
        next turn that reads it lists what is carried, with days unused, and she may let one go. A turn later, if it
        is still over, it lapses its least recently memorable items (felt ones last), as before. The moves made."""
        cap = CAPS.get(kind)
        carried = self._carried(doc, kind)
        key = 'over:%s:%s' % (self.persona, doc if kind in self.PER_DOC else 'store:' + kind)
        if not cap or len(carried) <= cap:
            self.rows.delete_one({'_id': key})
            return []
        pending = self.rows.find_one({'_id': key})
        order = sorted((row for row in carried if row['_id'] not in (keep, (pending or {}).get('keep'))),
                       key=lambda row: (bool(row.get('felt')), row.get('memorable_at') or '', row['_id']))
        if not pending or not pending.get('shown_in'):
            # Waiting for her: one item over at most; more than that lapses by the rule now (her choice is the last).
            self.rows.update_one({'_id': key}, {'$setOnInsert': {'row': 'over', 'persona': self.persona, 'doc': doc,
                                                                 'store': kind, 'since': _iso(moment), 'shown_in': []},
                                                '$set': {'keep': keep}}, upsert=True)
            return [move for move in (self.move(row, AT_HAND, 'overflow', moment)
                                      for row in order[:max(0, len(carried) - cap - 1)]) if move]
        self.rows.delete_one({'_id': key})
        return [move for move in (self.move(row, AT_HAND, 'overflow', moment) for row in order[:len(carried) - cap])
                if move]

    def overflows(self, here, scene_id, moment):
        """The stores over their cap that this turn reads: shown once each, for her to choose; one already shown
        in an earlier turn lapses by the program's rule first (so a cap is over for one turn at most)."""
        lines = []
        for pending in list(self.rows.find({'row': 'over', 'persona': self.persona})):
            if not here({'store': pending['store'], 'doc': pending['doc'], 'visibility': None}):
                continue
            if pending.get('shown_in'):
                self._overflow(pending['doc'], pending['store'], pending.get('keep'), moment)
                continue
            carried = self._carried(pending['doc'], pending['store'])
            cap = CAPS.get(pending['store'])
            if not cap or len(carried) <= cap:
                self.rows.delete_one({'_id': pending['_id']})
                continue
            def unused(row):
                last = max(filter(None, (_at(row.get('memorable_at')), _at(row.get('last_use_at')))), default=moment)
                return max(0, int((moment - last).total_seconds() // 86400))
            listed = sorted(carried, key=lambda row: (-unused(row), row.get('heading') or ''))
            oldest = sorted((row for row in carried if row['_id'] != pending.get('keep')),
                            key=lambda row: (bool(row.get('felt')), row.get('memorable_at') or '', row['_id']))[0]
            lines.append(OVER_LINE % (STORE_WORDS.get(pending['store'], pending['store']), len(carried), cap,
                                      '；'.join('「%s」%d 天没用到' % (row.get('heading') or row['sid'], unused(row))
                                               for row in listed),
                                      oldest.get('heading') or oldest['sid']))
            self.rows.update_one({'_id': pending['_id']}, {'$addToSet': {'shown_in': scene_id}})
        return lines

    # ── her writes ─────────────────────────────────────────────────
    def _gist_rewrite(self, slug, intent, old, new):
        """The row, when this write is the gist step: a short rewrite of an item listed for its gist (its basis lines
        not counted; one that dropped the basis was refused before it was written, gist_refusal). It keeps the
        verbatim behind it and stays where it is."""
        sid = intent.get('sid')
        if intent.get('op') != 'replace_section' or sid not in old or sid not in new:
            return None
        row = self.item(slug, sid)
        gist = (row or {}).get('gist') or {}
        if (row and old[sid].get('body_sha256') != new[sid].get('body_sha256') and gist.get('listed')
                and not gist.get('done') and claim_chars(new[sid].get('body') or '') <= GIST_CHARS):
            return row
        return None

    def placement_after(self, slug, intent, before, after):
        """Where a write leaves each section it moves, {sid: [(place, reason), ...]} in order, the last one the place it
        ends in: the one rule for the write (written) and for the gate that measures it first (carried.gate). Her
        write: a new section starts carried (a running record's at hand) unless she wrote it tucked away; a correction
        puts away what it corrects; a rewrite that changed an item brings it back to carried (not the gist step); a
        tag that tucks a section away is her let_go, and a tag never lifts one. Anything else (a seed adopted, an
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
            if op == 'correction' and new[sid].get('corrects') in old:
                plan[new[sid]['corrects']] = [(PUT_AWAY, 'superseded')]
        if self._gist_rewrite(slug, intent, old, new):
            return plan
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

    def written(self, slug, intent, before, after, *, scene_id=None, felt=False, moment=None, before_revision=None):
        """After one of her document writes, the moves placement_after gives, made: a new item starts carried (a
        running record's at hand), a rewrite that changed an item starts its stay again from carried, a correction
        supersedes the item it corrects. A group's notes refold. Returns the moves a reader should be told of (an
        overflow names what it lapsed)."""
        moment = moment or _now()
        kind = store_of(slug, (after or {}).get('kind'))
        if not kind:
            return []
        self.sync(moment)                        # rows for anything not seen yet (her other documents too)
        old = {s['sid']: s for s in (before or {}).get('sections') or []}
        new = {s['sid']: s for s in (after or {}).get('sections') or []}
        op, moves = intent.get('op'), []
        start = AT_HAND if kind == 'journal' else CARRIED
        plan = self.placement_after(slug, intent, before, after)
        for sid in [sid for sid in new if sid not in old]:
            # Encoding: what she just wrote is fresh in mind, unless she wrote it tucked away herself.
            row = self.item(slug, sid) or self._new(slug, sid, kind, new[sid], start, moment)
            self.rows.update_one({'_id': row['_id']}, {'$set': {
                'place': (plan.get(sid) or [(row['place'], None)])[-1][0], 'heading': new[sid].get('heading') or sid,
                'visibility': new[sid].get('visibility'),
                **({'scene_id': scene_id} if scene_id else {}), **({'felt': True} if felt else {})}})
            if self.item(slug, sid)['place'] == CARRIED:
                moves += self._overflow(slug, kind, row['_id'], moment)
            if op == 'correction' and new[sid].get('corrects') in old:
                corrected = self.item(slug, new[sid]['corrects'])
                if corrected:
                    moves.append(self.move(corrected, PUT_AWAY, 'superseded', moment, scene_id=scene_id))
        declared = declared_nature(intent)
        if declared:
            # What she says an item is, or where it came from, when she writes or tags it.
            for sid in ([sid for sid in new if sid not in old] if op in ('append_section', 'correction')
                        else [intent.get('sid')] if intent.get('sid') in new else []):
                self.rows.update_one({'_id': item_id(self.persona, slug, sid)}, {'$set': declared})
        sid = intent.get('sid')
        if op == 'replace_section' and sid in old and sid in new:
            row = self.item(slug, sid)
            changed = old[sid].get('body_sha256') != new[sid].get('body_sha256')
            if self._gist_rewrite(slug, intent, old, new):
                body = new[sid].get('body') or ''
                self.rows.update_one({'_id': row['_id']}, {'$set': {
                    'gist.done': _iso(moment), 'detail_of': {'revision_id': before_revision,
                                                             'body_sha256': old[sid].get('body_sha256')},
                    'body_sha256': new[sid].get('body_sha256'), 'chars': len(body)}})
                self._refold(slug, kind, after)
                return [move for move in moves if move]
            if row:
                self.rows.update_one({'_id': row['_id']}, {'$set': {
                    'heading': new[sid].get('heading') or sid, 'visibility': new[sid].get('visibility'),
                    'body_sha256': new[sid].get('body_sha256'), 'chars': len(new[sid].get('body') or '')}})
            if row and changed:
                self.memorable(row, 'rewritten', moment, scene_id=scene_id)
                self.rows.update_one({'_id': row['_id']}, {'$set': {'rewritten_at': _iso(moment)}})
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
        self.rows.update_one({'_id': 'fold:%s:%s' % (self.persona, slug)}, {'$set': {
            'row': 'fold', 'persona': self.persona, 'doc': slug, 'order': order, 'at': _iso(moment or _now())}},
            upsert=True)
        return order

    def folding(self, slug, content):
        """The kept fold order of a group's notes, made once when there is none."""
        row = self.rows.find_one({'_id': 'fold:%s:%s' % (self.persona, slug)}, {'order': 1})
        return row['order'] if row else self.refold(slug, content)

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
                    self.rows.update_one({'_id': row['_id']}, {'$addToSet': {'recalled_in': scene_id},
                                                               '$set': {'recalled_at': _iso(moment or _now())}})
                self.memorable(row, why, moment, scene_id=scene_id)

    def surfaced(self, refs, scene_id, moment=None):
        """Items a turn surfaced: memorable only when a second, different conversation brings one up."""
        for doc, sid in refs:
            row = self.item(doc, sid)
            if not row:
                continue
            seen = set(row.get('surfaced_in') or [])
            self.rows.update_one({'_id': row['_id']}, {'$addToSet': {'surfaced_in': scene_id},
                                                       '$set': {'last_use_at': _iso(moment or _now())}})
            if scene_id not in seen and seen:
                self.memorable(row, 'surfaced_again', moment, scene_id=scene_id)

    # ── what she reads each turn ───────────────────────────────────
    def things(self, cls, scene, zone, moment=None, *, home=False, readable_docs=None):
        """things_from_program: her items by store and place in words, and the moves since this conversation was
        last told, each once, with its clock time. A home turn is offered the split of current_self until `self`
        exists."""
        from . import visibility
        from .schedule_rules import line_stamp
        moment = moment or _now()

        def here(row):
            if not visibility.readable(row.get('visibility') or 'public', cls):
                return False
            if row['store'] == 'group_notes':
                return readable_docs is not None and row['doc'] in readable_docs
            return True
        counts, docs = {}, {}
        for row in self.items():
            if here(row):
                counts.setdefault(row['store'], {CARRIED: 0, AT_HAND: 0, PUT_AWAY: 0})[row['place']] += 1
                docs.setdefault(row['store'], set()).add(row['doc'])

        def room(kind):
            # Measured as the cap is (_overflow): all its carried items, per document where the cap is per document,
            # the tightest one this turn reads.
            return min(CAPS[kind] - len(self._carried(doc, kind)) for doc in docs[kind]) if kind in self.PER_DOC \
                else CAPS[kind] - len(self._carried(None, kind))
        places = {STORE_WORDS[kind]: '、'.join(
            '%s %s' % (place, words(ROOM_WORDS, max(0, room(kind))) if place == CARRIED and kind in CAPS
                       else words(COUNT_WORDS, n)) for place, n in tally.items())
                  for kind, tally in sorted(counts.items())}
        moves = [move for move in self.rows.find({'row': 'move', 'persona': self.persona,
                                                  'told_in': {'$ne': scene['_id']}}).sort('at', -1)
                 if here(move)][:MOVED_SHOWN]
        block = {'places': places}
        from .carried import room_block
        room = room_block(self.store, self.persona, cls, scene['_id'])
        if room:
            block['identity_room'] = room
        over = self.overflows(here, scene['_id'], moment)
        if over:
            block['over'] = over
        if moves:
            block['moved'] = ['%s %s' % (line_stamp(zone, move['at']), told(move)) for move in reversed(moves)]
            self.rows.update_many({'_id': {'$in': [move['_id'] for move in moves]}},
                                  {'$addToSet': {'told_in': scene['_id']}})
        if home and not self.rows.find_one({'row': 'item', 'persona': self.persona, 'doc': SELF_DOC}):
            block['self_items'] = SELF_OFFER
        return block


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


def gist_refusal(row, verbatim, body):
    """Why her rewrite may not be taken as the gist of a listed item, or None: it keeps the claim and drops the basis
    its verbatim had (her rule: a claim without its basis is loss, not fading)."""
    gist = (row or {}).get('gist') or {}
    if not gist.get('listed') or gist.get('done') or claim_chars(body or '') > GIST_CHARS:
        return None
    had = has_basis(verbatim or '') or (row or {}).get('from')
    if had and not has_basis(body or '') and len((body or '').splitlines()) < 2:
        return GIST_NO_BASIS % ((row or {}).get('from') or '原文里写着')
    return None


def claim_chars(text):
    """A gist's length without its basis lines: the basis is never what the 160 characters squeeze out."""
    return len('\n'.join(line for line in text.splitlines() if not has_basis(line)).strip())


def has_basis(text):
    return any(word in text for word in BASIS)


def declared_nature(intent):
    """The nature and source she gave a write ({} when neither): her word for the nature wins over the source's."""
    source = intent.get('from') if intent.get('from') in FROM_NATURE else None
    nature = intent.get('nature') if intent.get('nature') in NATURES else FROM_NATURE.get(source)
    if not nature:
        return {}
    return {'nature': nature, 'fact': nature == FACT, **({'from': source} if source else {})}


def told(move):
    """A move as her result or the moved line says it, in words."""
    return '「%s」%s→%s（%s）' % (move.get('heading') or move['sid'], move['from'], move['to'],
                               REASONS.get(move['reason'], move['reason']))


def night_list(store, persona, moment=None, *, excerpt_chars=600):
    """The night list (settlement, ADR-062 §4.2 step 8): at most NIGHT_ITEMS, chosen by rule and each told why, none of
    them a keep or drop choice: lapsed long or dated items waiting for their gist (写一句意思), items met in different
    conversations (几处都提到: what it is is hers to say), near-duplicate pairs in one store (合并, mandatory for facts),
    and once a week one put-away item with past uses (回头看). An item listed for its gist twice and not rewritten goes
    put away as it is. Returns None when nothing is due."""
    from .config import excerpt
    from .documents import DocumentStore
    moment = moment or _now()
    tiers = Tiers(store, persona)
    docs = DocumentStore(store, persona)
    night = moment.date().isoformat()
    bodies = {}

    def body(row):
        key = (row['doc'], row['sid'])
        if key not in bodies:
            content = docs.read(row['doc'])[1] or {}
            for section in content.get('sections') or []:
                bodies[(row['doc'], section['sid'])] = section.get('body') or ''
        return bodies.get(key, '')

    def entry(kind, row, why):
        text = body(row)
        return {'what': NIGHT_WHAT[kind], 'ref': ref(row['doc'], row['sid']), 'heading': row.get('heading'),
                'store': STORE_WORDS[row['store']], 'nature': row.get('nature') or (FACT if row.get('fact') else MEMORY),
                'why': why, 'body': excerpt(text, excerpt_chars)}
    items, offered = [], []
    # 写一句意思: lapsed down from carried, long or dated, no gist yet.
    for row in tiers.items(place=AT_HAND):
        gist = row.get('gist') or {}
        if gist.get('done'):
            continue
        lapsed = tiers.rows.find_one({'row': 'move', 'item': row['_id'], 'from': CARRIED, 'to': AT_HAND,
                                      'reason': {'$in': ['stay', 'overflow']}})
        text = body(row) if lapsed else ''
        # Her answer: an item of 160 characters or fewer is already short and never appears on the list.
        if not lapsed or len(text) <= GIST_CHARS or not (len(text) > GIST_LIST_ABOVE or DATED.search(text)):
            continue
        if gist.get('skipped'):
            continue
        if len(gist.get('nights') or []) >= GIST_NIGHTS and night not in gist['nights']:
            if row.get('fact'):
                # A fact never goes put away by disuse: its verbatim stays at hand, no longer listed.
                tiers.rows.update_one({'_id': row['_id']}, {'$set': {'gist.skipped': _iso(moment)}})
            else:
                tiers.move(row, PUT_AWAY, 'gist_skipped', moment)
            continue
        items.append(('gist', entry('gist', row, NIGHT_WHY['gist']), [row]))
    # 合并: near-duplicate pairs in one store (the item index's pairs), facts first.
    rows = {(row['doc'], row['sid']): row for row in tiers.items(place={'$in': [CARRIED, AT_HAND]})}
    shadow = {row['_id']: (row.get('doc'), row.get('sid')) for row in store.db['memory_shadow'].find(
        {'row': 'item', 'status': 'active'}, {'doc': 1, 'sid': 1})}
    pairs = []
    for pair in store.db['memory_shadow'].find({'row': 'pair', 'score': {'$gte': DUPLICATE_SCORE}}):
        a, b = (rows.get(shadow.get(key)) for key in pair['items'])
        if a and b and a['store'] == b['store'] and a['doc'] == b['doc']:
            pairs.append((not a.get('fact'), a, b))
            elsewhere = a.get('scene_id') and b.get('scene_id') and a['scene_id'] != b['scene_id']
            for row, other in ((a, b), (b, a)):
                if elsewhere and (row.get('last_moment') != 'duplicate_elsewhere'
                                  or (row.get('memorable_at') or '')[:10] != night):
                    tiers.memorable(row, 'duplicate_elsewhere', moment)       # met again from another conversation
                if elsewhere or other.get('from') in OTHERS_SAID:
                    # The same from someone else confirms a judgment of hers: it may now be made a fact.
                    tiers.rows.update_one({'_id': row['_id']}, {'$set': {'confirmed': _iso(moment)}})
    for _, a, b in sorted(pairs, key=lambda p: (p[0], p[1]['_id'])):
        merged = entry('merge', a, NIGHT_WHY['merge'])
        merged['what'] = NIGHT_WHAT['merge']
        merged['with'] = {k: v for k, v in entry('merge', b, '').items() if k in ('ref', 'heading', 'body')}
        items.append(('merge_fact' if a.get('fact') else 'merge', merged, [a, b]))
    # 几处都提到: a memory met in different conversations, or carried unchanged through several stays.
    week = (moment - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    for row in tiers.items():
        if row.get('fact') or row['store'] == 'core' or row.get('superseded_at'):
            continue
        places = set(row.get('surfaced_in') or []) | set(row.get('recalled_in') or [])
        if len(places) < REPEATED_PLACES and int(row.get('stays') or 0) < REPEATED_STAYS:
            continue
        if tiers.rows.find_one({'row': 'offer', 'item': row['_id'], 'what': 'repeated', 'at': {'$gte': week}}):
            continue
        items.append(('repeated', entry('repeated', row, NIGHT_WHY['repeated']), [row]))
    order = {'gist': 0, 'merge_fact': 1, 'merge': 2, 'repeated': 3}
    items = sorted(items, key=lambda item: order[item[0]])[:NIGHT_ITEMS]
    if not items:
        return None
    for kind, _, rows_ in items:
        for row in rows_:
            what = 'gist' if kind == 'gist' else 'merge' if kind.startswith('merge') else kind
            tiers.rows.update_one({'_id': 'offer:' + sha(canonical([row['_id'], what, night]))[:32]}, {'$setOnInsert': {
                'row': 'offer', 'persona': persona, 'item': row['_id'], 'what': what, 'night': night,
                'at': _iso(moment)}}, upsert=True)
            if kind == 'gist':
                tiers.rows.update_one({'_id': row['_id']}, {'$set': {'gist.listed': True},
                                                            '$addToSet': {'gist.nights': night}})
    def how(kind, rows_):
        if kind != 'repeated':
            return NIGHT_HOW[kind]
        # 记成事实 only for what someone else decided or she checked, or a judgment someone confirmed.
        row = rows_[0]
        signed = row.get('from') in FACT_AUTHORS or (row.get('from') == OWN_JUDGMENT and row.get('confirmed'))
        return NIGHT_HOW['repeated'] % ('、记成事实（set_tags nature=事实）' if signed else '')
    return {'items': [dict(value, how=how(kind, rows_)) for kind, value, rows_ in items]}


ABOUT = ('self', 'person', 'place', 'world')


def recalled(store, window_days, moment=None):
    """{memory id: [episode ids]} for memories she recalled herself (`recall.read`) in at least two different
    conversations within the window: promotion's candidates come from her acts, not from what she was shown."""
    moment = moment or _now()
    since = (moment - timedelta(days=float(window_days or 7))).isoformat()
    seen = {}
    for row in store.db.audit_events.find({'type': 'recall.read', 'occurred_at': {'$gte': since}},
                                          {'stream_id': 1, 'scope_key': 1, 'payload.memories': 1}):
        for memory_id in (row.get('payload') or {}).get('memories') or []:
            if isinstance(memory_id, str) and not memory_id.startswith('doc:'):
                entry = seen.setdefault(memory_id, ({}, set()))
                entry[0][row['stream_id']] = True
                entry[1].add(row.get('scope_key'))
    return {key: list(episodes) for key, (episodes, scopes) in seen.items() if len(scopes) >= 2}


def candidates(store, window_days, limit=20):
    """promotion_candidates with tiered memory on: what she recalled in different conversations."""
    picked = recalled(store, window_days)
    rows = {row['_id']: row for row in store.db.memory_units.find({'_id': {'$in': list(picked)}, 'status': 'active'},
                                                                 {'body_markdown': 1, 'kind': 1})}
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
        scenes = {row.get('scene_id') for row in store.db.episodes.find({'_id': {'$in': list(episodes)}}, {'scene_id': 1})}
        groups = [scene for scene in store.db.scenes.find({'_id': {'$in': list(scenes)}}, {'kind': 1})
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
    # What it adds is carried: the same gate as her own writes (ADR-096).
    docs.apply(slug, intent, body, base_revision_id=before[0], author='character',
               mutation_id='%s:promote:%s' % (ep['_id'], sha(canonical(item))[:16]),
               budget=budget_gate(store, ep['persona']))
    after = docs.read(slug)[1]
    sid = after['sections'][-1]['sid']
    Tiers(store, ep['persona']).written(slug, {**intent, 'nature': FACT}, before[1], after, scene_id=ep.get('scene_id'),
                                        before_revision=before[0])
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
    moment = moment or _now()
    tiers = Tiers(store, persona)
    since = (moment - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    if tiers.rows.find_one({'row': 'offer', 'persona': persona, 'what': 'week', 'at': {'$gte': since}}):
        return None
    left = []
    for move in tiers.rows.find({'row': 'move', 'persona': persona, 'from': CARRIED, 'at': {'$gte': since}}).sort('at', 1):
        row = tiers.rows.find_one({'_id': move['item']}) or {}
        again = (row.get('recalled_at') or '') >= move['at']      # same instant counts: a coarse clock ties them
        left.append('%s「%s」放到了%s（%s）；之后你%s' % (line_stamp(zone, move['at']), move.get('heading') or move['sid'],
                                                    move['to'], REASONS.get(move['reason'], move['reason']),
                                                    'recall 过它' if again else '没再 recall 它'))
    block = {'left': left or ['这一周没有东西从随身放下。']}
    week_id = moment.isocalendar()[:2]
    away = sorted(tiers.items(place=PUT_AWAY), key=lambda row: sha(canonical([list(week_id), row['_id']])))
    if away:
        row = away[0]
        content = DocumentStore(store, persona).read(row['doc'])[1] or {}
        text = next((s.get('body') for s in content.get('sections') or [] if s['sid'] == row['sid']), None)
        if text:
            block['put_away'] = {'ref': ref(row['doc'], row['sid']), 'heading': row.get('heading'),
                                 'text': excerpt(text, WEEK_TEXT_CHARS)}
    changed = [row.get('heading') or row['sid'] for row in tiers.items() if (row.get('rewritten_at') or '') >= since]
    block['changed'] = ('这周你改过：' + '、'.join('「%s」' % name for name in changed)) if changed else '这周你没改过哪一条。'
    tiers.rows.update_one({'_id': 'offer:week:%s:%d-%d' % (persona, *week_id)}, {'$setOnInsert': {
        'row': 'offer', 'persona': persona, 'what': 'week', 'at': _iso(moment)}}, upsert=True)
    return block


def detail(store, persona, row):
    """The verbatim a gist stands for (its revision before the gist), or None."""
    behind = (row or {}).get('detail_of') or {}
    if not behind:
        return None                     # not a gist (or no item at all, as for a working document): nothing behind
    revision = store.db.state_revisions.find_one({'_id': behind.get('revision_id')}) if behind.get('revision_id') else None
    for section in ((revision or {}).get('content') or {}).get('sections') or []:
        if section.get('sid') == row['sid']:
            return section.get('body')
    old = store.db.journal_revisions.find_one({'persona': persona, 'slug': row['doc'], 'sid': row['sid'],
                                               'body_sha256': behind.get('body_sha256')}) if behind else None
    if old:
        return old.get('body')
    for change in store.db.journal_revisions.find({'persona': persona, 'slug': row['doc'], 'sid': row['sid']}).sort(
            'created_at', -1):
        if sha((change.get('body') or '').encode()) == behind.get('body_sha256'):
            return change.get('body')
    return None


def placed(store, persona, slug, content, override=None):
    """A document's sections as the turn reads them when the switch is on; unchanged when it is off."""
    return Tiers(store, persona).placed(slug, content, override) if ENABLED else content


def deliver(store, persona, pilot, retrieval, query, readable, scene_id, *, recall=False, moment=None,
            excerpt_chars=800):
    """Her own items a turn brings up by itself (手边; a recall also reaches 收着), scored as memories are, at most
    OWN_SLOTS above FLOOR, as memory entries with their store, place and age words and a doc ref. What is carried
    (随身) is already in front of her and is never brought up again, except a group-notes section folded to its
    heading this turn (ADR-096), which comes up labelled as carried and folded. Each one surfaced is marked: recalled,
    or surfaced in this conversation. Returns (the entries, the refs of carried items the turn would have brought up
    had they not been carried: the program's score for what she carries)."""
    from .config import excerpt
    from .memory_pilot import admitted, rank
    items = list(getattr(pilot, 'items', None) or [])
    if not items:
        return [], []
    tiers = Tiers(store, persona)
    rows = {(row['doc'], row['sid']): row for row in tiers.items()}
    allowed = (AT_HAND, PUT_AWAY) if recall else (AT_HAND,)
    from .group_admin import folded as _folded
    folded = {(doc, sid) for doc in {item['doc'] for item in items if item['store'] == 'group_notes'
                                     and item['scope_key'] in readable}
              for sid in _folded(store, persona, doc)}

    def tier(item):
        return (rows.get((item['doc'], item['sid'])) or {}).get('place')

    def is_folded(item):
        return tier(item) == CARRIED and (item['doc'], item['sid']) in folded
    readable_items = [item for item in items if item['scope_key'] in readable and tier(item)]
    pool = [item for item in readable_items if tier(item) in allowed or is_folded(item)]
    carried = [item for item in readable_items if tier(item) == CARRIED and not is_folded(item)]
    if not pool and not carried:
        return [], []
    vector = retrieval.query_vector(query) or retrieval.embed([query], 'query')[0]
    moment = moment or _now()
    would = []
    if carried and not recall:
        # A carried item is never brought up (it is in front of her), so it cannot show use that way: one the turn
        # would have brought up above the floor, had it not been carried, is used in this conversation.
        order, scores, _ = rank(pool + carried, query, vector)
        above = admitted([(key, scores[key]) for key in order], FLOOR, OWN_SLOTS)
        hits = [(item['doc'], item['sid']) for item in carried if item['key'] in above]
        tiers.surfaced(hits, scene_id, moment)
        would = [ref(*hit) for hit in hits]
    if not pool:
        return [], would
    order, scores, _ = rank(pool, query, vector)
    by_key = {item['key']: item for item in pool}
    out, refs = [], []
    for key in admitted([(key, scores[key]) for key in order], FLOOR, OWN_SLOTS):
        item, row = by_key[key], rows[(by_key[key]['doc'], by_key[key]['sid'])]
        out.append({'_id': ref(item['doc'], item['sid']), 'kind': 'own_item', 'heading': item.get('heading') or row['heading'],
                    'body_markdown': excerpt(item['text'], excerpt_chars), 'store': STORE_WORDS[row['store']],
                    'place': FOLDED if is_folded(item) else row['place'],
                    'age': FACT if row.get('fact') else age_word(row.get('added'), moment)})
        refs.append((item['doc'], item['sid']))
    if refs:
        tiers.used(refs, 'recalled', scene_id) if recall else tiers.surfaced(refs, scene_id)
    return out, would


def headings(store, persona, pilot, query, readable, cls, shown=()):
    """recall: the headings of her items at hand or put away that match the question, beyond the bodies it returns."""
    from . import visibility
    from .retrieval import terms
    wanted = terms(query)
    rows = {(row['doc'], row['sid']): row for row in Tiers(store, persona).items(place={'$in': [AT_HAND, PUT_AWAY]})}
    texts = {(item['doc'], item['sid']): (item['scope_key'], item['lexical']) for item in getattr(pilot, 'items', None) or []}
    found = []
    for key, row in rows.items():
        if ref(*key) in shown or not visibility.readable(row.get('visibility') or 'public', cls):
            continue
        scope, text = texts.get(key, (None, row.get('heading') or ''))
        if scope is not None and scope not in readable:
            continue
        hits = len(wanted & terms(text))
        if hits >= min(2, len(wanted)) and hits:
            found.append((-hits, row['heading'], {'ref': ref(*key), 'heading': row['heading'],
                                                  'store': STORE_WORDS[row['store']], 'place': row['place']}))
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
