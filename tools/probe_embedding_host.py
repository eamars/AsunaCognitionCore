"""Authorized read-only SSH discovery of the embedding deployment; no credentials logged."""
from datetime import datetime,timezone
import hashlib,json,uuid
from pathlib import Path
import paramiko
from asuna.config import ROOT
from asuna.evidence import Evidence,write_json

ev=Evidence(ROOT/'reports'/('embedding-host-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]))
settings=json.loads((ROOT/'.runtime/operator-ssh.json').read_text(encoding='utf-8'))
settings.update(hostname='192.168.2.8',username='eamars')
target=ROOT/'.runtime/embedding-ssh.json'
if not target.exists():target.write_text(json.dumps(settings),encoding='utf-8')
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(**settings,timeout=10,banner_timeout=10,auth_timeout=10,allow_agent=False,look_for_keys=False)
    fingerprint=hashlib.sha256(client.get_transport().get_remote_server_key().asbytes()).hexdigest()
    ev.record('ssh.host_key',{'host':'192.168.2.8','sha256':fingerprint,'authorization':'explicit user read-only embedding manifest access'})
    commands=['uname -a',"ss -ltnp '( sport = :1234 )'",'ls -d /home/eamars/.lmstudio /home/eamars/.cache/lm-studio /home/eamars/.cache/huggingface /home/eamars/.ollama /home/eamars/models']
    for command in commands:
        _,stdout,stderr=client.exec_command(command,timeout=20)
        raw=(stdout.read()+stderr.read()).decode('utf-8','replace').replace(settings['password'],'[REDACTED]')
        ev.record('ssh.read',{'command':command,'exit_code':stdout.channel.recv_exit_status(),'output':raw})
    result={'status':'PASS','host_key_sha256':fingerprint,'evidence':str(ev.root)}
except Exception as exc:result={'status':'FAIL','error_type':type(exc).__name__}
finally:client.close()
write_json(ev.root/'result.json',result);print(json.dumps(result))
