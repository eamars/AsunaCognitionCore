import hashlib,json,shlex,uuid
from datetime import datetime,timezone
import paramiko
from asuna.config import ROOT,load
from asuna.evidence import Evidence,LocalHttp,write_json,sha

ev=Evidence(ROOT/'reports'/('embedding-fingerprint-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]));cfg=load();http=LocalHttp(ev)
base=cfg['embedding']['base_url'].removesuffix('/v1')
tags=http.request('GET',base+'/api/tags','deployment.embedding_tags',api_key=cfg['embedding'].get('api_key',''))
show=http.request('POST',base+'/api/show','deployment.embedding_manifest',{'model':cfg['embedding']['model']},cfg['embedding'].get('api_key',''))
http.client.close()
settings=json.loads((ROOT/'.runtime/embedding-ssh.json').read_text(encoding='utf-8'))
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy());client.connect(**settings,timeout=10,allow_agent=False,look_for_keys=False)
assert hashlib.sha256(client.get_transport().get_remote_server_key().asbytes()).hexdigest()=='b26c0e4a40aff7295132e7c8bc12d1d1c5a2712087ddb705533d0cee14a35cde'
script=r'''
import pathlib,json,hashlib,os
pid=2863
env={}
for value in pathlib.Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
 key,sep,content=value.partition(b'=')
 if key in (b'OLLAMA_MODELS',b'HOME'):env[key.decode()]=content.decode()
root=pathlib.Path(env.get('OLLAMA_MODELS',env.get('HOME','/usr/share/ollama')+'/.ollama/models')).resolve()
files=[]
for path in (root/'manifests').rglob('*'):
 if path.is_file() and ('nomic' in str(path).lower() or 'embedding' in str(path).lower()):
  raw=path.read_bytes();manifest=json.loads(raw);layers=[]
  for item in [manifest['config'],*manifest['layers']]:
   digest=item['digest'];blob=root/'blobs'/digest.replace(':','-');h=hashlib.sha256()
   with blob.open('rb') as f:
    while chunk:=f.read(8388608):h.update(chunk)
   layers.append({'digest':digest,'size':blob.stat().st_size,'actual_sha256':h.hexdigest(),'matches_manifest':h.hexdigest()==digest.split(':')[1],'media_type':item['mediaType']})
  files.append({'path':str(path),'manifest_sha256':hashlib.sha256(raw).hexdigest(),'manifest':manifest,'verified_layers':layers})
exe=pathlib.Path(f'/proc/{pid}/exe').resolve();h=hashlib.sha256()
with exe.open('rb') as f:
 while chunk:=f.read(8388608):h.update(chunk)
print(json.dumps({'pid':pid,'model_root':str(root),'executable':str(exe),'executable_sha256':h.hexdigest(),'models':files}))
'''
command="sudo -S -p '' python3 -c "+shlex.quote(script)
stdin,stdout,stderr=client.exec_command(command,timeout=120);stdin.write(settings['password']+'\n');stdin.flush()
raw=stdout.read();error=stderr.read().decode().replace(settings['password'],'[REDACTED]');code=stdout.channel.recv_exit_status();client.close()
ev.record('ssh.manifest_hash',{'command':'sudo python3 <read-only script in tools/fingerprint_embedding.py>','exit_code':code,'stderr':error})
result={'status':'PASS' if code==0 else 'FAIL','tags':tags,'details':show,'server_manifest':json.loads(raw) if code==0 else None,'command_exit_code':code}
write_json(ev.root/'fingerprint.json',result)
print(json.dumps({'status':result['status'],'path':str(ev.root/'fingerprint.json')}))
