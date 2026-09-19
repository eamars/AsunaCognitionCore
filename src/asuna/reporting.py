"""Evidence-first reporting. Missing evidence never becomes an acceptance pass."""
from datetime import datetime,timezone
import copy,io,json,re,subprocess,uuid,zipfile
from pathlib import Path
from .config import ROOT,BUNDLE
from .evidence import canonical,sha,write_json


def ref(path):
    return {'artifact_path':path.resolve().relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes())}


def build_report(reports:Path,output:Path):
    report=json.loads((BUNDLE/'reports/report.template.json').read_text(encoding='utf-8'))
    report.update(run_id='report-'+uuid.uuid4().hex[:12],created_at=datetime.now(timezone.utc).isoformat())
    report['fixture_sha256']=sha((BUNDLE/'fixtures/acceptance_cases.json').read_bytes())
    paths=sorted(p for p in reports.rglob('result.json') if 'private' not in p.relative_to(reports).parts)
    attempts=[]
    for path in paths:
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('report_kind'):continue
        attempts.append({'evidence':ref(path),'result':value})
    report['attempt_inventory']=attempts
    report['failure_artifacts']=[ref(p) for p in sorted(reports.rglob('*error.json')) if 'private' not in p.relative_to(reports).parts]
    report['unfinished_experiments']=[]
    for path in sorted(reports.rglob('manifest.json')):
        if 'private' in path.relative_to(reports).parts or (path.parent/'result.json').exists():continue
        manifest=json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('experiment_id'):report['unfinished_experiments'].append({'manifest':ref(path),'experiment_id':manifest['experiment_id'],'test_id':manifest.get('test_id'),'status':'INCONCLUSIVE','completed_sample_files':len(list(path.parent.rglob('sample.json'))),'reason':'No final result exists; work may still be running or was interrupted.'})
    report['environment']['implementation_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    env=ROOT/'environment.json'
    if not env.exists():env=reports/'environment.json'
    if env.exists():
        report['environment'].update(ref(env));report['environment']['dsh_revision']='fb2c4b9e698e30edb738bca4cf0618587db7d203'
        report['environment']['models']=json.loads(env.read_text(encoding='utf-8')).get('models',{})
    manifests=[]
    for row in report['results']:
        test=row['test_id'];runs=[a for a in attempts if a['result'].get('test_id')==test]
        if runs:
            latest=max(runs,key=lambda a:a['result'].get('executed_at',''))
            value=latest['result']
            for field in ('status','mode','executed_at','commands','assertions','metrics','failure_category','minimal_repro','limitations'):
                if field in value:row[field]=value[field]
            row['attempts']=sum(a['result'].get('attempts',1) for a in runs)
            row['evidence']=[a['evidence'] for a in runs]
            for attempt in runs:
                invocation=ROOT/attempt['evidence']['artifact_path']
                invocation=invocation.parent/'invocation.json'
                if invocation.exists():
                    actual=json.loads(invocation.read_text(encoding='utf-8'))
                    row['commands'].append({'argv':actual['argv'],'exit_code':actual['exit_code'],'note':'actual outer invocation; see '+ref(invocation)['artifact_path']})
                    row['evidence'].append(ref(invocation))
            row['experiment_id']=value.get('experiment_id');manifests.append(value.get('manifest_sha256'))
            if not test.startswith('E'):
                row['evidence_mode']=row['mode'];row['mode']='live+manual' if test.startswith('A') or test in ('L05','L06','L07','L08') else 'live'
            if not row['assertions']:
                metrics=value.get('metrics',{})
                if test=='L01':row['assertions']=[{'name':'first decision format','observed':metrics.get('first_decision_valid'),'required':57,'denominator':60},{'name':'decision after at most one repair','observed':metrics.get('decision_valid_after_repair'),'required':59,'denominator':60},{'name':'semantic route','observed':metrics.get('behavior_passes'),'required':54,'denominator':60}]
                elif test=='F01':row['assertions']=[{'name':'actual length, all three needles, stop and matching provider usage','observed_passed':metrics.get('passed'),'required_passed':24,'details':'Each sample has independently recorded input/usage/needle checks.'}]
                elif test in ('L02','L03','L12'):row['assertions']=[{'name':'fresh workspace task and independent oracle','observed_passed':metrics.get('successes'),'required_passed':9 if test=='L02' else 4,'samples':10 if test=='L02' else 5}]
                elif test=='L04':row['assertions']=[{'name':'retrieval gold, critical records, ready vector index, pending backread and stale-ID authority checks','observed':metrics,'details':'See recorded query-by-query assertions in result and retrieval selections.'}]
            if row['status']=='FAIL' and not row['minimal_repro']:
                row['minimal_repro']={'commands':row['commands'],'frozen_experiment':row['experiment_id'],'result_artifact':latest['evidence'],'instructions':'Use the frozen-inputs archive and per-sample input/request in this attempt; never overwrite the failing directory.'}
        else:
            supporting=[];checks=[]
            for path in reports.glob('check-*/junit.xml'):
                text=path.read_text(encoding='utf-8')
                if re.search(r'(?<![A-Z0-9])'+test+r'(?!\d)',text):
                    supporting.append(ref(path))
                    check_path=path.parent/'result.json'
                    if check_path.exists():
                        check=json.loads(check_path.read_text(encoding='utf-8'));checks.append({'argv':check['command'],'exit_code':check['exit_code']})
            if supporting:
                row.update(status='INCONCLUSIVE',mode='engineering_subset_real_Mongo',evidence=supporting)
                row.update(commands=checks,attempts=len(checks),assertions=[{'name':'repository integration subset','details':'Named pytest cases and their outcomes are in each JUnit artifact; this is not a full-contract PASS.'}])
                row['limitations']=['Passing subset is not full acceptance; review each clause of docs/04 and the immutable fixture.']
        # The immutable package validator expects paths relative to the report
        # directory; retain artifact_path as the repository-oriented reference.
        for ev in row['evidence']:
            try:ev['path']=(ROOT/ev['artifact_path']).resolve().relative_to(output.resolve().parent).as_posix()
            except ValueError:raise ValueError('REPORT_DIRECTORY_MUST_CONTAIN_REFERENCED_EVIDENCE')
    report['manifest_sha256']=sha(canonical([m for m in manifests if m])) if manifests else None
    groups={'ENGINEERING':[f'E{i:02}' for i in range(1,25)],'LOCAL_DEPLOYMENT':[f'L{i:02}' for i in range(1,13)],'COGNITION':['A01','A02','A03','L05','L06','L07','L08'],'PERFORMANCE':['F01','F02']}
    for gate,ids in groups.items():
        selected=[r for r in report['results'] if r['test_id'] in ids]
        status='FAIL' if any(r['status']=='FAIL' for r in selected) else 'PASS' if all(r['status']=='PASS' for r in selected) else 'INCONCLUSIVE'
        if gate=='COGNITION':status='INCONCLUSIVE'
        report['gates'][gate]={'status':status,'reason':'See per-test evidence and missing clauses; no independent human ratings imported.' if gate=='COGNITION' else 'Every mandatory clause must pass; subsets and unrun matrices do not pass the gate.','tests':ids}
    report['overall_status']='FAIL' if any(g['status']=='FAIL' for g in report['gates'].values()) else 'INCONCLUSIVE'
    report['not_tested']=[r['test_id'] for r in report['results'] if r['status']=='NOT_RUN']
    report['what_works']=['Native DSH staged character and tool task probes, durable restart, real vector retrieval, actual compaction, isolated WSL tools, scoped erasure (see stage reports).']
    report['what_fails']=[{'test_id':r['test_id'],'evidence':r['evidence']} for r in report['results'] if r['status']=='FAIL']
    report['design_deviations']=[
        'Qwen final OpenAI rendered token IDs are unavailable; equivalent server count was checked against returned usage.',
        'Deletion conservatively removes scope-derived content and affected run evidence; global-safe deletion is rejected. External exports/backups cannot be recalled.',
        'No automatic maintenance or per-turn emotion model is on the character path. No physical devices, camera or real group sending are connected.',
        'Working-budget overflow fails closed; compaction is explicit at complete boundaries, not automatic.',
        'No approved absolute performance SLO and no independent human ratings; cognition and user-experience claims remain INCONCLUSIVE.',
        'Large provider bodies use verified GridFS plus local evidence; arbitrary oversized state records still require explicit artifact storage and fail closed above 1 MiB.',
        'Offline review HTML was generated and import validation tested; rendered UI validation is blocked because the Browser runtime lists no available browser.',
    ]
    report['next_smallest_experiment']='Resolve failed assertions and incomplete acceptance clauses; obtain independent blind ratings after the fixed real-model matrix.'
    write_json(output,report)
    lines=['# Asuna V1 evidence report','',f"Overall: **{report['overall_status']}**",'', '| Gate | Status |','| --- | --- |']
    lines += [f"| {name} | {gate['status']} |" for name,gate in report['gates'].items()]
    lines += ['', '| Test | Status | Attempts | Evidence |','| --- | --- | ---: | --- |']
    for row in report['results']:
        links='; '.join(f"[{e['artifact_path']}]({e['artifact_path']})" for e in row['evidence'])
        lines.append(f"| {row['test_id']} | {row['status']} | {row['attempts']} | {links} |")
    lines += ['', 'All result.json attempts, including failures, are included in the JSON inventory. Paths and SHA256 values are recorded there. Stage probe passes are not full acceptance passes.','', 'Limitations:', '']+['- '+d for d in report['design_deviations']]
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'status':report['overall_status'],'report':ref(output),'attempts':len(attempts)}


def export(config,reports:Path,output:Path):
    """Create a redacted copy, preserving both source and export hashes."""
    secrets=set()
    def collect(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if re.search(r'password|token|api.?key|secret',k,re.I) and isinstance(v,str) and len(v)>=6:secrets.add(v)
                else:collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    collect(config)
    operator=ROOT/'.runtime/operator-ssh.json'
    if operator.exists():collect(json.loads(operator.read_text(encoding='utf-8')))
    embedding_operator=ROOT/'.runtime/embedding-ssh.json'
    if embedding_operator.exists():collect(json.loads(embedding_operator.read_text(encoding='utf-8')))
    selected=[]
    for directory in (reports,ROOT/'src',ROOT/'dsh-plugin',ROOT/'tests',ROOT/'tools',ROOT/'docs',ROOT/'migrations',ROOT/'examples',BUNDLE):
        if directory.exists():
            selected += [p for p in directory.rglob('*') if p.is_file() and not any(x in p.parts for x in ('private','__pycache__','.pytest_cache')) and (p.suffix.lower() not in ('.zip','.pyc') or p.name=='frozen-inputs.zip')]
    selected += [p for p in (ROOT/'README.md',ROOT/'pyproject.toml',ROOT/'uv.lock',ROOT/'package.json',ROOT/'package-lock.json',ROOT/'environment.json',ROOT/'integration_probe.md',ROOT/'report.json',ROOT/'report.md',ROOT/'config/local.example.json') if p.exists()]
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'files':[],'exclusions':['.runtime (homes, sessions, operator credentials, task workspaces)','.venv','node_modules','.git','config/local.json','reports/private','previous zip exports'],'redactions':0}
    # A six-digit password may coincidentally occur inside an embedding float
    # or SHA256. Redact actual credential-sized lexemes, not arbitrary numeric
    # substrings that would corrupt JSON and invalidate unrelated evidence.
    patterns=[re.compile(r'(?<![A-Za-z0-9_.:/\\-])'+re.escape(secret)+r'(?![A-Za-z0-9_.:/\\-])') for secret in secrets]
    def sanitize(raw):
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:raise ValueError('NON_TEXT_EXPORT_REQUIRES_EXPLICIT_REVIEW')
        for pattern in patterns:text=pattern.sub('[REDACTED]',text)
        text=re.sub(r'(mongodb(?:\+srv)?://)[^/@\s\"]+:[^/@\s\"]+@',r'\1[REDACTED]@',text)
        return text.encode()
    def sanitize_archive(raw):
        members=[];changed=False
        with zipfile.ZipFile(io.BytesIO(raw)) as nested:
            for name in nested.namelist():
                source=nested.read(name);safe=sanitize(source);members.append((name,safe));changed|=source!=safe
        if not changed:return raw
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as nested:
            for name,safe in members:nested.writestr(name,safe)
        return output.getvalue()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(set(selected)):
            raw=path.read_bytes();safe=sanitize_archive(raw) if path.suffix=='.zip' else sanitize(raw);name=path.resolve().relative_to(ROOT).as_posix()
            manifest['files'].append({'artifact_path':name,'source_sha256':sha(raw),'export_sha256':sha(safe),'redacted':raw!=safe})
            manifest['redactions']+=int(raw!=safe);archive.writestr(name,safe)
        archive.writestr('evidence-manifest.json',canonical(manifest))
    # Verify bytes actually stored, not only the pre-zip buffers.
    with zipfile.ZipFile(output) as archive:
        for item in manifest['files']:
            raw=archive.read(item['artifact_path'])
            if sha(raw)!=item['export_sha256']:raise ValueError('EXPORT_VERIFICATION_FAILED')
            if item['artifact_path'].endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(raw)) as nested:values=[nested.read(n).decode('utf-8') for n in nested.namelist()]
            else:values=[raw.decode('utf-8')]
            if any(pattern.search(value) for value in values for pattern in patterns):raise ValueError('EXPORT_VERIFICATION_FAILED')
    result={'status':'PASS','archive':ref(output),'files':len(manifest['files']),'redacted_files':manifest['redactions'],'export_is_redacted_copy':True}
    write_json(output.with_suffix('.manifest.json'),result)
    return result
