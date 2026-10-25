"""What a turn may carry on its own, and how her own notes stay short (owner 2026-10-06, ADR-014).

The program adds most of a turn's context by itself, so it also bounds it: a versioned table of limits for each
block it adds, a ceiling for what a turn sends (applied by the Host to the notice it composes, `ceiling`, or here to a
context sent whole, `trim_turn`), and the words for how full her own notes are. Nothing is cut
silently and nothing is lost: what a turn leaves out is counted and said, and stays readable through recall.
Her notes are hers to tidy. Over its limit a group's notes fold the section that surfaced longest ago to its heading
first (a pinned one never folds), any other note shows its newest sections and names the rest; far over it, a note
takes no new text until she tidies it. Her nightly settlement lists the notes due for tidying.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

BUDGET_VERSION = 1

AFFECT_REASONS = 6                  # feelings shown with their reasons; unsettled ones always, weaker ones counted
NOTE_CHARS = {'group_notes': 2400, 'ledger': 4000}   # what one note shows each turn (headings and bodies)
NOTE_HARD_FACTOR = 2                # this many times its limit, a note takes no new text until she tidies it
SINGLE_BODY_CHARS = 4000            # her understanding of a person; her character core; her current self
TURN_CHARS = 48000                  # the whole turn context, as JSON characters
FOLDED_HEADINGS = 20                # headings named for the sections a note does not show
REVIEW_EVERY_DAYS = 7               # a changed note is due for tidying this long after the last time
REVIEW_PER_NIGHT = 3                # notes listed in one settlement
STICKER_SHELF = 60                  # stickers she keeps (ADR-016); her turn lists their names only
STICKER_REVIEW = 6                  # stickers listed for her weekly look at the shelf
MEMBER_LINES = 80                   # group members a turn names (group_members.py); find_member reaches the rest
CARRIED_CHARS = 12000               # the summary a new session carries from one that no longer fit (ADR-028)

# A group's notes over their limit (ADR-096): what folded, and when her pins alone are over it.
FOLD_LINE = ('这份笔记超过了每回合的上限：最久没被用到的 %d 节这里只列标题（还在：recall 读得到，聊到它时也会带出来）。'
             '整理一下就能都放进来。')
PINS_OVER = '置顶的节加起来就有 %d 字，超过了上限 %d 字：置顶的节照常都在，没置顶的都只列标题。'
PIN_NOTE = ('置顶了：笔记超过每回合上限时，这一节不折成标题，它仍算在 %d 字里。置顶不让它留在随身：一阵子没用到，'
            '它照样会放到手边，也照样占随身的名额（每个群的笔记随身最多 %d 条）。')
UNPIN_NOTE = '取消置顶了：笔记超长时，它和别的节一样按多久没用到折叠。'
# How full a note is, in words (share of its limit).
FULLNESS = ((0.5, '宽裕'), (0.8, '用了一大半'), (1.0, '快满了'), (None, '超了'))
# How long ago a feeling was stirred, in words coarse enough to stay the same for a while.
ROUGH_AGO = ((1, '一小时内'), (6, '几小时前'), (24, '一天之内'), (72, '这两三天'), (None, '更早'))
# Over the ceiling, these lists lose rows first, in this order: (block, list inside it or None, which end goes).
TRIM_ORDER = (('members_from_program', 'items', 'last'),
              ('recent_experience_from_program', 'messages', 'oldest'),
              ('settlement_from_program', 'promotion_candidates', 'last'),
              ('memories', None, 'last'),
              ('group_continuity_from_program', 'related_messages', 'oldest'),
              ('delivered_history', None, 'oldest'))
KEEP_HISTORY_ROWS = 4               # delivered_history never goes below this


def _tier(table, value):
    for bound, word in table:
        if bound is None or value < bound:
            return word
    return table[-1][1]


def fullness(chars, limit):
    return _tier(FULLNESS, chars / limit if limit else 0)


def rough_ago(hours):
    return _tier(ROUGH_AGO, max(hours, 0))


def size(value):
    return len(json.dumps(value, ensure_ascii=False))


# ---- her notes ---------------------------------------------------------------
def shown(sections):
    """The sections a note puts in front of her every turn: inject=always, not superseded by a correction."""
    corrected = {s['corrects'] for s in sections if s.get('corrects')}
    return [s for s in sections if s.get('inject', 'always') == 'always' and s['sid'] not in corrected]


def note_chars(sections):
    return sum(len(s.get('heading') or '') + len(s.get('body') or '') for s in shown(sections))


def _cost(section):
    return len(section.get('heading') or '') + len(section.get('body') or '')


def _fold(always, limit, order):
    """Over its limit, a group's notes fold by `order` (the section that surfaced longest ago first; one not in it
    folds last) until the rest fit; a pinned section never folds and still counts. Returns (kept, folded)."""
    from .config import excerpt
    rank = {sid: index for index, sid in enumerate(order)}
    candidates = sorted((s for s in always if not s.get('pinned')),
                        key=lambda s: (rank.get(s['sid'], len(rank)), always.index(s)))
    used, folded = sum(map(_cost, always)), []
    for section in candidates:
        if used <= limit:
            break
        folded.append(section)
        used -= _cost(section)
    gone = {s['sid'] for s in folded}
    kept = [s for s in always if s['sid'] not in gone]
    if not kept and folded:                         # the last one alone is over: show its start
        last = folded.pop()
        kept = [{**last, 'body': excerpt(last.get('body'), max(limit, 200))}]
    gone = {s['sid'] for s in folded}
    return kept, [s for s in always if s['sid'] in gone]


def note_view(sections, limit, order=None):
    """(sections to show, words about the note). Within its limit a note shows whole; over it, a group's notes fold
    by `order` (pins never fold), any other note shows the newest sections that fit, in their own order, and the
    rest by heading. A section is never cut inside."""
    from .config import excerpt
    always = shown(sections)
    total = note_chars(sections)
    about = {'fullness': fullness(total, limit)}
    kept = always
    if total > limit and order is not None:
        kept, folded = _fold(always, limit, order)
        about['not_shown'] = [{'sid': s['sid'], 'heading': s.get('heading') or s['sid']}
                              for s in folded[:FOLDED_HEADINGS]]
        about['over_limit'] = FOLD_LINE % len(folded)
        pins = sum(_cost(s) for s in always if s.get('pinned'))
        if pins > limit:
            about['pinned_over'] = PINS_OVER % (pins, limit)
    elif total > limit:
        kept, used = [], 0
        for section in reversed(always):
            cost = len(section.get('heading') or '') + len(section.get('body') or '')
            if used + cost > limit:
                if not kept:                          # the newest alone is over: show its start
                    kept.append({**section, 'body': excerpt(section.get('body'), max(limit - used, 200))})
                break
            kept.append(section)
            used += cost
        kept.reverse()
        folded = [s for s in always if s['sid'] not in {k['sid'] for k in kept}]
        about['not_shown'] = [{'sid': s['sid'], 'heading': s.get('heading') or s['sid']}
                              for s in folded[-FOLDED_HEADINGS:]]
        about['over_limit'] = ('这份笔记超过了每回合的上限：较早的 %d 节这里只列标题（还在，recall 能读）。'
                         '整理一下就能都放进来。' % len(folded))
    tucked = [s for s in sections if s.get('inject', 'always') != 'always']
    if tucked:
        about['tucked_away'] = '另有 %d 节收起了（when_shown 不是 always），不自动带上。' % len(tucked)
    return kept, about


def note_limit(slug, content):
    if slug.startswith('group:'):
        return NOTE_CHARS['group_notes']
    if (content or {}).get('kind') == 'ledger':
        return NOTE_CHARS['ledger']
    return None


def note_gate(slug, before, after):
    """Refuse growth of a note already far over its limit (DocumentStore.apply's budget hook, through carried.gate,
    which passes both as her turns carry them)."""
    from .documents import DocumentError
    limit = note_limit(slug, after)
    if not limit:
        return
    old, new = note_chars((before or {}).get('sections') or []), note_chars(after.get('sections') or [])
    if new > old and new > limit * NOTE_HARD_FACTOR:
        raise DocumentError('NOTE_OVER_LIMIT', '%s写完 %d 字，上限 %d 字，超过 %d 字就不能再加长'
                            % ('群笔记' if slug.startswith('group:') else '「%s」' % slug, new, limit,
                               int(limit * NOTE_HARD_FACTOR)))


# ---- the whole turn -----------------------------------------------------------
def trim_turn(context, limit=TURN_CHARS):
    """Drop the oldest list rows (TRIM_ORDER) until the turn fits; say what was left out. Returns the counts."""
    total = size(context)
    if total <= limit:
        return {}
    left = {}
    for block, inner, end in TRIM_ORDER:
        holder = context.get(block)
        rows = holder.get(inner) if inner and isinstance(holder, dict) else holder
        if not isinstance(rows, list):
            continue
        floor = KEEP_HISTORY_ROWS if block == 'delivered_history' else 0
        while len(rows) > floor and total > limit:
            row = rows.pop(0 if end == 'oldest' else -1)
            total -= size(row) + 1
            name = block + ('.' + inner if inner else '')
            left[name] = left.get(name, 0) + 1
        if total <= limit:
            break
    # Still over (one huge message, row or block): the longest text left is halved, again and again, keeping its
    # start and saying how much went; the original stays in the record (recall, history). Every cut must make the
    # turn shorter: a text already near SHORT_TEXT comes back as long with its note, and cutting it again forever
    # stopped her whole queue (10-13, a turn of many ~400-character texts). When the longest text cannot get
    # shorter, nothing else can either: the turn goes as it is, over the ceiling.
    shortened = 0
    while total > limit:
        found = _longest_text(context)
        if found is None:
            break
        holder, key, text = found
        keep = max(SHORT_TEXT, len(text) // 2)
        cut = text[:keep] + CUT_NOTE % (len(text) - keep)
        if len(cut) >= len(text):
            break
        holder[key] = cut
        total = size(context)
        shortened += 1
    if shortened:
        left['shortened_texts'] = shortened
    if left:
        context['trimmed_from_program'] = {'left_out': left, 'note': TRIMMED_NOTE}
    return left


SHORT_TEXT = 400                    # a text is never cut below this many characters
CUT_NOTE = '……（太长，后面 %d 字没列出；原文还在记录里，要看就 recall）'
TRIMMED_NOTE = '这回合的资料超过了上限，这些列表里较早的几条没列出、过长的文字截短了；要看原文就 recall。'


def ceiling():
    """The ceiling as the Host applies it to the notice it composes (context-delivery.js trimTurn): what is sent, not
    what is prepared, so a block she still sees never pushes another one's text under the knife."""
    return {'chars': TURN_CHARS, 'order': [list(row) for row in TRIM_ORDER], 'keep_history_rows': KEEP_HISTORY_ROWS,
            'short_text': SHORT_TEXT, 'cut_note': CUT_NOTE, 'note': TRIMMED_NOTE}


def _longest_text(node):
    """(holder, key, text) of the longest string value in a context block, or None."""
    best = None
    stack = [node]
    while stack:
        item = stack.pop()
        pairs = item.items() if isinstance(item, dict) else enumerate(item) if isinstance(item, list) else ()
        for key, value in pairs:
            if isinstance(value, str):
                if best is None or len(value) > len(best[2]):
                    best = (item, key, value)
            elif isinstance(value, (dict, list)):
                stack.append(value)
    return best


def carried_block(summary):
    """What the first notice of a session that replaced one that no longer fit the model's window says (ADR-028)."""
    text = (summary or '').strip()
    if len(text) > CARRIED_CHARS:
        text = text[:CARRIED_CHARS] + CUT_NOTE % (len(text) - CARRIED_CHARS)
    if not text:
        return {'note': '之前那段会话太长，模型装不下了，程序换了这个新会话接着聊。旧会话还没压缩过，没有总结可带；'
                        '最近的消息在 delivered_history 里，更早的事要看就 recall。'}
    return {'summary': text,
            'note': '之前那段会话太长，模型装不下了，程序换了这个新会话接着聊。summary 是旧会话最后一次压缩时留下的总结；'
                    '那之后的细节不在这里，最近的消息在 delivered_history 里，更早的事要看就 recall。'}


# ---- nightly tidying ----------------------------------------------------------
def _last_tidied(store, docs, slug, tidy_episodes):
    """(when she last wrote this note in a settlement turn or else when it began, whether it changed since then,
    whether she has tidied it at all)."""
    rows = list(store.db.state_revisions.find({'entity_key': docs.key(slug)}, {'mutation_id': 1, 'created_at': 1})
                .sort('created_at', 1))
    if not rows:
        return None, False, False
    mark, tidied = rows[0], False
    for row in rows:
        if str(row.get('mutation_id') or '').split(':write:')[0] in tidy_episodes:
            mark, tidied = row, True
    return mark.get('created_at'), any(row['created_at'] > mark['created_at'] for row in rows), tidied


def review_block(store, persona, moment):
    """Her notes that show every turn and are due for tidying tonight: over or near their limit, or changed and
    left untidied for a week. At most REVIEW_PER_NIGHT, most pressing first, with their sections."""
    from .config import ago
    from .documents import DocumentStore
    from .group_admin import notes_slug
    from .people import People
    docs = DocumentStore(store, persona)
    people = People(store, persona)
    tidy = {row['_id'] for row in store.db.episodes.find({'episode_kind': 'settlement'}, {'_id': 1})}
    names = {notes_slug(scene['_id']): people.scene_title(scene) + '的笔记'
             for scene in store.db.scenes.find({'kind': 'group'}, {'_id': 1, 'kind': 1})}
    from .carried import placed
    due = []
    for slug in docs.slugs():
        content = placed(store, persona, slug, docs.read(slug)[1])         # as her turns carry it (ADR-096)
        limit = note_limit(slug, content)
        if not limit or not content:
            continue
        sections = content.get('sections') or []
        chars = note_chars(sections)
        when, changed, tidied = _last_tidied(store, docs, slug, tidy)
        try:
            days = (moment - datetime.fromisoformat(when)).total_seconds() / 86400 if when else 0
        except (TypeError, ValueError):
            days = 0
        if chars > limit:
            rank, why = 0, '超过了每回合的上限，较早的节现在只露标题'
        elif chars >= limit * 0.8:
            rank, why = 1, '快到上限了'
        elif changed and days >= REVIEW_EVERY_DAYS:
            rank, why = 2, '一周多没整理，之后又改过'
        else:
            continue
        due.append((rank, -days, {
            'doc': slug, 'what': names.get(slug) or content.get('title') or slug, 'why_now': why,
            'fullness': fullness(chars, limit), 'last_tidied': ago(days * 24) if tidied else '还没整理过',
            'sections': [{k: s[k] for k in ('sid', 'heading', 'body', 'inject') if k in s} for s in sections]}))
    due.sort(key=lambda item: item[:2])
    items = [item for _, _, item in due[:REVIEW_PER_NIGHT]]
    if not items:
        return None
    return {'items': items, **({'more': '还有 %d 份也该整理，下次再列' % (len(due) - len(items))}
                                if len(due) > len(items) else {}),
            'note': ('这几份是你每回合都会自动带上的笔记，今晚该整理了。整理就是：过时的、重复的、已经不对的，'
                     '用 replace_section 改写成现在成立的样子；不常用但想留着的节用 set_tags 把 when_shown 改成 '
                     'on_demand 收起来（还在，recall 能读）；细节多的可以挪进不自动带上的文档，这里留一句指路。'
                     'doc 照抄这里的 doc。笔记短了，你每回合要读的就少，留什么由你定，今晚不整理也可以。')}
