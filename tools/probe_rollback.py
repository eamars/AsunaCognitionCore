import json,sys,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.state import Store,Denied,Conflict
from asuna.memory import MemoryService
from asuna.coordinator import Coordinator
from asuna.context import ContextBuilder
from asuna.lanes import FakeLane,LaneResult

name='rollback-probe-'+uuid.uuid4().hex[:10];ev=Evidence(ROOT/'reports'/name);cfg=load();freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-L06-rollback')
store=Store(cfg,'asuna_v2_test_'+name.replace('-','_'));store.migrate();store.seed();status='FAIL'
try:
    old=store.head('relationship:A','scene:dm-a')[1]
    changed=store.mutate('relationship:A','scene:dm-a',old['_id'],{'body':'我会先做可撤回的选择，再等反馈。','trust':3},['M02'],'scene:dm-a','change')
    event={'event_id':'before-rollback','scene_id':'dm-a','person_id':'A','text':'我回来了'}
    decision={'next':'silent','goal':'等待','constraints':[],'recall_query':'','speak_before_action':False}
    episode=Coordinator(store,FakeLane(store,[LaneResult('我记得新的理解。'),LaneResult(json.dumps(decision))])).ingest(event)
    assert episode['manifest']['relationship_revision']==changed['_id']
    service=MemoryService(store)
    try:service.rollback('relationship:A','scene:dm-a',old['_id'],changed['_id'],'rollback');raise AssertionError('unauthorized rollback')
    except Denied:pass
    value=service.rollback('relationship:A','scene:dm-a',old['_id'],changed['_id'],'rollback',operator=True)
    assert value['content']==old['content'] and value['parent_revision_id']==changed['_id']
    assert value['processed_source_ids']==changed['processed_source_ids']
    assert service.rollback('relationship:A','scene:dm-a',old['_id'],changed['_id'],'rollback',operator=True)['_id']==value['_id']
    _,context,manifest=ContextBuilder(store).prepare({**event,'event_id':'next'})
    assert context['relationship']==old['content'] and manifest['relationship_revision']==value['_id']
    assert store.db.episodes.find_one({'_id':episode['_id']})['manifest']['relationship_revision']==changed['_id']
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:write_json(ev.root/'trace.json',list(store.db.audit_events.find({})));store.client.close()
code=0 if status=='PASS' else 1
write_json(ev.root/'result.json',{'test_id':'PROBE-L06-rollback','status':status,'mode':'real_Mongo_fake_character_version_snapshots','commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}]});print(json.dumps({'run':name,'status':status}));raise SystemExit(code)
