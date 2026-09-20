"""Verify that a checkout can reproduce exact evidence/source bytes."""
import hashlib,json,subprocess,sys,uuid
from datetime import datetime,timezone
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze

ev=Evidence(ROOT/'reports'/('git-byte-probe-'+uuid.uuid4().hex[:12]))
freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-GIT-EVIDENCE-BYTES')
command=['git','ls-files','--stage','-z']
raw=subprocess.check_output(command,cwd=ROOT);checked=0;mismatches=[]
for entry in raw.split(b'\0'):
    if not entry:continue
    info,name=entry.split(b'\t',1);mode,oid,stage=info.decode().split();name=name.decode()
    if stage!='0':raise ValueError('UNMERGED_INDEX')
    content=(ROOT/name).read_bytes()
    actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
    checked+=1
    if actual!=oid:mismatches.append({'artifact_path':name,'staged_git_oid':oid,'raw_worktree_git_oid':actual,'raw_worktree_sha256':sha(content)})
code=int(bool(mismatches));value={'test_id':'PROBE-GIT-EVIDENCE-BYTES','status':'FAIL' if code else 'PASS',
    'executed_at':datetime.now(timezone.utc).isoformat(),'checked_files':checked,'mismatches':mismatches,
    'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code},{'argv':command,'exit_code':0}],
    'method':'Compare every staged blob object ID against raw working-file bytes using the Git blob header; no text/line-ending filters.',
    'limitations':['Original files and historical commits are retained. Verification covers the current index, not all earlier normalized commits.']}
write_json(ev.root/'result.json',value);print(json.dumps({'run':ev.root.name,'status':value['status'],'checked_files':checked,'mismatches':len(mismatches)}));raise SystemExit(code)
