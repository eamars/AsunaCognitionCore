"""Probe the hardest real independent-compaction condition before full L09."""
import json,sys,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze
from asuna.matrix_trials import suite

ev=Evidence(ROOT/'reports'/('matrix-probe-'+uuid.uuid4().hex[:10]));cfg=load()
manifest=freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-L09')
result=suite(cfg,ev,repetitions=1,conditions=((3,5),))
code=1 if result['status']=='FAIL' else 0
result.update(test_id='PROBE-L09',experiment_id=manifest['experiment_id'],manifest_sha256=sha((ev.root/'manifest.json').read_bytes()),commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}])
write_json(ev.root/'result.json',result);print(json.dumps({'run':ev.root.name,'status':result['status']}),flush=True);raise SystemExit(code)
