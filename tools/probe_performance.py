"""Narrow real F02 measurement probe; all default formal counts remain unchanged."""
import json,sys,uuid
from datetime import datetime,timezone
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze
from asuna.performance_trials import suite

ev=Evidence(ROOT/'reports'/('performance-probe-'+uuid.uuid4().hex[:12]));cfg=load()
manifest=freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-F02')
try:
    value=suite(cfg,ev,repetitions=2,switch_cycles=1)
    measured_status=value['status']
    okay=len(value['samples'])==26 and all(r['status']=='PASS' for r in value['samples']) and value['metrics']['native_compactions']==2
    value.update(test_id='PROBE-F02',status='PASS' if okay else 'FAIL',measured_threshold_status=measured_status)
    value['limitations'].append('Narrow measurement-plumbing probe, not full F02; formal run requires 166 private turns and two native summaries. Cache threshold observations are retained separately even if measurement plumbing works.')
except Exception as exc:
    ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)});value={'test_id':'PROBE-F02','status':'FAIL','error':str(exc)}
code=int(value['status']=='FAIL');value.update(experiment_id=manifest['experiment_id'],executed_at=datetime.now(timezone.utc).isoformat(),manifest_sha256=sha((ev.root/'manifest.json').read_bytes()),commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}])
write_json(ev.root/'result.json',value);print(json.dumps({'run':ev.root.name,'status':value['status'],'metrics':value.get('metrics',{}).get('fixed_prefix')}));raise SystemExit(code)
