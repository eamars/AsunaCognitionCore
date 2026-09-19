"""Retrospective provider/native finish comparison; never rewrites attempts."""
import json,uuid
from asuna.config import ROOT
from asuna.evidence import write_json,sha
from asuna.dsh_lane import provider_finish

findings=[];checked=0
for directory in sorted({p.parent for p in (ROOT/'reports').rglob('*lane.receipt.json') if 'private' not in p.parts}):
    last={};intent={}
    for path in sorted(directory.glob('*.json')):
        try:item=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError):continue
        if not isinstance(item,dict):continue
        payload=item.get('payload',{});kind=item.get('type')
        if kind=='lane.intent':intent[payload['lane']]=payload;last[payload['lane']]=None
        elif kind=='provider.response' and 'body_utf8' in payload:
            request=directory/payload['request_ref']
            if not request.exists():continue
            req=json.loads(request.read_text(encoding='utf-8'))['payload']
            if req.get('lane') and req.get('purpose')!='compaction':last[req['lane']]=provider_finish(payload['body_utf8'])
        elif kind=='lane.receipt' and payload.get('status_code')==200:
            checked+=1;lane=payload['lane'];body=payload['body']
            if body.get('finish_reason')=='completed' and last.get(lane) not in ('stop',None):
                findings.append({'artifact_path':path.relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes()),'operation':payload['operation'],'phase':intent.get(lane,{}).get('phase'),'provider_finish':last[lane],'native_finish':'completed','content_nonempty':bool(body.get('content','').strip())})
out=ROOT/'reports'/('finish-reason-audit-'+uuid.uuid4().hex[:10]);out.mkdir()
result={'status':'FAIL' if any(f['content_nonempty'] for f in findings) else 'INCONCLUSIVE','checked_native_turns':checked,'mismatches':findings,'commands':[{'argv':['python','tools/audit_finish_reasons.py'],'exit_code':0}],'interpretation':'Previous adapter mapped native completed to stop. Empty content was already rejected. Nonempty provider-length completions require per-attempt adjudication and may not be counted valid. This analysis preserves original outputs.'}
write_json(out/'result.json',result);print(json.dumps({'out':str(out),'checked':checked,'mismatches':len(findings),'nonempty':sum(f['content_nonempty'] for f in findings)}))
