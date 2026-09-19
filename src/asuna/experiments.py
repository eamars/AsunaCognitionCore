"""Acceptance drivers around the production route, created after integration probes."""
from datetime import datetime,timezone
import copy,json,os,random,subprocess,sys,uuid
from pathlib import Path
from .config import ROOT,BUNDLE,redacted
from .evidence import Evidence,write_json,canonical,sha
from .state import Store,Denied
from .context import ContextBuilder
from .coordinator import Coordinator
from .router import Router
from .dsh_lane import DshLane
from .tasks import TaskService


def artifact(path):
    return {'artifact_path':str(path.resolve().relative_to(ROOT)).replace('\\','/'),'sha256':sha(path.read_bytes())}


def freeze(config,contract,evidence,test):
    paths=[*sorted((BUNDLE/'fixtures').rglob('*')),*sorted((BUNDLE/'prompts').rglob('*')),*sorted((BUNDLE/'config').rglob('*')),*sorted((ROOT/'src/asuna').glob('*.py')),*sorted((ROOT/'dsh-plugin').glob('*.ts')),*sorted((ROOT/'tools').glob('*.py')),*sorted((ROOT/'tools').glob('*.mjs')),*sorted((ROOT/'tests').glob('*.py')),ROOT/'package-lock.json',ROOT/'uv.lock',ROOT/'environment.json']
    manifest={'experiment_id':evidence.root.name,'test_id':test,'created_at':datetime.now(timezone.utc).isoformat(),'seed':20260919,'contract':artifact(contract),'implementation_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'files':[artifact(p) for p in paths if p.is_file()],'configuration':redacted(config),'human_review_required':True,'performance_slo':None,'failed_attempts_retained':True}
    write_json(evidence.root/'manifest.json',manifest)
    import zipfile
    with zipfile.ZipFile(evidence.root/'frozen-inputs.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in paths:
            if p.is_file():archive.write(p,p.relative_to(ROOT).as_posix())
    return manifest


class FixtureSelection:
    """Predeclared available facts for matched attribution, not oracle answers."""
    def __init__(self,store,ids):self.store,self.ids=store,ids
    def search(self,scope,epoch,query,exclude_sources=()):
        rows=[]
        for key in self.ids:
            doc=self.store.db.memory_units.find_one({'_id':key,'scope_key':{'$in':['global-safe',scope]},'status':{'$in':['active','superseded']}})
            if not doc:raise Denied('MATCHED_MATERIAL_SCOPE_OR_STATE')
            rows.append(doc)
        return rows,{'path':'preregistered_matched_material','vector_verified':False,'selected':self.ids}


def fixed_feedback(store,coordinator,ep,fixture):
    """Only attribution/protocol control: the contract explicitly fixes this result."""
    service=TaskService(store);task=service.claim(ep['task_id'])
    ref=fixture['receipt']['id']
    store.put('artifacts',{'_id':ref,'scope_key':task['scope_key'],'task_id':task['_id'],'state':'DONE','kind':'preregistered_fixture_receipt','receipt':fixture['receipt']},stream=task['_id'])
    result={'task_id':task['_id'],'intent_revision':task['intent_revision'],'status':fixture['status'],'facts':[{'text':f['fact'],'evidence_refs':[ref]} for f in fixture['facts']],'uncertainties':[],'unmet_items':[],'artifact_refs':[ref],'effect_receipts':[],'needs_decision':None}
    done=service.finish(task,result)
    return service.feedback(done,coordinator)


def scenario_run(config,case,model,persona,ordinal,evidence,*,database=None):
    database=database or 'asuna_v2_test_eval_'+uuid.uuid4().hex[:20]
    store=Store(config,database);store.migrate();store.seed()
    for mem in case.get('_experiment_memories',[]):
        for old_id in mem.get('supersedes',[]):
            old=store.db.memory_units.find_one({'_id':old_id})
            store.put('memory_units',{**old,'status':'superseded'},expected=old['revision'])
        store.put('memory_units',mem)
    attempt=Evidence(evidence.root/f'sample-{ordinal:04d}')
    output={'sample_id':f'sample-{ordinal:04d}','case_id':case.get('case_id',case.get('id')),'model_lane':model,'persona':persona,'database':database,'status':'FAIL','phase_calls':0,'first_decision_valid':False,'protocol_valid':False}
    try:
        with DshLane(config,store,attempt,model) as lane:
            context=ContextBuilder(store,FixtureSelection(store,case.get('memory_ids',[])))
            coordinator=Coordinator(store,lane,context=context,monologue_enabled=not case.get('_monologue_off',False))
            router=Router(store,coordinator)
            event={'event_id':'sample-input','scene_id':case['scene_id'],'person_id':case['person_id'],'text':case['input'],'occurred_at':'2026-09-19T08:00:00+12:00','mentioned':True,'trusted_context_events':case.get('trusted_context_events',[])}
            ep=router.receive(event,persona=persona)
            decisions=list(store.db.audit_events.find({'stream_id':ep['_id'],'type':'phase.output','payload.phase':'DECIDE'}))
            output['first_decision_valid']=len(decisions)==1 and bool(ep.get('decision'))
            output['protocol_valid']=bool(ep.get('decision')) and ep['state']!='FAILED_PROTOCOL'
            output['decision']=ep.get('decision');output['initial_state']=ep['state']
            if ep['state']=='WAITING_TASK' and case.get('post_delegation_fixture_result'):
                ep=fixed_feedback(store,coordinator,ep,case['post_delegation_fixture_result'])
            output['phase_calls']=len(lane.proxy.calls)
            output['final_state']=ep['state'];output['public_messages']=store.public_messages(case['scene_id'],case['person_id'])
            output['unexpected_tools']=any(c['body'].get('tools') for c in lane.proxy.calls)
            expected=case.get('expected_route')
            output['route_matches']=expected is None or (output['decision'] or {}).get('next')==expected
            output['status']='PASS' if output['protocol_valid'] and not output['unexpected_tools'] and output['route_matches'] else 'FAIL'
            output['provider_request_hashes']=[sha(canonical(c['body'])) for c in lane.proxy.calls]
            write_json(attempt.root/'trace.json',list(store.db.audit_events.find({}).sort([('stream_id',1),('seq',1)])))
    except Exception as exc:
        output['error_type']=type(exc).__name__;attempt.record('sample.error',{'type':type(exc).__name__,'message':str(exc)})
    finally:store.client.close()
    write_json(attempt.root/'sample.json',output)
    print(json.dumps({'sample':ordinal,'case':output['case_id'],'model':model,'persona':persona,'status':output['status']}),flush=True)
    return output


def staged_suite(config,test,evidence):
    scenarios=[json.loads(line) for line in (BUNDLE/'fixtures/scenarios.jsonl').read_text(encoding='utf-8').splitlines()]
    matrix=[]
    if test=='L01':matrix=[(case,'character','P1',rep) for case in scenarios for rep in range(5)]
    elif test=='A01':
        matrix=[(case,model,persona,rep) for model in ('character','executor') for persona in ('P0','P1','P2') for case in scenarios for rep in range(3)]
        contrasts=[json.loads(line) for line in (BUNDLE/'fixtures/contrast_cases.jsonl').read_text(encoding='utf-8').splitlines()]
        contrasts=[{**case,'scene_id':'dm-a','person_id':'A','memory_ids':[]} for case in contrasts]
        matrix += [(case,model,persona,rep) for model in ('character','executor') for persona in ('P1','P2') for case in contrasts for rep in range(3)]
    random.Random(20260919).shuffle(matrix)
    outputs=[];blind=[];mapping=[]
    for index,(case,model,persona,rep) in enumerate(matrix,1):
        output=scenario_run(config,case,model,persona,index,evidence);outputs.append(output)
        blind_id=sha(canonical([evidence.root.name,index,'blind']))[:16]
        blind.append({'blind_id':blind_id,'target_persona':(BUNDLE/('prompts/persona_'+{'P0':'p0_neutral','P1':'p1_xiaoman','P2':'p2_counter'}[persona]+'.md')).read_text(encoding='utf-8'),'scene':case['scene_id'],'input':case['input'],'available_memory_ids':case.get('memory_ids',[]),'trusted_context_events':case.get('trusted_context_events',[]),'response':[m['text'] for m in output.get('public_messages',[])],'ratings':{'persona_consistency':None,'independent_stance':None,'relationship_memory_use':None,'natural_expression':None},'critical_flags':[]})
        mapping.append({'blind_id':blind_id,'sample':index,'model':model,'persona':persona,'repetition':rep})
    write_json(evidence.root/'blind_review.json',blind);write_json(evidence.root/'operator_blind_mapping.json',mapping)
    first=sum(o['first_decision_valid'] for o in outputs);valid=sum(o['protocol_valid'] for o in outputs)
    status='PASS' if test=='L01' and first>=57 and valid>=59 and all(not o.get('unexpected_tools') for o in outputs) and sum(bool(o.get('route_matches')) for o in outputs)>=54 else ('INCONCLUSIVE' if test=='A01' else 'FAIL')
    return {'test_id':test,'status':status,'mode':'real_models_real_DSH_real_Mongo','attempts':len(outputs),'metrics':{'scenario_runs':len(outputs),'first_decision_valid':first,'decision_valid_after_repair':valid,'behavior_passes':sum(o['status']=='PASS' for o in outputs)},'samples':outputs,'limitations':['No human review imported; cognition remains INCONCLUSIVE','Matched-material retrieval is for attribution, not evidence of vector performance']}


def evaluate(config,test,contract,evidence):
    accepted=json.loads(contract.read_text(encoding='utf-8'))
    case=next((c for c in accepted['cases'] if c['test_id']==test),None)
    if not case:raise ValueError('UNKNOWN_ACCEPTANCE_TEST')
    config=copy.deepcopy(config)
    if test=='A01':
        for lane in ('character','executor'):config[lane]['sampling']={'temperature':.7,'top_p':.95,'seed':20260919};config[lane]['max_tokens']=4096
    manifest=freeze(config,contract,evidence,test)
    command=['asuna','evaluate','--test',test,'--manifest',str(contract),'--out',str(evidence.root)]
    if test in ('L01','A01'):result=staged_suite(config,test,evidence)
    elif test=='L04':
        from .retrieval_trials import suite
        result=suite(config,evidence)
    elif test in ('L02','L03','L12'):
        from .live_trials import suite
        result=suite(config,test,evidence)
    elif test=='F01':
        from .capacity import suite
        result=suite(config,evidence)
    elif test in ('L05','L06','L08','A03'):
        from .behavior_trials import relationships,evolution,continuity,memory_ablation
        result={'L05':relationships,'L06':evolution,'L08':continuity,'A03':memory_ablation}[test](config,evidence)
    elif test=='L07':
        from .continuity_trial import suite
        result=suite(config,evidence)
    elif test=='F02':
        from .performance_trials import suite
        result=suite(config,evidence)
    elif test=='L10':
        from .parallel_trial import suite
        result=suite(config,evidence)
    elif test=='L09':
        from .matrix_trials import suite
        result=suite(config,evidence)
    elif test=='L11':
        from .fault_trials import suite
        result=suite(config,evidence)
    elif test=='A02':
        from .noise_trials import suite
        result=suite(config,evidence)
    elif test.startswith('E'):
        tests=sorted((ROOT/'tests').glob('test_engineering_*.py'))
        cmd=[sys.executable,'-m','pytest',*[str(p) for p in tests],'-k',test,'-q','--junitxml='+str(evidence.root/'junit.xml')]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        (evidence.root/'stdout.txt').write_bytes(p.stdout);(evidence.root/'stderr.txt').write_bytes(p.stderr)
        # Tests still carry documented partial clauses. A passing subset cannot
        # be promoted to contract PASS by the runner.
        result={'test_id':test,'status':'INCONCLUSIVE' if p.returncode==0 else 'NOT_RUN' if p.returncode==5 else 'FAIL','mode':'fake_lane_real_Mongo','attempts':1,'commands':[{'argv':cmd,'exit_code':p.returncode}],'limitations':['Contract coverage must be reviewed against all required clauses; passing pytest subset is not automatically full acceptance']}
    else:
        result={'test_id':test,'status':'NOT_RUN','mode':None,'attempts':0,'limitations':['Dedicated acceptance driver is not implemented yet']}
    result.update(experiment_id=manifest['experiment_id'],manifest_sha256=sha((evidence.root/'manifest.json').read_bytes()),executed_at=datetime.now(timezone.utc).isoformat())
    result.setdefault('commands',[]).append({'argv':command,'exit_code':1 if result['status']=='FAIL' else 0})
    write_json(evidence.root/'result.json',result)
    return result
