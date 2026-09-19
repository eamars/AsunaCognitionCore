"""Version the aggregate after newly authorized embedding fingerprint evidence."""
from datetime import datetime,timezone
import copy,json,uuid
from asuna.config import ROOT,redacted
from asuna.evidence import Evidence,write_json,sha
from asuna.reporting import ref

path=ROOT/'environment.json';old=json.loads(path.read_text(encoding='utf-8'))
evidence=Evidence(ROOT/'reports'/('environment-v2-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]))
write_json(evidence.root/'previous-environment.json',old)
source=ROOT/'reports/embedding-fingerprint-20260919T091301Z-32b938/fingerprint.json'
data=json.loads(source.read_text(encoding='utf-8'))
model=next(m for m in data['server_manifest']['models'] if '/text-embedding-nomic-embed-text-v2-moe/' in m['path'])
assert all(layer['matches_manifest'] for layer in model['verified_layers'])
weight=next(layer['actual_sha256'] for layer in model['verified_layers'] if layer['media_type']=='application/vnd.ollama.image.model')
configpath=ROOT/'config/local.json';config=json.loads(configpath.read_text(encoding='utf-8'))
config['embedding'].update(weight_sha256=weight,manifest_sha256=model['manifest_sha256'])
config['workflow_timeout_seconds']=1800
configpath.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
old['created_at']=datetime.now(timezone.utc).isoformat();old['previous_version']=ref(evidence.root/'previous-environment.json')
old['configuration']=redacted(config)
old['models']['embedding'].update(weight_sha256=weight,manifest_sha256=model['manifest_sha256'],weight_revision_verified=True,quantization='F16',parameters='475.29M',fingerprint_source=ref(source),details=data['details'])
sourcepath=ROOT.parent/'qwen38_27b/runtime/freetoken-eamars/python/freetoken/models/qwen4_exp/weight.py'
text=sourcepath.read_text(encoding='utf-8');assert 'if raw_name.startswith("mtp."):' in text
old['models']['executor'].update(MTP_runtime_enabled=False,MTP_note='Source-supported inference: deployed qwen4_exp loader drops mtp.* weights; no speculative launch flag was observed. No dynamic MTP counter is exposed.',MTP_loader={'path':str(sourcepath),'sha256':sha(sourcepath.read_bytes()),'lines':'9,86-87'})
old['unknowns']=[x for x in old['unknowns'] if not x.startswith(('Qwen MTP','Embedding weight'))]
old['unknowns'].append('Qwen MTP disabled is inferred from deployed loader and launch flags; no dynamic speculative counter exposed.')
write_json(evidence.root/'environment.json',old)
path.write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(ROOT/'config/resolved.redacted.json').write_text(json.dumps(redacted(config),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'environment':ref(path),'embedding_weight_sha256':weight,'manifest_sha256':model['manifest_sha256']}))
