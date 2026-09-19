"""Invoke dedicated frozen drivers, preserving actual command exit and errors."""
import argparse,copy,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze

parser=argparse.ArgumentParser();parser.add_argument('test');parser.add_argument('--out',type=Path);parser.add_argument('--probe-count',type=int)
args=parser.parse_args();config=load()
ev=Evidence(args.out or ROOT/'reports'/('formal-'+args.test+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]))
manifest=freeze(config,BUNDLE/'fixtures/acceptance_cases.json',ev,args.test)
result=None
try:
    if args.test=='L04':
        from asuna.retrieval_trials import suite
        result=suite(config,ev)
    elif args.test in ('L02','L03','L12'):
        from asuna.live_trials import suite
        result=suite(config,args.test,ev,repetitions=args.probe_count,controls=not bool(args.probe_count))
    elif args.test=='F01':
        from asuna.capacity import suite
        result=suite(config,ev,**({'lengths':(8192,),'repetitions':1} if args.probe_count else {}))
    else:raise ValueError('UNKNOWN_DEDICATED_DRIVER')
except Exception as exc:
    ev.record('driver.error',{'type':type(exc).__name__,'message':str(exc)})
    result={'test_id':args.test,'status':'FAIL','attempts':1,'error_type':type(exc).__name__}
if args.probe_count:
    result['test_id']='PROBE-'+args.test;result.setdefault('limitations',[]).append('Reduced executable design probe, not full acceptance.')
    if result.get('samples') and all(s['status']=='PASS' for s in result['samples']):result['status']='PASS'
code=1 if result['status']=='FAIL' else 0
result.update(experiment_id=manifest['experiment_id'],manifest_sha256=sha((ev.root/'manifest.json').read_bytes()),executed_at=datetime.now(timezone.utc).isoformat(),commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}])
write_json(ev.root/'result.json',result)
print(json.dumps({'run':ev.root.name,'status':result['status'],'metrics':result.get('metrics')}),flush=True)
raise SystemExit(code)
