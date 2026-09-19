"""Version the implementation fingerprint without modifying any deployment."""
import json,subprocess,uuid
from datetime import datetime,timezone
from asuna.config import ROOT,load,redacted
from asuna.evidence import Evidence,write_json
from asuna.reporting import ref

ev=Evidence(ROOT/'reports'/('environment-v3-'+uuid.uuid4().hex[:10]))
path=ROOT/'environment.json';old=json.loads(path.read_text(encoding='utf-8'))
write_json(ev.root/'previous-environment.json',old)
current={**old,'created_at':datetime.now(timezone.utc).isoformat(),'previous_version':ref(ev.root/'previous-environment.json')}
current['configuration']=redacted(load())
current['adapter_runtime']={'bridge':ref(ROOT/'dsh-plugin/runtime-v2.ts'),
    'legacy_bridge_retained_for_frozen_experiments':ref(ROOT/'dsh-plugin/runtime.ts'),
    'provider_idle_timeout_seconds':1800,'provider_http_timeout_seconds':1800,
    'model_response_policy':'Upstream-accepted SSE comment followed by complete durable response before model content reaches DSH.',
    'summary_policy':'queued request persists across restart; only complete episode/task boundaries; silent DECIDE boundary validated against committed episode and native receipt',
    'implementation_commit_before_snapshot':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
current['storage_runtime']={'query_cache':'IDs and scores only; scope/epoch/source revision in key; authoritative read on every hit','large_provider_payloads':'verified scoped GridFS artifacts','task_fencing':'intent revision and worker token plus local cross-process side-effect lock','scope':'single Windows controller host; no multi-host HA claim'}
current['capacity_evidence']={'full_matrix_first_attempt':ref(ROOT/'reports/formal-F01-20260919T092450Z-ced9f8/result.json'),'transport_fix_234k_probe':ref(ROOT/'reports/capacity-stream-reprobe-4db631d2b7/result.json'),'conclusion':'First full matrix 23/24. New 234k Qwen probe passes after transport deadline fix; full new matrix required, no claim of all-length acceptance yet.'}
write_json(ev.root/'environment.json',current)
path.write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'snapshot':ev.root.name,'environment':ref(path)}))
