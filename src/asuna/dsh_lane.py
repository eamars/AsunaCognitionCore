from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import threading
import time
import yaml
from contextlib import ExitStack
import httpx
from deepseek_harness import DeepSeekHarness
from .config import ROOT
from .evidence import Evidence,sha,canonical
from .lanes import LaneResult
from .provider_proxy import ProviderProxy
from .state import Store
from .queue import RuntimeLease


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
        self._resources=ExitStack()
        self._resources.enter_context(RuntimeLease(self.home/'runtime.lock'))
        self.lock=threading.RLock()
        self.compact_pending=set()
        self.proxy=ProviderProxy(self.model,evidence,lane,store)
        self._resources.callback(self.proxy.close)
        self.token=secrets.token_hex(32)
        self.endpoint_file=self.home/'bridge-endpoint.json'
        if self.endpoint_file.exists():self.endpoint_file.unlink()
        rows=[{'id':name,'disabled':True} for name in ('llm-deepseek','deepseek-llm-api-extensions','session-log-deepseek','plugin-package-inventory-deepseek','persistent-bash','persistent-pwsh','terminal-bash','terminal-pwsh','pty','subprocess','session-title-llm','compaction-basic')]
        compat={'supportsDeveloperRole':False,'supportsReasoningEffort':lane=='executor','thinkingFormat':'chat-template' if lane=='character' else 'qwen','maxTokensField':'max_tokens'}
        if lane=='character':compat['chatTemplateKwargs']={'enable_thinking':True}
        provider={'api':'openai-completions','baseURL':self.proxy.url,'apiKeyEnv':'ASUNA_LOCAL_DUMMY_KEY','reasoning':'high','compat':compat,'models':[{'id':self.model['model'],'contextWindow':262144,'maxTokens':self.model['max_tokens'],'reasoningEfforts':{'high':'xhigh' if lane=='executor' else 'high','off':None}}],'retryPolicy':{'mode':'normal','maxRetries':0},'streamIdleTimeoutMs':config.get('provider_idle_timeout_seconds',1800)*1000}
        provider['timeoutMs']=config.get('provider_idle_timeout_seconds',1800)*1000
        rows += [{'id':'system-prompt','config':{'includeHarnessIdentity':False,'includeRuntimeContext':False,'personaPrefix':''}}, {'insert':[
            {'id':'asuna-token-meter','name':'@deepseek-ai/dsh-token-meter'},
            {'id':'asuna-compaction','name':(ROOT/'dsh-plugin/compaction.ts').as_posix(),'config':{'auto':False,'maxOverflowRetries':0,'maxTokens':self.model['max_tokens']}},
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
        self._resources.callback(self.sdk.close)
        try:
            self.sdk.start()
        except BaseException:
            self._resources.close()
            raise
        deadline=time.monotonic()+5
        while not self.endpoint_file.exists():
            if time.monotonic()>deadline:
                self._resources.close();raise TimeoutError('BRIDGE_ENDPOINT_NOT_READY')
            time.sleep(.05)
        self.url=f"http://127.0.0.1:{json.loads(self.endpoint_file.read_text())['port']}"
        # One bridge operation can contain many bounded model/tool steps.
        # The former 300s whole-operation timeout interrupted valid workflows.
        self.http=httpx.Client(timeout=config.get('workflow_timeout_seconds',1800),trust_env=False)
        self._resources.callback(self.http.close)

    def generate(self, session, operation, phase, text, system, *, scope_key=None,policy_epoch=None):
        with self.lock:
            native_id='s-'+sha(session.encode())[:40]
            bound=self.store.db.sessions.find_one({'_id':native_id})
            if bound and bound.get('state')=='INVALIDATED':raise PermissionError('SESSION_INVALIDATED')
            if bound and bound.get('compact_requested'):self.compact_pending.add(session)
            existing=self.store.db.lane_receipts.find_one({'_id':operation})
            semantic={'session':native_id,'phase':phase,'text':text,'system':system}
            if scope_key is not None:semantic.update(scope_key=scope_key,policy_epoch=policy_epoch)
            semantic_hash=sha(canonical(semantic))
            if existing:
                if existing.get('state')=='INVALIDATED':raise PermissionError('OPERATION_INVALIDATED')
                if existing.get('semantic_hash')!=semantic_hash:raise PermissionError('OPERATION_INPUT_CHANGED_OR_LEGACY_UNVERIFIED')
                return LaneResult(**existing['result'])
            self.proxy.purpose=phase
            initial_system=(bound or {}).get('initial_system',system)
            delivered_text=text if initial_system==system else ('ASUNA_STATE_REVISION\n本阶段采用程序已提交并冻结的当前人格快照；以下不是外部引用。历史阶段仍使用其原版本。\n'+system+'\n\n'+text)
            request={'session':'s-'+sha(session.encode())[:40],'operation':operation,'phase':phase,'text':delivered_text,'system':initial_system}
            if self.lane=='executor' and self.model.get('compact_at_steps'):request['compact_at_steps']=self.model['compact_at_steps']
            if session in self.compact_pending:
                request['compact_before']=True
            owner=self.store.db.episodes.find_one({'_id':operation.split(':')[0]}) or self.store.db.tasks.find_one({'_id':operation.split(':')[0]}) or {}
            if scope_key is not None:
                if owner and owner.get('scope_key')!=scope_key:raise PermissionError('LANE_OWNER_SCOPE_MISMATCH')
                owner={'scope_key':scope_key,'policy_epoch':policy_epoch}
            if bound and bound.get('scope_key','operator')!=owner.get('scope_key','operator'):raise PermissionError('SESSION_SCOPE_CHANGED')
            if owner.get('scene_id'):
                scene=self.store.db.scenes.find_one({'_id':owner['scene_id']})
                if scene['policy_epoch']!=owner['policy_epoch']:raise PermissionError('POLICY_EPOCH_CHANGED')
            self.proxy.scope_key=owner.get('scope_key','operator')
            roots=set((bound or {}).get('evidence_roots',[]))
            if (bound or {}).get('evidence_root'):roots.add(bound['evidence_root'])
            roots.add(str(self.evidence.root.resolve()))
            # Persist ownership before native delivery so an interrupted first
            # call cannot leave an untracked private session or raw request.
            bound=self.store.put('sessions',{**(bound or {}),'_id':native_id,'binding_key':session,'lane':self.lane,'scope_key':owner.get('scope_key','operator'),'policy_epoch':owner.get('policy_epoch'),'initial_system':initial_system,'dsh_home':str(self.home),'evidence_root':str(self.evidence.root.resolve()),'evidence_roots':sorted(roots),'state':'ACTIVE','inflight_operation':operation,'compaction_generation':(bound or {}).get('compaction_generation',0)},expected=bound['revision'] if bound else None,stream=operation)
            self.evidence.record('lane.intent',{'lane':self.lane,**request})
            before=len(self.proxy.calls)
            response=self.http.post(self.url+'/run',headers={'Authorization':'Bearer '+self.token},json=request)
            body=response.json()
            self.evidence.record('lane.receipt',{'lane':self.lane,'operation':operation,'status_code':response.status_code,'body':body})
            response.raise_for_status()
            if body.get('compaction'):
                self.compact_pending.discard(session)
                self.store.audit(operation,'compaction.native',{'result':body['compaction'],'events':body.get('compaction_events',[])})
            calls=self.proxy.calls[before:]
            refs=[{'artifact_path':(self.evidence.root/c['request_ref']).resolve().relative_to(ROOT).as_posix(),'sha256':sha((self.evidence.root/c['request_ref']).read_bytes())} for c in calls]
            value=LaneResult(content=body['content'],reasoning=body.get('reasoning'),finish_reason='stop' if body['finish_reason']=='completed' else body['finish_reason'],request_refs=refs,receipt=body['message_id'])
            self.store.put('lane_receipts',{'_id':operation,'scope_key':'operator','session_id':request['session'],'phase':phase,'result':vars(value),'semantic_hash':semantic_hash,'request_hash':sha(json.dumps(request,sort_keys=True).encode())},stream=operation)
            previous=self.store.db.sessions.find_one({'_id':request['session']})
            self.store.put('sessions',{**previous,'last_phase':phase,'last_operation':operation,'inflight_operation':None,'compact_requested':False,'compaction_generation':previous.get('compaction_generation',0)+len(body.get('compactions',[]))},expected=previous['revision'],stream=operation)
            return value

    def compact(self,session):
        """Queue native complete-span compaction before the next real phase."""
        self.compact_pending.add(session)
        self.store.audit(session,'compaction.requested',{'execution':'next real phase at completed episode/task boundary'})
        return {'state':'QUEUED','session':session,'summary_generated':False}

    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        self._resources.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
