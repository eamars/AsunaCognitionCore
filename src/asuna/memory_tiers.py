"""Tiered memory (ADR-062): where each of her items lives, kept up by what is memorable, moved down by the program.

Every section of her persona, voice, ledgers, group notes, running records and the `self` and `core` documents is an
item. The program never rewrites an item's text; beside it, in the collection `memory_tiers` (rows `item`), it keeps
the item's place (随身 carried in every turn where it is readable, 手边 at hand: found by a turn about it or by
`recall`, 收着 put away: found by `recall` only), when it was last memorable and its stay. A 随身 item lapses to 手边
when its stay runs out; each memorable moment (recall returned it, a rewrite that changed it, its `doc:` ref cited, a
second conversation it came up in, a correction touching it) starts the stay again and, once per stay, doubles the
next. A store over its count cap lapses its least recently memorable item. Memories (`self`, running records) cool to
收着 by disuse; facts (persona, voice, ledgers, group notes, `core`) never do: a correction or a merge supersedes
them. Every move is one row `move` and one audit line `memory.moved`, and is told once in each conversation that can
read the item (`things_from_program`). She reads all of it as words from the tables below.

`ENABLED` is the switch; off, nothing here is read or written and her turns are as before.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .evidence import canonical, sha

TIERS_VERSION = 1
ENABLED = False                    # the switch (ADR-062 phase 2): hers and the owner's to turn on
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
FACTS = ('persona', 'voice', 'ledger', 'group_notes', 'core')       # stores whose items are facts unless she says
MEMORIES = ('self', 'journal')
FACT, MEMORY = '事实', '记忆'
NATURES = (FACT, MEMORY)
FROM_NATURE = {'主人定的': FACT, '查过的': FACT, '别人说的': MEMORY, '我自己的判断': MEMORY}
SOURCES = tuple(FROM_NATURE)
CAPS = {'self': 12, 'persona': 16, 'ledger': 10, 'group_notes': 6, 'core': 12, 'voice': 6}
FIRST_STAY_DAYS = {'group_notes': 28, 'core': 56, 'voice': 56}
STAY_DAYS, STAY_CAP_DAYS = 14, 56
JOURNAL_COOL_DAYS = 30
AGE_WORDS = ((1, '刚写的'), (7, '这几天'), (14, '上周'), (45, '上个月'), (None, '更早'))
COUNT_WORDS = ((0, '没有'), (3, '几条'), (9, '好几条'), (19, '十几条'), (99, '几十条'), (None, '很多条'))
REASONS = {'stay': '一阵子没用到', 'overflow': '随身满了', 'cooled': '很久没用', 'let_go': '你放手了',
           'superseded': '被更正替换', 'merged': '合并了', 'gist_skipped': '两晚没写意思', 'rewritten': '你改写了它',
           'surprise': '被更正碰到了'}
MOVED_SHOWN = 5
# A tag never carries an item back (no pin, owner 2026-10-13): only a memorable moment or a changed rewrite does.
NOT_BACK = ('inject 改成 always 不会把它带回随身：它再被用到、被你改写出变化、或被更正碰到，才会回来；'
            '现在它在%s。')
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
        on_demand 手边, never 收着) with a fresh stay: nothing lapses on the day the switch goes on."""
        from .documents import DocumentStore
        moment = moment or _now()
        docs = DocumentStore(self.store, self.persona)
        known = {(row['doc'], row['sid']) for row in self.rows.find({'row': 'item', 'persona': self.persona},
                                                                     {'doc': 1, 'sid': 1})}
        for slug in docs.slugs():
            content = docs.read(slug)[1] or {}
            kind = store_of(slug, content.get('kind'))
            if not kind:
                continue
            for section in content.get('sections') or []:
                if (slug, section['sid']) in known:
                    continue
                place = FROM_INJECT.get(section.get('inject'), AT_HAND)
                self._new(slug, section['sid'], kind, section, AT_HAND if kind == 'journal' and place == CARRIED
                          else place, moment)

    def placed(self, slug, content):
        """A document as the turn reads it: each section's `inject` follows its place (a copy; the text untouched)."""
        if not content or not content.get('sections'):
            return content
        places = {row['sid']: row['place'] for row in self.rows.find(
            {'row': 'item', 'persona': self.persona, 'doc': slug}, {'sid': 1, 'place': 1})}
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
        move = {'_id': 'move:' + sha(canonical([row['_id'], row['place'], to, _iso(moment)]))[:32], 'row': 'move',
                'persona': self.persona, 'item': row['_id'], 'doc': row['doc'], 'sid': row['sid'],
                'heading': row.get('heading'), 'store': row['store'], 'visibility': row.get('visibility'),
                'from': row['place'], 'to': to, 'reason': reason, 'at': _iso(moment), 'told_in': []}
        self.rows.update_one({'_id': move['_id']}, {'$setOnInsert': move}, upsert=True)
        self.store.audit('memory:' + self.persona, 'memory.moved', {'item': row['_id'], 'doc': row['doc'],
                         'sid': row['sid'], 'from': row['place'], 'to': to, 'reason': reason,
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
        """A memorable moment: the stay starts again from now and, once per stay, the next one doubles. A surprise
        brings an item put away back to hand."""
        moment = moment or _now()
        fields = {'memorable_at': _iso(moment), 'last_use_at': _iso(moment), 'last_moment': why}
        if not row.get('doubled'):
            fields.update(stay_days=min(STAY_CAP_DAYS, float(row.get('stay_days') or STAY_DAYS) * 2), doubled=True)
        self.rows.update_one({'_id': row['_id']}, {'$set': fields, '$inc': {'uses': 1}})
        if why == 'surprise' and row['place'] == PUT_AWAY:
            self.move(row, AT_HAND, 'surprise', moment, scene_id=scene_id)

    def _overflow(self, doc, kind, keep, moment):
        """A store over its cap lapses its least recently memorable item (felt ones last); the moves made."""
        cap = CAPS.get(kind)
        carried = self.items(doc=doc, place=CARRIED) if kind in ('ledger', 'group_notes', 'self', 'core') \
            else self.items(store=kind, place=CARRIED)
        if not cap or len(carried) <= cap:
            return []
        order = sorted((row for row in carried if row['_id'] != keep),
                       key=lambda row: (bool(row.get('felt')), row.get('memorable_at') or '', row['_id']))
        return [move for move in (self.move(row, AT_HAND, 'overflow', moment) for row in order[:len(carried) - cap])
                if move]

    # ── her writes ─────────────────────────────────────────────────
    def written(self, slug, intent, before, after, *, scene_id=None, felt=False, moment=None):
        """After one of her document writes: a new item starts carried (a running record's at hand), a rewrite
        that changed an item starts its stay again from carried, a correction supersedes the item it corrects.
        Returns the moves a reader should be told of (an overflow names what it lapsed)."""
        moment = moment or _now()
        kind = store_of(slug, (after or {}).get('kind'))
        if not kind:
            return []
        self.sync(moment)                        # rows for anything not seen yet (her other documents too)
        old = {s['sid']: s for s in (before or {}).get('sections') or []}
        new = {s['sid']: s for s in (after or {}).get('sections') or []}
        op, moves = intent.get('op'), []
        start = AT_HAND if kind == 'journal' else CARRIED
        for sid in [sid for sid in new if sid not in old]:
            # Encoding: what she just wrote is fresh in mind, unless she wrote it tucked away herself.
            row = self.item(slug, sid) or self._new(slug, sid, kind, new[sid], start, moment)
            told = FROM_INJECT.get(intent.get('inject'))
            self.rows.update_one({'_id': row['_id']}, {'$set': {
                'place': told if told and DEPTH[told] > DEPTH[start] else start, 'heading': new[sid].get('heading') or sid, 'visibility': new[sid].get('visibility'),
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
        if op == 'replace_section' and intent.get('sid') in old and intent['sid'] in new:
            sid = intent['sid']
            row = self.item(slug, sid)
            changed = old[sid].get('body_sha256') != new[sid].get('body_sha256')
            if row:
                self.rows.update_one({'_id': row['_id']}, {'$set': {
                    'heading': new[sid].get('heading') or sid, 'visibility': new[sid].get('visibility'),
                    'body_sha256': new[sid].get('body_sha256'), 'chars': len(new[sid].get('body') or '')}})
            if row and changed:
                self.memorable(row, 'rewritten', moment, scene_id=scene_id)
                if start == CARRIED and row['place'] != CARRIED:
                    moves.append(self.move(self.item(slug, sid), CARRIED, 'rewritten', moment, scene_id=scene_id))
                    moves += self._overflow(slug, kind, row['_id'], moment)
        if intent.get('inject') in FROM_INJECT and intent.get('sid') in new and op in ('set_tags', 'replace_section'):
            # Tucking a section away is letting it go, a move down she makes herself. A tag never moves one up.
            row = self.item(slug, intent['sid'])
            to = FROM_INJECT[intent['inject']]
            if row and DEPTH[to] > DEPTH[row['place']]:
                moves.append(self.move(row, to, 'let_go', moment, scene_id=scene_id))
        return [move for move in moves if move]

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
                    self.rows.update_one({'_id': row['_id']}, {'$addToSet': {'recalled_in': scene_id}})
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
        counts = {}
        for row in self.items():
            if here(row):
                counts.setdefault(row['store'], {CARRIED: 0, AT_HAND: 0, PUT_AWAY: 0})[row['place']] += 1
        places = {STORE_WORDS[kind]: '、'.join('%s %s' % (place, words(COUNT_WORDS, n)) for place, n in tally.items())
                  for kind, tally in sorted(counts.items())}
        moves = [move for move in self.rows.find({'row': 'move', 'persona': self.persona,
                                                  'told_in': {'$ne': scene['_id']}}).sort('at', -1)
                 if here(move)][:MOVED_SHOWN]
        block = {'places': places}
        if moves:
            block['moved'] = ['%s %s' % (line_stamp(zone, move['at']), told(move)) for move in reversed(moves)]
            self.rows.update_many({'_id': {'$in': [move['_id'] for move in moves]}},
                                  {'$addToSet': {'told_in': scene['_id']}})
        if home and not self.rows.find_one({'row': 'item', 'persona': self.persona, 'doc': SELF_DOC}):
            block['self_items'] = SELF_OFFER
        return block


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


def placed(store, persona, slug, content):
    """A document's sections as the turn reads them when the switch is on; unchanged when it is off."""
    return Tiers(store, persona).placed(slug, content) if ENABLED else content


DOC_REF = re.compile(r'doc:([^#\s"\'，。、]+)#([^\s"\'，。、）)]+)')


def refs_in(value):
    """The `doc:slug#sid` refs anywhere in a tool call's arguments."""
    import json
    return sorted(set(DOC_REF.findall(json.dumps(value, ensure_ascii=False))))
