from datetime import datetime,timezone
import json,uuid
from asuna.config import ROOT,load
from asuna.state import Store
from asuna.evidence import Evidence,write_json
from asuna.dsh_lane import DshLane
from asuna.memory import MemoryService

run='M4-reflect-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run);store=Store(load(),'asuna_v2_test_'+run.replace('-','_'));status='FAIL'
try:
    store.migrate();store.seed()
    with DshLane(load(),store,ev) as lane:
        result=MemoryService(store).reflect(lane,'scene:dm-a','relationship:A',run)
        assert len(lane.proxy.calls)==1
        write_json(ev.root/'reflection.json',result);status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
write_json(ev.root/'result.json',{'status':status,'database':store.name,'command':'.venv/Scripts/python.exe tools/probe_reflection.py','exit_code':0 if status=='PASS' else 1,'limitations':['one actual bounded reflection; not full evolution fixture suite']})
print(json.dumps({'run':run,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
