"""Read-only deployment fingerprint. Does not import or execute an old app."""
from datetime import datetime,timezone
import json,subprocess,uuid
from asuna.config import ROOT,load,redacted
from asuna.evidence import Evidence,LocalHttp,write_json,sha

run='deployment-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev=Evidence(ROOT/'reports'/run);cfg=load();http=LocalHttp(ev)
result={'config':redacted(cfg),'model_endpoints':{},'limitations':[]}
for lane in ('character','executor','embedding'):
    try:result['model_endpoints'][lane]=http.request('GET',cfg[lane]['base_url']+'/models','deployment.metadata',api_key=cfg[lane].get('api_key',''))
    except Exception as exc:result['model_endpoints'][lane]={'error_type':type(exc).__name__}
script=r'''
import pathlib,json,hashlib
root=pathlib.Path('/home/rba90/models/Qwen3.8-Flash-Next-Uncensored-NVFP4')
files=[]
for p in sorted(root.iterdir()):
 if p.is_file() and (p.suffix in ('.json','.jinja','.safetensors') or p.name.endswith('.jinja2')):
  digest=hashlib.sha256()
  with p.open('rb') as f:
   while chunk:=f.read(8*1024*1024):digest.update(chunk)
  files.append({'name':p.name,'size':p.stat().st_size,'sha256':digest.hexdigest()})
config=json.loads((root/'config.json').read_text());tokenizer=json.loads((root/'tokenizer_config.json').read_text())
allow=['--model','--served-model-name','--max-seq-len-override','--max-output-tokens','--cache-type','--dtype','--speculative-algorithm','--mtp','--kv-cache-dtype','--max-running-requests','--reasoning-parser','--tool-call-parser']
process=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:argv=(p/'cmdline').read_bytes().decode().split('\0')
 except (OSError,UnicodeError):continue
 if '--served-model-name' in argv and 'qwen38-next-uncensored-freetoken-vision' in argv:
  selected={arg:argv[i+1] for i,arg in enumerate(argv[:-1]) if arg in allow};process.append({'pid':int(p.name),'argv_whitelist':selected})
print(json.dumps({'root':str(root),'files':files,'config':{k:config.get(k) for k in ('model_type','architectures','quantization_config','num_nextn_predict_layers','text_config')},'chat_template_sha256':hashlib.sha256(str(tokenizer.get('chat_template')).encode()).hexdigest(),'processes':process,'runtime_mtp_enabled':'not inferred from weights'}))
'''
command=['wsl','--exec','python3','-c',script]
proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=600)
ev.record('command',{'command':['wsl','--exec','python3','-c','<read-only manifest script in tools/fingerprint_models.py>'],'exit_code':proc.returncode,'stderr':proc.stderr})
if proc.returncode==0:result['qwen_local_manifest']=json.loads(proc.stdout)
else:result['limitations'].append('Qwen weight fingerprint failed')
source=ROOT.parent/'qwen38_27b/runtime/freetoken-eamars'
result['qwen_server_commit']=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
result['qwen_server_source_hashes']={str(p.relative_to(source)):sha(p.read_bytes()) for p in (source/'python/freetoken/server/anthropic_api.py',source/'python/freetoken/server/api_server.py')}
write_json(ev.root/'fingerprint.json',result)
print(json.dumps({'run':run,'exit_code':proc.returncode,'manifest':str(ev.root/'fingerprint.json')}));raise SystemExit(proc.returncode)
