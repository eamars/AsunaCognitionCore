import json,os,sys
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.lanes import FakeLane,LaneResult
from asuna.coordinator import Coordinator
from asuna.tasks import TaskService,ToolBroker

store=Store(load(),sys.argv[1]);point=sys.argv[2]
decision={'next':'delegate' if point in ('after_task_persist','after_tool_commit') else 'speak','goal':'复制受控文件','constraints':[],'recall_query':'','speak_before_action':False}
lane=FakeLane(store,[LaneResult('内部。'),LaneResult(json.dumps(decision)),LaneResult('回来了。')])
def crash(p):
    if p==point:os._exit(77)
if point=='before_commit_audit':
    previous=store.audit
    def audit(stream,kind,payload,scope='operator'):
        if kind=='state.commit' and payload.get('collection')=='sink_receipts':os._exit(77)
        return previous(stream,kind,payload,scope)
    store.audit=audit
ep=Coordinator(store,lane,crash=crash).ingest({'event_id':'matrix','scene_id':'dm-a','person_id':'A','text':'受控测试'})
if point=='after_tool_commit':
    service=TaskService(store);task=service.claim(ep['task_id']);broker=ToolBroker(service)
    work=ROOT/'.runtime/work'/store.name;work.mkdir();(work/'a.txt').write_text('unchanged')
    broker.bind('worker',task,work)
    copied=broker.call('worker','copy','fixture_stage_copy',{'source':'a.txt','destination':'copy.txt'})
    def tool_crash(p):
        if p=='after_tool_before_receipt':os._exit(77)
    service.crash=tool_crash
    broker.call('worker','commit','fixture_commit_copy',{'path':'copy.txt','sha256':copied['sha256']})
