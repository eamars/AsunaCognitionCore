from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import threading
import time
import yaml
import httpx
from deepseek_harness import DeepSeekHarness
from .config import ROOT
from .evidence import Evidence,sha
from .lanes import LaneResult
from .provider_proxy import ProviderProxy
from .state import Store


class DshLane:
    """Replaceable lane: pinned SDK boot + narrowly scoped native DSH operations."""
    def __init__(self, config: dict, store: Store, evidence: Evidence, lane='character', plugin_rows=None, broker_token=None):
        self.config,self.store,self.evidence,self.lane=config,store,evidence,lane
        declared=json.loads((ROOT/'package.json').read_text())['dependencies']['@deepseek-ai/dsh']
        installed=json.loads((ROOT/'node_modules/@deepseek-ai/dsh/package.json').read_text())['version']
        locked=json.loads((ROOT/'package-lock.json').read_text())['packages']['node_modules/@deepseek-ai/dsh']['version']
        if not declared==installed==locked=='0.1.5-rc.2':
            raise RuntimeError('DSH_RUNTIME_PIN_MISMATCH')
        evidence.record('runtime.fingerprint',{'version':installed,'executable':str(ROOT/'node_modules/.bin/dsh.cmd'),'executable_sha256':sha((ROOT/'node_modules/@deepseek-ai/dsh/lib/bin.js').read_bytes()),'package_lock_sha256':sha((ROOT/'package-lock.json').read_bytes()),'bridge_sha256':sha((ROOT/'dsh-plugin/runtime.ts').read_bytes()),'sampling':config[lane]['sampling']})
        self.model=config[lane]
        self.home=Path(config['dsh_home'])/store.name/lane
        self.work=Path(config['workdir'])/store.name/lane
        self.home.mkdir(parents=True,exist_ok=True);self.work.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.proxy=ProviderProxy(self.model,evidence,lane)
        self.token=secrets.token_hex(32)
        self.endpoint_file=self.home/'bridge-endpoint.json'
        if self.endpoint_file.exists():self.endpoint_file.unlink()
        rows=[{'id':name,'disabled':True} for name in ('llm-deepseek','deepseek-llm-api-extensions','session-log-deepseek','plugin-package-inventory-deepseek','persistent-bash','persistent-pwsh','terminal-bash','terminal-pwsh','pty','subprocess')]
        compat={'supportsDeveloperRole':False,'supportsReasoningEffort':lane=='executor','thinkingFormat':'chat-template' if lane=='character' else 'qwen','maxTokensField':'max_tokens'}
        if lane=='character':compat['chatTemplateKwargs']={'enable_thinking':True}
        provider={'api':'openai-completions','baseURL':self.proxy.url,'apiKeyEnv':'ASUNA_LOCAL_DUMMY_KEY','reasoning':'high','compat':compat,'models':[{'id':self.model['model'],'contextWindow':262144,'maxTokens':self.model['max_tokens'],'reasoningEfforts':{'high':'xhigh' if lane=='executor' else 'high','off':None}}],'retryPolicy':{'mode':'normal','maxRetries':0}}
        rows += [{'id':'system-prompt','config':{'includeHarnessIdentity':False,'includeRuntimeContext':False,'personaPrefix':''}}, {'insert':[
            {'id':'asuna-runtime','name':(ROOT/'dsh-plugin/runtime.ts').as_posix(),'config':{'model':self.model['model'],'maxTokens':self.model['max_tokens'],'workdir':self.work.as_posix(),'receipts':(self.home/'operations').as_posix(),'endpointFile':self.endpoint_file.as_posix()}},
            {'id':'asuna-local-provider','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'asuna-local':provider}}},
            *(plugin_rows or [])]}]
        patch=self.home/'lane.patch.yml';patch.write_text(yaml.safe_dump(rows,allow_unicode=True,sort_keys=False),encoding='utf-8')
        child={key:'' for key in os.environ}
        for key in ('SystemRoot','SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','COMSPEC'):
            if key in os.environ:child[key]=os.environ[key]
        child.update({'DSH_HOME':str(self.home),'DSH_TELEMETRY_DISABLED':'1','ASUNA_LOCAL_DUMMY_KEY':'local-only-not-a-secret','ASUNA_BRIDGE_TOKEN':self.token})
        if broker_token:child['ASUNA_BROKER_TOKEN']=broker_token
        self.sdk=DeepSeekHarness(dsh_bin=str(ROOT/'node_modules/.bin/dsh.cmd'),dsh_home=str(self.home),profile='sdk-minimal',patches=(str(patch),),cwd=str(self.work),env=child,provider='asuna-local',model=self.model['model'],reasoning_effort='high',max_tokens=self.model['max_tokens'],request_timeout_seconds=300,initialize_timeout_seconds=45)
        try:
            self.sdk.start()
        except BaseException:
            self.sdk.close()
            self.proxy.close()
            raise
        deadline=time.monotonic()+5
        while not self.endpoint_file.exists():
            if time.monotonic()>deadline:raise TimeoutError('BRIDGE_ENDPOINT_NOT_READY')
            time.sleep(.05)
        self.url=f"http://127.0.0.1:{json.loads(self.endpoint_file.read_text())['port']}"
        self.http=httpx.Client(timeout=300,trust_env=False)

    def generate(self, session, operation, phase, text, system):
        with self.lock:
            existing=self.store.db.lane_receipts.find_one({'_id':operation})
            if existing:return LaneResult(**existing['result'])
            self.proxy.purpose=phase
            request={'session':'s-'+sha(session.encode())[:40],'operation':operation,'phase':phase,'text':text,'system':system}
            self.evidence.record('lane.intent',{'lane':self.lane,**request})
            before=len(self.proxy.calls)
            response=self.http.post(self.url+'/run',headers={'Authorization':'Bearer '+self.token},json=request)
            body=response.json()
            self.evidence.record('lane.receipt',{'lane':self.lane,'operation':operation,'status_code':response.status_code,'body':body})
            response.raise_for_status()
            calls=self.proxy.calls[before:]
            value=LaneResult(content=body['content'],reasoning=body.get('reasoning'),finish_reason='stop' if body['finish_reason']=='completed' else body['finish_reason'],request_refs=[c['request_ref'] for c in calls],receipt=body['message_id'])
            self.store.put('lane_receipts',{'_id':operation,'scope_key':'operator','session_id':request['session'],'phase':phase,'result':vars(value),'request_hash':sha(json.dumps(request,sort_keys=True).encode())},stream=operation)
            return value

    def close(self):
        self.sdk.close()
        self.http.close()
        self.proxy.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
