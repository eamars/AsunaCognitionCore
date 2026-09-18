from datetime import datetime,timezone
import json
import uuid
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.evidence import Evidence,write_json
from asuna.dsh_lane import DshLane
from asuna.coordinator import Coordinator
from asuna.audit import render_html

run='M2-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run)
cfg=load();store=Store(cfg,'asuna_v2_test_'+run.replace('-','_'))
store.migrate();store.seed()
status='FAIL'
try:
    with DshLane(cfg,store,ev) as lane:
        ep=Coordinator(store,lane).ingest({'event_id':'greeting','scene_id':'dm-a','person_id':'A','text':'我回来了。不办事，聊两句。'})
        assert ep['state']=='COMMITTED',ep['state']
        assert len(lane.proxy.calls)==3
        for call in lane.proxy.calls:
            body=json.dumps(call['body'],ensure_ascii=False)
            assert '沈小满' in body and 'A 愿意让我自己决定' in body
            assert not call['body'].get('tools')
    # Fresh process, same home and scene: native DSH resume, not a fresh transcript.
    with DshLane(cfg,store,ev) as lane:
        ep2=Coordinator(store,lane).ingest({'event_id':'continued','scene_id':'dm-a','person_id':'A','text':'刚才我说这次回来想做什么？'})
        assert ep2['state']=='COMMITTED',ep2['state']
        assert '不办事，聊两句' in json.dumps(lane.proxy.calls[0]['body'],ensure_ascii=False)
    events=list(store.db.audit_events.find({}).sort([('stream_id',1),('seq',1)]))
    write_json(ev.root/'trace.json',events)
    render_html(events,ev.root/'trace.html')
    status='PASS'
except Exception as exc:
    ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
write_json(ev.root/'result.json',{'status':status,'database':store.name,'command':'.venv/Scripts/python.exe tools/probe_live_coordinator.py','exit_code':0 if status=='PASS' else 1,'limitations':['not 60-episode L01','no human cognition review','no forced process crash in this probe']})
print(json.dumps({'run':run,'status':status}))
raise SystemExit(0 if status=='PASS' else 1)
