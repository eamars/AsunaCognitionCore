"""What a turn may carry on its own, and how her own notes stay short (owner 2026-10-06, ADR-014).

The program adds most of a turn's context by itself, so it also bounds it: a versioned table of limits for each
block it adds, a ceiling for the whole turn, and the words for how full her own notes are. Nothing is cut
silently and nothing is lost: what a turn leaves out is counted and said, and stays readable through recall.
Her notes are hers to tidy. Over its limit a note shows its newest sections and names the rest; far over it, it
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

# How full a note is, in words (share of its limit).
FULLNESS = ((0.5, '宽裕'), (0.8, '用了一大半'), (1.0, '快满了'), (None, '超了'))
# How long ago a feeling was stirred, in words coarse enough to stay the same for a while.
ROUGH_AGO = ((1, '一小时内'), (6, '几小时前'), (24, '一天之内'), (72, '这两三天'), (None, '更早'))
# Over the ceiling, these lists lose rows first, in this order: (block, list inside it or None, which end goes).
TRIM_ORDER = (('recent_experience_from_program', 'messages', 'oldest'),
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


def note_view(sections, limit):
    """(sections to show, words about the note). Within its limit a note shows whole; over it, the newest sections
    that fit, in their own order, and the rest by heading. A section is never cut inside."""
    from .config import excerpt
    always = shown(sections)
    total = note_chars(sections)
    about = {'fullness': fullness(total, limit)}
    kept = always
    if total > limit:
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
        about['tucked_away'] = '另有 %d 节收起了（inject 不是 always），不自动带上。' % len(tucked)
    return kept, about


def note_limit(slug, content):
    if slug.startswith('group:'):
        return NOTE_CHARS['group_notes']
    if (content or {}).get('kind') == 'ledger':
        return NOTE_CHARS['ledger']
    return None


def note_gate(slug, before, after):
    """Refuse growth of a note already far over its limit (DocumentStore.apply's budget hook)."""
    from .documents import DocumentError
    limit = note_limit(slug, after)
    if not limit:
        return
    old, new = note_chars((before or {}).get('sections') or []), note_chars(after.get('sections') or [])
    if new > old and new > limit * NOTE_HARD_FACTOR:
        raise DocumentError('NOTE_OVER_LIMIT', '%d 字，上限 %d 字' % (new, limit))


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
    if left:
        context['trimmed_from_program'] = {
            'left_out': left, 'note': '这回合的资料超过了上限，这些列表里较早的几条没列出；要看就 recall。'}
    return left


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
    due = []
    for slug in docs.slugs():
        _, content = docs.read(slug)
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
                     '用 replace_section 改写成现在成立的样子；不常用但想留着的节用 set_tags 把 inject 改成 '
                     'on_demand 收起来（还在，recall 能读）；细节多的可以挪进不自动带上的文档，这里留一句指路。'
                     'doc 照抄这里的 doc。笔记短了，你每回合要读的就少，留什么由你定，今晚不整理也可以。')}
