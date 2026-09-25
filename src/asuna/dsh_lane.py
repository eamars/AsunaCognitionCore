from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid
import yaml
from contextlib import ExitStack
import httpx
from deepseek_harness import DeepSeekHarness
from .config import ROOT, redact_text
from .evidence import Evidence,sha,canonical
from .lanes import LaneResult
from .provider_proxy import ProviderProxy
from .state import Store
from .queue import RuntimeLease
from .skills import skills_directory
from .model_settings import validate


def provider_finish(raw):
    """Native turn completion is not proof that the provider stopped normally."""
    result=None
    for line in raw.splitlines():
        if line.startswith('data: ') and line[6:].strip()!='[DONE]':
            value=json.loads(line[6:])
            for choice in value.get('choices',[]):
                if choice.get('finish_reason') is not None:result=choice['finish_reason']
    return result


def compaction_audit_records(body,calls,evidence):
    """Join every native replacement to its exact same-lane summary output."""
    records=[];used=set()
    for result in body.get('compactions',[]) or ([body['compaction']] if body.get('compaction') else []):
        expected=''.join(b.get('text','') for b in result.get('summary',[]) if b.get('type')=='text')
        candidates=[]
        for i,call in enumerate(calls):
            if i in used:continue
            messages=call['body'].get('messages',[])
            if not messages or not str(messages[-1].get('content','')).startswith('ASUNA_COMPACTION_V1\n'):continue
            parts=[]
            for line in call['raw'].splitlines():
                if line.startswith('data: ') and line[6:].strip()!='[DONE]':
                    for choice in json.loads(line[6:]).get('choices',[]):
                        content=choice.get('delta',{}).get('content')
                        if isinstance(content,str):parts.append(content)
            if ''.join(parts)==expected:candidates.append((i,call))
        record={'result':result,'events':[e for e in body.get('compaction_events',[]) if e.get('data',{}).get('compactionId')==result.get('compactionId')],
                'request_refs':[],'response_refs':[],'provider_summary_join':'UNAVAILABLE'}
        if candidates:
            i,call=candidates[0];used.add(i)
            for key,field in (('request_ref','request_refs'),('response_ref','response_refs')):
                path=evidence.root/call[key]
                record[field].append({'artifact_path':path.resolve().relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes())})
            record.update(call_id=call['call_id'],provider_summary_join='EXACT_CONTENT_AND_OPERATION')
        records.append(record)
    return records


class DshLane:
    """Replaceable lane: pinned SDK boot + narrowly scoped native DSH operations."""
    def __init__(self, config: dict, store: Store, evidence: Evidence, lane='character', plugin_rows=None, broker_token=None, schedule_callback=None):
        self.config,self.store,self.evidence,self.lane=config,store,evidence,lane
        declared=json.loads((ROOT/'package.json').read_text())['dependencies']['@deepseek-ai/dsh']
        installed=json.loads((ROOT/'node_modules/@deepseek-ai/dsh/package.json').read_text())['version']
        locked=json.loads((ROOT/'package-lock.json').read_text())['packages']['node_modules/@deepseek-ai/dsh']['version']
        if not declared==installed==locked=='0.1.5-rc.2':
            raise RuntimeError('DSH_RUNTIME_PIN_MISMATCH')
        bridge=ROOT/'dsh-plugin/runtime-v2.ts'
        model_lane='character' if lane=='scheduler' else 'executor' if lane=='summary' else lane
        evidence.record('runtime.fingerprint',{'version':installed,'executable':str(ROOT/'node_modules/.bin/dsh.cmd'),'executable_sha256':sha((ROOT/'node_modules/@deepseek-ai/dsh/lib/bin.js').read_bytes()),'package_lock_sha256':sha((ROOT/'package-lock.json').read_bytes()),'bridge_path':str(bridge),'bridge_sha256':sha(bridge.read_bytes()),'sampling':config[model_lane]['sampling'],'provider_timeout_ms':config.get('provider_idle_timeout_seconds',1800)*1000})
        self.model=validate(config[model_lane])
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
        self.scheduler_session='s-'+sha(('asuna-scheduler:'+store.name).encode())[:40] if lane=='scheduler' else None
        self.endpoint_file=self.home/'bridge-endpoint.json'
        if self.endpoint_file.exists():self.endpoint_file.unlink()
        rows=[{'id':name,'disabled':True} for name in ('llm-deepseek','deepseek-llm-api-extensions','session-log-deepseek','plugin-package-inventory-deepseek','persistent-bash','persistent-pwsh','terminal-bash','terminal-pwsh','pty','subprocess','session-title-llm','compaction-basic')]
        compat=self.model['compat']
        # 输入模态是声明，不是猜测：pi-ai 适配器对没声明的模型按 [text] 算（DEFAULT_INPUT）。
        # 少声明会在图片还没附上时就拒绝并点名模型，多声明会让提供方在半路拒绝——
        # 所以这里只转达配置里写明的话，不从模型名里猜「它应该能看图」。
        declared=[m for m in (self.model.get('input_modalities') or []) if m in ('text','image')]
        model_entry={'id':self.model['model'],'contextWindow':self.model['context_window'],'maxTokens':self.model['max_tokens'],'reasoningEfforts':self.model['reasoning_efforts']}
        if declared:model_entry['input']=declared
        provider={'api':self.model['api'],'baseURL':self.proxy.url,'apiKeyEnv':'ASUNA_LOCAL_DUMMY_KEY','compat':compat,'models':[model_entry],'streamIdleTimeoutMs':config.get('provider_idle_timeout_seconds',1800)*1000}
        provider['timeoutMs']=config.get('provider_idle_timeout_seconds',1800)*1000
        # 图片历史会重进每一次请求。DSH 默认按 20 MiB base64 计，而本机审计代理只收 16 MiB 请求体；
        # 把图片预算压在它下面，超限时由 DSH 报 IMAGE_OFFLOAD_REQUIRED，不让请求体凭空被拒。
        provider['maxRequestImageBytes']=8*1024*1024
        chat=config.get('chat',{})
        skills=skills_directory(config,chat.get('scene_id'),chat.get('person_id')) if lane=='executor' else None
        self.skills_enabled=bool(skills)
        skill_rows=[{'id':'asuna-skills','name':'@deepseek-ai/dsh-skill'}]
        if skills:skill_rows += [
            {'id':'asuna-skill-filesystem','name':'@deepseek-ai/dsh-skill-filesystem','config':{'includeDefaultRoots':False,'agentsHome':self.home.as_posix(),'dshHome':self.home.as_posix(),'customSkillDirs':[skills.as_posix()],'watchFollowSymlinks':False}}]
        broker_tool_names=sorted({spec['name'] for row in (plugin_rows or [])
                                  for spec in row.get('config',{}).get('tools',[])
                                  if isinstance(spec,dict) and isinstance(spec.get('name'),str)})
        executor_plugins=list(plugin_rows or [])
        attachment_plugin={'id':'asuna-attachment-local','name':'@deepseek-ai/dsh-attachment-local','config':{'dshHome':self.home.as_posix()}}
        if lane=='executor':
            # Fixed DSH web seam and providers. The model-facing tools are
            # loaded later into each authorized action-agent scope.
            executor_plugins += [
                {'id':'asuna-web-service','name':'@deepseek-ai/dsh-web'},
                {'id':'asuna-web-search-deepseek','name':'@deepseek-ai/dsh-web-search-deepseek','config':{'apiKeyEnv':'DEEPSEEK_API_KEY'}},
                {'id':'asuna-web-fetch-http','name':'@deepseek-ai/dsh-web-fetch-http'},
                attachment_plugin,
            ]
        # Native pre-step pressure does not yet include a newly claimed inbox
        # message. Share its threshold with the bridge's pending-input check.
        pressure_ratio=.8
        rows += [{'id':'system-prompt','config':{'includeHarnessIdentity':False,'includeRuntimeContext':False,'personaPrefix':''}}, {'insert':[
            {'id':'asuna-token-meter','name':'@deepseek-ai/dsh-token-meter'},
            {'id':'asuna-compaction','name':(ROOT/'dsh-plugin/compaction.ts').as_posix(),'config':{'maxTokens':self.model['max_tokens'],'thresholdRatio':pressure_ratio}},
            *skill_rows,
            {'id':'asuna-runtime','name':bridge.as_posix(),'config':{'model':self.model['model'],'reasoningEffort':self.model['reasoning_effort'],'maxTokens':self.model['max_tokens'],'contextWindow':self.model['context_window'],'pressureThresholdRatio':pressure_ratio,'workdir':self.work.as_posix(),'skillsEnabled':bool(skills),'brokerToolNames':broker_tool_names,'receipts':(self.home/'operations').as_posix(),'endpointFile':self.endpoint_file.as_posix(),
                **({'schedulerSession':self.scheduler_session,'schedulerCallbackUrl':schedule_callback['url'],
                    'schedulerCallbackToken':schedule_callback['token']} if schedule_callback else {})}},
            {'id':'asuna-local-provider','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'asuna-local':provider}}},
            *executor_plugins]}]
        patch=self.home/'lane.patch.yml';patch.write_text(yaml.safe_dump(rows,allow_unicode=True,sort_keys=False),encoding='utf-8')
        child={key:'' for key in os.environ}
        for key in ('SystemRoot','SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','COMSPEC'):
            if key in os.environ:child[key]=os.environ[key]
        child.update({'DSH_HOME':str(self.home),'DSH_TELEMETRY_DISABLED':'1','ASUNA_LOCAL_DUMMY_KEY':'local-only-not-a-secret','ASUNA_BRIDGE_TOKEN':self.token})
        if broker_token:child['ASUNA_BROKER_TOKEN']=broker_token
        if lane=='executor':
            for key in ('DEEPSEEK_API_KEY','DEEPSEEK_SEARCH_BASE_URL','DSH_WEB_SEARCH_PROVIDER','DSH_WEB_FETCH_PROVIDER'):
                if os.environ.get(key):child[key]=os.environ[key]
        self.sdk=DeepSeekHarness(dsh_bin=str(ROOT/'node_modules/.bin/dsh.cmd'),dsh_home=str(self.home),profile='sdk-minimal',patches=(str(patch),),cwd=str(self.work),env=child,provider='asuna-local',model=self.model['model'],reasoning_effort=self.model['reasoning_effort'],max_tokens=self.model['max_tokens'],request_timeout_seconds=300,initialize_timeout_seconds=45)
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
        # /run returns when the native agent becomes idle, possibly after many
        # valid tool/model steps. A host-wide read deadline would terminate an
        # otherwise live agentic loop. Native provider timeouts and cancellation
        # still apply; local connection establishment remains bounded.
        self.http=httpx.Client(timeout=httpx.Timeout(None,connect=10),trust_env=False)
        self._resources.callback(self.http.close)

    def schedule(self, path, payload=None):
        if self.lane!='scheduler':raise ValueError('SCHEDULER_LANE_REQUIRED')
        headers={'Authorization':'Bearer '+self.token}
        response=(self.http.get(self.url+path,headers=headers) if payload is None else
                  self.http.post(self.url+path,headers=headers,json=payload))
        body=response.json()
        if response.is_error:raise RuntimeError('NATIVE_SCHEDULE: '+redact_text(json.dumps(body,ensure_ascii=False),self.config))
        return body

    def generate(self, session, operation, phase, text, system, *, scope_key=None,policy_epoch=None):
        with self.lock:
            native_id='s-'+sha(session.encode())[:40]
            bound=self.store.db.sessions.find_one({'_id':native_id})
            if bound and bound.get('state')=='INVALIDATED':raise PermissionError('SESSION_INVALIDATED')
            if bound and bound.get('compact_requested'):self.compact_pending.add(session)
            owner=self.store.db.episodes.find_one({'_id':operation.split(':')[0]}) or self.store.db.tasks.find_one({'_id':operation.split(':')[0]}) or {}
            if scope_key is not None:
                if owner and owner.get('scope_key')!=scope_key:raise PermissionError('LANE_OWNER_SCOPE_MISMATCH')
                owner={'scope_key':scope_key,'policy_epoch':policy_epoch}
            allowed_capabilities=(sorted(set(owner.get('allowed_capabilities',[])))
                                  if self.lane=='executor' and isinstance(owner.get('allowed_capabilities'),list) else None)
            existing=self.store.db.lane_receipts.find_one({'_id':operation})
            semantic={'session':native_id,'phase':phase,'text':text,'system':system}
            if scope_key is not None:semantic.update(scope_key=scope_key,policy_epoch=policy_epoch)
            if allowed_capabilities is not None:semantic['allowed_capabilities']=allowed_capabilities
            semantic_hash=sha(canonical(semantic))
            if existing:
                if existing.get('state')=='INVALIDATED':raise PermissionError('OPERATION_INVALIDATED')
                if existing.get('semantic_hash')!=semantic_hash:raise PermissionError('OPERATION_INPUT_CHANGED_OR_LEGACY_UNVERIFIED')
                return LaneResult(**existing['result'])
            self.proxy.purpose=phase
            self.proxy.ui_operation=operation
            initial_system=(bound or {}).get('initial_system',system)
            delivered_text=text if initial_system==system else ('ASUNA_STATE_REVISION\n本阶段采用程序已提交并冻结的当前人格快照；以下不是外部引用。历史阶段仍使用其原版本。\n'+system+'\n\n'+text)
            request={'session':'s-'+sha(session.encode())[:40],'operation':operation,'phase':phase,'text':delivered_text,'system':initial_system}
            if allowed_capabilities is not None:request['allowed_capabilities']=allowed_capabilities
            if self.lane=='executor' and self.model.get('compact_at_steps'):request['compact_at_steps']=self.model['compact_at_steps']
            if session in self.compact_pending:
                safe=bool(bound and bound.get('last_phase') in ('SPEAK','execution','execution-repair'))
                if bound and bound.get('last_phase') in ('DECIDE','SELF','REFLECT'):
                    prior=self.store.db.episodes.find_one({'_id':bound['last_operation'].split(':')[0],'state':'COMMITTED','decision.next':'silent'})
                    if prior:safe=True;request['completed_episode_boundary']=bound['last_operation']
                if safe:request['compact_before']=True
            if bound and bound.get('scope_key','operator')!=owner.get('scope_key','operator'):raise PermissionError('SESSION_SCOPE_CHANGED')
            if owner.get('scene_id'):
                scene=self.store.db.scenes.find_one({'_id':owner['scene_id']})
                if scene['policy_epoch']!=owner['policy_epoch']:raise PermissionError('POLICY_EPOCH_CHANGED')
            if self.lane=='executor':
                request['skills_enabled']=self.skills_enabled and allowed_capabilities is not None and 'skill' in allowed_capabilities
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
            if response.is_error:
                raise RuntimeError('DSH_BRIDGE: '+redact_text(json.dumps(body,ensure_ascii=False),self.config))
            skill_calls=[e for e in body.get('events',[]) if e.get('type')=='tool/call' and e.get('data',{}).get('name')=='skill']
            if skill_calls:
                self.store.audit(operation.split(':')[0],'skills.native_calls',{'session_id':native_id,'calls':skill_calls,
                    'results':[e for e in body.get('events',[]) if e.get('type')=='tool/result' and any(b.get('toolCallId') in {c['data']['callId'] for c in skill_calls} for b in e.get('data',{}).get('message',{}).get('content',[]))]},owner.get('scope_key','operator'))
            calls=self.proxy.calls[before:]
            if body.get('compaction') or body.get('compactions'):
                self.compact_pending.discard(session)
                for record in compaction_audit_records(body,calls,self.evidence):
                    self.store.audit(operation,'compaction.native',{**record,'session_id':native_id},owner.get('scope_key','operator'))
            refs=[{'artifact_path':(self.evidence.root/c['request_ref']).resolve().relative_to(ROOT).as_posix(),'sha256':sha((self.evidence.root/c['request_ref']).read_bytes())} for c in calls]
            finish=body['finish_reason']
            if finish=='completed':finish=(provider_finish(calls[-1]['raw']) if calls else None) or 'unverified_provider_finish'
            value=LaneResult(content=body['content'],reasoning=body.get('reasoning'),finish_reason=finish,request_refs=refs,receipt=body['message_id'],diagnostic=body.get('native_reason') if finish!='stop' else None)
            self.store.put('lane_receipts',{'_id':operation,'scope_key':'operator','session_id':request['session'],'phase':phase,'result':vars(value),'semantic_hash':semantic_hash,'request_hash':sha(json.dumps(request,sort_keys=True).encode())},stream=operation)
            previous=self.store.db.sessions.find_one({'_id':request['session']})
            pending=session in self.compact_pending or bool(previous.get('compact_requested') and previous.get('compact_request_id')!=bound.get('compact_request_id'))
            self.store.put('sessions',{**previous,'last_phase':phase,'last_operation':operation,'inflight_operation':None,'compact_requested':pending,'compaction_generation':previous.get('compaction_generation',0)+len(body.get('compactions',[]))},expected=previous['revision'],stream=operation)
            return value

    def compact(self,session):
        """Queue native complete-span compaction before the next real phase."""
        with self.lock:
            self.compact_pending.add(session)
            bound=self.store.db.sessions.find_one({'binding_key':session})
            if bound:self.store.put('sessions',{**bound,'compact_requested':True,'compact_request_id':str(uuid.uuid4())},expected=bound['revision'],stream=session)
            self.store.audit(session,'compaction.requested',{'execution':'next real phase at completed episode/task boundary'})
        return {'state':'QUEUED','session':session,'summary_generated':False}

    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        self._resources.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
