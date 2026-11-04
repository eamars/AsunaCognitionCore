"""ADR-062 review, third read: what a turn carries, by conversation kind, from the episodes of the last N days
(structure only: context_chars, block sizes, carried refs, selected counts). Read-only, batched, paced."""
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

config = json.load(open(sys.argv[1], encoding='utf-8'))
DAYS = int(sys.argv[3]) if len(sys.argv) > 3 else 4
client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000)
db = client[config['database']]
NOW = datetime.now(timezone.utc)
since = (NOW - timedelta(days=DAYS)).isoformat()


def q(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else None


def stats(values):
    values = [v for v in values if v is not None]
    return {'n': len(values), 'p50': q(values, .5), 'p90': q(values, .9), 'max': max(values) if values else None}


def size(value):
    return len(json.dumps(value, ensure_ascii=False)) if value is not None else 0


started = list(db.audit_events.find({'type': 'turn.started', 'occurred_at': {'$gte': since}}, {'stream_id': 1, 'occurred_at': 1}))
ids = sorted({r['stream_id'] for r in started})
scenes = {s['_id']: s.get('kind') for s in db.scenes.find({}, {'kind': 1})}
BLOCKS = ('self_state_from_program', 'things_from_program', 'memories', 'relationship', 'people_from_program', 'group_notes_from_program',
          'ledgers_from_program', 'delivered_history', 'recent_thoughts_from_program', 'doc_refs_from_program', 'night_list_from_program',
          'memory_week_from_program', 'understanding_update_from_program', 'elsewhere_from_program', 'notes_from_program')
projection = {'episode_kind': 1, 'scene_id': 1, 'manifest.session_class': 1, 'manifest.context_chars': 1, 'manifest.carried': 1,
              'manifest.selected': 1, 'manifest.retrieval.path': 1, 'manifest.retrieval.coverage': 1, 'system_ref.carried': 1,
              **{'context.' + b: 1 for b in BLOCKS}}
turns = []
for start in range(0, len(ids), 100):
    for ep in db.episodes.find({'_id': {'$in': ids[start:start + 100]}}, projection):
        turns.append(ep)
    time.sleep(0.15)
out = {'read_at': NOW.isoformat(), 'days': DAYS, 'turns_started': len(ids), 'episodes_read': len(turns)}


def kind_of(ep):
    m = ep.get('manifest') or {}
    return '%s|%s|%s' % (scenes.get(ep.get('scene_id')) or '?', m.get('session_class') or '?', ep.get('episode_kind') or '?')


groups = defaultdict(list)
for ep in turns:
    groups[kind_of(ep)].append(ep)
out['turns_by_kind'] = {k: len(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
out['context_chars_by_kind'] = {k: stats([(ep.get('manifest') or {}).get('context_chars') for ep in v])
                                for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
out['block_chars_by_kind'] = {}
for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]:
    out['block_chars_by_kind'][k] = {b: stats([size((ep.get('context') or {}).get(b)) for ep in v if (ep.get('context') or {}).get(b) is not None])
                                     for b in BLOCKS if any((ep.get('context') or {}).get(b) is not None for ep in v)}
out['carried_refs_by_kind'] = {}
for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]:
    counts = defaultdict(list)
    for ep in v:
        carried = (ep.get('manifest') or {}).get('carried') or {}
        for slug, refs in carried.items():
            counts[slug].append(len(refs) if isinstance(refs, list) else (len(refs) if isinstance(refs, dict) else 0))
    out['carried_refs_by_kind'][k] = {slug: stats(n) for slug, n in counts.items()}
out['memories_count_by_kind'] = {k: dict(Counter(len((ep.get('context') or {}).get('memories') or []) for ep in v))
                                 for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]}
out['own_items_in_memories_by_kind'] = {k: sum(1 for ep in v for m in (ep.get('context') or {}).get('memories') or []
                                               if isinstance(m, dict) and m.get('kind') == 'own_item')
                                        for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]}
out['things_block_keys'] = dict(Counter(key for ep in turns for key in ((ep.get('context') or {}).get('things_from_program') or {})))
out['things_block_chars'] = stats([size((ep.get('context') or {}).get('things_from_program')) for ep in turns
                                   if (ep.get('context') or {}).get('things_from_program')])
out['moved_lines_shown'] = sum(len(((ep.get('context') or {}).get('things_from_program') or {}).get('moved') or []) for ep in turns)
out['relationship_block_chars_1to1'] = stats([size((ep.get('context') or {}).get('relationship')) for ep in turns
                                              if (ep.get('context') or {}).get('relationship')])
out['people_block_chars_groups'] = stats([size((ep.get('context') or {}).get('people_from_program')) for ep in turns
                                          if (ep.get('context') or {}).get('people_from_program')])
out['group_notes_block_chars'] = stats([size((ep.get('context') or {}).get('group_notes_from_program')) for ep in turns
                                        if (ep.get('context') or {}).get('group_notes_from_program')])
# group entries (ADR-082): does the person who woke the turn arrive with a short, a body in its place, or nothing
entries = [e for ep in turns for e in ((ep.get('context') or {}).get('people_from_program') or []) if isinstance(e, dict)]
out['group_entries'] = {'entries': len(entries), 'with_person_short': sum(1 for e in entries if e.get('short')),
                        'with_person_body_in_place': sum(1 for e in entries if e.get('short_body')),
                        'with_here_short': sum(1 for e in entries if e.get('here')),
                        'with_here_body_in_place': sum(1 for e in entries if e.get('here_body')),
                        'with_neither_layer': sum(1 for e in entries if not any(e.get(k) for k in ('short', 'short_body', 'here', 'here_body'))),
                        'entry_chars': stats([size(e) for e in entries])}
rel = [(ep.get('context') or {}).get('relationship') for ep in turns if isinstance((ep.get('context') or {}).get('relationship'), dict)]
out['relationship_block_1to1'] = {'turns': len(rel), 'keys': dict(Counter(k for r in rel for k in r)),
                                  'person_text_chars': stats([len(((r.get('person') or {}).get('text') or '')) for r in rel if isinstance(r.get('person'), dict)]),
                                  'here_text_chars': stats([len(str(r.get('here') or r.get('text') or '')) for r in rel])}
out['self_state_block_chars'] = stats([size((ep.get('context') or {}).get('self_state_from_program')) for ep in turns
                                       if (ep.get('context') or {}).get('self_state_from_program')])
json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', sys.argv[2])
client.close()
