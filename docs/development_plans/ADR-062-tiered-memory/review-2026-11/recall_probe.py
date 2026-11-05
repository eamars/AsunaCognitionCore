"""Where a recall's prepare spends its seconds, measured read-only against the live database and the checkout's code.

    python -X utf8 recall_probe.py <config/local.json> <scene id> <out.json>

Every write is refused by a guard (the collection handle's insert, replace, update, claim and delete, and Store.put
raise; Store.audit is a no-op that counts), the embedding route is never called (a stored vector of the scene stands
in for the query's), and the query is this script's own words. It prints timings, round trips, documents and bytes by
phase and by collection, and a cumulative profile of the prepare's functions: never a text of hers. It waits while a
turn of hers started in the last 90 seconds, then reads about three turns' worth (one search, one own-thoughts read,
three prepares). Written for the ADR-062 review of 2026-11 (the recall fix of ADR-117)."""
import cProfile
import io
import json
import math
import os
import pstats
import sys
import tempfile
import time
import traceback
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'src'))
import bson

CONFIG, SCENE_ID, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
config = json.load(open(CONFIG, encoding='utf-8'))
QUERY = '上次说好的那件事后来怎么安排的，还有今天的计划'          # this script's own words, not hers

# ── guard and instrumentation ──────────────────────────────────────────────
from asuna.store import Handle
from asuna.store import mongodb as mongo_mod
from asuna.state import Store


class WriteRefused(Exception):
    pass


def _refuse(name):
    def method(self, *args, **kwargs):
        raise WriteRefused(name)
    return method


for _name in ('insert', 'replace', 'update', 'claim', 'delete'):
    setattr(Handle, _name, _refuse(_name))
Store.put = _refuse('put')
AUDITS = Counter()
Store.audit = lambda self, stream, kind, payload, scope='operator': AUDITS.update([kind]) or {}

LOG = []                     # (phase, op, collection, seconds, docs, bytes)
PHASE = ['-']
ENCODE = [0.0]               # seconds spent measuring bytes, taken out of each phase's wall time
Adapter = mongo_mod.MongoAdapter
_get, _find, _count, _group, _nearest = Adapter.get, Adapter.find, Adapter.count, Adapter.group, Adapter.nearest
_NOT_GIVEN = object()


def _size(rows):
    t = time.perf_counter()
    n = sum(len(bson.BSON.encode(r)) for r in rows if isinstance(r, dict))
    ENCODE[0] += time.perf_counter() - t
    return n


def get(self, coll, id, fields=None):
    t = time.perf_counter(); row = _get(self, coll, id, fields); dt = time.perf_counter() - t
    LOG.append((PHASE[0], 'get', coll, dt, 1 if row else 0, _size([row] if row else [])))
    return row


def find(self, coll, where, sort=(), skip=0, limit=None, fields=None):
    t = time.perf_counter(); rows = list(_find(self, coll, where, sort, skip, limit, fields)); dt = time.perf_counter() - t
    LOG.append((PHASE[0], 'find', coll, dt, len(rows), _size(rows)))
    yield from rows


def count(self, coll, where, limit=None):
    t = time.perf_counter(); n = _count(self, coll, where, limit); dt = time.perf_counter() - t
    LOG.append((PHASE[0], 'count', coll, dt, 0, 0))
    return n


def group(self, coll, where, by, total=_NOT_GIVEN):
    t = time.perf_counter(); out = _group(self, coll, where, by) if total is _NOT_GIVEN else _group(self, coll, where, by, total)
    LOG.append((PHASE[0], 'group', coll, time.perf_counter() - t, len(out) if hasattr(out, '__len__') else 0, 0))
    return out


def nearest(self, space, vector, k, where):
    t = time.perf_counter(); out = _nearest(self, space, vector, k, where); dt = time.perf_counter() - t
    LOG.append((PHASE[0], 'nearest', space.collection, dt, len(out), 0))
    return out


Adapter.get, Adapter.find, Adapter.count, Adapter.group, Adapter.nearest = get, find, count, group, nearest
PHASES = {}


class phase:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        PHASE[0] = self.name; self.t = time.perf_counter(); self.e = ENCODE[0]; self.n = len(LOG)
        return self

    def __exit__(self, *exc):
        wall = time.perf_counter() - self.t - (ENCODE[0] - self.e)
        rows = LOG[self.n:]
        by = defaultdict(lambda: [0, 0, 0.0])
        for _, op, coll, dt, docs, size in rows:
            by[coll][0] += 1; by[coll][1] += size; by[coll][2] += dt
        PHASES[self.name] = {'seconds': round(wall, 3), 'round_trips': len(rows), 'db_seconds': round(sum(r[3] for r in rows), 3),
                             'docs': sum(r[4] for r in rows), 'bytes': sum(r[5] for r in rows),
                             'by_collection': {c: {'calls': n, 'bytes': b, 'seconds': round(s, 3)}
                                               for c, (n, b, s) in sorted(by.items(), key=lambda kv: -kv[1][2])}}
        PHASE[0] = '-'


# ── the store, the scene, the stand-in vector, the retrieval ───────────────
from asuna.evidence import Evidence, canonical, sha
from asuna import visibility
from asuna.records import memories as memory_records
from asuna.records import heads as head_records
from asuna.records import scenes as scene_records
from asuna.records import episodes as episode_records
import asuna.records.people as people_records
from asuna.retrieval import Retrieval, terms, UNVECTORED
from asuna.store.words import AnyOf, Range

people_records.save_label = lambda store, doc, *a, **k: doc      # a probe's person gets no label row: the entry goes on

store = Store(config)
scene = scene_records.get(store, SCENE_ID)
if not scene:
    sys.exit('no scene ' + SCENE_ID)
scope, epoch = scene['scope_key'], scene.get('policy_epoch', 1)
episode = next(store.collection('episodes').find({'scene_id': SCENE_ID}, (('_id', -1),), 0, 1, ['person_id', 'persona']), None)
if not episode:
    sys.exit('no episode in that scene')
persona, person_id = episode.get('persona') or 'P1', episode['person_id']
unit = next(store.collection('memory_units').find({'scope_key': scope, 'policy_epoch': epoch, 'status': 'active',
                                                   'embedding_status': 'READY'}, (), 0, 1, ['character_id', 'embedding']), None)
if not unit:
    sys.exit('no embedded unit in that scene')
# The worker's config carries the character id from the persona contribution; a checkout's local.json may not.
config['character_id'] = unit['character_id']
store.close(); store = Store(config)
STANDIN = unit['embedding']
me = unit['character_id']
private = visibility.owner_private_scope(persona)
pairs = [('global-safe', 1), (scope, epoch), (private, 1)]
evidence = Evidence(Path(tempfile.mkdtemp(prefix='recall-probe-')) / 'evidence', keep=20)
retrieval = Retrieval(store, evidence)
retrieval.weight_verified = True
retrieval._embed = lambda texts, purpose: [list(STANDIN) for _ in texts]
forgetting = {'half_life_days': 30, 'half_life_messages': 400, 'step_back_below': 0.1}


def active_now(seconds=90):
    since = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    return store.collection('audit_events').count({'type': 'turn.started', 'occurred_at': Range(gte=since)})


for attempt in range(6):
    if not active_now():
        break
    print('a turn started in the last 90 s; waiting 20 s', flush=True); time.sleep(20)
LOG.clear()
out = {'read_at': datetime.now(timezone.utc).isoformat(), 'scene_kind': scene.get('kind')}

# ── A. the pieces of retrieval.search ──────────────────────────────────────
with phase('A1_pool_fetch_4096'):
    rows = memory_records.readable(store, pairs, character=me, by=('occurred_at', '_id')).rows(newest_first=True, limit=4096, fields=UNVECTORED)
with phase('A2_heads'):
    heads = head_records.heads(store, scopes=['global-safe', scope, private], by='_id').rows(fields=['_id', 'revision_id'])
with phase('A3_cpu_state_revision_sha'):
    sha(canonical([heads, [(m['_id'], m.get('revision'), m['status']) for m in rows]]))
with phase('A4_cpu_terms'):
    qterms = terms(QUERY)
    document_terms = {m['_id']: terms(m['body_markdown']) for m in rows}
with phase('A4b_cpu_frequencies_counter'):
    frequencies = Counter(term for values in document_terms.values() for term in values)
with phase('A5_cpu_lexical_rank'):
    qterms = {t for t in qterms if frequencies[t] <= max(2, len(rows) * .5)}

    def lexical_score(m):
        return sum(math.log(1 + len(rows) / (1 + frequencies[t])) for t in qterms & document_terms[m['_id']])
    sorted((m for m in rows if lexical_score(m) > 0), key=lambda m: (-lexical_score(m), m['_id']))[:24]
with phase('A6_nearest_exact_k24'):
    memory_records.nearest(store, STANDIN, 24, pairs, character=me, revision=retrieval.revision)
with phase('A7_last_manifest_ids'):
    last = next(store.collection('audit_events').find({'type': 'retrieval.selected', 'scope_key': scope}, (('occurred_at', -1),), 0, 1, ['payload.ranks']), None)
ids = list(((last or {}).get('payload') or {}).get('ranks') or {})
with phase('A8_rechecks_%d' % len(ids)):
    found = sum(bool(memory_records.get(store, k, UNVECTORED, pairs=pairs, character=me, status='active')) for k in ids)
with phase('A9_forget_and_sequences'):
    sequences = retrieval._scene_sequences([scope])
    retrieval._forget({k: {'score': 1.0, 'origins': {}} for k in ids}, forgetting, sequences, False)
with phase('A10_search_whole'):
    selected, manifest = retrieval.search(scope, epoch, QUERY, exclude_sources=(), coverage_floor=0, forgetting=forgetting,
                                          record_use=False, automatic=False, linked_scopes=(), private_scope=private)
out.update(A_pool_rows=len(rows), A_ids_rechecked=len(ids), A_found=found, A_search_selected=len(selected), A_search_path=manifest.get('path'))

# ── B. own thoughts elsewhere ──────────────────────────────────────────────
groups = {s['scope_key']: s for s in scene_records.of_kind(store, 'group', fields=['scope_key', 'policy_epoch', 'kind', 'channel_id'])}
gpairs = [(k, s.get('policy_epoch', 1)) for k, s in groups.items()]
with phase('B1_monologue_fetch_2048'):
    mrows = memory_records.readable(store, gpairs, character=me, kind='monologue', by=('formed_at', '_id')).rows(newest_first=True, limit=2048, fields=UNVECTORED)
with phase('B2_cpu_terms_2048'):
    sorted(((len(qterms & terms(m.get('body_markdown') or '')), m['_id']) for m in mrows), reverse=True)
with phase('B3_nearest_monologue_k12'):
    memory_records.nearest(store, STANDIN, 12, gpairs, character=me, revision=retrieval.revision, kind='monologue')
with phase('B4_own_thoughts_whole'):
    units = retrieval.own_thoughts(gpairs, QUERY)
from asuna.context import ContextBuilder
with phase('B5_own_thoughts_elsewhere_whole'):
    elsewhere = ContextBuilder(store, retrieval).own_thoughts_elsewhere(scene, QUERY)
out.update(B_monologue_rows=len(mrows), B_units=len(units), B_elsewhere=len(elsewhere))

# ── C. the tier reads a recall's deliver makes ─────────────────────────────
from asuna import memory_tiers
tiers = memory_tiers.Tiers(store, persona)
with phase('C1_tiers_items_all'):
    items = tiers.items()
with phase('C2_tiers_rarity'):
    tiers.rarity(SCENE_ID)
with phase('C3_tiers_items_at_hand_put_away'):
    tiers.items(place=AnyOf([memory_tiers.AT_HAND, memory_tiers.PUT_AWAY]))
out['C_tier_items'] = len(items)

# ── D. everything else a recall's prepare builds (retrieval off, pilot off) ─
event = {'event_id': 'probe:' + uuid.uuid4().hex, 'scene_id': SCENE_ID, 'person_id': person_id, 'text': QUERY, 'episode_kind': 'external'}
plain = ContextBuilder(store, None)


def run_prepare(name):
    with phase(name):
        try:
            _, context, _ = plain._prepare(event, persona, True, 'external')
            return {'blocks': sorted(context), 'context_chars': len(json.dumps(context, ensure_ascii=False))}
        except WriteRefused as exc:
            frames = [f for f in traceback.extract_tb(exc.__traceback__) if 'asuna' in f.filename][-12:]
            return {'write_refused': str(exc), 'at': ['%s:%d %s' % (os.path.basename(f.filename), f.lineno, f.name) for f in frames]}


out['D1'] = run_prepare('D1_prepare_recall_cold')
out['D2'] = run_prepare('D2_prepare_recall_warm')
prof = cProfile.Profile()
PHASE[0] = 'D3_profiled'
prof.enable()
try:
    plain._prepare(event, persona, True, 'external')
except WriteRefused:
    pass
prof.disable()
PHASE[0] = '-'
stream = io.StringIO()
pstats.Stats(prof, stream=stream).sort_stats('cumulative').print_stats(r'asuna', 60)
root = str(Path(__file__).resolve().parents[4] / 'src' / 'asuna')
out['D3_profile_top'] = [' '.join(line.split()[:6]).replace(root, 'asuna') for line in stream.getvalue().splitlines()
                         if 'asuna' in line and '{' not in line][:60]
out['audits_refused'] = dict(AUDITS)
out['phases'] = PHASES
json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\n%-36s %8s %6s %8s %10s' % ('phase', 'seconds', 'trips', 'db_s', 'bytes'))
for name, p in PHASES.items():
    print('%-36s %8.3f %6d %8.3f %10d' % (name, p['seconds'], p['round_trips'], p['db_seconds'], p['bytes']))
print('audits (not written):', dict(AUDITS))
for key in ('D1', 'D2'):
    print(key, {k: v for k, v in out[key].items() if k != 'blocks'}, 'blocks', len(out[key].get('blocks', [])))
for name in ('D2_prepare_recall_warm', 'A10_search_whole', 'B5_own_thoughts_elsewhere_whole'):
    print(name, 'by collection:', json.dumps(PHASES[name]['by_collection'])[:1200])
print('profile top (cumulative):')
for line in out['D3_profile_top'][:45]:
    print('  ', line)
print('wrote', OUT)
store.close()
