"""E01 read-only fingerprints around fresh Asuna initialization."""
import json,sys,uuid
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha,canonical
from asuna.experiments import freeze
from asuna.state import Store

name='isolation-probe-'+uuid.uuid4().hex[:10];ev=Evidence(ROOT/'reports'/name);cfg=load()
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-E01')
store=Store(cfg,'asuna_v2_test_'+name.replace('-','_'));status='FAIL'
def snapshot():
    legacy=Path(cfg['source']['embedding_model_and_key'])
    default=Path.home()/'.dsh';paths=[]
    if default.exists():
        paths=[p for p in default.glob('*') if p.is_file() and p.suffix in ('.yaml','.yml','.json','.toml')]
        paths += [p for p in (default/'profiles').rglob('*') if p.is_file()] if (default/'profiles').exists() else []
    db=store.client[cfg['legacy_database']]
    metadata=list(db.list_collections())
    return {'legacy_config_sha256':sha(legacy.read_bytes()),'default_DSH_home_exists':default.exists(),
        'default_profile_files':[{'relative_path':p.relative_to(default).as_posix(),'sha256':sha(p.read_bytes())} for p in sorted(paths)],
        'legacy_collection_metadata_sha256':sha(canonical(metadata)),'legacy_collection_count':len(metadata)}
try:
    before=snapshot();write_json(ev.root/'before.json',before)
    store.migrate();store.seed()
    denied=False
    try:Store(cfg,cfg['legacy_database'])
    except (ValueError,PermissionError):denied=True
    assert denied
    after=snapshot();write_json(ev.root/'after.json',after)
    assert before==after
    assert before['legacy_config_sha256']==cfg['source']['legacy_config_sha256']
    assert Path(cfg['dsh_home']).resolve().is_relative_to(ROOT/'.runtime')
    assert Path(cfg['workdir']).resolve().is_relative_to(ROOT/'.runtime')
    ev.record('isolation.checked',{'database':store.name,'old_namespace_construction_denied':denied,'new_collections':store.db.list_collection_names(),'legacy_env_matches_M0':True})
    status='PASS'
except Exception as exc:ev.record('probe.error',{'type':type(exc).__name__,'message':str(exc)})
finally:store.client.close()
code=0 if status=='PASS' else 1
write_json(ev.root/'result.json',{'test_id':'PROBE-E01','status':status,'mode':'real_Mongo_read_only_old_metadata_and_fresh_test_db','commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}],'limitations':['Default-profile and old-DB metadata before/after compare covers this probe; no pre-implementation metadata snapshot exists. Legacy environment hash additionally matches the M0 recorded hash.']})
print(json.dumps({'run':name,'status':status}));raise SystemExit(code)
