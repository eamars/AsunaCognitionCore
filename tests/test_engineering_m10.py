import pytest
from asuna.state import Denied
from asuna.publish import PublishService
from test_engineering_m1 import event
from test_engineering_m6 import normal, task_setup


def test_E12_E13_executor_cannot_publish_or_reach_host(store,monkeypatch):
    service,task,broker,work=task_setup(store)
    monkeypatch.setenv('MONGODB_URI','synthetic-host-only-mongo-credential')
    try:
        for tool in ('send_message','publish','mongo_write','persona_update'):
            with pytest.raises(Denied):broker.call('s-test',tool,tool,{'text':'executor text'})
        code=f"import socket,os,pathlib; assert 'MONGODB_URI' not in os.environ; assert not pathlib.Path('/mnt/c').exists(); s=socket.socket();s.settimeout(1);assert s.connect_ex(('127.0.0.1',27017))!=0;pathlib.Path('allowed.txt').write_text('local effect only')"
        assert broker.call('s-test','script','sandbox_run',{'argv':['python3','-c',code]})['exit_code']==0
        store.put('messages',{'_id':'qwen-bypass','scope_key':'scene:dm-a','author':'qwen','phase':'SPEAK','text':'invented completion','delivery_state':'READY'})
        with pytest.raises(Denied):PublishService(store).publish('qwen-bypass')
        assert store.db.sink_receipts.count_documents({})==0
        c,_=normal(store);assert c.ingest(event('legitimate'))['state']=='COMMITTED'
        assert len(store.public_messages('dm-a','A'))==1 and (work/'allowed.txt').exists()
    finally:broker.close()


def test_E19_message_source_cannot_be_laundered(store):
    store.put('messages',{'_id':'private-source','scope_key':'scene:dm-a','text':'synthetic private source'})
    store.put('memory_units',{'_id':'claimed-public','scope_key':'global-safe','status':'active','source_event_ids':['private-source'],'body_markdown':'anonymous reinterpretation'})
    head=store.init_head('relationship:P1','global-safe',{'body':'fixture relationship'},[])
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):store.mutate('relationship:P1','global-safe',head['revision_id'],{'body':'new'},['claimed-public'],'global-safe','invalid-source')


