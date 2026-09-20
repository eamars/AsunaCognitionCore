"""Stage-0 DSH probe via real pinned SDK and runtime, no generic replacement harness."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import uuid
import yaml
from deepseek_harness import DeepSeekHarness
from asuna.config import ROOT, BUNDLE, load
from asuna.evidence import Evidence, write_json, sha
from asuna.provider_proxy import ProviderProxy

cfg = load()
run_id = datetime.now(timezone.utc).strftime('M0-DSH-%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
ev = Evidence(ROOT/'reports'/run_id)
lane = 'character'
proxy = ProviderProxy(cfg[lane], ev, lane)
home = Path(cfg['dsh_home']) / run_id
work = Path(cfg['workdir']) / run_id
home.mkdir(parents=True)
work.mkdir(parents=True)
prompt = (BUNDLE/'prompts/common.md').read_text(encoding='utf-8')+'\n'+(BUNDLE/'prompts/persona_p1_xiaoman.md').read_text(encoding='utf-8')
prompt_file = work/'system.md'
prompt_file.write_text(prompt,encoding='utf-8',newline='\n')
patches = [{'id':name,'disabled':True} for name in ('llm-deepseek','deepseek-llm-api-extensions','session-log-deepseek','plugin-package-inventory-deepseek','persistent-bash','persistent-pwsh','terminal-bash','terminal-pwsh','pty','subprocess')]
patches += [{'insert':[{'id':'asuna-prompt','name':(ROOT/'dsh-plugin/bridge.ts').as_posix(),'config':{'promptFile':prompt_file.as_posix()}}, {'id':'asuna-local-provider','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'asuna-local':{'api':'openai-completions','baseURL':proxy.url,'apiKeyEnv':'ASUNA_LOCAL_DUMMY_KEY','reasoning':'high','compat':{'supportsDeveloperRole':False,'supportsReasoningEffort':False,'thinkingFormat':'chat-template','chatTemplateKwargs':{'enable_thinking':True},'maxTokensField':'max_tokens'},'models':[{'id':cfg[lane]['model'],'contextWindow':262144,'maxTokens':4096,'reasoningEfforts':{'high':'high','off':None}}],'retryPolicy':{'mode':'normal','maxRetries':0}}}}}]}]
patch_path = work/'lane.patch.yml'
patch_path.write_text(yaml.safe_dump(patches,allow_unicode=True,sort_keys=False),encoding='utf-8')
child_env = {k:'' for k in os.environ}
for k in ('SystemRoot','SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','COMSPEC'):
    if k in os.environ: child_env[k] = os.environ[k]
child_env.update({'DSH_HOME':str(home),'ASUNA_LOCAL_DUMMY_KEY':'local-only-not-a-secret','PYTHONIOENCODING':'utf-8'})
binary = ROOT/'node_modules/.bin/dsh.cmd'
manifest = {'experiment_id':run_id,'kind':'M0-DSH-probe','dsh_version':'0.1.5-rc.2','dsh_commit':'fb2c4b9e698e30edb738bca4cf0618587db7d203','dsh_executable':str(binary),'executable_sha256':sha((ROOT/'node_modules/@deepseek-ai/dsh/lib/bin.js').read_bytes()),'package_lock_sha256':sha((ROOT/'package-lock.json').read_bytes()),'prompt_sha256':sha(prompt.encode()),'patch':patches,'sampling':cfg[lane]['sampling']}
write_json(ev.root/'manifest.json',manifest)
results=[]
try:
    with DeepSeekHarness(dsh_bin=str(binary),dsh_home=str(home),profile='sdk-minimal',patches=(str(patch_path),),cwd=str(work),env=child_env,provider='asuna-local',model=cfg[lane]['model'],reasoning_effort='high',max_tokens=4096,request_timeout_seconds=180,initialize_timeout_seconds=45) as dsh:
        session = 'probe-'+uuid.uuid4().hex
        for phase in ('monologue','decide','speak'):
            proxy.purpose = phase
            text = (BUNDLE/f'prompts/stage_{phase}.md').read_text(encoding='utf-8')
            if phase == 'monologue':
                text = '可信场景：dm-a，参与者A。当前事件：我回来了。\n'+text
            value = dsh.run(text,session_id=session)
            ev.record('dsh.stage',{'phase':phase,'final_response':value.final_response,'finish_reason':value.finish_reason,'events':value.events})
            results.append({'phase':phase,'content':value.final_response,'finish_reason':value.finish_reason})
            if not value.final_response.strip() or value.finish_reason != 'completed':
                raise ValueError('INVALID_STAGE_OUTPUT')
        assert len(proxy.calls)==3, 'unexpected auxiliary calls'
        assert all(prompt in str(c['body']['messages'][0]['content']) for c in proxy.calls)
    status='PASS'
except Exception as exc:
    status='FAIL'
    ev.record('dsh.error',{'type':type(exc).__name__,'message':str(exc)})
finally:
    proxy.close()
write_json(ev.root/'result.json',{'status':status,'stages':results,'provider_call_count':len(proxy.calls),'command':'.venv/Scripts/python.exe tools/probe_dsh.py','exit_code':0 if status=='PASS' else 1})
print(json.dumps({'run_id':run_id,'status':status,'provider_calls':len(proxy.calls)}))
raise SystemExit(0 if status=='PASS' else 1)
