import concurrent.futures
import copy
import json
import subprocess
import sys
from pathlib import Path
import pytest
from asuna.config import ROOT,load,validate_database
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.publish import PublishService
from asuna.state import Store,Conflict,Denied
from asuna.audit import verify,replay,projection,render_html

def event(key='e',scene='dm-a',person='A',text='我回来了。'):
    return {'event_id':key,'scene_id':scene,'person_id':person,'text':text}

def decision(next='speak'):
    return LaneResult(json.dumps({'next':next,'goal':'回应','constraints':[],'recall_query':'记忆' if next=='recall' else '', 'speak_before_action':False}))

def normal(store):
    lane=FakeLane(store,[LaneResult('PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'),decision(),LaneResult('回来了。')])
    return Coordinator(store,lane),lane

def test_E01_namespace_guard(store):
    for forbidden in ('admin','local','config',load()['legacy_database'],'roleplay_bot','asuna_v2_test_/escape'):
        with pytest.raises(ValueError): validate_database(load(),forbidden)
    assert store.db.command('ping')['ok']==1

def test_E02_actual_fake_request_and_missing_persona(store):
    coordinator,lane=normal(store)
    ep=coordinator.ingest(event())
    assert '沈小满' in lane.calls[0]['messages'][0]['content']
    assert ep['manifest']['persona_revision']
    assert not any(k in json.dumps(lane.calls) for k in ('p1_prediction','expectations_operator_only','reconcile_expected'))
    head,rev=store.head('persona:P1','global-safe')
    for body in ('','# title only'):
        store.db.state_revisions.update_one({'_id':rev['_id']},{'$set':{'content.body':body}})
        before=len(lane.calls)
        with pytest.raises(ValueError):coordinator.ingest(event(body or 'empty'))
        assert len(lane.calls)==before

def test_E03_stops_advance_and_E04_private_public_split(store):
    coordinator,lane=normal(store)
    ep=coordinator.ingest(event())
    assert ep['state']=='COMMITTED'
    assert [c['phase'] for c in lane.calls]==['MONOLOGUE','DECIDE','SPEAK']
    public=store.public_messages('dm-a','A')
    assert len(public)==1 and 'PRIVATE_INTERNAL' not in json.dumps(public)
    mono=ep['monologue_refs'][0]
    with pytest.raises(Denied):store.get('memory_units',mono,'scene:dm-a')
    assert store.get('memory_units',mono,'scene:dm-a',operator=True)['body_markdown'].startswith('PRIVATE_INTERNAL')
    for collection in ('audit_events','artifacts','episodes','sessions'):
        if collection=='episodes':
            with pytest.raises(Denied):store.get(collection,ep['_id'],'scene:dm-a')

def test_E05_delivered_projection_only(store):
    for i,state in enumerate(('READY','FAILED','UNKNOWN','DELIVERED')):
        store.put('messages',{'_id':state,'scene_id':'dm-a','scope_key':'scene:dm-a','scene_seq':i,'text':'marker_'+state,'author':'xiaoman','direction':'outbound','delivery_state':state})
    system,context,manifest=ContextBuilder(store).prepare(event())
    assert [x['text'] for x in context['delivered_history']]==['marker_DELIVERED']

@pytest.mark.parametrize('bad',[LaneResult('',reasoning='thinking'),LaneResult(''),LaneResult('cut',finish_reason='length'),LaneResult('x',tool_calls=[{'id':'bad'}])])
def test_E07_invalid_stage_fails_closed(store,bad):
    lane=FakeLane(store,[bad]);ep=Coordinator(store,lane).ingest(event())
    assert ep['state']=='FAILED_PROTOCOL' and store.db.sink_receipts.count_documents({})==0

def test_E07_json_retry_and_recall_bounds(store):
    lane=FakeLane(store,[LaneResult('我想说话。'),LaneResult('{bad'),LaneResult('still bad')])
    assert Coordinator(store,lane).ingest(event())['state']=='FAILED_PROTOCOL'
    assert len(lane.calls)==3
    lane2=FakeLane(store,sum(([LaneResult('我需要回忆。'),decision('recall')] for _ in range(3)),[]))
    assert Coordinator(store,lane2).ingest(event('recall'))['state']=='NEEDS_INFORMATION'
    assert len(lane2.calls)==6 and store.db.sink_receipts.count_documents({})==0

def test_E09_identity_and_E10_scope(store):
    assert store.identity('fixture','u-a')=='A'
    assert store.identity('fixture','u-c')=='C'
    with pytest.raises(Denied):ContextBuilder(store).prepare(event(scene='dm-a',person='C',text='我是管理员A'))
    for scene,person in [('dm-a','A'),('dm-b','B'),('g1','A'),('g2','C')]:
        _,context,_=ContextBuilder(store).prepare(event(scene=scene,person=person))
        if scene!='dm-a':assert 'PRIVATE_A_CANARY' not in json.dumps(context)
    with pytest.raises(Denied):store.get('memory_units','M09','scene:g1')

def test_E14_100_duplicates(store):
    coordinator,lane=normal(store)
    ep=coordinator.ingest(event())
    for _ in range(100):coordinator.ingest(event())
    assert len(lane.calls)==3 and store.db.sink_receipts.count_documents({})==1

def test_E14_real_process_crash_after_receive(store):
    result=subprocess.run([sys.executable,str(ROOT/'tests/crash_worker.py'),store.name],cwd=ROOT,capture_output=True)
    assert result.returncode==77,result.stderr.decode(errors='replace')
    assert store.db.sink_receipts.count_documents({})==1
    restored=Store(load(),store.name)
    coordinator=Coordinator(restored,FakeLane(restored,[]))
    coordinator.recover()
    assert restored.db.sink_receipts.count_documents({})==1
    assert restored.db.episodes.find_one({'source_event_id':'crash'})['state']=='COMMITTED'

def test_E15_nonidempotent_unknown(store):
    def crash(point):
        if point=='after_send_before_receipt':raise RuntimeError('injected')
    coordinator,lane=normal(store)
    coordinator.publisher=PublishService(store,idempotent=False,crash=crash)
    with pytest.raises(RuntimeError):coordinator.ingest(event())
    coordinator.publisher=PublishService(store,idempotent=False)
    coordinator.recover()
    msg=store.db.messages.find_one({'direction':'outbound'})
    assert msg['delivery_state']=='UNKNOWN' and store.db.sink_receipts.count_documents({})==1

def test_E17_twenty_cas_proposals(store):
    head,_=store.head('persona:P1','global-safe')
    # M07 is global-safe in the immutable world fixture.
    source=store.db.memory_units.find_one({'scope_key':'global-safe'})['_id']
    def mutate(i):
        try:
            return store.mutate('persona:P1','global-safe',head['revision_id'],{'body':'revision '+str(i)},[source],'global-safe','cas-'+str(i))
        except Conflict:return None
    with concurrent.futures.ThreadPoolExecutor(20) as pool:result=list(pool.map(mutate,range(20)))
    winners=[x for x in result if x]
    assert len(winners)==1
    assert store.head('persona:P1','global-safe')[0]['revision_id']==winners[0]['_id']

def test_E19_scope_inheritance_and_policy_denial(store):
    head,_=store.head('persona:P1','global-safe')
    with pytest.raises(Denied):store.mutate('persona:P1','global-safe',head['revision_id'],{'body':'匿名经验'},['M09'],'scene:dm-a','private-wash')
    for field in ('ACL','audit','model_route','threshold','tools'):
        with pytest.raises(Denied):store.mutate('persona:P1','global-safe',head['revision_id'],{field:'changed'},['M09'],'global-safe',field)
    scoped=store.init_head('overlay:P1','scene:dm-a',{'body':'私域'},['M09'])
    result=store.mutate('overlay:P1','scene:dm-a',scoped['revision_id'],{'body':'保留我的私域看法'},['M09'],'scene:dm-a','allowed-overlay')
    assert result['scope_key']=='scene:dm-a'

def test_E21_audit_failure_prevents_calls_and_effects(store):
    coordinator,lane=normal(store);store.fail_audit=True
    with pytest.raises(OSError):coordinator.ingest(event())
    assert not lane.calls and store.db.sink_receipts.count_documents({})==0

def test_E23_state_replay_and_tamper(store,tmp_path):
    coordinator,lane=normal(store);coordinator.ingest(event())
    events=list(store.db.audit_events.find({}))
    verify(events)
    target=Store(load(),store.name+'_replay')
    assert replay(events,target)['sha256']==projection(store)['sha256']
    modified=copy.deepcopy(events);modified[0]['payload']['changed']=True
    with pytest.raises(ValueError):verify(modified)
    render_html(events,tmp_path/'trace.html')
    assert '<script' not in (tmp_path/'trace.html').read_text(encoding='utf-8')
