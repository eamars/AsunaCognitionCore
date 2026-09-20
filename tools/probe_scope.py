"""All 12 gold queries in every scope, plus retained real native summary scans."""
import json,re,sys,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,canonical,sha
from asuna.experiments import freeze
from asuna.state import Store,Denied
from asuna.retrieval import Retrieval
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult

name='scope-probe-'+uuid.uuid4().hex[:10];ev=Evidence(ROOT/'reports'/name);cfg=load()
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E10')
store=Store(cfg,'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed();r=Retrieval(store,ev);status='FAIL';rows=[];live=[]
world=json.loads((BUNDLE/'fixtures/world.json').read_text(encoding='utf-8'))
canaries={m['scope_key']:re.search(r'PRIVATE_[A-Za-z0-9_]+',m['body_markdown']).group() for m in world['memories'] if m['id'] in ('M09','M10')}
def clean(value,scope):
    body=canonical(value).decode()
    assert all(marker not in body for allowed,marker in canaries.items() if scope!=allowed),'CROSS_SCOPE_CANARY'
try:
    r.index_pending();assert r.ensure_index()
    queries=[json.loads(line) for line in (BUNDLE/'fixtures/retrieval_queries.jsonl').read_text(encoding='utf-8').splitlines()]
    for scene,person in [('dm-a','A'),('dm-b','B'),('g1','A'),('g2','C')]:
        scope='scene:'+scene
        for query in queries:
            selected,manifest=r.search(scope,1,query['query'],require_vector=True)
            assert all(m['scope_key'] in ('global-safe',scope) for m in selected)
            clean(selected,scope)
            lane=FakeLane(store,[LaneResult('这是范围内的解释。'),LaneResult(json.dumps({'next':'speak','goal':'回应','constraints':[],'recall_query':'','speak_before_action':False})),LaneResult('本测试公开回复不带任何私密资料。')])
            ep=Coordinator(store,lane,context=ContextBuilder(store,r)).ingest({'event_id':scene+'-'+query['id'],'scene_id':scene,'person_id':person,'text':query['query']})
            clean(lane.calls,scope);clean(store.public_messages(scene,person),scope);clean(r.cache,scope)
            rows.append({'scene':scene,'query':query['id'],'selected':manifest['selected'],'cache_key':manifest['cache_key'],'request_sha256':sha(canonical(lane.calls)),'episode':ep['_id']})
        for key,owner in [('M09','scene:dm-a'),('M10','scene:dm-b')]:
            if scope!=owner:
                try:store.get('memory_units',key,scope);raise AssertionError('unauthorized direct/forward source read')
                except Denied:pass
    # These companion calls were produced by the same native application route,
    # not a mocked summary. Scan completed samples only, preserving source hashes.
    coverage=set()
    for attempt in ('formal-L08-20260919-01','formal-L08-20260919-02'):
        for sample in (ROOT/'reports'/attempt).glob('*/sample.json'):
            value=json.loads(sample.read_text(encoding='utf-8'));scope='scene:'+value['scene'];summaries=0;requests=0
            for path in sample.parent.glob('*provider.request.json'):
                payload=json.loads(path.read_text(encoding='utf-8'))['payload'];clean(payload,scope);requests+=1
                if payload.get('purpose')=='compaction':summaries+=1
            if summaries:coverage.add(scope)
            clean(value.get('answers',[]),scope)
            live.append({'sample':sample.relative_to(ROOT).as_posix(),'sha256':sha(sample.read_bytes()),'scope':scope,'provider_requests_scanned':requests,'native_summary_requests':summaries})
    write_json(ev.root/'queries.json',rows);write_json(ev.root/'native-summary-companions.json',live)
    assert len(rows)==48
    status='PASS' if len(coverage)==4 else 'INCONCLUSIVE'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:
    write_json(ev.root/'trace.json',list(store.db.audit_events.find({})));r.close();store.client.close()
code=1 if status=='FAIL' else 0
write_json(ev.root/'result.json',{'test_id':'PROBE-E10','status':status,'mode':'real_Mongo_vector_embedding_all_scope_queries_fake_character_with_actual_native_summary_companions','queries':len(rows),'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}],'limitations':['Fixed synthetic canary set only; no general semantic non-disclosure claim. Public sharing has no automatic forwarding capability; source IDs must pass the same target-scope authority read.']})
print(json.dumps({'run':name,'status':status,'queries':len(rows)}),flush=True);raise SystemExit(code)
