"""ADR-062 review, second read (structure only): the carried items' lapse horizon, offers by store, tool timings,
retrieval manifests (what a turn's six slots hold, duplicates within a turn), index near-duplicates by vector.
Read-only. Prints counts, sizes, dates, kinds, scores only."""
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from pymongo import MongoClient

config = json.load(open(sys.argv[1], encoding='utf-8'))
client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000)
db = client[config['database']]
NOW = datetime.now(timezone.utc)
out = {'read_at': NOW.isoformat()}


def q(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else None


def stats(values):
    values = [v for v in values if v is not None]
    return {'n': len(values), 'p50': q(values, .5), 'p90': q(values, .9), 'max': max(values) if values else None,
            'min': min(values) if values else None}


def at(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


# ── 1. carried items: how far from lapsing, and what keeps them up ─────────────────────────────────────────────
items = list(db.memory_tiers.find({'row': 'item'}, {'heading': 0}))
by_id = {r['_id']: r for r in items}
carried = [r for r in items if r['place'] == '随身']
S1 = {'carried': len(carried), 'by_store': dict(Counter(r['store'] for r in carried))}
horizon = []
for r in carried:
    since = (NOW - (at(r.get('memorable_at')) or NOW)).total_seconds() / 86400
    horizon.append({'store': r['store'], 'days_since_memorable': round(since, 1), 'stay_days': float(r.get('stay_days') or 14),
                    'days_left': round(float(r.get('stay_days') or 14) - since, 1), 'last_moment': r.get('last_moment'),
                    'added_days_ago': round((NOW - (at(r.get('added')) or NOW)).total_seconds() / 86400, 1)})
S1['days_since_memorable'] = stats([h['days_since_memorable'] for h in horizon])
S1['days_left_until_lapse'] = stats([h['days_left'] for h in horizon])
S1['days_left_by_store'] = {s: stats([h['days_left'] for h in horizon if h['store'] == s]) for s in sorted({h['store'] for h in horizon})}
S1['lapse_within_7_days'] = sum(1 for h in horizon if h['days_left'] <= 7)
S1['last_moment_carried'] = dict(Counter(h['last_moment'] for h in horizon))
S1['carried_memorable_in_last_14_days'] = sum(1 for h in horizon if h['days_since_memorable'] <= 14)
S1['carried_added_days_ago'] = stats([h['added_days_ago'] for h in horizon])
S1['carried_per_group_doc'] = sorted(Counter(r['doc'] for r in carried if r['store'] == 'group_notes').values(), reverse=True)
# what memorable moments were counted on carried items, by kind, over the whole item set: last_moment × place
S1['last_moment_by_place'] = dict(Counter('%s|%s' % (r['place'], r.get('last_moment')) for r in items))
# surfaced_again on carried items comes from `deliver`'s "would have surfaced" path
S1['carried_with_surfaced_in_2plus'] = sum(1 for r in carried if len(r.get('surfaced_in') or []) >= 2)
# items she let go that came back up (and how long after)
moves = list(db.memory_tiers.find({'row': 'move'}, {'heading': 0}))
by_item = defaultdict(list)
for m in moves:
    by_item[m['item']].append(m)
back_after_let_go = []
for item_id, ms in by_item.items():
    ms.sort(key=lambda m: m.get('at') or '')
    for i, m in enumerate(ms):
        if m.get('reason') == 'let_go' and m.get('from') == '随身':
            later = [n for n in ms[i + 1:] if n.get('to') == '随身']
            if later:
                back_after_let_go.append(round((at(later[0]['at']) - at(m['at'])).total_seconds() / 86400, 1))
S1['let_go_from_carried'] = sum(1 for m in moves if m.get('reason') == 'let_go' and m.get('from') == '随身')
S1['let_go_then_back_up'] = {'n': len(back_after_let_go), 'days': stats(back_after_let_go)}
# offers by what × store, and whether an offered item was acted on (rewritten / moved) within 2 days
offers = list(db.memory_tiers.find({'row': 'offer'}))
S1['offers_by_what_store'] = dict(Counter('%s|%s' % (o.get('what'), (by_id.get(o.get('item')) or {}).get('store')) for o in offers))
S1['offered_items_distinct_by_what'] = dict(Counter(o.get('what') for o in {(o.get('what'), o.get('item')): o for o in offers}.values()))
acted = Counter()
for o in offers:
    row = by_id.get(o.get('item')) or {}
    t = at(o.get('at'))
    if not t:
        continue
    rewritten = at(row.get('rewritten_at'))
    moved = any(at(m.get('at')) and 0 <= (at(m['at']) - t).total_seconds() <= 2 * 86400 for m in by_item.get(o.get('item'), []))
    if (rewritten and 0 <= (rewritten - t).total_seconds() <= 2 * 86400) or moved:
        acted[o.get('what')] += 1
S1['offers_acted_on_within_2_days'] = dict(acted)
S1['offers_total_by_what'] = dict(Counter(o.get('what') for o in offers))
out['S1_carried_and_offers'] = S1

# ── 2. tool timings (tool.time audit: duration_s) ───────────────────────────────────────────────────────────────
rows = list(db.audit_events.find({'type': 'tool.time', 'occurred_at': {'$gte': '2026-10-14'}},
                                 {'occurred_at': 1, 'payload.tool': 1, 'payload.duration_s': 1, 'payload.outcome': 1}))
S2 = {'rows': len(rows)}
by_tool = defaultdict(list)
for r in rows:
    p = r.get('payload') or {}
    if isinstance(p.get('duration_s'), (int, float)):
        by_tool[p.get('tool')].append(round(p['duration_s'], 3))
S2['duration_s_by_tool'] = {tool: stats(v) for tool, v in sorted(by_tool.items(), key=lambda kv: -len(kv[1]))[:14]}
wk = defaultdict(list)
for r in rows:
    p = r.get('payload') or {}
    if p.get('tool') == 'recall' and isinstance(p.get('duration_s'), (int, float)):
        y, w, _ = at(r['occurred_at']).isocalendar()
        wk['%d-W%02d' % (y, w)].append(round(p['duration_s'], 3))
S2['recall_duration_by_week'] = {k: stats(v) for k, v in sorted(wk.items())}
wk = defaultdict(list)
for r in rows:
    p = r.get('payload') or {}
    if p.get('tool') == 'write_document' and isinstance(p.get('duration_s'), (int, float)):
        y, w, _ = at(r['occurred_at']).isocalendar()
        wk['%d-W%02d' % (y, w)].append(round(p['duration_s'], 3))
S2['write_document_duration_by_week'] = {k: stats(v) for k, v in sorted(wk.items())}
S2['outcomes'] = dict(Counter((r.get('payload') or {}).get('outcome') for r in rows))
out['S2_tool_time'] = S2

# ── 3. retrieval manifests, last 7 days: what the six slots hold; duplicates within a turn ──────────────────────
since = (NOW - timedelta(days=7)).isoformat()
sel = list(db.audit_events.find({'type': 'retrieval.selected', 'occurred_at': {'$gte': since}},
                                {'occurred_at': 1, 'scope_key': 1, 'payload.path': 1, 'payload.coverage': 1, 'payload.coverage_score': 1,
                                 'payload.selected': 1, 'payload.cache_hit': 1, 'payload.lexical_candidate_count': 1,
                                 'payload.vector_ranks': 1, 'payload.in_view': 1, 'payload.excluded': 1}))
S3 = {'manifests_7d': len(sel), 'by_path': dict(Counter((r.get('payload') or {}).get('path') for r in sel)),
      'by_coverage': dict(Counter((r.get('payload') or {}).get('coverage') for r in sel)),
      'cache_hit': dict(Counter(bool((r.get('payload') or {}).get('cache_hit')) for r in sel)),
      'lexical_candidate_count': stats([(r.get('payload') or {}).get('lexical_candidate_count') for r in sel]),
      'lexical_pool_capped_4096': sum(1 for r in sel if (r.get('payload') or {}).get('lexical_candidate_count') == 4096),
      'selected_count': dict(Counter(len((r.get('payload') or {}).get('selected') or []) for r in sel)),
      'coverage_score': stats([(r.get('payload') or {}).get('coverage_score') for r in sel])}


def prefix(key):
    return str(key).split('-', 1)[0]


S3['selected_by_prefix'] = dict(Counter(prefix(k) for r in sel for k in (r.get('payload') or {}).get('selected') or []))
S3['top_vector_score'] = stats([max((v.get('score', -1) for v in (r.get('payload') or {}).get('vector_ranks') or []), default=None)
                                for r in sel])
S3['excluded_reasons'] = dict(Counter(e.get('reason') for r in sel for e in (r.get('payload') or {}).get('excluded') or []))
S3['in_view_count'] = stats([len((r.get('payload') or {}).get('in_view') or []) for r in sel])
# same selection as the previous manifest in the same scope
prev = {}
same, total = 0, 0
for r in sorted(sel, key=lambda r: r.get('occurred_at') or ''):
    key = r.get('scope_key')
    s = tuple((r.get('payload') or {}).get('selected') or [])
    if key in prev:
        total += 1
        if s and s == prev[key]:
            same += 1
    prev[key] = s
S3['same_selection_as_previous_in_scope'] = {'turns': total, 'same': same}
# how often a memory id is selected across the week (concentration)
counts = Counter(k for r in sel for k in (r.get('payload') or {}).get('selected') or [])
S3['distinct_units_selected'] = len(counts)
S3['top20_share_of_selections'] = round(sum(n for _, n in counts.most_common(20)) / max(1, sum(counts.values())), 3)
S3['units_selected_once'] = sum(1 for n in counts.values() if n == 1)
# duplicates within a turn: units whose source events overlap (a chunk and the summary covering it, two segments of
# one message), and summaries with the same source window
ids = list(counts)
units = {}
for start in range(0, len(ids), 500):
    for u in db.memory_units.find({'_id': {'$in': ids[start:start + 500]}},
                                  {'kind': 1, 'source_event_ids': 1, 'scene_seq': 1, 'segment_index': 1, 'segment_count': 1,
                                   'source_window': 1, 'status': 1, 'supersedes': 1, 'corrected_by': 1, 'embedding_opening_chars': 1}):
        units[u['_id']] = u
    time.sleep(0.05)
S3['selected_units_fetched'] = len(units)
S3['selected_units_by_kind'] = dict(Counter(u.get('kind') for u in units.values()))
S3['selected_units_status'] = dict(Counter(u.get('status') for u in units.values()))
S3['selected_units_with_corrected_by'] = sum(1 for u in units.values() if u.get('corrected_by'))
S3['selected_units_embedded_by_opening'] = sum(1 for u in units.values() if u.get('embedding_opening_chars'))
overlap_turns, seg_turns, chunk_in_summary_turns = 0, 0, 0
for r in sel:
    chosen = [units.get(k) for k in (r.get('payload') or {}).get('selected') or []]
    chosen = [u for u in chosen if u]
    events = [set(u.get('source_event_ids') or []) for u in chosen]
    pair_overlap = any(events[i] & events[j] for i in range(len(events)) for j in range(i + 1, len(events)))
    overlap_turns += pair_overlap
    segs = Counter((tuple(sorted(u.get('source_event_ids') or [])), u.get('kind')) for u in chosen if u.get('kind') == 'chat_chunk')
    seg_turns += any(n > 1 for n in segs.values())
    chunks = [u for u in chosen if u.get('kind') == 'chat_chunk']
    summaries = [u for u in chosen if u.get('kind') == 'dialogue_summary']
    covered = False
    for c in chunks:
        seq = c.get('scene_seq')
        for s in summaries:
            w = s.get('source_window') if isinstance(s.get('source_window'), dict) else {}
            lo, hi = w.get('from_seq', w.get('from')), w.get('to_seq', w.get('to'))
            if isinstance(seq, int) and isinstance(lo, int) and isinstance(hi, int) and lo <= seq <= hi and (set(c.get('source_event_ids') or []) & set(s.get('source_event_ids') or []) or True):
                covered = True
    chunk_in_summary_turns += covered
S3['turns_with_two_units_sharing_a_source_event'] = overlap_turns
S3['turns_with_two_segments_of_one_message'] = seg_turns
S3['turns_with_a_chunk_inside_a_selected_summary_window'] = chunk_in_summary_turns
out['S3_retrieval_7d'] = S3

# ── 4. the item index: near-duplicates by vector (local computation after one read) ────────────────────────────
rows = list(db.memory_shadow.find({'row': 'item', 'status': 'active'}, {'embedding': 1, 'store': 1, 'doc': 1, 'sid': 1, 'chars': 1,
                                                                        'content_sha256': 1, 'synced_at': 1}))
tier = {(r['doc'], r['sid']): r for r in items}
keys = [r for r in rows if r.get('embedding')]
M = np.array([r['embedding'] for r in keys], dtype=np.float64)
M /= np.linalg.norm(M, axis=1, keepdims=True)
S = (1 + M @ M.T) / 2
np.fill_diagonal(S, 0)
S4 = {'indexed_active_with_vector': len(keys), 'dimensions': int(M.shape[1])}
levels = (0.90, 0.93, 0.95, 0.97, 0.99)
within, across = {}, {}
iu = np.triu_indices(len(keys), 1)
scores = S[iu]
for lvl in levels:
    sel_idx = np.where(scores >= lvl)[0]
    w, a = Counter(), Counter()
    for n in sel_idx:
        i, j = iu[0][n], iu[1][n]
        si, sj = keys[i]['store'], keys[j]['store']
        if si == sj:
            w[si] += 1
        else:
            a['%s×%s' % tuple(sorted((si, sj)))] += 1
    within[str(lvl)] = dict(w)
    across[str(lvl)] = dict(a)
S4['pairs_within_store_by_level'] = within
S4['pairs_across_stores_by_level'] = across
# for pairs at 0.93+ in non-journal stores: are the two in different places (one carried, one not), and how far apart
# in time were they added (the same idea written again later)
detail = Counter()
gaps = defaultdict(list)
for n in np.where(scores >= 0.93)[0]:
    i, j = iu[0][n], iu[1][n]
    a_, b_ = keys[i], keys[j]
    if a_['store'] != b_['store']:
        continue
    ta, tb = tier.get((a_['doc'], a_['sid'])) or {}, tier.get((b_['doc'], b_['sid'])) or {}
    places = tuple(sorted((ta.get('place') or '?', tb.get('place') or '?')))
    detail['%s|%s' % (a_['store'], '/'.join(places))] += 1
    da, db_ = at(ta.get('added')), at(tb.get('added'))
    if da and db_:
        gaps[a_['store']].append(round(abs((da - db_).total_seconds()) / 86400, 1))
S4['pairs_0.93_same_store_by_places'] = dict(detail)
S4['pairs_0.93_days_between_added_by_store'] = {k: stats(v) for k, v in gaps.items()}
# nearest-neighbour score per item, by store: how crowded each store is
nn = S.max(axis=1)
S4['nearest_neighbour_by_store'] = {s: stats([round(float(nn[i]), 3) for i, r in enumerate(keys) if r['store'] == s])
                                    for s in sorted({r['store'] for r in keys})}
S4['items_with_neighbour_over_0.90_by_store'] = dict(Counter(r['store'] for i, r in enumerate(keys) if nn[i] >= 0.90))
S4['items_with_neighbour_over_0.95_by_store'] = dict(Counter(r['store'] for i, r in enumerate(keys) if nn[i] >= 0.95))
# the legacy current_self lines still indexed
S4['indexed_docs_without_tier_row'] = dict(Counter(r['doc'] if r['doc'] in ('current_self',) else 'other' for r in keys
                                                   if (r['doc'], r['sid']) not in tier))
out['S4_index_near_duplicates'] = S4

json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', sys.argv[2])
client.close()
