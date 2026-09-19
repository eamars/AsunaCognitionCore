import json,subprocess,sys,uuid
from unittest.mock import patch
from .config import BUNDLE
from .evidence import write_json,sha,canonical
from .state import Store
from .retrieval import Retrieval
from .context import ContextBuilder


def suite(config,evidence):
    store=Store(config,'asuna_v2_test_L04_'+uuid.uuid4().hex[:16]);store.migrate();store.seed()
    r=Retrieval(store,evidence);results=[];checks={};status='FAIL'
    try:
        out=evidence.root/'distractors.jsonl'
        command=[sys.executable,str(BUNDLE/'tools/generate_distractors.py'),'--out',str(out),'--count','200']
        p=subprocess.run(command,capture_output=True)
        evidence.record('distractor.command',{'argv':command,'exit_code':p.returncode,'stdout':p.stdout.decode(),'stderr':p.stderr.decode()});p.check_returncode()
        for line in out.read_text(encoding='utf-8').splitlines():
            m=json.loads(line);store.put('memory_units',{**m,'_id':m['id'],'character_id':'xiaoman','policy_epoch':1,'embedding_status':'PENDING'},stream='seed-distractors')
        r.index_pending();checks['index_ready']=r.ensure_index()
        if not checks['index_ready']:raise RuntimeError('VECTOR_INDEX_NOT_READY')
        for line in (BUNDLE/'fixtures/retrieval_queries.jsonl').read_text(encoding='utf-8').splitlines():
            case=json.loads(line);scope='scene:'+case['scene_id']
            rows,manifest=r.search(scope,1,case['query'],require_vector=True)
            selected={m['_id'] for m in rows};gold=set(case['gold']);top_vector={m['_id'] for m in manifest['vector_ranks'][:6]}
            vector_nonliteral=bool(gold&top_vector) and all(case['query'] not in store.db.memory_units.find_one({'_id':key})['body_markdown'] for key in gold)
            results.append({'id':case['id'],'gold':case['gold'],'selected':sorted(selected),'recall_at_6':len(gold&selected)/len(gold),'critical':case['critical'],'vector_without_lexical_nonliteral_success':vector_nonliteral,'scope_allowed':all(m['scope_key'] in (scope,'global-safe') for m in rows)})
        checks['recall_at_6']=sum(v['recall_at_6'] for v in results)/12
        checks['critical_hits']=all(v['recall_at_6']>0 for v in results if v['critical'])
        checks['vector_only_nonliteral_successes']=sum(v['vector_without_lexical_nonliteral_success'] for v in results)
        for scene,person in [('dm-a','A'),('dm-b','B'),('g1','A'),('g2','C')]:
            _,context,manifest=ContextBuilder(store,r).prepare({'scene_id':scene,'person_id':person,'event_id':'baseline','text':'你好'})
            assert manifest['persona_revision'] and manifest['persona_sha256']
            if scene.startswith('dm'):assert context['relationship'] is not None
            if scene!='dm-a':assert 'PRIVATE_A_CANARY' not in json.dumps(context,ensure_ascii=False)
        checks['baseline_and_scope']=True
        new={'_id':'pending-acceptance','scope_key':'scene:dm-a','policy_epoch':1,'character_id':'xiaoman','status':'active','embedding_status':'PENDING','body_markdown':'新观察标识 DELAYED_INDEX_WITNESS，只存在于 dm-a。','source_event_ids':['new-observation'],'epistemic_type':'observed_fact'}
        store.put('memory_units',new)
        rows,m=r.search('scene:dm-a',1,'DELAYED_INDEX_WITNESS',require_vector=True)
        checks['pending_backread']='pending-acceptance' in m['pending_backread'] and any(x['_id']=='pending-acceptance' for x in rows)
        m09=store.db.memory_units.find_one({'_id':'M09'});store.put('memory_units',{**m09,'status':'tombstone'},expected=m09['revision'])
        # Deliberately stale search-server IDs: authority recheck remains real
        # Mongo. This injected segment is excluded from vector-hit statistics.
        with patch.object(store.db.memory_units,'aggregate',return_value=iter([{'_id':'M09','score':1.0}])):
            rows,m=r.search('scene:dm-a',1,'PRIVATE_A_CANARY')
        checks['stale_index_rejected']=all(x['_id']!='M09' for x in rows)
        evidence.record('stale_index.injection',{'mode':'injected_stale_vector_ids_real_authority','checks':checks,'selection':m})
        status='PASS' if checks['recall_at_6']>=.9 and checks['critical_hits'] and checks['vector_only_nonliteral_successes']>=5 and all(v['scope_allowed'] for v in results) and checks['pending_backread'] and checks['stale_index_rejected'] else 'FAIL'
    except Exception as exc:evidence.record('retrieval.error',{'type':type(exc).__name__,'message':str(exc)})
    finally:r.close();store.client.close()
    return {'test_id':'L04','status':status,'mode':'real_embedding_real_Mongo_vector_with_explicit_stale_ID_fault_injection','attempts':1,'queries':results,'metrics':checks,'limitations':['No query-result cache exists; no cache-hit claim is made.','Embedding route fingerprint is pinned; endpoint does not expose verified weight revision.']}
