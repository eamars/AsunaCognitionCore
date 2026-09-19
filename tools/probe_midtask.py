from datetime import datetime,timezone
import json,uuid
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import freeze
from asuna.live_trials import run_primary

cfg=load();cfg['executor']['compact_at_steps']=[3]
ev=Evidence(ROOT/'reports'/('midtask-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]))
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-midtask')
result,_,_,_,_=run_primary(cfg,'L03',1,ev)
events=[]
path=ev.root/'task-01/trace.json'
if path.exists():events=json.loads(path.read_text(encoding='utf-8'))
result['native_compactions']=sum(e['type']=='compaction.native' for e in events)
if result['native_compactions']==0:result['status']='FAIL'
result.update(command='.venv/Scripts/python.exe tools/probe_midtask.py',exit_code=0 if result['status']=='PASS' else 1)
write_json(ev.root/'result.json',result);print(json.dumps({'run':ev.root.name,'status':result['status'],'compactions':result['native_compactions']}));raise SystemExit(result['exit_code'])
