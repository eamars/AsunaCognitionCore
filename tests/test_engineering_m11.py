import json,uuid
from unittest.mock import patch
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.router import Router,FairQueue
from asuna.tasks import TaskService,ToolBroker,Executor
from asuna.state import Denied
from asuna.tokens import TokenMeter


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


def test_E24_budget_guard_before_generation_and_clock_fairness():
    # Capacity arithmetic is deterministic; real server token counting is
    # separately exercised by F01, including 196k and 234k requests.
    class Sink:
        def record(self,*args):pass
    meter=TokenMeter({},Sink(),'executor')
    with patch.object(meter,'measure',return_value={'input_tokens':262144}):
        with pytest.raises(ValueError,match='INPUT_BUDGET_EXCEEDED'):meter.check({'max_tokens':8192},capacity_override=True)
    queue=FairQueue();clock=0;result=[]
    schedule=[(i,'g1',f'a{i}') for i in range(5)]+[(i,'g2',f'b{i}') for i in range(5)]
    while clock<5:
        for tick,scene,event in schedule:
            if tick==clock:queue.put(scene,(scene,event,tick))
        clock+=1
    while (item:=queue.pop()) is not None:result.append(item)
    assert len(result)==10 and len({x[1] for x in result})==10
    assert all(not(result[i][0]==result[i+1][0]==result[i+2][0]) for i in range(8))
