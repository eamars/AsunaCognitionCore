"""Local embeddings and server-side, prefiltered Mongo vector retrieval."""
from __future__ import annotations
from .visibility import is_owner_private_scope
from .config import character_id
import math
from datetime import datetime, timezone
import re
import time
from collections import Counter,OrderedDict
from .evidence import Evidence, LocalHttp, canonical, sha
from .state import Space, Store, now

# kind: her own thoughts in other conversations are searched apart from their talk (own_thoughts).
MEMORY = Space(name='asuna_memory_v1', collection='memory_units', path='embedding', dimensions=768,
               fields=('scope_key', 'character_id', 'status', 'policy_epoch', 'embedding_revision', 'kind'))


def terms(text):
    # Deterministic lexical supplement; never consumes gold/oracle data.
    words=re.findall(r'[a-zA-Z0-9_-]+|[\u4e00-\u9fff]+',text.lower())
    return {part for word in words for part in ([word] if word.isascii() else [word[i:i+2] for i in range(max(1,len(word)-1))])}


# A unit the embedding model refuses on its own (longer than its context) is embedded from its opening part, longest
# first; one refused even at the shortest is marked REFUSED for this embedding route and left to lexical recall.
EMBED_OPENING_CHARS=(400,200,100)


def refused(exc):
    """The embedding service refused this input (HTTP 400), as opposed to being unreachable or failing."""
    import httpx
    return isinstance(exc,httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code==400


class Retrieval:
    REST_SECONDS=120

    def __init__(self, store: Store, evidence: Evidence):
        self.store,self.evidence=store,evidence
        self.cfg=store.config['embedding']
        self.http=LocalHttp(evidence)
        # A routing fingerprint is explicitly not a verified weight revision.
        self.revision='route-'+sha(canonical({k:self.cfg.get(k) for k in ('base_url','model','dimensions','query_prefix','document_prefix','weight_sha256','manifest_sha256')}))
        self.weight_verified=False
        self.dim=MEMORY.dimensions
        self.cache=OrderedDict()
        self.vectors=OrderedDict()     # the last queries' vectors by query sha, for the shadow pilot (memory_pilot.py)
        self.resting_until=0.0         # monotonic: query embeddings skipped until then, after a failure

    def embed(self, texts, purpose):
        # The embedding service is outside the program: when it fails, a turn's query embeddings rest for REST_SECONDS
        # and its searches go lexical at once, instead of each waiting out the connection again (the indexer, which
        # embeds documents in the background, keeps its own retries).
        if purpose == 'query' and time.monotonic() < self.resting_until:
            raise RuntimeError('EMBEDDING_RESTING')
        try:
            return self._embed(texts, purpose)
        except Exception:
            if purpose == 'query':
                self.resting_until = time.monotonic() + self.REST_SECONDS
            raise

    def _embed(self, texts, purpose):
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
        query={'status':'active','$or':[{'embedding_status':{'$nin':['READY','REFUSED']}},{'embedding_revision':{'$ne':self.revision}}]}
        if scope is not None:query.update(scope_key=scope,policy_epoch=epoch)
        pending=list(self.store.db.memory_units.find(query))
        indexed=0
        for start in range(0,len(pending),batch_size):
            if stopping is not None and stopping.is_set():break
            batch=pending[start:start+batch_size]
            try:vectors=self.embed([m['body_markdown'] for m in batch],'document')
            except Exception as exc:
                self.store.audit('retrieval','embedding.failed',{'count':len(batch),'error_type':type(exc).__name__})
                if not refused(exc):raise
                # One input the model refused fails its whole batch: embed them one by one, so it blocks no other.
                indexed+=sum(self._index_one(mem) for mem in batch)
                continue
            for mem,vector in zip(batch,vectors):
                self._ready(mem,vector)
                indexed+=1
        return indexed

    def _ready(self, mem, vector, opening=None):
        self.store.put('memory_units',{**mem,'embedding':vector,'embedding_revision':self.revision,'embedding_model':self.cfg['model'],
            'embedding_dim':self.dim,'embedding_status':'READY','content_sha256':sha(mem['body_markdown'].encode()),
            **({'embedding_opening_chars':opening} if opening else {})},expected=mem['revision'],stream='index')

    def _index_one(self, mem):
        """One unit on its own: whole, else its opening part (EMBED_OPENING_CHARS), else REFUSED. 1 when embedded."""
        body=mem['body_markdown']
        for opening in (None,*[n for n in EMBED_OPENING_CHARS if n<len(body)]):
            try:vector=self.embed([body if opening is None else body[:opening]],'document')[0]
            except Exception as exc:
                if not refused(exc):raise
                continue
            self._ready(mem,vector,opening)
            return 1
        self.store.put('memory_units',{**mem,'embedding_status':'REFUSED','embedding_revision':self.revision,
            'embedding_model':self.cfg['model']},expected=mem['revision'],stream='index')
        self.store.audit('retrieval','embedding.refused',{'memory_unit':mem['_id'],'chars':len(body)})
        return 0

    def ensure_index(self, timeout=45):
        ready=self.store.ensure_vectors(MEMORY,timeout)
        self.evidence.record('vector.index',{'database':self.store.name,'space':MEMORY.name,'fields':list(MEMORY.fields),'ready':ready})
        return ready

    def _scene_sequences(self, scopes):
        """Current message count of each scene scope (conversation volume)."""
        return {row['scope_key']: row.get('sequence', 0) for row in self.store.db.scenes.find(
            {'scope_key': {'$in': list(scopes)}}, {'scope_key': 1, 'sequence': 1})}

    def _forget(self, ranks, forgetting, sequences, automatic):
        """Multiply each candidate's score by its freshness (persona model memory.forgetting).

        freshness = 0.5^(days since last real use / half_life_days)
                  × 0.5^(messages in its conversation since then / half_life_messages)
        A pinned memory does not fade. Returns raw chat chunks that faded below step_back_below and whose
        message a summary already covers: automatic recall leaves them out (explicit recall still reads them).
        """
        half_days = float(forgetting.get('half_life_days') or 0)
        half_messages = float(forgetting.get('half_life_messages') or 0)
        if not ranks or not (half_days or half_messages):
            return set()
        rows = {row['_id']: row for row in self.store.db.memory_units.find({'_id': {'$in': list(ranks)}}, {
            'pinned': 1, 'salience': 1, 'occurred_at': 1, 'generated_at': 1, 'formed_at': 1, 'scene_seq': 1,
            'source_window': 1, 'source_event_ids': 1, 'scope_key': 1, 'kind': 1})}
        sources = {row['_id']: row for row in self.store.db.messages.find(
            {'_id': {'$in': [ids[-1] for row in rows.values() for ids in [row.get('source_event_ids') or []] if ids]}},
            {'scene_seq': 1, 'summary_batch_id': 1})}
        moment = datetime.now(timezone.utc)
        floor, stepped = float(forgetting.get('step_back_below') or 0), set()
        for key, row in rows.items():
            if row.get('pinned') or (row.get('salience') or {}).get('pinned'):
                ranks[key]['freshness'] = 1.0
                continue
            used = row.get('salience') or {}
            stamp = used.get('last_ref_at') or row.get('occurred_at') or row.get('generated_at') or row.get('formed_at')
            try:
                days = max(0.0, (moment - datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))).total_seconds() / 86400) if stamp else 0.0
            except ValueError:
                days = 0.0
            source = sources.get((row.get('source_event_ids') or [None])[-1]) or {}
            window = row.get('source_window') if isinstance(row.get('source_window'), dict) else {}
            anchor = used.get('last_ref_seq') or row.get('scene_seq') or window.get('to_seq') or window.get('to') or source.get('scene_seq')
            current = sequences.get(row.get('scope_key'))
            messages = max(0, current - anchor) if isinstance(current, int) and isinstance(anchor, int) else 0
            freshness = (0.5 ** (days / half_days) if half_days else 1.0) * (0.5 ** (messages / half_messages) if half_messages else 1.0)
            ranks[key]['score'] *= freshness
            ranks[key]['freshness'] = round(freshness, 4)
            if automatic and freshness < floor and row.get('kind') == 'chat_chunk' and source.get('summary_batch_id'):
                stepped.add(key)
        return stepped

    def own_thoughts(self, scopes, query, limit=3):
        """Her own thoughts (kind monologue) in the given conversations [(scope_key, policy_epoch)] matching the query,
        best first: vector and lexical ranks fused, each read back under the same filter. Only her thoughts, never
        the talk around them; callers decide where she may read them (at home)."""
        if not scopes:
            return []
        auth={'$or':[{'scope_key':scope,'policy_epoch':epoch} for scope,epoch in scopes],'kind':'monologue',
              'character_id':character_id(self.store.config),'status':'active'}
        try:
            v=self.embed([query],'query')[0]
            vector=self.store.nearest(MEMORY,v,12,{('scope_key','policy_epoch'):list(scopes),'kind':'monologue',
                'character_id':character_id(self.store.config),'status':'active','embedding_revision':self.revision})
        except Exception:
            vector=[]
        rows=list(self.store.db.memory_units.find(auth,{'embedding':0}).sort([('formed_at',-1),('_id',-1)]).limit(2048))
        qterms=terms(query)
        scored=sorted(((len(qterms & terms(m.get('body_markdown') or '')),m['_id']) for m in rows),reverse=True)
        lexical=[key for hits,key in scored if hits][:12]
        ranks={}
        for candidates in ([key for key,_ in vector],lexical):
            for rank,key in enumerate(candidates,1):
                ranks[key]=ranks.get(key,0)+1/(60+rank)
        out=[]
        for key in sorted(ranks,key=lambda k:(-ranks[k],k)):
            current=self.store.db.memory_units.find_one({'_id':key,**auth},{'embedding':0})
            if current:
                out.append(current)
            if len(out)==limit:
                break
        return out

    def search(self, scope, epoch, query, *, exclude_sources=(), require_vector=False, linked_scopes=(), private_scope=None,
               coverage_floor=0.0, forgetting=None, record_use=False, automatic=True):
        # 跨场景只读联动（A2）：配置给这个场景挂的别的场景，它的记忆可以一起被召回；写权限一点没变。
        # owner-private 只看会话类（private_scope 仅在 owner_private 会话里由调用方给出），与联动无关。
        linked=[item for item in dict.fromkeys(linked_scopes or ())
                if isinstance(item, str) and item and item not in ('global-safe', scope) and not is_owner_private_scope(item)]
        if is_owner_private_scope(scope) or (private_scope is not None and not is_owner_private_scope(private_scope)):
            raise ValueError('INVALID_RETRIEVAL_SCOPE')
        readable={scope} | set(linked)
        pairs=[('global-safe',1),(scope,epoch)]+[(item,epoch) for item in linked]+([(private_scope,1)] if private_scope else [])
        auth={'$or':[{'scope_key':s,'policy_epoch':e} for s,e in pairs],'character_id':character_id(self.store.config),'status':'active'}
        where={('scope_key','policy_epoch'):pairs,'character_id':auth['character_id'],'status':'active','embedding_revision':self.revision}
        vector_filter={'scope_key, policy_epoch':[list(p) for p in pairs],**{k:v for k,v in where.items() if isinstance(k,str)}}
        # Cache contains IDs/scores only, never bodies, vectors or raw queries.
        # Every hit still passes the authoritative read below. State revision
        # and scope epoch are part of the key even for an identical query.
        # Recent lexical fallback is bounded; vector search still covers the
        # entire authorized history. A growing scene must not abort a turn.
        rows=list(self.store.db.memory_units.find(auth,{'embedding':0}).sort([('occurred_at',-1),('_id',-1)]).limit(4096))
        cacheable=len(rows)<4096  # A sample cannot fingerprint the full scope.
        heads=list(self.store.db.state_heads.find({'scope_key':{'$in':['global-safe',scope]+linked+([private_scope] if private_scope else [])}},{'_id':1,'revision_id':1}).sort('_id',1))
        # 联动集合进缓存键：同一句话在「联动着读」和「只读本场景」下不是同一个结果，不能互相顶。
        key_fields={'scope':scope,'private_scope':private_scope,'policy_epoch':epoch,'character_id':character_id(self.store.config),'query_sha256':sha(query.encode()),'embedding_revision':self.revision,'linked_scopes':sorted(linked),'state_revision':sha(canonical([heads,[(m['_id'],m.get('revision'),m['status']) for m in rows]]))}
        cache_key=sha(canonical(key_fields));cached=self.cache.get(cache_key)
        cache_hit=bool(cacheable and cached and cached['expires']>time.monotonic())
        vector=[]; failure=None
        try:
            if cache_hit:
                vector=[dict(row) for row in cached['vector']];self.cache.move_to_end(cache_key)
            else:
                v=self.embed([query],'query')[0]
                self.vectors[sha(query.encode())]=v
                while len(self.vectors)>16:self.vectors.popitem(last=False)
                vector=[{'_id':key,'score':score} for key,score in self.store.nearest(MEMORY,v,24,where)]
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
        sequences=self._scene_sequences([scope,*linked])
        stepped=self._forget(ranks,forgetting or {},sequences,automatic)
        ordered=sorted(ranks,key=lambda key:(-ranks[key]['score'],key))
        candidates=[];excluded=[]
        for key in ordered:
            current=self.store.db.memory_units.find_one({'_id':key,**auth},{'embedding':0})
            if not current or current.get('expires_at', '9999')<=now():
                excluded.append({'id':key,'reason':'authoritative_recheck'});continue
            # In view: a record from a line she still sees, or one of her last thoughts (by its own id).
            if key in exclude_sources or (current.get('kind')!='monologue' and set(current.get('source_event_ids',[])) & set(exclude_sources)):
                excluded.append({'id':key,'reason':'source_in_recent_tail'});continue
            if key in stepped:
                excluded.append({'id':key,'reason':'faded_and_summarized'});continue
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
        # Records that would have made the cut but whose source she still sees (the recent tail): counted, so a
        # recall can say where the rest is instead of reading as "not found".
        position={key:i for i,key in enumerate(ordered)}
        cut=max((position[m['_id']] for m in selected),default=-1) if len(selected)==6 else len(ordered)
        in_view=[e['id'] for e in excluded if e['reason']=='source_in_recent_tail' and position[e['id']]<cut]
        for m in selected:
            m['historical_sources']=[]
            for old_id in m.get('supersedes',[])[:8]:
                old=self.store.db.memory_units.find_one({'_id':old_id,'$or':auth['$or'],'status':'superseded'},{'embedding':0})
                if old:m['historical_sources'].append({k:old[k] for k in ('_id','body_markdown','status','epistemic_type')})
        # Evidence sufficiency (ADR-009 MEMORY §5.2): RRF ranks only; it never decides "enough".
        if failure is None and vector:
            # Her coverage floor reads 0..1 (memory.coverage_floor): a cosine c counts as (1 + c) / 2.
            scores={row['_id']:(1+row.get('score',-1.0))/2 for row in vector}
            coverage_score=max((scores.get(m['_id'],0.0) for m in selected),default=0.0);coverage_basis='vector_cosine'
        else:
            raw=terms(query)
            coverage_score=max((len(raw & terms(m['body_markdown']))/len(raw) for m in selected),default=0.0) if raw else 0.0
            coverage_basis='lexical_overlap'
        coverage='insufficient' if not selected or coverage_score<float(coverage_floor or 0) else 'sufficient'
        moment=now()
        for m in selected if record_use else ():
            # Rehearsal: a memory a real turn used is fresh again, in time and in conversation volume.
            self.store.db.memory_units.update_one({'_id':m['_id']},{'$inc':{'salience.ref_count':1},'$set':{
                'salience.last_ref_at':moment,'salience.last_ref_seq':sequences.get(m['scope_key'])}})
        manifest={'path':'server_vector_rrf' if failure is None else 'scoped_lexical_recent_fallback',
                  'coverage':coverage,'coverage_score':coverage_score,'coverage_basis':coverage_basis,'vector_verified':failure is None,'failure':failure,'query_sha256':sha(query.encode()),'embedding_revision':self.revision,'embedding_weight_revision_verified':self.weight_verified,'filter':vector_filter,'exact':True,'vector_ranks':vector,'lexical_ids':[m['_id'] for m in lexical],'ranks':ranks,'selected':[m['_id'] for m in selected],'excluded':excluded,'in_view':in_view,'pending_backread':[m['_id'] for m in pending]}
        manifest.update(cache_key=key_fields,cache_key_sha256=cache_key,cache_hit=cache_hit,cache_contains='ids_and_scores_only',
                        recent_source_ids=[m['_id'] for m in recent_sources], lexical_candidate_count=len(rows), lexical_candidate_limit=4096,
                        cache_disabled_for_bounded_sample=not cacheable)
        self.evidence.record('retrieval.selection',manifest)
        self.store.audit('retrieval','retrieval.selected',manifest,scope)
        return selected,manifest

    def query_vector(self, query):
        """The vector this retrieval last computed for the query, or None (a cached search computes none)."""
        return self.vectors.get(sha(query.encode()))

    def close(self):self.http.client.close()
