"""The shadow pilot of tiered memory (ADR-062 phase 1): which of her own items a turn would surface, measured only.

Her own items (persona sections, the lines of `current_self`, journal rows, each group's notes sections) are embedded
on the memory route into one collection of their own, `memory_shadow`, never the index her turns read. After each
character turn's context is prepared, a background thread scores them against the turn's query the way retrieval
scores memories (vector and lexical ranks fused; the vector score is the index's own, (1 + cosine) / 2), keeps at
most `OWN_SLOTS` of `SLOTS` above the absolute `FLOOR`, and writes one row: ids, scores, the turn's kind, the
conversation and its kind. Nothing is delivered and nothing reaches a prompt. A `recall` writes a row of its own.
Near-duplicate pairs within a store are written as they are found. `tools/memory_pilot_report.py` reads the rows.

`SHADOW_PILOT` is the switch: off, the Host starts no pilot and nothing is written. Dropping the collection removes
everything the pilot wrote (its index goes with it).
"""
from __future__ import annotations

import math
import queue
import re
import threading
import time
import uuid
from collections import Counter

from .evidence import canonical, sha
from .retrieval import EMBED_OPENING_CHARS, refused, terms
from .state import now

TIERS_VERSION = 1
SHADOW_PILOT = True               # the switch (ADR-062 phase 1)
COLLECTION = 'memory_shadow'
FLOOR = 0.83                      # absolute floor on the vector score, from ADR-062 §1.1
OWN_SLOTS, SLOTS = 2, 6           # her own items may take at most two of a turn's six memory slots
RECORD_ABOVE = 0.75               # candidates written per turn (the best SLOTS above this), so a report can try floors
DUPLICATE_ABOVE = 0.93            # pairs within a store written from this score up
SYNC_SECONDS = 600                # her items are re-read at most this often
QUEUE_SIZE = 32
SELF_ITEM = re.compile(r'\s*([-*·•]|\d+[.、)])')
SELF_ITEM_CHARS = 30


def own_items(store, persona):
    """Her items as the pilot indexes them: [{key, store, doc, sid, scope_key, visibility, inject, text, lexical}]."""
    from .documents import DocumentStore
    from .group_admin import notes_slug
    from .visibility import owner_private_scope
    private = owner_private_scope(persona)
    docs = DocumentStore(store, persona)
    out = []

    def add(kind, doc, section, scope_key):
        body = (section.get('body') or '').strip()
        if body:
            out.append({'key': 'shadow:' + sha(canonical([kind, doc, section['sid']]))[:32], 'store': kind, 'doc': doc,
                        'sid': section['sid'], 'scope_key': scope_key, 'visibility': section.get('visibility'),
                        'inject': section.get('inject'), 'text': body, 'heading': section.get('heading') or '',
                        'lexical': (section.get('heading') or '') + '\n' + body})

    def scope_of(section):
        return 'global-safe' if section.get('visibility') == 'public' else private

    for section in (docs.read('persona')[1] or {}).get('sections') or []:
        add('persona', 'persona', section, scope_of(section))
    # current_self as it is split today: its list lines of some length (ADR-062 §1.1).
    head = store.head('current_self:' + persona, 'global-safe')
    for line in ((head[1]['content'].get('body') or '') if head else '').splitlines():
        if SELF_ITEM.match(line) and len(line.strip()) >= SELF_ITEM_CHARS:
            add('self', 'current_self', {'sid': sha(line.strip().encode())[:16], 'body': line.strip(),
                                         'visibility': 'public'}, 'global-safe')
    for slug in store.db.journal_entries.distinct('slug', {'persona': persona}):
        for row in store.db.journal_entries.find({'persona': persona, 'slug': slug}).sort('seq', 1):
            add('journal', slug, row, scope_of(row))
    # Her ledgers and her self described as items (`self`, `core`), when she has them.
    for slug in docs.slugs():
        content = docs.read(slug)[1] or {}
        kind = 'ledger' if content.get('kind') == 'ledger' else slug if slug in ('self', 'core') else None
        for section in content.get('sections') or [] if kind else []:
            add(kind, slug, section, scope_of(section))
    for scene in store.db.scenes.find({'kind': 'group'}, {'scope_key': 1}):
        content = docs.read(notes_slug(scene['_id']))[1]
        for section in (content or {}).get('sections') or []:
            add('group_notes', notes_slug(scene['_id']), section, scene['scope_key'])
    return out


def _unit(vector):
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _score(a, b):
    """The vector index's cosine score, (1 + cosine) / 2, for unit vectors."""
    return (1 + sum(x * y for x, y in zip(a, b))) / 2


def attach(context, store, persona, retrieval):
    """Start the item index for a context builder that retrieves: the Pilot, else None. It runs when the pilot's
    switch is on (it then also writes its rows) or when tiered memory is on (memory_tiers.ENABLED: its items come up
    in her turns from these vectors, whatever the pilot's switch says). `retrieval` makes its own embedding client."""
    from . import memory_tiers
    if not (SHADOW_PILOT or memory_tiers.ENABLED) or not persona or getattr(context, 'retrieval', None) is None:
        return None
    context.pilot = Pilot(store, persona, retrieval(), logging=SHADOW_PILOT).start()
    return context.pilot


def rank(items, query, vector):
    """Her items the way retrieval ranks memories: vector and lexical ranks fused (terms common to over half of the
    items say nothing). Returns (keys in fused order, each key's vector score, the items by vector score)."""
    unit = _unit(vector)
    scores = {item['key']: _score(unit, item['unit']) for item in items}
    by_vector = sorted(items, key=lambda item: (-scores[item['key']], item['key']))[:24]
    frequencies = Counter(term for item in items for term in item['terms'])
    qterms = {t for t in terms(query) if frequencies[t] <= max(2, len(items) * .5)}

    def lexical(item):
        return sum(math.log(1 + len(items) / (1 + frequencies[t])) for t in qterms & item['terms'])
    by_lexical = sorted((item for item in items if lexical(item) > 0), key=lambda i: (-lexical(i), i['key']))[:24]
    fused = {}
    for ranked in (by_vector, by_lexical):
        for position, item in enumerate(ranked, 1):
            fused[item['key']] = fused.get(item['key'], 0) + 1 / (60 + position)
    return sorted(fused, key=lambda key: (-fused[key], key)), scores, by_vector


def admitted(ranked, floor=FLOOR, slots=OWN_SLOTS):
    """Of candidates in fused order [(key, score)], the ones a turn would surface: at most `slots`, each at the floor."""
    return [key for key, score in ranked if score >= floor][:slots]


class Pilot:
    """One background thread: turns are queued by `submit` and scored off the reply path."""

    def __init__(self, store, persona, retrieval, *, logging=True):
        self.store, self.persona, self.retrieval, self.logging = store, persona, retrieval, logging
        self.items, self.synced_at, self.dropped, self.submit_ms = [], 0.0, 0, None
        self.jobs = queue.Queue(QUEUE_SIZE)
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._run, name='asuna-memory-pilot', daemon=True)
        self.collection = store.db[COLLECTION]

    def start(self):
        self.collection.create_index([('row', 1), ('at', 1)])
        self.worker.start()
        return self

    def close(self):
        self.stopping.set()
        if self.worker.ident is not None:
            self.worker.join(timeout=10)
        if hasattr(self.retrieval, 'close'):
            self.retrieval.close()

    # ── the reply path: one queue put ──────────────────────────────
    def submit(self, *, query, vector, scope, private_scope, scene, session_class, turn_kind, event_id, recall):
        started = time.perf_counter()
        job = {'query': query, 'vector': vector, 'scope': scope, 'private_scope': private_scope,
               'scene_id': scene['_id'], 'scene_kind': scene.get('kind'), 'session_class': session_class,
               'turn_kind': turn_kind, 'event_id': event_id, 'recall': recall, 'at': now(),
               'previous_submit_ms': self.submit_ms}
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            self.dropped += 1
        # What the reply path paid, written with the next row (this one may already be running).
        self.submit_ms = round((time.perf_counter() - started) * 1000, 3)

    def _run(self):
        while not self.stopping.is_set():
            try:
                job = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.run_job(job)
            except Exception as exc:          # a measurement never disturbs her turns; its failure stays with its rows
                try:
                    self.collection.insert_one({'_id': 'failure:' + uuid.uuid4().hex, 'row': 'failure', 'at': now(),
                                                'error_type': type(exc).__name__})
                except Exception:
                    pass

    # ── the background ─────────────────────────────────────────────
    def run_job(self, job):
        started = time.perf_counter()
        if time.monotonic() - self.synced_at > SYNC_SECONDS or not self.items:
            self.sync()
        if not self.logging:
            return None                      # the index only: tiered memory reads its items, nothing is logged
        vector = job['vector']
        reused = vector is not None
        if vector is None:
            vector = self.retrieval.embed([job['query']], 'query')[0]
        readable = {'global-safe', job['scope'], *([job['private_scope']] if job['private_scope'] else [])}
        items = [item for item in self.items if item['scope_key'] in readable]
        order, scores, by_vector = rank(items, job['query'], vector)
        surfaced = admitted([(key, scores[key]) for key in order])
        stores = {item['key']: item['store'] for item in items}
        top = [{'item': item['key'], 'store': item['store'], 'score': round(scores[item['key']], 4)}
               for item in by_vector[:SLOTS] if scores[item['key']] >= RECORD_ABOVE]
        row = {'_id': ('recall:' if job['recall'] else 'turn:') + uuid.uuid4().hex, 'row': 'recall' if job['recall'] else 'turn',
               'at': job['at'], 'tiers_version': TIERS_VERSION, 'floor': FLOOR, 'event_id': job['event_id'],
               'turn_kind': job['turn_kind'], 'scene_id': job['scene_id'], 'scene_kind': job['scene_kind'],
               'session_class': job['session_class'], 'query_sha256': sha(job['query'].encode()), 'readable_items': len(items),
               'top': top, 'surfaced': [{'item': key, 'store': stores[key], 'score': round(scores[key], 4)} for key in surfaced],
               'vector_reused': reused, 'previous_submit_ms': job.get('previous_submit_ms'), 'dropped_before': self.dropped}
        row['job_ms'] = round((time.perf_counter() - started) * 1000, 1)
        self.collection.insert_one(row)
        if surfaced and not job['recall']:
            # Which conversation surfaced what: an item counts as memorable only from two different ones (ADR-062).
            self.collection.update_many({'_id': {'$in': surfaced}}, {'$addToSet': {'surfaced_in': job['scene_id']},
                                                                    '$inc': {'surfaced': 1}})
        return row

    def sync(self):
        """Embed new and changed items, mark the ones gone, and write the near-duplicate pairs the changes made."""
        current = own_items(self.store, self.persona)
        known = {row['_id']: row for row in self.collection.find({'row': 'item'})}
        revision = self.retrieval.revision
        changed = [item for item in current if (known.get(item['key']) or {}).get('content_sha256') != sha(item['text'].encode())
                   or (known.get(item['key']) or {}).get('embedding_revision') != revision]
        for start in range(0, len(changed), 16):
            batch = changed[start:start + 16]
            try:
                vectors = [(vector, None) for vector in self.retrieval.embed([item['text'] for item in batch], 'document')]
            except Exception as exc:
                if not refused(exc):
                    raise
                vectors = [self._embed_one(item['text']) for item in batch]
            for item, (vector, opening) in zip(batch, vectors):
                fields = {k: item[k] for k in ('store', 'doc', 'sid', 'scope_key', 'visibility', 'inject')}
                self.collection.update_one({'_id': item['key']}, {'$set': {
                    'row': 'item', **fields, 'chars': len(item['text']), 'content_sha256': sha(item['text'].encode()),
                    'embedding': vector, 'embedding_revision': revision, 'embedding_opening_chars': opening,
                    'status': 'active' if vector else 'refused', 'synced_at': now()}}, upsert=True)
        present = {item['key'] for item in current}
        gone = [key for key, row in known.items() if key not in present and row.get('status') != 'gone']
        if gone:
            self.collection.update_many({'_id': {'$in': gone}}, {'$set': {'status': 'gone', 'synced_at': now()}})
        rows = {row['_id']: row for row in self.collection.find({'row': 'item', 'status': 'active'})}
        self.items = []
        for item in current:
            row = rows.get(item['key'])
            if row and row.get('embedding'):
                self.items.append({**item, 'unit': _unit(row['embedding']), 'terms': terms(item['lexical'])})
        self._pairs({item['key'] for item in changed})
        self.synced_at = time.monotonic()

    def _embed_one(self, text):
        """As the memory indexer does: whole, else its opening part, else (None, None)."""
        for opening in (None, *[n for n in EMBED_OPENING_CHARS if n < len(text)]):
            try:
                return self.retrieval.embed([text if opening is None else text[:opening]], 'document')[0], opening
            except Exception as exc:
                if not refused(exc):
                    raise
        return None, None

    def _pairs(self, changed):
        """Near-duplicates within one store, for every pair a changed item is in (both ids, the score)."""
        if not changed:
            return
        for a in [item for item in self.items if item['key'] in changed]:
            for b in self.items:
                if b['key'] == a['key'] or b['store'] != a['store'] or (b['key'] in changed and b['key'] < a['key']):
                    continue
                score = _score(a['unit'], b['unit'])
                if score >= DUPLICATE_ABOVE:
                    first, second = sorted((a['key'], b['key']))
                    self.collection.update_one({'_id': 'pair:' + sha(canonical([first, second]))[:32]}, {'$set': {
                        'row': 'pair', 'store': a['store'], 'items': [first, second], 'score': round(score, 4),
                        'at': now()}}, upsert=True)


# ── the daily report (counts only; tools/memory_pilot_report.py) ──────
HEARTBEAT = 'presence'            # the episode kind of a heartbeat
FLOORS = tuple(round(0.80 + i / 100, 2) for i in range(11))
PAIR_LEVELS = (0.93, 0.95, 0.97)


def _quantile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def report(store, zone, since=None):
    """ADR-062 §7 phase 1, in counts: would-be surfacings per day by turn kind, the floor that keeps her own items at
    or under one a turn on average and none in heartbeats, near-duplicate pairs, recall hits, and what it cost."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(zone)
    shadow = store.db[COLLECTION]
    when = {'at': {'$gte': since}} if since else {}
    items = list(shadow.find({'row': 'item'}, {'embedding': 0}))
    turns = list(shadow.find({'row': 'turn', **when}))
    recalls = list(shadow.find({'row': 'recall', **when}))

    def day(row):
        return datetime.fromisoformat(str(row['at']).replace('Z', '+00:00')).astimezone(tz).date().isoformat()
    days = {}
    for row in turns:
        entry = days.setdefault(day(row), {'turns': Counter(), 'surfaced': Counter(), 'turns_with_any': Counter()})
        entry['turns'][row['turn_kind']] += 1
        entry['surfaced'][row['turn_kind']] += len(row['surfaced'])
        entry['turns_with_any'][row['turn_kind']] += bool(row['surfaced'])

    def admitted_at(row, floor):
        return min(OWN_SLOTS, sum(1 for top in row['top'] if top['score'] >= floor))
    floors = []
    for floor in FLOORS:
        counts = [admitted_at(row, floor) for row in turns]
        beats = [admitted_at(row, floor) for row in turns if row['turn_kind'] == HEARTBEAT]
        floors.append({'floor': floor, 'per_turn': round(sum(counts) / len(counts), 3) if counts else None,
                       'heartbeat_items': sum(beats), 'heartbeat_turns': len(beats)})
    fitting = [f['floor'] for f in floors if f['per_turn'] is not None and f['per_turn'] <= 1 and f['heartbeat_items'] == 0]
    store_of = {row['_id']: row.get('store') for row in items}
    places = {}
    for row in turns:
        for hit in row['surfaced']:
            places.setdefault(hit['item'], set()).add(row['scene_id'])
    memorable = Counter(store_of.get(key) for key, scenes in places.items() if len(scenes) >= 2)
    once = Counter(store_of.get(key) for key, scenes in places.items() if len(scenes) == 1)
    active = {row['_id'] for row in items if row.get('status') == 'active'}
    pairs = [row for row in shadow.find({'row': 'pair'}) if set(row['items']) <= active]
    by_ref = {(row.get('doc'), row.get('sid')): row for row in items}
    read = Counter()
    for event in store.db.audit_events.find({'type': 'recall.read', **({'occurred_at': {'$gte': since}} if since else {})},
                                            {'payload.sections_read': 1}):
        for section in (event.get('payload') or {}).get('sections_read') or []:
            row = by_ref.get((section.get('doc'), section.get('sid')))
            if row:
                read[row['_id']] += 1
    query_hits = Counter(hit['item'] for row in recalls for hit in row['top'] if hit['score'] >= FLOOR)
    rows = turns + recalls
    jobs = [row['job_ms'] for row in rows if row.get('job_ms') is not None]
    submits = [row['previous_submit_ms'] for row in rows if row.get('previous_submit_ms') is not None]
    return {
        'items': {kind: dict(Counter(row.get('status') for row in items if row.get('store') == kind))
                  for kind in sorted({row.get('store') for row in items})},
        'days': {key: {name: dict(value) for name, value in entry.items()} for key, entry in sorted(days.items())},
        'floors': floors, 'floor_that_fits': min(fitting) if fitting else None, 'floor_in_use': FLOOR,
        'surfaced_in_two_or_more_conversations': dict(memorable), 'surfaced_in_one_conversation': dict(once),
        'near_duplicate_pairs': {str(level): dict(Counter(row['store'] for row in pairs if row['score'] >= level))
                                 for level in PAIR_LEVELS},
        'recall': {'recalls': len(recalls),
                   'with_a_hit_at_the_floor': sum(1 for row in recalls if any(h['score'] >= FLOOR for h in row['top'])),
                   'items_hit_by_query': dict(Counter(store_of.get(key) for key in query_hits)),
                   'items_read_by_heading': dict(Counter(store_of.get(key) for key in read)),
                   'reads_by_heading': sum(read.values())},
        'cost': {'job_ms_median': _quantile(jobs, .5), 'job_ms_p90': _quantile(jobs, .9), 'job_ms_max': max(jobs, default=None),
                 'reply_path_ms_median': _quantile(submits, .5), 'reply_path_ms_max': max(submits, default=None),
                 'query_vector_reused': sum(1 for row in rows if row.get('vector_reused')), 'rows': len(rows),
                 'dropped': max((row.get('dropped_before') or 0 for row in rows), default=0),
                 'failures': shadow.count_documents({'row': 'failure', **when})},
    }
