from datetime import datetime,timezone
import platform,subprocess
from .config import ROOT,redacted
from .evidence import LocalHttp,sha,write_json
from .state import Store


def doctor(config,evidence):
    checks=[];http=LocalHttp(evidence)
    result={'recorded_at':datetime.now(timezone.utc).isoformat(),'config':redacted(config),'platform':platform.platform(),'python':platform.python_version(),'checks':checks}
    try:
        p=subprocess.run([str(ROOT/'node_modules/.bin/dsh.cmd'),'--version'],capture_output=True,text=True,timeout=30)
        checks.append({'id':'DSH_VERSION','status':'PASS' if p.returncode==0 and p.stdout.strip()=='0.1.5-rc.2' else 'FAIL','value':p.stdout.strip(),'exit_code':p.returncode})
        result['dsh']={'version':p.stdout.strip(),'commit':'fb2c4b9e698e30edb738bca4cf0618587db7d203','executable':str(ROOT/'node_modules/.bin/dsh.cmd'),'executable_sha256':sha((ROOT/'node_modules/@deepseek-ai/dsh/lib/bin.js').read_bytes()),'package_lock_sha256':sha((ROOT/'package-lock.json').read_bytes())}
        for name in ('character','executor','embedding'):
            try:
                data=http.request('GET',config[name]['base_url']+'/models','doctor.metadata',api_key=config[name].get('api_key',''))
                checks.append({'id':name.upper()+'_ENDPOINT','status':'PASS','models':data})
            except Exception as exc:checks.append({'id':name.upper()+'_ENDPOINT','status':'FAIL','error_type':type(exc).__name__})
        store=Store(config)
        try:
            ping=store.db.command('ping');hello=store.db.command('hello')
            indexes=list(store.db.memory_units.list_search_indexes()) if 'memory_units' in store.db.list_collection_names() else []
            checks.append({'id':'MONGO','status':'PASS','database':store.name,'ping':ping['ok'],'set_name':hello.get('setName'),'isWritablePrimary':hello.get('isWritablePrimary'),'vector_indexes':indexes})
        except Exception as exc:checks.append({'id':'MONGO','status':'FAIL','error_type':type(exc).__name__})
        finally:store.client.close()
    finally:http.client.close()
    result['status']='PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL'
    result['limitations']=['Connectivity doctor is not behavioral acceptance or capacity validation','No latency SLO or human ratings are implicitly approved']
    write_json(evidence.root/'environment.json',result)
    return result
