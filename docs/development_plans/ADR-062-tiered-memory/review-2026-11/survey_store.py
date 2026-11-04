"""ADR-062 review (2026-11-05): her memory stores by structure only. Read-only; counts, sizes, dates, kinds, places,
scores. Never prints a body, a heading, a query, a person id or a scene id.

Usage: python -X utf8 survey_store.py <config/local.json> <out.json>
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

config = json.load(open(sys.argv[1], encoding='utf-8'))
client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000)
db = client[config['database']]
NOW = datetime.now(timezone.utc)
SWITCH_ON = '2026-10-14'
out = {'read_at': NOW.isoformat(), 'database': '<name withheld>'}


def q(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else None


def stats(values):
    values = [v for v in values if v is not None]
    return {'n': len(values), 'sum': sum(values), 'min': min(values) if values else None, 'p50': q(values, .5),
            'p90': q(values, .9), 'max': max(values) if values else None}


def day(value):
    return str(value)[:10] if value else None


def week(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        y, w, _ = d.isocalendar()
        return '%d-W%02d' % (y, w)
    except (TypeError, ValueError):
        return None


def at(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


# ── A. memory_tiers ──────────────────────────────────────────────────────────────────────────────────────────────
tiers = list(db.memory_tiers.find({}, {'heading': 0}))
rows_by_kind = Counter(r.get('row') for r in tiers)
items = [r for r in tiers if r.get('row') == 'item']
moves = [r for r in tiers if r.get('row') == 'move']
A = {'rows_by_kind': dict(rows_by_kind), 'personas': len({r.get('persona') for r in items})}
A['items_by_store_place'] = {}
for r in items:
    key = '%s|%s|%s' % (r['store'], r['place'], 'fact' if r.get('fact') else 'memory')
    A['items_by_store_place'][key] = A['items_by_store_place'].get(key, 0) + 1
A['items_chars_by_store_place'] = {}
by_sp = defaultdict(list)
for r in items:
    by_sp['%s|%s' % (r['store'], r['place'])].append(r.get('chars') or 0)
for k, v in sorted(by_sp.items()):
    A['items_chars_by_store_place'][k] = stats(v)
A['items_added_by_week_store'] = {}
for r in items:
    k = '%s|%s' % (week(r.get('added')), r['store'])
    A['items_added_by_week_store'][k] = A['items_added_by_week_store'].get(k, 0) + 1
A['items_added_by_week_store'] = dict(sorted(A['items_added_by_week_store'].items()))
A['last_moment'] = dict(Counter(r.get('last_moment') for r in items))
A['nature'] = dict(Counter('%s|%s' % (r.get('nature'), r.get('from')) for r in items))
A['uses'] = stats([int(r.get('uses') or 0) for r in items])
A['uses_zero_by_store_place'] = dict(Counter('%s|%s' % (r['store'], r['place']) for r in items if not r.get('uses')))
A['stays'] = dict(Counter(int(r.get('stays') or 0) for r in items))
A['doubled'] = dict(Counter(bool(r.get('doubled')) for r in items))
A['stay_days'] = dict(Counter(float(r.get('stay_days') or 0) for r in items))
A['gist'] = dict(Counter('listed' if (r.get('gist') or {}).get('listed') else 'none' for r in items))
A['gist_done'] = sum(1 for r in items if (r.get('gist') or {}).get('done'))
A['gist_skipped'] = sum(1 for r in items if (r.get('gist') or {}).get('skipped'))
A['gist_nights'] = dict(Counter(len((r.get('gist') or {}).get('nights') or []) for r in items))
A['detail_of'] = sum(1 for r in items if r.get('detail_of'))
A['superseded'] = sum(1 for r in items if r.get('superseded_at'))
A['confirmed'] = sum(1 for r in items if r.get('confirmed'))
A['with_line_anchor'] = sum(1 for r in items if r.get('line'))
A['recalled_in_len'] = dict(Counter(len(r.get('recalled_in') or []) for r in items))
A['surfaced_in_len'] = dict(Counter(len(r.get('surfaced_in') or []) for r in items))
A['put_away_recalled_in_2_or_more'] = dict(Counter(r['store'] for r in items if r['place'] == '收着'
                                                   and len(r.get('recalled_in') or []) >= 2))
A['put_away_with_any_recall'] = dict(Counter(r['store'] for r in items if r['place'] == '收着' and r.get('recalled_at')))
A['at_hand_with_any_recall'] = dict(Counter(r['store'] for r in items if r['place'] == '手边' and r.get('recalled_at')))
A['felt'] = sum(1 for r in items if r.get('felt'))
# duplicate body hashes among items (same text written as more than one item), per store
hashes = defaultdict(list)
for r in items:
    hashes[(r['store'], r.get('body_sha256'))].append(r['place'])
A['same_body_sha_groups_by_store'] = dict(Counter(store for (store, _), places in hashes.items() if len(places) > 1))
A['same_body_sha_items_by_store'] = dict(Counter(store for (store, _), places in hashes.items() if len(places) > 1
                                                 for _ in places))
# moves
A['moves_by_reason_from_to_by'] = dict(Counter('%s|%s→%s|%s' % (m.get('reason'), m.get('from'), m.get('to'),
                                                                 m.get('by') or '?') for m in moves))
A['moves_by_day_reason'] = {}
for m in moves:
    k = '%s|%s' % (day(m.get('at')), m.get('reason'))
    A['moves_by_day_reason'][k] = A['moves_by_day_reason'].get(k, 0) + 1
A['moves_by_day_reason'] = dict(sorted(A['moves_by_day_reason'].items()))
A['moves_by_week_reason'] = {}
for m in moves:
    k = '%s|%s' % (week(m.get('at')), m.get('reason'))
    A['moves_by_week_reason'][k] = A['moves_by_week_reason'].get(k, 0) + 1
A['moves_by_week_reason'] = dict(sorted(A['moves_by_week_reason'].items()))
A['moves_by_store_reason'] = dict(Counter('%s|%s' % (m.get('store'), m.get('reason')) for m in moves))
A['moves_told_in_len'] = dict(Counter(len(m.get('told_in') or []) for m in moves))
# regret: a lapse (stay/overflow) followed by a lift back (rewritten) of the same item, by delay
by_item = defaultdict(list)
for m in moves:
    by_item[m['item']].append(m)
regret, regret_days = 0, []
lapsed_items, recalled_after = 0, 0
for item_id, ms in by_item.items():
    ms.sort(key=lambda m: m.get('at') or '')
    for i, m in enumerate(ms):
        if m.get('from') == '随身' and m.get('reason') in ('stay', 'overflow'):
            lapsed_items += 1
            later = [n for n in ms[i + 1:] if n.get('to') == '随身']
            if later:
                regret += 1
                d = (at(later[0]['at']) - at(m['at'])).total_seconds() / 86400
                regret_days.append(round(d, 1))
            row = next((r for r in items if r['_id'] == item_id), None)
            if row and (row.get('recalled_at') or '') > m['at']:
                recalled_after += 1
A['regret'] = {'lapses': lapsed_items, 'came_back_up_later': regret, 'came_back_days': stats(regret_days),
               'recalled_after_lapse': recalled_after}
A['moves_per_item'] = dict(Counter(len(v) for v in by_item.values()))
A['items_never_moved'] = sum(1 for r in items if r['_id'] not in by_item)
A['other_rows'] = {k: v for k, v in rows_by_kind.items() if k not in ('item', 'move')}
offers = [r for r in tiers if r.get('row') == 'offer']
A['offers_by_what'] = dict(Counter(r.get('what') for r in offers))
A['offers_by_night_what'] = dict(sorted(Counter('%s|%s' % (r.get('night'), r.get('what')) for r in offers).items()))
A['over_rows'] = [{'store': r.get('store'), 'since': day(r.get('since')), 'shown_in': len(r.get('shown_in') or [])}
                  for r in tiers if r.get('row') == 'over']
out['A_memory_tiers'] = A

# ── B. memory_shadow (the item index), without embeddings ───────────────────────────────────────────────────────
shadow = list(db.memory_shadow.find({}, {'embedding': 0}))
B = {'rows_by_kind': dict(Counter(r.get('row') for r in shadow))}
sitems = [r for r in shadow if r.get('row') == 'item']
B['items_by_store_status'] = dict(Counter('%s|%s' % (r.get('store'), r.get('status')) for r in sitems))
B['items_chars_by_store'] = {}
for store in sorted({r.get('store') for r in sitems}):
    B['items_chars_by_store'][store] = stats([r.get('chars') or 0 for r in sitems if r.get('store') == store
                                              and r.get('status') == 'active'])
B['embedded_by_opening_only'] = dict(Counter('%s|%s' % (r.get('store'), r.get('embedding_opening_chars'))
                                             for r in sitems if r.get('embedding_opening_chars')))
B['items_over_400_chars_active'] = dict(Counter(r.get('store') for r in sitems if r.get('status') == 'active'
                                                and (r.get('chars') or 0) > 400))
B['synced_by_week'] = dict(sorted(Counter(week(r.get('synced_at')) for r in sitems).items()))
pairs = [r for r in shadow if r.get('row') == 'pair']
active = {r['_id'] for r in sitems if r.get('status') == 'active'}
B['pairs_total'] = len(pairs)
B['pairs_both_active_by_store_level'] = {}
for p in pairs:
    if set(p.get('items') or []) <= active:
        lvl = '≥0.97' if p['score'] >= .97 else '≥0.95' if p['score'] >= .95 else '≥0.93'
        k = '%s|%s' % (p.get('store'), lvl)
        B['pairs_both_active_by_store_level'][k] = B['pairs_both_active_by_store_level'].get(k, 0) + 1
B['pairs_stale'] = sum(1 for p in pairs if not set(p.get('items') or []) <= active)
# join with tier rows: what place the indexed items are in
tier_by_ref = {(r['doc'], r['sid']): r for r in items}
B['active_items_by_tier_place'] = dict(Counter((tier_by_ref.get((r.get('doc'), r.get('sid'))) or {}).get('place') or 'no tier row'
                                               for r in sitems if r.get('status') == 'active'))
B['active_items_superseded'] = sum(1 for r in sitems if r.get('status') == 'active'
                                   and (tier_by_ref.get((r.get('doc'), r.get('sid'))) or {}).get('superseded_at'))
B['tier_items_without_active_index_row'] = dict(Counter(r['store'] for r in items if (r['doc'], r['sid']) not in
                                                        {(s.get('doc'), s.get('sid')) for s in sitems if s.get('status') == 'active'}))
B['turn_rows_left'] = sum(1 for r in shadow if r.get('row') in ('turn', 'recall'))
B['turn_rows_at_range'] = [day(min((r.get('at') for r in shadow if r.get('row') in ('turn', 'recall')), default=None)),
                           day(max((r.get('at') for r in shadow if r.get('row') in ('turn', 'recall')), default=None))]
B['failures'] = sum(1 for r in shadow if r.get('row') == 'failure')
# identical content among active index rows (same text indexed twice under different ids)
by_sha = Counter(r.get('content_sha256') for r in sitems if r.get('status') == 'active')
B['identical_content_groups'] = sum(1 for v in by_sha.values() if v > 1)
B['identical_content_rows'] = sum(v for v in by_sha.values() if v > 1)
out['B_memory_shadow'] = B

# ── C. state_heads / state_revisions ─────────────────────────────────────────────────────────────────────────────
heads = list(db.state_heads.find({}))


def head_kind(key):
    entity, _, scope = key.rpartition('|')
    if entity.startswith('doc:'):
        slug = entity.split(':', 2)[2]
        if slug.startswith('group:'):
            return 'doc:group notes'
        if slug.startswith('dossier:'):
            return 'doc:dossier'
        return 'doc:' + slug if slug in ('persona', 'voice', 'self', 'core', 'work_log') else 'doc:other'
    if entity.startswith('relationship:'):
        return 'relationship|person' if scope == 'person' else 'relationship|here'
    return re.sub(r':.*', ':*', entity) + '|' + re.sub(r'scene:.*', 'scene:*', scope)


C = {'heads_by_kind': dict(Counter(head_kind(h['_id']) for h in heads)), 'heads': len(heads)}
C['heads_revision_number'] = {head_kind(h['_id']): stats([]) for h in []}
agg = list(db.state_revisions.aggregate([
    {'$project': {'entity_key': 1, 'created_at': 1, 'parent_revision_id': 1, 'author': 1, 'op': 1, 'change_class': 1,
                  'status': 1, 'size': {'$bsonSize': '$$ROOT'},
                  'sections': {'$size': {'$ifNull': ['$content.sections', []]}},
                  'section_hashes': {'$map': {'input': {'$ifNull': ['$content.sections', []]}, 'as': 's',
                                              'in': {'sid': '$$s.sid', 'sha': '$$s.body_sha256'}}},
                  'body_chars': {'$strLenCP': {'$ifNull': ['$content.body', '']}},
                  'short_chars': {'$strLenCP': {'$ifNull': ['$content.short', '']}}}}]))
C['revisions'] = len(agg)
C['revisions_bytes_total'] = sum(r['size'] for r in agg)
per_entity = defaultdict(list)
for r in agg:
    per_entity[r.get('entity_key') or '?'].append(r)
C['revisions_by_kind'] = {}
for key, rs in per_entity.items():
    k = head_kind(key)
    e = C['revisions_by_kind'].setdefault(k, {'entities': 0, 'revisions': 0, 'bytes': 0, 'max_rev_per_entity': 0})
    e['entities'] += 1
    e['revisions'] += len(rs)
    e['bytes'] += sum(r['size'] for r in rs)
    e['max_rev_per_entity'] = max(e['max_rev_per_entity'], len(rs))
C['revisions_by_week_kind'] = dict(sorted(Counter('%s|%s' % (week(r.get('created_at')), head_kind(r.get('entity_key') or '?'))
                                                  for r in agg).items()))
C['revisions_by_author'] = dict(Counter(r.get('author') for r in agg))
C['revisions_change_class'] = dict(Counter(r.get('change_class') for r in agg))
C['tombstones'] = sum(1 for r in agg if r.get('status') == 'tombstone')
ids = {r['_id'] for r in agg}
C['dangling_parents'] = sum(1 for r in agg if r.get('parent_revision_id') and r['parent_revision_id'] not in ids)
C['roots'] = sum(1 for r in agg if not r.get('parent_revision_id'))
head_rev = {h['_id']: h.get('revision_id') for h in heads}
C['heads_pointing_at_missing_revision'] = sum(1 for h in heads if h.get('revision_id') not in ids)
C['revisions_without_head'] = sum(1 for key in per_entity if key not in head_rev)
# per identity document: revisions, current sections, bytes
C['documents'] = {}
for key, rs in per_entity.items():
    if key.startswith('doc:'):
        kind = head_kind(key)
        slug = key.rpartition('|')[0].split(':', 2)[2]
        name = slug if kind != 'doc:group notes' else 'group:#%d' % (len([k for k in C['documents'] if k.startswith('group:#')]) + 1)
        if kind == 'doc:dossier':
            name = 'dossier:#%d' % (len([k for k in C['documents'] if k.startswith('dossier:#')]) + 1)
        if kind == 'doc:other':
            name = 'other:#%d' % (len([k for k in C['documents'] if k.startswith('other:#')]) + 1)
        cur = max(rs, key=lambda r: r.get('created_at') or '')
        C['documents'][name] = {'revisions': len(rs), 'bytes': sum(r['size'] for r in rs),
                                'sections_now': cur['sections'], 'first': day(min(r.get('created_at') or '' for r in rs)),
                                'last': day(cur.get('created_at')), 'has_head': key in head_rev}
# understanding: person and here layers
C['understanding'] = {}
for layer in ('relationship|person', 'relationship|here'):
    keys = [k for k in per_entity if head_kind(k) == layer]
    bodies, shorts, revs, deltas = [], [], [], []
    for key in keys:
        rs = sorted(per_entity[key], key=lambda r: r.get('created_at') or '')
        revs.append(len(rs))
        if key in head_rev:
            cur = next((r for r in rs if r['_id'] == head_rev[key]), rs[-1])
            bodies.append(cur['body_chars'])
            shorts.append(cur['short_chars'])
        for a, b in zip(rs, rs[1:]):
            deltas.append(b['body_chars'] - a['body_chars'])
    C['understanding'][layer] = {'records_with_head': sum(1 for k in keys if k in head_rev), 'entities_with_revisions': len(keys),
                                 'body_chars_now': stats(bodies), 'short_chars_now': stats(shorts),
                                 'revisions_per_record': stats(revs), 'body_delta_between_revisions': stats(deltas),
                                 'records_without_short': sum(1 for s in shorts if s == 0)}
out['C_state'] = C

# ── C2. document revisions: how much of a document changes per revision (sections by body hash) ─────────────────
C2 = {}
for key in per_entity:
    if not key.startswith('doc:') or key not in head_rev:
        continue
    kind = head_kind(key)
    rs = sorted(per_entity[key], key=lambda r: r.get('created_at') or '')
    changed, total, added, removed = [], [], 0, 0
    for a, b in zip(rs, rs[1:]):
        sa = {s['sid']: s.get('sha') for s in a.get('section_hashes') or []}
        sb = {s['sid']: s.get('sha') for s in b.get('section_hashes') or []}
        changed.append(sum(1 for sid in sb if sid in sa and sa[sid] != sb[sid]))
        added += sum(1 for sid in sb if sid not in sa)
        removed += sum(1 for sid in sa if sid not in sb)
        total.append(len(sb))
    e = C2.setdefault(kind, {'documents': 0, 'revision_steps': 0, 'sections_changed_per_step': [], 'sections_per_step': [],
                             'sections_added': 0, 'sections_removed': 0, 'ops': Counter()})
    e['documents'] += 1
    e['revision_steps'] += len(changed)
    e['sections_changed_per_step'] += changed
    e['sections_per_step'] += total
    e['sections_added'] += added
    e['sections_removed'] += removed
    e['ops'].update(r.get('op') for r in rs)
for kind, e in C2.items():
    e['sections_changed_per_step'] = stats(e['sections_changed_per_step'])
    e['sections_per_step'] = stats(e['sections_per_step'])
    e['ops'] = dict(e['ops'])
out['C2_document_revision_shape'] = C2

# ── D. journal (running records) ────────────────────────────────────────────────────────────────────────────────
entries = list(db.journal_entries.find({}, {'body': 0, 'heading': 0}))
jrevs = list(db.journal_revisions.find({}, {'reason': 0}))
D = {'entries': len(entries), 'slugs': len({e.get('slug') for e in entries}),
     'entries_by_slug_index': dict(Counter('slug#%d' % i for i, slug in enumerate(sorted({e.get('slug') for e in entries}))
                                           for e in entries if e.get('slug') == slug)),
     'entry_chars': stats([len(e.get('body_sha256') or '') and 0 for e in entries])}
# body chars: body excluded above; read lengths through an aggregation
D['entry_chars'] = stats([r['n'] for r in db.journal_entries.aggregate([{'$project': {'n': {'$strLenCP': {'$ifNull': ['$body', '']}}}}])])
D['entries_by_week'] = dict(sorted(Counter(week(e.get('created_at')) for e in entries).items()))
D['entries_updated_after_creation'] = sum(1 for e in entries if (e.get('updated_at') or '') > (e.get('created_at') or ''))
D['revisions'] = len(jrevs)
D['revisions_by_op'] = dict(Counter(r.get('op') for r in jrevs))
D['revisions_by_author'] = dict(Counter(r.get('author') for r in jrevs))
D['revisions_per_entry'] = dict(Counter(Counter(r.get('entry_id') for r in jrevs if r.get('entry_id')).values()))
D['inject'] = dict(Counter(e.get('inject') for e in entries))
out['D_journal'] = D

# ── E. carried_counts / carried_sections / carried_days ─────────────────────────────────────────────────────────
cc = list(db.carried_counts.find({}))
E = {'rows': len(cc), 'days': sorted({r.get('day') for r in cc}), 'reconstructed_rows': sum(1 for r in cc if r.get('reconstructed'))}
E['pairs'] = sorted({r.get('pair') for r in cc})
E['pair_turns_by_day_pair'] = {}
for r in cc:
    E['pair_turns_by_day_pair']['%s|%s' % (r.get('day'), r.get('pair'))] = r.get('pair_turns')
E['pair_turns_by_day_pair'] = dict(sorted(E['pair_turns_by_day_pair'].items()))
E['sections_per_day_pair'] = dict(sorted(Counter('%s|%s' % (r.get('day'), r.get('pair')) for r in cc).items()))
E['recall_hits_total'] = sum(int(r.get('recall_hits') or 0) for r in cc)
E['recall_hits_by_pair'] = dict(Counter(r.get('pair') for r in cc if r.get('recall_hits')))
E['program_score_nonzero_rows'] = sum(1 for r in cc if r.get('program_score'))
E['carried_sections'] = db.carried_sections.count_documents({})
E['carried_days'] = db.carried_days.count_documents({})
out['E_carried'] = E

# ── F. memory_fires (ADR-097) ────────────────────────────────────────────────────────────────────────────────────
fires = list(db.memory_fires.find({}, {'kind': 1, 'at': 1, 'by': 1, 'turn_kind': 1}))
F = {'rows': len(fires), 'by_kind': dict(Counter(r.get('kind') for r in fires)),
     'by_week_kind': dict(sorted(Counter('%s|%s' % (week(r.get('at')), r.get('kind')) for r in fires).items())),
     'note_by': dict(Counter(r.get('by') for r in fires if r.get('kind') == 'note'))}
out['F_memory_fires'] = F

# ── G. audit: recall.read, memory.moved, memory.promoted, embedding failures (indexed by type + occurred_at) ──────
G = {}
since = SWITCH_ON + 'T00:00:00'
recalls = list(db.audit_events.find({'type': 'recall.read', 'occurred_at': {'$gte': since}},
                                    {'occurred_at': 1, 'scope_key': 1, 'payload.sections_read': 1, 'payload.sections_asked': 1,
                                     'payload.sections_missing': 1, 'payload.memories': 1, 'payload.own_thoughts_elsewhere': 1,
                                     'payload.elsewhere': 1, 'payload.before': 1, 'payload.turn_kind': 1, 'payload.place': 1,
                                     'payload.query': 1}))
G['recalls_since_switch_on'] = len(recalls)
G['recalls_by_week'] = dict(sorted(Counter(week(r.get('occurred_at')) for r in recalls).items()))
G['recalls_by_turn_kind'] = dict(Counter((r.get('payload') or {}).get('turn_kind') for r in recalls))
G['recalls_by_place'] = dict(Counter((r.get('payload') or {}).get('place') for r in recalls))
G['recalls_with_query'] = sum(1 for r in recalls if (r.get('payload') or {}).get('query'))
G['recall_query_chars'] = stats([len((r.get('payload') or {}).get('query') or '') for r in recalls if (r.get('payload') or {}).get('query')])
G['recalls_with_sections_asked'] = sum(1 for r in recalls if (r.get('payload') or {}).get('sections_asked'))
G['sections_read_total'] = sum(len((r.get('payload') or {}).get('sections_read') or []) for r in recalls)
G['sections_read_by_doc_kind'] = dict(Counter(
    ('group notes' if str(s.get('doc')).startswith('group:') else s.get('doc') if s.get('doc') in ('persona', 'voice', 'self', 'core', 'work_log', 'forward', 'elsewhere') else 'other')
    for r in recalls for s in (r.get('payload') or {}).get('sections_read') or []))
G['sections_missing_total'] = sum(len((r.get('payload') or {}).get('sections_missing') or []) for r in recalls)
G['memories_returned'] = stats([len((r.get('payload') or {}).get('memories') or []) for r in recalls if (r.get('payload') or {}).get('query')])
G['recalls_returning_own_item'] = sum(1 for r in recalls if any(str(m).startswith('doc:') for m in (r.get('payload') or {}).get('memories') or []))
G['recalls_with_elsewhere'] = sum(1 for r in recalls if (r.get('payload') or {}).get('elsewhere'))
G['recalls_with_before'] = sum(1 for r in recalls if (r.get('payload') or {}).get('before'))
G['recalls_with_own_thoughts_elsewhere'] = sum(1 for r in recalls if (r.get('payload') or {}).get('own_thoughts_elsewhere'))
G['memory_moved_audits'] = db.audit_events.count_documents({'type': 'memory.moved', 'occurred_at': {'$gte': since}})
G['memory_promoted_audits'] = db.audit_events.count_documents({'type': 'memory.promoted', 'occurred_at': {'$gte': since}})
G['embedding_failed_audits'] = db.audit_events.count_documents({'type': 'embedding.failed', 'occurred_at': {'$gte': since}})
G['embedding_refused_audits'] = db.audit_events.count_documents({'type': 'embedding.refused', 'occurred_at': {'$gte': since}})
G['state_conflict_audits'] = db.audit_events.count_documents({'type': 'state.conflict', 'occurred_at': {'$gte': since}})
G['understanding_result_states'] = dict(Counter(
    (r.get('payload') or {}).get('state') + '|' + str((r.get('payload') or {}).get('layer'))
    for r in db.audit_events.find({'type': 'understanding.result', 'occurred_at': {'$gte': since}}, {'payload.state': 1, 'payload.layer': 1})))
turns = list(db.audit_events.find({'type': 'turn.started', 'occurred_at': {'$gte': since}}, {'occurred_at': 1, 'stream_id': 1}))
G['turns_started_since_switch_on'] = len(turns)
G['turns_by_week'] = dict(sorted(Counter(week(r.get('occurred_at')) for r in turns).items()))
G['latest_turn_started_at_minutes_ago'] = round((NOW - at(max(r['occurred_at'] for r in turns))).total_seconds() / 60, 1) if turns else None
out['G_audit'] = G

# ── H. ideas ─────────────────────────────────────────────────────────────────────────────────────────────────────
ideas = list(db.ideas.find({}, {'idea': 0, 'why': 0, 'source': 0}))
H = {'by_state': dict(Counter(r.get('state') for r in ideas)), 'created_by_week': dict(sorted(Counter(week(r.get('created_at')) for r in ideas).items()))}


def last_touch(r):
    ds = [d.get('at') for d in r.get('decisions') or [] if d.get('at')]
    return max(ds) if ds else r.get('created_at')


for state in ('open', 'deferred'):
    rows = [r for r in ideas if r.get('state') == state]
    H['%s_days_since_last_touch' % state] = stats([round((NOW - at(last_touch(r))).total_seconds() / 86400, 1) for r in rows if at(last_touch(r))])
    H['%s_days_since_created' % state] = stats([round((NOW - at(r.get('created_at'))).total_seconds() / 86400, 1) for r in rows if at(r.get('created_at'))])
    H['%s_decisions_count' % state] = dict(Counter(len(r.get('decisions') or []) for r in rows))
H['decisions_by_kind'] = dict(Counter(d.get('decision') for r in ideas for d in r.get('decisions') or []))
H['decisions_by_week'] = dict(sorted(Counter(week(d.get('at')) for r in ideas for d in r.get('decisions') or []).items()))
out['H_ideas'] = H

# ── I. stickers ──────────────────────────────────────────────────────────────────────────────────────────────────
st = list(db.stickers.find({}, {'name': 0, 'picture': 0, 'identity': 0, 'sha256': 0, 'artifact_id': 0, 'when': 0}))
I = {'count': len(st), 'sent_total': sum(int(r.get('sent') or 0) for r in st), 'sent': dict(Counter(int(r.get('sent') or 0) for r in st)),
     'never_sent': sum(1 for r in st if not r.get('sent')),
     'days_since_last_sent': stats([round((NOW - at(r['last_sent_at'])).total_seconds() / 86400, 1) for r in st if at(r.get('last_sent_at'))]),
     'sent_last_7_days': sum(1 for r in st if at(r.get('last_sent_at')) and (NOW - at(r['last_sent_at'])).days < 7),
     'sent_last_30_days': sum(1 for r in st if at(r.get('last_sent_at')) and (NOW - at(r['last_sent_at'])).days < 30),
     'kept_by_week': dict(sorted(Counter(week(r.get('kept_at')) for r in st).items()))}
out['I_stickers'] = I

# ── J. memory_units: index-only census by id prefix, counts by scope class ──────────────────────────────────────
ids_only = db.memory_units.find({}, {'_id': 1}).hint([('_id', 1)])
prefix = Counter(re.sub(r'[-_][0-9a-f]{8,}.*$', '', str(r['_id']))[:12] for r in ids_only)
J = {'by_id_prefix': dict(prefix.most_common(12)), 'total': sum(prefix.values())}
J['active_by_scope_kind'] = {}
scopes = db.memory_units.distinct('scope_key')
J['scopes'] = len(scopes)
for scope in scopes:
    kind = 'global-safe' if scope == 'global-safe' else 'owner-private' if 'owner' in str(scope) or 'private' in str(scope) else 'scene'
    for status in ('active', 'superseded', 'tombstone'):
        n = db.memory_units.count_documents({'scope_key': scope, 'status': status})
        if n:
            k = '%s|%s' % (kind, status)
            J['active_by_scope_kind'][k] = J['active_by_scope_kind'].get(k, 0) + n
out['J_memory_units'] = J

# ── K. her documents now (sections, chars, inject vs tier) ──────────────────────────────────────────────────────
K = {}
persona = next(iter({h['_id'].split(':')[1] for h in heads if h['_id'].startswith('doc:')}), None)
for h in heads:
    if not h['_id'].startswith('doc:'):
        continue
    slug = h['_id'].rpartition('|')[0].split(':', 2)[2]
    rev = db.state_revisions.find_one({'_id': h['revision_id']}, {'content.kind': 1, 'content.sections.sid': 1, 'content.sections.inject': 1,
                                                                    'content.sections.visibility': 1, 'content.sections.tags': 1,
                                                                    'content.sections.body': 1})
    content = (rev or {}).get('content') or {}
    secs = content.get('sections') or []
    kind = head_kind(h['_id'])
    name = slug if kind in ('doc:persona', 'doc:voice', 'doc:self', 'doc:core', 'doc:work_log') else kind + '#%d' % (sum(1 for k in K if k.startswith(kind)) + 1)
    places = {(r['doc'], r['sid']): r['place'] for r in items}
    K[name] = {'kind': content.get('kind'), 'sections': len(secs), 'chars': stats([len(s.get('body') or '') for s in secs]),
               'inject': dict(Counter(s.get('inject') for s in secs)),
               'tier_place': dict(Counter(places.get((slug, s['sid'])) or 'no row' for s in secs)),
               'inject_vs_tier_differ': sum(1 for s in secs if places.get((slug, s['sid'])) and
                                            {'always': '随身', 'on_demand': '手边', 'never': '收着'}.get(s.get('inject')) != places.get((slug, s['sid']))),
               'visibility': dict(Counter(s.get('visibility') for s in secs)),
               'with_place_tags': sum(1 for s in secs if any(str(t).startswith('place:') for t in s.get('tags') or []))}
cs = db.state_heads.find_one({'_id': {'$regex': '^current_self:'}})
if cs:
    rev = db.state_revisions.find_one({'_id': cs['revision_id']}, {'content.body': 1, 'created_at': 1})
    K['current_self_legacy'] = {'body_chars': len(((rev or {}).get('content') or {}).get('body') or ''), 'last': day((rev or {}).get('created_at'))}
out['K_documents_now'] = K

json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', sys.argv[2])
client.close()
