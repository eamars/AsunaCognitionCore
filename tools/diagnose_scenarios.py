"""Index observed staged-scenario failures without supplying semantic ratings."""
import argparse,json,re,sys,uuid
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import artifact,freeze

parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--out',type=Path)
args=parser.parse_args();source=args.source.resolve()
assert source.is_relative_to((ROOT/'reports').resolve())
ev=Evidence(args.out or ROOT/'reports'/('scenario-diagnosis-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-SCENARIO-FAILURE-PROVENANCE')
status='FAIL';rows=[];metrics={}
try:
    result=json.loads((source/'result.json').read_text(encoding='utf-8'))
    assert result['test_id'] in ('A01','A03','L01','L05')
    samples=result['samples'];assert len({s['sample_id'] for s in samples})==len(samples)
    counts=Counter(s['status'] for s in samples);groups={}
    for sample in samples:
        key='/'.join([sample['model_lane'],sample['persona'],sample.get('condition','main')])
        groups.setdefault(key,Counter())[sample['status']]+=1
        if sample['status']!='FAIL':continue
        name=sample['sample_id'];assert re.fullmatch(r'sample-[0-9]{4}',name)
        directory=source/name;stored=json.loads((directory/'sample.json').read_text(encoding='utf-8'))
        assert all(sample.get(k)==v for k,v in stored.items())
        flags=[]
        if sample.get('protocol_valid') is False:flags.append('protocol_invalid')
        if sample.get('route_matches') is False:flags.append('unexpected_route')
        if sample.get('unexpected_tools'):flags.append('unexpected_tools')
        if sample.get('error_type'):flags.append('recorded_exception')
        outputs=[];calls=[];errors=[]
        for file in sorted(directory.glob('[0-9]*-*.json')):
            event=json.loads(file.read_text(encoding='utf-8'));payload=event.get('payload',{})
            if event.get('type')=='lane.receipt':
                body=payload['body'];outputs.append({'source':artifact(file),'operation':payload['operation'],'finish_reason':body.get('finish_reason'),'native_reason':body.get('native_reason'),'content':body.get('content','')})
            elif event.get('type')=='provider.request' and urlsplit(payload['url']).path.endswith('/chat/completions'):
                assert sha(payload['body_utf8'].encode())==payload['body_sha256']
                calls.append(artifact(file))
            elif event.get('type','').endswith('.error'):errors.append({'source':artifact(file),'payload':payload})
        row={'sample_id':name,'case_id':sample['case_id'],'model_lane':sample['model_lane'],'persona':sample['persona'],
             'condition':sample.get('condition'),'observed_failure_flags':flags,'source_sample':artifact(directory/'sample.json'),
             'native_outputs':outputs,'exact_generation_requests':calls,'errors':errors,'database':sample['database']}
        trace=directory/'trace.json'
        if trace.exists():row['trace']=artifact(trace)
        else:row['missing_trace_reason']='Scenario raised before its success-path trace export; native provider evidence and named isolated database remain. Read-only recovery is still required.'
        rows.append(row)
    assert len(rows)==counts['FAIL']
    metrics={'samples':len(samples),'sample_statuses':dict(counts),'groups':{k:dict(v) for k,v in groups.items()},
             'failure_flags':dict(Counter(flag for row in rows for flag in row['observed_failure_flags'])),
             'missing_failure_traces':sum('trace' not in row for row in rows)}
    status='PASS'
except Exception as exc:ev.record('diagnosis.error',{'type':type(exc).__name__,'message':str(exc)})
code=int(status=='FAIL')
write_json(ev.root/'result.json',{'test_id':'PROBE-SCENARIO-FAILURE-PROVENANCE','status':status,'executed_at':datetime.now(timezone.utc).isoformat(),
    'mode':'offline_mechanical_failure_index','source_experiment':source.name,'source_result':artifact(source/'result.json'),
    'metrics':metrics,'failures':rows,'model_calls':0,'database_writes':0,'human_votes':0,'commands':[{'argv':sys.orig_argv,'exit_code':code}],
    'limitations':['Observed protocol/route flags are not personality, naturalness or memory-quality scores.','This does not change source statuses, rerun failed samples, or isolate a model/adapter root cause.','Grouping counts is descriptive; small samples do not establish statistical significance.']})
print(json.dumps({'run':ev.root.name,'status':status,'metrics':metrics}));raise SystemExit(code)
