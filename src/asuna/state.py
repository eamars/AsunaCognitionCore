"""The worker's store: every write goes through `Store.put` with an expected revision and is recorded in a
hash-chained audit stream.

`put`, `audit`, `recover_commits`, `ensure` (`migrate`), `nearest` and `ensure_vectors` go through the shared
layer's checks (asuna.store) over the adapter the registry opens (`asuna.store.adapters`); `collection(name)` is a
declared collection's handle, `blobs` its blob store. Her revisioned state (heads, `mutate`) is `records.heads`'.
"""
from __future__ import annotations
import copy
import json
import uuid
from pathlib import Path
from . import clock
from .config import validate_database, character_id
from .evidence import canonical, sha
from .store import Checked, Maintenance, adapters
from .store.catalog import CATALOG, Space
from .store.errors import DuplicateKey
from .store.words import Exists

COLLECTIONS = ('identities','scenes','messages','episodes','tasks','plans','memory_units','state_heads',
               'state_revisions','sessions','audit_events','artifacts','sink_receipts','lane_receipts',
               'affect_events','affect_amendments','affect_proposals','scene_people',
               # ADR-011: what the two brains say to each other about a task, and her improvement ideas.
               'task_messages','ideas',
               # ADR-016: the stickers she keeps; the candidates people posted in her groups (owner 2026-10-06).
               'stickers','sticker_pool',
               # The stickers she knows by fingerprint, in her words (owner 2026-10-06): kept, or looked at.
               'sticker_memory',
               # Her watchlist: people she wants to hear about when they speak anywhere (owner 2026-10-06).
               'watches',
               # Notes between her own conversations (ADR-018, owner 2026-10-07).
               'notes',
               # The program's notes to the developer agent (developer_inbox.py).
               'developer_inbox',
               # Who is in each group, as the channel adapter last fetched it (group_members.py, owner 2026-10-08).
               'group_members',
               # A Host taken away from outside, found at the next start (host_stops.py, 2026-10-08).
               'host_stops',
               # Her switches: a muted group, tools off in a conversation, a blocked person (switches.py, ADR-052).
               'switches',
               # Her own mute in each group, as the platform last said it (own_mute.py).
               'own_mutes',
               # Her running records, one row per entry, each change kept beside its entry (documents.JOURNALS).
               'journal_entries','journal_revisions',
               # Her questions, each to one or more places, with what came back (questions.py, ADR-061).
               'questions',
               # Faults of the channel lanes, by signature and hour (lane_faults.py, ADR-095).
               'lane_faults')
# Append-only ledgers (ADR-009 §6): written by insert only, through affect.AffectLedger.
INSERT_ONLY = ('audit_events','affect_events','affect_amendments','affect_proposals')


AUDIT_INLINE_LIMIT = 16 * 1024
# Counters written with $inc outside a revision (scene sequence, retrieval salience); not part of a document's digest.
COUNTER_FIELDS = {'scenes': ('sequence',), 'memory_units': ('salience',),
                  'watches': ('last_seen_at', 'appeared'),     # every line of a watched person moves these
                  'notes': ('seen_in',),                       # every turn that shows a note adds itself
                  # a stored file's last send drives its expiry, its last read the quota's order (records.artifacts)
                  'artifacts': ('last_sent_at', 'last_read_at')}


# Fields computed from a document's own content (a memory's embedding vector): a commit leaves them out and names
# them (`derived_left_out`); audit.verify_documents and the trace compare the stored document the same way.
DERIVED_FIELDS = {'memory_units': ('embedding',)}


def without_derived(collection, doc, fields=None):
    """(the document without its derived fields, the names left out)."""
    left = [k for k in (DERIVED_FIELDS.get(collection, ()) if fields is None else fields) if k in doc]
    return ({k: v for k, v in doc.items() if k not in left} if left else doc), left


def content_digest(collection, doc):
    skip = COUNTER_FIELDS.get(collection, ())
    return sha(canonical({k: v for k, v in doc.items() if k not in skip}))


def commit_payload(operation, collection, doc, **extra):
    """state.commit body: the document itself up to 16 KB, otherwise a reference (ADR-009 D-4).

    The hash chain covers the reference; audit.verify_documents compares the stored
    document with content_sha256, so tampering stays detectable.
    """
    doc, left = without_derived(collection, doc)
    if left:
        extra = {**extra, 'derived_left_out': left}
    body = canonical(doc)
    if len(body) <= AUDIT_INLINE_LIMIT:
        return {'operation': operation, 'collection': collection, 'document': doc, **extra}
    return {'operation': operation, 'collection': collection, 'id': doc['_id'], 'revision': doc.get('revision'),
            'content_sha256': content_digest(collection, doc), 'bytes': len(body), **extra}


def content_ref(text):
    """{content_sha256, bytes} for model output kept elsewhere (receipt or native transcript)."""
    raw = (text or '').encode()
    return {'content_sha256': sha(raw), 'bytes': len(raw)}


now = clock.stamp               # the core's one clock, as the ISO text records keep


class Conflict(RuntimeError):
    pass


class Denied(PermissionError):
    pass


class Store:
    def __init__(self, config: dict, database: str | None = None):
        self.config = config
        self.name = validate_database(config, database or config['database'])
        self.checked = Checked(adapters.open(config, self.name), CATALOG)
        self.fail_audit = False

    @classmethod
    def over(cls, checked, config: dict, name: str):
        """A store over a shared layer already built, opening nothing (the offline checks' fake store)."""
        store = cls.__new__(cls)
        store.config, store.name, store.checked, store.fail_audit = config, name, checked, False
        return store

    @property
    def adapter(self):
        return self.checked.adapter

    def collection(self, name):
        """The handle of a declared collection: the store's words, checked against the catalog."""
        return self.checked.collection(name)

    @property
    def maintenance(self):
        """Store-wide reads and writes by declared name (record, records, restore); used only by `audit.py`."""
        return Maintenance(self.checked)

    @property
    def blobs(self):
        """The blob store (write, open, delete, of_scope), each blob's metadata checked; used only by `blobs.py`."""
        return self.checked.blobs

    def ensure(self) -> dict:
        """Create every declared collection with its validator and indexes, and drop the retired indexes;
        {collection: Ensured}. An index of a declared name that differs stops it (SchemaConflict)."""
        return self.checked.ensure()

    def ping(self):
        """Whether the database answers: None, or the store's `Unavailable`."""
        return self.checked.ping()

    def close(self):
        """Close the store's connection to its database."""
        self.checked.close()

    def migrate(self):
        self.ensure()
        return {'database': self.name, 'collections': list(COLLECTIONS), 'migration': 3}

    def audit(self, stream: str, kind: str, payload: dict, scope: str='operator') -> dict:
        if self.fail_audit:
            raise OSError('AUDIT_UNAVAILABLE')
        events = self.collection('audit_events')
        for _ in range(50):
            previous = next(events.find({'stream_id': stream}, sort=[('seq', -1)], limit=1), None)
            event = {'_id':str(uuid.uuid4()),'schema_version':1,'stream_id':stream,'seq':previous['seq']+1 if previous else 1,
                     'type':kind,'scope_key':scope,'occurred_at':now(),'payload':copy.deepcopy(payload),
                     'prev_hash':previous['event_hash'] if previous else '0'*64}
            event['event_hash'] = sha(canonical(event))
            try:
                events.insert(event)
                return event
            except DuplicateKey:
                continue                     # a racing append took this seq: read the stream's newest again
        raise Conflict('AUDIT_STREAM_BUSY')

    def put(self, collection: str, document: dict, *, expected: int | None = None, stream: str='state',
            reset_counters: bool=False) -> dict:
        if collection not in COLLECTIONS or collection in INSERT_ONLY:
            raise Denied('COLLECTION_NOT_WRITABLE')
        doc = copy.deepcopy(document)
        doc['schema_version'] = 1
        doc['revision'] = 1 if expected is None else expected + 1
        if collection == 'state_revisions' or (collection == 'memory_units' and expected is None):
            doc.setdefault('created_at' if collection == 'state_revisions' else 'formed_at', now())
        operation = str(uuid.uuid4())
        doc['_last_op'] = operation
        records = self.collection(collection)
        # No intent record before the write (ADR-067): a single-document write is atomic, and a commit that never got
        # its record is found by the document's own _last_op (recover_commits). The record is checked (its size, its
        # declared fields) before anything is written.
        try:
            if expected is None:
                records.insert(doc)
            else:
                # The document comes from an earlier read: its counters (COUNTER_FIELDS) keep the values they reached
                # since, in the same write. Only a put that starts the record over (reset_counters) writes them.
                kept = () if reset_counters else COUNTER_FIELDS.get(collection, ())
                if not records.replace(doc, expected=expected, keep=kept):
                    self.audit(stream,'state.conflict',{'operation':operation,'collection':collection,'id':doc['_id'],'expected':expected,'reason':'STALE_REVISION'},doc.get('scope_key','operator'))
                    raise Conflict('STALE_REVISION: 这条记录刚被别处改过，这次没有写进去；不是参数的问题：读一次最新的再做')
        except DuplicateKey as exc:
            self.audit(stream,'state.conflict',{'operation':operation,'collection':collection,'id':doc['_id'],'expected':expected,'reason':'DUPLICATE_ID'},doc.get('scope_key','operator'))
            raise Conflict('DUPLICATE_ID') from exc
        self.audit(stream,'state.commit',commit_payload(operation,collection,doc),doc.get('scope_key','operator'))
        return doc

    def recover_commits(self):
        repaired = 0
        commits = self.collection('audit_events')
        for name in COLLECTIONS:
            if name in INSERT_ONLY:
                continue
            for doc in self.collection(name).find({'_last_op': Exists(True)}):
                op = doc['_last_op']
                if not commits.count({'type': 'state.commit', 'payload.operation': op}, limit=1):
                    self.audit('recovery','state.commit',commit_payload(op,name,doc,reconciled=True),doc.get('scope_key','operator'))
                    repaired += 1
        return repaired

    def ensure_vectors(self, space: Space, timeout: float = 45) -> bool:
        """Create the space's index, or bring an existing one's filter fields up to the space's (the old one keeps
        serving meanwhile); True once it can be queried, False if it cannot yet after `timeout` seconds."""
        return self.checked.ensure_vectors(space, timeout)

    def nearest(self, space: Space, vector, k: int, where) -> list[tuple[str, float]]:
        """The k records nearest to `vector` among those matching `where` (the store's words: equality, `AnyOf`, `And`,
        `Or` on the space's filter fields), best first, as (id, cosine similarity in [-1, 1]); exact, never
        approximate. Equal scores come in id order; which of several records tied at the k-th score are returned is
        the database's."""
        return self.checked.nearest(space, vector, k, where)

    def seed(self, fixture):
        """Test-only synthetic world; persona paths are relative to the fixture file."""
        fixture = Path(fixture)
        world = json.loads(fixture.read_text(encoding='utf-8'))
        for name, rows, key in [('identities',world['identities'],'person_id'),('scenes',world['scenes'],'scene_id'),('memory_units',world['memories'],'id')]:
            for row in rows:
                row=copy.deepcopy(row)
                row['_id']=row[key]
                if self.collection(name).get(row['_id']):
                    continue
                row.setdefault('policy_epoch',1)
                if name=='memory_units':
                    row.update(character_id=character_id(self.config),embedding_status='PENDING',depends_on=row['source_event_ids'])
                self.put(name,row,stream='seed')
        from .documents import DocumentStore
        for persona,path in world['personas'].items():
            docs=DocumentStore(self,persona)
            if not docs.head('persona'):
                docs.seed('persona','persona',(fixture.parent/path).read_text(encoding='utf-8'),path=Path(path).name)
        from .records import heads as head_records
        for rel in world['relationships']:
            head_records.init(self,'relationship:'+rel['subject_id'],rel['scope_key'],rel,rel['source_ids'])
