"""Preserve a completed L09 sample's protocol rejection and independent file facts."""
import argparse,json,re,sys,uuid,zipfile
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import artifact,freeze

parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--out',type=Path)
args=parser.parse_args();source=args.source.resolve()
assert source.is_relative_to((ROOT/'reports').resolve())
ev=Evidence(args.out or ROOT/'reports'/('matrix-diagnosis-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-L09-FAILURE-PROVENANCE')
status='FAIL';observations={}
try:
    sample=json.loads((source/'sample.json').read_text(encoding='utf-8'))
    terminal=json.loads((source/'terminal-state.json').read_text(encoding='utf-8'))
    trace=json.loads((source/'trace.json').read_text(encoding='utf-8'))
    db=sample['database'];assert re.fullmatch(r'asuna_v2_test_matrix_[0-9a-f]{12}',db)
    task=terminal['tasks'][0];assert len(terminal['tasks'])==1
    work=(ROOT/'.runtime/work'/('matrix-'+db.rsplit('_',1)[1])/'task').resolve()
    assert work.is_relative_to((ROOT/'.runtime/work').resolve())
    refs=[artifact(source/n) for n in ('sample.json','terminal-state.json','trace.json')]
    refs.append(artifact(source.parent/'manifest.json'))
    counts=Counter();summaries=[]
    for event in trace:
        if event['type']!='compaction.native':continue
        payload=event['payload'];native=payload['result']
        lane='executor' if event['stream_id'].startswith(task['_id']+':') else 'character'
        counts[lane]+=1
        summaries.append({'lane':lane,'id':native['compactionId'],'shadowed_range':native['shadowedRange'],'shadowed_token_count':native['shadowedTokenCount'],'provider_summary_join':payload['provider_summary_join']})
    assert len({s['id'] for s in summaries})==len(summaries)
    outputs=[]
    for path in sorted(source.glob('*lane.receipt.json')):
        p=json.loads(path.read_text(encoding='utf-8'))['payload']
        if p['lane']!='executor':continue
        body=p['body'];target=ev.root/(path.stem+'-output.json')
        write_json(target,{'operation':p['operation'],'content':body['content'],'finish_reason':body['finish_reason']})
        outputs.append({'source':artifact(path),'extracted':artifact(target)})
    files=[];expected={}
    with zipfile.ZipFile(source.parent/'frozen-inputs.zip') as archive:
        for name in archive.namelist():
            if name.startswith('asuna_v2_v1_handoff/fixtures/reconcile_task/'):
                leaf=Path(name).name;expected[leaf]=sha(archive.read(name))
        truth=json.loads(archive.read('asuna_v2_v1_handoff/fixtures/oracles/reconcile_expected.json'))
    assert len(expected)==13
    protected=all((work/name).is_file() and sha((work/name).read_bytes())==h for name,h in expected.items())
    for name in ('report.json','anomalies.md'):
        raw=(work/name).read_bytes();target=ev.root/('saved-'+name);target.write_bytes(raw)
        files.append({'name':name,'evidence':artifact(target),'source_sha256':sha(raw)})
    actual=json.loads((work/'report.json').read_text(encoding='utf-8'))
    correct=all(actual.get(k)==truth[k] for k in ('unique_posted_count','total_amount_cents'))
    receipts=[r for r in terminal['effect_receipts'] if r.get('kind')=='simulated_copy_commit']
    rejected=[r['payload'] for r in trace if r['type']=='execution.result_rejected']
    observations={'task_state':task['state'],'task_failure':task.get('failure'),'native_compactions':dict(counts),'summaries':summaries,
                  'result_rejections':rejected,'executor_outputs':outputs,'saved_work_products':files,
                  'protected_inputs_equal_frozen_fixtures':protected,'file_counts_and_total_equal_truth':correct,
                  'file_values':{k:actual.get(k) for k in ('unique_posted_count','total_amount_cents')},
                  'committed_effect_receipts':receipts,'sources':refs}
    assert counts=={'character':3,'executor':5} and task['state']=='FAILED_PROTOCOL'
    assert protected and correct and len(receipts)==2 and len(outputs)==2
    for item in refs:assert sha((ROOT/item['artifact_path']).read_bytes())==item['sha256']
    status='PASS'
except Exception as exc:ev.record('diagnosis.error',{'type':type(exc).__name__,'message':str(exc)})
code=int(status=='FAIL')
write_json(ev.root/'result.json',{'test_id':'PROBE-L09-FAILURE-PROVENANCE','status':status,'executed_at':datetime.now(timezone.utc).isoformat(),
    'mode':'offline_completed_failure_inspection','source_experiment':source.parent.name,'observations':observations,'model_calls':0,'database_writes':0,
    'commands':[{'argv':sys.orig_argv,'exit_code':code}],
    'limitations':['Source sample remains FAIL: correct files and eight summaries do not establish accepted task completion or public feedback.',
                   'The repaired result declares done with a nonempty unmet_items array; rejection is required by the existing task contract.',
                   'These are engineering observations, not independent natural-language ratings.']})
print(json.dumps({'run':ev.root.name,'status':status}));raise SystemExit(code)
