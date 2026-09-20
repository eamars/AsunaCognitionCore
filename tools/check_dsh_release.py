"""Read the public release tag without changing the project or global runtime."""
import json,subprocess,uuid
from asuna.config import ROOT
from asuna.evidence import Evidence,write_json
ev=Evidence(ROOT/'reports'/('dsh-release-check-'+uuid.uuid4().hex[:10]))
command=['npm.cmd','view','@deepseek-ai/dsh','dist-tags','--registry=https://registry.npmjs.org','--json']
p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60)
tags=json.loads(p.stdout) if p.returncode==0 else {}
installed=json.loads((ROOT/'node_modules/@deepseek-ai/dsh/package.json').read_text())['version']
value={'test_id':'PROBE-DSH-latest','status':'PASS' if p.returncode==0 and tags.get('latest')==installed else 'FAIL','installed':installed,'public_registry_tags':tags,'commands':[{'argv':command,'exit_code':p.returncode}],'changed_packages':False}
write_json(ev.root/'result.json',value);print(json.dumps({'run':ev.root.name,**value}));raise SystemExit(0 if value['status']=='PASS' else 1)
