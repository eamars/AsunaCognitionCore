"""Local embeddings and server-side, prefiltered Mongo vector retrieval."""
from __future__ import annotations
import math
import re
import time
from collections import Counter,OrderedDict
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
        self.revision='route-'+sha(canonical({k:self.cfg.get(k) for k in ('base_url','model','dimensions','query_prefix','document_prefix','weight_sha256','manifest_sha256')}))
        self.weight_verified=False
        self.dim=768
        self.cache=OrderedDict()

    def embed(self, texts, purpose):
        if self.cfg.get('manifest_sha256') and not self.weight_verified:
            tags=self.http.request('GET',self.cfg['base_url'].removesuffix('/v1')+'/api/tags','embedding.deployment_pin',api_key=self.cfg.get('api_key',''))
            match=next((m for m in tags['models'] if m['name'].removesuffix(':latest')==self.cfg['model'].removesuffix(':latest')),None)
            if not match or match['digest']!=self.cfg['manifest_sha256']:raise ValueError('EMBEDDING_DEPLOYMENT_DRIFT')
            self.weight_verified=True
        prefix=self.cfg.get('query_prefix','search_query: ') if purpose=='query' else self.cfg.get('document_prefix','search_document: ')
        data=self.http.request('POST',self.cfg['base_url']+'/embeddings','embedding.'+purpose,
                               {'model':self.cfg['model'],'input':[prefix+t for t in texts]},self.cfg.get('api_key',''))
        rows=sorted(data['data'],key=lambda d:d['index'])
        if [d['index'] for d in rows]!=list(range(len(texts))):raise ValueError('EMBEDDING_ORDER')
        vectors=[d['embedding'] for d in rows]
        if any(len(v)!=self.dim or not all(math.isfinite(x) for x in v) or not any(v) for v in vectors):raise ValueError('EMBEDDING_DIM_OR_VALUE')
        return vectors

    def index_pending(self, batch_size=16, *, scope=None, epoch=None, stopping=None):
        query={'status':'active','$or':[{'embedding_status':{'$ne':'READY'}},{'embedding_revision':{'$ne':self.revision}}]}
        if scope is not None:query.update(scope_key=scope,policy_epoch=epoch)
        pending=list(self.store.db.memory_units.find(query))
        indexed=0
        for start in range(0,len(pending),batch_size):
            if stopping is not None and stopping.is_set():break
            batch=pending[start:start+batch_size]
            try:vectors=self.embed([m['body_markdown'] for m in batch],'document')
            except Exception as exc:
                self.store.audit('retrieval','embedding.failed',{'count':len(batch),'error_type':type(exc).__name__})
                raise
            for mem,vector in zip(batch,vectors):
                self.store.put('memory_units',{**mem,'embedding':vector,'embedding_revision':self.revision,'embedding_model':self.cfg['model'],'embedding_dim':self.dim,'embedding_status':'READY','content_sha256':sha(mem['body_markdown'].encode())},expected=mem['revision'],stream='index')
                indexed+=1
        return indexed

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

    def search(self, scope, epoch, query, *, exclude_sources=(), require_vector=False, linked_scopes=()):
        # 跨场景只读联动（A2）：配置给这个场景挂的别的场景，它的记忆可以一起被召回；写权限一点没变。
        linked=[item for item in dict.fromkeys(linked_scopes or ())
                if isinstance(item, str) and item and item not in ('global-safe', scope)]
        readable={scope} | set(linked)
        auth={'$or':[{'scope_key':'global-safe','policy_epoch':1},{'scope_key':scope,'policy_epoch':epoch}]
                  +[{'scope_key':item,'policy_epoch':epoch} for item in linked],'character_id':'xiaoman','status':'active'}
        vector_filter={**auth,'embedding_revision':self.revision}
        # Cache contains IDs/scores only, never bodies, vectors or raw queries.
        # Every hit still passes the authoritative read below. State revision
        # and scope epoch are part of the key even for an identical query.
        # Recent lexical fallback is bounded; vector search still covers the
        # entire authorized history. A growing scene must not abort a turn.
        rows=list(self.store.db.memory_units.find(auth,{'embedding':0}).sort([('occurred_at',-1),('_id',-1)]).limit(4096))
        cacheable=len(rows)<4096  # A sample cannot fingerprint the full scope.
        heads=list(self.store.db.state_heads.find({'scope_key':{'$in':['global-safe',scope]+linked}},{'_id':1,'revision_id':1}).sort('_id',1))
        # 联动集合进缓存键：同一句话在「联动着读」和「只读本场景」下不是同一个结果，不能互相顶。
        key_fields={'scope':scope,'policy_epoch':epoch,'character_id':'xiaoman','query_sha256':sha(query.encode()),'embedding_revision':self.revision,'linked_scopes':sorted(linked),'state_revision':sha(canonical([heads,[(m['_id'],m.get('revision'),m['status']) for m in rows]]))}
        cache_key=sha(canonical(key_fields));cached=self.cache.get(cache_key)
        cache_hit=bool(cacheable and cached and cached['expires']>time.monotonic())
        vector=[]; failure=None
        pipeline=None
        try:
            if cache_hit:
                vector=[dict(row) for row in cached['vector']];self.cache.move_to_end(cache_key)
            else:
                v=self.embed([query],'query')[0]
                pipeline=[{'$vectorSearch':{'index':self.index_name,'path':'embedding','queryVector':v,'numCandidates':192,'limit':24,'filter':vector_filter}},
                          {'$project':{'_id':1,'score':{'$meta':'vectorSearchScore'}}}]
                vector=list(self.store.db.memory_units.aggregate(pipeline))
                if cacheable:self.cache[cache_key]={'expires':time.monotonic()+300,'vector':[dict(row) for row in vector]}
                while len(self.cache)>128:self.cache.popitem(last=False)
        except Exception as exc:
            failure=type(exc).__name__
            if require_vector:raise
        # Hard-bounded authorized candidate set, not global retrieve-then-filter.
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
        pending=sorted((m for m in rows if m.get('embedding_status')!='READY'),key=lambda m:(m.get('occurred_at') or '',m['_id']),reverse=True)[:6]
        for m in pending:
            ranks.setdefault(m['_id'],{'score':0,'origins':{}})['origins']['pending_backread']=True
        ordered=sorted(ranks,key=lambda key:(-ranks[key]['score'],key))
        candidates=[];excluded=[]
        for key in ordered:
            current=self.store.db.memory_units.find_one({'_id':key,**auth},{'embedding':0})
            if not current or current.get('expires_at', '9999')<=now():
                excluded.append({'id':key,'reason':'authoritative_recheck'});continue
            if current.get('kind')!='monologue' and set(current.get('source_event_ids',[])) & set(exclude_sources):
                excluded.append({'id':key,'reason':'source_in_recent_tail'});continue
            candidates.append(current)
        # Repeated character interpretations must not crowd newer source speech
        # out of the same bounded retrieval. Reserve two slots for recent
        # statements already returned by this query, never arbitrary recency.
        recent_sources=sorted((m for m in candidates if m.get('epistemic_type')=='reported_speech'
            and m['scope_key'] in readable),key=lambda m:m.get('scene_seq',0),reverse=True)[:2]
        selected=[];seen=set()
        for m in candidates[:1]+recent_sources+candidates:
            if m['_id'] in seen:continue
            seen.add(m['_id']);selected.append(m)
            if len(selected)==6:break
        for m in selected:
            m['historical_sources']=[]
            for old_id in m.get('supersedes',[])[:8]:
                old=self.store.db.memory_units.find_one({'_id':old_id,'$or':auth['$or'],'status':'superseded'},{'embedding':0})
                if old:m['historical_sources'].append({k:old[k] for k in ('_id','body_markdown','status','epistemic_type')})
        manifest={'path':'server_vector_rrf' if failure is None else 'scoped_lexical_recent_fallback','vector_verified':failure is None,'failure':failure,'query_sha256':sha(query.encode()),'embedding_revision':self.revision,'embedding_weight_revision_verified':self.weight_verified,'filter':vector_filter,'numCandidates':192,'vector_ranks':vector,'lexical_ids':[m['_id'] for m in lexical],'ranks':ranks,'selected':[m['_id'] for m in selected],'excluded':excluded,'pending_backread':[m['_id'] for m in pending]}
        manifest.update(cache_key=key_fields,cache_key_sha256=cache_key,cache_hit=cache_hit,cache_contains='ids_and_scores_only',
                        recent_source_ids=[m['_id'] for m in recent_sources], lexical_candidate_count=len(rows), lexical_candidate_limit=4096,
                        cache_disabled_for_bounded_sample=not cacheable)
        self.evidence.record('retrieval.selection',manifest)
        self.store.audit('retrieval','retrieval.selected',manifest,scope)
        return selected,manifest

    def close(self):self.http.client.close()
