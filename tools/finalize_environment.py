"""Aggregate read-only deployment witnesses without changing running services."""
from datetime import datetime,timezone
import hashlib,json,platform,subprocess,uuid
from pathlib import Path
from asuna.config import ROOT,load,redacted
from asuna.evidence import Evidence,LocalHttp,write_json,sha
from asuna.reporting import ref

cfg=load();ev=Evidence(ROOT/'reports'/('environment-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]))
source=ROOT/'reports/deployment-20260918T143934Z-d69e73/fingerprint.json'
previous=json.loads(source.read_text(encoding='utf-8'))
gemma=json.loads((ROOT/'reports/gemma-weight-hash.json').read_text())
mtp=Path('C:/workspace/qwen38_27b/models/unsloth-gemma4-26b-qat/MTP/mtp-gemma-4-26B-A4B-it-Q8_0.gguf')
digest=hashlib.sha256()
with mtp.open('rb') as stream:
    while block:=stream.read(8*1024*1024):digest.update(block)
http=LocalHttp(ev);metadata={}
for lane in ('character','executor','embedding'):
    metadata[lane]=http.request('GET',cfg[lane]['base_url']+'/models','deployment.metadata',api_key=cfg[lane].get('api_key',''))
try:embedding_detail=http.request('GET',cfg['embedding']['base_url'].removesuffix('/v1')+'/api/v0/models','deployment.embedding_metadata',api_key=cfg['embedding'].get('api_key',''))
except Exception as exc:embedding_detail={'available':False,'error_type':type(exc).__name__}
try:gemma_props=http.request('GET',cfg['character']['base_url'].removesuffix('/v1')+'/props','deployment.template')
except Exception as exc:gemma_props={'available':False,'error_type':type(exc).__name__}
http.client.close()
lock=json.loads((ROOT/'package-lock.json').read_text())
plugins={name.removeprefix('node_modules/'):value.get('version') for name,value in lock['packages'].items() if name.startswith('node_modules/@deepseek-ai/')}
qwen=previous['qwen_local_manifest']
template=next((v for v in qwen['files'] if v['name']=='chat_template.jinja'),None)
value={'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'python':platform.python_version(),
 'configuration':redacted(cfg),'dsh':{'version':'0.1.5-rc.2','commit':'fb2c4b9e698e30edb738bca4cf0618587db7d203','executable':str(ROOT/'node_modules/.bin/dsh.cmd'),'executable_sha256':sha((ROOT/'node_modules/@deepseek-ai/dsh/lib/bin.js').read_bytes()),'plugins':plugins,'package_lock':ref(ROOT/'package-lock.json'),'uv_lock':ref(ROOT/'uv.lock')},
 'models':{
 'character':{'deployment_variant':'Gemma 4 26B A4B IT QAT UD-Q4_K_XL','weight_path':gemma['Path'],'weight_sha256':gemma['Hash'].lower(),'MTP':{'enabled_observed':True,'draft_path':str(mtp),'draft_sha256':digest.hexdigest(),'draft_n_max':3,'source':ref(ROOT/'reports/gemma-runtime-process.json')},'template_sha256':sha(str(gemma_props.get('chat_template')).encode()) if gemma_props.get('chat_template') else None,'sampling':cfg['character']['sampling'],'KV':'q8_0 K and V','metadata':metadata['character'],'max_context_declared':262144,'capacity_evidence':'F01 per-length results, never inferred from client metadata'},
 'executor':{'deployment_variant':'Qwen3.8 Flash Next Uncensored NVFP4','files':qwen['files'],'chat_template_file':template,'tokenizer_config_chat_template_field':None,'previous_none_hash_is_not_template_fingerprint':qwen['chat_template_sha256'],'server_commit':previous['qwen_server_commit'],'server_source_hashes':previous['qwen_server_source_hashes'],'processes':qwen['processes'],'MTP_runtime_enabled':None,'MTP_note':'MTP weights present; runtime activation not established by the current witness.','sampling':cfg['executor']['sampling'],'metadata':metadata['executor'],'max_context_declared':262144},
 'embedding':{'route':redacted(cfg)['embedding'],'metadata':metadata['embedding'],'details':embedding_detail,'weight_sha256':None,'weight_revision_verified':False}},
 'sources':[ref(source),ref(ROOT/'reports/gemma-runtime-process.json'),ref(ROOT/'reports/gemma-weight-hash.json')],
 'unknowns':['Qwen MTP runtime activation is not established.','Embedding weight digest/revision not established.','No approved absolute performance SLO.','Qwen final OpenAI rendered token IDs unavailable.'],
 'isolation':{'old_profiles_modified':False,'model_launch_parameters_modified':False,'old_database_writes':False,'operator_authorized_Mongo_nofile_repair':ref(ROOT/'reports/search-diagnostics/20260918T142903-mongo-nofile-repair.json')},
 'sampling_changes_require_new_experiment_id':True}
write_json(ev.root/'environment.json',value)
write_json(ROOT/'environment.json',value)
write_json(ROOT/'config/resolved.redacted.json',redacted(cfg))
print(json.dumps({'environment':ref(ROOT/'environment.json'),'evidence':str(ev.root)}))
