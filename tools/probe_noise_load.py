"""A narrow real executor load probe, through the production task route."""
import json, sys, uuid
from datetime import datetime, timezone
from asuna.config import ROOT, BUNDLE, load
from asuna.evidence import Evidence, write_json, sha
from asuna.experiments import freeze
from asuna.noise_trials import executor_load

cfg=load()
ev=Evidence(ROOT/'reports'/('noise-load-probe-'+uuid.uuid4().hex[:10]))
manifest=freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-A02-LOAD')
result=executor_load(cfg,ev,'noisy+compact',1)
code=int(result['status']=='FAIL')
result.update(test_id='PROBE-A02-LOAD',experiment_id=manifest['experiment_id'],
              executed_at=datetime.now(timezone.utc).isoformat(),
              manifest_sha256=sha((ev.root/'manifest.json').read_bytes()),
              commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}],
              limitations=['One load probe only; no full A02 matrix or human noise-invariance claim.'])
write_json(ev.root/'result.json',result)
print(json.dumps({'run':ev.root.name,'status':result['status']}),flush=True)
raise SystemExit(code)
