"""Narrow real A02 load probe before the full, separately frozen matrix."""
import json,sys,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.noise_trials import executor_load

name='noise-load-probe-'+uuid.uuid4().hex[:10]
ev=Evidence(ROOT/'reports'/name);cfg=load()
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-A02')
result=executor_load(cfg,ev,'noisy+compact',1)
code=0 if result['status']=='PASS' else 1
result.update(test_id='PROBE-A02',commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}])
write_json(ev.root/'result.json',result)
print(json.dumps({'run':name,'status':result['status']}),flush=True)
raise SystemExit(code)
