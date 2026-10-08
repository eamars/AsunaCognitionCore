from pathlib import Path
import pytest
from asuna.config import ROOT
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,FakeTurn
from asuna.router import Router
from asuna.tasks import TaskService,ToolBroker,Executor
from asuna.state import Denied
from asuna.queue import RuntimeLease
from asuna.evidence import sha
from asuna.memory import MemoryService

THINK=('think',{'thought':'先核实，再说结果。'})


def route(store):
    lane=FakeLane(store,[FakeTurn([THINK,('delegate',{'title':'核实','brief':'核实第一版'})],'先核实。')])
    service=TaskService(store);coordinator=Coordinator(store,lane)
    return service,Router(store,coordinator,task_service=service)


def test_E16_old_worker_exception_does_not_poison_replacement(store):
    # The host stops running work (chat.stop: cancel with host_stop, then close the action lane); a new local
    # request continues it as a new task in the same action session; then the old native request ends in error.
    service,router=route(store)
    first=router.receive({'event_id':'v1','scene_id':'dm-a','person_id':'A','text':'核实第一版'})
    task_id=first['task_ids'][0]
    with pytest.raises(Denied):service.cancel(task_id,reason='host_stop',person_id='B')
    router.coordinator.character=FakeLane(store,[FakeTurn([THINK,('message_action',{'task':task_id,'message':'改成第二版'})],'接着做。')])
    event={'event_id':'v2','scene_id':'dm-a','person_id':'A','text':'改成第二版'}
    work=Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])
    broker=ToolBroker(service)
    replacement={}
    class InterruptedLane:
        def generate(self,*args,**kwargs):
            service.cancel(task_id,reason='host_stop',person_id='A')
            continued=router.receive(event)
            replacement.update(service.claim(continued['task_ids'][0]))
            raise ValueError('old native request ended after replacement started')
    try:
        with pytest.raises(ValueError):Executor(service,InterruptedLane(),broker).run(task_id,work)
        old=store.db.tasks.find_one({'_id':task_id})
        assert old['state']=='CANCELLED' and old['cancel_reason']=='host_stop' and 'result' not in old
        current=store.db.tasks.find_one({'_id':replacement['_id']})
        assert current['state']=='RUNNING' and current['fencing_token']==replacement['fencing_token']
        assert current['continues_task_id']==task_id and current['brief']=='改成第二版'
        assert current['execution_binding']==old['execution_binding']
        # The shared action session now works for the replacement only.
        session='s-'+sha(current['execution_binding'].encode())[:40]
        broker.bind(session,current,work)
        assert broker.call(session,'after','list_files',{})['evidence_ref']
        assert store.db.artifacts.find_one({'task_id':current['_id'],'tool':'list_files','state':'DONE'})
        assert router.receive(event)['task_ids']==[replacement['_id']] and store.db.tasks.count_documents({})==2
    finally:broker.close()


def test_E16_busy_workspace_is_not_claimed(store,runtime_work):
    service,router=route(store)
    ep=router.receive({'event_id':'work','scene_id':'dm-a','person_id':'A','text':'核实'})
    work=runtime_work('busy');work.mkdir()
    key=sha(str(work.resolve()).casefold().encode())
    with RuntimeLease(ROOT/'.runtime/locks'/('workspace-'+key+'.lock')):
        with pytest.raises(TimeoutError):Executor(service,None,None).run(ep['task_ids'][0],work)
    assert store.db.tasks.find_one({'_id':ep['task_ids'][0]})['state']=='READY'


def test_E19_rollback_rejects_other_scope_and_preserves_source_accounting(store):
    old=store.head('relationship:A','scene:dm-a')[1]
    new=store.mutate('relationship:A','scene:dm-a',old['_id'],{'body':'new'},['M02'],'scene:dm-a','new-relation')
    service=MemoryService(store)
    foreign=store.head('relationship:B','scene:dm-b')[1]
    with pytest.raises(Denied):service.rollback('relationship:A','scene:dm-a',foreign['_id'],new['_id'],'bad',operator=True)
    back=service.rollback('relationship:A','scene:dm-a',old['_id'],new['_id'],'back',operator=True)
    assert back['content']==old['content'] and back['processed_source_ids']==new['processed_source_ids']


