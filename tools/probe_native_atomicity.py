"""Freeze the installed native SDK fault probe before starting Node."""
import json,subprocess,sys,uuid
from datetime import datetime,timezone
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze

ev=Evidence(ROOT/'reports'/('native-atomicity-'+uuid.uuid4().hex[:12]))
manifest=freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E24')
command=['node',str(ROOT/'tools/probe_native_atomicity.mjs'),str(ev.root/'native')]
p=subprocess.run(command,cwd=ROOT,capture_output=True)
(ev.root/'stdout.txt').write_bytes(p.stdout);(ev.root/'stderr.txt').write_bytes(p.stderr)
value=json.loads((ev.root/'native/result.json').read_text(encoding='utf-8')) if (ev.root/'native/result.json').exists() else {'test_id':'PROBE-E24','status':'FAIL'}
value.update(experiment_id=manifest['experiment_id'],executed_at=datetime.now(timezone.utc).isoformat(),
             manifest_sha256=sha((ev.root/'manifest.json').read_bytes()),commands=[{'argv':command,'exit_code':p.returncode}])
if p.returncode:value['status']='FAIL'
write_json(ev.root/'result.json',value)
print(json.dumps({'run':ev.root.name,'status':value['status']}))
raise SystemExit(p.returncode or int(value['status']=='FAIL'))
