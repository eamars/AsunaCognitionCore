"""Assemble reviewed E-clause evidence; this does not run or grade model trials."""
import argparse,json,re,sys,uuid,zipfile
from datetime import datetime,timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze,artifact


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def contained(path,parent):
    path=path.resolve()
    if not path.is_relative_to(parent.resolve()):raise ValueError('EVIDENCE_PATH_ESCAPE')
    return path


def assess(check,coverage,out):
    check=contained(check,ROOT/'reports')
    ev=Evidence(out)
    freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'ENGINEERING-CLAUSE-REVIEW')
    # This is a post-run coverage review, not a claim of preregistered scoring.
    # The underlying immutable contract and test input manifests predate runs.
    (ev.root/'coverage-map.json').write_bytes(coverage.read_bytes())
    source=read(check/'manifest.json');run=read(check/'result.json');mapping=read(coverage)
    results=[]
    try:
        contract=artifact(BUNDLE/'fixtures/acceptance_cases.json')
        if source['contract']!=contract or mapping['contract_sha256']!=contract['sha256']:
            raise ValueError('CONTRACT_HASH_CHANGED')
        if run['exit_code']!=0:raise ValueError('CHECK_INVOCATION_FAILED')
        for name in ('stdout','stderr'):
            if sha((check/(name+'.txt')).read_bytes())!=run[name+'_sha256']:
                raise ValueError('CHECK_OUTPUT_HASH_CHANGED')
        frozen={r['artifact_path']:r['sha256'] for r in source['files']}
        # Verify the saved sources, not whatever the working tree later became.
        with zipfile.ZipFile(check/'frozen-inputs.zip') as archive:
            for name,digest in frozen.items():
                if sha(archive.read(name))!=digest:raise ValueError('FROZEN_SOURCE_HASH_CHANGED')
        current_core=[n for n in frozen if n.startswith(('src/asuna/','tests/','dsh-plugin/'))]
        changed=[n for n in current_core if not (ROOT/n).is_file() or sha((ROOT/n).read_bytes())!=frozen[n]]
        cases=list(ET.parse(check/'junit.xml').iter('testcase'))
        if len(mapping['cases'])!=24 or {r['test_id'] for r in mapping['cases']}!={f'E{i:02}' for i in range(1,25)}:
            raise ValueError('COVERAGE_CASE_SET_CHANGED')
        for row in mapping['cases']:
            test=row['test_id'];reasons=[];refs={};commands=[{'argv':run['command'],'exit_code':run['exit_code']}]
            def include(path):
                path=contained(path,ROOT)
                if path.is_file():refs[path.as_posix()]=artifact(path)
                else:raise ValueError('MISSING_EVIDENCE_FILE')
            for name in ('manifest.json','frozen-inputs.zip','junit.xml','result.json','stdout.txt','stderr.txt'):include(check/name)
            include(ev.root/'coverage-map.json')
            matched=[t for t in cases if re.search(r'(?<![A-Z0-9])'+test+r'(?!\d)',t.get('name',''))]
            if any(t.find(k) is not None for t in matched for k in ('failure','error','skipped')):
                reasons.append('A selected JUnit case did not pass.')
            selected=[]
            for t in matched:
                name=t.get('classname','').replace('.','/')+'.py'
                if name not in frozen:raise ValueError('TEST_SOURCE_NOT_FROZEN')
                selected.append({'name':t.get('name'),'source':{'artifact_path':name,'sha256':frozen[name]},'time_seconds':float(t.get('time','0'))})
                for p in t.findall('./properties/property'):
                    if p.get('name') not in ('evidence_path','auxiliary_evidence_path'):continue
                    directory=contained(ROOT/p.get('value'),check)
                    if not directory.is_dir():raise ValueError('MISSING_TEST_EVIDENCE')
                    for file in directory.rglob('*'):
                        if file.is_file():include(file)
            probes=[]
            for name in row['companion_probes']:
                directory=contained(ROOT/'reports'/name,ROOT/'reports')
                result=directory/'result.json'
                if not result.exists():result=directory/'command_result.json'
                value=read(result)
                if value.get('status')!='PASS':reasons.append('Companion probe did not pass: '+name)
                if not (directory/'manifest.json').exists():reasons.append('Companion lacks a frozen experiment manifest: '+name)
                commands.extend(value.get('commands',[]))
                if any(c.get('exit_code')!=0 for c in value.get('commands',[])):reasons.append('Companion invocation failed: '+name)
                for file in directory.rglob('*'):
                    if file.is_file():include(file)
                probes.append({'name':name,'result':artifact(result),'status':value.get('status'),'mode':value.get('mode')})
            if not matched and not probes:reasons.append('No executed evidence for this clause.')
            if row['reviewed_status']!='PASS':reasons.append(row['covered_clauses'])
            if changed:reasons.append('Current implementation differs from this frozen check; claims apply only to its archived source: '+', '.join(changed))
            value={'test_id':test,'status':'INCONCLUSIVE' if reasons else 'PASS',
                   'mode':'contract_review_of_frozen_integration_evidence',
                   'experiment_id':ev.root.name,'executed_at':datetime.now(timezone.utc).isoformat(),
                   'manifest_sha256':sha((ev.root/'manifest.json').read_bytes()),'attempts':1,
                   'commands':commands,'assertions':[{'name':'immutable E-case clause review','details':row['covered_clauses'],'reviewed_status':row['reviewed_status']}],
                   'tests':selected,'companion_probes':probes,'source_evidence':list(refs.values()),
                   'tested_implementation_commit':source['implementation_commit'],
                   'limits_of_claim':'Engineering integration only. Fake lanes, injected faults and real native/model companions are distinguished in each source. No cognition score or fresh test invocation is inferred from this review.',
                   'limitations':reasons}
            write_json(ev.root/test/'result.json',value);results.append(value)
        summary={'test_id':'ENGINEERING-CLAUSE-REVIEW','status':'PASS' if all(r['status']=='PASS' for r in results) else 'INCONCLUSIVE',
                 'executed_at':datetime.now(timezone.utc).isoformat(),'experiment_id':ev.root.name,
                 'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':0}],
                 'metrics':{s:sum(r['status']==s for r in results) for s in ('PASS','INCONCLUSIVE')},
                 'results':[artifact(ev.root/r['test_id']/'result.json') for r in results],
                 'note':'Append-only engineering evidence assessment; all original success, failed and paused attempts are retained.'}
        write_json(ev.root/'result.json',summary)
        return summary
    except Exception as exc:
        ev.record('assessment.error',{'type':type(exc).__name__,'message':str(exc)})
        write_json(ev.root/'result.json',{'test_id':'ENGINEERING-CLAUSE-REVIEW','status':'FAIL','commands':[{'argv':[sys.executable,*sys.argv],'exit_code':1}],'error':str(exc)})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('check',type=Path)
    parser.add_argument('--coverage',type=Path,default=ROOT/'docs/engineering-coverage.json')
    parser.add_argument('--out',type=Path,default=ROOT/'reports'/('engineering-assessment-'+uuid.uuid4().hex[:12]))
    args=parser.parse_args();value=assess(args.check,args.coverage,args.out)
    print(json.dumps({'run':args.out.name,'status':value['status'],'metrics':value['metrics']}))
