import json,time,uuid
from pathlib import Path
import pytest
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,FakeTurn
from asuna.sandbox import Sandbox
from asuna.config import ROOT
from asuna.privacy import PrivacyService
from asuna.state import Denied
from asuna.audit import verify
from asuna.tasks import TaskService,ToolBroker
from test_engineering_m1 import event


def normal(store):
    """One ordinary character turn: her thought, then what she says."""
    lane=FakeLane(store,[FakeTurn([('think',{'thought':'PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'})],'回来了。')])
    return Coordinator(store,lane),lane


def task_setup(store):
    """A running task she delegated in dm-a without saying anything yet, bound to the fixture grant's
    workspace as session s-test (nothing is published before the tests start)."""
    turn=FakeTurn([('think',{'thought':'交给行动脑复制，原件要保留。'}),
                   ('delegate',{'title':'copy fixture','brief':'复制受控文件，保留原件。'}),
                   ('stay_silent',{'reason':'做完再说'})])
    ep=Coordinator(store,FakeLane(store,[turn])).ingest({'event_id':'copy','scene_id':'dm-a','person_id':'A','text':'复制受控文件，保留原件。'})
    service=TaskService(store);task=service.claim(ep['task_ids'][0])
    work=Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])
    (work/'a.txt').write_text('controlled original',encoding='utf-8')
    broker=ToolBroker(service);broker.bind('s-test',task,work)
    return service,task,broker,work


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
        ref=broker.call('s-test','inspect','list_files',{})['evidence_ref']
        # The executor's natural-language report with program-attached receipts (tasks.Executor).
        current=store.db.tasks.find_one({'_id':task['_id']})
        done=store.put('tasks',{**current,'state':'RETURNED','feedback_state':'READY','result':{'task_id':task['_id'],
            'intent_revision':1,'text':'文件已查阅','facts':[{'text':'文件已查阅','evidence_refs':[ref]}],'artifact_refs':[ref]}},
            expected=current['revision'])
        lane=FakeLane(store,[FakeTurn([('think',{'thought':'这是工具结果，我来说明。'})],'文件已经查过了。')])
        c=Coordinator(store,lane)
        assert service.feedback(done,c)['state']=='COMMITTED'
        for _ in range(3):assert service.feedback(done,c) is None
        assert len(lane.calls)==1 and len(store.public_messages('dm-a','A'))==1
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
