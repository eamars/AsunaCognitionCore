"""One actual timeout case verifies failed-state evidence before full L11."""
import json,sys,uuid
from datetime import datetime,timezone
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze
from asuna.fault_trials import suite

ev=Evidence(ROOT/'reports'/('fault-capture-probe-'+uuid.uuid4().hex[:12]));cfg=load()
manifest=freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-L11')
value=suite(cfg,ev,repetitions=1,kinds=('endpoint_timeout',))
mechanical=value['status']!='FAIL' and (ev.root/'endpoint_timeout-1/terminal-state.json').exists() and (ev.root/'blind_review.json').exists()
value.update(test_id='PROBE-L11',status='PASS' if mechanical else 'FAIL',experiment_id=manifest['experiment_id'],executed_at=datetime.now(timezone.utc).isoformat(),manifest_sha256=sha((ev.root/'manifest.json').read_bytes()))
value['limitations'].append('Narrow terminal-evidence and recovery probe only; public statement quality still needs independent review.')
code=int(not mechanical);value['commands']=[{'argv':[sys.executable,*sys.argv],'exit_code':code}]
write_json(ev.root/'result.json',value);print(json.dumps({'run':ev.root.name,'status':value['status']}));raise SystemExit(code)
