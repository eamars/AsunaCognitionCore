"""E16 vertical probe: real Mongo/files/broker, two workers, fake role output."""
import concurrent.futures,json,sys,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.state import Store,Denied
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.router import Router
from asuna.tasks import TaskService,ToolBroker

name='revision-probe-'+uuid.uuid4().hex[:10];ev=Evidence(ROOT/'reports'/name);cfg=load()
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E16')
store=Store(cfg,'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed()
service=TaskService(store);broker=ToolBroker(service);status='FAIL'
def decision(goal):return LaneResult(json.dumps({'next':'delegate','goal':goal,'constraints':[],'recall_query':'','speak_before_action':False}))
lane=FakeLane(store,[LaneResult('先核实第一版。'),decision('复制为 first.txt'),LaneResult('改为第二版，原操作不再继续。'),decision('核实第二版目录')])
coordinator=Coordinator(store,lane);router=Router(store,coordinator,task_service=service)
work=ROOT/'.runtime/work'/name;work.mkdir();(work/'a.txt').write_text('original',encoding='utf-8')
try:
    first=router.receive({'event_id':'v1','scene_id':'dm-a','person_id':'A','text':'复制受控文件。'})
    old=service.claim(first['task_id']);broker.bind('old-worker',old,work)
    copied=broker.call('old-worker','copy','fixture_stage_copy',{'source':'a.txt','destination':'first.txt'})
    committed=broker.call('old-worker','commit','fixture_commit_copy',{'path':'first.txt','sha256':copied['sha256']})
    event={'event_id':'v2','scene_id':'dm-a','person_id':'A','text':'改成核实第二版目录，不再执行原操作。','supersedes_task_id':old['_id']}
    try:service.revise(old['_id'],{**event,'person_id':'B'});raise AssertionError('B revised A task')
    except Denied:pass
    second=router.receive(event);assert second['intent_revision']==2 and second['task_id']==old['_id']
    new=service.claim(second['task_id']);broker.bind('new-worker',new,work)
    checked=broker.call('new-worker','check','fixture_lookup',{})
    try:broker.call('old-worker','late','fixture_stage_copy',{'source':'a.txt','destination':'late.txt'});raise AssertionError('stale tool ran')
    except Denied:pass
    def result(task,ref):return {'task_id':task['_id'],'intent_revision':task['intent_revision'],'status':'done','facts':[{'text':'已核实目录','evidence_refs':[ref]}],'uncertainties':[],'unmet_items':[],'artifact_refs':[ref],'effect_receipts':[],'needs_decision':None}
    try:service.finish(new,result(new,copied['evidence_ref']));raise AssertionError('old evidence accepted')
    except Denied:pass
    def finish(task,ref):
        try:return service.finish(task,result(task,ref))['state']
        except Denied:return 'STALE_REJECTED'
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        a=pool.submit(finish,old,copied['evidence_ref']);b=pool.submit(finish,new,checked['evidence_ref'])
        outcomes=[a.result(),b.result()]
    assert outcomes==['STALE_REJECTED','DONE']
    assert service.feedback(old,coordinator) is None
    assert store.db.sink_receipts.find_one({'_id':committed['effect_receipt'],'intent_revision':1})
    assert (work/'first.txt').read_text()=='original' and not (work/'late.txt').exists()
    assert store.db.messages.count_documents({'direction':'outbound'})==0
    duplicate=router.receive(event);assert duplicate['_id']==second['_id']
    write_json(ev.root/'observations.json',{'worker_outcomes':outcomes,'old_intent':old['intent_revision'],'new_intent':new['intent_revision'],'old_effect_preserved':committed['effect_receipt'],'duplicate_revision_unchanged':store.db.tasks.find_one({'_id':old['_id']})['intent_revision']==2})
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:
    write_json(ev.root/'trace.json',list(store.db.audit_events.find({})));broker.close();store.client.close()
code=0 if status=='PASS' else 1
write_json(ev.root/'result.json',{'test_id':'PROBE-E16','status':status,'mode':'fake_character_real_Mongo_real_sandbox_concurrent_workers','commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}]})
print(json.dumps({'run':name,'status':status}),flush=True);raise SystemExit(code)
