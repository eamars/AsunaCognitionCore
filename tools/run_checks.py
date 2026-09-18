"""Preserve every validation attempt including nonzero subprocess exits."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from asuna.config import ROOT
from asuna.evidence import write_json,sha

run=datetime.now(timezone.utc).strftime('check-%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
out=ROOT/'reports'/run;out.mkdir()
command=[sys.executable,'-m','pytest',*sys.argv[1:],'--junitxml='+str(out/'junit.xml')]
env={**os.environ,'PYTHONIOENCODING':'utf-8'}
result=subprocess.run(command,cwd=ROOT,capture_output=True,env=env)
(out/'stdout.txt').write_bytes(result.stdout);(out/'stderr.txt').write_bytes(result.stderr)
write_json(out/'result.json',{'command':command,'exit_code':result.returncode,'stdout_sha256':sha(result.stdout),'stderr_sha256':sha(result.stderr)})
print(result.stdout.decode('utf-8',errors='replace'))
print(json.dumps({'run':run,'exit_code':result.returncode}))
raise SystemExit(result.returncode)
