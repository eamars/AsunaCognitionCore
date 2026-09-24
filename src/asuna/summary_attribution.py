"""ADR-005 P2：摘要条目上的说话人归属与更正——由程序从真实行算出来，不让模型自己认领。

群场景一批原文里本来就有好几个人。模型只负责把话顺成一段转述；「这段盖了谁」「谁更正了谁」
必须能从真实行里算出来并跟着条目一起存，否则下一轮会出两件事：把 A 的偏好登记成 B 的关系
证据，以及一段已经被更正过的旧转述还被当成现状。这里两处都只认看得见依据：

  - participants／source_by_speaker：直接来自这批行的 author，每条都能回读到原文行；
  - corrections：命中更正线索的行 + 真实 reply 链（入站 event.group_context.reply_message_id、
    出站 reply_to、平台消息 ID）或本批内同一说话人的前一条（标 low）；对象取不到就照实说
    取不到，不猜哪条被推翻——这条口径跟 P1-c 的按需整理完全一致，线索词也是同一份；
  - annotate_corrected：更正指向的行已经被更早一条摘要盖住时，给那条摘要追加 corrected_by，
    让下一轮看得见「这段转述之后有人更正过」，不改写它的正文也不删它；
  - covers_person：一条摘要能不能当某个人的关系来源，看它盖没盖过这个人说的话。

全部只读＋追加；不新增集合、不新增状态服务、不调模型。
"""
from __future__ import annotations

try:                                  # 宿主按包加载
    from .discussion_digest import CORRECTION_CUES, SELF_REFERENCE_CUES, _first_cue
    from .state import Conflict, now
except Exception:                     # 同目录平铺加载（离线自检）也认
    from discussion_digest import CORRECTION_CUES, SELF_REFERENCE_CUES, _first_cue
    from state import Conflict, now

SNIPPET = 120            # 条目里只带显示片段，全文仍按 source_event_ids 回读
MAX_CORRECTIONS = 8      # 一条摘要上最多带几条更正标注
MAX_MARKS = 8            # corrected_by 的有界长度
CORRECTABLE_KINDS = ('dialogue_summary',)


def _clip(text):
    body = text if isinstance(text, str) else ''
    return body[:SNIPPET]


def _reply_reference(row):
    """这行带的真实 reply 引用：先取宿主已经绑定过的消息 _id，再退回平台消息 ID。"""
    group = (row.get('event') or {}).get('group_context') or {}
    bound = group.get('reply_message_id') or (row.get('reply_to') if isinstance(row.get('reply_to'), str) else None)
    if isinstance(bound, str) and bound:
        return bound, 'reply_link'
    platform = group.get('reply_to') or row.get('platform_reply_to')
    if isinstance(platform, str) and platform:
        return platform, 'reply_link_by_platform_id'
    return '', ''


def _resolve(store, scene, reference):
    """reply 引用落到本场景本纪元的真实行；落不到就返回 None（不猜对象）。"""
    if not reference:
        return None
    return store.db.messages.find_one({'scene_id': scene['_id'], 'policy_epoch': scene['policy_epoch'],
                                       '$or': [{'_id': reference},
                                               {'event.channel.platform_event_id': reference},
                                               {'platform_message_id': reference}]},
                                      {'author': 1, 'scene_seq': 1, 'direction': 1, 'summary_batch_id': 1})


def _same_author_previous(rows, position):
    for earlier in reversed(rows[:position]):
        if earlier.get('author') == rows[position].get('author'):
            return earlier
    return None


def corrections(store, scene, rows):
    """这批原文里的更正：谁说的、凭什么认定对象、是不是自我更正。取不到对象就照实说。"""
    out = []
    for position, row in enumerate(rows):
        text = row.get('text') or ''
        cue = _first_cue(text, CORRECTION_CUES)
        if not cue:
            continue
        reference, how = _reply_reference(row)
        target = _resolve(store, scene, reference)
        if target is None and _first_cue(text, SELF_REFERENCE_CUES):
            target = _same_author_previous(rows, position)
            how = 'same_author_previous_in_batch' if target else 'self_reference_unresolved'
        elif target is None and reference:
            # 引用带在行上但在本场景本纪元落不到行：照实说没认定，别写成像已经认定了。
            how = how + '_unresolved'
        elif target is not None and target.get('_id') == row.get('_id'):
            target, how = None, 'self_reference_to_self'
        out.append({'message_id': row.get('_id'), 'actor': row.get('author'), 'cue': cue,
                    'scene_seq': row.get('scene_seq'), 'snippet': _clip(text),
                    'corrects': (target or {}).get('_id'), 'target_author': (target or {}).get('author'),
                    'target_resolution': how or 'unresolved',
                    'self_correction': bool(target) and target.get('author') == row.get('author'),
                    'in_batch': bool(target) and target.get('_id') in {r.get('_id') for r in rows}})
    return out[:MAX_CORRECTIONS]


def attribute(store, scene, rows):
    """这批原文的归属事实：盖了谁、每人几条、里面有没有更正。全部可回读，不掺模型判断。"""
    by_speaker, speakers = {}, {}
    for row in rows:
        author = row.get('author') or 'unknown'
        by_speaker.setdefault(author, []).append(row.get('_id'))
        entry = speakers.setdefault(author, {'messages': 0, 'chars': 0, 'directions': []})
        entry['messages'] += 1
        entry['chars'] += len(row.get('text') or '')
        if row.get('direction') not in entry['directions']:
            entry['directions'].append(row.get('direction'))
    peers = [author for author in by_speaker if author != 'xiaoman']
    return {'participants': sorted(by_speaker),
            'source_by_speaker': {author: sorted(ids) for author, ids in sorted(by_speaker.items())},
            'speakers': {author: {'messages': entry['messages'], 'chars': entry['chars'],
                                  'directions': sorted(entry['directions'])}
                         for author, entry in sorted(speakers.items())},
            'multi_speaker': len(peers) > 1,
            'corrections': corrections(store, scene, rows)}


def annotate_corrected(store, scene, items, current_key):
    """更正指向的行已被更早一条摘要盖住 → 给那条摘要追加 corrected_by（只追加，不动正文）。"""
    applied = []
    for item in items:
        target = item.get('corrects')
        if not target or item.get('in_batch'):
            continue            # 同一批里的更正由这条摘要自己写清，不需要回标旧条目
        row = store.db.messages.find_one({'_id': target}, {'summary_batch_id': 1})
        prior = (row or {}).get('summary_batch_id')
        if not prior or prior == current_key:
            continue
        unit = store.db.memory_units.find_one({'_id': prior})
        if not unit or unit.get('kind') not in CORRECTABLE_KINDS or unit.get('status') != 'active':
            continue
        before = list(unit.get('corrected_by') or [])
        marks = sorted({*before, item.get('message_id')})[:MAX_MARKS]
        if marks == before:
            continue
        try:
            store.put('memory_units', {**unit, 'corrected_by': marks, 'corrected_at': now()},
                      expected=unit['revision'], stream=prior)
        except Conflict:
            continue            # 有人同时在动这条：下一轮还会看见这条更正，不硬来
        applied.append({'unit': prior, 'by': item.get('message_id'), 'actor': item.get('actor'),
                        'corrected_by': marks})
    return applied


def covers_person(store, unit, person_id):
    """这条摘要盖没盖过这个人说的话？盖过才能当这条关系的来源；盖不到就给出原因。"""
    if not isinstance(unit, dict):
        return False, 'unit_missing'
    participants = unit.get('participants')
    if participants:
        if person_id in participants:
            return True, 'participants'
        return False, 'person_not_in_participants'
    sources = [key for key in (unit.get('source_event_ids') or []) if isinstance(key, str)]
    if not sources:
        return False, 'no_source_events'
    rows = list(store.db.messages.find({'_id': {'$in': sources}}, {'author': 1}))
    if any(row.get('author') == person_id for row in rows):
        return True, 'legacy_source_authors'
    if len(rows) < len(sources):
        return False, 'sources_unreadable'
    return False, 'person_not_in_sources'
