import getpass
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,FakeTurn
from asuna.state import Denied
from asuna.tasks import TaskService,ToolBroker


def mongo_endpoint(config):
    """The configured Mongo host the sandbox must not reach; derived, never hard-coded."""
    try:
        parts = urlsplit(config.get('mongo_uri') or '')
        if parts.hostname and ',' not in parts.netloc:
            return parts.hostname, parts.port or 27017
    except ValueError:
        pass
    return '192.0.2.10', 27017


def granted_workspace(store):
    """The fixture grant's workspace (tests/fixture_grant.py); delegation is workspace mode only."""
    return Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])


def task_setup(store):
    # She hands the copy to the action brain and says nothing until the result is back.
    lane=FakeLane(store,[FakeTurn([('think',{'thought':'先核实。'}),
                                   ('delegate',{'title':'copy fixture','brief':'复制受控文件，保留原件。'}),
                                   ('stay_silent',{'reason':'等结果'})])])
    # Running commands is for the owner's own scenes: dm-a is the owner's DM (A is the owner by account).
    store.config['canonical_persons']={'A':store.config['chat']['person_id']}
    ep=Coordinator(store,lane).ingest({'event_id':'copy','scene_id':'dm-a','person_id':'A','text':'复制受控文件，保留原件。'})
    assert ep['state']=='WAITING_TASK' and len(ep['task_ids'])==1
    service=TaskService(store);task=service.claim(ep['task_ids'][0])
    work=granted_workspace(store)
    (work/'a.txt').write_text('controlled original',encoding='utf-8')
    broker=ToolBroker(service);broker.bind('s-test',task,work)
    return service,task,broker,work


def test_E16_cancel_fences_tool_and_result(store):
    service,task,broker,work=task_setup(store)
    try:
        read=broker.call('s-test','read','list_files',{})
        service.cancel(task['_id'],person_id='A')
        with pytest.raises(Denied):broker.call('s-test','late','write_file',{'path':'late.txt','text':'late'})
        assert not (work/'late.txt').exists()
        assert store.db.artifacts.find_one({'_id':read['evidence_ref']})['state']=='DONE'
    finally:broker.close()


def test_E14_repeated_call_id_replays_the_recorded_effect(store):
    service,task,broker,work=task_setup(store)
    try:
        args={'path':'out.txt','text':'controlled original'}
        effect=broker.call('s-test','commit','write_file',args)
        for _ in range(100):assert broker.call('s-test','commit','write_file',args)==effect
        assert store.db.artifacts.count_documents({'task_id':task['_id'],'tool':'write_file'})==1
        assert (work/'a.txt').read_bytes()==(work/'out.txt').read_bytes()
    finally:broker.close()


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


def test_E08_cancelled_task_gets_no_feedback(store):
    service,task,broker,work=task_setup(store)
    try:
        assert store.db.tasks.find_one({'_id':task['_id']})['state']=='RUNNING'
        service.cancel(task['_id'],person_id='A')
        assert service.feedback(store.db.tasks.find_one({'_id':task['_id']}),None) is None
    finally:broker.close()
