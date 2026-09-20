"""Offline causal request/response extraction from completed F02 lane samples."""
import argparse,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import artifact,freeze

parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--lane',choices=['character','executor'],default='character');parser.add_argument('--out',type=Path)
args=parser.parse_args();source=args.source.resolve();assert source.is_relative_to((ROOT/'reports').resolve())
ev=Evidence(args.out or ROOT/'reports'/('performance-diagnosis-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-F02-ERROR-PROVENANCE')
rows=[];status='FAIL'
try:
    p=source/args.lane
    inputs=sorted(p.glob('sample-*.json'));assert len(inputs)==83
    write_json(ev.root/'plan.json',{'source_manifest':artifact(source/'manifest.json'),'samples':[artifact(f) for f in inputs],'method':'One serialized operation per lane. Match response records strictly between lane.intent and lane.receipt sequence numbers, then require final URL path /chat/completions and exactly one actual generation response. Copy each body under its unique source filename and verify its original body_sha256.','model_calls':0})
    receipts={};intents={};responses=[]
    for path in p.glob('*.json'):
        event=json.loads(path.read_text(encoding='utf-8'));kind=event.get('type');payload=event.get('payload',{})
        if kind=='lane.receipt':receipts[payload['operation']]=(path,event)
        elif kind=='lane.intent':intents[payload['operation']]=event
        elif kind=='provider.response':responses.append((path,event))
    for path in inputs:
        sample=json.loads(path.read_text(encoding='utf-8'))
        if sample['status']!='FAIL':continue
        operation='perf:'+args.lane+':'+str(sample['ordinal']);receipt,end=receipts[operation]
        low=intents[operation]['seq'];high=end['seq'];body=end['payload']['body']
        row={'ordinal':sample['ordinal'],'condition':sample['condition'],'sample':artifact(path),'native_receipt':artifact(receipt),'native_reason':body.get('native_reason'),'finish_reason':sample.get('finish_reason'),'generation_calls':[]}
        for response,event in responses:
            payload=event['payload']
            if not low<event['seq']<high or not payload.get('request_ref'):continue
            request=(p/payload['request_ref']).resolve();assert request.is_relative_to(p)
            req=json.loads(request.read_text(encoding='utf-8'))['payload']
            if not urlsplit(req['url']).path.endswith('/chat/completions'):continue
            target=ev.root/(request.stem+'-body.json');assert not target.exists()
            raw=req['body_utf8'].encode();assert sha(raw)==req['body_sha256'];target.write_bytes(raw)
            row['generation_calls'].append({'request':artifact(request),'response':artifact(response),'raw_request_body':artifact(target),'http_status':payload['status_code'],'error_frames':[line for line in payload.get('body_utf8','').splitlines() if line.startswith('data: ') and '"error"' in line]})
        assert len(row['generation_calls'])==1
        for call in row['generation_calls']:
            for key in ['request','response','raw_request_body']:
                ref=call[key];assert sha((ROOT/ref['artifact_path']).read_bytes())==ref['sha256']
        rows.append(row)
    status='PASS'
except Exception as exc:ev.record('diagnosis.error',{'type':type(exc).__name__,'message':str(exc)})
code=int(status=='FAIL')
write_json(ev.root/'result.json',{'test_id':'PROBE-F02-ERROR-PROVENANCE','status':status,'executed_at':datetime.now(timezone.utc).isoformat(),'mode':'offline_actual_generation_evidence_hash_check','source_experiment':source.name,'lane':args.lane,'samples':rows,'verified_failed_samples':len(rows),'model_calls':0,'commands':[{'argv':sys.orig_argv,'exit_code':code}],
                                'limitations':['This verifies extraction provenance, not model quality. The failed source calls remain FAIL.','Server format errors do not isolate model generation, MTP or parser root cause.','Use the saved exact body with the frozen source deployment/adapter for a targeted reproduction; this extraction makes no model call.']})
print(json.dumps({'run':ev.root.name,'status':status,'failed_samples':len(rows)}));raise SystemExit(code)
