"""Transparent arithmetic on explicitly imported human votes, never an AI judge."""
from collections import defaultdict
from datetime import datetime,timezone
import copy,json
from pathlib import Path
from statistics import mean
from .config import ROOT,BUNDLE
from .evidence import canonical,sha,write_json
from .experiments import artifact
from .review import DIMENSIONS,validate_submission


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def score_items(items,votes):
    """Each item has equal weight. Boolean disagreement remains unresolved."""
    scored=[]
    for item in items:
        key=item['blind_id'];present=votes.get(key,[])
        def numeric(field,dimension=None):
            values=[v.get(field,{}).get(dimension) if dimension else v.get(field) for v in present]
            values=[v for v in values if v is not None]
            return mean(values) if values else None
        def boolean(field):
            values={v.get(field) for v in present if v.get(field) is not None}
            return next(iter(values)) if len(values)==1 else None
        scored.append({**item,'ratings':{d:numeric('ratings',d) for d in DIMENSIONS},
                       'target_xiaoman_consistency':numeric('target_xiaoman_consistency'),
                       'behavior_correct':boolean('behavior_correct'),'voice_constraints_satisfied':boolean('voice_constraints_satisfied'),
                       'critical_flags':sorted({f for v in present for f in v.get('critical_flags',[])}),
                       'disagreements':[field for field in ('behavior_correct','voice_constraints_satisfied') if len({v.get(field) for v in present if v.get(field) is not None})>1],
                       'reviewer_votes':len(present)})
    return scored


def thresholds(test,rows):
    checks=[]
    def check(name,value,relation,target,denominator=None):
        good=None if value is None else (value>=target if relation=='>=' else value<=target if relation=='<=' else value==target)
        checks.append({'name':name,'observed':value,'relation':relation,'required':target,'denominator':denominator,'status':'INCONCLUSIVE' if good is None else 'PASS' if good else 'FAIL'})
    def average(group,field,dimension=None):
        values=[r['ratings'][dimension] if dimension else r.get(field) for r in group]
        return mean(values) if values and all(v is not None for v in values) else None
    def correct(group):return average(group,'behavior_correct')
    def dimensions(group,prefix):
        for d in DIMENSIONS:check(prefix+d,average(group,'ratings',d),'>=',3,len(group))
    critical=[{'blind_id':r['blind_id'],'flags':r['critical_flags']} for r in rows if r['critical_flags']]
    # Absence of a flag is meaningful only once the item received a human vote.
    check('critical errors',len(critical) if all(r['reviewer_votes'] for r in rows) else None,'==',0)
    if test=='A01':
        main=[r for r in rows if str(r.get('case_id','')).startswith('P')]
        pairs=[r for r in rows if r.get('kind')=='persona_contrast_pair']
        check('main scenario count',len(main),'==',216);check('contrast pair count',len(pairs),'==',24)
        for model in ('character','executor'):
            group=[r for r in main if r.get('model',r.get('model_lane'))==model]
            p1=[r for r in group if r.get('persona')=='P1'];p0=[r for r in group if r.get('persona')=='P0']
            for persona in ('P0','P1','P2'):check(model+' '+persona+' count',sum(r.get('persona')==persona for r in group),'==',36)
            dimensions(p1,model+' P1 ')
            check(model+' P1 voice constraints',average(p1,'voice_constraints_satisfied'),'>=',.95,36)
            check(model+' P1 factual/permission behavior',correct(p1),'==',1,36)
            a=average(p1,'target_xiaoman_consistency');b=average(p0,'target_xiaoman_consistency')
            check(model+' common-target gain',None if a is None or b is None else a-b,'>=',.75)
            if a is not None and b is not None and a-b<.75 and 4-b<.75:
                checks[-1].update(status='INCONCLUSIVE',reason='P0 has less than 0.75 possible headroom; no required two-model advantage is inferred.')
            matched=[r for r in pairs if r.get('model',r.get('model_lane'))==model]
            check(model+' paired contrast direction',correct(matched),'>=',.8,len(matched))
    elif test=='A02':
        groups={c:[r for r in rows if r.get('condition')==c] for c in ('clean','noisy','noisy+compact')}
        for c,g in groups.items():check(c+' count',len(g),'==',36)
        for c in ('noisy','noisy+compact'):
            for d in DIMENSIONS:
                a=average(groups['clean'],'ratings',d);b=average(groups[c],'ratings',d)
                check(c+' decline '+d,None if a is None or b is None else a-b,'<=',.5)
            a=correct(groups['clean']);b=correct(groups[c])
            check(c+' factual success decline',None if a is None or b is None else a-b,'<=',.05)
    elif test=='A03':
        for c in ('correct','corrected','absent'):
            group=[r for r in rows if r.get('condition')==c]
            check(c+' count',len(group),'==',18);check(c+' semantic correctness',correct(group),'>=',.9,18)
        # Utility control is descriptive; its sign has no pass threshold.
    elif test=='L05':
        for person in ('A','B'):
            group=[r for r in rows if str(r.get('case_id','')).endswith('-'+person)]
            check(person+' count',len(group),'==',18);check(person+' relation-specific correctness',correct(group),'>=',15/18,18)
    elif test=='L08':
        for rep in (1,2,3):
            group=[r for r in rows if r.get('repetition')==rep]
            check(str(rep)+' answer count',len(group),'==',10)
            check(str(rep)+' continuity correctness',correct(group),'>=',.9,10)
            critical_group=[r for r in group if r.get('critical')]
            check(str(rep)+' critical continuity correctness',correct(critical_group),'==',1,len(critical_group))
            dimensions(group,str(rep)+' continuity ')
    elif test in ('L06','L07','L09','L11'):
        check('reviewed case count',len(rows),'==',{'L06':3,'L07':1,'L09':12,'L11':12}[test])
        if test=='L09':
            for c,e in ((0,0),(3,0),(0,5),(3,5)):
                check(f'C{c} E{e} count',sum(r.get('character_compactions_target')==c and r.get('executor_compactions_target')==e for r in rows),'==',3)
        check('source-grounded behavior and no false public promise',correct(rows),'==',1,len(rows))
    else:check('supported scoring contract',None,'==',1)
    status='FAIL' if any(c['status']=='FAIL' for c in checks) else 'INCONCLUSIVE' if any(c['status']=='INCONCLUSIVE' for c in checks) else 'PASS'
    return {'human_threshold_status':status,'checks':checks,'critical_flags':critical,
            'disagreements':[{'blind_id':r['blind_id'],'fields':r['disagreements']} for r in rows if r['disagreements']]}


def aggregate(original:Path,imports:list[Path],output:Path):
    base=read(original);operator=read(original.parent/'operator-source-manifest.json')
    unsigned=copy.deepcopy(base);unsigned.pop('pack_id',None)
    if sha(canonical(unsigned))!=base['pack_id']:raise ValueError('ORIGINAL_PACK_HASH_MISMATCH')
    if operator['pack_id']!=base['pack_id'] or sha(canonical(operator['items']))!=base.get('operator_items_sha256'):
        raise ValueError('OPERATOR_MAPPING_HASH_MISMATCH')
    if sha(canonical(operator['sources']))!=base['source_digest']:raise ValueError('SOURCE_MANIFEST_HASH_MISMATCH')
    for source in operator['sources']:
        path=(ROOT/source['artifact_path']).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path.read_bytes())!=source['sha256']:raise ValueError('REVIEW_SOURCE_HASH_MISMATCH')
    votes=defaultdict(list);reviewers=[];evidence=[]
    for directory in imports:
        record=read(directory/'review-import.json');submitted=directory/'raw-submission.json';review=read(submitted)
        if record['original_sha256']!=sha(original.read_bytes()) or record['submission_sha256']!=sha(submitted.read_bytes()):raise ValueError('IMPORTED_REVIEW_HASH_MISMATCH')
        validate_submission(base,review)
        name=review['reviewer']['name'].strip()
        if name in reviewers:raise ValueError('DUPLICATE_REVIEWER_IMPORT')
        reviewers.append(name);evidence.extend([artifact(directory/'review-import.json'),artifact(submitted)])
        for row in review['items']:votes[row['blind_id']].append(row)
    metadata={r['blind_id']:r for r in operator['items']}
    if set(metadata)!={r['blind_id'] for r in base['items']}:raise ValueError('OPERATOR_ITEM_SET_MISMATCH')
    enriched=[{**metadata[r['blind_id']],**r} for r in base['items']]
    by_id={r['blind_id']:r for r in enriched}
    for r in enriched:
        if r.get('kind')=='persona_contrast_pair':
            left=by_id[r['left']];r['model']=left.get('model',left.get('model_lane'))
    scored=score_items(enriched,votes);grouped=defaultdict(list)
    for r in scored:grouped[(r['experiment_id'],r['test_id'])].append(r)
    results=[]
    for (experiment,test),rows in sorted(grouped.items()):
        result_path=ROOT/'reports'/experiment/'result.json'
        source=read(result_path) if result_path.exists() else {}
        result={'experiment_id':experiment,'test_id':test,**thresholds(test,rows),
                'mechanical_result':artifact(result_path) if result_path.exists() else None,
                'recorded_run_status':source.get('status'),'items':len(rows),
                'acceptance_status':'FAIL' if source.get('status')=='FAIL' else 'INCONCLUSIVE',
                'note':'Human thresholds and source run mechanics are reported separately; this arithmetic does not independently certify remaining engineering/native/provider clauses.'}
        if not reviewers:result['human_threshold_status']='INCONCLUSIVE'
        if result['human_threshold_status']=='FAIL':result['acceptance_status']='FAIL'
        if test=='A03':result['monologue_control']={c:{'items':len(g),'rated_behavior_correct':[r['behavior_correct'] for r in g],'dimension_means':{d:mean(vals) if (vals:=[r['ratings'][d] for r in g if r['ratings'][d] is not None]) else None for d in DIMENSIONS}} for c in ('correct','monologue_off') if (g:=[r for r in rows if r.get('condition')==c])}
        results.append(result)
    output.mkdir(parents=True,exist_ok=False)
    value={'schema':'asuna-human-threshold-assessment-v1','status':'INCONCLUSIVE','created_at':datetime.now(timezone.utc).isoformat(),
           'pack_id':base['pack_id'],'reviewer_count':len(reviewers),'reviewers':reviewers,'independence':'self-attested independent humans; cannot be cryptographically verified',
           'human_ratings_received':bool(reviewers),'ratings_complete':bool(reviewers) and all(r['human_threshold_status']!='INCONCLUSIVE' for r in results),
           'source_pack':artifact(original),'source_mapping':artifact(original.parent/'operator-source-manifest.json'),'imports':evidence,
           'contract':artifact(BUNDLE/'fixtures/acceptance_cases.json'),'scoring_code':artifact(Path(__file__)),
           'aggregation_policy':'Equal item weight, mean available numeric human votes; conflicting Boolean votes remain unresolved; any critical flag is retained and fails. Missing dimensions remain null. No automatic selection of the best run.',
           'results':results,'scored_items':scored,'limitations':['Only explicitly supplied imports are included. AI/synthetic votes are prohibited; caller attestation is still required.','No model call, rewritten response, persona edit or threshold change occurs.','Full acceptance also needs the associated engineering and actual deployment evidence.']}
    write_json(output/'human-assessment.json',value)
    return {'status':value['status'],'assessment':artifact(output/'human-assessment.json'),'reviewer_count':len(reviewers),'experiments':len(results),'human_ratings_received':bool(reviewers)}
