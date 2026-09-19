"""Cross-process cancellation must not acknowledge before an in-flight effect."""
import json,subprocess,sys,time,uuid
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.state import Store,Denied
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.tasks import TaskService,ToolBroker

if len(sys.argv)>1:
    store=Store(load(),sys.argv[1]);Path(sys.argv[3]).write_text('ready')
    try:TaskService(store).cancel(sys.argv[2],person_id='A')
    finally:store.client.close()
    raise SystemExit(0)
name='effect-fence-probe-'+uuid.uuid4().hex[:10];ev=Evidence(ROOT/'reports'/name);cfg=load()
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E16-cross-process')
store=Store(cfg,'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed()
work=ROOT/'.runtime/work'/name;work.mkdir();child=None;status='FAIL'
decision={'next':'delegate','goal':'write controlled file','constraints':[],'recall_query':'','speak_before_action':False}
ep=Coordinator(store,FakeLane(store,[LaneResult('先核实。'),LaneResult(json.dumps(decision))])).ingest({'event_id':'start','scene_id':'dm-a','person_id':'A','text':'写入受控文件'})
service=TaskService(store);task=service.claim(ep['task_id']);broker=ToolBroker(service);broker.bind('worker',task,work)
def pause(point):
    global child
    if point!='before_tool':return
    marker=work/'cancel-ready.txt'
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),store.name,task['_id'],str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+10
    while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
    assert marker.exists(),'child failed to start'
    time.sleep(.25)
    assert child.poll() is None,'cancellation acknowledged while effect fence held'
service.crash=pause
try:
    result=broker.call('worker','write','sandbox_run',{'argv':['python3','-c',"open('effect.txt','w').write('one')"]})
    stdout,stderr=child.communicate(timeout=15)
    assert child.returncode==0,(stdout,stderr)
    assert result['exit_code']==0 and (work/'effect.txt').read_text()=='one'
    assert store.db.tasks.find_one({'_id':task['_id']})['state']=='CANCELLED'
    try:broker.call('worker','late','sandbox_run',{'argv':['python3','-c',"open('late.txt','w').write('two')"]});raise AssertionError('late effect')
    except Denied:pass
    assert not (work/'late.txt').exists()
    ev.record('cross_process_fence',{'cancel_process_exit':child.returncode,'existing_effect_retained':True,'after_cancel_effects':0})
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:
    write_json(ev.root/'trace.json',list(store.db.audit_events.find({})));broker.close();store.client.close()
code=0 if status=='PASS' else 1
write_json(ev.root/'result.json',{'test_id':'PROBE-E16-cross-process','status':status,'mode':'real_Mongo_Windows_process_lock_WSL_effect','commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}]})
print(json.dumps({'run':name,'status':status}),flush=True);raise SystemExit(code)
