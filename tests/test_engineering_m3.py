import json
import uuid
from pathlib import Path
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.state import Denied,Conflict
from asuna.tasks import TaskService,ToolBroker


def task_setup(store):
    decision={'next':'delegate','goal':'copy fixture','constraints':[],'recall_query':'','speak_before_action':False}
    lane=FakeLane(store,[LaneResult('先核实。'),LaneResult(json.dumps(decision))])
    ep=Coordinator(store,lane).ingest({'event_id':'copy','scene_id':'dm-a','person_id':'A','text':'复制受控文件，保留原件。'})
    service=TaskService(store);task=service.claim(ep['task_id'])
    work=ROOT/'.runtime/work'/('test-'+uuid.uuid4().hex);work.mkdir()
    (work/'a.txt').write_text('controlled original',encoding='utf-8')
    broker=ToolBroker(service);broker.bind('s-test',task,work)
    return service,task,broker,work


def test_E16_cancel_fences_tool_and_result(store):
    service,task,broker,work=task_setup(store)
    try:
        read=broker.call('s-test','read','fixture_lookup',{})
        service.cancel(task['_id'])
        with pytest.raises(Denied):broker.call('s-test','late','fixture_stage_copy',{'source':'a.txt','destination':'late.txt'})
        with pytest.raises(Denied):service.finish(task,{})
        assert not (work/'late.txt').exists()
        assert store.db.artifacts.find_one({'_id':read['evidence_ref']})['state']=='DONE'
    finally:broker.close()


def test_E14_simulated_effect_dedupe(store):
    service,task,broker,work=task_setup(store)
    try:
        copied=broker.call('s-test','copy','fixture_stage_copy',{'source':'a.txt','destination':'out.txt'})
        args={'path':'out.txt','sha256':copied['sha256']}
        effect=broker.call('s-test','commit','fixture_commit_copy',args)
        for _ in range(100):assert broker.call('s-test','commit','fixture_commit_copy',args)==effect
        assert store.db.sink_receipts.count_documents({'task_id':task['_id']})==1
        assert (work/'a.txt').read_bytes()==(work/'out.txt').read_bytes()
    finally:broker.close()


def test_E06_sandbox_cannot_access_host_credentials_or_network(store):
    service,task,broker,work=task_setup(store)
    try:
        result=broker.call('s-test','isolation','sandbox_run',{'argv':['python3','-c',"import pathlib,os,socket; assert not pathlib.Path('/mnt/c').exists(); assert not pathlib.Path('/home/rba90').exists(); assert not any('KEY' in k or 'TOKEN' in k or 'MONGO' in k for k in os.environ); s=socket.socket();s.settimeout(1); assert s.connect_ex(('192.168.2.10',27027))!=0;print('isolated')"]})
        assert result['exit_code']==0,result
        with pytest.raises(Denied):broker.call('s-test','publish','publish',{'text':'bypass'})
        assert store.db.messages.count_documents({'direction':'outbound'})==0
    finally:broker.close()


def test_E21_audit_failure_blocks_file_effect(store):
    service,task,broker,work=task_setup(store)
    try:
        store.fail_audit=True
        with pytest.raises(OSError):broker.call('s-test','blocked','fixture_stage_copy',{'source':'a.txt','destination':'blocked.txt'})
        assert not (work/'blocked.txt').exists()
    finally:store.fail_audit=False;broker.close()


def test_E14_uncertain_tool_does_not_repeat(store):
    service,task,broker,work=task_setup(store)
    def crash(point):
        if point=='after_tool_before_receipt':raise RuntimeError('simulated worker failure')
    service.crash=crash
    try:
        with pytest.raises(RuntimeError):broker.call('s-test','uncertain','sandbox_run',{'argv':['python3','-c',"open('effect.txt','a').write('x')"]})
        service.crash=lambda p:None
        with pytest.raises(Denied):broker.call('s-test','uncertain','sandbox_run',{'argv':['python3','-c',"open('effect.txt','a').write('x')"]})
        assert (work/'effect.txt').read_text()=='x'
    finally:broker.close()


def test_E08_scope_and_receipt_references_are_enforced(store):
    service,task,broker,work=task_setup(store)
    try:
        result={'task_id':task['_id'],'intent_revision':1,'status':'done','facts':[{'text':'done','evidence_refs':['invented']}],'artifact_refs':[],'effect_receipts':[],'uncertainties':[],'unmet_items':[],'needs_decision':None}
        with pytest.raises(Denied):service.finish(task,result)
        assert store.db.tasks.find_one({'_id':task['_id']})['state']=='RUNNING'
        service.cancel(task['_id'])
        assert service.feedback(store.db.tasks.find_one({'_id':task['_id']}),None) is None
    finally:broker.close()
