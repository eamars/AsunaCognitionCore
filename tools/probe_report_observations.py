"""Check a real report and falsify stale/misattributed engineering annotations."""
import argparse,copy,json,subprocess,sys,uuid
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import artifact,freeze
from asuna.reporting import observations

parser=argparse.ArgumentParser();parser.add_argument('report',type=Path);args=parser.parse_args()
ev=Evidence(ROOT/'reports'/('report-observations-probe-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-REPORT-OBSERVATIONS')
command=[sys.executable,'-X','utf8',str(BUNDLE/'tools/check_report.py'),str(args.report),'--allow-incomplete']
proc=subprocess.run(command,capture_output=True)
(ev.root/'validator-stdout.txt').write_bytes(proc.stdout);(ev.root/'validator-stderr.txt').write_bytes(proc.stderr)
checks={};status='FAIL'
try:
    assert proc.returncode==0;checks['immutable_package_validator']=True
    report=json.loads(args.report.read_text(encoding='utf-8'))
    rows={r['test_id']:r for r in report['results']}
    assert all(r['assertions'] for r in rows.values() if r['status']!='NOT_RUN')
    checks['every_started_case_lists_acceptance_requirements']=True
    notes=report['engineering_observations']
    assert {'F01','F02','L08','L10','A03','PROBE-L09'}.issubset({note['test_id'] for note in notes})
    assert any('capacity-association-audit-a5867f773264' in e['artifact_path'] for e in rows['F01']['evidence'])
    assert rows['F01']['status']=='PASS';checks['exact_capacity_audit_attached']=True
    assert rows['F02']['status']=='FAIL' and rows['F02']['failure_category']=='provider_format_error_and_output_budget'
    assert report['gates']['COGNITION']['status']=='INCONCLUSIVE' and report['human_review']['reviewer_count']==0
    checks['failure_and_missing_human_review_preserved']=True
    assert rows['L10']['failure_category']=='unrequested_task_route';checks['source_specific_classification']=True
    for label,field,value,error in [('changed_hash','sha256','0'*64,'OBSERVATION_EVIDENCE_HASH_MISMATCH'),('wrong_test','test_id','L01','OBSERVATION_TEST_MISMATCH')]:
        note=copy.deepcopy(notes[0]);note.pop('annotation',None)
        if field=='sha256':note['result'][field]=value
        else:note[field]=value
        directory=ROOT/'.runtime'/ev.root.name/label/'acceptance-observations-invalid';directory.mkdir(parents=True)
        write_json(directory/'observations.json',{'schema':'asuna-evidence-observations-v1','observations':[note]})
        try:observations(directory.parent)
        except ValueError as exc:
            assert str(exc)==error;checks[label+'_rejected']=True
        else:raise AssertionError('INVALID_ANNOTATION_ACCEPTED')
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
code=int(status=='FAIL')
write_json(ev.root/'result.json',{'test_id':'PROBE-REPORT-OBSERVATIONS','status':status,'mode':'real_report_validation_and_invalid_annotation_counterexamples',
    'assertions':checks,'report':artifact(args.report),'commands':[{'argv':command,'exit_code':proc.returncode},{'argv':sys.orig_argv,'exit_code':code}],
    'model_calls':0,'human_votes':0,'limitations':['Valid report structure is not a PASS for its failed or incomplete acceptance cases.']})
print(json.dumps({'run':ev.root.name,'status':status,'checks':len(checks)}));raise SystemExit(code)
