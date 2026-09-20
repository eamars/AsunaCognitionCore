"""Exercise report arithmetic with labelled synthetic votes and real blank packs."""
import copy,json,sys,uuid
from datetime import datetime,timezone
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze,artifact
from asuna.review import DIMENSIONS
from asuna.review_scores import score_items,thresholds,aggregate

ev=Evidence(ROOT/'reports'/('review-scores-probe-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-REVIEW-SCORES')
results=[]
try:
    blank=ROOT/'reports/blind-review-v4-20260920-01/blind.json'
    value=aggregate(blank,[],ev.root/'blank-assessment')
    assert value['reviewer_count']==0 and not value['human_ratings_received']
    actual=json.loads((ev.root/'blank-assessment/human-assessment.json').read_text(encoding='utf-8'))
    assert all(r['human_threshold_status']=='INCONCLUSIVE' for r in actual['results'])
    rows=[];votes={}
    for model in ('character','executor'):
        for persona in ('P0','P1','P2'):
            for case in range(1,13):
                for rep in range(3):
                    key=f'SYNTHETIC-{model}-{persona}-{case}-{rep}'
                    rows.append({'blind_id':key,'case_id':f'P{case:02}','model':model,'persona':persona,'kind':'scenario'})
                    votes[key]=[{'ratings':{d:4 for d in DIMENSIONS},'target_xiaoman_consistency':3 if persona=='P0' else 4,'behavior_correct':True,'voice_constraints_satisfied':True,'critical_flags':[]}]
        for case in range(4):
            for rep in range(3):
                key=f'SYNTHETIC-pair-{model}-{case}-{rep}'
                rows.append({'blind_id':key,'model':model,'kind':'persona_contrast_pair'})
                votes[key]=[{'ratings':{d:None for d in DIMENSIONS},'behavior_correct':True,'critical_flags':[]}]
    scored=score_items(rows,votes);passing=thresholds('A01',scored)
    assert passing['human_threshold_status']=='PASS';results.append({'case':'all synthetic A01 thresholds met','observed':passing})
    missing=copy.deepcopy(votes);key=rows[0]['blind_id'];missing[key][0]['target_xiaoman_consistency']=None
    result=thresholds('A01',score_items(rows,missing));assert result['human_threshold_status']=='INCONCLUSIVE';results.append({'case':'missing common-target vote','observed':result})
    conflict=copy.deepcopy(votes);key=rows[-1]['blind_id'];conflict[key].append({**conflict[key][0],'behavior_correct':False})
    result=thresholds('A01',score_items(rows,conflict));assert result['human_threshold_status']=='INCONCLUSIVE' and result['disagreements'];results.append({'case':'opposed human Boolean votes','observed':result})
    flagged=copy.deepcopy(votes);flagged[key][0]['critical_flags']=['SYNTHETIC_PRIVACY_ERROR']
    result=thresholds('A01',score_items(rows,flagged));assert result['human_threshold_status']=='FAIL';results.append({'case':'critical cannot be averaged away','observed':result})
    weak=copy.deepcopy(votes)
    for row in rows:
        if row.get('persona')=='P1' and row['model']=='executor':weak[row['blind_id']][0]['ratings']['natural_expression']=2
    result=thresholds('A01',score_items(rows,weak));assert result['human_threshold_status']=='FAIL';results.append({'case':'weak model cannot hide in pooled average','observed':result})
    near=copy.deepcopy(votes)
    for row in rows:
        if row.get('persona')=='P0':near[row['blind_id']][0]['target_xiaoman_consistency']=4
    result=thresholds('A01',score_items(rows,near));assert result['human_threshold_status']=='INCONCLUSIVE';results.append({'case':'P0 at ceiling','observed':result})
    noise=[]
    for condition in ('clean','noisy','noisy+compact'):
        for index in range(36):noise.append({'blind_id':f'SYNTHETIC-{condition}-{index}','condition':condition,'ratings':{d:4 if condition=='clean' else 3.5 for d in DIMENSIONS},'behavior_correct':True,'critical_flags':[],'disagreements':[],'reviewer_votes':2})
    result=thresholds('A02',noise);assert result['human_threshold_status']=='PASS';results.append({'case':'0.5 noise score decline allowed','observed':result})
    noise[36]['behavior_correct']=False;noise[37]['behavior_correct']=False
    result=thresholds('A02',noise);assert result['human_threshold_status']=='FAIL';results.append({'case':'2/36 factual failures exceed five percentage points','observed':result})
    matrix=[{'blind_id':f'SYNTHETIC-C{c}-E{e}-{rep}','character_compactions_target':c,'executor_compactions_target':e,'ratings':{d:None for d in DIMENSIONS},'behavior_correct':True,'critical_flags':[],'disagreements':[],'reviewer_votes':1} for c,e in ((0,0),(3,0),(0,5),(3,5)) for rep in range(3)]
    result=thresholds('L09',matrix);assert result['human_threshold_status']=='PASS';results.append({'case':'12 matrix human-behavior votes with all required conditions','observed':result})
    matrix[-1]['character_compactions_target']=0
    result=thresholds('L09',matrix);assert result['human_threshold_status']=='FAIL';results.append({'case':'same item total cannot replace a missing matrix condition','observed':result})
    write_json(ev.root/'SYNTHETIC-NOT-HUMAN-VOTES.json',{'warning':'Arithmetic control only; no actor output was graded and these are not human ratings.','items':rows,'votes':votes,'cases':results})
    value={'test_id':'PROBE-REVIEW-SCORES','status':'PASS','checks':len(results)+1,'mode':'real_saved_blank_pack_and_explicit_synthetic_arithmetic_controls','independent_human_votes':0}
except Exception as exc:
    ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)});value={'test_id':'PROBE-REVIEW-SCORES','status':'FAIL','error':str(exc)}
code=int(value['status']=='FAIL')
value.update(executed_at=datetime.now(timezone.utc).isoformat(),commands=[{'argv':[sys.executable,*sys.argv],'exit_code':code}],manifest_sha256=sha((ev.root/'manifest.json').read_bytes()))
write_json(ev.root/'result.json',value);print(json.dumps({'run':ev.root.name,**value}));raise SystemExit(code)
