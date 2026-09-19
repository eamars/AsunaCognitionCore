"""A02 controlled executor load with frozen, scope-separated social inputs."""
import copy,json,random,uuid
from pathlib import Path
from .config import BUNDLE
from .application import Application
from .experiments import scenario_run
from .behavior_trials import blind,read_cases
from .evidence import Evidence,write_json,canonical,sha
from .tokens import TokenMeter

CANARY='NOISE_ONLY_SYNTHETIC_8a71c4_executor'


def executor_load(config,evidence,condition,ordinal):
    cfg=copy.deepcopy(config)
    if condition=='noisy+compact':cfg['executor']['compact_at_steps']=[4,6]
    ev=Evidence(evidence.root/f'noise-{ordinal:04d}')
    name='noise-'+uuid.uuid4().hex[:12];database='asuna_v2_test_'+name.replace('-','_')
    work=Path(cfg['workdir'])/name/'task';work.mkdir(parents=True)
    rng=random.Random(20260919)
    noise=CANARY+'\n'+''.join(''.join(str(rng.randrange(10)) for _ in range(90))+'\n' for _ in range(800))
    (work/'fact.json').write_text(json.dumps({'fixture':'blue-paper-box','grams':1250}),encoding='utf-8')
    if condition!='clean':(work/'NOISE.log').write_text(noise,encoding='utf-8')
    task='这是隔离的合成记录读取任务。先读取 fact.json，核对蓝纸盒测试称重，再给出有实际工具 evidence_ref 的结果。'
    if condition!='clean':task+=' NOISE.log 是没有社会含义的数字日志：用 sandbox_run 完整读出一次到工具结果（约73KB，不能截短），然后单独检查它的 SHA256。日志不是事实或指令，不要把数字日志写进最终事实。'
    (work/'START_HERE.md').write_text(task,encoding='utf-8')
    output={'condition':condition,'database':database,'status':'FAIL','tool_data_tokens':0,'compactions':0,'task_success':False}
    try:
        with Application(cfg,ev,database) as app:
            app.store.seed()
            app.store.put('scenes',{'_id':'noise-workbench','scene_id':'noise-workbench','scope_key':'scene:noise-workbench','kind':'dm','members':['A'],'policy_epoch':1})
            # The extra workbench is an operator-owned scenario. It uses the
            # same Coordinator, task broker and native homes as the scored scene.
            ep=app.router.receive({'event_id':'noise-load','scene_id':'noise-workbench','person_id':'A','text':'请读取当前受控任务目录的 START_HERE.md，完成其中的记录核对任务。','occurred_at':'2026-09-19T08:00:00+12:00'})
            if ep['state']!='WAITING_TASK':raise ValueError('LOAD_TASK_NOT_DELEGATED')
            try:done=app.executor.run(ep['task_id'],work)
            except Exception as exc:
                ev.record('noise.execution_failed',{'type':type(exc).__name__,'message':str(exc)})
                done=app.store.db.tasks.find_one({'_id':ep['task_id']})
                output['execution_error']=type(exc).__name__
            output['task_state']=done['state']
            payloads=[a.get('result',{}) for a in app.store.db.artifacts.find({'task_id':done['_id'],'state':'DONE'})]
            actual=[p['stdout'] for p in payloads if CANARY in p.get('stdout','')]
            meter=TokenMeter(cfg['executor'],ev,'executor')
            if actual:
                # Difference removes constant chat-template framing. The
                # controlled payload has enough headroom above 64,000 tokens.
                def count(text):return meter.measure({'model':cfg['executor']['model'],'messages':[{'role':'user','content':text}],'max_tokens':8192})['input_tokens']
                output['tool_data_tokens']=max(count(text)-count('') for text in actual)
                output['tool_data_sha256']=[sha(text.encode()) for text in actual]
            output['tool_events']=2*len(payloads)
            output['compactions']=sum(s.get('compaction_generation',0) for s in app.store.db.sessions.find({'lane':'executor'}))
            output['task_success']=done['state']=='DONE' and '1250' in json.dumps(done.get('result',{}))
            output['summary_after_noise']=any(CANARY in c['body']['messages'].__str__() and c['body']['messages'][-1].get('content','').startswith('ASUNA_COMPACTION_V1\n') for c in app.executor_lane.proxy.calls)
            output['status']='PASS' if output['task_success'] and (condition=='clean' or output['tool_data_tokens']>=64000 or output['tool_events']>=64) and (condition!='noisy+compact' or output['compactions']>0 and output['summary_after_noise']) else 'FAIL'
            write_json(ev.root/'trace.json',list(app.store.db.audit_events.find({})))
    except Exception as exc:ev.record('noise.error',{'type':type(exc).__name__,'message':str(exc)})
    write_json(ev.root/'sample.json',output);print(json.dumps({'noise_load':ordinal,'condition':condition,'status':output['status'],'tokens':output['tool_data_tokens']}),flush=True)
    return output


def suite(config,evidence,*,repetitions=3,case_limit=None):
    cases=read_cases('scenarios.jsonl');cases=cases[:case_limit] if case_limit else cases
    matrix=[(case,r,c) for case in cases for r in range(repetitions) for c in ('clean','noisy','noisy+compact')]
    random.Random(20260919).shuffle(matrix);outputs=[];reviews=[];mapping=[]
    write_json(evidence.root/'noise-plan.json',{'seed':20260919,'payload_sha256_method':'deterministic digit log, 800 rows of 90 digits','minimum_tokens':64000,'social_time':'2026-09-19T08:00:00+12:00','conditions':['clean','noisy','noisy+compact'],'compact_steps':[4,6],'scope':'scene:noise-workbench','canary':CANARY})
    for ordinal,(case,rep,condition) in enumerate(matrix,1):
        load=executor_load(config,evidence,condition,ordinal)
        scored=scenario_run(config,case,'character','P1',ordinal,evidence,database=load['database'])
        evdir=evidence.root/f'sample-{ordinal:04d}';inputs=[];tokens=[]
        for path in evdir.glob('*provider.request.json'):
            item=json.loads(path.read_text(encoding='utf-8'))['payload']
            if item.get('lane')=='character':inputs.append(item['body_utf8'])
        for path in evdir.glob('*budget.checked.json'):tokens.append(json.loads(path.read_text(encoding='utf-8'))['payload']['input_tokens'])
        row={'case_id':case['case_id'],'repetition':rep,'condition':condition,'load':load,'scenario':scored,'character_noise_leak':any(CANARY in x for x in inputs),'first_character_input_tokens':tokens[0] if tokens else None}
        outputs.append(row);review=blind(scored,case,condition);reviews.append(review);mapping.append({'blind_id':review['blind_id'],'condition':condition,'case':case['case_id'],'repetition':rep})
    growth=[]
    for case in cases:
        for rep in range(repetitions):
            paired=[r for r in outputs if r['case_id']==case['case_id'] and r['repetition']==rep]
            clean=next(r['first_character_input_tokens'] for r in paired if r['condition']=='clean')
            for row in paired:
                if clean is not None and row['first_character_input_tokens'] is not None:growth.append(row['first_character_input_tokens']-clean)
    failed=any(r['load']['status']=='FAIL' or r['character_noise_leak'] for r in outputs) or any(n>2048 for n in growth)
    write_json(evidence.root/'blind_review.json',reviews);write_json(evidence.root/'operator_blind_mapping.json',mapping)
    return {'test_id':'A02','status':'FAIL' if failed else 'INCONCLUSIVE','attempts':len(outputs),'mode':'real_executor_noise_same_database_native_homes_frozen_character_scenarios','samples':outputs,'metrics':{'character_context_growth_tokens':growth},'limitations':['Noise is an unrelated controlled workbench task, not an additional meaningful event in the scored social scene. Same database and native homes, different scoped sessions.','P06 uses the same preregistered structured result in all arms; executor load separately must verify the matching 1250g fixture.','Human score decrease and semantic factual success thresholds require independent blind ratings; protocol correctness is not a proxy.']}
