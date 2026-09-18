"""Operator-authorized read-only Docker discovery; credentials stay in ignored storage."""
import hashlib
import json
import re
from pathlib import Path
import paramiko

settings=json.loads(Path('.runtime/operator-ssh.json').read_text(encoding='utf-8'))
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(**settings, timeout=10, banner_timeout=10, auth_timeout=10, allow_agent=False, look_for_keys=False)
key=client.get_transport().get_remote_server_key()
print(json.dumps({'ssh_host_key_sha256':hashlib.sha256(key.asbytes()).hexdigest()}))
cmd="sudo -S -p '' docker ps --format '{{.Names}}\t{{.Image}}'"
stdin,stdout,stderr=client.exec_command(cmd,timeout=15)
stdin.write(settings['password']+'\n')
stdin.flush()
print(stdout.read().decode())
print(stderr.read().decode().replace(settings['password'],'[REDACTED]'))
print('exit_code='+str(stdout.channel.recv_exit_status()))
for label,cmd in [
 ('disk', 'df -h /home/eamars/mongo_vector'),
 ('search_logs', "sudo -S -p '' docker logs --since 30m --tail 1000 mongot-community-pupr"),
 ('search_mounts', "sudo -S -p '' docker inspect --format '{{json .Mounts}}' mongot-community-pupr"),
 ('search_state', "sudo -S -p '' docker inspect --format '{{json .State}}' mongot-community-pupr")]:
 stdin,stdout,stderr=client.exec_command(cmd,timeout=20)
 stdin.write(settings['password']+'\n'); stdin.flush()
 raw=stdout.read().decode()+stderr.read().decode()
 raw=re.sub(r'mongodb(?:\+srv)?://[^\s\"\']+', '[MONGO_URI_REDACTED]', raw)
 raw=re.sub(r'(?i)(password|token|secret|api_key)([\"\s:=]+)[^\s,}]+', r'\1\2[REDACTED]',raw)
 raw=raw.replace(settings['password'],'[REDACTED]')
 lines=[x for x in raw.splitlines() if label!='search_logs' or any(w in x.lower() for w in ('exception','error','failed','caused by','no space'))]
 item={'label':label,'exit_code':stdout.channel.recv_exit_status(),'lines':list(dict.fromkeys(lines))[-20:]}
 output=Path('reports/search-diagnostics');output.mkdir(exist_ok=True)
 from datetime import datetime,timezone
 (output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-')+label+'.json')).write_text(json.dumps(item,indent=2),encoding='utf-8')
 print(json.dumps(item))
client.close()
