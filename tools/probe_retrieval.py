from datetime import datetime,timezone
import json,subprocess,sys,uuid
from asuna.config import ROOT,BUNDLE,load,redacted
from asuna.state import Store
from asuna.evidence import Evidence,write_json,sha
from asuna.retrieval import Retrieval

run='M4-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run);cfg=load();store=Store(cfg,'asuna_v2_test_'+run.replace('-','_'))
write_json(ev.root/'manifest.json',{'experiment_id':run,'kind':'integration-probe','seed':20260919,'embedding':redacted(cfg)['embedding'],'code_sha256':sha((ROOT/'src/asuna/retrieval.py').read_bytes()),'fixtures':{str(p.relative_to(BUNDLE)):sha(p.read_bytes()) for p in (BUNDLE/'fixtures/world.json',BUNDLE/'fixtures/retrieval_queries.jsonl',BUNDLE/'tools/generate_distractors.py')}})
status='FAIL';results=[]
retrieval=Retrieval(store,ev)
try:
    store.migrate();store.seed()
    out=ev.root/'distractors.jsonl'
    value=subprocess.run([sys.executable,str(BUNDLE/'tools/generate_distractors.py'),'--out',str(out),'--count','200'],capture_output=True,text=True)
    ev.record('command',{'command':value.args,'exit_code':value.returncode,'stdout':value.stdout,'stderr':value.stderr});value.check_returncode()
    for line in out.read_text(encoding='utf-8').splitlines():
        m=json.loads(line);store.put('memory_units',{**m,'_id':m['id'],'character_id':'xiaoman','policy_epoch':1,'embedding_status':'PENDING'},stream='seed-distractors')
    count=retrieval.index_pending()
    assert retrieval.ensure_index(), 'VECTOR_INDEX_NOT_READY'
    for line in (BUNDLE/'fixtures/retrieval_queries.jsonl').read_text(encoding='utf-8').splitlines():
        case=json.loads(line);memories,trace=retrieval.search('scene:'+case['scene_id'],1,case['query'],require_vector=True)
        selected=[m['_id'] for m in memories]
        hit=len(set(selected)&set(case['gold']))/len(case['gold'])
        results.append({'id':case['id'],'recall_at_6':hit,'critical':case['critical'],'selected':selected,'vector_only_rank':[r['_id'] for r in trace['vector_ranks'][:6]],'gold':case['gold']})
        assert all(m['scope_key'] in ('global-safe','scene:'+case['scene_id']) for m in memories)
    assert sum(r['recall_at_6'] for r in results)/len(results)>=.9
    assert all(r['recall_at_6']>0 for r in results if r['critical'])
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:retrieval.close()
write_json(ev.root/'result.json',{'status':status,'database':store.name,'command':'.venv/Scripts/python.exe tools/probe_retrieval.py','exit_code':0 if status=='PASS' else 1,'queries':results,'limitations':['retrieval probe only; not all L04 clauses','embedding weight revision not supplied by endpoint']})
print(json.dumps({'run':run,'status':status,'recall_at_6':sum(r['recall_at_6'] for r in results)/len(results) if results else None}));raise SystemExit(0 if status=='PASS' else 1)
