import json,subprocess,sys,uuid
from asuna.config import ROOT
from asuna.evidence import Evidence,write_json,sha
ev=Evidence(ROOT/'reports'/('cli-probe-'+uuid.uuid4().hex[:10]))
checks=[]
for args in (['--help'],['run','--help'],['rollback','--help']):
    command=[sys.executable,'-m','asuna.cli',*args]
    result=subprocess.run(command,cwd=ROOT,capture_output=True)
    stem=str(len(checks));(ev.root/(stem+'-stdout.txt')).write_bytes(result.stdout);(ev.root/(stem+'-stderr.txt')).write_bytes(result.stderr)
    checks.append({'argv':command,'exit_code':result.returncode,'stdout_sha256':sha(result.stdout),'stderr_sha256':sha(result.stderr)})
status='PASS' if all(x['exit_code']==0 for x in checks) else 'FAIL'
write_json(ev.root/'result.json',{'test_id':'PROBE-CLI','status':status,'commands':checks})
print(json.dumps({'run':ev.root.name,'status':status}));raise SystemExit(0 if status=='PASS' else 1)
