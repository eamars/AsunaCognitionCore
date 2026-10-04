import json,os,sys
from asuna.config import load
from asuna.state import Store
from asuna.lanes import FakeLane,LaneResult
from asuna.coordinator import Coordinator
from asuna.tasks import TaskService,ToolBroker

config=load();config['character_id']='demo'  # same synthetic identity and grant as the conftest store
from fixture_grant import fixture_grant
work=fixture_grant(config,sys.argv[1])
store=Store(config,sys.argv[1]);point=sys.argv[2]
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
    broker.bind('worker',task,work)
    def tool_crash(p):
        if p=='after_tool_before_receipt':os._exit(77)
    service.crash=tool_crash
    broker.call('worker','commit','write_file',{'path':'copy.txt','text':'unchanged'})
