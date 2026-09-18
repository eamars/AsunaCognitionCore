from datetime import datetime, timezone
from pathlib import Path
import json
import uuid
from asuna.config import ROOT
from asuna.sandbox import Sandbox
from asuna.evidence import write_json

run='M0-sandbox-'+uuid.uuid4().hex[:8]
workspace=ROOT/'.runtime/work'/run
workspace.mkdir(parents=True)
(ROOT/'.runtime/synthetic-host-canary.txt').write_text('HOST_SECRET_CANARY_SYNTHETIC',encoding='utf-8')
code='''import os,socket,pathlib,json
pathlib.Path('inside.txt').write_text('ok')
result={'host_absent':not pathlib.Path('/mnt/c/workspace').exists(), 'home_absent':not pathlib.Path('/home/rba90').exists(), 'dsh_absent':not pathlib.Path('/task/../../asuna-dsh').exists(),'env_keys':sorted(os.environ),'interfaces':socket.if_nameindex(),'task_write':pathlib.Path('inside.txt').read_text()=='ok'}
assert result['host_absent'] and result['home_absent'] and result['dsh_absent'] and result['task_write']
assert [x[1] for x in result['interfaces']]==['lo']
assert not any(k in os.environ for k in ('MONGODB_URI','ASUNA_MONGODB_URI','ASUNA_LOCAL_DUMMY_KEY'))
print(json.dumps(result))
'''
result=Sandbox(workspace).run(['/usr/bin/python3','-c',code])
write_json(ROOT/'reports'/run/'result.json',{'probe':'task-isolation','command':'.venv/Scripts/python.exe tools/probe_sandbox.py','status':'PASS' if result['exit_code']==0 else 'FAIL',**result})
print(json.dumps({'run':run,'exit_code':result['exit_code']}))
raise SystemExit(result['exit_code'])
