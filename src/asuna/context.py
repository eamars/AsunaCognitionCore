from __future__ import annotations
import json
from .config import BUNDLE
from .evidence import canonical, sha
from .state import Store, Denied


class ContextBuilder:
    def __init__(self, store: Store, retrieval=None):
        self.store,self.retrieval=store,retrieval

    def prepare(self, event: dict, persona='P1'):
        scene=self.store.authorize(event['scene_id'],event['person_id'])
        scope=scene['scope_key']
        head,revision=self.store.head('persona:'+persona,'global-safe') or (None,None)
        if not revision:
            raise ValueError('REQUIRED_PERSONA_MISSING')
        body=revision['content']['body']
        content_lines=[line for line in body.splitlines() if line.strip() and not line.startswith('#')]
        if len(''.join(content_lines))<80:
            raise ValueError('REQUIRED_PERSONA_BODY_MISSING')
        relation=self.store.head('relationship:'+event['person_id'],scope)
        overlay=self.store.head('overlay:'+persona,scope)
        history=list(self.store.db.messages.find({'scene_id':scene['_id'],'$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]},{'text':1,'author':1,'direction':1,'delivery_state':1,'platform_event_id':1}).sort('scene_seq',-1).limit(12))
        undelivered=list(self.store.db.messages.find({'scene_id':scene['_id'],'direction':'outbound','delivery_state':{'$in':['READY','FAILED','UNKNOWN']}},{'text':1,'delivery_state':1,'author':1}).sort('scene_seq',-1).limit(4))
        tail_sources={x for m in history for x in (m['_id'],m.get('platform_event_id')) if x}
        if self.retrieval:
            memories, retrieval_manifest=self.retrieval.search(scope,scene['policy_epoch'],event['text'],exclude_sources=tail_sources)
        else:
            memories=list(self.store.db.memory_units.find({'$or':[{'scope_key':'global-safe','policy_epoch':1},{'scope_key':scope,'policy_epoch':scene['policy_epoch']}],'status':'active'},{'embedding':0}).sort('_id',1).limit(6))
            retrieval_manifest={'path':'scoped_recent_development_fallback','vector_verified':False}
        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','source_event_ids','status','historical_sources') if k in m} for m in memories]
        context={'scene_id':scene['_id'],'scope_key':scope,'policy_epoch':scene['policy_epoch'],'person_id':event['person_id'],
                 'relationship':relation[1]['content'] if relation else None,'overlay':overlay[1]['content'] if overlay else None,
                 'memories':facts,'delivered_history':list(reversed(history)),'undelivered_outbound_not_public':list(reversed(undelivered)),
                 'event':{'event_id':event['event_id'],'text':event['text'],'trusted_context_events':event.get('trusted_context_events',[])}}
        manifest={'persona_revision':head['revision_id'],'persona_sha256':sha(body.encode()),'relationship_revision':relation[0]['revision_id'] if relation else None,'scope_key':scope,'policy_epoch':scene['policy_epoch'],'selected':[m['_id'] for m in memories],'retrieval':retrieval_manifest,'context_sha256':sha(canonical(context))}
        system=(BUNDLE/'prompts/common.md').read_text(encoding='utf-8')+'\n'+body
        return system,context,manifest
