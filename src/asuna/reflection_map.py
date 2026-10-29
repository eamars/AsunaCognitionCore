"""map_from_program (ADR-073): in a reflection turn, a map of what she has, what changed since the last map she saw,
and how to open each; what she changed, in her own words with the reasons she gave; and where her attention went, as
counts.

Reflection turns run in a session of their own (ADR-072), so this costs her regular turns nothing. Facts only, each
count with its source; no verdict, no one else's lines. The per-conversation understandings stay out (scoped to their
conversation by her own design). It does not overlap ADR-071's exchanges: those are her lines, the thought she wrote
then and what came back; this is what she changed and why. Each has its own window and its own limit.
"""
from __future__ import annotations

import collections
import json
from datetime import datetime, timedelta, timezone

from . import clock
from .config import excerpt
from .records import scenes as scene_records
from .records import plans as plan_records
from .records import memories as memory_records
from .records import artifacts as artifact_records
from .records import heads as head_records
from .records import ideas as idea_records
from .records import people as people_records

TABLES_VERSION = 1
SHOWN = 'review.map'
WINDOW_DAYS = 14             # the look-back at most; a longer gap is said, not hidden (her review)
# At most about 8,000 characters in all: each store has its own share, so the busiest cannot fill the map (her review: volume is not importance); within a
# store the newest come first, whole while they fit, then by heading and reference, then as a count.
BUDGET = {'group_notes': 2800, 'documents': 1500, 'people': 1200}
REASONS_SHOWN = 3
WHOLE_CHARS = 1200
NOTE = ('这是你现在有的东西的一张图：每样一行，多少、上次看这张图以来变了什么、怎么打开（recall 的 sections 写 doc 和 section）。'
        'changed 是你上次以来改过的，你自己的话和你当时写的理由；attention 是每个群你的相关性判断看了几行、叫你看了几行，'
        '两数的差就是没叫你看的，只有数，不是评价。看什么、改什么由你。')


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat()


def _at(value):
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _heads(store, prefix):
    return head_records.with_prefix(store, prefix).rows(fields=['_id', 'revision_id'])


def _revision(store, revision_id):
    return head_records.revision(store, revision_id, ['content', 'created_at', 'entity_key']) if revision_id else None


def _before(store, entity, since):
    """The entity's content as it was at `since` (its newest revision before it), or {}."""
    row = head_records.history(store, entity, before=since).first(newest_first=True, fields=['content'])
    return (row or {}).get('content') or {}


def _changed_sections(then, now):
    old = {s['sid']: s.get('body') for s in then.get('sections') or []}
    return [s for s in now.get('sections') or [] if old.get(s['sid']) != s.get('body') and (s.get('body') or '').strip()]


def _reasons(store, entity, since):
    seen = []
    for row in head_records.history(store, entity, since=since).rows(newest_first=True, fields=['reason']):
        reason = (row.get('reason') or '').strip()
        if reason and reason not in seen:
            seen.append(reason)
    return seen[:REASONS_SHOWN]


def _size(value):
    return len(json.dumps(value, ensure_ascii=False))


def _who(store, people, person):
    """A person by the name she reads them by: the owner's word for the owner, the name kept here, else their last card."""
    from .people import safe_name
    if person == (store.config.get('chat') or {}).get('person_id'):
        return people.owner_label
    seen = people_records.label_of_person(store, person, ['card', 'nickname'])
    return (people.named(person) or safe_name((seen or {}).get('card')) or safe_name((seen or {}).get('nickname'))
            or '一个没留下名字的人')


def _fill(entries, budget, slim, left_words):
    """Entries newest first within `budget` characters: whole, then slimmed (`slim`), then a count of the rest."""
    out, rest = [], 0
    for entry in entries:
        if _size(out + [entry]) <= budget:
            out.append(entry)
        elif _size(out + [slim(entry)]) <= budget:
            out.append(slim(entry))
        else:
            rest += 1
    return out + ([left_words % rest] if rest else [])


def block(store, persona, moment=None, *, tag=None):
    """The map since the last one she saw (at most WINDOW_DAYS); records the showing."""
    from . import affect, group_admin, places, questions, self_review, switches
    from . import notes as note_owner
    from .people import People
    moment = moment or clock.now()
    from . import audit as audit_trail
    last = audit_trail.events(store, SHOWN, persona=persona).first(newest_first=True)
    floor = moment - timedelta(days=WINDOW_DAYS)
    since_at = max(_at(last['occurred_at']), floor) if last else floor
    since = _iso(since_at)
    if not last:
        # Her review: seen for the first time is not new, so the first map counts nothing as changed.
        window = '这是第一张图：没有上一张可比，现有的都是基线·首次入图，不算改过；从下一张起才数改了什么。'
    elif _at(last['occurred_at']) < floor:
        gap = (moment - _at(last['occurred_at'])).days
        window = '上次地图在 %d 天前，最早的 %d 天没进这张图（只看最近 %d 天）。' % (gap, gap - WINDOW_DAYS, WINDOW_DAYS)
    else:
        window = None
    store.audit('review:' + persona, SHOWN, {'persona': persona})
    people = People(store, persona)
    index = []

    # Her group notes, by group, newest first, each with the reasons she gave.
    groups = {group_admin.notes_slug(s['_id']): s for s in scene_records.of_kind(store, 'group')}
    totals = [0, 0, 0, 0]
    notes = []
    for head in _heads(store, 'doc:%s:group' % persona):
        slug = head['_id'].split('|')[0].split(':', 2)[2]
        row = _revision(store, head['revision_id']) or {}
        entity = row.get('entity_key') or head['_id']          # history is kept under the revision's own key
        now = row.get('content') or {}
        secs = now.get('sections') or []
        totals[0] += 1
        totals[1] += len(secs)
        totals[2] += sum(len(s.get('body') or '') for s in secs)
        moved = _changed_sections(_before(store, entity, since), now) if last else []
        if not moved:
            continue
        totals[3] += len(moved)
        scene = groups.get(slug)
        notes.append((row.get('created_at') or '', {
            'group': people.scene_title(scene) if scene else slug, 'your_reasons': _reasons(store, entity, since),
            'sections': [{'heading': s.get('heading') or s['sid'], 'ref': {'doc': slug, 'section': s['sid']},
                          'text': excerpt(s.get('body'), WHOLE_CHARS)} for s in moved]}))
    index.append(('群笔记：%d 个群，%d 节，%d 字；' % tuple(totals[:3]))
                 + ('上次以来改了 %d 节（changed.group_notes）' % totals[3] if last else '基线·首次入图')
                 + '。打开：recall 的 sections 写 {doc: "group:…", section: "…"}')

    # Her own documents: headings changed, newest first, with the reasons she gave then.
    documents = []
    for head in _heads(store, 'doc:%s:' % persona):
        slug = head['_id'].split('|')[0].split(':', 2)[2]
        if slug.startswith('group'):
            continue
        row = _revision(store, head['revision_id']) or {}
        entity = row.get('entity_key') or head['_id']
        now = row.get('content') or {}
        moved = _changed_sections(_before(store, entity, since), now) if last else []
        index.append('%s：%d 节，%s' % (slug, len(now.get('sections') or []),
                                       '上次以来改了 %d 节' % len(moved) if last else '基线·首次入图'))
        if moved:
            documents.append((row.get('created_at') or '', {
                'doc': slug, 'headings': [s.get('heading') or s['sid'] for s in moved],
                'your_reasons': _reasons(store, entity, since)}))

    # People: the person-level understandings changed since (the per-conversation ones stay in their conversation).
    heads = _heads(store, 'relationship:')
    persons = [h for h in heads if h['_id'].endswith('|person')]
    understood = []
    for head in persons:
        row = _revision(store, head['revision_id']) or {}
        if last and (row.get('created_at') or '') >= since:
            person = head['_id'].split('|')[0].split(':', 1)[1]
            understood.append((row['created_at'], {'who': _who(store, people, person),
                                                   'text': excerpt((row.get('content') or {}).get('body'), WHOLE_CHARS)}))
    index.append('人：按人那层的理解 %d 个人，按对话那层 %d 个对话（那层只在各自的对话里）；%s'
                 % (len(persons), len(heads) - len(persons),
                    '上次以来按人那层改了 %d 个' % len(understood) if last else '基线·首次入图'))

    # The rest, as counts with where to look.
    kinds = collections.Counter(m.get('kind') for m in memory_records.alive(store).each(fields=['kind']))
    words = {'chat_chunk': '聊天片段', 'dialogue_summary': '对话摘要', 'monologue': '你的心里话'}
    index.append('记忆：' + '、'.join('%s %d' % (words.get(k, k), n) for k, n in kinds.most_common(4)))
    # memory_tiers is declared, so the store's ensure makes it at every start: it is always there to be counted.
    from . import memory_tiers
    tiers = collections.Counter(r.get('place') for r in memory_tiers.items(store, persona).each(fields=['place']))
    moves = audit_trail.count(store, 'memory.moved', since=since)
    index.append('分层的条目：' + '、'.join('%s %d' % kv for kv in tiers.items()) + '；上次以来挪动 %d 次' % moves)
    index.append('感受：一共 %d 笔，上次以来 %d 笔，还挂着没了的 %d 笔（feel）' % (
        affect.count_events(store, persona), affect.count_events(store, persona, since=since),
        affect.count_events(store, persona, still_open=True)))
    ideas = collections.Counter(i.get('state') for i in idea_records.of_persona(store, persona, by=None).rows(fields=['state']))
    index.append('想法本：没处理 %d、暂缓 %d（ideas 的 read）' % (ideas.get('open', 0), ideas.get('deferred', 0)))
    index.append('计划：生效中 %d（plans_from_program）；问题：还开着 %d（ask 的 read）' % (
        plan_records.count_status(store, 'ACTIVE'),
        questions.count_open(store, persona)))
    index.append('便条：上次以来写了 %d 张' % note_owner.count_since(store, persona, since))
    errands = (places.errands_block(store, persona, moment) or {}).get('items') or []
    on_way = [e for e in errands if e.get('state') in (places.ERRAND_STATES['pending'], places.ERRAND_STATES['sending'])]
    index.append('差事：最近 %d 趟，还在路上 %d 趟（下场在 errands_from_program）' % (len(errands), len(on_way)))
    live = switches.on(store, moment=moment)
    index.append('你开着的开关：%d 个' % len(live) + ('，' + '；'.join('%s 到 %s' % (switches.WORDS[r['kind']] + '：' + r['label'],
                                                                         r['until'][:16]) for r in live[:6]) if live else ''))
    pictures = artifact_records.count_tool(store, 'generate_image', 'DONE')
    from . import stickers
    shelf = stickers.shelf(store, persona)
    index.append('你做的东西：画的图 %d 张；表情包架 %d 个（sticker 的 shelf 列全）' % (pictures, len(shelf)))
    found = self_review.cared(store, persona, tag, whole=True)
    index.append('self_review.tag「%s」在 self、core 里找到 %d 节' % (tag, len(found or [])) if tag else '人格模型里没有 self_review.tag')

    # Attention: per group, lines her relevance gate saw and how many it gave her a look at.
    seen, looked = collections.Counter(), collections.Counter()
    for row in audit_trail.events(store, 'attend.verdict', since=since, by=None).each(
            fields=['scope_key', 'payload.choice']):
        scene_id = str(row.get('scope_key') or '')[len('scene:'):]
        seen[scene_id] += 1
        looked[scene_id] += (row.get('payload') or {}).get('choice') == 'join'
    attention = []
    for scene_id, n in seen.most_common():
        scene = scene_records.get(store, scene_id)
        attention.append('%s：看了 %d 行，叫你看了 %d 行' % (people.scene_title(scene) if scene else '一个现在已经没有的对话',
                                                    n, looked[scene_id]))

    newest = lambda pairs: [entry for _, entry in sorted(pairs, key=lambda pair: pair[0], reverse=True)]
    changed = {
        'group_notes': _fill(newest(notes), BUDGET['group_notes'],
                             lambda e: {**e, 'sections': [{k: v for k, v in s.items() if k != 'text'} for s in e['sections']]},
                             '另有 %d 个群的改动没列出（打开：recall 的 sections）'),
        'documents': _fill(newest(documents), BUDGET['documents'], lambda e: {**e, 'your_reasons': e['your_reasons'][:1]},
                           '另有 %d 份文档的改动没列出'),
        'people': _fill(newest(understood), BUDGET['people'], lambda e: {'who': e['who']}, '另有 %d 个人的理解改过，没列出')}
    out = {'since_at': since, **({'window': window} if window else {}), 'index': index, 'changed': changed,
           'attention': attention or ['上次以来没有要判断的行。'],
           'sources': ('群笔记和你的文档：state_heads 与 state_revisions（改过的节＝和 since_at 那一刻的版本比，正文不同或新加；理由是'
                       '那段时间每次修改时你写的 why）；人：relationship:…|person；记忆 memory_units、memory_tiers、audit memory.moved；'
                       '感受 affect_events；想法 ideas；计划 plans；问题 questions；便条 notes；差事 errands_from_program 同源；开关 '
                       'switches；图 artifacts（generate_image）；注意力：audit type=attend.verdict，join 算叫你看'),
           'note': NOTE}
    return out
