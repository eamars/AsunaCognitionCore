from __future__ import annotations
import copy
import json
from .config import BUNDLE
from .evidence import canonical,sha
from .state import Store,Denied,Conflict
import jsonschema

REFLECTION=json.loads((BUNDLE/'schemas/reflection.schema.json').read_text(encoding='utf-8'))
MUTATION=json.loads((BUNDLE/'schemas/mutation.schema.json').read_text(encoding='utf-8'))


class MemoryService:
    def __init__(self,store:Store):self.store=store

    def chunk(self,scene_id):
        scene=self.store.db.scenes.find_one({'_id':scene_id})
        rows=list(self.store.db.messages.find({'scene_id':scene_id,'$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]}).sort('scene_seq',1))
        made=[]
        # UTF-8 bytes are a conservative upper bound for byte-fallback tokenizer
        # text tokens. Four messages, at most 900 bytes; zero overlap.
        group=[];size=0
        def save(group):
            if len(group)<2:return
            sources=[m['_id'] for m in group];key='chunk-'+sha(canonical(sources))
            if self.store.db.memory_units.find_one({'_id':key}):return
            body='\n'.join(m['author']+': '+m['text'] for m in group)
            made.append(self.store.put('memory_units',{'_id':key,'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],'character_id':'xiaoman','kind':'chat_chunk','body_markdown':body,'epistemic_type':'observed_fact','source_event_ids':sources,'depends_on':sources,'status':'active','embedding_status':'PENDING','chunk_budget_method':'UTF8_bytes_conservative_bound','overlap_tokens':0},stream='chunk:'+scene_id))
        for row in rows:
            cost=len((row['author']+': '+row['text']+'\n').encode())
            if cost>900:
                save(group);group=[];size=0;continue
            if size+cost>900 or len(group)==4:save(group);group=[];size=0
            group.append(row);size+=cost
        save(group)
        return made

    def proposal(self,proposal,request_scope,mutation_id):
        jsonschema.validate(proposal,MUTATION)
        if proposal['scope_key']!=request_scope:raise Denied('SCOPE_PROMOTION_DENIED')
        pair=self.store.head(proposal['entity_key'],request_scope)
        if not pair:raise Denied('UNKNOWN_STATE_ENTITY')
        head,base=pair
        if head['revision_id']!=proposal['base_revision_id']:raise Conflict('BASE_REVISION_STALE')
        content=copy.deepcopy(base['content'])
        for change in proposal['changes']:
            field=change['path'].removeprefix('/')
            if field not in {'body','familiarity','trust','closeness','tension'}:raise Denied('POLICY_PATH_DENIED')
            if content.get(field)!=change['old']:raise Conflict('OLD_VALUE_MISMATCH')
            content[field]=change['new']
        # Existing immutable metadata cannot be overwritten by the actor.
        writable={k:v for k,v in content.items() if k in {'body','familiarity','trust','closeness','tension'}}
        return self.store.mutate(proposal['entity_key'],request_scope,proposal['base_revision_id'],writable,proposal['source_ids'],request_scope,mutation_id)

    def reflect(self,lane,scope,entity,operation):
        pair=self.store.head(entity,scope)
        if not pair:raise Denied('UNKNOWN_STATE_ENTITY')
        head,base=pair
        sources=list(self.store.db.memory_units.find({'scope_key':{'$in':['global-safe',scope]},'status':'active'},{'embedding':0}).sort('_id',1).limit(24))
        persona=self.store.head('persona:P1','global-safe')[1]['content']['body']
        system=(BUNDLE/'prompts/common.md').read_text(encoding='utf-8')+'\n'+persona
        text=json.dumps({'scope_key':scope,'entity_key':entity,'base_revision_id':head['revision_id'],'current':base['content'],'sources':sources,'schema':REFLECTION},ensure_ascii=False)+'\n'+(BUNDLE/'prompts/reflect.md').read_text(encoding='utf-8')
        scene=self.store.db.scenes.find_one({'scope_key':scope})
        result=lane.generate('reflection:'+scope+':'+operation,operation,'REFLECT',text,system,scope_key=scope,policy_epoch=scene['policy_epoch'] if scene else 1)
        self.store.audit(operation,'reflection.output',{'request_refs':result.request_refs,'content':result.content,'finish_reason':result.finish_reason},scope)
        if result.finish_reason!='stop':raise ValueError('REFLECTION_INCOMPLETE')
        value=json.loads(result.content);jsonschema.validate(value,REFLECTION)
        if value['decision']=='propose':
            if value['proposal']['entity_key']!=entity:raise Denied('REFLECTION_TARGET_CHANGED')
            accepted=self.proposal(value['proposal'],scope,operation)
            value['accepted_revision']=accepted['_id']
        self.store.audit(operation,'reflection.result',value,scope)
        return value
