"""Append a validation correction; never rewrite an earlier attempt."""
import json,uuid,zipfile
from asuna.config import ROOT
from asuna.evidence import Evidence,write_json
from asuna.reporting import ref
ev=Evidence(ROOT/'reports'/('retrieval-evidence-correction-'+uuid.uuid4().hex[:10]));affected=[]
for result in (ROOT/'reports').glob('formal-L04-*/result.json'):
    archive=result.parent/'frozen-inputs.zip'
    if not archive.exists():continue
    with zipfile.ZipFile(archive) as z:
        code=z.read('src/asuna/retrieval_trials.py').decode('utf-8')
    if "patch.object(store.db.memory_units,'aggregate'" in code:affected.append(ref(result))
write_json(ev.root/'correction.json',{'affected_results':affected,'claim_invalidated':'The old stale-ID assertion did not prove an injected stale vector response was rechecked. Ordinary real vector query results remain evidence for recall, not this fault clause.','cause':'PyMongo database attribute access creates a fresh Collection instance; patch.object on one temporary Collection did not intercept the subsequent search call.','detection':ref(ROOT/'reports/cache-probe-1a1de5adedc6/result.json'),'fix':'Patch the real Collection.aggregate method in the narrow fault context, assert exactly one interception, and assert M09 appears in authoritative_recheck exclusions.','verified_by':ref(ROOT/'reports/cache-probe-d8bfda54b8d0/result.json'),'original_attempts_unchanged':True})
print(json.dumps({'correction':ev.root.name,'affected_results':len(affected)}))
