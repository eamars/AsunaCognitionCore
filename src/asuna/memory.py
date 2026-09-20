from __future__ import annotations
import copy
import json
from .config import BUNDLE
from .evidence import canonical,sha
from .state import Store,Denied,Conflict
from .queue import database_effects_lock
import jsonschema

REFLECTION=json.loads((BUNDLE/'schemas/reflection.schema.json').read_text(encoding='utf-8'))
MUTATION=json.loads((BUNDLE/'schemas/mutation.schema.json').read_text(encoding='utf-8'))


class MemoryService:
    def __init__(self,store:Store):self.store=store

    def commit_understanding(self,episode,body):
        """Commit bounded role-authored prose using the existing revision/CAS path."""
        scope=episode['scope_key'];operation=episode['_id']+':understanding'
        scene=self.store.authorize(episode['scene_id'],episode['person_id'])
        if (scene['scope_key'],scene['policy_epoch'])!=(scope,episode['policy_epoch']):
            raise Denied('UNDERSTANDING_SCOPE_OR_EPOCH_CHANGED')
        if body.strip()=='不更新':
            result={'state':'NO_CHANGE'}
        else:
            entity='relationship:'+episode['person_id']
            base_id=episode['manifest']['relationship_revision']
            base=self.store.db.state_revisions.find_one({'_id':base_id,'entity_key':entity+'|'+scope})
            if not base:raise Denied('UNDERSTANDING_BASE_NOT_IN_CONTEXT')
            if not body.strip():raise Denied('EMPTY_UNDERSTANDING')
            if body==base['content'].get('body'):
                result={'state':'NO_CHANGE'}
            else:
                sources=episode['monologue_refs']
                for key in sources:
                    if not self.store.db.memory_units.find_one({'_id':key,'episode_id':episode['_id'],
                            'scope_key':scope,'policy_epoch':episode['policy_epoch'],'status':'active'}):
                        raise Denied('UNDERSTANDING_SOURCE_NOT_CURRENT')
                content={k:v for k,v in base['content'].items() if k in {'body','familiarity','trust','closeness','tension'}}
                content['body']=body
                revision=self.store.mutate(entity,scope,base_id,content,sources,scope,operation,
                    reason='角色基于本轮真实输入与独白形成的理解；来源由程序关联。',change_class='interpretation')
                result={'state':'COMMITTED','entity':entity,'base_revision':base_id,
                    'accepted_revision':revision['_id'],'body':body,'source_ids':sources}
        self.store.audit(episode['_id'],'understanding.result',result,scope)
        return result

    def rollback(self,entity,scope,target_id,base_id,operation,*,operator=False):
        """Append an audited revision; do not erase history or reapply events."""
        if not operator:raise Denied('OPERATOR_ROLLBACK_REQUIRED')
        if not entity.startswith(('persona:','overlay:','relationship:','scene_affect:')):raise Denied('POLICY_ENTITY_DENIED')
        with database_effects_lock(self.store.name):
            pair=self.store.head(entity,scope)
            if not pair:raise Denied('UNKNOWN_STATE_ENTITY')
            head,current=pair;ancestors={};node=current
            for _ in range(512):
                if not node:break
                if node['_id'] in ancestors:raise Denied('REVISION_CYCLE')
                ancestors[node['_id']]=node
                node=self.store.db.state_revisions.find_one({'_id':node['parent_revision_id']}) if node.get('parent_revision_id') else None
            prior=self.store.db.state_revisions.find_one({'mutation_id':operation})
            if prior:
                if prior.get('rollback_target')==target_id and prior.get('parent_revision_id')==base_id and prior['_id'] in ancestors:return prior
                raise Conflict('ROLLBACK_OPERATION_REUSED_OR_UNCOMMITTED')
            if current['_id']!=base_id:raise Conflict('BASE_REVISION_STALE')
            target=ancestors.get(target_id)
            if not target or target.get('status')=='tombstone' or target.get('deletion_id') or target['scope_key']!=scope:
                raise Denied('ROLLBACK_TARGET_NOT_ACTIVE_ANCESTOR')
            for source in target.get('source_ids',[]):
                memory=self.store.db.memory_units.find_one({'_id':source})
                if not memory or memory.get('status')=='tombstone' or memory['scope_key'] not in ('global-safe',scope):raise Denied('ROLLBACK_SOURCE_INVALIDATED')
            value={'_id':sha(canonical([operation,entity,scope])),'mutation_id':operation,'entity_key':head['_id'],'scope_key':scope,
                'content':copy.deepcopy(target['content']),'source_ids':target.get('source_ids',[]),'processed_source_ids':current.get('processed_source_ids',[]),
                'parent_revision_id':base_id,'rollback_target':target_id,'change_class':'operator_rollback'}
            revision=self.store.put('state_revisions',value,stream='rollback:'+operation)
            self.store.put('state_heads',{**head,'revision_id':revision['_id']},expected=head['revision'],stream='rollback:'+operation)
            return revision

    def chunk(self,scene_id):
        scene=self.store.db.scenes.find_one({'_id':scene_id})
        rows=list(self.store.db.messages.find({'scene_id':scene_id,'$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]}).sort('scene_seq',1))
        made=[]
        for row in rows:
            if row.get('policy_epoch',1)!=scene['policy_epoch']:continue
            if row.get('memory_chunk_version')==2:continue
            # Stable per-message segments: adding another turn cannot regroup
            # old events or drop the last single message. No text is discarded.
            parts=[];part='';size=0
            for char in row['text']:
                cost=len(char.encode('utf-8'))
                if size+cost>900:parts.append(part);part='';size=0
                part+=char;size+=cost
            if part:parts.append(part)
            for index,body in enumerate(parts):
                key='chunk-'+sha(canonical([row['_id'],2,index]))
                if self.store.db.memory_units.find_one({'_id':key}):continue
                made.append(self.store.put('memory_units',{'_id':key,'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],
                    'character_id':'xiaoman','kind':'chat_chunk','body_markdown':body,
                    'epistemic_type':'reported_speech' if row['direction']=='inbound' else 'public_statement',
                    'speaker':row['author'],'scene_seq':row['scene_seq'],'occurred_at':row.get('occurred_at',row.get('received_at')),
                    'segment_index':index,'segment_count':len(parts),'source_event_ids':[row['_id']],
                    'depends_on':[row['_id']],'status':'active','embedding_status':'PENDING',
                    'chunk_budget_method':'UTF8_bytes_conservative_bound','overlap_tokens':0},stream='chunk:'+scene_id))
            self.store.put('messages',{**row,'memory_chunk_version':2},expected=row['revision'],stream='chunk:'+scene_id)
        return made

    def proposal(self,proposal,request_scope,mutation_id):
        jsonschema.validate(proposal,MUTATION)
        if proposal['scope_key']!=request_scope:raise Denied('SCOPE_PROMOTION_DENIED')
        self.store.audit('mutation:'+mutation_id,'state.proposed',proposal,request_scope)
        pair=self.store.head(proposal['entity_key'],request_scope)
        if not pair:raise Denied('UNKNOWN_STATE_ENTITY')
        head,base=pair
        if head['revision_id']!=proposal['base_revision_id']:
            self.store.audit('mutation:'+mutation_id,'state.conflict',{'base_revision_id':proposal['base_revision_id'],'reason':'BASE_REVISION_STALE'},request_scope)
            raise Conflict('BASE_REVISION_STALE')
        content=copy.deepcopy(base['content'])
        for change in proposal['changes']:
            field=change['path'].removeprefix('/')
            if field not in {'body','familiarity','trust','closeness','tension'}:raise Denied('POLICY_PATH_DENIED')
            if content.get(field)!=change['old']:raise Conflict('OLD_VALUE_MISMATCH')
            content[field]=change['new']
        # Existing immutable metadata cannot be overwritten by the actor.
        writable={k:v for k,v in content.items() if k in {'body','familiarity','trust','closeness','tension'}}
        return self.store.mutate(proposal['entity_key'],request_scope,proposal['base_revision_id'],writable,proposal['source_ids'],request_scope,mutation_id,reason=proposal['reason'],change_class=proposal['change_class'])

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
