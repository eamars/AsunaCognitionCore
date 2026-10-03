"""Freeze source evidence for diagnostics; model execution belongs to native DSH."""
from datetime import datetime,timezone
import subprocess
from .config import ROOT,BUNDLE,redacted
from .evidence import sha,write_json

def artifact(path):
    return {'artifact_path':str(path.resolve().relative_to(ROOT)).replace('\\','/'),'sha256':sha(path.read_bytes())}


def freeze(config,contract,evidence,test):
    plugin_paths=[p for package in ('cognition-core','xiaoman') for pattern in ('src/*.js','*.json','*.yml')
                  for p in sorted((ROOT/'packages'/package).glob(pattern))]
    paths=[*sorted((BUNDLE/'fixtures').rglob('*')),*sorted((BUNDLE/'prompts').rglob('*')),*sorted((BUNDLE/'config').rglob('*')),*sorted((ROOT/'src/asuna').glob('*.py')),*plugin_paths,*sorted((ROOT/'tools').glob('*.py')),*sorted((ROOT/'tools').glob('*.mjs')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'package-lock.json',ROOT/'uv.lock',ROOT/'environment.json']
    manifest={'experiment_id':evidence.root.name,'test_id':test,'created_at':datetime.now(timezone.utc).isoformat(),'seed':20260919,'contract':artifact(contract),'implementation_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'files':[artifact(p) for p in paths if p.is_file()],'configuration':redacted(config),'human_review_required':True,'performance_slo':None,'failed_attempts_retained':True}
    write_json(evidence.root/'manifest.json',manifest)
    import zipfile
    with zipfile.ZipFile(evidence.root/'frozen-inputs.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in paths:
            if p.is_file():archive.write(p,p.relative_to(ROOT).as_posix())
    return manifest
