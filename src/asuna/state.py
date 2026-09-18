from __future__ import annotations
from datetime import datetime, timezone
import copy
import json
import uuid
from bson import BSON
from pymongo import ASCENDING, MongoClient, ReturnDocument, WriteConcern
from pymongo.errors import DuplicateKeyError
from .config import BUNDLE, validate_database
from .evidence import canonical, sha

COLLECTIONS = ('identities','scenes','messages','episodes','tasks','memory_units','state_heads',
               'state_revisions','sessions','audit_events','artifacts','sink_receipts','lane_receipts')


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

    def migrate(self):
        for name in COLLECTIONS:
            if name not in self.db.list_collection_names():
                self.db.create_collection(name, validator={'$jsonSchema':{'bsonType':'object','required':['_id','schema_version'],'properties':{'schema_version':{'enum':[1]}}}})
        specs = {
            'identities': [([('platform',1),('account_id',1)], {'unique':True})],
            'messages': [([('adapter_id',1),('scene_id',1),('platform_event_id',1)], {'unique':True,'partialFilterExpression':{'platform_event_id':{'$type':'string'}}}),
                         ([('publication_key',1)],{'unique':True,'partialFilterExpression':{'publication_key':{'$type':'string'}}}),
                         ([('scene_id',1),('scene_seq',1)],{})],
            'episodes': [([('scene_id',1),('source_event_id',1),('episode_kind',1)], {'unique':True})],
            'tasks': [([('request_key',1)], {'unique':True})],
            'memory_units': [([('scope_key',1),('status',1),('policy_epoch',1)],{})],
            'state_revisions': [([('mutation_id',1)], {'unique':True})],
            'sessions': [([('binding_key',1)], {'unique':True})],
            'audit_events': [([('stream_id',1),('seq',1)], {'unique':True})],
        }
        for name, indexes in specs.items():
            for keys, options in indexes:
                self.db[name].create_index(keys, **options)
        return {'database': self.name, 'collections':list(COLLECTIONS),'migration':1}

    def audit(self, stream: str, kind: str, payload: dict, scope: str='operator') -> dict:
        if self.fail_audit:
            raise OSError('AUDIT_UNAVAILABLE')
        for _ in range(50):
            previous = self.db.audit_events.find_one({'stream_id':stream}, sort=[('seq',-1)])
            event = {'_id':str(uuid.uuid4()),'schema_version':1,'stream_id':stream,'seq':previous['seq']+1 if previous else 1,
                     'type':kind,'scope_key':scope,'occurred_at':now(),'payload':copy.deepcopy(payload),
                     'prev_hash':previous['event_hash'] if previous else '0'*64}
            event['event_hash'] = sha(canonical(event))
            self._size(event)
            try:
                self.db.audit_events.insert_one(event)
                return event
            except DuplicateKeyError:
                continue
        raise Conflict('AUDIT_STREAM_BUSY')

    @staticmethod
    def _size(document):
        if len(BSON.encode(document)) > 1024*1024:
            raise ValueError('DOCUMENT_TOO_LARGE_USE_ARTIFACT')

    def put(self, collection: str, document: dict, *, expected: int | None = None, stream: str='state') -> dict:
        if collection not in COLLECTIONS or collection in ('audit_events',):
            raise Denied('COLLECTION_NOT_WRITABLE')
        doc = copy.deepcopy(document)
        doc['schema_version'] = 1
        doc['revision'] = 1 if expected is None else expected + 1
        operation = str(uuid.uuid4())
        doc['_last_op'] = operation
        self._size(doc)
        self.audit(stream,'state.intent',{'operation':operation,'collection':collection,'id':doc['_id'],'expected':expected},doc.get('scope_key','operator'))
        try:
            if expected is None:
                self.db[collection].insert_one(doc)
            else:
                result = self.db[collection].replace_one({'_id':doc['_id'],'revision':expected},doc)
                if result.modified_count != 1:
                    raise Conflict('STALE_REVISION')
        except DuplicateKeyError as exc:
            raise Conflict('DUPLICATE_ID') from exc
        self.audit(stream,'state.commit',{'operation':operation,'collection':collection,'document':doc},doc.get('scope_key','operator'))
        return doc

    def recover_commits(self):
        repaired = 0
        for name in COLLECTIONS:
            if name == 'audit_events':
                continue
            for doc in self.db[name].find({'_last_op':{'$exists':True}}):
                op = doc['_last_op']
                if not self.db.audit_events.find_one({'type':'state.commit','payload.operation':op}):
                    self.audit('recovery','state.commit',{'operation':op,'collection':name,'document':doc,'reconciled':True},doc.get('scope_key','operator'))
                    repaired += 1
        return repaired

    def get(self, collection: str, key: str, scope: str, *, operator: bool=False):
        if collection not in COLLECTIONS:
            raise Denied('UNKNOWN_OBJECT')
        doc = self.db[collection].find_one({'_id':key})
        if doc is None:
            return None
        if not operator and (collection in ('audit_events','artifacts','episodes','sessions','state_revisions') or doc.get('scope_key') not in ('global-safe',scope) or doc.get('status')=='tombstone'):
            raise Denied('OBJECT_SCOPE_DENIED')
        if not operator and collection == 'memory_units' and doc.get('kind')=='monologue':
            raise Denied('OPERATOR_ONLY_MONOLOGUE')
        return doc

    def authorize(self, scene_id: str, person_id: str) -> dict:
        scene = self.db.scenes.find_one({'_id':scene_id})
        if not scene or person_id not in scene['members']:
            raise Denied('SCENE_MEMBERSHIP_DENIED')
        return scene

    def identity(self, platform: str, account_id: str):
        doc = self.db.identities.find_one({'platform':platform,'account_id':account_id})
        if not doc:
            raise Denied('UNKNOWN_ACCOUNT')
        return doc['person_id']

    def seed(self, fixture=BUNDLE/'fixtures/world.json'):
        world = json.loads(fixture.read_text(encoding='utf-8'))
        for name, rows, key in [('identities',world['identities'],'person_id'),('scenes',world['scenes'],'scene_id'),('memory_units',world['memories'],'id')]:
            for row in rows:
                row=copy.deepcopy(row)
                row['_id']=row[key]
                if self.db[name].find_one({'_id':row['_id']}):
                    continue
                row.setdefault('policy_epoch',1)
                if name=='memory_units':
                    row.update(character_id='xiaoman',embedding_status='PENDING',depends_on=row['source_event_ids'])
                self.put(name,row,stream='seed')
        for persona,path in world['personas'].items():
            self.init_head('persona:'+persona,'global-safe',{'body':(BUNDLE/path).read_text(encoding='utf-8')},[])
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
               sources: list[str], request_scope: str, mutation_id: str, actor='character'):
        allowed = {'body','familiarity','trust','closeness','tension'}
        if actor!='character' or not entity.startswith(('persona:','overlay:','relationship:','scene_affect:')) or not set(content).issubset(allowed):
            raise Denied('POLICY_PATH_OR_ACTOR_DENIED')
        if scope != request_scope or (entity.startswith('persona:') and scope!='global-safe'):
            raise Denied('SCOPE_PROMOTION_DENIED')
        if not sources:
            raise Denied('MUTATION_REQUIRES_SOURCES')
        for source in sources:
            row=self.db.memory_units.find_one({'_id':source,'status':{'$ne':'tombstone'}})
            if not row or row['scope_key'] not in ('global-safe',scope):
                raise Denied('MUTATION_SOURCE_DENIED')
        for field in ('familiarity','trust','closeness','tension'):
            if field in content and (type(content[field]) is not int or not 0<=content[field]<=4):
                raise Denied('RELATIONSHIP_PARAMETER_RANGE')
        head,base=self.head(entity,scope) or (None,None)
        existing=self.db.state_revisions.find_one({'mutation_id':mutation_id})
        if existing:
            if head and head['revision_id']==existing['_id']:
                return existing
            raise Conflict('MUTATION_ALREADY_ATTEMPTED')
        if not head or head['revision_id']!=base_revision_id:
            raise Conflict('BASE_REVISION_STALE')
        new_id=sha(canonical({'mutation_id':mutation_id,'entity':entity,'scope':scope}))
        revision=self.put('state_revisions',{'_id':new_id,'mutation_id':mutation_id,'entity_key':head['_id'],'scope_key':scope,'content':content,'source_ids':sources,'parent_revision_id':base_revision_id},stream='mutation:'+mutation_id)
        self.put('state_heads',{**head,'revision_id':new_id},expected=head['revision'],stream='mutation:'+mutation_id)
        return revision

    def public_messages(self, scene: str, person: str):
        self.authorize(scene,person)
        return [{k:row[k] for k in ('_id','scene_id','text','author','reply_to','delivery_state') if k in row}
                for row in self.db.messages.find({'scene_id':scene,'direction':'outbound','delivery_state':'DELIVERED'}).sort('scene_seq',1)]
