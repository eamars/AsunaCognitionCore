"""An actual native lane must reject the erased old binding before a model call."""
import json,sys,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze
from asuna.state import Store
from asuna.dsh_lane import DshLane

source=ROOT/'reports/E20-probe-20260919T105127Z-700191/result.json'
prior=json.loads(source.read_text(encoding='utf-8'));assert prior['status']=='PASS'
ev=Evidence(ROOT/'reports'/('erasure-reuse-probe-'+uuid.uuid4().hex[:10]));cfg=load();freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E20-reuse')
store=Store(cfg,prior['database']);status='FAIL'
try:
    with DshLane(cfg,store,ev) as lane:
        try:lane.generate('xiaoman:dm-a:1:P1','erased-old-binding:MONOLOGUE:0','MONOLOGUE','old binding reuse probe','unused');raise AssertionError('erased binding accepted')
        except PermissionError as exc:assert str(exc)=='SESSION_INVALIDATED'
        assert not lane.proxy.calls
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:store.client.close()
code=0 if status=='PASS' else 1
write_json(ev.root/'result.json',{'test_id':'PROBE-E20-reuse','status':status,'source_erasure_result':{'artifact_path':source.relative_to(ROOT).as_posix(),'sha256':sha(source.read_bytes())},'model_calls':0 if status=='PASS' else None,'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}]});print(json.dumps({'run':ev.root.name,'status':status}));raise SystemExit(code)
