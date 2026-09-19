import json,time,uuid
import pytest
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.router import Router,FairQueue
from asuna.sandbox import Sandbox
from asuna.config import ROOT
from asuna.privacy import PrivacyService
from asuna.state import Denied
from asuna.audit import verify
from test_engineering_m1 import decision,event,normal
from test_engineering_m3 import task_setup


def test_E24_queue_fairness_and_group_quiet(store):
    q=FairQueue()
    for scene in ('g1','g2'):
        for i in range(5):q.put(scene,scene)
    values=[]
    while (value:=q.pop()) is not None:values.append(value)
    assert values==['g1','g1','g2','g2','g1','g1','g2','g2','g1','g2']
    lane=FakeLane(store,[]);router=Router(store,Coordinator(store,lane))
    for _ in range(100):assert router.receive(event(scene='g1'))['state']=='RECEIVED_NO_WAKE'
    assert not lane.calls and store.db.messages.count_documents({'scene_id':'g1'})==1


def test_E09_E16_owner_cancellation_and_expired_lease(store):
    service,task,broker,work=task_setup(store)
    try:
        for actor in ('B','C',None):
            with pytest.raises(Denied):service.cancel(task['_id'],person_id=actor)
        store.db.tasks.update_one({'_id':task['_id']},{'$set':{'lease_expires_at':time.time()-1}})
        with pytest.raises(Denied,match='LEASE_EXPIRED'):broker.call('s-test','expired','fixture_lookup',{})
        service.cancel(task['_id'],person_id='A')
        assert store.db.tasks.find_one({'_id':task['_id']})['state']=='CANCELLED'
    finally:broker.close()


def test_E06_duplicate_result_one_character_feedback(store):
    service,task,broker,work=task_setup(store)
    try:
        ref=broker.call('s-test','inspect','fixture_lookup',{})['evidence_ref']
        value={'task_id':task['_id'],'intent_revision':1,'status':'done','facts':[{'text':'文件已查阅','evidence_refs':[ref]}],'artifact_refs':[ref],'effect_receipts':[],'uncertainties':[],'unmet_items':[],'needs_decision':None}
        done=service.finish(task,value)
        lane=FakeLane(store,[LaneResult('这是工具结果，我来说明。'),decision(),LaneResult('文件已经查过了。')])
        c=Coordinator(store,lane)
        assert service.feedback(done,c)['state']=='COMMITTED'
        for _ in range(3):assert service.feedback(done,c) is None
        assert len(lane.calls)==3 and len(store.public_messages('dm-a','A'))==1
        assert '文件已查阅'!=store.public_messages('dm-a','A')[0]['text']
    finally:broker.close()


def test_E12_output_cap_and_literal_shell_arguments():
    work=ROOT/'.runtime/work'/('limits-'+uuid.uuid4().hex);sandbox=Sandbox(work)
    text='literal; $(touch /tmp/ASUNA_HOST_ESCAPE) `echo nope`'
    result=sandbox.run(['python3','-c','import sys;print(sys.argv[1])',text])
    assert result['stdout'].strip()==text
    with pytest.raises(RuntimeError,match='OUTPUT_LIMIT'):
        sandbox.run(['python3','-c','import os;\nwhile True:os.write(1,b"x"*8192)'])
    assert sandbox.run(['python3','-c','print("still operational")'])['exit_code']==0


def test_E20_erasure_preserves_unique_keys_and_refences_context(store):
    c,lane=normal(store);c.ingest(event())
    c,lane=normal(store);c.ingest(event('second'))
    result=PrivacyService(store).delete_memory('M09',operator=True)
    assert result['policy_epoch']==2
    assert store.db.episodes.count_documents({'state':'INVALIDATED'})==2
    assert store.db.memory_units.find_one({'_id':'M09'})['status']=='tombstone'
    verify(list(store.db.audit_events.find({})))
    c,lane=normal(store);assert c.ingest(event('third'))['state']=='COMMITTED'
    assert 'PRIVATE_A_CANARY' not in json.dumps(lane.calls)
