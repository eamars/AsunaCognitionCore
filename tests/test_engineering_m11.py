import json,uuid,subprocess,sys
from unittest.mock import patch
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.router import Router,FairQueue
from asuna.tasks import TaskService,ToolBroker,Executor
from asuna.state import Denied
from asuna.tokens import TokenMeter
from asuna.queue import RuntimeLease
from asuna.evidence import sha
from asuna.memory import MemoryService


def revised_route(store):
    def decision(goal):return LaneResult(json.dumps({'next':'delegate','goal':goal,'constraints':[],'recall_query':'','speak_before_action':False}))
    lane=FakeLane(store,[LaneResult('先核实。'),decision('original'),LaneResult('按新意图核实。'),decision('replacement')])
    service=TaskService(store);coordinator=Coordinator(store,lane)
    return service,Router(store,coordinator,task_service=service)


def test_E16_old_worker_exception_does_not_poison_replacement(store):
    service,router=revised_route(store)
    first=router.receive({'event_id':'v1','scene_id':'dm-a','person_id':'A','text':'核实第一版'})
    event={'event_id':'v2','scene_id':'dm-a','person_id':'A','text':'改成第二版','supersedes_task_id':first['task_id']}
    with pytest.raises(Denied):service.revise(first['task_id'],{**event,'person_id':'B'})
    work=ROOT/'.runtime/work'/('revision-test-'+uuid.uuid4().hex);work.mkdir()
    broker=ToolBroker(service)
    class InterruptedLane:
        def generate(self,*args,**kwargs):
            revised=router.receive(event);assert revised['intent_revision']==2
            service.claim(revised['task_id'])
            raise ValueError('old native request ended after replacement started')
    try:
        with pytest.raises(ValueError):Executor(service,InterruptedLane(),broker).run(first['task_id'],work)
        current=store.db.tasks.find_one({'_id':first['task_id']})
        assert current['state']=='RUNNING' and current['intent_revision']==2 and current['goal']=='replacement'
        assert router.receive(event)['intent_revision']==2
    finally:broker.close()


def test_E24_budget_observation_does_not_preempt_native_recovery_and_clock_fairness():
    class Sink:
        def record(self,*args):pass
    meter=TokenMeter({},Sink(),'executor')
    with patch.object(meter,'measure',return_value={'input_tokens':262144}):
        observation=meter.check({'max_tokens':8192})
        assert observation['input_tokens']>observation['input_limit'] and observation['enforced'] is False
    with patch.object(meter,'measure',side_effect=RuntimeError('tokenizer unavailable')):
        observation=meter.check({'max_tokens':8192})
        assert observation['input_tokens'] is None and observation['measurement_error']=='tokenizer unavailable'
    queue=FairQueue();clock=0;result=[]
    schedule=[(i,'g1',f'a{i}') for i in range(5)]+[(i,'g2',f'b{i}') for i in range(5)]
    while clock<5:
        for tick,scene,event in schedule:
            if tick==clock:queue.put(scene,(scene,event,tick))
        clock+=1
    while (item:=queue.pop()) is not None:result.append(item)
    assert len(result)==10 and len({x[1] for x in result})==10
    assert all(not(result[i][0]==result[i+1][0]==result[i+2][0]) for i in range(8))


def test_E16_busy_workspace_is_not_claimed(store):
    service,router=revised_route(store)
    ep=router.receive({'event_id':'work','scene_id':'dm-a','person_id':'A','text':'核实'})
    work=ROOT/'.runtime/work'/('busy-'+uuid.uuid4().hex);work.mkdir()
    key=sha(str(work.resolve()).casefold().encode())
    with RuntimeLease(ROOT/'.runtime/locks'/('workspace-'+key+'.lock')):
        with pytest.raises(TimeoutError):Executor(service,None,None).run(ep['task_id'],work)
    assert store.db.tasks.find_one({'_id':ep['task_id']})['state']=='READY'


def test_E19_rollback_rejects_other_scope_and_preserves_source_accounting(store):
    old=store.head('relationship:A','scene:dm-a')[1]
    new=store.mutate('relationship:A','scene:dm-a',old['_id'],{'body':'new','trust':3},['M02'],'scene:dm-a','new-relation')
    service=MemoryService(store)
    foreign=store.head('relationship:B','scene:dm-b')[1]
    with pytest.raises(Denied):service.rollback('relationship:A','scene:dm-a',foreign['_id'],new['_id'],'bad',operator=True)
    back=service.rollback('relationship:A','scene:dm-a',old['_id'],new['_id'],'back',operator=True)
    assert back['content']==old['content'] and back['processed_source_ids']==new['processed_source_ids']


def test_cli_starts_and_exposes_revision_commands():
    for command,expected in [('run','--supersedes-task'),('rollback','--target-revision')]:
        result=subprocess.run([sys.executable,'-m','asuna.cli',command,'--help'],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        assert expected in result.stdout
