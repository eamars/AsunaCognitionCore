"""Local embeddings and server-side, prefiltered Mongo vector retrieval."""
from __future__ import annotations
import math
import re
import time
from collections import Counter
from pymongo.operations import SearchIndexModel
from .evidence import Evidence, LocalHttp, canonical, sha
from .state import Store, now


def terms(text):
    # Deterministic lexical supplement; never consumes gold/oracle data.
    words=re.findall(r'[a-zA-Z0-9_-]+|[\u4e00-\u9fff]+',text.lower())
    return {part for word in words for part in ([word] if word.isascii() else [word[i:i+2] for i in range(max(1,len(word)-1))])}


class Retrieval:
    index_name='asuna_memory_v1'

    def __init__(self, store: Store, evidence: Evidence):
        self.store,self.evidence=store,evidence
        self.cfg=store.config['embedding']
        self.http=LocalHttp(evidence)
        # A routing fingerprint is explicitly not a verified weight revision.
        self.revision='route-'+sha(canonical({k:self.cfg.get(k) for k in ('base_url','model','dimensions','query_prefix','document_prefix')}))
        self.dim=768

    def embed(self, texts, purpose):
        prefix=self.cfg.get('query_prefix','search_query: ') if purpose=='query' else self.cfg.get('document_prefix','search_document: ')
        data=self.http.request('POST',self.cfg['base_url']+'/embeddings','embedding.'+purpose,
                               {'model':self.cfg['model'],'input':[prefix+t for t in texts]},self.cfg.get('api_key',''))
        rows=sorted(data['data'],key=lambda d:d['index'])
        if [d['index'] for d in rows]!=list(range(len(texts))):raise ValueError('EMBEDDING_ORDER')
        vectors=[d['embedding'] for d in rows]
        if any(len(v)!=self.dim or not all(math.isfinite(x) for x in v) or not any(v) for v in vectors):raise ValueError('EMBEDDING_DIM_OR_VALUE')
        return vectors

    def index_pending(self, batch_size=16):
        pending=list(self.store.db.memory_units.find({'status':'active','$or':[{'embedding_status':{'$ne':'READY'}},{'embedding_revision':{'$ne':self.revision}}]}))
        for start in range(0,len(pending),batch_size):
            batch=pending[start:start+batch_size]
            try:vectors=self.embed([m['body_markdown'] for m in batch],'document')
            except Exception as exc:
                self.store.audit('retrieval','embedding.failed',{'count':len(batch),'error_type':type(exc).__name__})
                raise
            for mem,vector in zip(batch,vectors):
                self.store.put('memory_units',{**mem,'embedding':vector,'embedding_revision':self.revision,'embedding_model':self.cfg['model'],'embedding_dim':self.dim,'embedding_status':'READY','content_sha256':sha(mem['body_markdown'].encode())},expected=mem['revision'],stream='index')
        return len(pending)

    def ensure_index(self, timeout=45):
        definition={'fields':[{'type':'vector','path':'embedding','numDimensions':self.dim,'similarity':'cosine'},
                              *[{'type':'filter','path':key} for key in ('scope_key','character_id','status','policy_epoch','embedding_revision')]]}
        current=list(self.store.db.memory_units.list_search_indexes(self.index_name))
        if not current:
            self.store.db.memory_units.create_search_index(SearchIndexModel(name=self.index_name,type='vectorSearch',definition=definition))
        until=time.monotonic()+timeout
        while True:
            rows=list(self.store.db.memory_units.list_search_indexes(self.index_name))
            if rows and rows[0].get('status')=='READY' and rows[0].get('queryable'):break
            if time.monotonic()>until:break
            time.sleep(.5)
        self.evidence.record('vector.index',{'database':self.store.name,'definition':definition,'status':rows})
        return bool(rows and rows[0].get('status')=='READY' and rows[0].get('queryable'))

    def search(self, scope, epoch, query, *, exclude_sources=(), require_vector=False):
        auth={'scope_key':{'$in':['global-safe',scope]},'character_id':'xiaoman','policy_epoch':epoch,'status':'active'}
        vector_filter={**auth,'embedding_revision':self.revision}
        vector=[]; failure=None
        pipeline=None
        try:
            v=self.embed([query],'query')[0]
            pipeline=[{'$vectorSearch':{'index':self.index_name,'path':'embedding','queryVector':v,'numCandidates':192,'limit':24,'filter':vector_filter}},
                      {'$project':{'_id':1,'score':{'$meta':'vectorSearchScore'}}}]
            vector=list(self.store.db.memory_units.aggregate(pipeline))
        except Exception as exc:
            failure=type(exc).__name__
            if require_vector:raise
        # Hard-bounded authorized candidate set, not global retrieve-then-filter.
        rows=list(self.store.db.memory_units.find(auth,{'embedding':0}).sort('_id',1).limit(4097))
        if len(rows)>4096:raise ValueError('LEXICAL_SCOPE_LIMIT')
        qterms=terms(query)
        document_terms={m['_id']:terms(m['body_markdown']) for m in rows}
        frequencies=Counter(term for values in document_terms.values() for term in values)
        # A corpus-wide boilerplate word (e.g. "record number") is not evidence
        # of exact relevance. Entity aliases come from identities, never gold.
        qterms={t for t in qterms if frequencies[t] <= max(2,len(rows)*.5)}
        aliases={p['person_id'] for p in self.store.db.identities.find({})
                 if p.get('display_name') and p['display_name'] in query}
        def lexical_score(m):
            return sum(math.log(1+len(rows)/(1+frequencies[t])) for t in qterms & document_terms[m['_id']])+4*len(aliases & set(m.get('subjects',[])))
        lexical=sorted((m for m in rows if lexical_score(m)>0),key=lambda m:(-lexical_score(m),m['_id']))[:24]
        ranks={}
        for origin,candidates in [('vector',vector),('lexical',lexical)]:
            for rank,m in enumerate(candidates,1):
                ranks.setdefault(m['_id'],{'score':0,'origins':{}})
                ranks[m['_id']]['score']+=1/(60+rank)
                ranks[m['_id']]['origins'][origin]=rank
        # Exact recent backread keeps pending records available, separately labelled.
        pending=sorted((m for m in rows if m.get('embedding_status')!='READY'),key=lambda m:(m.get('occurred_at',''),m['_id']),reverse=True)[:6]
        for m in pending:
            ranks.setdefault(m['_id'],{'score':0,'origins':{}})['origins']['pending_backread']=True
        ordered=sorted(ranks,key=lambda key:(-ranks[key]['score'],key))
        selected=[];excluded=[]
        for key in ordered:
            current=self.store.db.memory_units.find_one({'_id':key,**auth},{'embedding':0})
            if not current or current.get('expires_at', '9999')<=now():
                excluded.append({'id':key,'reason':'authoritative_recheck'});continue
            if set(current.get('source_event_ids',[])) & set(exclude_sources):
                excluded.append({'id':key,'reason':'source_in_recent_tail'});continue
            selected.append(current)
            if len(selected)==6:break
        for m in selected:
            m['historical_sources']=[]
            for old_id in m.get('supersedes',[])[:8]:
                old=self.store.db.memory_units.find_one({'_id':old_id,'scope_key':auth['scope_key'],'status':'superseded','policy_epoch':epoch},{'embedding':0})
                if old:m['historical_sources'].append({k:old[k] for k in ('_id','body_markdown','status','epistemic_type')})
        manifest={'path':'server_vector_rrf' if failure is None else 'scoped_lexical_recent_fallback','vector_verified':failure is None,'failure':failure,'query_sha256':sha(query.encode()),'embedding_revision':self.revision,'embedding_weight_revision_verified':False,'filter':vector_filter,'numCandidates':192,'vector_ranks':vector,'lexical_ids':[m['_id'] for m in lexical],'ranks':ranks,'selected':[m['_id'] for m in selected],'excluded':excluded,'pending_backread':[m['_id'] for m in pending]}
        self.evidence.record('retrieval.selection',manifest)
        self.store.audit('retrieval','retrieval.selected',manifest,scope)
        return selected,manifest

    def close(self):self.http.client.close()
