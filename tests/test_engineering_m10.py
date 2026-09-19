import copy,json,uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
from asuna.audit import replay,projection,verify
from asuna.config import load,ROOT
from asuna.state import Store,Conflict,Denied
from asuna.context import ContextBuilder
from asuna.publish import PublishService
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.dsh_lane import provider_finish
from test_engineering_m1 import normal,event,decision
from test_engineering_m3 import task_setup


def test_E05_undelivered_are_explicit_and_survive_new_store(store):
    for i,state in enumerate(('READY','FAILED','UNKNOWN','DELIVERED')):
        store.put('messages',{'_id':state,'scene_id':'dm-a','scope_key':'scene:dm-a','scene_seq':i,'text':state+'_body','author':'xiaoman','direction':'outbound','delivery_state':state})
    reopened=Store(load(),store.name)
    try:
        _,context,_=ContextBuilder(reopened).prepare(event())
        assert [m['delivery_state'] for m in context['delivered_history']]==['DELIVERED']
        assert {m['delivery_state'] for m in context['undelivered_outbound_not_public']}=={'READY','FAILED','UNKNOWN'}
    finally:reopened.client.close()


def test_E17_twenty_mutation_ids_replayed_after_cas(store):
    head,base=store.head('persona:P1','global-safe');source=store.db.memory_units.find_one({'scope_key':'global-safe'})['_id']
    def apply(i):
        try:return store.mutate('persona:P1','global-safe',base['_id'],{'body':'choice-'+str(i)},[source],'global-safe','retry-cas-'+str(i))
        except Conflict:return None
    with ThreadPoolExecutor(20) as pool:results=list(pool.map(apply,range(20)))
    winner=[i for i,row in enumerate(results) if row is not None];assert len(winner)==1
    count=store.db.state_revisions.count_documents({})
    again=[apply(i) for i in range(20)]
    assert [i for i,row in enumerate(again) if row is not None]==winner
    assert store.db.state_revisions.count_documents({})==count
    current=store.head('persona:P1','global-safe')[1]
    assert current['_id']==results[winner[0]]['_id'] and current['parent_revision_id']==base['_id']


def test_E12_E13_executor_cannot_publish_or_reach_host(store,monkeypatch):
    service,task,broker,work=task_setup(store)
    monkeypatch.setenv('MONGODB_URI','synthetic-host-only-mongo-credential')
    try:
        for tool in ('send_message','publish','mongo_write','persona_update'):
            with pytest.raises(Denied):broker.call('s-test',tool,tool,{'text':'executor text'})
        code=f"import socket,os,pathlib; assert 'MONGODB_URI' not in os.environ; assert not pathlib.Path('/mnt/c').exists(); s=socket.socket();s.settimeout(1);assert s.connect_ex(('127.0.0.1',{broker.server.server_port}))!=0;pathlib.Path('allowed.txt').write_text('local effect only')"
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
    head,_=store.head('persona:P1','global-safe')
    with pytest.raises(Denied,match='DERIVED_SOURCE_SCOPE_DENIED'):store.mutate('persona:P1','global-safe',head['revision_id'],{'body':'new'},['claimed-public'],'global-safe','invalid-source')


def test_E21_audit_failure_immediately_before_sink(store):
    def fault(point):
        if point=='before_send':store.fail_audit=True
    c,lane=normal(store);c.publisher=PublishService(store,crash=fault)
    with pytest.raises(OSError):c.ingest(event())
    assert store.db.sink_receipts.count_documents({})==0
    store.fail_audit=False


def test_E23_mixed_state_replay_without_external_actions(store):
    c,_=normal(store);c.ingest(event('done'))
    bad=Coordinator(store,FakeLane(store,[LaneResult('',reasoning='only')]))
    assert bad.ingest(event('failure'))['state']=='FAILED_PROTOCOL'
    def fault(point):
        if point=='after_send_before_receipt':raise RuntimeError('lost receipt')
    unknown,_=normal(store);unknown.publisher=PublishService(store,idempotent=False,crash=fault)
    with pytest.raises(RuntimeError):unknown.ingest(event('unknown'))
    unknown.publisher=PublishService(store,idempotent=False);unknown.recover()
    service,task,broker,work=task_setup(store)
    try:
        service.cancel(task['_id'],person_id='A')
        with pytest.raises(Denied):service.finish(task,{})
    finally:broker.close()
    head,base=store.head('persona:P1','global-safe');source=store.db.memory_units.find_one({'scope_key':'global-safe'})['_id']
    store.mutate('persona:P1','global-safe',base['_id'],base['content'],[source],'global-safe','winning')
    with pytest.raises(Conflict):store.mutate('persona:P1','global-safe',base['_id'],base['content'],[source],'global-safe','conflicting')
    trace=list(store.db.audit_events.find({}));verify(trace)
    target=Store(load(),'asuna_v2_test_mixed_replay_'+uuid.uuid4().hex[:16])
    try:
        with patch('httpx.Client.send',side_effect=AssertionError('network forbidden')),patch('asuna.sandbox.Sandbox.run',side_effect=AssertionError('tool forbidden')):
            assert replay(trace,target)['sha256']==projection(store)['sha256']
        modified=copy.deepcopy(trace);modified[-1]['payload']={'tampered':True}
        with pytest.raises(ValueError,match='HASH_CHAIN'):verify(modified)
    finally:target.client.close()


def test_E07_provider_length_is_not_stop():
    assert provider_finish('data: {"choices":[{"finish_reason":"length"}]}\n\ndata: [DONE]\n')=='length'
    assert provider_finish('data: {"choices":[{"finish_reason":"stop"}]}\n\ndata: {"usage":{"completion_tokens":10},"choices":[]}\n')=='stop'
