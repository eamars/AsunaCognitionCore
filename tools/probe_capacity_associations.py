"""Frozen offline verification of exact marker associations in real returns."""
import argparse,copy,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.capacity import check_needle_associations
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze,artifact

parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);args=parser.parse_args()
source=args.source.resolve();assert source.is_relative_to((ROOT/'reports').resolve())
ev=Evidence(ROOT/'reports'/('capacity-association-audit-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-F01-ASSOCIATIONS')
paths=[source/'result.json',source/'manifest.json',*sorted(source.glob('*/sample.json')),*sorted(source.glob('*/capacity-input.json'))]
assert all(p.exists() for p in paths)
write_json(ev.root/'plan.json',{'method':'Strict unique-key JSON with optional outer JSON code fence; compare each START/MIDDLE/END code and value against its own frozen expected record. Unsupported format is unverified, never an automatic capability claim.','source_files':[artifact(p) for p in paths],'scope':'Offline reassessment of retained actual model responses, no new model calls. Original source experiment remains unchanged.','counterexample':'Swap two marker objects while retaining all six literal values; old substring check accepts this, exact association must reject it.'})
checks=[];rows=[]
try:
    expected={tag:{'code':str(i)*12,'value':str(500+i)} for i,tag in enumerate(('START','MIDDLE','END'),1)}
    correct=json.dumps(expected);swapped=copy.deepcopy(expected);swapped['START'],swapped['END']=swapped['END'],swapped['START'];wrong=json.dumps(swapped)
    assert all(v in wrong for item in expected.values() for v in item.values())
    assert check_needle_associations(correct,expected)['verified']
    assert not check_needle_associations(wrong,expected)['verified']
    assert not check_needle_associations(correct[:-1]+',"START":'+json.dumps(expected['START'])+'}',expected)['verified']
    write_json(ev.root/'counterexample.json',{'expected':expected,'swapped_answer':swapped,'old_substring_check':True,'new_check':check_needle_associations(wrong,expected),'mode':'synthetic oracle control; not a model output'})
    recorded=json.loads((source/'result.json').read_text(encoding='utf-8'))
    for path in sorted(source.glob('*/sample.json')):
        sample=json.loads(path.read_text(encoding='utf-8'));input_path=path.parent/'capacity-input.json';truth=json.loads(input_path.read_text(encoding='utf-8'))['expected_operator_only']
        checked=check_needle_associations(sample.get('content',''),truth)
        rows.append({'sample':artifact(path),'input':artifact(input_path),'id':sample['id'],'source_status':sample['status'],**checked})
    source_pass=[r for r in rows if r['source_status']=='PASS']
    assert len(rows)==len(recorded['samples'])==24
    status='PASS' if all(r['verified'] for r in source_pass) else 'FAIL'
    value={'test_id':'PROBE-F01-ASSOCIATIONS','status':status,'source_experiment':source.name,'samples':rows,'metrics':{'source_samples':len(rows),'source_PASS_samples':len(source_pass),'source_PASS_associations_verified':sum(r['verified'] for r in source_pass)},'limitations':['This verifies needle binding in the retained responses only. Source transport/length failures remain failures; no new live capacity result is invented.','A malformed or unsupported response shape remains unverified by this parser.']}
except Exception as exc:
    ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)});value={'test_id':'PROBE-F01-ASSOCIATIONS','status':'FAIL','error':str(exc),'samples':rows}
code=int(value['status']=='FAIL');value.update(executed_at=datetime.now(timezone.utc).isoformat(),commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}]);write_json(ev.root/'result.json',value);print(json.dumps({'run':ev.root.name,'status':value['status'],'metrics':value.get('metrics')}));raise SystemExit(code)
