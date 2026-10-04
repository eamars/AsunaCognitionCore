from pathlib import Path
import json,uuid
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.router import Router
from asuna.tasks import TaskService,ToolBroker,Executor
from asuna.state import Denied
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
    work=Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])
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


