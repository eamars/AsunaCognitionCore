"""Read-only health snapshot with pinned host key; no environment or DB contents."""
import base64,hashlib,json,uuid
from pathlib import Path
import paramiko
from asuna.config import ROOT
from asuna.evidence import write_json

settings=json.loads((ROOT/'.runtime/operator-ssh.json').read_text(encoding='utf-8'))
class PinnedKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self,client,hostname,key):
        if hashlib.sha256(key.asbytes()).hexdigest()!='e6afdad6bf6e7f1f974a08aaab929a252a07d24adb3b4de9f75719a832dfe061':raise RuntimeError('SSH_HOST_KEY_CHANGED')
client=paramiko.SSHClient();client.set_missing_host_key_policy(PinnedKey())
client.connect(**settings,timeout=10,banner_timeout=10,auth_timeout=10,allow_agent=False,look_for_keys=False)
script="""import pathlib,resource,json,subprocess,os
rows=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  if (p/'comm').read_text().strip()=='mongod':rows.append({'pid':int(p.name),'nofile':list(resource.prlimit(int(p.name),resource.RLIMIT_NOFILE)),'open_fds':len(list((p/'fd').iterdir()))})
 except (FileNotFoundError,ProcessLookupError):pass
containers=subprocess.run(['docker','ps','--filter','name=mongo','--format','{{json .Names}} {{json .Status}}'],capture_output=True,text=True)
compose=pathlib.Path('/var/lib/docker/volumes/portainer_data/_data/compose/17/docker-compose.yml')
import hashlib
print(json.dumps({'mongo_processes':rows,'containers':containers.stdout.splitlines(),'compose_sha256':hashlib.sha256(compose.read_bytes()).hexdigest(),'disk_free_bytes':__import__('shutil').disk_usage('/').free,'read_only':True}))
"""
encoded=base64.b64encode(script.encode()).decode()
cmd="sudo -S -p '' python3 -c 'import base64;exec(base64.b64decode(\""+encoded+"\"))'"
stdin,stdout,stderr=client.exec_command(cmd,timeout=25);stdin.write(settings['password']+'\n');stdin.flush()
raw=stdout.read().decode();error=stderr.read().decode();code=stdout.channel.recv_exit_status();client.close()
result={'exit_code':code,'health':json.loads(raw) if raw else None,'stderr_present':bool(error)}
out=ROOT/'reports/search-diagnostics'/('health-'+uuid.uuid4().hex[:10]+'.json');write_json(out,result)
print(json.dumps(result));raise SystemExit(code)
