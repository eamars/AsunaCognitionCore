"""M1 executable vertical slice, real MongoDB + explicitly fake model lane."""
import json
import uuid
from asuna.config import ROOT,load
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane,LaneResult
from asuna.state import Store
from asuna.evidence import write_json

run='M1-probe-'+uuid.uuid4().hex[:8]
store=Store(load(),'asuna_v2_test_'+run.replace('-','_'))
store.migrate();store.seed()
lane=FakeLane(store,[LaneResult('PRIVATE_INTERNAL_THOUGHT_TEST_ONLY'),LaneResult(json.dumps({'next':'speak','goal':'回应','constraints':[],'recall_query':'','speak_before_action':False})),LaneResult('回来了。')])
coordinator=Coordinator(store,lane)
event={'event_id':'probe-normal','scene_id':'dm-a','person_id':'A','text':'我回来了。'}
ep=coordinator.ingest(event)
for _ in range(100):
    coordinator.ingest(event)
public=store.public_messages('dm-a','A')
assert ep['state']=='COMMITTED' and len(public)==1 and len(lane.calls)==3
assert 'PRIVATE_INTERNAL' not in json.dumps(public)
record={'status':'PASS','mode':'fake-model-real-mongodb','test_ids':['E03','E04','E14-partial'], 'episode_id':ep['_id'],'database':store.name,'calls':lane.calls,'public':public,'command':'.venv/Scripts/python.exe tools/probe_coordinator.py','exit_code':0,'limitations':['not five process-crash points','not formal E03/E04 complete acceptance']}
write_json(ROOT/'reports'/run/'result.json',record)
write_json(ROOT/'reports'/run/'trace.json',list(store.db.audit_events.find({}).sort([('stream_id',1),('seq',1)])))
print(json.dumps({'run':run,'status':'PASS','database':store.name}))
