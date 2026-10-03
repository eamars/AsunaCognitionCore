"""Read-only helpers for preserved pre-ADR-008 diagnostic artifacts."""
import json
from .config import ROOT
from .evidence import sha

def provider_finish(raw):
    """Native turn completion is not proof that the provider stopped normally."""
    result=None
    for line in raw.splitlines():
        if line.startswith('data: ') and line[6:].strip()!='[DONE]':
            value=json.loads(line[6:])
            for choice in value.get('choices',[]):
                if choice.get('finish_reason') is not None:result=choice['finish_reason']
    return result


def compaction_audit_records(body,calls,evidence):
    """Join every native replacement to its exact same-lane summary output."""
    records=[];used=set()
    for result in body.get('compactions',[]) or ([body['compaction']] if body.get('compaction') else []):
        expected=''.join(b.get('text','') for b in result.get('summary',[]) if b.get('type')=='text')
        candidates=[]
        for i,call in enumerate(calls):
            if i in used:continue
            messages=call['body'].get('messages',[])
            if not messages or not str(messages[-1].get('content','')).startswith('ASUNA_COMPACTION_V1\n'):continue
            parts=[]
            for line in call['raw'].splitlines():
                if line.startswith('data: ') and line[6:].strip()!='[DONE]':
                    for choice in json.loads(line[6:]).get('choices',[]):
                        content=choice.get('delta',{}).get('content')
                        if isinstance(content,str):parts.append(content)
            if ''.join(parts)==expected:candidates.append((i,call))
        record={'result':result,'events':[e for e in body.get('compaction_events',[]) if e.get('data',{}).get('compactionId')==result.get('compactionId')],
                'request_refs':[],'response_refs':[],'provider_summary_join':'UNAVAILABLE'}
        if candidates:
            i,call=candidates[0];used.add(i)
            for key,field in (('request_ref','request_refs'),('response_ref','response_refs')):
                path=evidence.root/call[key]
                record[field].append({'artifact_path':path.resolve().relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes())})
            record.update(call_id=call['call_id'],provider_summary_join='EXACT_CONTENT_AND_OPERATION')
        records.append(record)
    return records


