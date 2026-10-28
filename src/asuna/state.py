"""The worker's store: every write goes through `Store.put` with an expected revision and is recorded in a
hash-chained audit stream.

`put`, `audit`, `recover_commits`, `ensure` (`migrate`), `nearest` and `ensure_vectors` go through the store's
MongoDB adapter and the shared layer's checks (asuna.store); `collection(name)` is a declared collection's handle,
and `db` the database itself for the code that still reads it directly. `get` refuses reads outside the caller's
scope, and `mutate` writes her relationship and scene-affect revisions only from sources she may read.
"""
from __future__ import annotations
from datetime import datetime, timezone
import copy
import json
import uuid
from pathlib import Path
from pymongo import MongoClient, WriteConcern
from .config import validate_database, character_id
from .evidence import canonical, sha
from .store import Checked
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
                  'notes': ('seen_in',)}                       # every turn that shows a note adds itself


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


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(RuntimeError):
    pass


class Denied(PermissionError):
    pass


class Store:
    def __init__(self, config: dict, database: str | None = None):
        self.config = config
        self.name = validate_database(config, database or config['database'])
        self.client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000,
                                  connectTimeoutMS=5000, timeoutMS=20000)
        self.db = self.client.get_database(self.name, write_concern=WriteConcern(w='majority', j=True))
        self.fail_audit = False

    @property
    def checked(self):
        """The shared layer over the MongoDB adapter on this store's database, derived from `db` as it is now."""
        if getattr(self, '_checked_db', None) is not self.db:
            from .store.mongodb import MongoAdapter       # only where a store is used: a module may stub pymongo
            self._checked, self._checked_db = Checked(MongoAdapter.over(self.db), CATALOG), self.db
        return self._checked

    @property
    def adapter(self):
        return self.checked.adapter

    def collection(self, name):
        """The handle of a declared collection: the store's words, checked against the catalog."""
        return self.checked.collection(name)

    def ensure(self) -> dict:
        """Create every declared collection with its validator and indexes, and drop the retired indexes;
        {collection: Ensured}. An index of a declared name that differs stops it (SchemaConflict)."""
        return self.checked.ensure()

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

    def get(self, collection: str, key: str, scope: str, *, operator: bool=False):
        if collection not in COLLECTIONS:
            raise Denied('UNKNOWN_OBJECT')
        doc = self.db[collection].find_one({'_id':key})
        if doc is None:
            return None
        if not operator and (collection in ('audit_events','artifacts','episodes','sessions','state_revisions','lane_receipts','tasks','plans') or doc.get('scope_key') not in ('global-safe',scope) or doc.get('status')=='tombstone'):
            raise Denied('OBJECT_SCOPE_DENIED')
        if not operator and collection == 'memory_units' and doc.get('kind')=='monologue':
            raise Denied('OPERATOR_ONLY_MONOLOGUE')
        return doc

    def identity(self, platform: str, account_id: str):
        doc = self.db.identities.find_one({'platform':platform,'account_id':account_id})
        if not doc:
            raise Denied('UNKNOWN_ACCOUNT')
        return doc['person_id']

    def seed(self, fixture):
        """Test-only synthetic world; persona paths are relative to the fixture file."""
        fixture = Path(fixture)
        world = json.loads(fixture.read_text(encoding='utf-8'))
        for name, rows, key in [('identities',world['identities'],'person_id'),('scenes',world['scenes'],'scene_id'),('memory_units',world['memories'],'id')]:
            for row in rows:
                row=copy.deepcopy(row)
                row['_id']=row[key]
                if self.db[name].find_one({'_id':row['_id']}):
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
        for rel in world['relationships']:
            self.init_head('relationship:'+rel['subject_id'],rel['scope_key'],rel,rel['source_ids'])

    def init_head(self, entity: str, scope: str, content: dict, sources: list[str]):
        key=entity+'|'+scope
        head=self.db.state_heads.find_one({'_id':key})
        if head:
            return head
        rev_id=str(uuid.uuid4())
        self.put('state_revisions',{'_id':rev_id,'entity_key':key,'mutation_id':'seed:'+key,'scope_key':scope,'content':content,'source_ids':sources,'parent_revision_id':None},stream='seed')
        return self.put('state_heads',{'_id':key,'scope_key':scope,'revision_id':rev_id},stream='seed')

    def head(self, entity: str, scope: str):
        head=self.db.state_heads.find_one({'_id':entity+'|'+scope})
        if not head:
            return None
        revision=self.db.state_revisions.find_one({'_id':head['revision_id']})
        return head,revision

    def mutate(self, entity: str, scope: str, base_revision_id: str, content: dict,
               sources: list[str], request_scope: str, mutation_id: str, actor='character',*,reason=None,change_class=None,linked_scopes=(),origin=None):
        # A relationship is her understanding in prose; no level fields (nothing ever wrote them).
        allowed = {'body', 'short'}           # her prose, and her one line for herself (ADR-082)
        # 跨场景只读联动（A2）里唯一被放宽的是「关系/偏好状态落在哪一份」：配置认定同一个人时，
        # 别名场景这一轮写的是 canonical 那一份。linked_scopes 就是本轮授权的那个场景 scope——
        # 来源证据仍只许落在 global-safe、目标 scope 或它里面；不传就等于原来的行为。
        linked = {item for item in (linked_scopes or ()) if isinstance(item, str) and item}
        readable_scopes = {'global-safe', scope} | linked
        # The persona is a document (ADR-009 §5); state heads hold only relationships and scene affect.
        if actor!='character' or not entity.startswith(('relationship:','scene_affect:')) or not set(content).issubset(allowed):
            raise Denied('POLICY_PATH_OR_ACTOR_DENIED')
        if scope != request_scope and not (request_scope in linked
                                           and entity.startswith(('relationship:',
                                                                  'scene_affect:'))):
            raise Denied('SCOPE_PROMOTION_DENIED')
        if not sources:
            raise Denied('MUTATION_REQUIRES_SOURCES')
        if reason is not None and (not isinstance(reason,str) or not 1<=len(reason)<=2000):raise Denied('INVALID_MUTATION_REASON')
        if change_class not in (None,'persona','relationship','interpretation','scene_affect'):raise Denied('INVALID_CHANGE_CLASS')
        from .records import memories as memory_records
        for source in sources:
            row=memory_records.get(self,source,erased=False)
            if not row or row['scope_key'] not in readable_scopes:
                raise Denied('MUTATION_SOURCE_DENIED')
        head,base=self.head(entity,scope) or (None,None)
        existing=self.db.state_revisions.find_one({'mutation_id':mutation_id})
        if existing:
            if existing.get('content')!=content or existing.get('source_ids')!=sources or existing.get('parent_revision_id')!=base_revision_id or existing.get('entity_key')!=entity+'|'+scope or existing.get('reason')!=reason or existing.get('change_class')!=change_class:
                raise Conflict('MUTATION_ID_CONTENT_CHANGED')
            ancestor=base
            for _ in range(512):
                if not ancestor:break
                if ancestor['_id']==existing['_id']:return existing
                parent=ancestor.get('parent_revision_id')
                ancestor=self.db.state_revisions.find_one({'_id':parent}) if parent else None
            raise Conflict('MUTATION_ALREADY_ATTEMPTED')
        # A relationship has no record until she first writes one: that write starts from no base.
        first=head is None and base_revision_id is None and entity.startswith('relationship:')
        if not first and (not head or head['revision_id']!=base_revision_id):
            self.audit('mutation:'+mutation_id,'state.conflict',{'entity':entity,'base_revision_id':base_revision_id,'reason':'BASE_REVISION_STALE'},scope)
            raise Conflict('BASE_REVISION_STALE')
        evidence_ids=set();visited=set()
        def roots(key,path):
            if key in path:raise Denied('SOURCE_CYCLE')
            if len(visited)>512:raise Denied('SOURCE_GRAPH_LIMIT')
            if key in visited:return
            visited.add(key)
            row=memory_records.get(self,key)
            if row:
                if row.get('status')=='tombstone' or row['scope_key'] not in readable_scopes:raise Denied('DERIVED_SOURCE_SCOPE_DENIED')
                descendants=row.get('source_event_ids',[])
                if descendants:
                    for child in descendants:roots(child,path|{key})
                else:evidence_ids.add(key)
            else:
                # Derived memory may cite a message/artifact rather than
                # another memory. Known internal sources retain their scope.
                from .records import messages as message_records
                line=message_records.get(self,key,fields=['scope_key','deletion_id'])
                known=[line] if line else []
                from .records import episodes as episode_records
                source=self.db.artifacts.find_one({'_id':key},{'scope_key':1,'deletion_id':1})
                if source:known.append(source)
                turn=episode_records.get(self,key,fields=['scope_key','deletion_id'])
                if turn:known.append(turn)
                known+=message_records.of_platform_event(self,key,fields=['scope_key','deletion_id'])
                if any(item.get('deletion_id') or item.get('scope_key') not in readable_scopes for item in known):raise Denied('DERIVED_SOURCE_SCOPE_DENIED')
                evidence_ids.add(key)
        for source in sources:roots(source,set())
        processed=set((base or {}).get('processed_source_ids',[]))
        if evidence_ids and evidence_ids.issubset(processed):
            raise Conflict('NO_NEW_SOURCE_EVENTS')
        new_id=sha(canonical({'mutation_id':mutation_id,'entity':entity,'scope':scope}))
        # origin: where and when a revision was written, for a record read in other conversations (understanding.py).
        metadata={k:v for k,v in {'reason':reason,'change_class':change_class,'origin':origin}.items() if v is not None}
        revision=self.put('state_revisions',{'_id':new_id,'mutation_id':mutation_id,'entity_key':entity+'|'+scope,'scope_key':scope,'content':content,'source_ids':sources,'processed_source_ids':sorted(processed|evidence_ids),'parent_revision_id':base_revision_id,**metadata},stream='mutation:'+mutation_id)
        if first:
            self.put('state_heads',{'_id':entity+'|'+scope,'scope_key':scope,'revision_id':new_id},stream='mutation:'+mutation_id)
        else:
            self.put('state_heads',{**head,'revision_id':new_id},expected=head['revision'],stream='mutation:'+mutation_id)
        return revision

    def public_messages(self, scene: str, person: str):
        from .records import scenes as scene_records          # the owner imports this module
        from .records import messages as message_records
        scene_records.authorize(self, scene, person)
        return [{k:row[k] for k in ('_id','scene_id','text','author','reply_to','delivery_state') if k in row}
                for row in message_records.spoken(self,scene).rows()]
