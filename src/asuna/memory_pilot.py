"""The item index of tiered memory.

Her own items (persona and voice sections, the lines of `current_self` until `self` has sections, journal rows,
ledgers, `self` and `core`, each group's notes sections) are embedded on the memory route into one collection of their
own, `memory_shadow` (rows `item`), never the index her turns read; near-duplicate pairs within a store are written as
they are found (rows `pair`). Tiered memory reads both: `memory_tiers.deliver` and `recall` bring her items up from
these vectors, and the night list takes its merge pairs from them, so dropping the collection takes that away until
the index is rebuilt.

The index runs while tiered memory is on; each character turn wakes it, and it re-reads her items at most every
`SYNC_SECONDS`. The closed shadow pilot of ADR-062 phase 1 left rows `turn`, `recall` and `failure` here; each start
deletes those older than `TURN_ROWS_DAYS` (`prune`), and a failed sync still writes a `failure` row.
"""
from __future__ import annotations

import math
import queue
import re
import threading
import time
import uuid
from collections import Counter

from . import clock
from .evidence import canonical, sha
from .retrieval import EMBED_OPENING_CHARS, refused, terms
from .state import now
from .records import scenes as scene_records
from .records.view import ANY, View, is_text
from .store.words import AnyOf, Range, Set

TURN_ROWS_DAYS = 30               # the old pilot's turn rows older than this go (prune)
COLLECTION = 'memory_shadow'
# Every score below is on the (1 + cosine) / 2 scale (`_score`); tiered memory reads FLOOR and the slots from here.
FLOOR = 0.83                      # absolute floor on the vector score, from ADR-062 §1.1 (cosine 0.66)
OWN_SLOTS, SLOTS = 2, 6           # her own items may take at most two of a turn's six memory slots
DUPLICATE_ABOVE = 0.93            # pairs within a store written from this score up
SYNC_SECONDS = 600                # her items are re-read at most this often
QUEUE_SIZE = 32
SELF_ITEM = re.compile(r'\s*([-*·•]|\d+[.、)])')
SELF_ITEM_CHARS = 30


def own_items(store, persona):
    """Her items as the pilot indexes them: [{key, store, doc, sid, scope_key, visibility, inject, text, heading, tags,
    lexical}]."""
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
                        'tags': list(section.get('tags') or []),
                        'lexical': (section.get('heading') or '') + '\n' + body})

    def scope_of(section):
        return 'global-safe' if section.get('visibility') == 'public' else private

    for slug in ('persona', 'voice'):
        for section in (docs.read(slug)[1] or {}).get('sections') or []:
            add(slug, slug, section, scope_of(section))
    # current_self as it is split today: its list lines of some length (ADR-062 §1.1), until `self` has sections.
    from .records import heads as head_records
    head = None if (docs.read('self')[1] or {}).get('sections') else \
        head_records.current(store, 'current_self:' + persona, 'global-safe')
    for line in ((head[1]['content'].get('body') or '') if head else '').splitlines():
        if SELF_ITEM.match(line) and len(line.strip()) >= SELF_ITEM_CHARS:
            add('self', 'current_self', {'sid': sha(line.strip().encode())[:16], 'body': line.strip(),
                                         'visibility': 'public'}, 'global-safe')
    from . import documents
    for slug in documents.slugs(store, persona):
        for row in documents.entries(store, persona, slug).rows():
            add('journal', slug, row, scope_of(row))
    # Her ledgers and her self described as items (`self`, `core`), when she has them.
    for slug in docs.slugs():
        content = docs.read(slug)[1] or {}
        kind = 'ledger' if content.get('kind') == 'ledger' else slug if slug in ('self', 'core') else None
        for section in content.get('sections') or [] if kind else []:
            add(kind, slug, section, scope_of(section))
    for scene in scene_records.of_kind(store, 'group', fields=['scope_key']):
        content = docs.read(notes_slug(scene['_id']))[1]
        for section in (content or {}).get('sections') or []:
            add('group_notes', notes_slug(scene['_id']), section, scene['scope_key'])
    return out


# ── the owner of `memory_shadow` ──
# Its rows by kind (`row`: item, pair, turn, recall, failure), as stored (`fields` names what to return; `_id` always
# comes back). A time bound given None finds nothing (ADR-104 section 4); not given is `ANY`. Only this module writes
# them.
def rows(store, kind, *, since=ANY, status=ANY, min_score=ANY):
    """View: the rows of a kind (at or after `since`, ISO text; of this status; scored at least `min_score`)."""
    where = {'row': kind}
    if since is not ANY:
        where = {**where, 'at': Range(gte=since)} if is_text(since) else None
    if where is not None and status is not ANY:
        where['status'] = status
    if where is not None and min_score is not ANY:
        where = {**where, 'score': Range(gte=min_score)} if isinstance(min_score, (int, float)) else None
    return View(store, COLLECTION, where)


def prune(store, moment=None, days=TURN_ROWS_DAYS):
    """Delete the pilot's turn rows (and recall and failure rows) older than `days`; items and pairs stay. Their `at` is
    an ISO string, so a TTL index cannot do it. Returns how many went."""
    from datetime import timedelta
    cutoff = ((moment or clock.now()) - timedelta(days=days)).isoformat()
    return store.collection(COLLECTION).delete({'row': AnyOf(['turn', 'recall', 'failure']), 'at': Range(lt=cutoff)},
                                               many=True)


def _unit(vector):
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _score(a, b):
    """The vector index's cosine score, (1 + cosine) / 2, for unit vectors."""
    return (1 + sum(x * y for x, y in zip(a, b))) / 2


def attach(context, store, persona, retrieval):
    """Start the item index for a context builder that retrieves: the Pilot, else None. Its items come up in her turns from these
    vectors. `retrieval` makes its own embedding client.
    The process's one full tier sync runs first (memory_tiers.Tiers.sync): rows for what was
    written while the worker was down; every write makes its own."""
    from . import memory_tiers
    if persona:
        memory_tiers.Tiers(store, persona).sync()
    if not persona or getattr(context, 'retrieval', None) is None:
        return None
    context.pilot = Pilot(store, persona, retrieval()).start()
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


class Pilot:
    """One background thread: each turn wakes it (`submit`), and it re-reads her items off the reply path."""

    def __init__(self, store, persona, retrieval):
        self.store, self.persona, self.retrieval = store, persona, retrieval
        self.items, self.synced_at = [], 0.0
        self.wakes = queue.Queue(QUEUE_SIZE)
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._run, name='asuna-memory-pilot', daemon=True)
        self.collection = store.collection(COLLECTION)

    def start(self):
        self.worker.start()             # its index (row, at) is the catalog's, made by the store's ensure
        return self

    def close(self):
        self.stopping.set()
        if self.worker.ident is not None:
            self.worker.join(timeout=10)
        if hasattr(self.retrieval, 'close'):
            self.retrieval.close()

    # ── the reply path: one queue put ──────────────────────────────
    def submit(self):
        """A character turn happened: wake the index (a full queue drops the wake; one already waits)."""
        try:
            self.wakes.put_nowait(None)
        except queue.Full:
            pass

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.wakes.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if time.monotonic() - self.synced_at > SYNC_SECONDS or not self.items:
                    self.sync()
            except Exception as exc:          # a sync never disturbs her turns; its failure stays with its rows
                try:
                    self.collection.insert({'_id': 'failure:' + uuid.uuid4().hex, 'row': 'failure', 'at': now(),
                                            'error_type': type(exc).__name__})
                except Exception:
                    pass

    # ── the background ─────────────────────────────────────────────
    def sync(self):
        """Embed new and changed items, mark the ones gone, and write the near-duplicate pairs the changes made."""
        current = own_items(self.store, self.persona)
        known = {row['_id']: row for row in rows(self.store, 'item').each()}
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
                self.collection.update({'_id': item['key']}, Set({
                    'row': 'item', **fields, 'chars': len(item['text']), 'content_sha256': sha(item['text'].encode()),
                    'embedding': vector, 'embedding_revision': revision, 'embedding_opening_chars': opening,
                    'status': 'active' if vector else 'refused', 'synced_at': now()}), create=True)
        present = {item['key'] for item in current}
        gone = [key for key, row in known.items() if key not in present and row.get('status') != 'gone']
        if gone:
            self.collection.update({'_id': AnyOf(gone)}, Set({'status': 'gone', 'synced_at': now()}), many=True)
        active = {row['_id']: row for row in rows(self.store, 'item', status='active').each()}
        # Built aside and assigned once: a turn on another thread (deliver) reads the list while a write syncs it.
        self.items = [{**item, 'unit': _unit(active[item['key']]['embedding']), 'terms': terms(item['lexical'])}
                      for item in current if (active.get(item['key']) or {}).get('embedding')]
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
                    self.collection.update({'_id': 'pair:' + sha(canonical([first, second]))[:32]}, Set({
                        'row': 'pair', 'store': a['store'], 'items': [first, second], 'score': round(score, 4),
                        'at': now()}), create=True)
