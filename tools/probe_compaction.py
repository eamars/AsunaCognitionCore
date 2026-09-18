from datetime import datetime,timezone
import json,uuid
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.evidence import Evidence,write_json,sha
from asuna.dsh_lane import DshLane
from asuna.coordinator import Coordinator

run='M5-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run);cfg=load();store=Store(cfg,'asuna_v2_test_'+run.replace('-','_'));status='FAIL'
write_json(ev.root/'manifest.json',{'experiment_id':run,'kind':'native-compaction-probe','bridge_sha256':sha((ROOT/'dsh-plugin/runtime.ts').read_bytes()),'compaction_sha256':sha((ROOT/'dsh-plugin/compaction.ts').read_bytes()),'package_lock_sha256':sha((ROOT/'package-lock.json').read_bytes()),'sampling':cfg['character']['sampling']})
try:
    store.migrate();store.seed()
    with DshLane(cfg,store,ev) as lane:
        c=Coordinator(store,lane)
        ep=c.ingest({'event_id':'before','scene_id':'dm-a','person_id':'A','text':'我回来了。不办事，聊两句。'})
        assert ep['state']=='COMMITTED'
        lane.compact('xiaoman:dm-a:1:P1')
        ep2=c.ingest({'event_id':'after','scene_id':'dm-a','person_id':'A','text':'我刚才回来想做什么？'})
        assert ep2['state']=='COMMITTED',ep2['state']
        compact=list(store.db.audit_events.find({'type':'compaction.native'}))
        assert len(compact)==1
        result=compact[0]['payload']['result']
        assert result
        assert len(lane.proxy.calls)==7,len(lane.proxy.calls)
        write_json(ev.root/'native_result.json',compact)
        assert 'compacted-summary' in json.dumps(lane.proxy.calls[-1]['body'])
        status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
write_json(ev.root/'result.json',{'status':status,'database':store.name,'command':'.venv/Scripts/python.exe tools/probe_compaction.py','exit_code':0 if status=='PASS' else 1,'limitations':['one actual character compaction, not full independent-cycle matrix','not a long-context capacity test','summary semantic retention requires further evaluation']})
print(json.dumps({'run':run,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
